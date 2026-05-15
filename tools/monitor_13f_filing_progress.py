#!/usr/bin/env python3
"""Monitor Q1 2026 13F filing progress and update holdings incrementally"""

import json
import time
from datetime import datetime
from pathlib import Path

from elite_managers import get_all_managers
from sec_13f.edgar_13f import SEC13FFetcher

CACHE_DIR = Path("data/13f_cache")
TARGET_QUARTER = "2026-03-31"
OUTPUT_FILE = Path("production_data/holdings_2026-03-31.json")
STATUS_FILE = Path("production_data/13f_filing_status.json")


def load_status():
    """Load filing status tracking"""
    if STATUS_FILE.exists():
        with open(STATUS_FILE) as f:
            return json.load(f)
    return {"last_check": None, "filed": {}, "pending": {}}


def save_status(status):
    """Save filing status"""
    with open(STATUS_FILE, "w") as f:
        json.dump(status, f, indent=2)


def check_manager_filings():
    """Check which managers have Q1 2026 filings"""
    managers = get_all_managers()
    fetcher = SEC13FFetcher(cache_dir=str(CACHE_DIR))

    status = load_status()
    status["last_check"] = datetime.now().isoformat()

    filed_count = 0
    newly_filed = []

    print(f"\n[{datetime.now().isoformat()}] Checking {len(managers)} managers for Q1 2026 filings...")

    for m in managers:
        cik = m["cik"].zfill(10)
        name = m["name"]

        # Skip if already processed
        if cik in status["filed"]:
            filed_count += 1
            continue

        try:
            filings = fetcher.get_recent_filings(m["cik"], count=1)
            if filings and filings[0].report_date.isoformat() == TARGET_QUARTER:
                status["filed"][cik] = {
                    "name": name,
                    "filed_date": filings[0].filing_date.isoformat(),
                    "accession": filings[0].accession_number,
                }
                newly_filed.append((cik, name, filings[0].filing_date.isoformat()))
                filed_count += 1
                print(f"  ✓ {name:30s} ({cik}) filed {filings[0].filing_date}")
            else:
                status["pending"][cik] = {"name": name, "checked_at": datetime.now().isoformat()}

            time.sleep(0.1)  # Rate limit

        except Exception as e:
            status["pending"][cik] = {"name": name, "error": str(e)[:50]}

    save_status(status)

    print("\nSummary:")
    print(f"  Total filed: {len(status['filed'])}/{len(managers)}")
    print(f"  Newly filed this check: {len(newly_filed)}")

    if newly_filed:
        print("\nNew filings:")
        for cik, name, date in newly_filed:
            print(f"  - {name} ({cik}) on {date}")

    # Check if we should lift quarantine (70%+ filed)
    filing_pct = len(status["filed"]) / len(managers) * 100
    print(f"\nFiling progress: {filing_pct:.1f}%")

    if filing_pct >= 70 and len(status["filed"]) >= 34:
        print(f"\n⚠️  MILESTONE: 70% filing threshold reached ({len(status['filed'])} managers)")
        print("    Ready for cohort validation rerun")

    return newly_filed


if __name__ == "__main__":
    check_manager_filings()
