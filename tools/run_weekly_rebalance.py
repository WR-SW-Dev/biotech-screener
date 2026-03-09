#!/usr/bin/env python3
"""Run Weekly Rebalance — generate trade packet on rebalance day, or detect off-cycle exceptions.

Reads portfolio_policy.json to determine:
  - Is today the rebalance_day (e.g. FRIDAY)?
  - If yes → generate full trade packet
  - If no → generate "no trades" summary UNLESS off-cycle exception triggers

Off-cycle exceptions:
  - New gap-risk HIGH position that wasn't in prior snapshot
  - Hard gate FAIL in run_manifest.json

Usage:
    python3 tools/run_weekly_rebalance.py --as-of-date 2026-03-08
    python3 tools/run_weekly_rebalance.py --as-of-date 2026-03-08 --force  # always generate trades
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.build_trade_deltas import (
    DEFAULT_MIN_TRADE_USD,
    POSITIONS_DIR,
    TRADES_ROOT,
    build_no_trades_summary,
    build_trade_packet,
    find_prior_positions,
    load_positions_json,
)
from tools.live_shadow_portfolio import load_policy

SNAPSHOTS_ROOT = PROJECT_ROOT / "data" / "snapshots"

# Map policy day names to Python weekday numbers
DAY_MAP = {
    "MONDAY": 0,
    "TUESDAY": 1,
    "WEDNESDAY": 2,
    "THURSDAY": 3,
    "FRIDAY": 4,
    "SATURDAY": 5,
    "SUNDAY": 6,
}


def is_rebalance_day(as_of_date: str, policy: Dict[str, Any]) -> bool:
    """Check if as_of_date falls on the policy's rebalance_day."""
    rebalance_day = policy.get("rebalance_day", "FRIDAY").upper()
    target_weekday = DAY_MAP.get(rebalance_day, 4)
    dt = datetime.strptime(as_of_date, "%Y-%m-%d")
    return dt.weekday() == target_weekday


def detect_off_cycle_exceptions(
    current_positions_path: Path,
    snap_dir: Optional[Path] = None,
) -> list[str]:
    """Detect off-cycle trading exceptions.

    Returns list of reason strings (empty = no exceptions).
    """
    exceptions = []

    # Check for new gap-risk HIGH positions
    current_date, current_positions = load_positions_json(current_positions_path)
    prior_path = find_prior_positions(current_date, current_positions_path.parent)

    if prior_path:
        _, prior_positions = load_positions_json(prior_path)
        prior_high = {p["ticker"] for p in prior_positions if p.get("gap_risk") == "HIGH"}
        current_high = {p["ticker"] for p in current_positions if p.get("gap_risk") == "HIGH"}
        new_high = current_high - prior_high
        if new_high:
            exceptions.append(f"NEW_GAP_RISK_HIGH: {', '.join(sorted(new_high))}")

    # Check for hard gate FAIL in manifest
    if snap_dir and snap_dir.is_dir():
        manifest_path = snap_dir / "run_manifest.json"
        if manifest_path.is_file():
            with open(manifest_path) as f:
                manifest = json.load(f)
            if manifest.get("overall_status") == "FAIL":
                exceptions.append("HARD_GATE_FAIL")

    return exceptions


def run_weekly_rebalance(
    as_of_date: str,
    *,
    policy_path: Optional[Path] = None,
    positions_dir: Path = POSITIONS_DIR,
    force: bool = False,
    min_trade_usd: float = DEFAULT_MIN_TRADE_USD,
) -> Dict[str, Any]:
    """Orchestrate weekly rebalance: decide whether to trade, then build packet.

    Returns dict with decision, trade packet (if any), exceptions.
    """
    if "PYTEST_CURRENT_TEST" in os.environ and positions_dir == POSITIONS_DIR:
        raise AssertionError(f"Tests must pass `positions_dir` explicitly — got production default {POSITIONS_DIR}")
    policy = load_policy(policy_path)
    current_path = positions_dir / f"{as_of_date}.json"

    if not current_path.is_file():
        return {
            "decision": "NO_POSITIONS",
            "reason": f"No positions file for {as_of_date}",
            "trades": None,
        }

    rebalance = is_rebalance_day(as_of_date, policy)
    snap_dir = SNAPSHOTS_ROOT / as_of_date
    exceptions = detect_off_cycle_exceptions(current_path, snap_dir)

    should_trade = force or rebalance or bool(exceptions)

    out_dir = TRADES_ROOT / as_of_date

    if should_trade:
        result = build_trade_packet(
            current_path,
            min_trade_usd=min_trade_usd,
            out_dir=out_dir,
        )
        # Also generate trade plan artifact (best-effort)
        try:
            from tools.build_trade_plan import build_trade_plan

            _plan = build_trade_plan(
                as_of_date,
                positions_dir=positions_dir,
                min_trade_usd=min_trade_usd,
            )
            result["trade_plan_path"] = _plan.get("md_path", "")
        except Exception:
            pass
        decision = "REBALANCE" if rebalance else "OFF_CYCLE"
        return {
            "decision": decision,
            "is_rebalance_day": rebalance,
            "exceptions": exceptions,
            "forced": force,
            **result,
        }
    else:
        summary_path = build_no_trades_summary(
            as_of_date,
            f"Not rebalance day ({policy.get('rebalance_day', 'FRIDAY')}); no off-cycle exceptions",
            out_dir / "trade_summary.md",
        )
        return {
            "decision": "NO_TRADE",
            "is_rebalance_day": False,
            "exceptions": [],
            "forced": False,
            "as_of_date": as_of_date,
            "summary_path": str(summary_path),
            "n_trades": 0,
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Weekly rebalance orchestrator")
    parser.add_argument("--as-of-date", type=str, required=True, help="Snapshot date (YYYY-MM-DD)")
    parser.add_argument("--policy", type=str, help="Portfolio policy JSON path")
    parser.add_argument("--force", action="store_true", help="Force trade generation regardless of day")
    parser.add_argument("--min-trade", type=float, default=DEFAULT_MIN_TRADE_USD)
    args = parser.parse_args()

    policy_path = Path(args.policy) if args.policy else None

    result = run_weekly_rebalance(
        args.as_of_date,
        policy_path=policy_path,
        force=args.force,
        min_trade_usd=args.min_trade,
    )

    print(f"Decision: {result['decision']}")
    if result.get("exceptions"):
        print(f"Off-cycle exceptions: {', '.join(result['exceptions'])}")
    if result.get("n_trades", 0) > 0:
        print(f"Trades: {result['n_trades']} ({result.get('n_buys', 0)} buys, {result.get('n_sells', 0)} sells)")
    if result.get("summary_path"):
        print(f"Summary: {result['summary_path']}")


if __name__ == "__main__":
    main()
