"""Append-only Parquet landing zone for raw pulls (the step before Bronze).

Layout — Hive-style so DuckDB and Spark expose the path segments as columns:

    data/raw/<dataset>/provider=<provider>/pull_id=<pull_id>/<name>.parquet

Rules (see docs/decisions/0002-append-only-pulls-dedup-in-silver.md):
  * every run gets a fresh ``pull_id`` and never overwrites an earlier pull;
  * ``provider`` and ``pull_id`` live only in the path, never inside the file, so that
    the partition columns and the file columns can never disagree;
  * "which row is current?" is answered downstream in Silver with a window function
    (latest ``pull_id`` wins per ticker+date), not by mutating files here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


def new_pull_id(now: datetime | None = None) -> str:
    """A sortable, filesystem-safe timestamp: 20260915T101800Z."""
    now = now or datetime.now(UTC)
    return now.strftime("%Y%m%dT%H%M%SZ")


def pull_dir(raw_dir: Path, dataset: str, provider: str, pull_id: str) -> Path:
    return raw_dir / dataset / f"provider={provider}" / f"pull_id={pull_id}"


def dataset_glob(raw_dir: Path, dataset: str) -> str:
    """Glob that DuckDB's read_parquet() understands, forward slashes on every OS."""
    return (raw_dir / dataset / "**" / "*.parquet").as_posix()


def has_data(raw_dir: Path, dataset: str) -> bool:
    return any((raw_dir / dataset).rglob("*.parquet"))


def write_parquet(
    df: pd.DataFrame,
    raw_dir: Path,
    dataset: str,
    provider: str,
    pull_id: str,
    name: str,
) -> Path:
    out_dir = pull_dir(raw_dir, dataset, provider, pull_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}.parquet"
    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, path, compression="zstd")
    return path


def write_text(
    text: str, raw_dir: Path, dataset: str, provider: str, pull_id: str, name: str
) -> Path:
    """Preserve a source document (e.g. the HTML page a table was parsed from) next to
    the parsed data, so a parsing bug can always be traced back to the original."""
    out_dir = pull_dir(raw_dir, dataset, provider, pull_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / name
    path.write_text(text, encoding="utf-8")
    return path


def read_latest_pull(raw_dir: Path, dataset: str) -> pd.DataFrame:
    """Rows from the most recent pull_id of a dataset (any provider)."""
    if not has_data(raw_dir, dataset):
        return pd.DataFrame()
    glob = dataset_glob(raw_dir, dataset)
    # QUALIFY + a window over the whole set rather than a scalar subquery: DuckDB 1.5
    # raises an internal error when an aggregate touches *only* hive-partition columns.
    return duckdb.sql(
        f"""
        SELECT * FROM read_parquet('{glob}', hive_partitioning = true)
        QUALIFY pull_id = max(pull_id) OVER ()
        """
    ).df()


def latest_price_dates(raw_dir: Path) -> pd.DataFrame:
    """Per ticker, the most recent date we already hold — the input to incremental mode."""
    if not has_data(raw_dir, "prices"):
        return pd.DataFrame(columns=["ticker", "last_date"])
    glob = dataset_glob(raw_dir, "prices")
    return duckdb.sql(
        f"""
        SELECT ticker, max(date) AS last_date
        FROM read_parquet('{glob}', hive_partitioning = true)
        GROUP BY ticker
        """
    ).df()
