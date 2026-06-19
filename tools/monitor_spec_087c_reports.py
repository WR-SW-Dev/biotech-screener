#!/usr/bin/env python3
"""
Spec 087C Report Accumulation Monitor

Tracks fresh weekly hedge report accumulation for Spec 087C (bioshort alpha research).
Requirement: ≥4 fresh weekly reports before 087C implementation approval.

Current status as of 2026-06-19:
- Latest report: 2026-06-02 (stale, 17 days old)
- Cron schedule: Fridays 8 AM ET
- Threshold for approval: ≥4 fresh reports
- Expected threshold date: ~2026-06-30

Usage:
    python3 tools/monitor_spec_087c_reports.py
    python3 tools/monitor_spec_087c_reports.py --output artifacts/ops/spec_087c_report_status.json
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

def get_hedge_reports():
    """List all hedge_report_*.json files by date."""
    hr_dir = PROJECT_ROOT / "output/hedge_report"
    if not hr_dir.exists():
        return []

    reports = sorted(hr_dir.glob("hedge_report_*.json"))
    return reports


def parse_report_date(filepath):
    """Extract YYYY-MM-DD from hedge_report_YYYY-MM-DD.json."""
    try:
        name = filepath.stem
        date_str = name.replace("hedge_report_", "")
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return None


def get_fresh_reports():
    """Filter reports to only those generated Fridays (cron schedule)."""
    reports = get_hedge_reports()
    fresh = []

    for report_path in reports:
        date = parse_report_date(report_path)
        if not date:
            continue

        # Check if date is a Friday (weekday 4 = Friday)
        if date.weekday() == 4:
            fresh.append((date, report_path))

    return sorted(fresh, reverse=True)


def generate_status():
    """Generate comprehensive status report."""
    fresh = get_fresh_reports()
    today = datetime.now().date()

    # Calculate expected Friday dates
    today_obj = datetime.now()
    days_since_friday = (today_obj.weekday() - 4) % 7
    last_friday = today - timedelta(days=days_since_friday if days_since_friday != 0 else 7)
    next_friday = last_friday + timedelta(days=7)

    status = {
        "as_of_date": today.isoformat(),
        "spec_id": "spec_087c",
        "title": "Bioshort Alpha Research — Report Accumulation Monitor",
        "requirement": "≥4 fresh weekly hedge reports before implementation approval",
        "current_count": len(fresh),
        "threshold_met": len(fresh) >= 4,
        "threshold_date_estimate": (
            None if len(fresh) >= 4
            else (next_friday + timedelta(days=14 * max(0, 4 - len(fresh)))).isoformat()
        ),
        "cron_schedule": "Fridays 8:00 AM ET (0 8 * * 5)",
        "reports": [
            {
                "date": date.isoformat(),
                "age_days": (today - date).days,
                "file": report_path.name,
                "status": "fresh" if (today - date).days <= 7 else "stale",
            }
            for date, report_path in fresh
        ],
        "analysis": {
            "total_friday_reports": len(fresh),
            "fresh_reports_7d": sum(1 for _, rp in fresh if (today - parse_report_date(rp)).days <= 7),
            "latest_report_date": fresh[0][0].isoformat() if fresh else None,
            "latest_report_age_days": (today - fresh[0][0]).days if fresh else None,
            "next_expected_friday": next_friday.isoformat(),
            "days_until_threshold": max(0, 4 - len(fresh)) * 7,
            "estimated_approval_ready": (
                "READY NOW" if len(fresh) >= 4
                else f"Ready ~{(next_friday + timedelta(days=14 * max(0, 4 - len(fresh)))).isoformat()}"
            ),
        },
        "governance": {
            "blocker": f"Need {max(0, 4 - len(fresh))} more Friday reports",
            "next_allowed_action": (
                "OPERATOR_DECISION on 087C implementation approval"
                if len(fresh) >= 4
                else "Continue accumulating reports; Phase A research design only"
            ),
            "constraints": [
                "No selector/ranker integration",
                "No EV/sizing changes",
                "No Module 3/5 changes",
                "No bioshort_watch LLM reactivation",
                "No scoring changes",
            ],
        },
        "timeline": {
            "spec_087_b1b_passed": "2026-05-14",
            "spec_087c_unblocked": "2026-05-14",
            "monitoring_start": "2026-05-14",
            "as_of": today.isoformat(),
            "estimated_ready_date": (
                next_friday.isoformat() if len(fresh) >= 4
                else (next_friday + timedelta(days=14 * max(0, 4 - len(fresh)))).isoformat()
            ),
        },
    }

    return status


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Monitor Spec 087C report accumulation")
    parser.add_argument("--output", help="Write status JSON to file", default=None)
    parser.add_argument("--summary", action="store_true", help="Print summary only")
    args = parser.parse_args()

    status = generate_status()

    if args.summary:
        print(f"\n{'='*70}")
        print(f"Spec 087C Report Accumulation Status ({status['as_of_date']})")
        print(f"{'='*70}\n")
        print(f"Current Count: {status['current_count']}/4 reports")
        print(f"Threshold Met: {status['threshold_met']}")
        print(f"Latest Report: {status['analysis']['latest_report_date']} ({status['analysis']['latest_report_age_days']}d old)")
        print(f"Next Expected: {status['analysis']['next_expected_friday']}")
        print(f"Estimated Ready: {status['analysis']['estimated_approval_ready']}")
        print(f"\nNext Action: {status['governance']['next_allowed_action']}\n")
    else:
        print(json.dumps(status, indent=2))

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(status, f, indent=2)
        print(f"✓ Status written to {output_path}")


if __name__ == "__main__":
    main()
