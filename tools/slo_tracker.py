#!/usr/bin/env python3
"""SLO / error-budget tracker for the daily production pipeline.

Reads the gate verdict ledger (JSONL) and computes:
  - Rolling 30-day gate pass rate (SLO attainment)
  - Error budget remaining (allowed failures before SLO breach)
  - Per-gate failure frequency

Usage:
    python tools/slo_tracker.py                    # default: 30-day window
    python tools/slo_tracker.py --window 14        # 14-day window
    python tools/slo_tracker.py --json             # machine-readable output
    python tools/slo_tracker.py --exit-on-breach   # exit 1 if SLO breached

The SLO target is defined as a minimum pass rate over the rolling window.
"PASS" and "WARN" count as successful runs; only "FAIL" consumes budget.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
GATE_LEDGER_PATH = REPO_ROOT / "artifacts" / "gate_verdict_ledger.jsonl"

# ── SLO definition ──────────────────────────────────────────────────────
# "99% of daily runs in a rolling 30-day window must not FAIL."
# With 30 trading days, that means at most 0 FAIL days (ceiling).
# We use 95% as a pragmatic starting target — allows ~1 FAIL per 20 runs.
SLO_TARGET_PCT = 95.0
DEFAULT_WINDOW_DAYS = 30


def load_ledger(path: Path = GATE_LEDGER_PATH) -> List[Dict[str, Any]]:
    """Load all rows from the gate verdict ledger."""
    if not path.exists():
        return []
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def compute_slo_report(
    rows: List[Dict[str, Any]],
    window_days: int = DEFAULT_WINDOW_DAYS,
    slo_target_pct: float = SLO_TARGET_PCT,
    as_of: Optional[date] = None,
) -> Dict[str, Any]:
    """Compute SLO attainment and error budget from ledger rows.

    Args:
        rows: Ledger entries (each has 'as_of_date' and 'overall_status').
        window_days: Rolling window size in calendar days.
        slo_target_pct: Target pass rate (0-100).
        as_of: Reference date (defaults to today).

    Returns:
        Dict with SLO metrics.
    """
    if as_of is None:
        as_of = date.today()

    cutoff = as_of - timedelta(days=window_days)

    # Filter to window and deduplicate by date (keep latest per date)
    by_date: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        d = r.get("as_of_date", "")
        if d and d >= cutoff.isoformat() and d <= as_of.isoformat():
            by_date[d] = r  # last entry per date wins

    window_rows = sorted(by_date.values(), key=lambda r: r["as_of_date"])
    total = len(window_rows)

    if total == 0:
        return {
            "slo_target_pct": slo_target_pct,
            "window_days": window_days,
            "as_of": as_of.isoformat(),
            "total_runs": 0,
            "pass_runs": 0,
            "warn_runs": 0,
            "fail_runs": 0,
            "pass_rate_pct": None,
            "slo_met": None,
            "budget_total": 0,
            "budget_consumed": 0,
            "budget_remaining": 0,
            "gate_failure_counts": {},
            "recent_failures": [],
        }

    fail_runs = [r for r in window_rows if r["overall_status"] == "FAIL"]
    warn_runs = [r for r in window_rows if r["overall_status"] == "WARN"]
    pass_runs = [r for r in window_rows if r["overall_status"] == "PASS"]

    n_fail = len(fail_runs)
    n_warn = len(warn_runs)
    n_pass = len(pass_runs)
    pass_rate = ((total - n_fail) / total) * 100.0

    # Error budget: how many FAILs are allowed before breaching SLO
    import math
    max_allowed_fails = math.floor(total * (1.0 - slo_target_pct / 100.0))
    budget_remaining = max(0, max_allowed_fails - n_fail)

    # Per-gate failure frequency (which gates fail most often)
    gate_fail_counts: Dict[str, int] = {}
    for r in fail_runs:
        for gate_name, gate_status in r.get("gates", {}).items():
            if gate_status == "FAIL":
                gate_fail_counts[gate_name] = gate_fail_counts.get(gate_name, 0) + 1

    # Recent failures (last 5)
    recent_failures = [
        {"date": r["as_of_date"], "gates": {
            g: s for g, s in r.get("gates", {}).items() if s == "FAIL"
        }}
        for r in fail_runs[-5:]
    ]

    return {
        "slo_target_pct": slo_target_pct,
        "window_days": window_days,
        "as_of": as_of.isoformat(),
        "total_runs": total,
        "pass_runs": n_pass,
        "warn_runs": n_warn,
        "fail_runs": n_fail,
        "pass_rate_pct": round(pass_rate, 2),
        "slo_met": pass_rate >= slo_target_pct,
        "budget_total": max_allowed_fails,
        "budget_consumed": n_fail,
        "budget_remaining": budget_remaining,
        "gate_failure_counts": dict(sorted(
            gate_fail_counts.items(), key=lambda x: -x[1]
        )),
        "recent_failures": recent_failures,
    }


def format_report(report: Dict[str, Any]) -> str:
    """Format SLO report as human-readable text."""
    lines = []
    lines.append(f"SLO Report — {report['as_of']} ({report['window_days']}-day window)")
    lines.append("=" * 60)

    if report["total_runs"] == 0:
        lines.append("No runs in window. Ledger may be empty or not yet populated.")
        return "\n".join(lines)

    slo_status = "MET" if report["slo_met"] else "BREACHED"
    lines.append(f"Target:   {report['slo_target_pct']}% pass rate")
    lines.append(f"Actual:   {report['pass_rate_pct']}%  [{slo_status}]")
    lines.append("")
    lines.append(f"Runs:     {report['total_runs']} total "
                 f"({report['pass_runs']} pass, {report['warn_runs']} warn, "
                 f"{report['fail_runs']} fail)")
    lines.append(f"Budget:   {report['budget_consumed']}/{report['budget_total']} "
                 f"consumed, {report['budget_remaining']} remaining")

    if report["gate_failure_counts"]:
        lines.append("")
        lines.append("Top failing gates:")
        for gate, count in report["gate_failure_counts"].items():
            lines.append(f"  {gate}: {count}x")

    if report["recent_failures"]:
        lines.append("")
        lines.append("Recent failures:")
        for f in report["recent_failures"]:
            gates = ", ".join(f["gates"].keys()) or "unknown"
            lines.append(f"  {f['date']}: {gates}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="SLO / error-budget tracker")
    parser.add_argument("--window", type=int, default=DEFAULT_WINDOW_DAYS,
                        help=f"Rolling window in days (default: {DEFAULT_WINDOW_DAYS})")
    parser.add_argument("--target", type=float, default=SLO_TARGET_PCT,
                        help=f"SLO target pass rate %% (default: {SLO_TARGET_PCT})")
    parser.add_argument("--ledger", type=Path, default=GATE_LEDGER_PATH,
                        help="Path to gate verdict ledger JSONL")
    parser.add_argument("--json", action="store_true",
                        help="Output JSON instead of human-readable text")
    parser.add_argument("--exit-on-breach", action="store_true",
                        help="Exit 1 if SLO is breached")
    args = parser.parse_args()

    rows = load_ledger(args.ledger)
    report = compute_slo_report(
        rows,
        window_days=args.window,
        slo_target_pct=args.target,
    )

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(format_report(report))

    # Write report to artifacts for CI pickup
    report_path = REPO_ROOT / "artifacts" / "slo_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    if args.exit_on_breach and report.get("slo_met") is False:
        sys.exit(1)


if __name__ == "__main__":
    main()
