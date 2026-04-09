#!/usr/bin/env python3
"""A/B evaluation: regulatory confidence-weighted tilt.

Compares two arms using the same snapshot root + base policy:
  A = baseline (quality tilt ON, confidence tilt OFF)
  B = treatment (quality tilt ON, confidence tilt ON with default weights)

Uses weekly-rebalanced live-sim with the same acceptance bars as
eval_calendar_confidence_ab.py:
  - cumulative hedged delta >= +0.20pp
  - mean weekly hedged delta >= -0.05pp
  - turnover increase <= +0.25pp

Usage:
    python3 scripts/research/eval_regulatory_confidence_tilt_ab.py \
      --snapshot-root data/snapshots_reranked_v1100 \
      --date-from 2025-06-01 \
      --out-dir output/research/reg_conf_tilt_ab
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "research"))

from eval_calendar_expansion_ab import (
    PRICE_HISTORY_DEFAULT,
    compute_period_return,
    compute_turnover,
    discover_dates,
    enrich_with_calendar,
    load_calendar,
    load_prices,
)
from live_shadow_portfolio import BUCKET_NAMES, build_positions, load_policy, load_rankings

PDUFA_DEFAULT = PROJECT_ROOT / "production_data" / "pdufa_dates.json"


def _enrich_with_confidence(
    rankings: List[Dict[str, str]],
    calendar: List[Dict[str, str]],
) -> None:
    """Stamp regulatory_confidence on ranking rows from calendar entries."""
    conf_map: Dict[str, str] = {}
    for entry in calendar:
        ticker = (entry.get("ticker") or "").upper()
        conf = (entry.get("confidence") or "HIGH").upper()
        if ticker and ticker not in conf_map:
            conf_map[ticker] = conf
    for row in rankings:
        ticker = (row.get("ticker") or "").upper()
        if row.get("has_regulatory_upcoming_180d") == "1" and ticker in conf_map:
            row["regulatory_confidence"] = conf_map[ticker]
        else:
            row["regulatory_confidence"] = "HIGH"


def run_arm(
    arm_name: str,
    snap_root: Path,
    rebal_dates: List[str],
    prices: Dict[str, Dict[str, float]],
    policy: Dict[str, Any],
    calendar: List[Dict[str, str]],
    cost_bps: float = 30.0,
) -> Tuple[List[Dict[str, Any]], Dict[str, List[int]]]:
    """Simulate weekly-rebalanced portfolio for one arm."""
    results = []
    prev_positions: List[Dict[str, Any]] = []
    coverage: Dict[str, List[int]] = {}

    for i in range(len(rebal_dates) - 1):
        entry_date = rebal_dates[i]
        exit_date = rebal_dates[i + 1]

        snap_dir = snap_root / entry_date
        if not (snap_dir / "rankings.csv").exists():
            continue

        rankings = load_rankings(snap_dir)
        rankings, n_flagged = enrich_with_calendar(rankings, entry_date, calendar)
        _enrich_with_confidence(rankings, calendar)
        coverage[entry_date] = [len(rankings), n_flagged]

        pos_data = build_positions(rankings, policy)
        positions = pos_data["positions"]

        turnover = compute_turnover(prev_positions, positions)
        period = compute_period_return(
            positions,
            prices,
            entry_date,
            exit_date,
            cost_bps=cost_bps,
            turnover_frac=turnover,
        )

        row = {
            "arm": arm_name,
            "entry_date": entry_date,
            "exit_date": exit_date,
            "n_positions": len(positions),
            "n_regulatory": n_flagged,
            "turnover": round(turnover, 4),
            "hedged_return": period["hedged_return"],
            "net_return": period["net_return"],
        }
        for b in BUCKET_NAMES:
            ba = period["bucket_attr"].get(b, {})
            row[f"{b}_hedged"] = ba.get("hedged_return")

        results.append(row)
        prev_positions = positions

        if (i + 1) % 50 == 0:
            print(f"    {arm_name}: {i + 1}/{len(rebal_dates) - 1} periods")

    return results, coverage


def _safe_mean(vals):
    clean = [v for v in vals if v is not None]
    return sum(clean) / len(clean) if clean else None


def _cumulative(vals):
    clean = [v for v in vals if v is not None]
    if not clean:
        return None
    cum = 1.0
    for v in clean:
        cum *= 1.0 + v
    return cum - 1.0


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


def write_summary(
    arm_results: Dict[str, List[Dict[str, Any]]],
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

    lines = [
        "# Regulatory Confidence Tilt A/B",
        "",
        f"**Snapshot root**: `{snap_root_name}`",
        f"**Periods**: {agg[baseline]['n_periods']}",
        "",
    ]

    # Returns table
    lines.extend(["## Returns (weekly rebalance, 30bps cost)", ""])
    header = "| Metric |"
    sep = "|--------|"
    for arm in arms:
        header += f" {arm} |"
        sep += "-------------|"
    lines.append(header)
    lines.append(sep)

    for metric_name, key in [
        ("Mean weekly hedged", "mean_hedged"),
        ("Cumulative hedged", "cum_hedged"),
        ("Mean weekly net", "mean_net"),
        ("Cumulative net", "cum_net"),
        ("Mean turnover", "mean_turnover"),
    ]:
        row_line = f"| {metric_name} |"
        for arm in arms:
            v = agg[arm][key]
            row_line += f" {_fmt_pct(v)} |"
        lines.append(row_line)
    lines.append("")

    # Delta vs baseline
    lines.extend([f"## Delta vs {baseline}", ""])
    treatment = [a for a in arms if a != baseline]
    header = "| Metric |"
    sep = "|--------|"
    for arm in treatment:
        header += f" {arm} |"
        sep += "-------------|"
    lines.append(header)
    lines.append(sep)

    for metric_name, key in [
        ("Cumulative hedged delta", "cum_hedged"),
        ("Mean weekly hedged delta", "mean_hedged"),
        ("Turnover delta", "mean_turnover"),
    ]:
        row_line = f"| {metric_name} |"
        for arm in treatment:
            row_line += f" {_delta_pp(agg[arm][key], agg[baseline][key])} |"
        lines.append(row_line)
    lines.append("")

    # Bucket attribution
    lines.extend(["## Bucket Attribution Delta", ""])
    header = "| Bucket |"
    sep = "|--------|"
    for arm in treatment:
        header += f" {arm} cum delta |"
        sep += "-------------|"
    lines.append(header)
    lines.append(sep)
    for b in BUCKET_NAMES:
        row_line = f"| {b} |"
        for arm in treatment:
            row_line += f" {_delta_pp(agg[arm].get(f'{b}_cum_hedged'), agg[baseline].get(f'{b}_cum_hedged'))} |"
        lines.append(row_line)
    lines.append("")

    # Verdict
    lines.extend(["## Verdict", ""])
    for arm in treatment:
        delta_cum = (agg[arm]["cum_hedged"] or 0) - (agg[baseline]["cum_hedged"] or 0)
        delta_mean = (agg[arm]["mean_hedged"] or 0) - (agg[baseline]["mean_hedged"] or 0)
        delta_turnover = (agg[arm]["mean_turnover"] or 0) - (agg[baseline]["mean_turnover"] or 0)
        bars = []
        bars.append(f"cum_hedged_delta={delta_cum * 100:+.2f}pp {'PASS' if delta_cum * 100 >= 0.20 else 'FAIL'}")
        bars.append(f"mean_hedged_delta={delta_mean * 100:+.2f}pp {'PASS' if delta_mean * 100 >= -0.05 else 'FAIL'}")
        bars.append(
            f"turnover_delta={delta_turnover * 100:+.2f}pp {'PASS' if delta_turnover * 100 <= 0.25 else 'FAIL'}"
        )

        all_pass = delta_cum * 100 >= 0.20 and delta_mean * 100 >= -0.05 and delta_turnover * 100 <= 0.25
        status = "PASS" if all_pass else "FAIL"
        lines.append(f"**{arm}**: {status}")
        for b in bars:
            lines.append(f"  - {b}")
    lines.append("")
    lines.append("---")
    lines.append("*Generated by eval_regulatory_confidence_tilt_ab.py*")

    md_path = out_dir / "SUMMARY.md"
    md_path.write_text("\n".join(lines))

    # Write JSON
    json_path = out_dir / "BEST.json"
    best_arm = baseline
    best_cum = agg[baseline]["cum_hedged"] or -999
    for arm in arms:
        cum = agg[arm]["cum_hedged"] or -999
        if cum > best_cum:
            best_cum = cum
            best_arm = arm
    with open(json_path, "w") as f:
        json.dump({"arms": agg, "best_arm": best_arm}, f, indent=2, default=str)
        f.write("\n")

    # Write RESULTS.csv
    csv_path = out_dir / "RESULTS.csv"
    all_results = []
    for arm, results in arm_results.items():
        all_results.extend(results)
    if all_results:
        fieldnames = list(all_results[0].keys())
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_results)

    return md_path


def main():
    parser = argparse.ArgumentParser(description="A/B: regulatory confidence-weighted tilt")
    parser.add_argument("--snapshot-root", type=Path, required=True)
    parser.add_argument("--calendar", type=Path, default=PDUFA_DEFAULT)
    parser.add_argument("--policy", type=Path, default=PROJECT_ROOT / "production_data" / "portfolio_policy.json")
    parser.add_argument("--price-csv", type=Path, default=PRICE_HISTORY_DEFAULT)
    parser.add_argument("--date-from", type=str, default=None)
    parser.add_argument("--date-to", type=str, default=None)
    parser.add_argument("--out-dir", type=Path, default=PROJECT_ROOT / "output" / "research" / "reg_conf_tilt_ab")
    args = parser.parse_args()

    calendar = load_calendar(args.calendar)
    print(f"Calendar: {len(calendar)} entries")

    base_policy = load_policy(args.policy)

    # Build arms: baseline (confidence OFF) vs treatment (confidence ON)
    baseline_policy = dict(base_policy)
    baseline_policy["regulatory_confidence_tilt_enabled"] = False

    treatment_policy = dict(base_policy)
    treatment_policy["regulatory_confidence_tilt_enabled"] = True
    treatment_policy.setdefault("regulatory_confidence_weights", {"HIGH": 1.0, "MED": 0.6, "LOW": 0.3})

    dates = discover_dates(args.snapshot_root)
    if args.date_from:
        dates = [d for d in dates if d >= args.date_from]
    if args.date_to:
        dates = [d for d in dates if d <= args.date_to]
    print(f"Snapshot dates: {len(dates)}")

    print("Loading prices...")
    prices = load_prices(args.price_csv)
    print(f"  {len(prices)} tickers loaded")

    arm_policies = {
        "conf_tilt_OFF": baseline_policy,
        "conf_tilt_ON": treatment_policy,
    }

    arm_results = {}
    for arm, pol in arm_policies.items():
        print(f"\nRunning {arm}...")
        results, _ = run_arm(arm, args.snapshot_root, dates, prices, pol, calendar)
        arm_results[arm] = results
        print(f"  {len(results)} periods")

    md_path = write_summary(arm_results, args.out_dir, args.snapshot_root.name)

    print(f"\nSummary: {md_path}")
    print()
    for arm in arm_results:
        hedged = [r["hedged_return"] for r in arm_results[arm] if r["hedged_return"] is not None]
        cum = _cumulative(hedged)
        mean = _safe_mean(hedged)
        print(f"  {arm:20s}: cum_hedged={_fmt_pct(cum):>8s}  mean_hedged={_fmt_pct(mean):>8s}")


if __name__ == "__main__":
    main()
