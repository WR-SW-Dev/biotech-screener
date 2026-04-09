#!/usr/bin/env python3
"""Regime-conditional pruner analysis.

The pruner backtest shows +127pp overall but was flat in 2021 and 2024.
This script decomposes performance by market regime to understand WHEN
the pruner fails and whether regime awareness could improve it.

Regimes (by XBI 63d return):
  Bear:    XBI < -5%
  Neutral: -5% <= XBI <= +5%
  Bull:    XBI > +5%

Usage:
    python3 scripts/research/pruner_regime_analysis.py
"""

from __future__ import annotations

import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

SNAPSHOTS_DIR = PROJECT_ROOT / "data" / "snapshots"
PRICE_CSV = PROJECT_ROOT / "production_data" / "price_history.csv"
OUTPUT_DIR = PROJECT_ROOT / "output" / "ranker_eval"


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


def classify_regime(xbi_ret: float) -> str:
    if xbi_ret < -0.05:
        return "bear"
    if xbi_ret > 0.05:
        return "bull"
    return "neutral"


def main():
    print("Loading prices...")
    prices = load_prices()
    xbi = prices.get("XBI", {})

    all_dates = sorted(
        d.name
        for d in SNAPSHOTS_DIR.iterdir()
        if d.is_dir() and d.name >= "2020-01-01" and (d / "rankings.csv").exists() and "__pre_" not in d.name
    )
    by_month = {}
    for d in all_dates:
        by_month[d[:7]] = d
    eval_dates = sorted(by_month.values())

    horizons = [20, 63]
    records = []

    for snap_date in eval_dates:
        with open(SNAPSHOTS_DIR / snap_date / "rankings.csv") as f:
            rows = list(csv.DictReader(f))

        ranked = [r for r in rows if r.get("actionable_rank", "").strip()]
        if not ranked:
            continue
        ranked.sort(key=lambda r: int(float(r["actionable_rank"])))
        top30 = ranked[:30]

        for r in top30:
            r["_idz"] = _sf(r.get("inst_delta_z"))
        with_signal = [r for r in top30 if not math.isnan(r["_idz"])]
        if len(with_signal) >= 20:
            with_signal.sort(key=lambda r: r["_idz"], reverse=True)
            kept = {r["ticker"] for r in with_signal[:20]}
        else:
            kept = {r["ticker"] for r in top30[:20]}

        rec = {"date": snap_date}

        for h in horizons:
            xbi_ret = forward_return(xbi, snap_date, h)
            if xbi_ret is None:
                continue

            regime = classify_regime(xbi_ret)
            rec[f"h{h}_regime"] = regime
            rec[f"h{h}_xbi"] = round(xbi_ret * 100, 2)

            # EW Top-30
            rets30 = [forward_return(prices.get(r["ticker"], {}), snap_date, h) for r in top30]
            rets30 = [r for r in rets30 if r is not None]

            # EW Top-20 (pruned)
            rets20 = [forward_return(prices.get(t, {}), snap_date, h) for t in kept]
            rets20 = [r for r in rets20 if r is not None]

            if len(rets30) < 15 or len(rets20) < 10:
                continue

            ew30 = statistics.mean(rets30)
            ew20 = statistics.mean(rets20)
            rec[f"h{h}_ew30"] = round((ew30 - xbi_ret) * 100, 2)
            rec[f"h{h}_ew20"] = round((ew20 - xbi_ret) * 100, 2)
            rec[f"h{h}_spread"] = round((ew20 - ew30) * 100, 2)

        records.append(rec)

    # Aggregate by regime
    print(f"\n{'='*70}")
    print(f"PRUNER REGIME ANALYSIS — {len(records)} months")
    print(f"{'='*70}")

    for h in horizons:
        regime_data: dict[str, list[dict]] = defaultdict(list)
        for rec in records:
            regime = rec.get(f"h{h}_regime")
            if regime and f"h{h}_spread" in rec:
                regime_data[regime].append(rec)

        print(f"\n--- {h}d horizon ---")
        print(
            f"  {'Regime':<10s} {'N':>4s} {'EW30 excess':>12s} {'EW20 excess':>12s} {'Spread':>10s} {'Hit':>6s} {'IR':>6s}"
        )
        print(f"  {'-'*65}")

        for regime in ["bear", "neutral", "bull"]:
            recs = regime_data.get(regime, [])
            if not recs:
                continue
            ew30s = [r[f"h{h}_ew30"] for r in recs]
            ew20s = [r[f"h{h}_ew20"] for r in recs]
            spreads = [r[f"h{h}_spread"] for r in recs]
            mean_30 = statistics.mean(ew30s)
            mean_20 = statistics.mean(ew20s)
            mean_sp = statistics.mean(spreads)
            hit = sum(1 for s in spreads if s > 0) / len(spreads)
            std_sp = statistics.stdev(spreads) if len(spreads) > 1 else 0
            ir = mean_sp / std_sp if std_sp > 0 else 0
            print(
                f"  {regime:<10s} {len(recs):>4d} {mean_30:>+10.2f}pp {mean_20:>+10.2f}pp {mean_sp:>+8.2f}pp {hit:>5.0%} {ir:>5.2f}"
            )

        # Overall
        all_spreads = [r[f"h{h}_spread"] for r in records if f"h{h}_spread" in r]
        if all_spreads:
            mean_all = statistics.mean(all_spreads)
            hit_all = sum(1 for s in all_spreads if s > 0) / len(all_spreads)
            std_all = statistics.stdev(all_spreads) if len(all_spreads) > 1 else 0
            ir_all = mean_all / std_all if std_all > 0 else 0
            print(
                f"  {'ALL':<10s} {len(all_spreads):>4d} {'':>12s} {'':>12s} {mean_all:>+8.2f}pp {hit_all:>5.0%} {ir_all:>5.2f}"
            )

    # Save
    result = {
        "schema": "pruner_regime_analysis.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_months": len(records),
        "records": records,
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / "pruner_regime_analysis.json"
    out_path.write_text(json.dumps(result, indent=2, default=str))
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
