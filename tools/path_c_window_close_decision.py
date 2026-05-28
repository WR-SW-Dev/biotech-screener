#!/usr/bin/env python3
"""
Path C Window Close Decision Automation (2026-06-03)

Implements the hard decision logic at window close:
1. Check IC observability
2. If observable: evaluate against floor (0.0200)
3. If unobservable: operator chooses extend or revert
4. Execute decision and document outcome
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def check_ic_status(window_end: str = "2026-06-03") -> dict:
    """Check current IC status at window close."""
    ic_ledger = REPO_ROOT / "artifacts" / "forward_eval_ic_ledger.jsonl"

    if not ic_ledger.exists():
        return {
            "observable": False,
            "reason": "IC ledger not created yet (cold start)",
            "latest_date": None,
            "latest_ic": None,
            "status": "IC_UNOBSERVABLE",
        }

    observations = []
    with open(ic_ledger) as f:
        for line in f:
            if line.strip():
                try:
                    entry = json.loads(line)
                    if entry.get("as_of_date") <= window_end:
                        observations.append(entry)
                except json.JSONDecodeError:
                    continue

    if not observations:
        return {
            "observable": False,
            "reason": "No IC observations in ledger through window close",
            "latest_date": None,
            "latest_ic": None,
            "status": "IC_UNOBSERVABLE",
        }

    latest = observations[-1]
    latest_date = latest.get("as_of_date")
    latest_ic = latest.get("mean_ic")

    if latest_ic is None:
        return {
            "observable": False,
            "reason": "Forward eval gate cold start (10+ lookback snapshots not yet with filled horizons)",
            "latest_date": latest_date,
            "latest_ic": None,
            "status": "IC_UNOBSERVABLE",
        }

    return {
        "observable": True,
        "reason": None,
        "latest_date": latest_date,
        "latest_ic": latest_ic,
        "status": "OBSERVABLE",
    }


def decision_tree(floor: float = 0.0200) -> dict:
    """Execute decision tree at window close."""
    print("\n" + "=" * 80)
    print("PATH C WINDOW CLOSE DECISION — 2026-06-03")
    print("=" * 80 + "\n")

    # Step 1: Check IC status
    print("[STEP 1] Checking IC observability...")
    ic_status = check_ic_status()
    print(f"  Status: {ic_status['status']}")
    if ic_status["latest_date"]:
        print(f"  Latest observation date: {ic_status['latest_date']}")
    if ic_status["latest_ic"]:
        print(f"  Latest mean_ic: {ic_status['latest_ic']:.4f}")
    if ic_status["reason"]:
        print(f"  Reason: {ic_status['reason']}")
    print()

    # Step 2: Scenario branching
    if ic_status["observable"]:
        print("[STEP 2] IC IS OBSERVABLE — Evaluate against floor")
        latest_ic = ic_status["latest_ic"]
        gap = latest_ic - floor

        if latest_ic >= floor:
            decision = "PATH_C_VALID"
            verdict = "✓ PASS"
            action = "Window closes successfully. Path C remains valid through 2026-06-03."
            next = "Continue monitoring; proceed with next governance cycle; begin Path A design post-freeze"
        else:
            decision = "PATH_C_REVOKE"
            verdict = "✗ FAIL"
            action = "Revert to HOLD pending Path A design. Path C governance override revoked immediately."
            next = "Escalate to governance review; document evidence; begin Path A design work"

        print(f"  Floor threshold: {floor:.4f}")
        print(f"  Gap: {gap:+.4f}")
        print(f"  Verdict: {verdict}")
        print(f"  Action: {action}")
        print()

    else:
        print("[STEP 2] IC IS UNOBSERVABLE — Operator decision required")
        print(f"  Reason: {ic_status['reason']}")
        print()
        print("  OPTION A: Extend observation window (recommended if conviction remains)")
        print("    - Extend Path C until first observable IC print (~2026-06-17)")
        print("    - Evaluate against floor at that date")
        print("    - Allows institutional signal strength to accumulate more evidence")
        print()
        print("  OPTION B: Revert to HOLD (conservative if uncertain)")
        print("    - Revert to HOLD pending Path A design")
        print("    - Closes override immediately")
        print("    - Triggers Path A portfolio timing gate design (post-freeze)")
        print()

        # In automation mode, we can't ask the operator interactively here,
        # but we provide the decision framework
        decision = "IC_UNOBSERVABLE"
        verdict = "DECISION_REQUIRED"
        action = "Operator must choose: extend window or revert to HOLD"
        next = "Document decision and rationale in governance ledger with timestamp"

        print(f"  Verdict: {verdict}")
        print(f"  Required action: {action}")
        print()

    # Step 3: Document the outcome
    print("[STEP 3] Document decision")
    outcome = {
        "date": datetime.utcnow().isoformat(),
        "window_close_date": "2026-06-03",
        "ic_status": ic_status["status"],
        "ic_observable": ic_status["observable"],
        "ic_value": ic_status["latest_ic"],
        "ic_floor": floor,
        "decision": decision,
        "action": action,
        "next_steps": next,
    }

    print("  Path: artifacts/readiness/WINDOW_CLOSE_DECISION_2026_06_03.md")
    print("  Save this decision and rationale to governance ledger")
    print()

    print("=" * 80)
    print(f"SUMMARY: {decision}")
    print("=" * 80)
    print()

    return outcome


def main():
    parser = argparse.ArgumentParser(description="Path C window close decision automation")
    parser.add_argument("--floor", type=float, default=0.0200, help="IC floor threshold")
    parser.add_argument("--output-json", action="store_true", help="Output decision as JSON")
    args = parser.parse_args()

    outcome = decision_tree(floor=args.floor)

    if args.output_json:
        print(json.dumps(outcome, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
