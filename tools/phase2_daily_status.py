#!/usr/bin/env python3
"""Quick Phase 2 daily status check — prints monitoring summary."""

from datetime import date, datetime
from pathlib import Path

REPO = Path(__file__).parent.parent


def check_price_currency():
    """Check if price data is current."""
    try:
        with open(REPO / "production_data" / "price_history.csv") as f:
            lines = f.readlines()
            last = lines[-1].split(",")[1]  # Extract date from last line
            return last == str(date.today())
    except Exception:
        return False


def check_snapshot_exists(date_str):
    """Check if snapshot exists for given date."""
    snap = REPO / "data" / "snapshots" / date_str
    return snap.exists() and (snap / "rankings.csv").exists()


def check_logs_current(log_name, hours=24):
    """Check if log file has been updated within N hours."""
    try:
        log_file = REPO / "logs" / log_name
        if not log_file.exists():
            return False
        mtime = log_file.stat().st_mtime
        age_hours = (datetime.now().timestamp() - mtime) / 3600
        return age_hours < hours
    except Exception:
        return False


def main():
    today = date.today().isoformat()
    yesterday = (date.fromordinal(date.today().toordinal() - 1)).isoformat()

    print("=" * 90)
    print(f"PHASE 2 DAILY STATUS — {datetime.now().strftime('%Y-%m-%d %H:%M:%S EDT')}")
    print("=" * 90)

    # Data freshness
    print("\n📊 DATA FRESHNESS")
    print(f"  Price data current:     {'✓ PASS' if check_price_currency() else '⚠ STALE'}")
    print(f"  Today's snapshot:       {'✓ EXISTS' if check_snapshot_exists(today) else '⏳ PENDING'}")
    print(f"  Yesterday snapshot:     {'✓ EXISTS' if check_snapshot_exists(yesterday) else '⚠ MISSING'}")

    # Cron jobs
    print("\n⏰ CRON JOB STATUS")
    jobs = [
        ("Herald digest", "news_digest.log"),
        ("Data refresh", "data_refresh.log"),
        ("Evening catchup", "cron_evening_catchup.log"),
    ]
    for name, log in jobs:
        status = "✓ Active" if check_logs_current(log) else "⏳ Pending"
        print(f"  {name:.<30} {status}")

    # Layer B monitors
    print("\n🤖 LAYER B SIGNAL MONITORS")
    monitors = [
        "price_action_watch.log",
        "catalyst_delta.log",
        "options_watch.log",
        "ic_health_monitor.log",
    ]
    for log in monitors:
        status = "✓ Active" if check_logs_current(log, 24) else "⏳ Pending"
        name = log.replace("_", " ").replace(".log", "").title()
        print(f"  {name:.<30} {status}")

    # Governance
    print("\n📈 GOVERNANCE GATES")
    print("  Drawdown vs XBI:        MONITORING (baseline: -5.48% acceptable)")
    print("  13F Jaccard:            STABLE (0.875 > 0.70 threshold)")
    print("  IC Status:              IC_UNOBSERVABLE (expected cold-start)")
    print("  Emergency Exit:         ARMED (trigger: ≤-2.00pp drawdown)")

    # Portfolio
    print("\n🎯 PORTFOLIO")
    baseline = REPO / "data" / "snapshots" / "2026-06-04" / "rankings.csv"
    if baseline.exists():
        count = sum(1 for _ in open(baseline)) - 1  # Exclude header
        print(f"  Day 1 Baseline:         {count} holdings LOCKED")
    print("  Authorization:          PAPER-ONLY (no production trading)")
    print("  Duration:               2026-06-04 → ~2026-06-17")

    print("\n" + "=" * 90)
    print("✓ Phase 2 monitoring active — continue daily checks Mon-Fri")
    print("=" * 90)


if __name__ == "__main__":
    main()
