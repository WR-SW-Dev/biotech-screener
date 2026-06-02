#!/usr/bin/env python3
"""Standalone price refresh — runs extend_price_csv_safe with batch mode for speed.

Usage:
    python tools/_price_refresh_standalone.py --as-of-date 2026-06-02
"""
import sys
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT))

import argparse
parser = argparse.ArgumentParser()
parser.add_argument("--as-of-date", required=True)
args = parser.parse_args()

universe_path = REPO_ROOT / "production_data" / "universe.json"
price_csv = REPO_ROOT / "production_data" / "price_history.csv"

with open(universe_path) as f:
    universe = json.load(f)

if isinstance(universe, list):
    tickers = [e.get("ticker", e) if isinstance(e, dict) else str(e) for e in universe]
elif isinstance(universe, dict):
    tickers = universe.get("tickers", [])

tickers = [t for t in tickers if t and not t.startswith("_")]
if "XBI" not in tickers:
    tickers.append("XBI")

logger.info("Starting price refresh: %d tickers -> %s", len(tickers), price_csv)

from backtest_signal_robustness import extend_price_csv_safe

stats = extend_price_csv_safe(
    csv_path=price_csv,
    through_date=args.as_of_date,
    tickers=tickers,
    use_per_ticker_mode=False,  # batch mode — much faster
    delay_sec=0.5,
)

logger.info("Price refresh complete: %s", stats)
