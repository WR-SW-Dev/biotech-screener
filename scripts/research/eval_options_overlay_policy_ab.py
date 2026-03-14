#!/usr/bin/env python3
"""A/B evaluation: options construction overlay.

Compares two arms using the same snapshots, rankings, and ruleset:
  A = baseline (options_overlay disabled in policy)
  B = treatment (options_overlay enabled in policy)

No re-ranking — only portfolio construction differs.

Standard acceptance bars:
  - cumulative hedged delta >= +0.20pp
  - mean weekly hedged delta >= -0.05pp
  - turnover increase <= +0.25pp

Usage:
    python3 scripts/research/eval_options_overlay_policy_ab.py \\
        --snapshot-root data/snapshots \\
        --date-from 2026-03-01 \\
        --out-dir output/research/options_overlay_policy_ab
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "research"))
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from eval_calendar_expansion_ab import (
    PRICE_HISTORY_DEFAULT,
    _cumulative,
    _safe_mean,
    compute_period_return,
    compute_turnover,
    discover_dates,
    load_prices,
)
from live_shadow_portfolio import BUCKET_NAMES, build_positions, load_policy, load_rankings

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------


def preflight_check(
    snap_root: Path,
    dates: List[str],
) -> Dict[str, Any]:
    """Check options data coverage across snapshots."""
    total_rows = 0
    rows_with_oqc = 0
    rows_with_opt = 0
    rows_31_90 = 0
    rows_0_30 = 0

    for d in dates[:10]:  # sample first 10
        csv_path = snap_root / d / "rankings.csv"
        if not csv_path.exists():
            continue
        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                total_rows += 1
                if r.get("options_quality_composite", "").strip() not in ("", "0", "0.0"):
                    rows_with_oqc += 1
                if r.get("opt_has_data", "") == "1":
                    rows_with_opt += 1
                try:
                    cd = int(float(r.get("catalyst_days", "") or "9999"))
                except (ValueError, TypeError):
                    cd = 9999
                if 31 <= cd <= 90:
                    rows_31_90 += 1
                elif 0 < cd <= 30:
                    rows_0_30 += 1

    return {
        "total_rows_sampled": total_rows,
        "rows_with_oqc": rows_with_oqc,
        "rows_with_opt_data": rows_with_opt,
        "rows_binary_31_90": rows_31_90,
        "rows_binary_0_30": rows_0_30,
        "dates_sampled": min(len(dates), 10),
        "valid": rows_with_opt > 0,
    }


# ---------------------------------------------------------------------------
# Arms
# ---------------------------------------------------------------------------


def run_arm(
    arm_name: str,
    snap_root: Path,
    rebal_dates: List[str],
    prices: Dict[str, Dict[str, float]],
    policy: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], int]:
    """Simulate weekly-rebalanced portfolio for one arm."""
    results = []
    prev_positions: List[Dict[str, Any]] = []
    n_overlay_active = 0

    for i in range(len(rebal_dates) - 1):
        entry_date = rebal_dates[i]
        exit_date = rebal_dates[i + 1]

        snap_dir = snap_root / entry_date
        if not (snap_dir / "rankings.csv").exists():
            continue

        rankings = load_rankings(snap_dir)
        pos_data = build_positions(rankings, policy)
        positions = pos_data["positions"]

        # Count overlay-affected positions
        n_up = sum(1 for p in positions if p.get("options_overlay_multiplier", 1.0) > 1.0)
        n_down = sum(1 for p in positions if p.get("options_overlay_multiplier", 1.0) < 1.0)
        n_review = sum(1 for p in positions if p.get("options_review_required"))
        if n_up > 0 or n_down > 0:
            n_overlay_active += 1

        turnover = compute_turnover(prev_positions, positions)
        period = compute_period_return(
            positions,
            prices,
            entry_date,
            exit_date,
            cost_bps=30.0,
            turnover_frac=turnover,
        )

        row = {
            "arm": arm_name,
            "entry_date": entry_date,
            "exit_date": exit_date,
            "n_positions": len(positions),
            "turnover": round(turnover, 4),
            "hedged_return": period["hedged_return"],
            "net_return": period["net_return"],
            "n_overlay_up": n_up,
            "n_overlay_down": n_down,
            "n_overlay_review": n_review,
        }
        for b in BUCKET_NAMES:
            ba = period["bucket_attr"].get(b, {})
            row[f"{b}_hedged"] = ba.get("hedged_return")

        results.append(row)
        prev_positions = positions

    return results, n_overlay_active


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------


def compute_verdict(
    agg_baseline: Dict[str, Any],
    agg_treatment: Dict[str, Any],
    n_overlay_active: int,
    n_periods: int,
) -> Dict[str, Any]:
    """Apply pass/fail thresholds."""
    cum_b = agg_baseline.get("cum_hedged") or 0
    cum_t = agg_treatment.get("cum_hedged") or 0
    mean_b = agg_baseline.get("mean_hedged") or 0
    mean_t = agg_treatment.get("mean_hedged") or 0
    turn_b = agg_baseline.get("mean_turnover") or 0
    turn_t = agg_treatment.get("mean_turnover") or 0

    delta_cum = (cum_t - cum_b) * 100
    delta_mean = (mean_t - mean_b) * 100
    delta_turnover = (turn_t - turn_b) * 100

    cum_pass = delta_cum >= 0.20
    mean_pass = delta_mean >= -0.05
    turn_pass = delta_turnover <= 0.25

    if n_overlay_active == 0:
        verdict = "INVALID_NOOP"
    elif mean_pass and turn_pass and cum_pass:
        verdict = "PASS"
    elif mean_pass and turn_pass and not cum_pass:
        # Check NEEDS_MORE_BUT_SAFE
        b31_b = agg_baseline.get("binary_31_90_cum_hedged") or 0
        b31_t = agg_treatment.get("binary_31_90_cum_hedged") or 0
        if (b31_t - b31_b) >= 0:
            verdict = "NEEDS_MORE_BUT_SAFE"
        else:
            verdict = "WARN"
    else:
        verdict = "FAIL"

    return {
        "verdict": verdict,
        "delta_cum_hedged_pp": round(delta_cum, 2),
        "delta_mean_hedged_pp": round(delta_mean, 2),
        "delta_turnover_pp": round(delta_turnover, 2),
        "cum_pass": cum_pass,
        "mean_pass": mean_pass,
        "turn_pass": turn_pass,
        "overlay_active_periods": n_overlay_active,
        "total_periods": n_periods,
    }


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def _fmt_pct(v, dp=2):
    if v is None:
        return "---"
    return f"{v * 100:.{dp}f}%"


def _delta_pp(cand, base):
    if cand is None or base is None:
        return "---"
    d = (cand - base) * 100
    sign = "+" if d >= 0 else ""
    return f"{sign}{d:.2f}pp"


def write_outputs(
    arm_results: Dict[str, List[Dict[str, Any]]],
    verdict: Dict[str, Any],
    preflight: Dict[str, Any],
    out_dir: Path,
    snap_root_name: str,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)

    agg = {}
    for arm, results in arm_results.items():
        hedged = [r["hedged_return"] for r in results]
        net = [r["net_return"] for r in results]
        turnover = [r["turnover"] for r in results]
        agg[arm] = {
            "n_periods": len(results),
            "mean_hedged": _safe_mean(hedged),
            "cum_hedged": _cumulative(hedged),
            "mean_net": _safe_mean(net),
            "cum_net": _cumulative(net),
            "mean_turnover": _safe_mean(turnover),
        }
        for b in BUCKET_NAMES:
            bh = [r.get(f"{b}_hedged") for r in results]
            agg[arm][f"{b}_mean_hedged"] = _safe_mean(bh)
            agg[arm][f"{b}_cum_hedged"] = _cumulative(bh)

    arms = list(agg.keys())
    baseline = arms[0]
    treatment_arms = arms[1:]

    # Overlay diagnostics from treatment arm
    treatment_results = arm_results.get(treatment_arms[0], []) if treatment_arms else []
    n_up_total = sum(r.get("n_overlay_up", 0) for r in treatment_results)
    n_down_total = sum(r.get("n_overlay_down", 0) for r in treatment_results)

    # Markdown
    lines = [
        "# Options Construction Overlay A/B",
        "",
        f"**Snapshot root**: `{snap_root_name}`",
        f"**Periods**: {agg[baseline]['n_periods']}",
        "",
        "## Preflight Coverage",
        "",
        f"- Rows sampled: {preflight['total_rows_sampled']}",
        f"- With OQC: {preflight['rows_with_oqc']}",
        f"- With opt_data: {preflight['rows_with_opt_data']}",
        f"- In binary_31_90: {preflight['rows_binary_31_90']}",
        f"- In binary_0_30: {preflight['rows_binary_0_30']}",
        "",
        "## Returns",
        "",
    ]

    header = "| Metric |"
    sep = "|--------|"
    for arm in arms:
        header += f" {arm} |"
        sep += "-------------|"
    lines.append(header)
    lines.append(sep)
    for name, key in [
        ("Mean weekly hedged", "mean_hedged"),
        ("Cumulative hedged", "cum_hedged"),
        ("Mean turnover", "mean_turnover"),
    ]:
        row_line = f"| {name} |"
        for arm in arms:
            row_line += f" {_fmt_pct(agg[arm][key])} |"
        lines.append(row_line)
    lines.append("")

    lines.append("## Delta vs Baseline")
    lines.append("")
    for arm in treatment_arms:
        lines.append(f"- Cum hedged: {_delta_pp(agg[arm]['cum_hedged'], agg[baseline]['cum_hedged'])}")
        lines.append(f"- Mean hedged: {_delta_pp(agg[arm]['mean_hedged'], agg[baseline]['mean_hedged'])}")
        lines.append(f"- Turnover: {_delta_pp(agg[arm]['mean_turnover'], agg[baseline]['mean_turnover'])}")
    lines.append("")

    lines.append("## Overlay Diagnostics")
    lines.append("")
    lines.append(f"- Active periods: {verdict['overlay_active_periods']}/{verdict['total_periods']}")
    lines.append(f"- Total upsizes: {n_up_total}")
    lines.append(f"- Total downsizes: {n_down_total}")
    lines.append("")

    lines.append(f"## Verdict: **{verdict['verdict']}**")
    lines.append("")
    lines.append(
        f"- cum_hedged_delta: {verdict['delta_cum_hedged_pp']:+.2f}pp {'PASS' if verdict['cum_pass'] else 'FAIL'}"
    )
    lines.append(
        f"- mean_hedged_delta: {verdict['delta_mean_hedged_pp']:+.2f}pp {'PASS' if verdict['mean_pass'] else 'FAIL'}"
    )
    lines.append(
        f"- turnover_delta: {verdict['delta_turnover_pp']:+.2f}pp {'PASS' if verdict['turn_pass'] else 'FAIL'}"
    )
    lines.append("")

    md_path = out_dir / "SUMMARY.md"
    md_path.write_text("\n".join(lines))

    # JSON receipt
    receipt = {
        "arms": agg,
        "verdict": verdict,
        "preflight": preflight,
        "overlay_diagnostics": {
            "n_up_total": n_up_total,
            "n_down_total": n_down_total,
        },
    }
    json_path = out_dir / "AB_RECEIPT.json"
    with open(json_path, "w") as f:
        json.dump(receipt, f, indent=2, default=str)
        f.write("\n")

    # CSV
    csv_path = out_dir / "RESULTS.csv"
    all_results = []
    for results in arm_results.values():
        all_results.extend(results)
    if all_results:
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(all_results[0].keys()))
            writer.writeheader()
            writer.writerows(all_results)

    return md_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    p = argparse.ArgumentParser(description="A/B: options construction overlay")
    p.add_argument("--snapshot-root", type=Path, required=True)
    p.add_argument("--policy", type=Path, default=PROJECT_ROOT / "production_data" / "portfolio_policy.json")
    p.add_argument("--price-csv", type=Path, default=PRICE_HISTORY_DEFAULT)
    p.add_argument("--date-from", type=str, default=None)
    p.add_argument("--date-to", type=str, default=None)
    p.add_argument("--out-dir", type=Path, default=PROJECT_ROOT / "output" / "research" / "options_overlay_policy_ab")
    p.add_argument("--min-active-periods", type=int, default=4)
    args = p.parse_args()

    dates = discover_dates(args.snapshot_root)
    if args.date_from:
        dates = [d for d in dates if d >= args.date_from]
    if args.date_to:
        dates = [d for d in dates if d <= args.date_to]
    print(f"Snapshot dates: {len(dates)}")

    if len(dates) < 2:
        print("ERROR: Need at least 2 dates for A/B")
        return 1

    # Preflight
    preflight = preflight_check(args.snapshot_root, dates)
    print(f"Preflight: {preflight}")
    if not preflight["valid"]:
        print("WARNING: No options data in sampled snapshots — results will be INVALID_DATA")

    print("Loading prices...")
    prices = load_prices(args.price_csv)
    print(f"  {len(prices)} tickers")

    # Load base policy
    base_policy = load_policy(args.policy)

    # Arm A: baseline (overlay off)
    policy_a = deepcopy(base_policy)
    policy_a.pop("options_overlay", None)

    # Arm B: treatment (overlay on)
    policy_b = deepcopy(base_policy)
    policy_b["options_overlay"] = {
        "enabled": True,
        "options_fresh": True,
        "crowding_panel_populated": False,
    }

    print("\nRunning baseline...")
    results_a, _ = run_arm("baseline", args.snapshot_root, dates, prices, policy_a)
    print(f"  {len(results_a)} periods")

    print("Running treatment (overlay ON)...")
    results_b, n_active = run_arm("overlay_ON", args.snapshot_root, dates, prices, policy_b)
    print(f"  {len(results_b)} periods, {n_active} overlay-active")

    # Aggregate for verdict
    agg_a = {
        "cum_hedged": _cumulative([r["hedged_return"] for r in results_a]),
        "mean_hedged": _safe_mean([r["hedged_return"] for r in results_a]),
        "mean_turnover": _safe_mean([r["turnover"] for r in results_a]),
    }
    agg_b = {
        "cum_hedged": _cumulative([r["hedged_return"] for r in results_b]),
        "mean_hedged": _safe_mean([r["hedged_return"] for r in results_b]),
        "mean_turnover": _safe_mean([r["turnover"] for r in results_b]),
        "binary_31_90_cum_hedged": _cumulative([r.get("binary_31_90_hedged") for r in results_b]),
    }

    verdict = compute_verdict(agg_a, agg_b, n_active, len(results_b))
    print(f"\nVerdict: {verdict['verdict']}")

    arm_results = {"baseline": results_a, "overlay_ON": results_b}
    md_path = write_outputs(arm_results, verdict, preflight, args.out_dir, args.snapshot_root.name)
    print(f"Summary: {md_path}")

    return 0 if verdict["verdict"] in ("PASS", "NEEDS_MORE_BUT_SAFE") else 1


if __name__ == "__main__":
    sys.exit(main())
