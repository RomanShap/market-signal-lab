# Learning track

This repo is built in "Claude writes, Roman studies and re-explains" mode. The rule that
keeps that honest: **nothing ships until the person whose name is on the repo can explain
it.** Every `.sql` file and every non-trivial module gets an entry here, written by Roman,
using [TEMPLATE.md](TEMPLATE.md). Claude reviews the entry and asks follow-up questions;
the weekly drill (10 interview-style questions, answered from memory) is logged in the
vault, not here.

## Week 1 — Docker mental model + SQL basics (15–21 Sep 2026)

Read, in this order:

1. `src/msl/storage.py` — the Parquet layout and why `provider`/`pull_id` are only in
   the path. Then [ADR-0002](../decisions/0002-append-only-pulls-dedup-in-silver.md).
2. `src/msl/universe/sp500.py` — membership intervals. Then
   [ADR-0003](../decisions/0003-sp500-point-in-time-membership.md).
3. `sql/lessons/01_explore_raw.sql` — run it, change it, break it. Three queries:
   `GROUP BY`, a `JOIN` to the constituent table, a CTE with `date_trunc`.
4. `Dockerfile` + `docker-compose.yml` — image vs. container vs. volume; why the
   dependency layer is built before `COPY src`.

Entries due: `storage.md`, `sp500.md`, `01_explore_raw.md`, `docker.md`.

## How to run a lesson

```bash
uv run python -c "import duckdb; print(duckdb.sql(open('sql/lessons/01_explore_raw.sql').read().split(';')[0]).df())"
```

or, less clumsily, open a DuckDB shell on the data:

```bash
uv run python -c "import duckdb; duckdb.connect().sql(\"SELECT count(*) FROM read_parquet('data/raw/prices/**/*.parquet', hive_partitioning=true)\").show()"
```

The `research` Docker service (JupyterLab) is the comfortable option once Docker is
installed: `docker compose up research`, open http://localhost:8888, `import duckdb`.
