"""Compact daily construction v2 compare artifact.

One artifact per day showing:
  - EW Top-30 excess
  - Regime overlay excess
  - Legacy shadow excess
  - Turnover for each
  - Overlap between variants
  - Current regime
  - Cumulative comparison

Designed for operator quick-read. Runs after construction_v2_shadow.py.

Usage:
    python tools/build_daily_v2_compare.py --as-of-date 2026-04-01
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
from datetime import date, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

V2_PERF_PATH = REPO_ROOT / "artifacts" / "construction_v2" / "performance.csv"
V2_POS_DIR = REPO_ROOT / "artifacts" / "construction_v2" / "positions"
SHADOW_PERF_PATH = REPO_ROOT / "artifacts" / "live_shadow" / "performance.csv"
OUTPUT_DIR = REPO_ROOT / "artifacts" / "construction_v2"

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("v2_compare")


def load_v2_performance() -> list[dict]:
    if not V2_PERF_PATH.exists():
        return []
    rows = []
    with open(V2_PERF_PATH, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(row)
    return rows


def load_shadow_performance() -> dict[str, dict]:
    if not SHADOW_PERF_PATH.exists():
        return {}
    result = {}
    with open(SHADOW_PERF_PATH, encoding="utf-8") as f:
        for line in csv.reader(f):
            if len(line) >= 10 and line[0] == "live_shadow_perf.v1":
                try:
                    result[line[1]] = {
                        "pnl_pct": float(line[4]) if line[4] else 0,
                        "xbi_pct": float(line[5]) if line[5] else 0,
                        "excess": float(line[6]) if line[6] else 0,
                        "n_held": int(line[7]) if line[7] else 0,
                        "turnover": float(line[8]) if line[8] else 0,
                    }
                except (ValueError, IndexError):
                    pass
    return result


def load_positions(date_str: str) -> dict | None:
    path = V2_POS_DIR / f"{date_str}.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_compare(as_of_date: str) -> dict:
    v2_rows = load_v2_performance()
    shadow = load_shadow_performance()
    positions = load_positions(as_of_date)

    # Cumulative v2
    cum_ew30 = 0.0
    cum_regime = 0.0
    cum_xbi = 0.0
    today_ew30 = None
    today_regime = None

    for r in v2_rows:
        ew_pnl = float(r.get("ew30_pnl_pct", 0))
        rg_pnl = float(r.get("regime_pnl_pct", 0))
        xbi_pnl = float(r.get("xbi_pct", 0))
        cum_ew30 += ew_pnl
        cum_regime += rg_pnl
        cum_xbi += xbi_pnl

        if r.get("date") == as_of_date:
            today_ew30 = {
                "pnl_pct": ew_pnl,
                "excess": float(r.get("ew30_excess", 0)),
                "n_held": int(r.get("ew30_n_held", 0)),
                "turnover": float(r.get("ew30_turnover", 0)),
            }
            today_regime = {
                "pnl_pct": rg_pnl,
                "excess": float(r.get("regime_excess", 0)),
                "n_held": int(r.get("regime_n_held", 0)),
                "turnover": float(r.get("regime_turnover", 0)),
            }

    # Cumulative shadow (over same period as v2)
    cum_shadow = 0.0
    cum_shadow_xbi = 0.0
    v2_dates = set(r.get("date") for r in v2_rows)
    today_shadow = shadow.get(as_of_date)

    for d, s in shadow.items():
        if d in v2_dates:
            cum_shadow += s["pnl_pct"]
            cum_shadow_xbi += s["xbi_pct"]

    # Overlap between ew30 and legacy shadow
    overlap_ew30_shadow = None
    if positions:
        ew30_tickers = set(p["ticker"] for p in positions.get("variants", {}).get("ew30", {}).get("positions", []))
        # Load legacy shadow positions for same date
        legacy_pos_path = REPO_ROOT / "artifacts" / "live_shadow" / "positions" / f"{as_of_date}.json"
        if legacy_pos_path.exists():
            with open(legacy_pos_path, encoding="utf-8") as f:
                legacy_data = json.load(f)
            legacy_tickers = set(p.get("ticker", "") for p in legacy_data.get("positions", []))
            if ew30_tickers and legacy_tickers:
                overlap_ew30_shadow = len(ew30_tickers & legacy_tickers)

    n_periods = len(v2_rows)
    regime = positions.get("regime", "unknown") if positions else "unknown"

    compare = {
        "schema": "daily_v2_compare.v1",
        "as_of_date": as_of_date,
        "generated_at": datetime.now().isoformat(),
        "regime": regime,
        "n_periods": n_periods,
        "today": {
            "ew30": today_ew30,
            "regime_overlay": today_regime,
            "legacy_shadow": (
                {
                    "pnl_pct": today_shadow["pnl_pct"] if today_shadow else None,
                    "excess": today_shadow["excess"] if today_shadow else None,
                    "n_held": today_shadow["n_held"] if today_shadow else None,
                    "turnover": today_shadow["turnover"] if today_shadow else None,
                }
                if today_shadow
                else None
            ),
        },
        "cumulative": {
            "ew30_pct": round(cum_ew30, 4),
            "ew30_excess_pct": round(cum_ew30 - cum_xbi, 4),
            "regime_pct": round(cum_regime, 4),
            "regime_excess_pct": round(cum_regime - cum_xbi, 4),
            "legacy_pct": round(cum_shadow, 4),
            "legacy_excess_pct": round(cum_shadow - cum_shadow_xbi, 4) if cum_shadow_xbi else None,
            "xbi_pct": round(cum_xbi, 4),
        },
        "overlap": {
            "ew30_vs_legacy": overlap_ew30_shadow,
        },
    }

    return compare


def main():
    parser = argparse.ArgumentParser(description="Daily v2 compare artifact")
    parser.add_argument("--as-of-date", default=date.today().isoformat())
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    compare = build_compare(args.as_of_date)

    output_path = OUTPUT_DIR / f"compare_{args.as_of_date}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(compare, f, indent=2)

    # Print compact summary
    c = compare["cumulative"]
    t = compare["today"]
    print(f"\n  CONSTRUCTION V2 COMPARE — {args.as_of_date}")
    print(f"  Regime: {compare['regime']} | Periods: {compare['n_periods']}")
    print(f"  {'─'*50}")
    print(f"  {'Variant':<20} {'Today':<12} {'Cumulative':<15} {'Excess':<12}")
    print(f"  {'─'*50}")

    if t.get("ew30"):
        print(
            f"  {'EW Top-30':<20} {t['ew30']['pnl_pct']:>+7.2f}%     {c['ew30_pct']:>+8.2f}%      {c['ew30_excess_pct']:>+7.2f}%"
        )
    if t.get("regime_overlay"):
        print(
            f"  {'Regime overlay':<20} {t['regime_overlay']['pnl_pct']:>+7.2f}%     {c['regime_pct']:>+8.2f}%      {c['regime_excess_pct']:>+7.2f}%"
        )
    if t.get("legacy_shadow") and t["legacy_shadow"].get("pnl_pct") is not None:
        print(
            f"  {'Legacy shadow':<20} {t['legacy_shadow']['pnl_pct']:>+7.2f}%     {c['legacy_pct']:>+8.2f}%      {c.get('legacy_excess_pct','—'):>+7.2f}%"
            if c.get("legacy_excess_pct")
            else f"  {'Legacy shadow':<20} {t['legacy_shadow']['pnl_pct']:>+7.2f}%     {c['legacy_pct']:>+8.2f}%"
        )
    print(f"  {'XBI':<20} {'':>12} {c['xbi_pct']:>+8.2f}%")

    if compare["overlap"].get("ew30_vs_legacy") is not None:
        print(f"\n  EW30 ↔ Legacy overlap: {compare['overlap']['ew30_vs_legacy']} names")

    log.info("Wrote %s", output_path)


if __name__ == "__main__":
    main()
