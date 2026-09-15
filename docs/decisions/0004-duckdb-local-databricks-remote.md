# ADR-0004 — DuckDB locally, Databricks Free Edition as the lakehouse, one set of SQL

**Status:** accepted · 2026-09-15

## Context

The full dataset is ~2.6 M rows. Databricks is not needed for scale; it is used because
the medallion / Delta / Workflows pattern is what the target jobs run, and because the
Free Edition costs nothing. But a serverless workspace is a slow place to *learn* SQL, and
a repo whose tests need cloud credentials cannot run in CI or on a stranger's laptop.

## Decision

- **Databricks Free Edition** is the system of record: Unity Catalog, Delta tables,
  `bronze` / `silver` / `gold` schemas, a Workflow chaining the layers.
- **DuckDB** runs the *same* `sql/` files over the same Parquet locally: instant feedback,
  unit tests on a 5-ticker fixture, CI without secrets.
- SQL is written once in the portable subset both engines share (CTEs, window functions,
  `QUALIFY`, `date_trunc`, `NTILE`, `PERCENT_RANK`, …). Engine-specific statements
  (Delta `MERGE INTO`, `OPTIMIZE`, `COPY INTO`) live in clearly named files and are the
  only place the two paths diverge.
- Data reaches Databricks by **uploading the raw Parquet tree to a Unity Catalog Volume**
  from the ingestion container. The auth mechanism from a container on Free Edition is
  the one unverified assumption; fallbacks are the workspace UI upload, then running the
  ingestion notebook inside Databricks.

## Consequences

- Two engines, one SQL — the discipline of writing portable SQL is itself a skill worth
  showing, and a divergence is caught by the test suite rather than in an interview.
- The README says out loud that Databricks is used for the pattern, not for scale.
- A DuckDB 1.5 bug already shaped one query: an aggregate over *only* hive-partition
  columns raises an internal error, so `read_latest_pull` uses
  `QUALIFY pull_id = max(pull_id) OVER ()` instead of a scalar subquery.
