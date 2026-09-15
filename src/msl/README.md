# `msl` — the package behind the `msl` command

`msl` = *market-signal-lab*. This folder is the whole program. `uv run msl …` starts it:
`pyproject.toml` declares `msl = "msl.cli:main"`, i.e. "the command `msl` runs the
function `main()` in `cli.py`". Inside Docker the same entry point is the container's
`ENTRYPOINT`, so `docker compose run --rm ingestion …` and `uv run msl …` are the same
program started two ways.

## Reading order

| File | What it does | Read it when |
|---|---|---|
| `cli.py` | Parses the words you type (`ingest prices --tickers AAPL`) and calls the right function. Start here. | first |
| `config.py` | Settings from environment variables; reads `.env` into `os.environ` at start-up. | you wonder where the token/paths come from |
| `storage.py` | Writes/reads the raw Parquet landing zone `data/raw/<dataset>/provider=…/pull_id=…/`. | before the Silver SQL (week 2) |
| `providers/base.py` | The contract every data source must satisfy (`fetch_daily`). | you want to add a new data source |
| `providers/yfinance_provider.py` | Yahoo Finance implementation of that contract. | a pull fails or looks wrong |
| `universe/sp500.py` | Wikipedia constituents + change log → point-in-time membership intervals. | with ADR-0003 |
| `ingest/run.py` | Orchestration: universe → prices → corporate actions → ingest log; full and incremental modes. | you want to know what `ingest all` does step by step |
| `lakehouse/upload.py` | Mirrors `data/raw` into a Databricks Unity Catalog Volume (the courier). | with ADR-0004 |

## How a command flows

```
uv run msl lakehouse check
  └─ cli.py: main()                 parse "lakehouse check"
       └─ config.py: load_settings()   read .env -> os.environ
       └─ lakehouse/upload.py: connect()   os.environ["DATABRICKS_TOKEN"] -> WorkspaceClient
            └─ Databricks SDK              adds "Authorization: Bearer <token>" to every request
                 └─ https://<workspace>/api/2.0/preview/scim/v2/Me   -> "you are shapo.roman.96"
```

```
uv run msl ingest all
  └─ cli.py: main()
       └─ ingest/run.py: ingest_all()
            ├─ ingest_universe()   universe/sp500.py  -> data/raw/reference/…
            └─ ingest_prices()     providers/yfinance_provider.py -> data/raw/prices/… + corporate_actions/…
                                   storage.py writes every file; IngestLog records ok/error per ticker
```

Tests for each module live in `tests/` with the same names.
