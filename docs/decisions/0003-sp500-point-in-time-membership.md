# ADR-0003 — S&P 500 universe with point-in-time membership

**Status:** accepted · 2026-09-15

## Context

The obvious universe — "the S&P 500" — is a moving target. Using *today's* member list
for a 20-year backtest quietly selects the companies that survived and grew into the
index (survivorship bias) and drops the ones that were in it and collapsed.

## Decision

- Fetch both Wikipedia pages: the current constituents and the additions/removals log
  (*Historical components of the S&P 500*, 407 rows from 1976 to 2026-08-18 at first
  pull). Tables are located by **content** (header names), never by position.
- Replay the log into membership intervals per ticker — `start_date` inclusive,
  `end_date` exclusive, `NULL` meaning "before the log begins" / "still a member".
  Uncertain intervals carry a `note` instead of being dropped (273 of 906 at first pull:
  252 pre-log members, 19 probable ticker renames, 2 unlogged re-additions).
- Price ingestion pulls **every ticker that was a member at any time since the start
  date** — 865 tickers for 2004→2026, versus 503 today.

## Consequences

- Membership bias is handled. **Price bias is not**: roughly one in five historical
  members returns no data from Yahoo (delisted). Those failures are recorded per ticker
  in the ingest log so the gap is measurable and reported, not silent.
- Results are therefore an *upper bound* for any strategy that would have held the
  losers. The README states this plainly.
- Sector (`gics_sector`) is today's classification, not historical. Fine for a
  "does the effect differ by sector" cut; not fine for a sector-rotation strategy.
- Two log quirks (`UA` 2016, `IR` 2020: "added while already a member") are ticker
  re-use, logged as warnings and ignored.
