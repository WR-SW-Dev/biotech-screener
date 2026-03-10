#!/usr/bin/env python3
"""A/B gate for calendar changes.

Compares baseline (current production calendar) vs candidate (proposed edit)
using weekly-rebalanced live-sim. Emits AB_RECEIPT.md/.json with pass/fail
verdict. Exit code: 0 = PASS, 2 = FAIL or WARN.

Pass bars (same as eval_calendar_expansion_ab):
  - Cumulative hedged delta >= +0.20pp
  - Mean weekly hedged delta >= -0.05pp
  - Turnover increase <= +0.25pp

Usage:
    python3 scripts/research/gate_calendar_change_ab.py \
        --snapshot-root data/snapshots_reranked_v1100 \
        --baseline-calendar production_data/pdufa_dates.json \
        --candidate-calendar /tmp/pdufa_dates_candidate.json \
        --out-dir output/research/calendar_ab_gate
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "research"))

from eval_calendar_expansion_ab import (
    PRICE_HISTORY_DEFAULT,
    aggregate,
    discover_dates,
    load_calendar,
    load_prices,
    run_arm,
    write_results_csv,
)
from live_shadow_portfolio import BUCKET_NAMES, load_policy

# ---------------------------------------------------------------------------
# Acceptance bars
# ---------------------------------------------------------------------------

CUM_HEDGED_DELTA_THRESHOLD = 0.0020  # +0.20pp
MEAN_HEDGED_DELTA_THRESHOLD = -0.0005  # -0.05pp
TURNOVER_DELTA_THRESHOLD = 0.0025  # +0.25pp


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------


def compute_verdict(
    base_agg: Dict[str, Any],
    cand_agg: Dict[str, Any],
    *,
    cum_threshold: float = CUM_HEDGED_DELTA_THRESHOLD,
    mean_threshold: float = MEAN_HEDGED_DELTA_THRESHOLD,
    turnover_threshold: float = TURNOVER_DELTA_THRESHOLD,
) -> Dict[str, Any]:
    """Compute pass/fail verdict from aggregated results."""
    cum_delta = _safe_delta(cand_agg.get("cum_hedged"), base_agg.get("cum_hedged"))
    mean_delta = _safe_delta(cand_agg.get("mean_hedged"), base_agg.get("mean_hedged"))
    turnover_delta = _safe_delta(cand_agg.get("mean_turnover"), base_agg.get("mean_turnover"))

    cum_pass = cum_delta is not None and cum_delta >= cum_threshold
    mean_pass = mean_delta is not None and mean_delta >= mean_threshold
    turnover_pass = turnover_delta is not None and turnover_delta <= turnover_threshold

    all_pass = cum_pass and mean_pass and turnover_pass

    # WARN: guardrail + turnover pass but cumulative doesn't clear
    if not all_pass and mean_pass and turnover_pass:
        verdict = "WARN"
    elif all_pass:
        verdict = "PASS"
    else:
        verdict = "FAIL"

    return {
        "verdict": verdict,
        "cum_hedged_delta": cum_delta,
        "cum_hedged_pass": cum_pass,
        "mean_hedged_delta": mean_delta,
        "mean_hedged_pass": mean_pass,
        "turnover_delta": turnover_delta,
        "turnover_pass": turnover_pass,
    }


def _safe_delta(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    return a - b


def _fmt_pct(v: Optional[float], dp: int = 2) -> str:
    if v is None:
        return "—"
    return f"{v * 100:.{dp}f}%"


def _fmt_pp(v: Optional[float]) -> str:
    if v is None:
        return "—"
    d = v * 100
    sign = "+" if d >= 0 else ""
    return f"{sign}{d:.2f}pp"


# ---------------------------------------------------------------------------
# Receipt writer
# ---------------------------------------------------------------------------


def write_ab_receipt(
    verdict_data: Dict[str, Any],
    base_agg: Dict[str, Any],
    cand_agg: Dict[str, Any],
    baseline_n: int,
    candidate_n: int,
    n_periods: int,
    out_dir: Path,
) -> Path:
    """Write AB_RECEIPT.md + .json."""
    out_dir.mkdir(parents=True, exist_ok=True)
    v = verdict_data

    lines = [
        "# Calendar Change A/B Receipt",
        "",
        f"**Verdict**: {v['verdict']}",
        f"**Baseline calendar**: {baseline_n} entries",
        f"**Candidate calendar**: {candidate_n} entries",
        f"**Periods evaluated**: {n_periods}",
        "",
        "## Pass Bars",
        "",
        "| Criterion | Threshold | Actual | Status |",
        "|-----------|-----------|--------|--------|",
        f"| Cumulative hedged delta | >= +0.20pp | {_fmt_pp(v['cum_hedged_delta'])} | {'PASS' if v['cum_hedged_pass'] else 'FAIL'} |",
        f"| Mean weekly hedged delta | >= -0.05pp | {_fmt_pp(v['mean_hedged_delta'])} | {'PASS' if v['mean_hedged_pass'] else 'FAIL'} |",
        f"| Turnover increase | <= +0.25pp | {_fmt_pp(v['turnover_delta'])} | {'PASS' if v['turnover_pass'] else 'FAIL'} |",
        "",
        "## Returns",
        "",
        "| Metric | Baseline | Candidate | Delta |",
        "|--------|----------|-----------|-------|",
        f"| Mean weekly hedged | {_fmt_pct(base_agg.get('mean_hedged'))} | {_fmt_pct(cand_agg.get('mean_hedged'))} | {_fmt_pp(v['mean_hedged_delta'])} |",
        f"| Cumulative hedged | {_fmt_pct(base_agg.get('cum_hedged'))} | {_fmt_pct(cand_agg.get('cum_hedged'))} | {_fmt_pp(v['cum_hedged_delta'])} |",
        f"| Mean turnover | {_fmt_pct(base_agg.get('mean_turnover'))} | {_fmt_pct(cand_agg.get('mean_turnover'))} | {_fmt_pp(v['turnover_delta'])} |",
        "",
    ]

    # Bucket attribution
    lines.extend(["## Bucket Attribution (cumulative hedged)", ""])
    lines.append("| Bucket | Baseline | Candidate | Delta |")
    lines.append("|--------|----------|-----------|-------|")
    for b in BUCKET_NAMES:
        bk_base = base_agg.get(f"{b}_mean_hedged")
        bk_cand = cand_agg.get(f"{b}_mean_hedged")
        delta = _safe_delta(bk_cand, bk_base)
        lines.append(f"| {b} | {_fmt_pct(bk_base)} | {_fmt_pct(bk_cand)} | {_fmt_pp(delta)} |")
    lines.append("")

    # Verdict message
    if v["verdict"] == "PASS":
        lines.append("**PASS**: Candidate calendar meets all pass bars. Safe to promote.")
    elif v["verdict"] == "WARN":
        lines.append(
            "**WARN**: Candidate does not hurt (guardrail + turnover OK) but "
            "cumulative hedged delta is below +0.20pp. Impact is limited."
        )
    else:
        failed = []
        if not v["mean_hedged_pass"]:
            failed.append("mean hedged guardrail")
        if not v["turnover_pass"]:
            failed.append("turnover")
        if not v["cum_hedged_pass"]:
            failed.append("cumulative hedged")
        lines.append(f"**FAIL**: Candidate fails {', '.join(failed)}. " "Do not promote this calendar change.")

    lines.extend(["", "---", "*Generated by gate_calendar_change_ab.py*"])

    md_path = out_dir / "AB_RECEIPT.md"
    md_path.write_text("\n".join(lines))

    json_data = {
        "schema": "calendar_change_ab_gate.v1",
        "verdict": v["verdict"],
        "baseline_n": baseline_n,
        "candidate_n": candidate_n,
        "n_periods": n_periods,
        "bars": {
            "cum_hedged_delta": v["cum_hedged_delta"],
            "cum_hedged_pass": v["cum_hedged_pass"],
            "mean_hedged_delta": v["mean_hedged_delta"],
            "mean_hedged_pass": v["mean_hedged_pass"],
            "turnover_delta": v["turnover_delta"],
            "turnover_pass": v["turnover_pass"],
        },
        "base_agg": base_agg,
        "cand_agg": cand_agg,
    }
    json_path = out_dir / "AB_RECEIPT.json"
    with open(json_path, "w") as f:
        json.dump(json_data, f, indent=2, default=str)
        f.write("\n")

    return md_path


# ---------------------------------------------------------------------------
# Gate runner
# ---------------------------------------------------------------------------


def run_calendar_ab_gate(
    snapshot_root: Path,
    baseline_calendar_path: Path,
    candidate_calendar_path: Path,
    policy_path: Path,
    price_csv: Path,
    out_dir: Path,
    *,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    cost_bps: float = 30.0,
) -> Tuple[str, Path]:
    """Run the full A/B gate. Returns (verdict, receipt_path)."""
    baseline_cal = load_calendar(baseline_calendar_path)
    candidate_cal = load_calendar(candidate_calendar_path)
    print(f"Baseline calendar: {len(baseline_cal)} entries")
    print(f"Candidate calendar: {len(candidate_cal)} entries")

    dates = discover_dates(snapshot_root)
    if date_from:
        dates = [d for d in dates if d >= date_from]
    if date_to:
        dates = [d for d in dates if d <= date_to]
    print(f"Snapshot dates: {len(dates)}")

    if len(dates) < 2:
        print("ERROR: Need at least 2 snapshot dates.")
        sys.exit(1)

    print("Loading prices...")
    prices = load_prices(price_csv)
    print(f"  {len(prices)} tickers loaded")

    policy = load_policy(policy_path)

    print("\nRunning baseline arm...")
    base_results, _ = run_arm("baseline", snapshot_root, dates, prices, policy, baseline_cal, cost_bps)
    print(f"  {len(base_results)} periods")

    print("\nRunning candidate arm...")
    cand_results, _ = run_arm("candidate", snapshot_root, dates, prices, policy, candidate_cal, cost_bps)
    print(f"  {len(cand_results)} periods")

    # Write raw results
    all_results = base_results + cand_results
    csv_path = out_dir / "RESULTS.csv"
    write_results_csv(all_results, csv_path)

    base_agg = aggregate(base_results)
    cand_agg = aggregate(cand_results)

    verdict_data = compute_verdict(base_agg, cand_agg)
    md_path = write_ab_receipt(
        verdict_data,
        base_agg,
        cand_agg,
        len(baseline_cal),
        len(candidate_cal),
        base_agg["n_periods"],
        out_dir,
    )

    return verdict_data["verdict"], md_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    p = argparse.ArgumentParser(description="A/B gate for calendar changes")
    p.add_argument("--snapshot-root", type=Path, required=True)
    p.add_argument(
        "--baseline-calendar",
        type=Path,
        default=PROJECT_ROOT / "production_data" / "pdufa_dates.json",
    )
    p.add_argument("--candidate-calendar", type=Path, required=True)
    p.add_argument(
        "--policy",
        type=Path,
        default=PROJECT_ROOT / "production_data" / "portfolio_policy.json",
    )
    p.add_argument("--price-csv", type=Path, default=PRICE_HISTORY_DEFAULT)
    p.add_argument("--date-from", type=str, default=None)
    p.add_argument("--date-to", type=str, default=None)
    p.add_argument("--cost-bps", type=float, default=30.0)
    p.add_argument(
        "--out-dir",
        type=Path,
        default=PROJECT_ROOT / "output" / "research" / "calendar_ab_gate",
    )
    args = p.parse_args()

    verdict, md_path = run_calendar_ab_gate(
        args.snapshot_root,
        args.baseline_calendar,
        args.candidate_calendar,
        args.policy,
        args.price_csv,
        args.out_dir,
        date_from=args.date_from,
        date_to=args.date_to,
        cost_bps=args.cost_bps,
    )

    print(f"\nReceipt: {md_path}")
    print(f"Verdict: {verdict}")

    if verdict == "PASS":
        sys.exit(0)
    else:
        sys.exit(2)


if __name__ == "__main__":
    main()
