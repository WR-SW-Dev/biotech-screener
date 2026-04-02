#!/usr/bin/env python3
"""
build_ipo_dates.py - Build IPO date lookup from price_history.csv

For each ticker, finds the earliest date with a price entry (proxy for IPO/listing date)
and the latest date (proxy for delist date). Saves to production_data/ipo_dates.json.

Used by run_screen.py to enforce PIT survivorship filtering:
- Exclude tickers that hadn't IPO'd yet as of the snapshot date
- Exclude tickers that delisted before the snapshot date
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def build_ipo_dates(price_history_path: Path) -> dict:
    """Read price_history.csv and return {ticker: {first_date, last_date}}."""
    first_dates: dict[str, str] = {}
    last_dates: dict[str, str] = {}

    with open(price_history_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ticker = row.get("ticker", "").strip()
            date_str = row.get("date", "").strip()
            if not ticker or not date_str:
                continue
            # Track first (earliest) date per ticker
            if ticker not in first_dates or date_str < first_dates[ticker]:
                first_dates[ticker] = date_str
            # Track last (latest) date per ticker
            if ticker not in last_dates or date_str > last_dates[ticker]:
                last_dates[ticker] = date_str

    tickers = {}
    for ticker in sorted(first_dates.keys()):
        tickers[ticker] = {
            "first_price_date": first_dates[ticker],
            "last_price_date": last_dates[ticker],
        }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "price_history.csv first-price-date proxy",
        "ticker_count": len(tickers),
        "tickers": tickers,
    }


def main():
    project_root = Path(__file__).resolve().parent.parent
    price_history_path = project_root / "production_data" / "price_history.csv"
    output_path = project_root / "production_data" / "ipo_dates.json"

    if not price_history_path.exists():
        print(f"ERROR: {price_history_path} not found", file=sys.stderr)
        sys.exit(1)

    print(f"Reading {price_history_path}...")
    result = build_ipo_dates(price_history_path)
    print(f"Found {result['ticker_count']} tickers")

    # Show some examples
    tickers = result["tickers"]
    examples = list(tickers.items())[:5]
    for ticker, dates in examples:
        print(f"  {ticker}: first={dates['first_price_date']}, last={dates['last_price_date']}")

    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"Saved to {output_path}")


if __name__ == "__main__":
    main()
