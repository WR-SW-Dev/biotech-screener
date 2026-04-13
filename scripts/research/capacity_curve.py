#!/usr/bin/env python3
"""Capacity curve — capital vs Sharpe/return under execution friction.

Architecture: Trap T20 → B6 rank → conviction sizing (α=1.5)
Impact model: cost_bps = fixed_bps + a * participation^b
"""

from __future__ import annotations

import csv
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from event_ev.expectation_error_model import ExpectationErrorModel
from event_ev.portfolio_sizing import compute_weights
from scripts.eval_forward_returns import (
    compute_forward_return,
    discover_snapshot_dates,
    load_price_series,
    load_rankings,
    resolve_trade_date,
)

TOP_K = 30
HORIZON = 20
ALPHA = 1.5
model = ExpectationErrorModel()

# Impact model parameters
FIXED_BPS = 15  # round-trip floor
IMPACT_A = 35
IMPACT_B = 0.60

CAPITAL_GRID = [100_000, 250_000, 500_000, 1_000_000, 2_500_000, 5_000_000, 10_000_000, 25_000_000, 50_000_000]


def impact_cost_bps(participation: float) -> float:
    """Participation-based impact: a * participation^b + fixed floor."""
    if participation <= 0:
        return FIXED_BPS
    return FIXED_BPS + IMPACT_A * (participation**IMPACT_B)


