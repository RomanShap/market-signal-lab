"""The provider contract.

The pipeline never imports a concrete provider; it asks for one by name (see
``msl.providers.get_provider``) and only relies on this interface. Swapping Yahoo for
Tiingo, Stooq or a paid point-in-time vendor therefore touches one file.

Every provider returns *long* frames with canonical column names and one row per
(ticker, date). Tickers are canonical (``BRK.B``); the provider's own spelling
(``BRK-B`` on Yahoo) is kept in ``source_symbol`` for traceability.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

import pandas as pd

PRICE_COLUMNS = [
    "ticker",
    "source_symbol",
    "date",
    "open",
    "high",
    "low",
    "close",
    "adj_close",
    "volume",
]
ACTION_COLUMNS = ["ticker", "source_symbol", "date", "action_type", "value"]
ACTION_TYPES = ("dividend", "split")


@dataclass
class FetchResult:
    prices: pd.DataFrame
    actions: pd.DataFrame
    # ticker -> short reason; a ticker absent from both frames and this dict is a bug
    failures: dict[str, str] = field(default_factory=dict)


class MarketDataProvider(Protocol):
    name: str

    def to_source_symbol(self, ticker: str) -> str:
        """Canonical ticker -> the provider's spelling."""
        ...

    def fetch_daily(self, tickers: list[str], start: date, end: date | None = None) -> FetchResult:
        """Daily OHLCV (+ adjusted close) and corporate actions for ``tickers``."""
        ...


def empty_prices() -> pd.DataFrame:
    return pd.DataFrame(columns=PRICE_COLUMNS)


def empty_actions() -> pd.DataFrame:
    return pd.DataFrame(columns=ACTION_COLUMNS)
