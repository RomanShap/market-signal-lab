"""The yfinance flattening logic, exercised on a hand-built frame — no network."""

from datetime import date

import numpy as np
import pandas as pd

from msl.providers.base import ACTION_COLUMNS, PRICE_COLUMNS
from msl.providers.yfinance_provider import YFinanceProvider, flatten_download

FIELDS = ["Open", "High", "Low", "Close", "Adj Close", "Volume", "Dividends", "Stock Splits"]


def _raw(symbols: list[str]) -> pd.DataFrame:
    """Mimic yf.download(group_by='ticker', auto_adjust=False, actions=True)."""
    idx = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    cols = pd.MultiIndex.from_product([symbols, FIELDS])
    df = pd.DataFrame(index=idx, columns=cols, dtype="float64")
    for s in symbols:
        df[(s, "Open")] = [10.0, 11.0, 12.0]
        df[(s, "High")] = [11.0, 12.0, 13.0]
        df[(s, "Low")] = [9.0, 10.0, 11.0]
        df[(s, "Close")] = [10.5, 11.5, 12.5]
        df[(s, "Adj Close")] = [10.4, 11.4, 12.5]
        df[(s, "Volume")] = [1000.0, 2000.0, 3000.0]
        df[(s, "Dividends")] = [0.0, 0.0, 0.0]
        df[(s, "Stock Splits")] = [0.0, 0.0, 0.0]
    return df


def test_flatten_maps_symbols_back_to_canonical_tickers():
    raw = _raw(["AAA", "BRK-B"])
    raw[("AAA", "Dividends")] = [0.0, 0.25, 0.0]
    raw[("BRK-B", "Stock Splits")] = [0.0, 0.0, 2.0]

    prices, actions, missing = flatten_download(
        raw, ["AAA", "BRK.B", "MISSING"], YFinanceProvider.to_source_symbol
    )

    assert missing == ["MISSING"]
    assert list(prices.columns) == PRICE_COLUMNS
    assert set(prices["ticker"]) == {"AAA", "BRK.B"}
    assert set(prices["source_symbol"]) == {"AAA", "BRK-B"}
    assert len(prices) == 6
    assert prices["date"].iloc[0] == date(2024, 1, 2)
    assert str(prices["volume"].dtype) == "Int64"

    assert list(actions.columns) == ACTION_COLUMNS
    recs = {(r.ticker, r.action_type, r.value) for r in actions.itertuples(index=False)}
    assert recs == {("AAA", "dividend", 0.25), ("BRK.B", "split", 2.0)}


def test_all_nan_rows_are_dropped_and_ticker_reported_missing():
    raw = _raw(["AAA", "DEAD"])
    for f in FIELDS:
        raw[("DEAD", f)] = np.nan  # yfinance pads unknown symbols with NaN columns
    prices, actions, missing = flatten_download(raw, ["AAA", "DEAD"], lambda t: t)
    assert missing == ["DEAD"]
    assert set(prices["ticker"]) == {"AAA"}
    assert actions.empty


def test_single_symbol_flat_columns_are_handled():
    raw = _raw(["AAA"])["AAA"]  # what a one-ticker download can look like
    prices, _, missing = flatten_download(raw, ["AAA"], lambda t: t)
    assert missing == []
    assert len(prices) == 3


def test_empty_download_marks_everything_missing():
    prices, actions, missing = flatten_download(pd.DataFrame(), ["A", "B"], lambda t: t)
    assert prices.empty and actions.empty and missing == ["A", "B"]
