#!/usr/bin/env python3
"""Phase 2 gate verification — single-command status check.

Checks all active Phase 2 governance gates and prints a traffic-light
status table. Exits 0 if no FAIL gates, 1 if any FAIL.

Usage:
    python3 tools/verify_phase2_gates.py
    python3 tools/verify_phase2_gates.py --as-of-date 2026-06-24
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MONITORING_DIR = PROJECT_ROOT / "artifacts" / "monitoring"
IC_HISTORY = PROJECT_ROOT / "artifacts" / "ic_dashboard" / "history.jsonl"
EES_LEDGER = PROJECT_ROOT / "scripts" / "research" / "ees_shadow_ledger.jsonl"

PHASE2_WINDOW_END = date(2026, 7, 1)
DRAWDOWN_HARD_EXIT_PP = -5.0
DRAWDOWN_WARN_PP = -2.0
POSITION_STOP_PCT = -20.0
EES_20D_TARGET = 20


def _find_latest_daily(as_of: date) -> Path | None:
    """Return the most recent daily monitoring JSON on or before as_of."""
    candidates = sorted(MONITORING_DIR.glob("daily_*.json"), reverse=True)
    as_of_str = as_of.strftime("%Y_%m_%d")
    for p in candidates:
        stem = p.stem  # daily_2026_06_23
        if stem <= f"daily_{as_of_str}":
            return p
    return None


def check_drawdown(as_of: date) -> tuple[str, str]:
    """Return (status, detail) for drawdown vs XBI gate."""
    daily = _find_latest_daily(as_of)
    if daily is None:
        return "DEFERRED", "no daily monitoring artifact found"
    with open(daily) as f:
        d = json.load(f)
    overview = d.get("portfolio_overview", {})
    pp = overview.get("drawdown_vs_xbi_pp")
    date_str = daily.stem.replace("daily_", "").replace("_", "-")
    if pp is None:
        return "DEFERRED", f"drawdown_vs_xbi_pp missing in {daily.name}"
    if pp <= DRAWDOWN_HARD_EXIT_PP:
        return "FAIL", f"{pp:+.2f}pp vs XBI (hard exit threshold {DRAWDOWN_HARD_EXIT_PP}pp) [{date_str}]"
    if pp <= DRAWDOWN_WARN_PP:
        return "WARN", f"{pp:+.2f}pp vs XBI (warn threshold {DRAWDOWN_WARN_PP}pp) [{date_str}] — ACCEPTED 2026-06-24"
    return "PASS", f"{pp:+.2f}pp vs XBI [{date_str}]"


def check_ic_observable() -> tuple[str, str]:
    """Return (status, detail) for IC observable gate."""
    if not IC_HISTORY.exists():
        return "DEFERRED", "IC history file not found"
    observable_dates = 0
    with open(IC_HISTORY) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                if row.get("score_rank_pct_health", "NO_DATA") != "NO_DATA":
                    observable_dates += 1
            except json.JSONDecodeError:
                pass
    if observable_dates >= 1:
        ic_health = None
        # Get most recent non-NO_DATA health
        with open(IC_HISTORY) as f:
            rows = [json.loads(line.strip()) for line in f if line.strip()]
        for row in reversed(rows):
            h = row.get("score_rank_pct_health", "NO_DATA")
            if h != "NO_DATA":
                ic_health = h
                ic_ic = row.get("score_rank_pct_ic")
                ic_date = row.get("date", "?")
                break
        detail = f"health={ic_health} ic={ic_ic:+.4f} as of {ic_date} ({observable_dates} dates observed)"
        return "PASS", detail
    return "DEFERRED", "IC not yet observable (no completed 20d return windows)"


def check_critical_positions(as_of: date) -> tuple[str, str]:
    """Return (status, detail) for position stop-loss gate."""
    daily = _find_latest_daily(as_of)
    if daily is None:
        return "DEFERRED", "no daily monitoring artifact found"
    with open(daily) as f:
        d = json.load(f)
    positions = d.get("positions", [])
    critical = []
    for p in positions:
        pnl = p.get("pnl_vs_entry_pct")
        if pnl is not None and pnl < POSITION_STOP_PCT:
            critical.append(f"{p['ticker']} {pnl:+.1f}%")
    date_str = daily.stem.replace("daily_", "").replace("_", "-")
    if critical:
        return "FAIL", f"{len(critical)} position(s) below {POSITION_STOP_PCT}%: {', '.join(critical)} [{date_str}]"
    return "PASS", f"no positions below {POSITION_STOP_PCT}% [{date_str}]"


def check_phase2_window(as_of: date) -> tuple[str, str]:
    """Return (status, detail) for Phase 2 window status."""
    days_remaining = (PHASE2_WINDOW_END - as_of).days
    if days_remaining < 0:
        return "FAIL", f"Phase 2 window EXPIRED {abs(days_remaining)}d ago (ended {PHASE2_WINDOW_END})"
    if days_remaining == 0:
        return "WARN", f"Phase 2 window ends TODAY ({PHASE2_WINDOW_END})"
    if days_remaining <= 3:
        return "WARN", f"Phase 2 window ends in {days_remaining}d ({PHASE2_WINDOW_END})"
    return "PASS", f"{days_remaining}d remaining (window ends {PHASE2_WINDOW_END})"


def check_ees_shadow_gate() -> tuple[str, str]:
    """Return (status, detail) for EES 20d shadow monitor gate."""
    if not EES_LEDGER.exists():
        return "DEFERRED", "EES shadow ledger not found (ledger gitignored — run monitor first)"
    completed_20d = 0
    total_rows = 0
    with open(EES_LEDGER) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                total_rows += 1
                if row.get("completed_20d", False):
                    completed_20d += 1
            except json.JSONDecodeError:
                pass
    detail = f"{completed_20d}/{EES_20D_TARGET} completed 20d observations ({total_rows} total rows)"
    if completed_20d >= EES_20D_TARGET:
        return "PASS", detail
    return "DEFERRED", detail


STATUS_ORDER = {"FAIL": 0, "WARN": 1, "PASS": 2, "DEFERRED": 3}
STATUS_ICON = {"FAIL": "✗ FAIL   ", "WARN": "! WARN   ", "PASS": "✓ PASS   ", "DEFERRED": "~ DEFERRED"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 2 governance gate verification")
    parser.add_argument("--as-of-date", default=None, help="Date YYYY-MM-DD (default: today)")
    args = parser.parse_args()

    if args.as_of_date:
        as_of = datetime.strptime(args.as_of_date, "%Y-%m-%d").date()
    else:
        as_of = date.today()

    gates = [
        ("Drawdown vs XBI", check_drawdown(as_of)),
        ("IC Observable", check_ic_observable()),
        ("Position Stop-Loss", check_critical_positions(as_of)),
        ("Phase 2 Window", check_phase2_window(as_of)),
        ("EES 20d Gate", check_ees_shadow_gate()),
    ]

    print(f"\nPhase 2 Gate Status — {as_of}")
    print("=" * 72)
    fail_count = 0
    warn_count = 0
    for name, (status, detail) in gates:
        icon = STATUS_ICON[status]
        print(f"  {icon} {name:<22} {detail}")
        if status == "FAIL":
            fail_count += 1
        elif status == "WARN":
            warn_count += 1
    print("=" * 72)
    summary_parts = []
    if fail_count:
        summary_parts.append(f"{fail_count} FAIL")
    if warn_count:
        summary_parts.append(f"{warn_count} WARN")
    if not summary_parts:
        summary_parts.append("all gates OK")
    print(f"  Summary: {', '.join(summary_parts)}")
    print()

    return 1 if fail_count else 0


if __name__ == "__main__":
    sys.exit(main())
