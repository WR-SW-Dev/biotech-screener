#!/usr/bin/env python3
"""A/B evaluation: calendar confidence inclusion policies.

Compares three arms using the same snapshot root + policy:
  A = HIGH confidence only
  B = HIGH + MED (all MED entries)
  C = HIGH + MED (quality sources only: SEC_8K, COMPANY_GUIDANCE, FEDERAL_REGISTER)

Uses weekly-rebalanced live-sim with the same acceptance bars as
eval_calendar_expansion_ab.py.

Usage:
    python3 scripts/research/eval_calendar_confidence_ab.py \
      --calendar production_data/pdufa_dates.json \
      --snapshot-root data/snapshots_reranked_v1100 \
      --date-from 2025-06-01 \
      --out-dir output/research/reg_confidence_ab
"""
from __future__ import annotations

import argparse
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

# Quality source whitelist for arm C
_QUALITY_SOURCES = frozenset(
    {
        "COMPANY_GUIDANCE",
        "SEC_8K",
        "SEC_8K_FILING",
        "FEDERAL_REGISTER",
        "MANUAL",
    }
)


def filter_calendar(
    calendar: List[Dict[str, str]],
    confidence_allow: frozenset,
    source_allow: frozenset | None = None,
) -> List[Dict[str, str]]:
    """Filter calendar entries by confidence and optionally source."""
    out = []
    for entry in calendar:
        conf = entry.get("confidence", "MED").upper()
        if conf not in confidence_allow:
            continue
        if source_allow is not None:
            src = entry.get("source", "MANUAL").upper()
            # HIGH confidence always passes source filter
            if conf != "HIGH" and src not in source_allow:
                continue
        out.append(entry)
    return out


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
    if not clean:
        return None
    return sum(clean) / len(clean)


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
        return "—"
    return f"{v * 100:.{dp}f}%"


def _delta_pp(cand, base):
    if cand is None or base is None:
        return "—"
    d = (cand - base) * 100
    sign = "+" if d >= 0 else ""
    return f"{sign}{d:.2f}pp"


def write_summary(
    arm_results: Dict[str, List[Dict[str, Any]]],
    arm_calendars: Dict[str, List[Dict[str, str]]],
    arm_coverages: Dict[str, Dict[str, List[int]]],
    out_dir: Path,
    snap_root_name: str,
) -> Path:
    """Write SUMMARY.md + SUMMARY.json."""
    out_dir.mkdir(parents=True, exist_ok=True)

    # Compute aggregates per arm
    agg = {}
    for arm, results in arm_results.items():
        hedged = [r["hedged_return"] for r in results]
        net = [r["net_return"] for r in results]
        turnover = [r["turnover"] for r in results]
        reg_flags = [r["n_regulatory"] for r in results]
        agg[arm] = {
            "n_entries": len(arm_calendars[arm]),
            "n_periods": len(results),
            "mean_hedged": _safe_mean(hedged),
            "cum_hedged": _cumulative(hedged),
            "mean_net": _safe_mean(net),
            "cum_net": _cumulative(net),
            "mean_turnover": _safe_mean(turnover),
            "mean_reg_flagged": _safe_mean([float(r) for r in reg_flags]),
        }

    arms = list(agg.keys())
    baseline = arms[0]  # HIGH_only is baseline

    # Write SUMMARY.md
    lines = [
        "# Regulatory Calendar Confidence Policy A/B",
        "",
        f"**Snapshot root**: `{snap_root_name}`",
    ]
    for arm in arms:
        lines.append(f"**{arm}**: {agg[arm]['n_entries']} calendar entries")
    lines.append(f"**Periods**: {agg[baseline]['n_periods']}")
    lines.append("")

    # Coverage table
    lines.extend(["## Regulatory Coverage", ""])
    header = "| Metric |"
    sep = "|--------|"
    for arm in arms:
        header += f" {arm} |"
        sep += "-------------|"
    lines.append(header)
    lines.append(sep)

    row_flags = "| Mean tickers flagged |"
    for arm in arms:
        v = agg[arm]["mean_reg_flagged"]
        row_flags += f" {v:.1f} |" if v is not None else " — |"
    lines.append(row_flags)
    lines.append("")

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

    # Delta vs baseline table
    lines.extend([f"## Delta vs {baseline}", ""])
    non_base = [a for a in arms if a != baseline]
    header = "| Metric |"
    sep = "|--------|"
    for arm in non_base:
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
        for arm in non_base:
            row_line += f" {_delta_pp(agg[arm][key], agg[baseline][key])} |"
        lines.append(row_line)
    lines.append("")

    # Verdict
    lines.extend(["## Verdict", ""])
    lines.append("| Arm | Cum Hedged Delta | Status |")
    lines.append("|-----|-----------------|--------|")
    for arm in non_base:
        delta_cum = (agg[arm]["cum_hedged"] or 0) - (agg[baseline]["cum_hedged"] or 0)
        delta_mean = (agg[arm]["mean_hedged"] or 0) - (agg[baseline]["mean_hedged"] or 0)
        if delta_cum * 100 >= 0.20 and delta_mean * 100 >= -0.05:
            status = "PASS"
        elif delta_mean * 100 >= -0.05:
            status = "NEUTRAL"
        else:
            status = "FAIL"
        lines.append(f"| {arm} | {_delta_pp(agg[arm]['cum_hedged'], agg[baseline]['cum_hedged'])} | {status} |")
    lines.append("")

    # Best arm recommendation
    best_arm = baseline
    best_cum = agg[baseline]["cum_hedged"] or -999
    for arm in arms:
        cum = agg[arm]["cum_hedged"] or -999
        if cum > best_cum:
            best_cum = cum
            best_arm = arm
    lines.append(f"**Best arm**: {best_arm} (cumulative hedged = {_fmt_pct(best_cum)})")
    lines.append("")
    lines.append("---")
    lines.append("*Generated by eval_calendar_confidence_ab.py*")

    md_path = out_dir / "SUMMARY.md"
    md_path.write_text("\n".join(lines))

    # Write JSON
    json_path = out_dir / "SUMMARY.json"
    with open(json_path, "w") as f:
        json.dump({"arms": agg, "best_arm": best_arm}, f, indent=2, default=str)
        f.write("\n")

    return md_path


