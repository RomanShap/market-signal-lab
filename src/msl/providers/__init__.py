from __future__ import annotations

from pathlib import Path

from msl.providers.base import FetchResult, MarketDataProvider


def get_provider(name: str, cache_dir: Path | None = None) -> MarketDataProvider:
    """Resolve a provider by name. Add new sources here and nowhere else."""
    if name == "yfinance":
        from msl.providers.yfinance_provider import YFinanceProvider

        return YFinanceProvider(cache_dir=cache_dir / "yfinance" if cache_dir else None)
    raise ValueError(f"unknown provider {name!r}; available: yfinance")


__all__ = ["FetchResult", "MarketDataProvider", "get_provider"]
