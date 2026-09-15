"""Ingestion orchestration: universe -> prices + corporate actions -> ingest log.

Two modes:
  * ``full``        — pull every ticker from ``start``. Used for the first load and after
                      provider changes.
  * ``incremental`` — pull only the last few days per ticker (with a small overlap so a
                      late-corrected bar is captured; Silver keeps the latest pull).
                      Any ticker that shows a *new split* in that window is re-pulled in
                      full, because Yahoo rescales its entire history at a split.

Every run is one ``pull_id``; nothing is ever overwritten (ADR-0002).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

import pandas as pd

from msl.config import Settings
from msl.providers import get_provider
from msl.storage import (
    latest_price_dates,
    new_pull_id,
    read_latest_pull,
    write_parquet,
    write_text,
)
from msl.universe import sp500

log = logging.getLogger(__name__)

INCREMENTAL_OVERLAP_DAYS = 7
UNIVERSE_PROVIDER = "wikipedia"
LOG_COLUMNS = ["dataset", "ticker", "status", "rows", "first_date", "last_date", "message"]


@dataclass
class IngestLog:
    pull_id: str
    provider: str
    entries: list[dict] = field(default_factory=list)

    def add(
        self,
        dataset: str,
        ticker: str | None,
        status: str,
        rows: int = 0,
        first_date: date | None = None,
        last_date: date | None = None,
        message: str | None = None,
    ) -> None:
        self.entries.append(
            {
                "dataset": dataset,
                "ticker": ticker,
                "status": status,
                "rows": rows,
                "first_date": first_date,
                "last_date": last_date,
                "message": message,
            }
        )

    def flush(self, settings: Settings) -> None:
        df = pd.DataFrame(self.entries, columns=LOG_COLUMNS)
        df["pulled_at"] = datetime.now(UTC)
        write_parquet(df, settings.raw_dir, "_ingest_log", self.provider, self.pull_id, "log")
        counts = df["status"].value_counts().to_dict()
        log.info("ingest log written for pull %s: %s", self.pull_id, counts)


# --------------------------------------------------------------------------- universe


def ingest_universe(settings: Settings, pull_id: str | None = None) -> pd.DataFrame:
    """Fetch the two Wikipedia pages, keep their HTML, write constituents + change log +
    reconstructed membership intervals. Returns the membership frame."""
    pull_id = pull_id or new_pull_id()
    ilog = IngestLog(pull_id, UNIVERSE_PROVIDER)
    pulled_at = datetime.now(UTC)

    pages = {
        "sp500_constituents_page": sp500.CONSTITUENTS_URL,
        "sp500_changes_page": sp500.CHANGES_URL,
    }
    html: dict[str, str] = {}
    for name, url in pages.items():
        html[name] = sp500.fetch_html(url)
        # Keep the source document next to what is parsed out of it (ADR-0001), so a
        # parser bug — or Wikipedia restructuring a page — can always be traced.
        write_text(
            html[name],
            settings.raw_dir,
            f"reference/{name}",
            UNIVERSE_PROVIDER,
            pull_id,
            "page.html",
        )

    constituents = sp500.parse_constituents(html["sp500_constituents_page"])
    changes = sp500.parse_changes(html["sp500_changes_page"])
    membership = sp500.build_membership(set(constituents["ticker"].dropna()), changes)
    for df in (constituents, changes, membership):
        df["snapshot_date"] = pulled_at.date()
        df["pulled_at"] = pulled_at

    write_parquet(
        constituents,
        settings.raw_dir,
        "reference/sp500_constituents",
        UNIVERSE_PROVIDER,
        pull_id,
        "constituents",
    )
    write_parquet(
        changes, settings.raw_dir, "reference/sp500_changes", UNIVERSE_PROVIDER, pull_id, "changes"
    )
    write_parquet(
        membership,
        settings.raw_dir,
        "reference/sp500_membership",
        UNIVERSE_PROVIDER,
        pull_id,
        "membership",
    )

    ilog.add("reference/sp500_constituents", None, "ok", len(constituents))
    ilog.add(
        "reference/sp500_changes",
        None,
        "ok",
        len(changes),
        changes["date"].min(),
        changes["date"].max(),
    )
    uncertain = int(membership["note"].notna().sum())
    ilog.add(
        "reference/sp500_membership",
        None,
        "ok",
        len(membership),
        message=f"{membership['ticker'].nunique()} tickers, {uncertain} uncertain intervals",
    )
    ilog.flush(settings)
    log.info(
        "universe: %d current constituents, %d change rows (%s → %s), %d membership intervals",
        len(constituents),
        len(changes),
        changes["date"].min(),
        changes["date"].max(),
        len(membership),
    )
    return membership


def universe_tickers(settings: Settings, since: date) -> list[str]:
    membership = read_latest_pull(settings.raw_dir, "reference/sp500_membership")
    if membership.empty:
        raise RuntimeError("no S&P 500 membership found — run `msl ingest universe` first")
    return sp500.tickers_active_since(membership, since)


# --------------------------------------------------------------------------- prices


def _plan_incremental(
    settings: Settings, tickers: list[str], start: date, today: date
) -> dict[date, list[str]]:
    """Group tickers by the start date they need, so each group is one provider call."""
    held = latest_price_dates(settings.raw_dir)
    last_by_ticker = {
        r.ticker: pd.Timestamp(r.last_date).date() for r in held.itertuples(index=False)
    }
    plan: dict[date, list[str]] = {}
    for t in tickers:
        last = last_by_ticker.get(t)
        if last is None:
            plan.setdefault(start, []).append(t)
        elif last >= today:
            continue  # nothing new can exist yet
        else:
            plan.setdefault(last - timedelta(days=INCREMENTAL_OVERLAP_DAYS), []).append(t)
    return plan


def ingest_prices(
    settings: Settings,
    tickers: list[str],
    start: date,
    end: date | None = None,
    mode: str = "full",
    provider_name: str = "yfinance",
    pull_id: str | None = None,
) -> IngestLog:
    provider = get_provider(provider_name, cache_dir=settings.data_dir / ".cache")
    pull_id = pull_id or new_pull_id()
    ilog = IngestLog(pull_id, provider.name)
    today = date.today()

    if mode == "full":
        plan = {start: list(tickers)}
    elif mode == "incremental":
        plan = _plan_incremental(settings, tickers, start, today)
    else:
        raise ValueError(f"mode must be 'full' or 'incremental', got {mode!r}")

    if not plan:
        log.info("incremental: every ticker is already up to date")
        ilog.flush(settings)
        return ilog

    for batch_start, batch in sorted(plan.items()):
        log.info("pulling %d tickers from %s (mode=%s)", len(batch), batch_start, mode)
        result = provider.fetch_daily(batch, batch_start, end)
        _write_result(settings, provider.name, pull_id, ilog, result, batch, batch_start)

        if mode == "incremental" and not result.actions.empty:
            # Yahoo back-adjusts the whole history at a split -> re-pull those in full.
            new_splits = result.actions[
                (result.actions["action_type"] == "split") & (result.actions["date"] >= batch_start)
            ]
            resplit = sorted(set(new_splits["ticker"]))
            if resplit:
                log.info("new split(s) for %s — re-pulling full history", resplit)
                full = provider.fetch_daily(resplit, start, end)
                _write_result(
                    settings, provider.name, pull_id, ilog, full, resplit, start, suffix="__full"
                )

    ilog.flush(settings)
    return ilog


def _write_result(
    settings, provider_name, pull_id, ilog, result, requested, batch_start, suffix=""
):
    pulled_at = datetime.now(UTC)
    for ticker in requested:
        if ticker in result.failures:
            ilog.add("prices", ticker, "error", message=result.failures[ticker])
            continue
        p = result.prices[result.prices["ticker"] == ticker]
        if p.empty:
            ilog.add("prices", ticker, "empty", message=f"no rows since {batch_start}")
            continue
        p = p.assign(pulled_at=pulled_at)
        write_parquet(p, settings.raw_dir, "prices", provider_name, pull_id, f"{ticker}{suffix}")
        ilog.add("prices", ticker, "ok", len(p), p["date"].min(), p["date"].max())

        a = result.actions[result.actions["ticker"] == ticker]
        if not a.empty:
            a = a.assign(pulled_at=pulled_at)
            write_parquet(
                a,
                settings.raw_dir,
                "corporate_actions",
                provider_name,
                pull_id,
                f"{ticker}{suffix}",
            )
            ilog.add("corporate_actions", ticker, "ok", len(a), a["date"].min(), a["date"].max())


# --------------------------------------------------------------------------- all


def ingest_all(
    settings: Settings,
    start: date,
    end: date | None,
    mode: str,
    provider_name: str,
    tickers: list[str] | None = None,
) -> None:
    pull_id = new_pull_id()
    if tickers is None:
        ingest_universe(settings, pull_id)
        tickers = universe_tickers(settings, since=start)
        log.info("%d tickers were S&P 500 members at some point since %s", len(tickers), start)
    ingest_prices(settings, tickers, start, end, mode, provider_name, pull_id)
