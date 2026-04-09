#!/usr/bin/env python3
"""Refresh price_history.csv with latest prices from yfinance.

Appends new dates to the existing price_history.csv without rewriting
historical data. Designed to run daily as part of the screen pipeline.

Usage:
    python scripts/refresh_price_history.py
    python scripts/refresh_price_history.py --days-back 5
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, Set

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def load_existing_dates(price_csv: Path) -> Dict[str, Set[str]]:
    """Load existing (ticker, date) pairs from price_history.csv."""
    existing: Dict[str, Set[str]] = {}
    if not price_csv.exists():
        return existing
    with open(price_csv, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            tk = row.get("ticker", "")
            dt = row.get("date", "")
            if tk and dt:
                existing.setdefault(tk, set()).add(dt)
    return existing


def load_universe(path: Path) -> list:
    """Load tickers from universe.json."""
    data = json.loads(path.read_text())
    tickers = data if isinstance(data, list) else data.get("tickers", [])
    return sorted(set(t.upper() if isinstance(t, str) else t.get("ticker", "").upper() for t in tickers))


def fetch_new_prices(tickers: list, start_date: date, end_date: date) -> list:
    """Fetch prices from yfinance for the given date range."""
    try:
        import yfinance as yf
    except ImportError:
        logger.error("yfinance not installed — run: pip install yfinance")
        return []

    logger.info("Fetching %d tickers from %s to %s...", len(tickers), start_date, end_date)

    try:
        data = yf.download(
            tickers,
            start=start_date.isoformat(),
            end=(end_date + timedelta(days=1)).isoformat(),
            progress=False,
            threads=True,
        )
    except Exception as exc:
        logger.error("yfinance download failed: %s", exc)
        return []

    if data.empty:
        logger.warning("No data returned from yfinance")
        return []

    rows = []
    for dt_idx in data.index:
        dt_str = dt_idx.strftime("%Y-%m-%d")
        for ticker in tickers:
            try:
                if len(tickers) == 1:
                    close = float(data.loc[dt_idx, "Close"])
                    opn = float(data.loc[dt_idx, "Open"])
                    high = float(data.loc[dt_idx, "High"])
                    low = float(data.loc[dt_idx, "Low"])
                    vol = int(data.loc[dt_idx, "Volume"])
                else:
                    close = float(data.loc[dt_idx, ("Close", ticker)])
                    opn = float(data.loc[dt_idx, ("Open", ticker)])
                    high = float(data.loc[dt_idx, ("High", ticker)])
                    low = float(data.loc[dt_idx, ("Low", ticker)])
                    vol = int(data.loc[dt_idx, ("Volume", ticker)])
            except (KeyError, ValueError, TypeError):
                continue

            if close != close:  # NaN check
                continue

            rows.append(
                {
                    "date": dt_str,
                    "ticker": ticker,
                    "close": close,
                    "open": opn if opn == opn else "",
                    "high": high if high == high else "",
                    "low": low if low == low else "",
                    "volume": vol if vol == vol else "",
                }
            )

    logger.info("Fetched %d price rows", len(rows))
    return rows


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Refresh price_history.csv with latest prices.")
    p.add_argument(
        "--price-csv",
        type=Path,
        default=PROJECT_ROOT / "production_data" / "price_history.csv",
    )
    p.add_argument(
        "--universe",
        type=Path,
        default=PROJECT_ROOT / "production_data" / "universe.json",
    )
    p.add_argument("--days-back", type=int, default=5, help="Days to look back for missing data")
    args = p.parse_args(argv)

    # Load existing data
    existing = load_existing_dates(args.price_csv)
    if existing:
        all_dates = set()
        for dates in existing.values():
            all_dates.update(dates)
        last_date = max(all_dates)
        logger.info("Existing data: %d tickers, last date: %s", len(existing), last_date)
    else:
        last_date = (date.today() - timedelta(days=30)).isoformat()
        logger.info("No existing data, starting from %s", last_date)

    # Determine fetch range
    start = date.fromisoformat(last_date) - timedelta(days=args.days_back)
    end = date.today()
    logger.info("Fetch range: %s to %s", start, end)

    # Load universe
    tickers = load_universe(args.universe)
    # Add XBI benchmark
    if "XBI" not in tickers:
        tickers.append("XBI")
    logger.info("Universe: %d tickers", len(tickers))

    # Fetch
    new_rows = fetch_new_prices(tickers, start, end)
    if not new_rows:
        logger.info("No new prices to append")
        return 0

    # Filter to truly new rows
    appended = 0
    with open(args.price_csv, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["date", "ticker", "close", "open", "high", "low", "volume"],
        )
        for row in new_rows:
            tk = row["ticker"]
            dt = row["date"]
            if dt not in existing.get(tk, set()):
                writer.writerow(row)
                existing.setdefault(tk, set()).add(dt)
                appended += 1

    logger.info("Appended %d new rows to %s", appended, args.price_csv)

    # Report new date range
    new_dates = sorted(set(r["date"] for r in new_rows))
    if new_dates:
        logger.info("New dates: %s to %s", new_dates[0], new_dates[-1])

    return 0


if __name__ == "__main__":
    sys.exit(main())