def run_capacity_curve(
    snapshot_root: Path,
    price_csv: Path,
    volume_data: Dict[str, Dict[str, float]],
    date_from: str = "2022-03-18",
    date_to: str = "2026-03-31",
) -> Dict[str, Any]:
    snap_dates = discover_snapshot_dates(snapshot_root, date_from, date_to)
    prices = load_price_series(price_csv)

    all_dates_set: set = set()
    for tp in prices.values():
        all_dates_set.update(tp.keys())
    sorted_dates = sorted(all_dates_set)

    # Per-capital-level accumulators
    results_by_cap: Dict[int, Dict[str, list]] = {
        cap: {
            "gross_rets": [],
            "net_rets": [],
            "turnovers": [],
            "max_participations": [],
            "median_participations": [],
            "pct_above_1": [],
            "pct_above_3": [],
            "pct_above_5": [],
            "pct_above_10": [],
        }
        for cap in CAPITAL_GRID
    }

    # Track prior holdings for turnover
    prior_holdings: Dict[int, Dict[str, float]] = {cap: {} for cap in CAPITAL_GRID}
    n_dates = 0

    # Top stress names accumulator
    stress_names: Dict[str, List[float]] = defaultdict(list)

    for snap_date in snap_dates:
        trade_date = resolve_trade_date(sorted_dates, snap_date, "next_trading_day")
        if not trade_date:
            continue

        rankings = load_rankings(snapshot_root / snap_date)
        if not rankings:
            continue

        scores = model.score_batch(rankings, snap_date)
        if not scores:
            continue

        by_ticker = {s.ticker: s for s in scores}
        b6_map = {}
        for row in rankings:
            t = row.get("ticker", "")
            sel = row.get("selector_score", "")
            if t and sel and sel.strip() not in ("", "None", "nan"):
                try:
                    b6_map[t] = float(sel)
                except (ValueError, TypeError):
                    pass

        if len(b6_map) < 20:
            continue

        trap_vals = [by_ticker[t].trap_overlay_score for t in by_ticker if t in b6_map]
        if len(set(round(v, 6) for v in trap_vals)) <= 2:
            continue
        t_thresh = sorted(trap_vals)[min(int(len(trap_vals) * 0.20), len(trap_vals) - 1)]
        eligible = [t for t in by_ticker if t in b6_map and by_ticker[t].trap_overlay_score > t_thresh]

        ranked = sorted(eligible, key=lambda t: b6_map[t], reverse=True)[:TOP_K]

        fwd = {}
        for t in ranked:
            if t in prices:
                ret = compute_forward_return(prices[t], sorted_dates, trade_date, HORIZON)
                if ret is not None:
                    fwd[t] = ret

        active = [t for t in ranked if t in fwd]
        if len(active) < 10:
            continue

        trap_map = {t: by_ticker[t].trap_overlay_score for t in active}

        # Dollar volumes (20d lookback)
        dv_map: Dict[str, float] = {}
        for t in active:
            dv_hist = volume_data.get(t, {})
            recent = sorted(d for d in dv_hist if d <= snap_date)[-20:]
            if recent:
                dv_map[t] = statistics.mean(dv_hist[d] for d in recent)

        # Weights (no liquidity cap — as validated)
        weights = compute_weights(active, b6_map, trap_map, alpha=ALPHA)

        n_dates += 1

        # Gross return (same for all capital levels)
        gross_ret = sum(fwd[t] * weights.get(t, 0) for t in active)

        for cap in CAPITAL_GRID:
            # Dollar orders per name
            participations = []
            costs_weighted = 0.0
            total_trade_dollars = 0.0

            for t in active:
                w = weights.get(t, 0)
                if w <= 0:
                    continue

                target_dollars = cap * w
                dv = dv_map.get(t, 0)

                # Turnover: difference from prior
                prior_w = prior_holdings[cap].get(t, 0)
                trade_dollars = abs(target_dollars - prior_w * cap)
                total_trade_dollars += trade_dollars

                if dv > 0:
                    participation = trade_dollars / dv
                    participations.append(participation)
                    cost = impact_cost_bps(participation)
                    costs_weighted += w * cost / 10000  # convert bps to fraction
                    stress_names[t].append(participation)
                else:
                    participations.append(1.0)  # illiquid
                    costs_weighted += w * impact_cost_bps(1.0) / 10000

            net_ret = gross_ret - costs_weighted

            # Turnover
            turnover = total_trade_dollars / cap if cap > 0 else 0

            # Participation stats
            if participations:
                max_p = max(participations)
                med_p = statistics.median(participations)
                n_trades = len(participations)
                pct_1 = sum(1 for p in participations if p > 0.01) / n_trades
                pct_3 = sum(1 for p in participations if p > 0.03) / n_trades
                pct_5 = sum(1 for p in participations if p > 0.05) / n_trades
                pct_10 = sum(1 for p in participations if p > 0.10) / n_trades
            else:
                max_p = med_p = 0
                pct_1 = pct_3 = pct_5 = pct_10 = 0

            r = results_by_cap[cap]
            r["gross_rets"].append(gross_ret)
            r["net_rets"].append(net_ret)
            r["turnovers"].append(turnover)
            r["max_participations"].append(max_p)
            r["median_participations"].append(med_p)
            r["pct_above_1"].append(pct_1)
            r["pct_above_3"].append(pct_3)
            r["pct_above_5"].append(pct_5)
            r["pct_above_10"].append(pct_10)

            # Update prior holdings
            prior_holdings[cap] = {t: weights.get(t, 0) for t in active}

    # Aggregate
    table = []
    for cap in CAPITAL_GRID:
        r = results_by_cap[cap]
        gross = r["gross_rets"]
        net = r["net_rets"]
        if not gross:
            continue

        def _sharpe(rets):
            m = statistics.mean(rets)
            s = statistics.stdev(rets) if len(rets) >= 2 else 0.001
            return m / s if s > 0 else 0

        table.append(
            {
                "capital": cap,
                "capital_label": f"${cap/1e6:.1f}M" if cap >= 1e6 else f"${cap/1e3:.0f}K",
                "gross_mean_pct": round(statistics.mean(gross) * 100, 4),
                "net_mean_pct": round(statistics.mean(net) * 100, 4),
                "gross_sharpe": round(_sharpe(gross), 3),
                "net_sharpe": round(_sharpe(net), 3),
                "hit_rate": round(sum(1 for r in net if r > 0) / len(net), 3),
                "avg_turnover": round(statistics.mean(r["turnovers"]), 4),
                "max_participation": round(max(r["max_participations"]), 4),
                "median_participation": round(statistics.median(r["median_participations"]), 6),
                "pct_above_1_adv": round(statistics.mean(r["pct_above_1"]) * 100, 1),
                "pct_above_3_adv": round(statistics.mean(r["pct_above_3"]) * 100, 1),
                "pct_above_5_adv": round(statistics.mean(r["pct_above_5"]) * 100, 1),
                "pct_above_10_adv": round(statistics.mean(r["pct_above_10"]) * 100, 1),
                "n_dates": len(gross),
            }
        )

    # Thresholds
    baseline_sharpe = table[0]["net_sharpe"] if table else 0
    soft_cap = None
    hard_cap = None
    for row in table:
        if soft_cap is None and row["net_sharpe"] < baseline_sharpe * 0.90:
            soft_cap = row["capital_label"]
        if hard_cap is None and row["net_sharpe"] < baseline_sharpe * 0.75:
            hard_cap = row["capital_label"]

    # Top stress names
    top_stress = sorted(stress_names.items(), key=lambda x: max(x[1]), reverse=True)[:10]

    return {
        "n_dates": n_dates,
        "impact_model": {"fixed_bps": FIXED_BPS, "a": IMPACT_A, "b": IMPACT_B},
        "table": table,
        "baseline_sharpe": baseline_sharpe,
        "soft_capacity": soft_cap or "beyond grid",
        "hard_capacity": hard_cap or "beyond grid",
        "top_stress_names": [
            {"ticker": t, "max_participation": round(max(ps), 4), "mean_participation": round(statistics.mean(ps), 6)}
            for t, ps in top_stress
        ],
    }


