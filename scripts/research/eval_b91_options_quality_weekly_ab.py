#!/usr/bin/env python3
"""A/B evaluation: options quality sort tilt for REGULATORY in less_binary.

Compares two arms using the same snapshot root + base policy:
  A = baseline (active production ruleset: clinical_quality mode)
  B = treatment (clinical_plus_options mode: keeps CLINICAL tilt, adds REGULATORY options tilt)

Re-ranks snapshots in-memory through the decision engine before portfolio
construction so the sort contribution actually affects selection.

Uses weekly-rebalanced live-sim with the standard acceptance bars:
  - cumulative hedged delta >= +0.20pp
  - mean weekly hedged delta >= -0.05pp
  - turnover increase <= +0.25pp

DATA REQUIREMENT:
  Snapshots must have `options_quality_composite` populated (from tastytrade
  diagnostics via `opt_*` columns in run_screen.py). Without this data, the
  treatment arm will behave identically to baseline.

  Check coverage:
    python3 -c "import csv; r=csv.DictReader(open('data/snapshots/DATE/rankings.csv'));
      print(sum(1 for row in r if row.get('options_quality_composite','')!=''))"

Usage:
    python3 scripts/research/eval_b91_options_quality_weekly_ab.py \
      --snapshot-root data/snapshots \
      --date-from 2026-04-01 \
      --out-dir output/research/b91_options_quality_weekly_ab
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

from common.ranking_utils import backfill_columns
from common.ranking_utils import safe_float as _safe_float
from decision_engine import DecisionRuleset, compute_actionable_sort_key


def _load_active_ruleset() -> DecisionRuleset:
    """Load the active production ruleset."""
    manifest_path = PROJECT_ROOT / "production_data" / "decision_rulesets" / "manifest.json"
    with open(manifest_path) as f:
        manifest = json.load(f)
    for entry in manifest.get("rulesets", []):
        if entry.get("status") == "active":
            rs_path = PROJECT_ROOT / "production_data" / "decision_rulesets" / entry["file"]
            with open(rs_path) as f:
                data = json.load(f)
            return DecisionRuleset(**{k: v for k, v in data.items() if k in DecisionRuleset.__dataclass_fields__})
    return DecisionRuleset()


def _rerank_with_ruleset(rows: List[Dict[str, str]], ruleset: DecisionRuleset) -> List[Dict[str, str]]:
    """Re-sort rows using the given ruleset and assign fresh actionable_rank."""
    backfill_columns(rows)

    rows.sort(
        key=lambda r: compute_actionable_sort_key(
            decision_fields=r,
            archetype=r.get("archetype", ""),
            optionality=_safe_float(r.get("clinical_optionality_pct_dev")),
            composite_rank=r.get("composite_rank"),
            ticker=r.get("ticker", ""),
            catalyst_event_type=r.get("catalyst_event_type", ""),
            catalyst_source=r.get("catalyst_source", ""),
            ruleset=ruleset,
            tiebreaker_pct=(
                _safe_float(r.get("alpha_cohort_pct"))
                if ruleset.sort_anchor == "alpha_cohort"
                else (
                    _safe_float(r.get("commercial_quality_pct"))
                    if r.get("archetype", "").startswith("commercial_")
                    else _safe_float(r.get("clinical_optionality_pct_dev"))
                )
            ),
        )
    )

    rank = 1
    for r in rows:
        if r.get("eligible") == "1":
            r["actionable_rank"] = str(rank)
            rank += 1
        else:
            r["actionable_rank"] = ""

    return rows


def run_arm(
    arm_name: str,
    snap_root: Path,
    rebal_dates: List[str],
    prices: Dict[str, Dict[str, float]],
    policy: Dict[str, Any],
    ruleset: DecisionRuleset,
    cost_bps: float = 30.0,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Simulate weekly-rebalanced portfolio for one arm."""
    results = []
    prev_positions: List[Dict[str, Any]] = []
    coverage_stats = {"total_rows": 0, "rows_with_oqc": 0, "regulatory_less_binary": 0}

    for i in range(len(rebal_dates) - 1):
        entry_date = rebal_dates[i]
        exit_date = rebal_dates[i + 1]

        snap_dir = snap_root / entry_date
        if not (snap_dir / "rankings.csv").exists():
            continue

        rankings = load_rankings(snap_dir)

        # Track options_quality_composite coverage
        for r in rankings:
            coverage_stats["total_rows"] += 1
            if r.get("options_quality_composite", "") != "":
                coverage_stats["rows_with_oqc"] += 1
            if r.get("catalyst_family") == "REGULATORY" and r.get("catalyst_bucket") == "less_binary":
                coverage_stats["regulatory_less_binary"] += 1

        # Re-rank through the DE with this arm's ruleset
        rankings = _rerank_with_ruleset(deepcopy(rankings), ruleset)

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

    return results, coverage_stats


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
    coverage_stats: Dict[str, Dict[str, Any]],
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
        "# Options Quality 91-180 A/B (REGULATORY in less_binary)",
        "",
        f"**Snapshot root**: `{snap_root_name}`",
        f"**Periods**: {agg[baseline]['n_periods']}",
        "",
    ]

    # Coverage warning
    for arm, stats in coverage_stats.items():
        total = stats.get("total_rows", 0)
        with_oqc = stats.get("rows_with_oqc", 0)
        reg_lb = stats.get("regulatory_less_binary", 0)
        pct = f"{100 * with_oqc / total:.1f}%" if total > 0 else "n/a"
        lines.append(
            f"**{arm}**: {with_oqc}/{total} rows with options_quality_composite ({pct}), "
            f"{reg_lb} REGULATORY+less_binary rows"
        )
    lines.append("")

    if all(s.get("rows_with_oqc", 0) == 0 for s in coverage_stats.values()):
        lines.append("**WARNING**: No snapshots contain options_quality_composite data.")
        lines.append("The treatment arm is identical to baseline. Results are meaningless.")
        lines.append("Ensure tastytrade credentials (TT_SECRET, TT_REFRESH) are set in run_screen.py.")
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

    # Delta table
    treatment = [a for a in arms if a != baseline]
    lines.extend([f"## Delta vs {baseline}", ""])
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
    lines.append("*Generated by eval_b91_options_quality_weekly_ab.py*")

    md_path = out_dir / "SUMMARY.md"
    md_path.write_text("\n".join(lines))

    # JSON receipt
    json_path = out_dir / "AB_RECEIPT.json"
    receipt = {"arms": agg, "best_arm": baseline, "coverage": coverage_stats}
    best_cum = agg[baseline]["cum_hedged"] or -999
    for arm in arms:
        cum = agg[arm]["cum_hedged"] or -999
        if cum > best_cum:
            best_cum = cum
            receipt["best_arm"] = arm
    with open(json_path, "w") as f:
        json.dump(receipt, f, indent=2, default=str)
        f.write("\n")

    # CSV results
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
    parser = argparse.ArgumentParser(description="A/B: options quality sort tilt for REGULATORY in less_binary")
    parser.add_argument("--snapshot-root", type=Path, required=True)
    parser.add_argument("--policy", type=Path, default=PROJECT_ROOT / "production_data" / "portfolio_policy.json")
    parser.add_argument("--price-csv", type=Path, default=PRICE_HISTORY_DEFAULT)
    parser.add_argument("--date-from", type=str, default=None)
    parser.add_argument("--date-to", type=str, default=None)
    parser.add_argument("--options-quality-weight", type=float, default=0.5)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=PROJECT_ROOT / "output" / "research" / "b91_options_quality_weekly_ab",
    )
    args = parser.parse_args()

    # Load active production ruleset as baseline
    baseline_rs = _load_active_ruleset()
    print(f"Baseline ruleset: {baseline_rs.ruleset_id}")
    print(f"  binary_91_180_sort_mode: {baseline_rs.binary_91_180_sort_mode}")

    # Build treatment ruleset: keeps clinical_quality for CLINICAL, adds options_quality for REGULATORY
    treatment_kwargs = {k: getattr(baseline_rs, k) for k in DecisionRuleset.__dataclass_fields__}
    treatment_kwargs["binary_91_180_sort_mode"] = "clinical_plus_options"
    treatment_kwargs["binary_91_180_options_quality_weight"] = args.options_quality_weight
    treatment_rs = DecisionRuleset(**treatment_kwargs)
    print(f"Treatment ruleset: {treatment_rs.ruleset_id}")
    print(f"  binary_91_180_sort_mode: {treatment_rs.binary_91_180_sort_mode}")
    print(f"  binary_91_180_clinical_quality_weight: {treatment_rs.binary_91_180_clinical_quality_weight}")
    print(f"  binary_91_180_options_quality_weight: {treatment_rs.binary_91_180_options_quality_weight}")

    policy = load_policy(args.policy)

    dates = discover_dates(args.snapshot_root)
    if args.date_from:
        dates = [d for d in dates if d >= args.date_from]
    if args.date_to:
        dates = [d for d in dates if d <= args.date_to]
    print(f"Snapshot dates: {len(dates)}")

    # Pre-flight check: do any snapshots have options_quality_composite?
    sample_dates = dates[:5] if len(dates) >= 5 else dates
    has_oqc = False
    for d in sample_dates:
        rankings_path = args.snapshot_root / d / "rankings.csv"
        if rankings_path.exists():
            with open(rankings_path) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("options_quality_composite", "") != "":
                        has_oqc = True
                        break
            if has_oqc:
                break
    if not has_oqc:
        print("\n*** WARNING: No options_quality_composite data found in sampled snapshots ***")
        print("*** Treatment arm will be identical to baseline — results are meaningless ***")
        print("*** Ensure TT_SECRET and TT_REFRESH are set for run_screen.py ***\n")

    print("Loading prices...")
    prices = load_prices(args.price_csv)
    print(f"  {len(prices)} tickers loaded")

    arm_configs = {
        "oq_tilt_OFF": baseline_rs,
        "oq_tilt_ON": treatment_rs,
    }

    arm_results = {}
    arm_coverage = {}
    for arm, rs in arm_configs.items():
        print(f"\nRunning {arm}...")
        results, coverage = run_arm(arm, args.snapshot_root, dates, prices, policy, rs)
        arm_results[arm] = results
        arm_coverage[arm] = coverage
        print(f"  {len(results)} periods")

    md_path = write_summary(arm_results, args.out_dir, args.snapshot_root.name, arm_coverage)

    print(f"\nSummary: {md_path}")
    for arm in arm_results:
        hedged = [r["hedged_return"] for r in arm_results[arm] if r["hedged_return"] is not None]
        cum = _cumulative(hedged)
        mean = _safe_mean(hedged)
        print(f"  {arm:20s}: cum_hedged={_fmt_pct(cum):>8s}  mean_hedged={_fmt_pct(mean):>8s}")


if __name__ == "__main__":
    main()
