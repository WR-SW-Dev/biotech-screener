#!/usr/bin/env python3
"""Weekly regulatory calendar maintenance audit.

Checks the manual calendar for:
  - Upcoming events by proximity band (14/45/90/180 days)
  - Missing as_of_disclosed_at on imminent entries
  - Duplicates after normalization
  - Past-dated entries (PDUFA date already passed)
  - Calendar freshness (newest disclosed_at age)

Outputs:
    {out_dir}/REPORT.md
    {out_dir}/REPORT.json

Usage:
    python3 scripts/research/audit_regulatory_calendar_maintenance.py \
        --as-of-date 2026-03-10 \
        --out-dir output/research/reg_calendar_maintenance
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date as _date
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from common.regulatory_calendar import get_calendar_telemetry, load_and_validate, load_regulatory_calendar

PROXIMITY_BANDS = [
    ("imminent", 0, 14),
    ("near", 15, 45),
    ("mid", 46, 90),
    ("far", 91, 180),
]


def compute_proximity(records: List[Dict[str, str]], as_of_date: str) -> Dict[str, List[Dict[str, str]]]:
    """Group records by days-to-event proximity band."""
    try:
        ref = _date.fromisoformat(as_of_date)
    except ValueError:
        return {}

    bands: Dict[str, List[Dict[str, str]]] = {b[0]: [] for b in PROXIMITY_BANDS}
    for rec in records:
        pdufa = rec.get("pdufa_date", "")
        if not pdufa:
            continue
        try:
            pd = _date.fromisoformat(pdufa)
        except ValueError:
            continue
        days = (pd - ref).days
        if days < 0:
            continue
        for band_name, lo, hi in PROXIMITY_BANDS:
            if lo <= days <= hi:
                rec_copy = dict(rec)
                rec_copy["days_to_event"] = days
                bands[band_name].append(rec_copy)
                break
    # Sort each band by days
    for band_name in bands:
        bands[band_name].sort(key=lambda r: r.get("days_to_event", 999))
    return bands


def find_missing_disclosed(
    records: List[Dict[str, str]], max_days: int = 90, as_of_date: str = ""
) -> List[Dict[str, str]]:
    """Find records within max_days that lack as_of_disclosed_at."""
    try:
        ref = _date.fromisoformat(as_of_date)
    except ValueError:
        return []
    missing = []
    for rec in records:
        pdufa = rec.get("pdufa_date", "")
        disclosed = rec.get("as_of_disclosed_at", "")
        if not pdufa:
            continue
        try:
            pd = _date.fromisoformat(pdufa)
        except ValueError:
            continue
        days = (pd - ref).days
        if 0 <= days <= max_days and not disclosed:
            rec_copy = dict(rec)
            rec_copy["days_to_event"] = days
            missing.append(rec_copy)
    return missing


def find_past_dated(records: List[Dict[str, str]], as_of_date: str) -> List[Dict[str, str]]:
    """Find records where pdufa_date < as_of_date."""
    past = []
    for rec in records:
        pdufa = rec.get("pdufa_date", "")
        if pdufa and pdufa < as_of_date:
            past.append(rec)
    return past


def compute_freshness(records: List[Dict[str, str]], as_of_date: str) -> Dict[str, Any]:
    """Compute calendar freshness stats."""
    disclosed_dates = [r.get("as_of_disclosed_at", "") for r in records if r.get("as_of_disclosed_at", "")]
    if not disclosed_dates:
        return {"newest_disclosed_at": None, "age_days": None, "n_with_disclosed": 0}

    newest = max(disclosed_dates)
    try:
        age = (_date.fromisoformat(as_of_date) - _date.fromisoformat(newest)).days
    except ValueError:
        age = None
    return {
        "newest_disclosed_at": newest,
        "age_days": age,
        "n_with_disclosed": len(disclosed_dates),
        "n_total": len(records),
    }


def run_maintenance_audit(
    as_of_date: str,
    calendar_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Run the full maintenance audit."""
    # Load raw + validated
    raw = load_regulatory_calendar(path=calendar_path)
    records, errors = load_and_validate(path=calendar_path, as_of_date=as_of_date)
    telemetry = get_calendar_telemetry(records)

    # All records (not PIT-filtered) for maintenance view
    all_records, all_errors = load_and_validate(path=calendar_path)

    result: Dict[str, Any] = {
        "as_of_date": as_of_date,
        "raw_count": len(raw),
        "pit_eligible": len(records),
        "all_normalized": len(all_records),
        "telemetry": telemetry,
    }

    # Proximity bands (using all records, not just PIT-eligible)
    bands = compute_proximity(all_records, as_of_date)
    result["proximity"] = {
        name: [
            {
                "ticker": r["ticker"],
                "pdufa_date": r["pdufa_date"],
                "event_type": r.get("event_type", ""),
                "days": r.get("days_to_event", 0),
                "confidence": r.get("confidence", ""),
                "disclosed_at": r.get("as_of_disclosed_at", ""),
            }
            for r in recs
        ]
        for name, recs in bands.items()
    }

    # Missing disclosed_at on imminent entries
    missing_disc = find_missing_disclosed(all_records, max_days=90, as_of_date=as_of_date)
    result["missing_disclosed_at"] = [
        {
            "ticker": r["ticker"],
            "pdufa_date": r["pdufa_date"],
            "days": r.get("days_to_event", 0),
        }
        for r in missing_disc
    ]

    # Past-dated entries
    past = find_past_dated(all_records, as_of_date)
    result["past_dated"] = [{"ticker": r["ticker"], "pdufa_date": r["pdufa_date"]} for r in past]

    # Duplicates
    dupes = [e for e in all_errors if "duplicate" in e.lower()]
    result["duplicates"] = dupes

    # Freshness
    result["freshness"] = compute_freshness(all_records, as_of_date)

    # Validation errors
    result["validation_errors"] = errors + [e for e in all_errors if "duplicate" not in e.lower()]

    return result


