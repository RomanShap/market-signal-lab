-- Lesson 01 — exploring the raw landing zone with DuckDB.
-- Run each statement on its own. Paths are relative to the repo root.
-- read_parquet(..., hive_partitioning = true) turns the "provider=…/pull_id=…" folder
-- names into columns, so the latest pull can be selected with ordinary SQL.

-- 1. GROUP BY: how much history do we hold per ticker, and does it start where we asked?
SELECT
    ticker,
    count(*)  AS trading_days,
    min(date) AS first_date,
    max(date) AS last_date
FROM read_parquet('data/raw/prices/**/*.parquet', hive_partitioning = true)
GROUP BY ticker
ORDER BY trading_days DESC
LIMIT 20;

-- 2. JOIN: which sectors did we actually get data for? Note the join is on the
--    canonical ticker (BRK.B), not Yahoo's spelling (BRK-B) — that mapping is the
--    provider's job, so the rest of the system never sees it.
SELECT
    c.gics_sector,
    count(DISTINCT p.ticker) AS tickers_with_data,
    count(*)                 AS rows
FROM read_parquet('data/raw/prices/**/*.parquet', hive_partitioning = true) AS p
JOIN read_parquet('data/raw/reference/sp500_constituents/**/*.parquet', hive_partitioning = true) AS c
  ON c.ticker = p.ticker
GROUP BY c.gics_sector
ORDER BY tickers_with_data DESC;

-- 3. CTE + date_trunc: month-end close for one ticker. The CTE names an intermediate
--    result so the final SELECT reads like a sentence. Change the ticker; change
--    'month' to 'year'; then ask why max(date) is the right way to find the month-end row.
WITH monthly AS (
    SELECT
        ticker,
        date_trunc('month', date) AS month,
        max(date)                 AS month_end
    FROM read_parquet('data/raw/prices/**/*.parquet', hive_partitioning = true)
    WHERE ticker = 'AAPL'
    GROUP BY ticker, date_trunc('month', date)
)
SELECT
    m.month,
    p.close,
    p.adj_close
FROM monthly AS m
JOIN read_parquet('data/raw/prices/**/*.parquet', hive_partitioning = true) AS p
  ON p.ticker = m.ticker AND p.date = m.month_end
ORDER BY m.month
LIMIT 24;

-- 4. Data-quality: which tickers did the provider fail on, and why? This is the
--    survivorship-bias evidence — historical members with no free price history.
SELECT status, count(*) AS tickers
FROM read_parquet('data/raw/_ingest_log/**/*.parquet', hive_partitioning = true)
WHERE dataset = 'prices'
GROUP BY status;
