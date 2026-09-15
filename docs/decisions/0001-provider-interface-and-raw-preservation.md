# ADR-0001 — Provider interface; raw sources are preserved as pulled

**Status:** accepted · 2026-09-15

## Context

The project starts on free data (Yahoo Finance via `yfinance`, Wikipedia for index
membership). Free sources are unofficial, change shape without notice, and will be
replaced by better ones if the research ever justifies paying. On the very first day the
Wikipedia change log turned out to have moved to a different article, and `yfinance`
silently failed one ticker per batch because of a broken local cache directory.

## Decision

1. The pipeline talks to market data only through `msl.providers.base.MarketDataProvider`
   (`fetch_daily(tickers, start, end) -> FetchResult`). Concrete providers are resolved by
   name in `msl.providers.get_provider`; nothing else imports them.
2. Every provider returns **long** frames with canonical column names
   (`ticker, source_symbol, date, open, high, low, close, adj_close, volume`) and a
   `failures` map. Canonical tickers use the S&P spelling (`BRK.B`); the provider keeps its
   own spelling in `source_symbol`.
3. Whatever the source served is kept next to what was parsed out of it: the Wikipedia
   HTML pages are written to `data/raw/reference/*_page/…/page.html`, yfinance frames are
   stored column-for-column (including Yahoo's own `adj_close`, which Silver will
   cross-check against our dividend-derived adjustment).

## Consequences

- Adding Tiingo/Stooq/EODHD is one new module plus one `elif`.
- A parser bug or a source restructuring can always be diagnosed from disk, offline.
- Bronze is honest about what Yahoo actually provides: `close` is split-adjusted,
  `adj_close` is split+dividend adjusted, neither is a raw print. Silver documents that.
