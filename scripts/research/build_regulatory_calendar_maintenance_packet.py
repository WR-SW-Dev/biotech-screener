#!/usr/bin/env python3
"""Build a maintenance packet for the regulatory calendar.

Aggregates:
  - Proximity bands (imminent/near/mid/far)
  - Calendar freshness (newest disclosed_at age)
  - Duplicates
  - Past-dated entries
  - Missing as_of_disclosed_at within 90 days
  - Suggested edits (actionable list)

Outputs:
    {out_dir}/MAINTENANCE_PACKET.md
    {out_dir}/MAINTENANCE_PACKET.json

Usage:
    python3 scripts/research/build_regulatory_calendar_maintenance_packet.py \
        --as-of-date 2026-03-10 \
        --out-dir output/research/reg_calendar_maintenance
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.research.audit_regulatory_calendar_maintenance import PROXIMITY_BANDS, run_maintenance_audit

PDUFA_DEFAULT = PROJECT_ROOT / "production_data" / "pdufa_dates.json"


# ---------------------------------------------------------------------------
# Suggested edits
# ---------------------------------------------------------------------------


def build_suggested_edits(audit: Dict[str, Any]) -> List[Dict[str, str]]:
    """Derive a list of actionable suggested edits from audit results."""
    edits: List[Dict[str, str]] = []

    # 1. Past-dated entries → suggest removal
    for rec in audit.get("past_dated", []):
        edits.append(
            {
                "ticker": rec["ticker"],
                "pdufa_date": rec["pdufa_date"],
                "action": "REMOVE",
                "reason": "pdufa_date is in the past",
            }
        )

    # 2. Missing disclosed_at within 90d → suggest adding disclosed_at
    for rec in audit.get("missing_disclosed_at", []):
        edits.append(
            {
                "ticker": rec["ticker"],
                "pdufa_date": rec["pdufa_date"],
                "action": "ADD_DISCLOSED_AT",
                "reason": f"within {rec['days']}d but no as_of_disclosed_at",
            }
        )

    # 3. Duplicates → suggest dedup
    for dup_msg in audit.get("duplicates", []):
        edits.append(
            {
                "ticker": "",
                "pdufa_date": "",
                "action": "DEDUP",
                "reason": dup_msg,
            }
        )

    # 4. Freshness: if newest disclosed_at is >30d old → suggest refresh
    fresh = audit.get("freshness", {})
    age = fresh.get("age_days")
    if age is not None and age > 30:
        edits.append(
            {
                "ticker": "",
                "pdufa_date": "",
                "action": "REFRESH",
                "reason": f"newest disclosed_at is {age}d old (>30d threshold)",
            }
        )

    return edits


# ---------------------------------------------------------------------------
# Packet builder
# ---------------------------------------------------------------------------


def build_maintenance_packet(
    as_of_date: str,
    calendar_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Build the full maintenance packet."""
    audit = run_maintenance_audit(as_of_date, calendar_path)
    edits = build_suggested_edits(audit)
    audit["suggested_edits"] = edits
    audit["n_suggested_edits"] = len(edits)
    return audit


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------


