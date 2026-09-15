# ADR-0002 — Append-only pulls; "which row is current" is decided in Silver

**Status:** accepted · 2026-09-15

## Context

Daily bars get corrected after the fact, Yahoo rescales a ticker's entire history when
it splits, and an unattended job can crash halfway. An ingestion layer that *updates
files in place* has to get all of that right at write time, in Python, with no audit
trail.

## Decision

- Every run gets a fresh `pull_id` (`20260915T104222Z`) and writes under
  `data/raw/<dataset>/provider=<p>/pull_id=<id>/<ticker>.parquet`. Nothing is ever
  overwritten or deleted by ingestion.
- `provider` and `pull_id` exist **only in the path** (Hive partitioning). Putting them
  inside the file too would let the two disagree.
- Incremental mode re-pulls the last 7 days per ticker (overlap on purpose) and re-pulls
  the *full* history of any ticker with a new split.
- Silver resolves duplicates with one window function — the latest `pull_id` wins per
  `(ticker, date)`:

  ```sql
  SELECT * FROM bronze.market_prices
  QUALIFY row_number() OVER (PARTITION BY ticker, date ORDER BY pull_id DESC) = 1
  ```

## Consequences

- Idempotent by construction: rerunning a failed job just adds another pull.
- Full lineage: any Silver row can be traced to the pull that produced it.
- Storage grows with every pull (about 2.6 M rows per full pull, a few tens of MB
  zstd-compressed) — acceptable; a compaction job is a later concern, not a design one.
- The same dedup rule is the first real window function in the learning track.
