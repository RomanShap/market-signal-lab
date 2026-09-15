# sql/

All analytical SQL lives here and runs on **both** DuckDB (local, tests, CI) and Databricks
(Delta, Workflows) — see [ADR-0004](../docs/decisions/0004-duckdb-local-databricks-remote.md).

```
lessons/   guided queries for the learning track (week 1+)
bronze/    raw -> Delta as-is, plus ingestion metadata           (week 2)
silver/    dedup, types, calendar, adjustment factors, dq checks (week 2)
gold/      features, forward returns, ranks, holdout gate        (week 3)
```
