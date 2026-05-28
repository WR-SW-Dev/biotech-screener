#!/usr/bin/env python3
"""
monitor_forward_eval_ic.py — Monitor forward_eval IC trend through Path C window.

Extracts IC values from recent snapshots and tracks against floor threshold (0.0200).
Used during Path C temporary policy override (2026-05-28 to 2026-06-03).

Usage:
    python3 tools/monitor_forward_eval_ic.py [--window-end YYYY-MM-DD] [--floor 0.0200]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from forward_eval_ic_ledger import append_to_ledger, extract_forward_eval_ic, read_gate_verdict_ledger

REPO_ROOT = Path(__file__).resolve().parent.parent


def monitor_ic_window(
    window_end: str = "2026-06-03",
    floor: float = 0.0200,
    lookback_n: int = 10,
    horizon: int = 20,
) -> dict:
    """Check forward_eval IC against floor threshold and return status.

    Args:
        window_end: End date of monitoring window (YYYY-MM-DD)
        floor: IC floor threshold (default 0.0200)
        lookback_n: Number of past snapshots to evaluate (unused, for compatibility)
        horizon: Forward return horizon in days (unused, for compatibility)

    Returns:
        dict with:
        - window_end: end date
        - floor: threshold
        - latest_date: most recent snapshot with IC
        - latest_ic: most recent mean_ic value
        - status: 'ABOVE_FLOOR', 'BELOW_FLOOR', or 'NO_DATA'
        - observations: list of IC observations through window
        - message: human-readable summary
    """
    ic_ledger = REPO_ROOT / "artifacts" / "forward_eval_ic_ledger.jsonl"

    # Read IC ledger
    observations = []
    if ic_ledger.exists():
        with open(ic_ledger) as f:
            for line in f:
                if line.strip():
                    try:
                        entry = json.loads(line)
                        if entry.get("as_of_date") <= window_end:
                            observations.append(entry)
                    except json.JSONDecodeError:
                        continue

    # Sort by date
    observations.sort(key=lambda x: x["as_of_date"])

    # Get latest IC
    latest_date = None
    latest_ic = None
    status = "NO_DATA"

    if observations:
        latest = observations[-1]
        latest_date = latest["as_of_date"]
        latest_ic = latest["mean_ic"]

        if latest_ic is not None:
            status = "ABOVE_FLOOR" if latest_ic >= floor else "BELOW_FLOOR"

    # Build message
    if latest_ic is None:
        message = "No IC data yet in window"
    else:
        gap = (latest_ic - floor) if latest_ic else None
        message = f"Latest IC: {latest_ic:.4f} ({status}), " f"gap={gap:.4f}, floor={floor:.4f} [{latest_date}]"

    return {
        "window_end": window_end,
        "floor": floor,
        "latest_date": latest_date,
        "latest_ic": latest_ic,
        "status": status,
        "observations": observations,
        "message": message,
    }


def main():
    parser = argparse.ArgumentParser(description="Monitor forward_eval IC through Path C window")
    parser.add_argument("--window-end", default="2026-06-03", help="End date of monitoring window")
    parser.add_argument("--floor", type=float, default=0.0200, help="IC floor threshold")
    args = parser.parse_args()

    # Refresh IC ledger
    print("[IC_MONITOR] Refreshing forward_eval IC ledger...")
    snapshot_dir = REPO_ROOT / "data" / "snapshots"
    price_cache_base = REPO_ROOT / "data" / "caches" / "price_pit"
    ic_ledger = REPO_ROOT / "artifacts" / "forward_eval_ic_ledger.jsonl"

    # Get existing dates
    existing_dates = set()
    if ic_ledger.exists():
        with open(ic_ledger) as f:
            for line in f:
                if line.strip():
                    try:
                        entry = json.loads(line)
                        existing_dates.add(entry["as_of_date"])
                    except json.JSONDecodeError:
                        continue

    # Find snapshots from gate verdict ledger
    gate_ledger = REPO_ROOT / "artifacts" / "gate_verdict_ledger.jsonl"
    verdicts = read_gate_verdict_ledger(gate_ledger)

    # Process recent snapshots
    processed = 0
    for record in verdicts[-20:]:
        as_of_date = record.get("as_of_date")

        if not as_of_date or as_of_date in existing_dates or as_of_date > args.window_end:
            continue

        snap_path = snapshot_dir / as_of_date
        if not snap_path.exists():
            continue

        ic_data = extract_forward_eval_ic(snap_path, as_of_date, price_cache_base)
        if ic_data:
            append_to_ledger(ic_ledger, ic_data)
            print(f"[IC_MONITOR] {as_of_date}: mean_ic={ic_data['mean_ic']:.4f}")
            processed += 1

    if processed > 0:
        print(f"[IC_MONITOR] Refreshed: {processed} new snapshot(s)")

    # Check window status
    result = monitor_ic_window(window_end=args.window_end, floor=args.floor)
    print(f"\n[IC_MONITOR] {result['message']}")

    if result["status"] == "BELOW_FLOOR":
        print(f"[IC_MONITOR] ⚠️  WARNING: IC below floor at {result['latest_date']}")
        print("[IC_MONITOR] If this persists to window close (2026-06-03), Path C will revert to HOLD")

    # Output JSON for parsing
    print(f"\n[IC_MONITOR_JSON] {json.dumps(result)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
