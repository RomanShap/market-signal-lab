"""S&P 500 universe with *point-in-time* membership reconstructed from Wikipedia.

Why: the list of *current* S&P 500 constituents is survivorship-biased by construction —
companies that collapsed were removed, companies that boomed were added. Testing a signal
only on today's members quietly conditions on "survived until 2026".

Wikipedia keeps the current constituents on one page and the additions/removals log on a
second one ("Historical components of the S&P 500", back to 1976; until 2026 the log was
a section of the first page, which is why both pages are fetched and preserved as-is).
Replaying the changes turns the snapshot into membership *intervals* per ticker:

    ticker | start_date (inclusive, NULL = before the change log begins)
           | end_date   (exclusive,  NULL = still a member at the snapshot date)
           | note       (NULL, or why this interval is uncertain)

What this fixes: membership bias. What it does NOT fix: price bias — free providers
rarely serve prices for delisted tickers, so many historical members will fail to
download. That failure count is reported, not hidden (see the ingest log).

Caveats we accept and document: the change log is known to be incomplete before ~2000
and occasionally lists ticker renames as remove+add; the current-constituent table gives
today's sector, not the historical one.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import date
from io import StringIO

import pandas as pd
import requests

log = logging.getLogger(__name__)

CONSTITUENTS_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
CHANGES_URL = "https://en.wikipedia.org/wiki/Historical_components_of_the_S%26P_500"
USER_AGENT = "market-signal-lab/0.1 (open-source research project; github.com/RomanShap)"

CONSTITUENT_COLUMNS = {
    "symbol": "ticker",
    "security": "security",
    "gics_sector": "gics_sector",
    "gics_sub_industry": "gics_sub_industry",
    "headquarters_location": "headquarters",
    "date_added": "date_added",
    "cik": "cik",
    "founded": "founded",
}


def fetch_html(url: str, timeout: int = 30) -> str:
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def _snake(name: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def normalize_ticker(value: object) -> str | None:
    """'BRK.B[1]' -> 'BRK.B'; blanks and NaN -> None. Canonical form keeps the dot."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = re.sub(r"\[.*?\]", "", str(value)).strip().upper()
    return text or None


def _tables(html: str) -> list[pd.DataFrame]:
    return pd.read_html(StringIO(html))


def parse_constituents(html: str) -> pd.DataFrame:
    """The current-constituent table, found by *content* (it has Symbol + Security
    columns), never by position — Wikipedia adds and removes navboxes without notice."""
    for table in _tables(html):
        if isinstance(table.columns, pd.MultiIndex):
            continue
        cols = {_snake(c) for c in table.columns}
        if {"symbol", "security"} <= cols:
            constituents = table.copy()
            constituents.columns = [_snake(c) for c in constituents.columns]
            missing = [c for c in CONSTITUENT_COLUMNS if c not in constituents.columns]
            if missing:
                raise ValueError(f"constituent table lacks {missing}: {list(constituents)}")
            constituents = constituents.rename(columns=CONSTITUENT_COLUMNS)[
                list(CONSTITUENT_COLUMNS.values())
            ]
            constituents["ticker"] = constituents["ticker"].map(normalize_ticker)
            for col in ("cik", "founded", "date_added"):
                constituents[col] = constituents[col].astype("string")
            return constituents.reset_index(drop=True)
    raise ValueError("no constituent table (Symbol + Security columns) found on the page")


