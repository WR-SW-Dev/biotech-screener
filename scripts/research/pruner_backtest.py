#!/usr/bin/env python3
"""Stage-2 pruner backtest: EW Top-30 vs EW Top-20 (pruned by signal).

DEM picks 30. A simple non-options stage-2 model drops 10 and holds EW Top-20.
Tests three portfolios:
  1. EW Top-30 (baseline)
  2. EW Top-20 by inst_delta_z (first pruner)
  3. EW Top-20 by inst_delta_z + aact_execution_score (joint pruner, when available)

Promotion rule: joint Top-20 must beat both EW Top-30 AND inst_delta-only Top-20
on IC, cumulative spread, and net of costs.

Usage:
    python3 scripts/research/pruner_backtest.py
    python3 scripts/research/pruner_backtest.py --start 2020-01-01
    python3 scripts/research/pruner_backtest.py --start 2024-01-01 --include-aact
"""
from __future__ import annotations

import argparse
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

SCHEMA = "pruner_backtest.v1"

# Cost assumptions
ANNUAL_EW30_COST_BPS = 223
ANNUAL_EW20_COST_BPS = 280  # higher turnover from pruning
MONTHLY_COST_DIFF_PP = (ANNUAL_EW20_COST_BPS - ANNUAL_EW30_COST_BPS) / 12 / 100


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
    p0 = prices.get(sorted_dates[idx])
    p1 = prices.get(sorted_dates[target])
    if p0 and p1 and p0 > 0:
        return (p1 - p0) / p0
    return None


