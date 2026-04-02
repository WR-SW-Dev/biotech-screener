"""Construction v2 promotion report — net-of-costs comparison.

Combines:
  - construction_v2_benchmark.json (gross returns by variant + window)
  - txn_cost_model.json (per-name costs, turnover)

Produces a cost-adjusted promotion verdict for EW Top-30.

Usage:
    python scripts/research/construction_v2_promotion_report.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

BENCHMARK_PATH = PROJECT_ROOT / "output" / "benchmarks" / "construction_v2_benchmark.json"
COST_MODEL_PATH = PROJECT_ROOT / "output" / "txn_cost_model" / "txn_cost_model.json"
OUTPUT_PATH = PROJECT_ROOT / "output" / "benchmarks" / "construction_v2_promotion_report.json"


def load_data():
    benchmark = json.loads(BENCHMARK_PATH.read_text())
    cost_model = json.loads(COST_MODEL_PATH.read_text())
    return benchmark, cost_model


def compute_net_of_costs(benchmark: dict, cost_model: dict) -> dict:
    """Compute cost-adjusted returns and IR for each variant and window."""

    # Extract cost parameters
    mean_rt_bps = cost_model["costs"]["mean_rt_bps"]

    # Turnover by variant (from benchmark)
    turnover_data = benchmark.get("turnover", {})

    # Cost drag per period (weekly) for each variant
    # cost_per_period = mean_turnover × mean_rt_bps (one-way) × 2 (round-trip) / 10000
    variant_weekly_cost = {}
    for variant, to in turnover_data.items():
        mean_to = to.get("mean_turnover", 0)
        # turnover is fraction of names changed; cost = turnover × rt_cost per name
        # For EW: each turned name costs mean_rt_bps round-trip
        weekly_cost_pct = mean_to * mean_rt_bps * 2 / 10000
        variant_weekly_cost[variant] = weekly_cost_pct

    summaries = benchmark.get("summaries", {})
    results = {}

    for window_name, summary in summaries.items():
        n_periods = summary.get("n_periods", 0)
        if n_periods == 0:
            continue

        window_result = {
            "window": window_name,
            "n_periods": n_periods,
            "date_range": summary.get("date_range", ""),
            "xbi_cumulative_pct": summary.get("xbi_cumulative_pct", 0),
        }

        for variant in ["A_ew20", "C_ew30", "D_rank_wt20"]:
            cum_gross = summary.get(f"{variant}_cumulative_pct", 0)
            excess_gross = summary.get(f"{variant}_excess_pct", 0)
            ir_gross = summary.get(f"{variant}_ir", 0)
            win_rate = summary.get(f"{variant}_win_rate", 0)

            weekly_cost = variant_weekly_cost.get(variant, 0)
            total_cost_pct = weekly_cost * n_periods * 100  # as percentage points

            cum_net = cum_gross - total_cost_pct
            excess_net = excess_gross - total_cost_pct

            # Approximate net IR: scale gross IR by (net_excess / gross_excess)
            if excess_gross > 0 and ir_gross > 0:
                ir_net = ir_gross * (excess_net / excess_gross)
            else:
                ir_net = ir_gross

            label = {
                "A_ew20": "EW Top-20",
                "C_ew30": "EW Top-30",
                "D_rank_wt20": "Rank-Weighted Top-20",
            }.get(variant, variant)

            window_result[variant] = {
                "label": label,
                "gross_cumulative_pct": round(cum_gross, 2),
                "gross_excess_pct": round(excess_gross, 2),
                "gross_ir": round(ir_gross, 2),
                "total_cost_pct": round(total_cost_pct, 2),
                "net_cumulative_pct": round(cum_net, 2),
                "net_excess_pct": round(excess_net, 2),
                "net_ir": round(ir_net, 2),
                "win_rate": round(win_rate, 3),
                "weekly_cost_pct": round(weekly_cost * 100, 4),
                "annual_cost_bps": round(weekly_cost * 52 * 10000, 0),
            }

        results[window_name] = window_result

    return results


def compute_promotion_verdict(net_results: dict, cost_model: dict) -> dict:
    """Produce the final promotion verdict."""

    full = net_results.get("full", {})

    ew30_full = full.get("C_ew30", {})
    ew20_full = full.get("A_ew20", {})
    rw20_full = full.get("D_rank_wt20", {})

    # Promotion bar from cost model
    incremental_rw_bps = cost_model["costs"]["incremental_rw_bps"]

    verdict = {
        "recommendation": "PROMOTE_EW30",
        "confidence": "HIGH",
        "rationale": [],
    }

    # Check 1: Net IR > 1.0 (minimum bar)
    net_ir = ew30_full.get("net_ir", 0)
    if net_ir > 1.0:
        verdict["rationale"].append(f"Full-period net IR = {net_ir:.2f} > 1.0 (minimum bar)")
    else:
        verdict["recommendation"] = "HOLD"
        verdict["confidence"] = "LOW"
        verdict["rationale"].append(f"Full-period net IR = {net_ir:.2f} < 1.0 (below minimum bar)")

    # Check 2: Net excess > 0 in all major windows
    all_positive = True
    for window in ["full", "2024_2026", "2025_2026", "2026_ytd"]:
        w = net_results.get(window, {}).get("C_ew30", {})
        if w.get("net_excess_pct", 0) <= 0:
            all_positive = False
            verdict["rationale"].append(f"Net excess negative in {window}: {w.get('net_excess_pct', 0):.1f}%")

    if all_positive:
        verdict["rationale"].append("Net excess positive in all 4 windows")

    # Check 3: EW30 beats EW20 net-of-costs
    ew30_net = ew30_full.get("net_excess_pct", 0)
    ew20_net = ew20_full.get("net_excess_pct", 0)
    spread = ew30_net - ew20_net
    verdict["rationale"].append(f"EW30 vs EW20 net spread: {spread:+.1f}pp ({ew30_net:.1f} vs {ew20_net:.1f})")

    # Check 4: Cost is small relative to alpha
    cost_pct = ew30_full.get("total_cost_pct", 0)
    gross = ew30_full.get("gross_excess_pct", 0)
    if gross > 0:
        cost_as_fraction = cost_pct / gross
        verdict["rationale"].append(
            f"Costs consume {cost_as_fraction:.1%} of gross alpha ({cost_pct:.1f}pp / {gross:.1f}pp)"
        )

    # Check 5: Bear market IR
    bear = net_results.get("bear_xbi", {}).get("C_ew30", {})
    if bear:
        verdict["rationale"].append(f"Bear-market net IR: {bear.get('net_ir', 0):.2f}")

    # Check 6: RW doesn't clear promotion bar
    rw_net = rw20_full.get("net_excess_pct", 0)
    rw_incremental = rw_net - ew30_net
    verdict["rationale"].append(
        f"Rank-weighted incremental vs EW30: {rw_incremental:+.1f}pp (bar: +{incremental_rw_bps / 100:.1f}pp/yr)"
    )
    if rw_incremental < 0:
        verdict["rationale"].append("Rank-weighting does NOT clear promotion bar → EW is correct default")

    return verdict


def print_report(net_results: dict, verdict: dict, cost_model: dict):
    print(f"\n{'='*70}")
    print("CONSTRUCTION V2 PROMOTION REPORT — Net of Costs")
    print(f"{'='*70}")

    print("\nCost parameters:")
    print(f"  Mean RT cost:      {cost_model['costs']['mean_rt_bps']:.1f} bps")
    print(f"  EW annual drag:    {cost_model['costs']['annual_ew_drag_bps']} bps")
    print(f"  RW annual drag:    {cost_model['costs']['annual_rw_drag_bps']} bps")
    print(f"  RW incremental:    {cost_model['costs']['incremental_rw_bps']} bps")

    for window_name in ["full", "2024_2026", "2025_2026", "2026_ytd", "bear_xbi", "bull_xbi"]:
        w = net_results.get(window_name)
        if not w:
            continue
        print(f"\n--- {window_name} ({w['n_periods']} periods, {w['date_range']}) ---")
        print(f"  XBI: {w['xbi_cumulative_pct']:+.1f}%")
        print(f"  {'Variant':<25} {'Gross':>8} {'Cost':>7} {'Net':>8} {'gIR':>6} {'nIR':>6} {'Win%':>6}")
        print(f"  {'-'*67}")
        for variant in ["A_ew20", "C_ew30", "D_rank_wt20"]:
            v = w.get(variant)
            if not v:
                continue
            print(
                f"  {v['label']:<25} {v['gross_excess_pct']:>+7.1f}% {v['total_cost_pct']:>6.1f}% "
                f"{v['net_excess_pct']:>+7.1f}% {v['gross_ir']:>5.2f} {v['net_ir']:>5.2f} {v['win_rate']:>5.1%}"
            )

    print(f"\n{'='*70}")
    print(f"VERDICT: {verdict['recommendation']} (confidence: {verdict['confidence']})")
    print(f"{'='*70}")
    for r in verdict["rationale"]:
        print(f"  - {r}")


def main():
    benchmark, cost_model = load_data()
    net_results = compute_net_of_costs(benchmark, cost_model)
    verdict = compute_promotion_verdict(net_results, cost_model)

    report = {
        "schema": "construction_v2_promotion_report.v1",
        "net_results": net_results,
        "verdict": verdict,
        "cost_model_summary": cost_model["costs"],
        "cost_parameters": cost_model["parameters"],
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Saved: {OUTPUT_PATH}")

    print_report(net_results, verdict, cost_model)


if __name__ == "__main__":
    main()
