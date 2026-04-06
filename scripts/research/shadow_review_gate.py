#!/usr/bin/env python3
"""Governed shadow review — formal promote/reject gates for shadow arms.

Evaluates shadow arm performance against Checklist v2 criteria at the
end of a shadow window. Produces a formal verdict for each arm.

Gates (all must pass for PROMOTE):
  1. Net excess > 0 (cumulative excess return vs baseline, after costs)
  2. Win rate >= 50% (fraction of days with positive excess)
  3. Hit rate stability (no more than 1 negative 5-day sub-window)
  4. Overlap drift < 40% (mean overlap with baseline stays above 60%)
  5. Turnover feasible (mean daily turnover < 20%)

Produces: PROMOTE / NEEDS_MORE / REJECT for each arm.
PROMOTE requires all 5 gates pass + minimum 20 data points.
NEEDS_MORE if <20 data points but no gate failures yet.
REJECT if any gate fails definitively.

Usage:
    python3 scripts/research/shadow_review_gate.py
    python3 scripts/research/shadow_review_gate.py --min-days 20
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SHADOW_DIR = PROJECT_ROOT / "artifacts" / "coinvest_shadow"
HISTORY_CSV = SHADOW_DIR / "history.csv"
OUTPUT_DIR = PROJECT_ROOT / "output" / "shadow_review"

# Gate thresholds
MIN_DAYS_FOR_VERDICT = 20
NET_EXCESS_MIN = 0.0  # cumulative excess must be positive
WIN_RATE_MIN = 0.50
MAX_NEGATIVE_SUBWINDOWS = 1  # out of 5-day rolling windows
MIN_OVERLAP_PCT = 60.0
MAX_DAILY_TURNOVER = 0.20  # 20%

# Arms to evaluate (column name prefixes in history.csv)
ARMS = [
    "coinvest_orig",
    "coinvest_resid",
    "coinvest_inst",
    "resid_inst",
]


def load_history() -> List[Dict[str, Any]]:
    """Load shadow history CSV."""
    if not HISTORY_CSV.exists():
        print(f"ERROR: {HISTORY_CSV} not found")
        sys.exit(1)

    rows = []
    with open(HISTORY_CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append(r)
    return rows


def _sf(v):
    """Safe float conversion."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def evaluate_arm(
    rows: List[Dict], arm: str, baseline: str = "baseline", min_days: int = MIN_DAYS_FOR_VERDICT
) -> Dict[str, Any]:
    """Evaluate a single shadow arm against gates."""
    # Collect data points with forward returns
    data_points = []
    for r in rows:
        arm_fwd_5d = _sf(r.get(f"{arm}_fwd_5d"))
        base_fwd_5d = _sf(r.get(f"{baseline}_fwd_5d"))
        overlap = _sf(r.get(f"{arm}_overlap_pct"))
        turnover = _sf(r.get(f"{arm}_turnover"))

        if arm_fwd_5d is not None and base_fwd_5d is not None:
            data_points.append(
                {
                    "date": r.get("date", ""),
                    "arm_return": arm_fwd_5d,
                    "base_return": base_fwd_5d,
                    "excess": arm_fwd_5d - base_fwd_5d,
                    "overlap": overlap,
                    "turnover": turnover,
                }
            )

    n_points = len(data_points)
    n_total = len(rows)

    if n_points == 0:
        return {
            "arm": arm,
            "n_total_days": n_total,
            "n_with_returns": 0,
            "verdict": "NEEDS_MORE",
            "reason": "No matured forward returns yet",
            "gates": {},
        }

    # Gate 1: Net cumulative excess
    cum_excess = sum(d["excess"] for d in data_points)
    gate_excess = {
        "name": "net_excess",
        "value": round(cum_excess, 4),
        "threshold": NET_EXCESS_MIN,
        "pass": cum_excess > NET_EXCESS_MIN,
    }

    # Gate 2: Win rate
    wins = sum(1 for d in data_points if d["excess"] > 0)
    win_rate = wins / n_points
    gate_win_rate = {
        "name": "win_rate",
        "value": round(win_rate, 4),
        "threshold": WIN_RATE_MIN,
        "pass": win_rate >= WIN_RATE_MIN,
    }

    # Gate 3: Stability (5-day rolling sub-windows)
    negative_windows = 0
    window_size = 5
    for i in range(0, n_points - window_size + 1):
        window_excess = sum(d["excess"] for d in data_points[i : i + window_size])
        if window_excess < 0:
            negative_windows += 1
    gate_stability = {
        "name": "stability",
        "value": negative_windows,
        "threshold": MAX_NEGATIVE_SUBWINDOWS,
        "pass": negative_windows <= MAX_NEGATIVE_SUBWINDOWS,
        "n_windows": max(n_points - window_size + 1, 0),
    }

    # Gate 4: Overlap drift
    overlaps = [d["overlap"] for d in data_points if d["overlap"] is not None]
    # Also include rows without returns (overlap is tracked daily)
    for r in rows:
        ovlp = _sf(r.get(f"{arm}_overlap_pct"))
        if ovlp is not None:
            overlaps.append(ovlp)
    mean_overlap = sum(overlaps) / len(overlaps) if overlaps else 0
    gate_overlap = {
        "name": "overlap_stability",
        "value": round(mean_overlap, 2),
        "threshold": MIN_OVERLAP_PCT,
        "pass": mean_overlap >= MIN_OVERLAP_PCT,
    }

    # Gate 5: Turnover feasibility
    turnovers = [d["turnover"] for d in data_points if d["turnover"] is not None]
    for r in rows:
        t = _sf(r.get(f"{arm}_turnover"))
        if t is not None:
            turnovers.append(t)
    mean_turnover = sum(turnovers) / len(turnovers) if turnovers else 0
    gate_turnover = {
        "name": "turnover_feasible",
        "value": round(mean_turnover, 4),
        "threshold": MAX_DAILY_TURNOVER,
        "pass": mean_turnover <= MAX_DAILY_TURNOVER,
    }

    gates = {
        "net_excess": gate_excess,
        "win_rate": gate_win_rate,
        "stability": gate_stability,
        "overlap_stability": gate_overlap,
        "turnover_feasible": gate_turnover,
    }

    all_pass = all(g["pass"] for g in gates.values())
    any_fail = any(not g["pass"] for g in gates.values())

    if n_points < min_days:
        if any_fail:
            verdict = "REJECT"
            reason = f"Gate failure with only {n_points} data points"
        else:
            verdict = "NEEDS_MORE"
            reason = f"Only {n_points}/{min_days} minimum data points"
    elif all_pass:
        verdict = "PROMOTE"
        reason = f"All 5 gates pass with {n_points} data points"
    else:
        failed = [g["name"] for g in gates.values() if not g["pass"]]
        verdict = "REJECT"
        reason = f"Failed gates: {', '.join(failed)}"

    return {
        "arm": arm,
        "n_total_days": n_total,
        "n_with_returns": n_points,
        "cum_excess": round(cum_excess, 4),
        "win_rate": round(win_rate, 4),
        "mean_overlap": round(mean_overlap, 2),
        "mean_turnover": round(mean_turnover, 4),
        "verdict": verdict,
        "reason": reason,
        "gates": gates,
    }


