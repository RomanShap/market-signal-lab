"""Yahoo Finance via the ``yfinance`` package — the free, unofficial MVP provider.

Known properties of this source (documented, not hidden):
  * ``close`` is already *split*-adjusted by Yahoo; ``adj_close`` is additionally
    *dividend*-adjusted (total-return series). Neither is a true raw print.
  * Because Yahoo back-adjusts the whole history whenever a split happens, an
    incremental pull that only appends new dates would leave older rows on the wrong
    scale. The ingestion layer therefore re-pulls the full history of any ticker that
    shows a new split (see ``msl.ingest.run``).
  * Delisted tickers mostly return nothing. We record that as a failure in the ingest
    log instead of silently dropping the ticker — it is the survivorship-bias evidence.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable
from datetime import date
from pathlib import Path

import pandas as pd

from msl.providers.base import (
    ACTION_COLUMNS,
    PRICE_COLUMNS,
    FetchResult,
    empty_actions,
    empty_prices,
)

log = logging.getLogger(__name__)


def chunked(items: list[str], size: int) -> Iterable[list[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def flatten_download(
    raw: pd.DataFrame | None,
    tickers: list[str],
    to_symbol: Callable[[str], str],
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """Turn ``yf.download(group_by="ticker")`` output into long prices + actions.

    Returns (prices, actions, missing_tickers). Pure function — unit-tested without
    network access.
    """
    if raw is None or raw.empty:
        return empty_prices(), empty_actions(), list(tickers)

    # A single symbol may come back with flat columns; normalise to the 2-level shape.
    if not isinstance(raw.columns, pd.MultiIndex):
        raw = raw.copy()
        raw.columns = pd.MultiIndex.from_product([[to_symbol(tickers[0])], raw.columns])

    available = set(raw.columns.get_level_values(0))
    price_frames: list[pd.DataFrame] = []
    action_frames: list[pd.DataFrame] = []
    missing: list[str] = []

    for ticker in tickers:
        symbol = to_symbol(ticker)
        if symbol not in available:
            missing.append(ticker)
            continue
        sub = raw[symbol].copy()
        price_cols = [c for c in ("Open", "High", "Low", "Close") if c in sub.columns]
        sub = sub.dropna(subset=price_cols, how="all")
        if sub.empty:
            missing.append(ticker)
            continue

        sub.index = pd.to_datetime(sub.index).tz_localize(None)
        sub.index.name = "date"
        sub = sub.reset_index()

        prices = pd.DataFrame(
            {
                "ticker": ticker,
                "source_symbol": symbol,
                "date": sub["date"].dt.date,
                "open": sub["Open"].astype("float64"),
                "high": sub["High"].astype("float64"),
                "low": sub["Low"].astype("float64"),
                "close": sub["Close"].astype("float64"),
                # auto_adjust=False gives "Adj Close"; fall back to Close if a future
                # yfinance version drops it rather than crash the whole pull.
                "adj_close": sub.get("Adj Close", sub["Close"]).astype("float64"),
                "volume": sub["Volume"].round().astype("Int64"),
            }
        )
        price_frames.append(prices[PRICE_COLUMNS])

        has_div = "Dividends" in sub.columns
        has_split = "Stock Splits" in sub.columns
        dividends = sub[sub["Dividends"] > 0] if has_div else sub.iloc[0:0]
        splits = sub[sub["Stock Splits"] != 0] if has_split else sub.iloc[0:0]
        if not dividends.empty:
            action_frames.append(
                pd.DataFrame(
                    {
                        "ticker": ticker,
                        "source_symbol": symbol,
                        "date": dividends["date"].dt.date,
                        "action_type": "dividend",
                        "value": dividends["Dividends"].astype("float64"),
                    }
                )
            )
        if not splits.empty:
            action_frames.append(
                pd.DataFrame(
                    {
                        "ticker": ticker,
                        "source_symbol": symbol,
                        "date": splits["date"].dt.date,
                        "action_type": "split",
                        "value": splits["Stock Splits"].astype("float64"),
                    }
                )
            )

    prices_out = pd.concat(price_frames, ignore_index=True) if price_frames else empty_prices()
    actions_out = (
        pd.concat(action_frames, ignore_index=True)[ACTION_COLUMNS]
        if action_frames
        else empty_actions()
    )
    return prices_out, actions_out, missing


class YFinanceProvider:
    name = "yfinance"

    def __init__(
        self,
        batch_size: int = 100,
        max_retries: int = 3,
        pause_s: float = 1.0,
        cache_dir: Path | None = None,
    ):
        self.batch_size = batch_size
        self.max_retries = max_retries
        self.pause_s = pause_s
        self.cache_dir = cache_dir

    @staticmethod
    def to_source_symbol(ticker: str) -> str:
        # Wikipedia/S&P spell share classes with a dot (BRK.B); Yahoo uses a dash (BRK-B).
        return ticker.replace(".", "-")

    def _download(self, symbols: list[str], start: date, end: date | None) -> pd.DataFrame:
        import yfinance as yf  # imported lazily so unit tests never need it

        if self.cache_dir is not None:
            # yfinance keeps a small sqlite cache. Its default location under
            # %LOCALAPPDATA% was locked/unwritable on a Windows machine, which silently
            # failed one ticker per batch — so the cache lives next to our data instead.
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            yf.set_tz_cache_location(str(self.cache_dir))

        return yf.download(
            symbols,
            start=start.isoformat(),
            end=end.isoformat() if end else None,
            auto_adjust=False,  # keep Close *and* Adj Close
            actions=True,  # add Dividends and Stock Splits columns
            group_by="ticker",
            threads=True,
            progress=False,
        )

    def _download_with_retry(
        self, symbols: list[str], start: date, end: date | None
    ) -> pd.DataFrame | None:
        for attempt in range(1, self.max_retries + 1):
            try:
                return self._download(symbols, start, end)
            except Exception as exc:  # noqa: BLE001 - provider errors are heterogeneous
                wait = self.pause_s * 2 ** (attempt - 1)
                log.warning(
                    "yfinance batch failed (attempt %d/%d): %s — retrying in %.0fs",
                    attempt,
                    self.max_retries,
                    exc,
                    wait,
                )
                time.sleep(wait)
        return None

    def fetch_daily(self, tickers: list[str], start: date, end: date | None = None) -> FetchResult:
        prices_parts: list[pd.DataFrame] = []
        actions_parts: list[pd.DataFrame] = []
        failures: dict[str, str] = {}

        for batch in chunked(list(tickers), self.batch_size):
            symbols = [self.to_source_symbol(t) for t in batch]
            raw = self._download_with_retry(symbols, start, end)
            if raw is None:
                failures.update({t: "download failed after retries" for t in batch})
                continue
            prices, actions, missing = flatten_download(raw, batch, self.to_source_symbol)
            prices_parts.append(prices)
            actions_parts.append(actions)
            failures.update({t: "no data returned (delisted or unknown symbol)" for t in missing})
            log.info(
                "yfinance batch: %d requested, %d with data, %d missing",
                len(batch),
                len(batch) - len(missing),
                len(missing),
            )
            time.sleep(self.pause_s)

        return FetchResult(
            prices=pd.concat(prices_parts, ignore_index=True) if prices_parts else empty_prices(),
            actions=(
                pd.concat(actions_parts, ignore_index=True) if actions_parts else empty_actions()
            ),
            failures=failures,
        )