def main():
    snapshot_root = PROJECT_ROOT / "data" / "snapshots"
    price_csv = PROJECT_ROOT / "production_data" / "price_history.csv"
    out_dir = PROJECT_ROOT / "output" / "capacity_curve"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Load volume data
    print("Loading volume data...")
    volume_data: Dict[str, Dict[str, float]] = {}
    with open(price_csv) as f:
        for row in csv.DictReader(f):
            t = row.get("ticker", "").strip()
            d = row.get("date", "").strip()
            v = row.get("volume", "").strip()
            c = row.get("close", "").strip()
            if t and d and v and c and v not in ("", "None", "nan", "0", "0.0"):
                try:
                    volume_data.setdefault(t, {})[d] = float(v) * float(c)
                except (ValueError, TypeError):
                    pass

    print("Running capacity curve...")
    results = run_capacity_curve(snapshot_root, price_csv, volume_data)

    with open(out_dir / "capacity_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)

    # Print report
    print(f"\n{'=' * 90}")
    print("  CAPACITY CURVE — Trap T20 → B6 rank → conviction α=1.5")
    print(f"  Impact: {FIXED_BPS}bps fixed + {IMPACT_A}×participation^{IMPACT_B}")
    print(f"  {results['n_dates']} dates evaluated")
    print(f"{'=' * 90}\n")

    header = (
        f"{'Capital':>10s} {'Gross%':>8s} {'Net%':>8s} {'G-Sharpe':>9s} {'N-Sharpe':>9s}"
        f" {'Hit%':>6s} {'Turn':>6s} {'MaxP':>7s} {'>1%ADV':>7s} {'>5%ADV':>7s} {'>10%ADV':>8s}"
    )
    print(header)
    print("-" * 90)

    for row in results["table"]:
        print(
            f"{row['capital_label']:>10s}"
            f" {row['gross_mean_pct']:>+7.3f}%"
            f" {row['net_mean_pct']:>+7.3f}%"
            f" {row['gross_sharpe']:>+8.3f}"
            f" {row['net_sharpe']:>+8.3f}"
            f" {row['hit_rate']:>5.0%}"
            f" {row['avg_turnover']:>5.1%}"
            f" {row['max_participation']:>6.1%}"
            f" {row['pct_above_1_adv']:>6.1f}%"
            f" {row['pct_above_5_adv']:>6.1f}%"
            f" {row['pct_above_10_adv']:>7.1f}%"
        )

    print(f"\nBaseline net Sharpe (${CAPITAL_GRID[0]/1e3:.0f}K): {results['baseline_sharpe']:.3f}")
    print(f"Soft capacity (10% decay): {results['soft_capacity']}")
    print(f"Hard capacity (25% decay): {results['hard_capacity']}")

    print("\nTop stress names (highest participation):")
    for s in results["top_stress_names"][:5]:
        print(f"  {s['ticker']:6s}  max_participation={s['max_participation']:.1%}  mean={s['mean_participation']:.4%}")

    print(f"\nWritten: {out_dir / 'capacity_results.json'}")


if __name__ == "__main__":
    main()
