#!/usr/bin/env python3
"""Process Herald CRT intake candidates into resolution records.

Reads the Herald intake candidates and creates CRT resolution records
for candidates with high-confidence outcome mappings (HIT/MISS).
NEEDS_REVIEW candidates are skipped — they require manual classification.

Usage:
    python3 scripts/research/process_herald_crt_candidates.py
    python3 scripts/research/process_herald_crt_candidates.py --dry-run
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

INTAKE_DIR = PROJECT_ROOT / "artifacts" / "herald_crt_intake"
RESOLUTION_DIR = PROJECT_ROOT / "data" / "snapshots" / "resolutions"
SCHEMA_VERSION = "1.0.0"


def _compute_hash(record: dict) -> str:
    d = {k: v for k, v in record.items() if k != "record_hash"}
    raw = json.dumps(d, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def load_existing_keys() -> set[tuple[str, str]]:
    """Load (ticker, catalyst_date) keys from existing resolutions."""
    keys = set()
    for month_dir in RESOLUTION_DIR.iterdir():
        if not month_dir.is_dir():
            continue
        for f in month_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                keys.add((data["ticker"], data["catalyst_date"]))
            except (json.JSONDecodeError, KeyError):
                pass
    return keys


def load_candidates() -> list[dict]:
    """Load the most recent intake candidates file."""
    files = sorted(INTAKE_DIR.glob("*_candidates.json"))
    if not files:
        print("ERROR: No intake candidate files found")
        sys.exit(1)
    latest = files[-1]
    data = json.loads(latest.read_text())
    print(f"Loaded {data['n_candidates']} candidates from {latest.name}")
    return data["candidates"]


def candidate_to_resolution(cand: dict) -> dict:
    """Convert a Herald intake candidate to a CRT resolution record."""
    record = {
        "schema_version": SCHEMA_VERSION,
        "ticker": cand["ticker"],
        "catalyst_date": cand["catalyst_date"],
        "catalyst_type": cand["catalyst_type"],
        "catalyst_description": cand.get("headline", ""),
        "resolution_date": cand.get("catalyst_date"),  # use catalyst date as resolution date
        "outcome": cand["mapped_outcome"],
        "outcome_detail": cand.get("headline", ""),
        "source_type": "PRESS_RELEASE",
        "source_id": cand.get("source_url", "herald_intake"),
        "prediction_snapshot_date": None,
        "prediction_dem_rank": None,
        "prediction_composite_score": None,
        "price_t_minus_1": None,
        "price_t_0": None,
        "price_t_plus_5": None,
        "price_direction": None,
        "days_from_expected": None,
        "as_of_date": str(date.today()),
    }
    record["record_hash"] = _compute_hash(record)
    return record


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Process Herald CRT intake candidates")
    parser.add_argument("--dry-run", action="store_true", help="Print without writing")
    parser.add_argument(
        "--include-needs-review",
        action="store_true",
        help="Also write NEEDS_REVIEW candidates (default: only HIT/MISS)",
    )
    args = parser.parse_args()

    candidates = load_candidates()
    existing = load_existing_keys()
    print(f"Existing resolutions: {len(existing)} (ticker, date) keys")

    # Filter to actionable candidates
    actionable = []
    for c in candidates:
        outcome = c.get("mapped_outcome", "")
        if outcome in ("HIT", "MISS"):
            actionable.append(c)
        elif outcome == "NEEDS_REVIEW" and args.include_needs_review:
            actionable.append(c)

    print(
        f"Actionable candidates: {len(actionable)} (HIT/MISS{' + NEEDS_REVIEW' if args.include_needs_review else ''})"
    )

    # Deduplicate against existing resolutions
    new_records = []
    skipped_existing = 0
    for c in actionable:
        key = (c["ticker"], c["catalyst_date"])
        if key in existing:
            skipped_existing += 1
            continue
        record = candidate_to_resolution(c)
        new_records.append(record)
        existing.add(key)  # prevent intra-batch duplicates

    print(f"New records to write: {len(new_records)} (skipped {skipped_existing} existing)")

    if not new_records:
        print("Nothing to write.")
        return

    # Group by month
    by_month: dict[str, list[dict]] = {}
    for r in new_records:
        month = r["catalyst_date"][:7]
        by_month.setdefault(month, []).append(r)

    for month, records in sorted(by_month.items()):
        month_dir = RESOLUTION_DIR / month
        if not args.dry_run:
            month_dir.mkdir(parents=True, exist_ok=True)
        for r in records:
            filename = f"{r['ticker']}_{r['catalyst_date']}.json"
            filepath = month_dir / filename
            if args.dry_run:
                print(f"  [DRY] {filepath.name}: {r['outcome']} — {r['catalyst_description'][:60]}")
            else:
                filepath.write_text(json.dumps(r, indent=4, default=str))
                print(f"  WROTE {filepath.name}: {r['outcome']}")

    # Summary
    from collections import Counter

    outcomes = Counter(r["outcome"] for r in new_records)
    types = Counter(r["catalyst_type"] for r in new_records)
    print(f"\nSummary: {len(new_records)} new records")
    print(f"  Outcomes: {dict(outcomes)}")
    print(f"  Types: {dict(types)}")

    # Count total resolutions
    total = len(existing)
    print(f"\nTotal resolutions (including new): {total}")
    if total >= 50:
        print("  TARGET REACHED: 50+ resolutions for outcome calibration")
    else:
        print(f"  Need {50 - total} more for outcome calibration target")


if __name__ == "__main__":
    main()
