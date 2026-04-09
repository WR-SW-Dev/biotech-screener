#!/usr/bin/env python3
"""Audit regulatory calendar coverage against a snapshot.

Reports:
  - eligible count
  - regulatory flagged count + coverage %
  - flagged tickers list with regulatory_days + event_type + source
  - manual calendar stats (loaded, PIT-eligible, by event_type/confidence)
  - overlap vs previous snapshot (newly added / dropped)

Exits nonzero if:
  - manual file loads but PIT-eligible count is 0 (likely schema error)
  - duplicates exist after normalization

Usage:
    python3 scripts/research/audit_regulatory_calendar_coverage.py \\
        --as-of-date 2026-03-08 --snapshot-root data/snapshots
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from common.regulatory_calendar import get_calendar_telemetry, load_and_validate, load_regulatory_calendar


def find_snapshot(snapshot_root: Path, as_of_date: str) -> Optional[Path]:
    """Find the snapshot directory for a given date."""
    snap = snapshot_root / as_of_date
    if snap.exists() and (snap / "rankings.csv").exists():
        return snap
    return None


def load_snapshot_regulatory(snap_path: Path) -> List[Dict[str, str]]:
    """Load rankings.csv and extract regulatory columns."""
    rankings_path = snap_path / "rankings.csv"
    rows = list(csv.DictReader(open(rankings_path, encoding="utf-8")))
    return rows


def compute_coverage(
    rows: List[Dict[str, str]],
) -> Tuple[int, int, List[Dict[str, str]]]:
    """Return (eligible_count, flagged_count, flagged_details)."""
    eligible = [r for r in rows if r.get("eligible") == "1"]
    flagged = [r for r in eligible if r.get("has_regulatory_upcoming_180d") == "1"]
    details = []
    for r in flagged:
        details.append(
            {
                "ticker": r.get("ticker", ""),
                "regulatory_days": r.get("regulatory_days", ""),
                "regulatory_event_type": r.get("regulatory_event_type", ""),
            }
        )
    details.sort(key=lambda x: int(x["regulatory_days"]) if x["regulatory_days"] else 999)
    return len(eligible), len(flagged), details


def compute_overlap(
    current_flagged: Set[str],
    prior_flagged: Set[str],
) -> Tuple[Set[str], Set[str], Set[str]]:
    """Return (kept, added, dropped) tickers."""
    kept = current_flagged & prior_flagged
    added = current_flagged - prior_flagged
    dropped = prior_flagged - current_flagged
    return kept, added, dropped


def find_prior_snapshot(snapshot_root: Path, as_of_date: str) -> Optional[Path]:
    """Find the most recent snapshot before as_of_date."""
    snaps = sorted(
        [d for d in snapshot_root.iterdir() if d.is_dir() and (d / "rankings.csv").exists()],
        key=lambda d: d.name,
    )
    prior = [s for s in snaps if s.name < as_of_date]
    return prior[-1] if prior else None


def run_audit(
    as_of_date: str,
    snapshot_root: Path,
    calendar_path: Optional[Path] = None,
) -> Dict:
    """Run the full audit and return results dict."""
    result: Dict = {"as_of_date": as_of_date, "exit_code": 0}

    # 1. Load and validate manual calendar
    raw = load_regulatory_calendar(path=calendar_path)
    records, errors = load_and_validate(
        path=calendar_path,
        as_of_date=as_of_date,
    )
    telemetry = get_calendar_telemetry(records)

    result["manual_calendar"] = {
        "raw_count": len(raw),
        "pit_eligible": len(records),
        "errors": errors,
        "telemetry": telemetry,
    }

    # Check: loaded but 0 PIT-eligible is suspicious
    if raw and not records:
        result["exit_code"] = 1
        result["manual_calendar"]["warning"] = "manual file loaded but 0 PIT-eligible records — likely schema error"

    if errors:
        dupes = [e for e in errors if e.startswith("duplicate")]
        if dupes:
            result["exit_code"] = 1
            result["manual_calendar"]["duplicate_warning"] = f"{len(dupes)} duplicates found"

    # 2. Load snapshot
    snap = find_snapshot(snapshot_root, as_of_date)
    if not snap:
        result["snapshot"] = {"error": f"no snapshot found for {as_of_date}"}
        return result

    rows = load_snapshot_regulatory(snap)
    eligible_count, flagged_count, flagged_details = compute_coverage(rows)

    result["snapshot"] = {
        "path": str(snap),
        "total_rows": len(rows),
        "eligible_count": eligible_count,
        "flagged_count": flagged_count,
        "coverage_pct": round(flagged_count / max(eligible_count, 1) * 100, 1),
        "flagged_details": flagged_details,
    }

    # 3. Overlap with prior snapshot
    prior_snap = find_prior_snapshot(snapshot_root, as_of_date)
    if prior_snap:
        prior_rows = load_snapshot_regulatory(prior_snap)
        _, _, prior_details = compute_coverage(prior_rows)
        current_tickers = {d["ticker"] for d in flagged_details}
        prior_tickers = {d["ticker"] for d in prior_details}
        kept, added, dropped = compute_overlap(current_tickers, prior_tickers)
        result["overlap"] = {
            "prior_snapshot": prior_snap.name,
            "prior_flagged": len(prior_tickers),
            "kept": sorted(kept),
            "added": sorted(added),
            "dropped": sorted(dropped),
        }

    return result


def print_report(result: Dict) -> None:
    """Print a human-readable report."""
    print(f"\n=== Regulatory Calendar Audit: {result['as_of_date']} ===\n")

    mc = result.get("manual_calendar", {})
    print(f"Manual Calendar: {mc.get('raw_count', 0)} raw → {mc.get('pit_eligible', 0)} PIT-eligible")
    tel = mc.get("telemetry", {})
    if tel.get("manual_calendar_by_event_type"):
        print(f"  By event_type: {tel['manual_calendar_by_event_type']}")
    if tel.get("manual_calendar_by_confidence"):
        print(f"  By confidence: {tel['manual_calendar_by_confidence']}")
    if mc.get("errors"):
        print(f"  Validation errors: {mc['errors'][:5]}")
    if mc.get("warning"):
        print(f"  WARNING: {mc['warning']}")

    snap = result.get("snapshot", {})
    if snap.get("error"):
        print(f"\nSnapshot: {snap['error']}")
    else:
        print(f"\nSnapshot: {snap.get('path', '?')}")
        print(f"  Eligible: {snap.get('eligible_count', 0)}")
        print(f"  Flagged:  {snap.get('flagged_count', 0)}")
        print(f"  Coverage: {snap.get('coverage_pct', 0)}%")
        print("\n  Flagged tickers:")
        for d in snap.get("flagged_details", []):
            print(f"    {d['ticker']:6s}  {d['regulatory_days']:>4s}d  {d['regulatory_event_type']}")

    overlap = result.get("overlap")
    if overlap:
        print(f"\n  vs prior ({overlap['prior_snapshot']}):")
        print(f"    Kept:    {overlap['kept']}")
        print(f"    Added:   {overlap['added']}")
        print(f"    Dropped: {overlap['dropped']}")

    if mc.get("pit_eligible", 0) == 0 and mc.get("raw_count", 0) > 0:
        print("\n  DATA SPARSE: manual file has records but none are PIT-eligible at this date")

    print(f"\nExit code: {result.get('exit_code', 0)}")


def main() -> None:
    p = argparse.ArgumentParser(description="Audit regulatory calendar coverage")
    p.add_argument("--as-of-date", type=str, required=True)
    p.add_argument("--snapshot-root", type=Path, default=PROJECT_ROOT / "data" / "snapshots")
    p.add_argument("--calendar-path", type=Path, default=None)
    args = p.parse_args()

    result = run_audit(args.as_of_date, args.snapshot_root, args.calendar_path)
    print_report(result)
    sys.exit(result.get("exit_code", 0))


if __name__ == "__main__":
    main()
