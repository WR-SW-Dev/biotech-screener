#!/usr/bin/env python3
"""Regenerate historical snapshots with PIT financials (pseudo-PIT v2).

Runs run_screen.py for each monthly snapshot date with --pit-mode degrade,
writing to data/snapshots_pit_v2/. Only runs dates not already present
in the output directory (idempotent).

Usage:
    python scripts/research/regenerate_pit_v2_snapshots.py
    python scripts/research/regenerate_pit_v2_snapshots.py --start 2023-01-01
    python scripts/research/regenerate_pit_v2_snapshots.py --dry-run
    python scripts/research/regenerate_pit_v2_snapshots.py --max-dates 5
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOTS_DIR = PROJECT_ROOT / "data" / "snapshots"
PIT_V2_DIR = PROJECT_ROOT / "data" / "snapshots_pit_v2"
PROD_DATA = PROJECT_ROOT / "production_data"
LOG_PATH = PROJECT_ROOT / "output" / "pit" / "regeneration_log.json"


def get_monthly_dates(start: str = "2020-01-01") -> list[str]:
    """Get one snapshot date per month (last available per month)."""
    by_month: dict[str, str] = {}
    for d in sorted(SNAPSHOTS_DIR.iterdir()):
        if not d.is_dir() or not (d / "rankings.csv").exists():
            continue
        name = d.name
        if "__" in name:  # skip staging dirs like 2026-04-02__pre_*
            continue
        if name < start:
            continue
        by_month[name[:7]] = name
    return sorted(by_month.values())


def already_done(date_str: str) -> bool:
    """Check if PIT v2 snapshot already exists for this date."""
    return (PIT_V2_DIR / date_str / "rankings.csv").exists()


def run_one(date_str: str, dry_run: bool = False) -> dict:
    """Run run_screen.py for one date. Returns status dict."""
    if dry_run:
        return {"date": date_str, "status": "dry_run"}

    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "run_screen.py"),
        "--as-of-date",
        date_str,
        "--data-dir",
        str(PROD_DATA),
        "--pit-mode",
        "degrade",
        "--snapshot-dir",
        str(PIT_V2_DIR),
        "--no-clinical-filter",
        "--diagnostics",
        "none",
    ]

    t0 = time.time()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
            cwd=str(PROJECT_ROOT),
        )
        elapsed = time.time() - t0
        if result.returncode == 0:
            return {
                "date": date_str,
                "status": "ok",
                "elapsed_s": round(elapsed, 1),
            }
        else:
            # Extract last few lines of stderr for diagnosis
            err_tail = result.stderr.strip().split("\n")[-5:]
            return {
                "date": date_str,
                "status": "error",
                "returncode": result.returncode,
                "elapsed_s": round(elapsed, 1),
                "error_tail": err_tail,
            }
    except subprocess.TimeoutExpired:
        return {"date": date_str, "status": "timeout", "elapsed_s": 600}
    except Exception as e:
        return {"date": date_str, "status": "exception", "error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="Regenerate PIT v2 snapshots")
    parser.add_argument("--start", default="2020-01-01", help="Start date")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-dates", type=int, default=0, help="Max dates to process (0=all)")
    args = parser.parse_args()

    dates = get_monthly_dates(args.start)
    todo = [d for d in dates if not already_done(d)]
    done = [d for d in dates if already_done(d)]

    print(f"Monthly dates: {len(dates)}")
    print(f"Already done:  {len(done)}")
    print(f"To process:    {len(todo)}")

    if args.max_dates > 0:
        todo = todo[: args.max_dates]
        print(f"Limited to:    {len(todo)}")

    if not todo:
        print("Nothing to do.")
        return

    PIT_V2_DIR.mkdir(parents=True, exist_ok=True)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    results = []
    n_ok = 0
    n_err = 0
    t_start = time.time()

    for i, date_str in enumerate(todo, 1):
        prefix = f"[{i}/{len(todo)}]"
        if args.dry_run:
            print(f"{prefix} {date_str} — dry run")
            results.append(run_one(date_str, dry_run=True))
            continue

        print(f"{prefix} {date_str} ...", end=" ", flush=True)
        r = run_one(date_str)
        results.append(r)

        if r["status"] == "ok":
            n_ok += 1
            print(f"OK ({r['elapsed_s']}s)")
        else:
            n_err += 1
            print(f"FAIL: {r['status']}")
            if "error_tail" in r:
                for line in r["error_tail"]:
                    print(f"    {line}")

    elapsed_total = time.time() - t_start

    # Save log
    log = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_dates": len(dates),
        "processed": len(results),
        "ok": n_ok,
        "errors": n_err,
        "elapsed_total_s": round(elapsed_total, 1),
        "results": results,
    }
    with open(LOG_PATH, "w") as f:
        json.dump(log, f, indent=2)

    print(f"\nDone: {n_ok} ok, {n_err} errors in {elapsed_total:.0f}s")
    print(f"Log: {LOG_PATH}")


if __name__ == "__main__":
    main()
