# Market Signal Lab

A small, serious quantitative-research platform: can measurable conditions in daily
market data be tied to better future returns — and can that be tested rigorously enough
to tell a real effect from noise and overfitting?

```
free market data ──► Dockerized ingestion ──► Parquet landing zone ──► Databricks lakehouse
                                                                        bronze → silver → gold (SQL)
                                                                                 │
                                                        hypothesis tests ◄───────┘
                                                        (decile spreads, Newey-West t, placebo)
                                                                 │
                                                        backtest ─► written report
```

The interesting part is the research process, not the stack. SQL, Docker and Databricks
are here because each solves a concrete problem in that process (see *Decisions*).
An effect counts only if it survives an untouched holdout period and realistic costs; a
hypothesis rejected for a valid reason is a successful outcome.

**Status — week 1 of 4 (2026-09-15):** ingestion is live. Silver/Gold SQL, the first
hypothesis test (12-1 momentum) and the backtest follow in weeks 2–4. See *Roadmap*.

## What exists today

| Piece | Where | State |
|---|---|---|
| Provider interface + Yahoo Finance provider | `src/msl/providers/` | ✅ tested |
| S&P 500 **point-in-time** membership from Wikipedia's change log (1976→) | `src/msl/universe/sp500.py` | ✅ tested |
| Append-only Parquet landing zone, Hive-partitioned by `provider` / `pull_id` | `src/msl/storage.py` | ✅ tested |
| Full + incremental ingestion with split-triggered full re-pull, per-ticker ingest log | `src/msl/ingest/run.py` | ✅ ran end to end |
| `msl` CLI, Docker image + compose (ingestion, JupyterLab research env) | `src/msl/cli.py`, `Dockerfile` | ✅ / image build in CI |
| GitHub Actions: ruff, pytest, Docker build | `.github/workflows/ci.yml` | ✅ |
| Bronze / Silver / Gold SQL on DuckDB **and** Databricks | `sql/` | week 2–3 |
| Hypothesis test, backtest, report | `src/msl/research/`, `reports/` | week 4 |

First full load (2026-09-15, `yfinance`, 2004-01-01 → today):

| | |
|---|---|
| Tickers that were S&P 500 members at some point since 2004 | **865** (503 today) |
| Tickers with price data | **679** |
| Tickers with **no** free data (delisted / renamed) | **186 (21 %)** — recorded per ticker in the ingest log |
| Rows | 3,239,861 daily bars, 541 splits, 36,065 dividends |
| Size | ~100 MB zstd Parquet; ~2.5 min wall-clock |

That 21 % is the survivorship bias this dataset still carries — see *Known limitations*.

## Quickstart

