#!/usr/bin/env python3
"""Build historical IV surface from Massive day aggregates.

For each cached day-agg date:
  1. Parse option ticker → underlying, expiry, type, strike
  2. Join underlying close from price_history.csv
  3. Compute DTE
  4. Solve implied vol via Brent's method
  5. Compute full BS Greeks

Output: data/research/historical_iv_surface.csv

Usage:
    python scripts/research/build_historical_iv_surface.py
    python scripts/research/build_historical_iv_surface.py --max-dates 10
"""
from __future__ import annotations

import argparse
import csv
import logging
import math
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Set

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from common.options_greeks import compute_historical_greeks, parse_option_ticker
from common.options_history_massive import ingest_day_aggs

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

SURFACE_COLUMNS = [
    "date",
    "ticker",
    "option_ticker",
    "expiry",
    "dte",
    "option_type",
    "strike",
    "underlying_close",
    "option_close",
    "volume",
    "transactions",
    "implied_vol",
    "delta",
    "gamma",
    "vega",
    "theta",
]

# Guardrails
MIN_DTE = 2
MIN_IV = 0.01
MAX_IV = 10.0


def load_price_history(path: Path) -> Dict[str, Dict[str, float]]:
    """Load price_history.csv → {ticker: {date_str: close}}."""
    prices: Dict[str, Dict[str, float]] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            tk = row.get("ticker", "").upper()
            dt = row.get("date", "")
            cl = row.get("close", "")
            if tk and dt and cl:
                try:
                    prices.setdefault(tk, {})[dt] = float(cl)
                except ValueError:
                    pass
    return prices


def find_cached_dates(cache_root: Path) -> List[date]:
    """Find all cached day-agg dates."""
    dates = []
    for gz in sorted(cache_root.rglob("*.csv.gz")):
        # Filename: YYYY-MM-DD.csv.gz → stem is "YYYY-MM-DD.csv"
        name = gz.name.replace(".csv.gz", "")
        try:
            d = date.fromisoformat(name)
            dates.append(d)
        except ValueError:
            pass
    return sorted(set(dates))


def load_universe_tickers(path: Path) -> Set[str]:
    """Load universe tickers for filtering."""
    import json

    data = json.loads(path.read_text())
    tickers = data if isinstance(data, list) else data.get("tickers", [])
    return {(t.upper() if isinstance(t, str) else t.get("ticker", "").upper()) for t in tickers}


def process_date(
    dt: date,
    prices: Dict[str, Dict[str, float]],
    universe: Set[str],
) -> List[Dict[str, Any]]:
    """Process one day of aggs into surface rows."""
    records = ingest_day_aggs(dt)
    if not records:
        return []

    dt_str = dt.isoformat()
    rows = []

    for rec in records:
        opt_close = rec.get("close")
        if not opt_close or opt_close <= 0:
            continue

        parsed = parse_option_ticker(rec.get("option_ticker", ""))
        underlying = parsed["underlying"]
        if not underlying or underlying not in universe:
            continue

        expiry_str = parsed["expiry_str"]
        strike = parsed["strike"]
        option_type = parsed["option_type"]
        if not expiry_str or not strike or not option_type:
            continue

        # DTE
        try:
            dte = (date.fromisoformat(expiry_str) - dt).days
        except (ValueError, TypeError):
            continue
        if dte < MIN_DTE:
            continue

        # Underlying close
        underlying_close = (prices.get(underlying) or {}).get(dt_str)
        if not underlying_close or underlying_close <= 0:
            continue

        # Compute historical Greeks (includes IV solver)
        greeks = compute_historical_greeks(opt_close, underlying_close, strike, dte, option_type)
        iv = greeks.get("implied_vol", float("nan"))
        if math.isnan(iv) or iv < MIN_IV or iv > MAX_IV:
            continue

        rows.append(
            {
                "date": dt_str,
                "ticker": underlying,
                "option_ticker": rec.get("option_ticker", ""),
                "expiry": expiry_str,
                "dte": dte,
                "option_type": option_type,
                "strike": strike,
                "underlying_close": round(underlying_close, 4),
                "option_close": round(opt_close, 4),
                "volume": rec.get("volume", 0),
                "transactions": rec.get("transactions", 0),
                "implied_vol": round(iv, 6),
                "delta": greeks.get("delta", ""),
                "gamma": greeks.get("gamma", ""),
                "vega": greeks.get("vega", ""),
                "theta": greeks.get("theta", ""),
            }
        )

    return rows


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Build historical IV surface from Massive day aggs.")
    p.add_argument("--price-csv", type=Path, default=PROJECT_ROOT / "production_data" / "price_history.csv")
    p.add_argument("--universe", type=Path, default=PROJECT_ROOT / "production_data" / "universe.json")
    p.add_argument("--cache-root", type=Path, default=PROJECT_ROOT / "data" / "caches" / "massive_options" / "day_aggs")
    p.add_argument("--output", type=Path, default=PROJECT_ROOT / "data" / "research" / "historical_iv_surface.csv")
    p.add_argument("--max-dates", type=int, default=0, help="Limit dates processed (0=all)")
    args = p.parse_args(argv)

    logger.info("Loading price history...")
    prices = load_price_history(args.price_csv)
    logger.info("  %d tickers", len(prices))

    logger.info("Loading universe...")
    universe = load_universe_tickers(args.universe)
    logger.info("  %d tickers", len(universe))

    dates = find_cached_dates(args.cache_root)
    logger.info("Cached dates: %d (%s to %s)", len(dates), dates[0] if dates else "?", dates[-1] if dates else "?")

    if args.max_dates > 0:
        dates = dates[-args.max_dates :]
        logger.info("  Limited to last %d dates", args.max_dates)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    total_rows = 0
    tickers_seen: Set[str] = set()

    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SURFACE_COLUMNS)
        writer.writeheader()

        for i, dt in enumerate(dates):
            rows = process_date(dt, prices, universe)
            for row in rows:
                writer.writerow(row)
                tickers_seen.add(row["ticker"])
            total_rows += len(rows)

            if (i + 1) % 10 == 0 or i == len(dates) - 1:
                logger.info(
                    "  %d/%d dates, %d surface rows, %d tickers", i + 1, len(dates), total_rows, len(tickers_seen)
                )

    logger.info("Done: %d rows, %d tickers, %d dates → %s", total_rows, len(tickers_seen), len(dates), args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
