#!/usr/bin/env python3
"""Backfill weekly AACT snapshots for gap dates.

Downloads, extracts, and ingests AACT snapshots for each missing Monday
between 2026-01-01 and 2026-04-05. Skips dates that already have snapshots.

Usage:
    python3 scripts/backfill_aact_weekly.py
    python3 scripts/backfill_aact_weekly.py --dry-run
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.fetch_aact_snapshot import (
    AACT_DOWNLOAD_DIR,
    AACT_SNAPSHOT_DIR,
    _find_prior_snapshot,
    download_aact_snapshot,
    extract_aact_zip,
    log,
    run_ingest,
)

# Target: every Monday from Jan 5 through Mar 23, 2026
TARGET_DATES = []
d = date(2026, 1, 5)  # First Monday after Jan 1
end = date(2026, 4, 5)
while d <= end:
    TARGET_DATES.append(d.isoformat())
    d += timedelta(days=7)


def already_has_snapshot(dt: str) -> bool:
    snap_dir = AACT_SNAPSHOT_DIR / dt
    return (snap_dir / "trial_master.json").exists()


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    existing = [d for d in TARGET_DATES if already_has_snapshot(d)]
    missing = [d for d in TARGET_DATES if not already_has_snapshot(d)]

    print(f"Target dates: {len(TARGET_DATES)}")
    print(f"Already have: {len(existing)}")
    print(f"Need to download: {len(missing)}")
    for d in missing:
        print(f"  {d}")

    if args.dry_run:
        return

    successes = 0
    failures = []

    for i, dt in enumerate(missing):
        print(f"\n{'='*60}")
        print(f"[{i+1}/{len(missing)}] Processing {dt}...")
        print(f"{'='*60}")

        # Download
        zip_path = download_aact_snapshot(AACT_DOWNLOAD_DIR, dt)
        if not zip_path:
            log.error("Download failed for %s, skipping", dt)
            failures.append(dt)
            continue

        # Extract
        extract_dir = AACT_DOWNLOAD_DIR / f"extracted_{dt}"
        try:
            extract_aact_zip(zip_path, extract_dir)
        except Exception as e:
            log.error("Extract failed for %s: %s", dt, e)
            failures.append(dt)
            continue

        # Ingest
        try:
            prior = _find_prior_snapshot(dt)
            health = run_ingest(extract_dir, dt, prior)
            log.info(
                "Done %s: %d trials, %.1f%% linked, %d deltas",
                dt,
                health["n_trials"],
                health["linkage_pct"],
                health["delta_summary"]["n_total"],
            )
            successes += 1
        except Exception as e:
            log.error("Ingest failed for %s: %s", dt, e)
            failures.append(dt)

    print(f"\n{'='*60}")
    print(f"SUMMARY: {successes} succeeded, {len(failures)} failed")
    if failures:
        print(f"Failed dates: {failures}")


if __name__ == "__main__":
    main()
