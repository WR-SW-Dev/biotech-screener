#!/usr/bin/env python3
"""Per-name attribution for the pruner portfolio.

For each rebalance period, tracks which names the pruner picked vs dropped,
and measures whether the pruner's choices outperformed:
  - Did the kept names beat the dropped names?
  - Which individual picks drove returns?
  - Does the pruner fail on specific name types?

Usage:
    python tools/build_name_attribution.py --as-of-date 2026-04-02
    python tools/build_name_attribution.py --start 2024-01-01
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

SNAPSHOTS_DIR = REPO_ROOT / "data" / "snapshots"
PRICE_CSV = REPO_ROOT / "production_data" / "price_history.csv"
OUTPUT_DIR = REPO_ROOT / "artifacts" / "name_attribution"

SCHEMA = "name_attribution.v1"


def _sf(v, default=float("nan")):
    if v is None or v == "":
        return default
    try:
        f = float(v)
        return f if not math.isnan(f) else default
    except (ValueError, TypeError):
        return default


def load_prices():
    series = {}
    with open(PRICE_CSV) as f:
        for row in csv.DictReader(f):
            t, d, c = row.get("ticker", ""), row.get("date", ""), row.get("close", "")
            if t and d and c:
                try:
                    series.setdefault(t, {})[d] = float(c)
                except ValueError:
                    pass
    return series


def forward_return(prices, snap_date, horizon):
    sorted_dates = sorted(prices.keys())
    candidates = [d for d in sorted_dates if d >= snap_date]
    if not candidates:
        return None
    idx = sorted_dates.index(candidates[0])
    target = idx + horizon
    if target >= len(sorted_dates):
        return None
    p0, p1 = prices.get(sorted_dates[idx]), prices.get(sorted_dates[target])
    if p0 and p1 and p0 > 0:
        return (p1 - p0) / p0
    return None


def build_attribution(start: str, horizon: int = 20) -> dict:
    prices = load_prices()

    all_dates = sorted(
        d.name
        for d in SNAPSHOTS_DIR.iterdir()
        if d.is_dir() and d.name >= start and (d / "rankings.csv").exists() and "__pre_" not in d.name
    )
    by_month = {}
    for d in all_dates:
        by_month[d[:7]] = d
    eval_dates = sorted(by_month.values())

    records = []
    kept_wins = 0
    kept_losses = 0
    dropped_would_have_won = 0

    for snap_date in eval_dates:
        with open(SNAPSHOTS_DIR / snap_date / "rankings.csv") as f:
            rows = list(csv.DictReader(f))

        ranked = [r for r in rows if r.get("actionable_rank", "").strip()]
        ranked.sort(key=lambda r: int(float(r["actionable_rank"])))
        top30 = ranked[:30]

        for r in top30:
            r["_idz"] = _sf(r.get("inst_delta_z"))

        with_signal = [r for r in top30 if not math.isnan(r["_idz"])]
        if len(with_signal) < 20:
            with_signal = top30
        with_signal.sort(key=lambda r: r.get("_idz", 0), reverse=True)
        kept_set = {r["ticker"] for r in with_signal[:20]}
        # dropped names are those in top30 not in kept_set

        # Forward returns
        kept_rets = {}
        dropped_rets = {}
        for r in top30:
            ret = forward_return(prices.get(r["ticker"], {}), snap_date, horizon)
            if ret is None:
                continue
            if r["ticker"] in kept_set:
                kept_rets[r["ticker"]] = ret
            else:
                dropped_rets[r["ticker"]] = ret

        if not kept_rets:
            continue

        kept_mean = statistics.mean(kept_rets.values())
        dropped_mean = statistics.mean(dropped_rets.values()) if dropped_rets else 0
        pruner_correct = kept_mean > dropped_mean

        if pruner_correct:
            kept_wins += 1
        else:
            kept_losses += 1

        # Best and worst in each group
        best_kept = max(kept_rets.items(), key=lambda x: x[1]) if kept_rets else ("", 0)
        worst_kept = min(kept_rets.items(), key=lambda x: x[1]) if kept_rets else ("", 0)
        best_dropped = max(dropped_rets.items(), key=lambda x: x[1]) if dropped_rets else ("", 0)

        if dropped_rets and best_dropped[1] > kept_mean:
            dropped_would_have_won += 1

        records.append(
            {
                "date": snap_date,
                "kept_mean_ret": round(kept_mean * 100, 2),
                "dropped_mean_ret": round(dropped_mean * 100, 2),
                "spread": round((kept_mean - dropped_mean) * 100, 2),
                "pruner_correct": pruner_correct,
                "best_kept": {"ticker": best_kept[0], "ret": round(best_kept[1] * 100, 2)},
                "worst_kept": {"ticker": worst_kept[0], "ret": round(worst_kept[1] * 100, 2)},
                "best_dropped": {"ticker": best_dropped[0], "ret": round(best_dropped[1] * 100, 2)},
                "n_kept": len(kept_rets),
                "n_dropped": len(dropped_rets),
            }
        )

    # Aggregate
    n_total = kept_wins + kept_losses
    hit_rate = kept_wins / n_total if n_total > 0 else 0
    spreads = [r["spread"] for r in records]
    mean_spread = statistics.mean(spreads) if spreads else 0
    cum_spread = sum(spreads)

    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "start": start,
        "horizon": horizon,
        "n_periods": n_total,
        "pruner_hit_rate": round(hit_rate, 2),
        "kept_wins": kept_wins,
        "kept_losses": kept_losses,
        "dropped_would_have_beaten_kept": dropped_would_have_won,
        "mean_spread_pp": round(mean_spread, 2),
        "cum_spread_pp": round(cum_spread, 1),
        "records": records,
    }


def main():
    parser = argparse.ArgumentParser(description="Name-level attribution for pruner")
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--horizon", type=int, default=20)
    parser.add_argument("--as-of-date", default=None, help="Single date attribution")
    args = parser.parse_args()

    result = build_attribution(args.start, args.horizon)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / "name_attribution.json"
    out_path.write_text(json.dumps(result, indent=2, default=str))

    print(f"NAME ATTRIBUTION — {result['n_periods']} periods, {args.horizon}d horizon")
    print(f"  Pruner hit rate: {result['pruner_hit_rate']:.0%} ({result['kept_wins']}W / {result['kept_losses']}L)")
    print(f"  Mean spread: {result['mean_spread_pp']:+.2f}pp/period")
    print(f"  Cumulative: {result['cum_spread_pp']:+.1f}pp")
    print(f"  Dropped names beat kept: {result['dropped_would_have_beaten_kept']}x")

    # Show best/worst months
    if result["records"]:
        best = max(result["records"], key=lambda r: r["spread"])
        worst = min(result["records"], key=lambda r: r["spread"])
        print(f"\n  Best month:  {best['date']} spread={best['spread']:+.2f}pp")
        print(f"    Best kept: {best['best_kept']['ticker']} {best['best_kept']['ret']:+.1f}%")
        print(f"  Worst month: {worst['date']} spread={worst['spread']:+.2f}pp")
        print(f"    Best dropped: {worst['best_dropped']['ticker']} {worst['best_dropped']['ret']:+.1f}%")

    print(f"\n  Saved: {out_path}")


if __name__ == "__main__":
    main()
