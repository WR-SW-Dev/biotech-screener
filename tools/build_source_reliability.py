#!/usr/bin/env python3
"""Build empirical source reliability table from historical calendar slip artifacts.

Reads slips.csv files from artifacts/calendar_slips/<date>/ directories,
aggregates by source × confidence × family, applies deterministic policy,
and writes:
    artifacts/calendar_source_reliability/<as_of_date>/source_reliability.json
    artifacts/calendar_source_reliability/<as_of_date>/source_reliability.md

Usage:
    python3 tools/build_source_reliability.py --as-of-date 2026-03-10
    python3 tools/build_source_reliability.py --as-of-date 2026-03-10 --n-weeks 12
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from common.source_reliability import (
    aggregate_reliability,
    apply_reliability_policy,
    render_reliability_md,
    write_reliability_json,
)

DEFAULT_SLIPS_ROOT = PROJECT_ROOT / "artifacts" / "calendar_slips"
DEFAULT_OUT_ROOT = PROJECT_ROOT / "artifacts" / "calendar_source_reliability"

DEFAULT_N_WEEKS = 26  # ~6 months rolling window


# ---------------------------------------------------------------------------
# Production-path guards
# ---------------------------------------------------------------------------


def _in_pytest() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ


def _assert_not_production_default(name: str, value: Path, production_default: Path) -> None:
    if _in_pytest() and value == production_default:
        raise AssertionError(f"Tests must pass `{name}` explicitly — got production default {production_default}")


# ---------------------------------------------------------------------------
# Slip artifact loading
# ---------------------------------------------------------------------------


def discover_slip_dates(slips_root: Path) -> List[str]:
    """Return sorted date strings that have a slips.csv artifact."""
    dates = []
    if not slips_root.is_dir():
        return dates
    for entry in slips_root.iterdir():
        if entry.is_dir() and len(entry.name) == 10 and (entry / "slips.csv").is_file():
            dates.append(entry.name)
    dates.sort()
    return dates


def load_slips_csv(path: Path) -> List[Dict[str, str]]:
    """Load a single slips.csv file into list of row dicts."""
    rows = []
    if not path.is_file():
        return rows
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(dict(row))
    return rows


def load_historical_slips(
    slips_root: Path,
    as_of_date: str,
    n_weeks: int = DEFAULT_N_WEEKS,
) -> Tuple[List[Dict[str, str]], List[str]]:
    """Load slip rows from the most recent n_weeks of artifacts up to as_of_date.

    Returns (all_rows, dates_used).
    """
    all_dates = discover_slip_dates(slips_root)
    eligible = [d for d in all_dates if d <= as_of_date]

    # Take most recent n_weeks
    selected = eligible[-n_weeks:] if len(eligible) > n_weeks else eligible

    all_rows: List[Dict[str, str]] = []
    for date_str in selected:
        csv_path = slips_root / date_str / "slips.csv"
        rows = load_slips_csv(csv_path)
        all_rows.extend(rows)

    return all_rows, selected


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run_build_reliability(
    as_of_date: str,
    *,
    slips_root: Path = DEFAULT_SLIPS_ROOT,
    out_root: Path = DEFAULT_OUT_ROOT,
    n_weeks: int = DEFAULT_N_WEEKS,
) -> Dict[str, Any]:
    """Build and write reliability table.

    Returns result dict with buckets, paths, and metadata.
    """
    _assert_not_production_default("slips_root", slips_root, DEFAULT_SLIPS_ROOT)
    _assert_not_production_default("out_root", out_root, DEFAULT_OUT_ROOT)

    slip_rows, dates_used = load_historical_slips(slips_root, as_of_date, n_weeks)

    if not slip_rows:
        return {
            "status": "SKIP",
            "error": "No slip data found",
            "n_weeks": 0,
            "n_rows": 0,
        }

    # Aggregate and apply policy
    buckets = aggregate_reliability(slip_rows)
    apply_reliability_policy(buckets)

    # Write artifacts
    out_dir = out_root / as_of_date
    json_path = out_dir / "source_reliability.json"
    md_path = out_dir / "source_reliability.md"

    write_reliability_json(
        buckets,
        json_path,
        as_of_date=as_of_date,
        n_weeks=len(dates_used),
        n_slip_rows=len(slip_rows),
    )

    md_content = render_reliability_md(
        buckets,
        as_of_date=as_of_date,
        n_weeks=len(dates_used),
    )
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(md_content, encoding="utf-8")

    return {
        "status": "OK",
        "n_weeks": len(dates_used),
        "n_rows": len(slip_rows),
        "n_buckets": len(buckets),
        "dates_used": dates_used,
        "buckets": buckets,
        "paths": {
            "json_path": str(json_path),
            "md_path": str(md_path),
        },
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Build source reliability table from slip artifacts")
    parser.add_argument("--as-of-date", required=True, help="Reference date (YYYY-MM-DD)")
    parser.add_argument("--slips-root", type=str, help="Root of slip artifacts")
    parser.add_argument("--out-root", type=str, help="Output root directory")
    parser.add_argument("--n-weeks", type=int, default=DEFAULT_N_WEEKS, help="Rolling window in weeks")
    args = parser.parse_args()

    slips_root = Path(args.slips_root) if args.slips_root else DEFAULT_SLIPS_ROOT
    out_root = Path(args.out_root) if args.out_root else DEFAULT_OUT_ROOT

    result = run_build_reliability(
        args.as_of_date,
        slips_root=slips_root,
        out_root=out_root,
        n_weeks=args.n_weeks,
    )

    if result.get("error"):
        print(f"SKIP: {result['error']}")
        sys.exit(0)

    print(f"Reliability table built: {result['n_weeks']} weeks, {result['n_rows']} slip rows")
    print(f"  Buckets: {result['n_buckets']}")
    for b in result["buckets"]:
        print(
            f"  {b['source']}|{b['confidence']}|{b['family']}: "
            f"n={b['sample_count']} action={b['action']} — {b['reason']}"
        )
    print(f"  JSON: {result['paths']['json_path']}")
    print(f"  MD:   {result['paths']['md_path']}")


if __name__ == "__main__":
    main()