def spearman_ic(x, y):
    n = len(x)
    if n < 5:
        return None

    def _rank(vals):
        indexed = sorted(range(n), key=lambda i: vals[i])
        ranks = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j < n - 1 and vals[indexed[j + 1]] == vals[indexed[j]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                ranks[indexed[k]] = avg
            i = j + 1
        return ranks

    rx, ry = _rank(x), _rank(y)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    dx = sum((rx[i] - mx) ** 2 for i in range(n)) ** 0.5
    dy = sum((ry[i] - my) ** 2 for i in range(n)) ** 0.5
    if dx < 1e-9 or dy < 1e-9:
        return None
    return num / (dx * dy)


def run_backtest(start: str, include_aact: bool, horizons: list[int]):
    print("Loading prices...")
    prices = load_prices()
    xbi = prices.get("XBI", {})

    # Get monthly snapshot dates
    all_dates = sorted(
        d.name
        for d in SNAPSHOTS_DIR.iterdir()
        if d.is_dir() and d.name >= start and (d / "rankings.csv").exists() and "__pre_" not in d.name
    )
    by_month = {}
    for d in all_dates:
        by_month[d[:7]] = d
    eval_dates = sorted(by_month.values())
    print(f"Evaluation dates: {len(eval_dates)} ({eval_dates[0]} to {eval_dates[-1]})")

    # Three portfolios per date per horizon
    strats = ["ew_top30", "pruned_idz_top20"]
    if include_aact:
        strats.append("pruned_joint_top20")

    results = {s: {h: [] for h in horizons} for s in strats}
    records = []

    for snap_date in eval_dates:
        with open(SNAPSHOTS_DIR / snap_date / "rankings.csv") as f:
            rows = list(csv.DictReader(f))

        ranked = [r for r in rows if r.get("actionable_rank", "").strip()]
        if not ranked:
            continue
        ranked.sort(key=lambda r: int(float(r["actionable_rank"])))
        top30 = ranked[:30]

        if len(top30) < 20:
            continue

        # Sort top-30 by inst_delta_z (higher = better, keep top 20)
        for r in top30:
            r["_idz"] = _sf(r.get("inst_delta_z"))
            r["_aact"] = _sf(r.get("aact_execution_score"))

        idz_valid = [r for r in top30 if not math.isnan(r["_idz"])]
        idz_valid.sort(key=lambda r: r["_idz"], reverse=True)

        # If not enough inst_delta data, use DEM rank order as fallback
        if len(idz_valid) >= 20:
            pruned_idz = [r["ticker"] for r in idz_valid[:20]]
        else:
            pruned_idz = [r["ticker"] for r in top30[:20]]

        # Joint signal: z-score both, combine 0.7*idz + 0.3*aact
        pruned_joint = None
        if include_aact:
            joint_valid = [
                r for r in top30 if not math.isnan(r["_idz"]) and not math.isnan(r["_aact"]) and r["_aact"] != 0
            ]
            if len(joint_valid) >= 15:
                idz_vals = [r["_idz"] for r in joint_valid]
                aact_vals = [r["_aact"] for r in joint_valid]
                idz_mu, idz_sd = statistics.mean(idz_vals), (statistics.stdev(idz_vals) if len(idz_vals) > 1 else 1)
                aact_mu, aact_sd = statistics.mean(aact_vals), (
                    statistics.stdev(aact_vals) if len(aact_vals) > 1 else 1
                )
                for r in joint_valid:
                    idz_z = (r["_idz"] - idz_mu) / idz_sd if idz_sd > 0 else 0
                    aact_z = (r["_aact"] - aact_mu) / aact_sd if aact_sd > 0 else 0
                    r["_joint"] = 0.7 * idz_z + 0.3 * aact_z
                joint_valid.sort(key=lambda r: r["_joint"], reverse=True)
                pruned_joint = [r["ticker"] for r in joint_valid[:20]]

        rec = {"date": snap_date}

        for h in horizons:
            hk = f"h{h}"

            # EW Top-30
            rets_30 = []
            for r in top30:
                ret = forward_return(prices.get(r["ticker"], {}), snap_date, h)
                if ret is not None:
                    rets_30.append(ret)

            xbi_ret = forward_return(xbi, snap_date, h)
            if len(rets_30) < 20 or xbi_ret is None:
                continue

            ew30 = statistics.mean(rets_30)
            results["ew_top30"][h].append(ew30 - xbi_ret)
            rec[f"{hk}_ew30"] = round((ew30 - xbi_ret) * 100, 2)

            # Pruned by inst_delta_z
            rets_idz = []
            for t in pruned_idz:
                ret = forward_return(prices.get(t, {}), snap_date, h)
                if ret is not None:
                    rets_idz.append(ret)
            if rets_idz:
                ew20_idz = statistics.mean(rets_idz)
                results["pruned_idz_top20"][h].append(ew20_idz - xbi_ret)
                rec[f"{hk}_idz20"] = round((ew20_idz - xbi_ret) * 100, 2)
                rec[f"{hk}_idz_vs_ew30"] = round((ew20_idz - ew30) * 100, 2)

            # Pruned by joint signal
            if pruned_joint and include_aact:
                rets_joint = []
                for t in pruned_joint:
                    ret = forward_return(prices.get(t, {}), snap_date, h)
                    if ret is not None:
                        rets_joint.append(ret)
                if rets_joint:
                    ew20_joint = statistics.mean(rets_joint)
                    results["pruned_joint_top20"][h].append(ew20_joint - xbi_ret)
                    rec[f"{hk}_joint20"] = round((ew20_joint - xbi_ret) * 100, 2)
                    rec[f"{hk}_joint_vs_ew30"] = round((ew20_joint - ew30) * 100, 2)
                    rec[f"{hk}_joint_vs_idz"] = round((ew20_joint - ew20_idz) * 100, 2)

        records.append(rec)

    # --- Report ---
    print(f"\n{'='*70}")
    print(f"PRUNER BACKTEST — {len(records)} months")
    print(f"{'='*70}")

    for h in horizons:
        print(f"\n--- {h}d horizon ---\n")
        print(f"  {'Strategy':<25s} {'Mean':>8s} {'Cum':>8s} {'Hit':>6s} {'IR':>6s} {'N':>4s}")
        print(f"  {'-'*60}")

        for strat in strats:
            rets = results[strat][h]
            if not rets:
                continue
            mean_r = statistics.mean(rets) * 100
            cum_r = sum(rets) * 100
            hit = sum(1 for r in rets if r > 0) / len(rets)
            std_r = statistics.stdev(rets) * 100 if len(rets) > 1 else 0
            ir = mean_r / std_r if std_r > 0 else 0
            print(f"  {strat:<25s} {mean_r:>+7.2f}pp {cum_r:>+7.0f}pp {hit:>5.0%} {ir:>5.2f} {len(rets):>4d}")

        # Spread: pruned vs EW30
        ew30_rets = results["ew_top30"][h]
        idz_rets = results["pruned_idz_top20"][h]
        if ew30_rets and idz_rets and len(ew30_rets) == len(idz_rets):
            spreads = [(a - b) * 100 for a, b in zip(idz_rets, ew30_rets)]
            net_spreads = [s - MONTHLY_COST_DIFF_PP for s in spreads]
            print("\n  IDZ Top-20 vs EW Top-30:")
            print(f"    Gross: {statistics.mean(spreads):+.2f}pp/mo, cum={sum(spreads):+.0f}pp")
            print(f"    Net:   {statistics.mean(net_spreads):+.2f}pp/mo, cum={sum(net_spreads):+.0f}pp")

    # Yearly breakdown for the primary comparison
    print(f"\n{'='*70}")
    print("YEARLY: IDZ Top-20 vs EW Top-30 (63d excess vs XBI)")
    print(f"{'='*70}")

    if 63 in horizons:
        yearly_30: dict[str, list] = defaultdict(list)
        yearly_20: dict[str, list] = defaultdict(list)
        for rec in records:
            yr = rec["date"][:4]
            if "h63_ew30" in rec:
                yearly_30[yr].append(rec["h63_ew30"])
            if "h63_idz20" in rec:
                yearly_20[yr].append(rec["h63_idz20"])

        print(f"\n  {'Year':<6s} {'EW30':>8s} {'IDZ20':>8s} {'Spread':>8s} {'N':>4s}")
        print(f"  {'-'*40}")
        for yr in sorted(set(yearly_30.keys()) | set(yearly_20.keys())):
            r30 = yearly_30.get(yr, [])
            r20 = yearly_20.get(yr, [])
            m30 = statistics.mean(r30) if r30 else 0
            m20 = statistics.mean(r20) if r20 else 0
            n = min(len(r30), len(r20))
            print(f"  {yr:<6s} {m30:>+7.2f}pp {m20:>+7.2f}pp {m20 - m30:>+7.2f}pp {n:>4d}")

    # Save
    output = {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "start": start,
        "include_aact": include_aact,
        "n_months": len(records),
        "strategies": {s: {} for s in strats},
        "records": records,
    }
    for strat in strats:
        for h in horizons:
            rets = results[strat][h]
            if rets:
                std_r = statistics.stdev(rets) if len(rets) > 1 else 0
                output["strategies"][strat][str(h)] = {
                    "mean_excess_pp": round(statistics.mean(rets) * 100, 2),
                    "cum_excess_pp": round(sum(rets) * 100, 1),
                    "hit_rate": round(sum(1 for r in rets if r > 0) / len(rets), 2),
                    "ir": round(statistics.mean(rets) * 100 / (std_r * 100) if std_r > 0 else 0, 2),
                    "n": len(rets),
                }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / "pruner_backtest.json"
    out_path.write_text(json.dumps(output, indent=2, default=str))
    print(f"\nSaved: {out_path}")

    return output


def main():
    parser = argparse.ArgumentParser(description="Stage-2 pruner backtest")
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--horizons", default="20,63")
    parser.add_argument("--include-aact", action="store_true")
    args = parser.parse_args()

    horizons = [int(h) for h in args.horizons.split(",")]
    run_backtest(args.start, args.include_aact, horizons)


if __name__ == "__main__":
    main()