def write_report(result: Dict[str, Any], out_dir: Path) -> Path:
    """Write REPORT.md + REPORT.json."""
    out_dir.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Regulatory Calendar Maintenance Report",
        "",
        f"**As-of date**: {result['as_of_date']}",
        f"**Raw entries**: {result['raw_count']}",
        f"**PIT-eligible**: {result['pit_eligible']}",
        f"**All normalized**: {result['all_normalized']}",
        "",
    ]

    # Freshness
    fresh = result.get("freshness", {})
    if fresh.get("newest_disclosed_at"):
        age = fresh.get("age_days")
        age_str = f"{age}d ago" if age is not None else "?"
        lines.append("**Calendar freshness**: newest disclosed_at = " f"{fresh['newest_disclosed_at']} ({age_str})")
        lines.append("**Disclosed coverage**: " f"{fresh.get('n_with_disclosed', 0)}/{fresh.get('n_total', 0)} entries")
    else:
        lines.append("**Calendar freshness**: no disclosed_at dates found")
    lines.append("")

    # Proximity bands
    lines.extend(["## Upcoming Events by Proximity", ""])
    for band_name, lo, hi in PROXIMITY_BANDS:
        entries = result.get("proximity", {}).get(band_name, [])
        lines.append(f"### {band_name.title()} ({lo}-{hi}d): {len(entries)} entries")
        lines.append("")
        if entries:
            lines.append("| Ticker | Date | Event | Days | Confidence | Disclosed |")
            lines.append("|--------|------|-------|------|------------|-----------|")
            for e in entries:
                lines.append(
                    f"| {e['ticker']} | {e['pdufa_date']} | {e['event_type'] or '—'} "
                    f"| {e['days']} | {e['confidence'] or '—'} | {e['disclosed_at'] or '—'} |"
                )
            lines.append("")
        else:
            lines.append("No entries in this band.")
            lines.append("")

    # Warnings
    warnings_count = 0

    missing_disc = result.get("missing_disclosed_at", [])
    if missing_disc:
        warnings_count += len(missing_disc)
        lines.extend(["## Missing as_of_disclosed_at (within 90d)", ""])
        lines.append("| Ticker | Date | Days |")
        lines.append("|--------|------|------|")
        for m in missing_disc:
            lines.append(f"| {m['ticker']} | {m['pdufa_date']} | {m['days']} |")
        lines.append("")

    past = result.get("past_dated", [])
    if past:
        lines.extend(["## Past-Dated Entries", ""])
        lines.append(f"{len(past)} entries have pdufa_date before {result['as_of_date']}.")
        lines.append("Consider marking with outcome in `notes` field.")
        lines.append("")

    dupes = result.get("duplicates", [])
    if dupes:
        warnings_count += len(dupes)
        lines.extend(["## Duplicates", ""])
        for d in dupes:
            lines.append(f"- {d}")
        lines.append("")

    val_errs = result.get("validation_errors", [])
    if val_errs:
        warnings_count += len(val_errs)
        lines.extend(["## Validation Errors", ""])
        for e in val_errs[:10]:
            lines.append(f"- {e}")
        if len(val_errs) > 10:
            lines.append(f"- ... and {len(val_errs) - 10} more")
        lines.append("")

    # Summary
    lines.extend(
        [
            "## Summary",
            "",
            f"- **Warnings**: {warnings_count}",
            f"- **Past-dated**: {len(past)}",
            f"- **Calendar status**: {'HEALTHY' if warnings_count == 0 else 'NEEDS_ATTENTION'}",
            "",
            "---",
            "*Generated by audit_regulatory_calendar_maintenance.py*",
        ]
    )

    md_path = out_dir / "REPORT.md"
    md_path.write_text("\n".join(lines))

    json_path = out_dir / "REPORT.json"
    with open(json_path, "w") as f:
        json.dump(result, f, indent=2, default=str)

    return md_path


def main():
    p = argparse.ArgumentParser(description="Weekly regulatory calendar maintenance audit")
    p.add_argument("--as-of-date", type=str, required=True)
    p.add_argument("--calendar-path", type=Path, default=None)
    p.add_argument(
        "--out-dir",
        type=Path,
        default=PROJECT_ROOT / "output" / "research" / "reg_calendar_maintenance",
    )
    args = p.parse_args()

    result = run_maintenance_audit(args.as_of_date, args.calendar_path)
    md_path = write_report(result, args.out_dir)
    print(f"Report: {md_path}")

    # Print summary
    print(f"\nCalendar: {result['raw_count']} raw → {result['pit_eligible']} PIT-eligible")
    for band_name, lo, hi in PROXIMITY_BANDS:
        n = len(result.get("proximity", {}).get(band_name, []))
        print(f"  {band_name:>9s} ({lo:>3d}-{hi:>3d}d): {n}")
    fresh = result.get("freshness", {})
    if fresh.get("newest_disclosed_at"):
        print(f"  Freshness: {fresh['newest_disclosed_at']} ({fresh.get('age_days', '?')}d ago)")
    n_warn = len(result.get("missing_disclosed_at", [])) + len(result.get("duplicates", []))
    print(f"  Warnings: {n_warn}")


if __name__ == "__main__":
    main()