def write_maintenance_packet(packet: Dict[str, Any], out_dir: Path) -> Path:
    """Write MAINTENANCE_PACKET.md + .json."""
    out_dir.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Regulatory Calendar Maintenance Packet",
        "",
        f"**As-of date**: {packet['as_of_date']}",
        f"**Raw entries**: {packet['raw_count']}",
        f"**PIT-eligible**: {packet['pit_eligible']}",
        f"**All normalized**: {packet['all_normalized']}",
        "",
    ]

    # Freshness
    fresh = packet.get("freshness", {})
    if fresh.get("newest_disclosed_at"):
        age = fresh.get("age_days")
        age_str = f"{age}d ago" if age is not None else "?"
        lines.append(f"**Calendar freshness**: newest disclosed_at = " f"{fresh['newest_disclosed_at']} ({age_str})")
        lines.append(
            f"**Disclosed coverage**: " f"{fresh.get('n_with_disclosed', 0)}/{fresh.get('n_total', 0)} entries"
        )
    else:
        lines.append("**Calendar freshness**: no disclosed_at dates found")
    lines.append("")

    # Proximity bands
    lines.extend(["## Proximity Bands", ""])
    for band_name, lo, hi in PROXIMITY_BANDS:
        entries = packet.get("proximity", {}).get(band_name, [])
        lines.append(f"### {band_name.title()} ({lo}-{hi}d): {len(entries)} entries")
        lines.append("")
        if entries:
            lines.append("| Ticker | Date | Event | Days | Confidence | Disclosed |")
            lines.append("|--------|------|-------|------|------------|-----------|")
            for e in entries:
                lines.append(
                    f"| {e['ticker']} | {e['pdufa_date']} | {e.get('event_type') or '—'} "
                    f"| {e['days']} | {e.get('confidence') or '—'} | {e.get('disclosed_at') or '—'} |"
                )
            lines.append("")
        else:
            lines.append("No entries in this band.")
            lines.append("")

    # Past-dated
    past = packet.get("past_dated", [])
    if past:
        lines.extend(["## Past-Dated Entries", ""])
        lines.append(f"{len(past)} entries have pdufa_date before {packet['as_of_date']}:")
        lines.append("")
        lines.append("| Ticker | Date |")
        lines.append("|--------|------|")
        for p in past:
            lines.append(f"| {p['ticker']} | {p['pdufa_date']} |")
        lines.append("")

    # Missing disclosed_at
    missing_disc = packet.get("missing_disclosed_at", [])
    if missing_disc:
        lines.extend(["## Missing as_of_disclosed_at (within 90d)", ""])
        lines.append("| Ticker | Date | Days |")
        lines.append("|--------|------|------|")
        for m in missing_disc:
            lines.append(f"| {m['ticker']} | {m['pdufa_date']} | {m['days']} |")
        lines.append("")

    # Duplicates
    dupes = packet.get("duplicates", [])
    if dupes:
        lines.extend(["## Duplicates", ""])
        for d in dupes:
            lines.append(f"- {d}")
        lines.append("")

    # Suggested edits
    edits = packet.get("suggested_edits", [])
    lines.extend(["## Suggested Edits", ""])
    if edits:
        lines.append(f"{len(edits)} suggested edit(s):")
        lines.append("")
        lines.append("| # | Ticker | Date | Action | Reason |")
        lines.append("|---|--------|------|--------|--------|")
        for i, e in enumerate(edits, 1):
            lines.append(
                f"| {i} | {e['ticker'] or '—'} | {e['pdufa_date'] or '—'} " f"| {e['action']} | {e['reason']} |"
            )
        lines.append("")
    else:
        lines.append("No edits suggested. Calendar is clean.")
        lines.append("")

    # Summary
    n_warnings = len(missing_disc) + len(dupes)
    status = "HEALTHY" if n_warnings == 0 and len(past) == 0 else "NEEDS_ATTENTION"
    lines.extend(
        [
            "## Summary",
            "",
            f"- **Warnings**: {n_warnings}",
            f"- **Past-dated**: {len(past)}",
            f"- **Suggested edits**: {len(edits)}",
            f"- **Calendar status**: {status}",
            "",
            "---",
            "*Generated by build_regulatory_calendar_maintenance_packet.py*",
        ]
    )

    md_path = out_dir / "MAINTENANCE_PACKET.md"
    md_path.write_text("\n".join(lines))

    json_path = out_dir / "MAINTENANCE_PACKET.json"
    with open(json_path, "w") as f:
        json.dump(packet, f, indent=2, default=str)
        f.write("\n")

    return md_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    p = argparse.ArgumentParser(description="Build regulatory calendar maintenance packet")
    p.add_argument("--as-of-date", type=str, required=True)
    p.add_argument("--calendar-path", type=Path, default=None)
    p.add_argument(
        "--out-dir",
        type=Path,
        default=PROJECT_ROOT / "output" / "research" / "reg_calendar_maintenance",
    )
    args = p.parse_args()

    packet = build_maintenance_packet(args.as_of_date, args.calendar_path)
    md_path = write_maintenance_packet(packet, args.out_dir)
    print(f"Packet: {md_path}")

    # Print summary
    print(f"\nCalendar: {packet['raw_count']} raw → {packet['pit_eligible']} PIT-eligible")
    for band_name, lo, hi in PROXIMITY_BANDS:
        n = len(packet.get("proximity", {}).get(band_name, []))
        print(f"  {band_name:>9s} ({lo:>3d}-{hi:>3d}d): {n}")
    fresh = packet.get("freshness", {})
    if fresh.get("newest_disclosed_at"):
        print(f"  Freshness: {fresh['newest_disclosed_at']} ({fresh.get('age_days', '?')}d ago)")
    edits = packet.get("suggested_edits", [])
    print(f"  Suggested edits: {len(edits)}")
    for e in edits:
        print(f"    - [{e['action']}] {e['ticker'] or '—'} {e['pdufa_date'] or ''}: {e['reason']}")


if __name__ == "__main__":
    main()
