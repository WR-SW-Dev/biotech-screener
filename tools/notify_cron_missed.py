#!/usr/bin/env python3
"""CLI: emit cron_missed Town event (Spec 090). Used by cron_watchdog.sh."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from common.town_bridge_events import notify_cron_missed  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="Notify Town of missed cron / production gap")
    p.add_argument("--date", required=True, help="As-of date YYYY-MM-DD")
    p.add_argument(
        "--reason",
        default="production_snapshot_missing",
        help="Short reason code (logged in summary)",
    )
    p.add_argument(
        "--recovery-triggered",
        action="store_true",
        help="Set when watchdog is about to run recovery",
    )
    args = p.parse_args()

    ok = notify_cron_missed(
        as_of_date=args.date,
        missed_critical_times=["17:30"],
        missed_noncritical_times=[],
        runtime_severity="RED",
        reasons=[args.reason],
        artifact=f"logs/watchdog.log",
        recovery_triggered=args.recovery_triggered,
        source="cron_watchdog",
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
