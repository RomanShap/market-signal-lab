"""Parquet landing zone: layout, partition columns, and latest-pull selection."""

from datetime import date, datetime

import pandas as pd

from msl.storage import (
    latest_price_dates,
    new_pull_id,
    read_latest_pull,
    write_parquet,
)


def _prices(ticker: str, dates: list[date]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ticker": ticker,
            "source_symbol": ticker,
            "date": dates,
            "open": 1.0,
            "high": 1.0,
            "low": 1.0,
            "close": 1.0,
            "adj_close": 1.0,
            "volume": pd.array([100] * len(dates), dtype="Int64"),
        }
    )


def test_pull_id_is_sortable_utc_timestamp():
    assert new_pull_id(datetime(2026, 9, 15, 10, 18, 0)) == "20260915T101800Z"


def test_layout_and_partition_columns(tmp_path):
    raw = tmp_path / "raw"
    path = write_parquet(_prices("AAA", [date(2024, 1, 2)]), raw, "prices", "yfinance", "p1", "AAA")
    assert path == raw / "prices" / "provider=yfinance" / "pull_id=p1" / "AAA.parquet"

    df = read_latest_pull(raw, "prices")
    assert df.loc[0, "provider"] == "yfinance" and df.loc[0, "pull_id"] == "p1"
    assert "provider" not in pd.read_parquet(path).columns  # only in the path, never inside


def test_latest_pull_and_latest_dates_across_pulls(tmp_path):
    raw = tmp_path / "raw"
    write_parquet(
        _prices("AAA", [date(2024, 1, 2), date(2024, 1, 3)]), raw, "prices", "yf", "p1", "AAA"
    )
    write_parquet(_prices("BBB", [date(2024, 1, 2)]), raw, "prices", "yf", "p1", "BBB")
    write_parquet(_prices("AAA", [date(2024, 1, 4)]), raw, "prices", "yf", "p2", "AAA")

    latest = read_latest_pull(raw, "prices")
    assert set(latest["pull_id"]) == {"p2"} and len(latest) == 1

    held = latest_price_dates(raw).set_index("ticker")["last_date"]
    assert pd.Timestamp(held["AAA"]).date() == date(2024, 1, 4)
    assert pd.Timestamp(held["BBB"]).date() == date(2024, 1, 2)


def test_empty_dataset_returns_empty_frames(tmp_path):
    raw = tmp_path / "raw"
    assert read_latest_pull(raw, "prices").empty
    assert list(latest_price_dates(raw).columns) == ["ticker", "last_date"]


def test_membership_helpers_accept_duckdb_datetime_columns(tmp_path):
    """Frames read back through DuckDB carry datetime64, not python dates."""
    from msl.universe.sp500 import members_on, tickers_active_since

    raw = tmp_path / "raw"
    m = pd.DataFrame(
        {
            "ticker": ["A", "B"],
            "start_date": [None, date(2020, 1, 1)],
            "end_date": [date(2010, 1, 1), None],
            "note": [None, None],
        }
    )
    write_parquet(m, raw, "reference/sp500_membership", "wikipedia", "p1", "membership")
    back = read_latest_pull(raw, "reference/sp500_membership")
    assert str(back["end_date"].dtype).startswith("datetime64")
    assert members_on(back, date(2005, 1, 1)) == {"A"}
    assert members_on(back, date(2021, 1, 1)) == {"B"}
    assert tickers_active_since(back, date(2004, 1, 1)) == ["A", "B"]
    assert tickers_active_since(back, date(2011, 1, 1)) == ["B"]
