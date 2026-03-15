#!/usr/bin/env python3
"""Build daily per-ticker IV features from the historical IV surface.

Reads historical_iv_surface.csv and computes per (date, ticker):
  - ATM IV (nearest expiry)
  - 25-delta put/call IV and risk reversal
  - ATM straddle price and implied move
  - Volume/OI metrics from day aggs

Output: data/research/historical_iv_features.csv

Usage:
    python scripts/research/build_historical_iv_features.py
"""
from __future__ import annotations

import argparse
import csv
import logging
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

FEATURE_COLUMNS = [
    "date",
    "ticker",
    "underlying_close",
    "atm_iv",
    "atm_iv_expiry",
    "atm_iv_dte",
    "put_25d_iv",
    "call_25d_iv",
    "rr_25d",
    "atm_straddle_price",
    "actual_implied_move",
    "total_volume",
    "put_volume",
    "call_volume",
    "put_call_volume_ratio",
    "n_contracts",
]


def _nearest_expiry_contracts(
    contracts: List[Dict[str, Any]],
    min_dte: int = 5,
) -> List[Dict[str, Any]]:
    """Filter to the nearest expiry with DTE >= min_dte."""
    valid = [c for c in contracts if c["dte"] >= min_dte]
    if not valid:
        return []
    min_exp = min(c["expiry"] for c in valid)
    return [c for c in valid if c["expiry"] == min_exp]


def compute_features(
    contracts: List[Dict[str, Any]],
    underlying_close: float,
) -> Dict[str, Any]:
    """Compute features from one date×ticker group of surface rows."""
    result: Dict[str, Any] = {col: "" for col in FEATURE_COLUMNS[2:]}
    result["underlying_close"] = underlying_close

    if not contracts:
        return result

    # Nearest expiry for ATM/skew features
    nearest = _nearest_expiry_contracts(contracts)
    if not nearest:
        return result

    expiry = nearest[0]["expiry"]
    dte = nearest[0]["dte"]

    # ATM IV: contract with strike closest to underlying, prefer call
    calls = [c for c in nearest if c["option_type"] == "call"]
    puts = [c for c in nearest if c["option_type"] == "put"]

    atm_call = min(calls, key=lambda c: abs(c["strike"] - underlying_close)) if calls else None
    atm_put = min(puts, key=lambda c: abs(c["strike"] - underlying_close)) if puts else None

    if atm_call:
        result["atm_iv"] = atm_call["implied_vol"]
        result["atm_iv_expiry"] = expiry
        result["atm_iv_dte"] = dte

    # ATM straddle
    if atm_call and atm_put:
        straddle = atm_call["option_close"] + atm_put["option_close"]
        result["atm_straddle_price"] = round(straddle, 4)
        if underlying_close > 0:
            result["actual_implied_move"] = round(straddle / underlying_close, 4)

    # 25-delta contracts
    put_25d = None
    call_25d = None
    best_put_dist = float("inf")
    best_call_dist = float("inf")
    for c in puts:
        d = c.get("delta")
        if d is not None and not (isinstance(d, float) and math.isnan(d)):
            dist = abs(float(d) - (-0.25))
            if dist < best_put_dist and dist < 0.15:
                best_put_dist = dist
                put_25d = c
    for c in calls:
        d = c.get("delta")
        if d is not None and not (isinstance(d, float) and math.isnan(d)):
            dist = abs(float(d) - 0.25)
            if dist < best_call_dist and dist < 0.15:
                best_call_dist = dist
                call_25d = c

    if put_25d:
        result["put_25d_iv"] = put_25d["implied_vol"]
    if call_25d:
        result["call_25d_iv"] = call_25d["implied_vol"]
    if put_25d and call_25d:
        result["rr_25d"] = round(float(call_25d["implied_vol"]) - float(put_25d["implied_vol"]), 6)

    # Volume metrics (across all expiries for this date×ticker)
    total_vol = 0
    put_vol = 0
    call_vol = 0
    for c in contracts:
        v = c.get("volume", 0) or 0
        total_vol += v
        if c["option_type"] == "put":
            put_vol += v
        else:
            call_vol += v

    result["total_volume"] = total_vol
    result["put_volume"] = put_vol
    result["call_volume"] = call_vol
    result["put_call_volume_ratio"] = round(put_vol / call_vol, 4) if call_vol > 0 else ""
    result["n_contracts"] = len(contracts)

    return result


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Build daily per-ticker IV features.")
    p.add_argument(
        "--surface",
        type=Path,
        default=PROJECT_ROOT / "data" / "research" / "historical_iv_surface.csv",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data" / "research" / "historical_iv_features.csv",
    )
    args = p.parse_args(argv)

    if not args.surface.exists():
        logger.error("Surface not found: %s — run build_historical_iv_surface.py first", args.surface)
        return 1

    logger.info("Loading surface from %s...", args.surface)
    # Group by (date, ticker)
    groups: Dict[tuple, List[Dict[str, Any]]] = defaultdict(list)
    underlying_prices: Dict[tuple, float] = {}
    n_rows = 0

    with open(args.surface, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            dt = row["date"]
            tk = row["ticker"]
            key = (dt, tk)
            groups[key].append(
                {
                    "expiry": row["expiry"],
                    "dte": int(row["dte"]),
                    "option_type": row["option_type"],
                    "strike": float(row["strike"]),
                    "underlying_close": float(row["underlying_close"]),
                    "option_close": float(row["option_close"]),
                    "implied_vol": float(row["implied_vol"]),
                    "delta": float(row["delta"]) if row.get("delta") else None,
                    "gamma": float(row["gamma"]) if row.get("gamma") else None,
                    "vega": float(row["vega"]) if row.get("vega") else None,
                    "theta": float(row["theta"]) if row.get("theta") else None,
                    "volume": int(row["volume"]) if row.get("volume") else 0,
                }
            )
            underlying_prices[key] = float(row["underlying_close"])
            n_rows += 1

    logger.info("  %d surface rows, %d date×ticker groups", n_rows, len(groups))

    # Compute features
    args.output.parent.mkdir(parents=True, exist_ok=True)
    n_features = 0
    n_with_rr = 0
    n_with_straddle = 0
    tickers_with_30d: Dict[str, int] = defaultdict(int)

    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FEATURE_COLUMNS)
        writer.writeheader()

        for (dt, tk), contracts in sorted(groups.items()):
            underlying = underlying_prices[(dt, tk)]
            features = compute_features(contracts, underlying)
            features["date"] = dt
            features["ticker"] = tk
            writer.writerow(features)
            n_features += 1
            tickers_with_30d[tk] += 1
            if features.get("rr_25d") not in ("", None):
                n_with_rr += 1
            if features.get("atm_straddle_price") not in ("", None):
                n_with_straddle += 1

    tickers_30plus = sum(1 for n in tickers_with_30d.values() if n >= 30)

    logger.info("=== Coverage Report ===")
    logger.info("  Total dates: %d", len(set(k[0] for k in groups)))
    logger.info("  Total feature rows: %d", n_features)
    logger.info("  Tickers with >= 30 daily rows: %d", tickers_30plus)
    logger.info("  rr_25d coverage: %d/%d (%.1f%%)", n_with_rr, n_features, 100 * n_with_rr / max(n_features, 1))
    logger.info(
        "  ATM straddle coverage: %d/%d (%.1f%%)",
        n_with_straddle,
        n_features,
        100 * n_with_straddle / max(n_features, 1),
    )
    logger.info("  Output: %s", args.output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
