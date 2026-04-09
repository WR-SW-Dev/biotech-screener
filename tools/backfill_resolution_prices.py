#!/usr/bin/env python3
"""Backfill null price fields in CRT resolution files from price_history.csv.

For each resolution JSON with null price_t_minus_1 / price_t_0 / price_t_plus_5:
  - price_t_minus_1: close on last trading day before catalyst_date
  - price_t_0:       close on catalyst_date (or nearest trading day)
  - price_t_plus_5:  close 5 trading days after catalyst_date
  - price_direction:  "up" if price_t_0 > price_t_minus_1, else "down"

Uses common.market_calendar for trading day logic.
"""

import hashlib
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from common.market_calendar import add_trading_days, nearest_trading_day, prev_trading_day

RESOLUTIONS_DIR = PROJECT_ROOT / "data" / "snapshots" / "resolutions"
PRICE_HISTORY = PROJECT_ROOT / "production_data" / "price_history.csv"


def load_price_index() -> dict[str, dict[date, float]]:
    """Load price_history.csv into {ticker: {date: close}} lookup."""
    df = pd.read_csv(PRICE_HISTORY, usecols=["date", "ticker", "close"])
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df = df.dropna(subset=["close"])
    result: dict[str, dict[date, float]] = {}
    for ticker, group in df.groupby("ticker"):
        result[ticker] = dict(zip(group["date"], group["close"]))
    return result


def find_close(prices: dict[date, float], target: date, search_back: int = 5) -> float | None:
    """Find close price on target date, searching back up to search_back days."""
    for offset in range(search_back + 1):
        d = target
        for _ in range(offset):
            d = prev_trading_day(d)
        if d in prices:
            return prices[d]
    return None


def compute_record_hash(data: dict) -> str:
    """Compute SHA-256 hash of all fields except record_hash."""
    content = {k: v for k, v in data.items() if k != "record_hash"}
    raw = json.dumps(content, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def backfill():
    print("Loading price history...")
    price_index = load_price_index()
    print(f"  {len(price_index)} tickers loaded")

    resolution_files = sorted(RESOLUTIONS_DIR.glob("202*/*.json"))
    print(f"  {len(resolution_files)} resolution files found")

    updated = 0
    skipped_no_ticker = 0
    skipped_already_filled = 0
    skipped_missing_dates = 0
    details_missing = []

    for fpath in resolution_files:
        with open(fpath) as f:
            data = json.load(f)

        # Skip if already filled
        if data.get("price_t_minus_1") is not None:
            skipped_already_filled += 1
            continue

        ticker = data["ticker"]
        catalyst_date_str = data["catalyst_date"]
        cat_date = date.fromisoformat(catalyst_date_str)

        if ticker not in price_index:
            skipped_no_ticker += 1
            details_missing.append(f"  {ticker} ({catalyst_date_str}) - ticker not in price_history")
            continue

        prices = price_index[ticker]

        # price_t_minus_1: close on last trading day before catalyst_date
        t_minus_1_date = prev_trading_day(cat_date)
        p_minus_1 = find_close(prices, t_minus_1_date, search_back=5)

        # price_t_0: close on catalyst_date or nearest trading day
        t_0_date = nearest_trading_day(cat_date)
        p_0 = find_close(prices, t_0_date, search_back=5)

        # price_t_plus_5: close 5 trading days after catalyst_date
        t_plus_5_date = add_trading_days(cat_date, 5)
        p_5 = find_close(prices, t_plus_5_date, search_back=5)

        if p_minus_1 is None or p_0 is None:
            skipped_missing_dates += 1
            details_missing.append(
                f"  {ticker} ({catalyst_date_str}) - price dates not found "
                f"(t-1={t_minus_1_date}: {p_minus_1}, t0={t_0_date}: {p_0}, t+5={t_plus_5_date}: {p_5})"
            )
            continue

        data["price_t_minus_1"] = p_minus_1
        data["price_t_0"] = p_0
        data["price_t_plus_5"] = p_5  # may be None if future date
        data["price_direction"] = "up" if p_0 > p_minus_1 else "down"

        # Recompute record hash
        data["record_hash"] = compute_record_hash(data)

        with open(fpath, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")

        updated += 1
        direction = data["price_direction"]
        pct = ((p_0 / p_minus_1) - 1) * 100 if p_minus_1 else 0
        print(f"  {ticker} {catalyst_date_str}: {direction} ({pct:+.1f}%), t+5={'set' if p_5 else 'NULL'}")

    print("\n--- Summary ---")
    print(f"Updated:              {updated}")
    print(f"Already filled:       {skipped_already_filled}")
    print(f"Ticker not in prices: {skipped_no_ticker}")
    print(f"Dates not found:      {skipped_missing_dates}")
    print(f"Total files:          {len(resolution_files)}")

    if details_missing:
        print(f"\nFiles still missing prices ({len(details_missing)}):")
        for d in details_missing:
            print(d)


if __name__ == "__main__":
    backfill()