def parse_changes(html: str) -> pd.DataFrame:
    """The additions/removals log: the table whose two-level header carries
    (Added, Ticker) and (Removed, Ticker). The date column was called "Date" until
    2026 and "Effective Date" since — matched by substring."""
    for table in _tables(html):
        if not isinstance(table.columns, pd.MultiIndex):
            continue
        pairs = {(_snake(a), _snake(b)) for a, b in table.columns}
        if ("added", "ticker") not in pairs or ("removed", "ticker") not in pairs:
            continue
        changes = table.copy()
        changes.columns = [
            _snake(a) if _snake(a) == _snake(b) else f"{_snake(a)}_{_snake(b)}"
            for a, b in changes.columns
        ]
        date_col = next(c for c in changes.columns if "date" in c)
        changes = changes.rename(columns={date_col: "date"})
        if "reason" not in changes.columns:
            changes["reason"] = pd.NA
        changes["date"] = pd.to_datetime(changes["date"], errors="coerce").dt.date
        for col in ("added_ticker", "removed_ticker"):
            changes[col] = changes[col].map(normalize_ticker)
        keep = ["date", "added_ticker", "added_security", "removed_ticker", "removed_security"]
        changes = changes[[*keep, "reason"]]
        bad = int(changes["date"].isna().sum())
        if bad:
            log.warning("dropping %d change rows with unparseable dates", bad)
            changes = changes[changes["date"].notna()]
        return changes.reset_index(drop=True)
    raise ValueError("no change-log table (Added/Removed Ticker header) found on the page")


def build_membership(current_tickers: set[str], changes: pd.DataFrame) -> pd.DataFrame:
    """Replay the change log forward in time into membership intervals per ticker."""
    events: dict[str, list[tuple[date, str]]] = defaultdict(list)
    for row in changes.itertuples(index=False):
        # pandas stores a missing cell as NaN, which is truthy — go through the
        # normaliser so blanks, NaN and footnotes all collapse to None.
        removed, added = normalize_ticker(row.removed_ticker), normalize_ticker(row.added_ticker)
        if removed:
            events[removed].append((row.date, "remove"))
        if added:
            events[added].append((row.date, "add"))

    rows: list[dict] = []

    def emit(ticker: str, start: date | None, end: date | None, note: str | None) -> None:
        rows.append({"ticker": ticker, "start_date": start, "end_date": end, "note": note})

    for ticker, evs in events.items():
        # Same-day remove+add (a ticker swap) must be processed as remove first.
        evs.sort(key=lambda e: (e[0], 0 if e[1] == "remove" else 1))
        member, start = False, None
        for when, kind in evs:
            if kind == "add":
                if member:
                    log.warning("%s: added on %s while already a member — ignoring", ticker, when)
                    continue
                member, start = True, when
            else:
                if member:
                    emit(ticker, start, when, None)
                else:
                    emit(ticker, None, when, "member before the change log begins")
                member, start = False, None
        if member:
            if ticker in current_tickers:
                emit(ticker, start, None, None)
            else:
                emit(
                    ticker,
                    start,
                    None,
                    "added, never removed, yet not in the current list — likely a ticker "
                    "rename; end date unknown",
                )
        elif ticker in current_tickers:
            emit(
                ticker,
                None,
                None,
                "in the current list but the last logged event is a removal — re-addition "
                "not logged; start date unknown",
            )

    for ticker in sorted(current_tickers - set(events)):
        emit(ticker, None, None, None)  # member for the whole logged history

    out = pd.DataFrame(rows, columns=["ticker", "start_date", "end_date", "note"])
    return out.sort_values(["ticker", "start_date"], na_position="first").reset_index(drop=True)


def _as_ts(series: pd.Series) -> pd.Series:
    # Fresh frames hold python dates; frames read back through DuckDB hold datetime64.
    # Normalise so both compare cleanly against a pd.Timestamp; None/NaN -> NaT.
    return pd.to_datetime(series, errors="coerce")


def members_on(membership: pd.DataFrame, on: date) -> set[str]:
    """Tickers that were members on a given date (start inclusive, end exclusive)."""
    when = pd.Timestamp(on)
    starts, ends = _as_ts(membership["start_date"]), _as_ts(membership["end_date"])
    ok = (starts.isna() | (starts <= when)) & (ends.isna() | (ends > when))
    return set(membership.loc[ok, "ticker"])


def tickers_active_since(membership: pd.DataFrame, since: date) -> list[str]:
    """Every ticker that was a member at any point on or after ``since``."""
    ends = _as_ts(membership["end_date"])
    active = ends.isna() | (ends > pd.Timestamp(since))
    return sorted(set(membership.loc[active, "ticker"]))