def main():
    parser = argparse.ArgumentParser(description="A/B: calendar confidence inclusion policies")
    parser.add_argument("--snapshot-root", type=Path, required=True)
    parser.add_argument("--calendar", type=Path, required=True, help="Full calendar JSON (will be filtered per arm)")
    parser.add_argument("--policy", type=Path, default=PROJECT_ROOT / "production_data" / "portfolio_policy.json")
    parser.add_argument("--price-csv", type=Path, default=PRICE_HISTORY_DEFAULT)
    parser.add_argument("--date-from", type=str, default=None)
    parser.add_argument("--date-to", type=str, default=None)
    parser.add_argument("--out-dir", type=Path, default=PROJECT_ROOT / "output" / "research" / "reg_confidence_ab")
    args = parser.parse_args()

    calendar = load_calendar(args.calendar)
    print(f"Full calendar: {len(calendar)} entries")

    # Build arms
    arm_calendars = {
        "HIGH_only": filter_calendar(
            calendar,
            confidence_allow=frozenset({"HIGH"}),
        ),
        "HIGH_plus_MED": filter_calendar(
            calendar,
            confidence_allow=frozenset({"HIGH", "MED"}),
        ),
        "HIGH_plus_MED_quality": filter_calendar(
            calendar,
            confidence_allow=frozenset({"HIGH", "MED"}),
            source_allow=_QUALITY_SOURCES,
        ),
    }

    for arm, cal in arm_calendars.items():
        print(f"  {arm}: {len(cal)} entries")

    dates = discover_dates(args.snapshot_root)
    if args.date_from:
        dates = [d for d in dates if d >= args.date_from]
    if args.date_to:
        dates = [d for d in dates if d <= args.date_to]
    print(f"Snapshot dates: {len(dates)}")

    print("Loading prices...")
    prices = load_prices(args.price_csv)
    print(f"  {len(prices)} tickers loaded")

    policy = load_policy(args.policy)

    arm_results = {}
    arm_coverages = {}
    for arm, cal in arm_calendars.items():
        print(f"\nRunning {arm}...")
        results, coverage = run_arm(
            arm,
            args.snapshot_root,
            dates,
            prices,
            policy,
            cal,
        )
        arm_results[arm] = results
        arm_coverages[arm] = coverage
        print(f"  {len(results)} periods")

    md_path = write_summary(
        arm_results,
        arm_calendars,
        arm_coverages,
        args.out_dir,
        args.snapshot_root.name,
    )

    print(f"\nSummary: {md_path}")
    print()
    for arm in arm_results:
        hedged = [r["hedged_return"] for r in arm_results[arm] if r["hedged_return"] is not None]
        cum = _cumulative(hedged)
        mean = _safe_mean(hedged)
        print(
            f"  {arm:25s}: cum_hedged={_fmt_pct(cum):>8s}  mean_hedged={_fmt_pct(mean):>8s}  entries={len(arm_calendars[arm])}"
        )


if __name__ == "__main__":
    main()