def main():
    parser = argparse.ArgumentParser(description="Shadow review gate evaluation")
    parser.add_argument("--min-days", type=int, default=MIN_DAYS_FOR_VERDICT)
    args = parser.parse_args()

    min_days = args.min_days

    rows = load_history()
    print("=" * 70)
    print("GOVERNED SHADOW REVIEW")
    print("=" * 70)
    print(f"\nShadow history: {len(rows)} records")
    if rows:
        print(f"  Date range: {rows[0].get('date', '?')} to {rows[-1].get('date', '?')}")
    print(f"  Minimum days for verdict: {min_days}")

    results = []
    for arm in ARMS:
        print(f"\n--- {arm} ---")
        result = evaluate_arm(rows, arm, min_days=min_days)
        results.append(result)
        print(f"  Days: {result['n_total_days']} total, {result['n_with_returns']} with returns")
        if result["n_with_returns"] > 0:
            print(f"  Cum excess: {result['cum_excess']:+.4f}")
            print(f"  Win rate: {result['win_rate']:.1%}")
            print(f"  Mean overlap: {result['mean_overlap']:.1f}%")
            print(f"  Mean turnover: {result['mean_turnover']:.1%}")

        # Show gate status
        for gate_name, gate in result.get("gates", {}).items():
            status = "PASS" if gate["pass"] else "FAIL"
            print(f"  [{status}] {gate_name}: {gate['value']} (threshold: {gate['threshold']})")

        verdict = result["verdict"]
        emoji = {"PROMOTE": "+", "REJECT": "X", "NEEDS_MORE": "?"}[verdict]
        print(f"  [{emoji}] VERDICT: {verdict} — {result['reason']}")

    # Summary table
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"  {'Arm':25s} {'Verdict':12s} {'Excess':>8s} {'WinRate':>8s} {'Overlap':>8s}")
    print(f"  {'-'*25} {'-'*12} {'-'*8} {'-'*8} {'-'*8}")
    for r in results:
        excess_str = f"{r['cum_excess']:+.4f}" if r["n_with_returns"] > 0 else "—"
        wr_str = f"{r['win_rate']:.1%}" if r["n_with_returns"] > 0 else "—"
        ovlp_str = f"{r['mean_overlap']:.1f}%" if r["n_with_returns"] > 0 else "—"
        print(f"  {r['arm']:25s} {r['verdict']:12s} {excess_str:>8s} {wr_str:>8s} {ovlp_str:>8s}")

    # Save results
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "generated_at": str(date.today()),
        "n_history_records": len(rows),
        "min_days_for_verdict": min_days,
        "arms": results,
    }
    report_path = OUTPUT_DIR / "shadow_review_report.json"
    report_path.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nReport: {report_path}")


if __name__ == "__main__":
    main()
