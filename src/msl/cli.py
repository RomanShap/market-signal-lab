"""``msl`` — the command-line entry point (also the Docker container's ENTRYPOINT).

msl ingest universe                       # S&P 500 constituents + point-in-time membership
msl ingest prices --universe sp500        # every ticker that was ever a member since START
msl ingest prices --tickers AAPL,MSFT     # a hand-picked list (smoke tests, lessons)
msl ingest all                            # universe, then prices; one pull_id for both
msl ingest ... --mode incremental         # only what is new since the last pull
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

from msl.config import load_settings


def _date(text: str) -> date:
    return date.fromisoformat(text)


def build_parser() -> argparse.ArgumentParser:
    settings = load_settings()
    parser = argparse.ArgumentParser(prog="msl", description=__doc__.split("\n\n")[0])
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="pull raw data into data/raw/").add_subparsers(
        dest="dataset", required=True
    )

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--start", type=_date, default=_date(settings.default_start))
        p.add_argument("--end", type=_date, default=None, help="exclusive; default = today")
        p.add_argument("--mode", choices=["full", "incremental"], default="full")
        p.add_argument("--provider", default="yfinance")
        p.add_argument("--tickers", help="comma-separated canonical tickers, e.g. AAPL,BRK.B")

    ingest.add_parser("universe", help="S&P 500 constituents, change log, PIT membership")
    prices = ingest.add_parser("prices", help="daily OHLCV + corporate actions")
    common(prices)
    prices.add_argument("--universe", choices=["sp500"], default=None)
    everything = ingest.add_parser("all", help="universe, then prices for every historical member")
    common(everything)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    settings = load_settings()
    settings.raw_dir.mkdir(parents=True, exist_ok=True)

    from msl.ingest import run

    if args.command == "ingest" and args.dataset == "universe":
        run.ingest_universe(settings)
        return 0

    tickers = [t.strip().upper() for t in args.tickers.split(",")] if args.tickers else None

    if args.command == "ingest" and args.dataset == "prices":
        if tickers is None:
            if args.universe is None:
                print("error: pass --universe sp500 or --tickers A,B,C", file=sys.stderr)
                return 2
            tickers = run.universe_tickers(settings, since=args.start)
        run.ingest_prices(settings, tickers, args.start, args.end, args.mode, args.provider)
        return 0

    if args.command == "ingest" and args.dataset == "all":
        run.ingest_all(settings, args.start, args.end, args.mode, args.provider, tickers)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
