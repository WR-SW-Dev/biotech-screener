#!/usr/bin/env python3
"""Backfill catalyst_event_type into historical snapshots.

RESEARCH ONLY — infers catalyst_event_type for pre-2026-01-15 snapshots
where the field is empty.

Strategy:
  1. Load PIT-safe CTgov trial records (monthly caches) → match ticker
     + primary_completion_date within catalyst_days window → CT_PRIMARY_COMPLETION
  2. Load PDUFA dates → match ticker + pdufa_date → FDA_DECISION
  3. Fallback for catalyst_mode=specific_days → DATA_READOUT (generic clinical)

Usage:
    python3 scripts/research/backfill_catalyst_event_type.py \\
        --snapshot-root data/snapshots \\
        --out-root data/snapshots_backfilled \\
        --ctgov-cache-dir cache/ctgov \\
        --pdufa-json production_data/pdufa_dates.json

    # In-place update (modifies snapshot CSVs directly):
    python3 scripts/research/backfill_catalyst_event_type.py \\
        --snapshot-root data/snapshots --in-place
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from event_ledger import classify_catalyst_family


def _safe_float(v) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        f = float(v)
        return None if f != f else f
    except (ValueError, TypeError):
        return None


def _parse_date(s: str) -> Optional[datetime]:
    """Parse YYYY-MM-DD date string."""
    if not s or len(s) < 10:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d")
    except ValueError:
        return None


def load_ctgov_cache(cache_dir: Path, as_of_date: str) -> Dict[str, List[dict]]:
    """Load the nearest PIT-safe CTgov trial cache for a given date.

    Returns {ticker: [trial_records]} where each trial has primary_completion_date.
    Only loads caches with date <= as_of_date (PIT-safe).
    """
    cache_files = sorted(f for f in cache_dir.glob("trial_records_*.json") if not f.name.endswith(".meta.json"))
    # Find nearest cache <= as_of_date
    best = None
    for f in cache_files:
        # Extract date from filename: trial_records_YYYY-MM-DD.json
        parts = f.stem.replace("trial_records_", "")
        if parts <= as_of_date:
            best = f

    if best is None:
        return {}

    with open(best, "r", encoding="utf-8") as f:
        trials = json.load(f)

    # Group by ticker
    by_ticker: Dict[str, List[dict]] = {}
    for t in trials:
        ticker = t.get("ticker", "")
        if not ticker:
            continue
        # Only interventional trials
        if t.get("study_type", "") != "INTERVENTIONAL":
            continue
        pcd = t.get("primary_completion_date", "")
        if not pcd:
            continue
        by_ticker.setdefault(ticker, []).append(t)

    return by_ticker


def load_pdufa_dates(pdufa_json: Path) -> Dict[str, List[dict]]:
    """Load PDUFA dates grouped by ticker."""
    if not pdufa_json.exists():
        return {}
    with open(pdufa_json, "r", encoding="utf-8") as f:
        data = json.load(f)

    by_ticker: Dict[str, List[dict]] = {}
    for entry in data:
        ticker = entry.get("ticker", "")
        if ticker:
            by_ticker.setdefault(ticker, []).append(entry)
    return by_ticker


def infer_event_type(
    ticker: str,
    snap_date: str,
    catalyst_days: float,
    ctgov_by_ticker: Dict[str, List[dict]],
    pdufa_by_ticker: Dict[str, List[dict]],
    *,
    tolerance_days: int = 30,
) -> tuple:
    """Infer catalyst_event_type and catalyst_source for a ticker.

    Returns (event_type, source, confidence).
    """
    snap_dt = _parse_date(snap_date)
    if snap_dt is None:
        return ("", "", "")

    implied_catalyst_dt = snap_dt + timedelta(days=int(catalyst_days))

    # 1. Check PDUFA dates
    pdufa_entries = pdufa_by_ticker.get(ticker, [])
    for entry in pdufa_entries:
        pdufa_dt = _parse_date(entry.get("pdufa_date", ""))
        if pdufa_dt is not None:
            delta = abs((pdufa_dt - implied_catalyst_dt).days)
            if delta <= tolerance_days:
                return ("FDA_DECISION", "PDUFA_MANUAL", "HIGH")

    # 2. Check CTgov trials — find nearest PCD match
    trials = ctgov_by_ticker.get(ticker, [])
    best_delta = tolerance_days + 1
    best_trial = None
    for t in trials:
        pcd = _parse_date(t.get("primary_completion_date", ""))
        if pcd is None:
            continue
        # PIT check: trial must have been posted before snapshot
        first_posted = t.get("first_posted", "")
        if first_posted and first_posted > snap_date:
            continue
        delta = abs((pcd - implied_catalyst_dt).days)
        if delta < best_delta:
            best_delta = delta
            best_trial = t

    if best_trial is not None:
        return ("CT_PRIMARY_COMPLETION", "CTGOV_CALENDAR", "MED")

    # 3. Fallback: generic clinical readout
    return ("DATA_READOUT", "INFERRED", "LOW")


def backfill_snapshot(
    rows: List[Dict[str, str]],
    snap_date: str,
    ctgov_by_ticker: Dict[str, List[dict]],
    pdufa_by_ticker: Dict[str, List[dict]],
) -> int:
    """Backfill catalyst_event_type for rows missing it.

    Returns count of rows updated.
    """
    n_updated = 0
    for r in rows:
        # Skip rows that already have event_type
        if r.get("catalyst_event_type"):
            continue
        # Only backfill rows with a concrete catalyst signal
        if r.get("catalyst_mode") != "specific_days":
            # Set empty for non-catalyst rows
            r.setdefault("catalyst_event_type", "")
            r.setdefault("catalyst_source", "")
            r.setdefault("catalyst_family", "NO_CATALYST")
            continue

        ticker = r.get("ticker", "")
        cat_days = _safe_float(r.get("catalyst_days"))
        if not ticker or cat_days is None:
            r.setdefault("catalyst_event_type", "")
            r.setdefault("catalyst_source", "")
            r.setdefault("catalyst_family", "NO_CATALYST")
            continue

        event_type, source, _confidence = infer_event_type(
            ticker,
            snap_date,
            cat_days,
            ctgov_by_ticker,
            pdufa_by_ticker,
        )
        r["catalyst_event_type"] = event_type
        if not r.get("catalyst_source"):
            r["catalyst_source"] = source
        r["catalyst_family"] = classify_catalyst_family(event_type)
        n_updated += 1

    # Also backfill catalyst_family for any remaining rows
    for r in rows:
        if "catalyst_family" not in r:
            r["catalyst_family"] = classify_catalyst_family(r.get("catalyst_event_type", ""))

    return n_updated


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Backfill catalyst_event_type into historical snapshots",
    )
    parser.add_argument("--snapshot-root", type=Path, required=True)
    parser.add_argument(
        "--out-root",
        type=Path,
        default=None,
        help="Output root. If omitted, use --in-place.",
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Modify snapshot CSVs in place (no --out-root needed).",
    )
    parser.add_argument(
        "--ctgov-cache-dir",
        type=Path,
        default=PROJECT_ROOT / "cache" / "ctgov",
    )
    parser.add_argument(
        "--pdufa-json",
        type=Path,
        default=PROJECT_ROOT / "production_data" / "pdufa_dates.json",
    )
    parser.add_argument("--date-from", default=None)
    parser.add_argument("--date-to", default=None)
    parser.add_argument("--min-cols", type=int, default=50)
    args = parser.parse_args()

    if not args.in_place and args.out_root is None:
        print("ERROR: specify --out-root or --in-place")
        sys.exit(1)

    # Load PDUFA dates (small, load once)
    pdufa_by_ticker = load_pdufa_dates(args.pdufa_json)
    print(f"PDUFA: {sum(len(v) for v in pdufa_by_ticker.values())} entries for {len(pdufa_by_ticker)} tickers")

    # Discover snapshots
    snap_dates = sorted(
        d.name
        for d in args.snapshot_root.iterdir()
        if d.is_dir()
        and not d.name.startswith("_")
        and (d / "rankings.csv").exists()
        and len(d.name) == 10
        and d.name[4] == "-"
        and (args.date_from is None or d.name >= args.date_from)
        and (args.date_to is None or d.name <= args.date_to)
    )
    print(f"Found {len(snap_dates)} snapshots")

    # Cache CTgov data per-month to avoid reloading
    _ctgov_cache: Dict[str, Dict[str, List[dict]]] = {}

    def get_ctgov(snap_date: str) -> Dict[str, List[dict]]:
        # Key by year-month to reduce reloads
        key = snap_date[:7]
        if key not in _ctgov_cache:
            _ctgov_cache.clear()  # Keep memory bounded
            _ctgov_cache[key] = load_ctgov_cache(args.ctgov_cache_dir, snap_date)
        return _ctgov_cache[key]

    n_processed = 0
    n_updated_total = 0
    n_skipped = 0

    for snap_date in snap_dates:
        src = args.snapshot_root / snap_date / "rankings.csv"
        with open(src, "r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        if not rows or len(rows[0]) < args.min_cols:
            n_skipped += 1
            continue

        # Check if already has event_type data
        n_with_et = sum(1 for r in rows if r.get("catalyst_event_type"))
        if n_with_et > 0:
            # Already populated, skip unless very few
            n_skipped += 1
            continue

        ctgov = get_ctgov(snap_date)
        n_updated = backfill_snapshot(rows, snap_date, ctgov, pdufa_by_ticker)

        # Write output
        if args.in_place:
            out_path = src
        else:
            out_dir = args.out_root / snap_date
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / "rankings.csv"
            # Also copy metadata if exists
            meta_src = args.snapshot_root / snap_date / "metadata.json"
            if meta_src.exists():
                meta = json.loads(meta_src.read_text())
                meta["backfill_catalyst_event_type"] = True
                (out_dir / "metadata.json").write_text(json.dumps(meta, indent=2))

        fieldnames = list(rows[0].keys())
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

        n_processed += 1
        n_updated_total += n_updated

    print(f"\nDone: {n_processed} processed, {n_skipped} skipped")
    print(f"Total rows updated: {n_updated_total}")
    if n_processed > 0:
        print(f"Avg updates per snapshot: {n_updated_total / n_processed:.1f}")


if __name__ == "__main__":
    main()