Local (Python 3.12 + [uv](https://docs.astral.sh/uv/)):

```bash
uv sync --all-groups
uv run pytest -q
uv run msl ingest all                      # S&P 500 universe + full price history (~3 min)
uv run msl ingest all --mode incremental   # later: only what is new
```

Docker (the same thing, reproducibly — `./data` is bind-mounted so Parquet lands on the host):

```bash
cp .env.example .env
docker compose run --rm ingestion ingest all
docker compose up research                 # JupyterLab + DuckDB on http://localhost:8888
```

Explore the landing zone with DuckDB — `sql/lessons/01_explore_raw.sql` has four guided
queries (`GROUP BY`, `JOIN`, CTE + `date_trunc`, a data-quality check).

## Layout

```
src/msl/
  config.py           settings from environment variables (MSL_DATA_DIR, MSL_DEFAULT_START)
  storage.py          Parquet landing zone: data/raw/<dataset>/provider=<p>/pull_id=<id>/
  providers/          MarketDataProvider contract + yfinance implementation
  universe/sp500.py   Wikipedia constituents + change log -> membership intervals
  ingest/run.py       full / incremental orchestration, ingest log
  cli.py              `msl ingest universe | prices | all`
sql/                  bronze / silver / gold, runnable on DuckDB and Databricks
tests/                unit tests, no network (synthetic frames, tmp_path)
docs/decisions/       ADRs — the "why" behind each engineering choice
docs/learning/        the learning track (this repo is also how its author learns SQL/Docker/Databricks)
reports/              hypothesis-test write-ups (week 4+)
```

## Decisions (short form — each links to an ADR)

1. **Provider interface; raw sources preserved as pulled** —
   [ADR-0001](docs/decisions/0001-provider-interface-and-raw-preservation.md).
   Swapping Yahoo for Tiingo/Stooq touches one file. The Wikipedia HTML is kept next to
   the parsed tables; on day one that is how a moved change-log table was diagnosed.
2. **Append-only pulls; "which row is current" is one window function in Silver** —
   [ADR-0002](docs/decisions/0002-append-only-pulls-dedup-in-silver.md).
   Idempotent, fully traceable, and the natural place for the first `ROW_NUMBER()`.
3. **Point-in-time S&P 500 membership** —
   [ADR-0003](docs/decisions/0003-sp500-point-in-time-membership.md).
   Membership bias handled; price bias measured and reported, not hidden.
4. **DuckDB locally, Databricks Free Edition as the lakehouse, one set of SQL** —
   [ADR-0004](docs/decisions/0004-duckdb-local-databricks-remote.md).
   Databricks is used for the medallion/Delta/Workflows pattern, **not for scale** —
   2.6 M rows do not need a cluster and this README will not pretend otherwise.

Research-design decisions fixed *before* looking at data (so they cannot be tuned to it):

- First hypothesis: **12-1 momentum → next 21 trading days** (Jegadeesh & Titman 1993),
  chosen because it is the most robust documented effect and therefore validates the
  pipeline. Second: **short-term reversal** (past 5 days → next 5), the one most likely
  to die after costs.
- "Outperform" = top decile minus bottom decile of the universe on each formation date
  (cancels the market); the backtest benchmark is SPY buy-and-hold.
- Statistics: mean and median spread, hit rate, **Newey-West t-stat with lag =
  horizon − 1** (overlapping forward returns inflate naïve t-stats), per-year stability,
  and a placebo test (signal shuffled within date).
- **Holdout 2023-01-01 → today is locked structurally**: Gold views exclude it by
  default; one flagged evaluation job may read it, once per hypothesis.

## Known limitations (read before believing any result)

- **Free daily data.** `yfinance` is an unofficial API that breaks a few times a year.
  Raw pulls are preserved so nothing is silently re-derived.
- **Survivorship bias, partially.** Membership is point-in-time; prices are not — 21 %
  of historical members have no free price history. Results are an *upper bound* for
  strategies that would have held the losers.
- **Adjusted prices are back-adjusted at pull time**, not point-in-time. Yahoo's
  `close` is split-adjusted, `adj_close` also dividend-adjusted. Fine for returns;
  wrong for "distance from a $-high" in raw dollars. Features use one series consistently
  and say which.
- **Sector is today's GICS sector**, not historical.
- **No intraday data**, so no intraday slippage model; costs are modelled per trade.

## Roadmap

| Week | Deliverable |
|---|---|
| 1 ✅ | Ingestion (this), Docker, CI. Databricks Free Edition workspace + Volume upload from the container. |
| 2 | Bronze + Silver in SQL on both engines: dedup by latest pull, types, trading-calendar alignment, adjustment factors, `silver.dq_results`. |
| 3 | Gold: returns 1/5/20/60/252 d, 12-1 momentum, rolling vol/volume, abnormal volume, distance from 52-w high, drawdown, cross-sectional deciles, forward returns; holdout gate; Databricks Workflow. |
| 4 | Momentum hypothesis test per the protocol above, basic Python backtest, `reports/2026-10-momentum.md`. |
| later | Short-term reversal · Italian universe (FTSE MIB, `.MI` tickers) · conditional/combined signals · walk-forward · realistic costs (Fineco, Italian FTT, capital gains) · crypto (`asset_class` is in the schema from day one) · Qlib only if experiment management becomes the bottleneck. |

## License

MIT.
