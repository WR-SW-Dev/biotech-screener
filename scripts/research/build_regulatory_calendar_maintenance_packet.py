#!/usr/bin/env python3
"""Build a maintenance packet for the regulatory calendar.

Aggregates:
  - Proximity bands (imminent/near/mid/far)
  - Calendar freshness (newest disclosed_at age)
  - Duplicates
  - Past-dated entries
  - Missing as_of_disclosed_at within 90 days
  - Slip leaders (from calendar_slips artifacts)
  - Chronic slip sources (source×confidence breakdown)
  - Suggested edits (REMOVE / ADD_DISCLOSED_AT / DEDUP / DOWNGRADE_CONF)

Outputs:
    {out_dir}/MAINTENANCE_PACKET.md
    {out_dir}/MAINTENANCE_PACKET.json

Usage:
    python3 scripts/research/build_regulatory_calendar_maintenance_packet.py \
        --as-of-date 2026-03-10 \
        --out-dir output/research/reg_calendar_maintenance_packet

    # With slip data:
    python3 scripts/research/build_regulatory_calendar_maintenance_packet.py \
        --as-of-date 2026-03-10 \
        --slips-root artifacts/calendar_slips \
        --snap-root data/snapshots \
        --out-dir output/research/reg_calendar_maintenance_packet
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.research.audit_regulatory_calendar_maintenance import PROXIMITY_BANDS, run_maintenance_audit

PDUFA_DEFAULT = PROJECT_ROOT / "production_data" / "pdufa_dates.json"

# Slip thresholds for edit classification
IMMINENT_DAYS = 14
LARGE_SLIP_DAYS = 14
CHRONIC_SLIP_COUNT = 2  # >=2 large slips → DOWNGRADE_CONF candidate
DOWNGRADE_SOURCE_TYPES = {"ANALYST_ESTIMATE", "CTGOV_ESTIMATE"}
DOWNGRADE_CONFIDENCE_TYPES = {"MED", "LOW"}


# ---------------------------------------------------------------------------
# Slip loading
# ---------------------------------------------------------------------------


def load_slip_artifacts(
    slips_root: Path,
    as_of_date: str,
    lookback_days: int = 7,
) -> Dict[str, Any]:
    """Load slip CSV + summary JSON from artifacts directory.

    Tries as_of_date dir first, then scans backwards up to lookback_days.
    Returns {"slips": [...], "summary": {...}, "slip_date": str} or empty dict.
    """
    from datetime import datetime, timedelta

    target = datetime.strptime(as_of_date, "%Y-%m-%d")
    for offset in range(0, lookback_days + 1):
        candidate_date = (target - timedelta(days=offset)).strftime("%Y-%m-%d")
        candidate_dir = slips_root / candidate_date

        csv_path = candidate_dir / "slips.csv"
        json_path = candidate_dir / "slip_summary.json"

        if not csv_path.is_file():
            continue

        slips = []
        with open(csv_path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                slips.append(row)

        summary = {}
        if json_path.is_file():
            with open(json_path, encoding="utf-8") as f:
                summary = json.load(f)

        return {"slips": slips, "summary": summary, "slip_date": candidate_date}

    return {}


def find_slip_leaders(slips: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Find tickers with imminent_large_slip: days <= 14 AND |slip| >= 14."""
    leaders = []
    for s in slips:
        imminent = s.get("imminent", "0") == "1"
        large_slip = s.get("large_slip", "0") == "1"
        if imminent and large_slip:
            leaders.append(
                {
                    "ticker": s["ticker"],
                    "family": s.get("family", ""),
                    "current_days": s.get("current_days", ""),
                    "slip_days": s.get("slip_days", ""),
                    "prior_days": s.get("prior_days", ""),
                    "current_source": s.get("current_source", ""),
                    "current_confidence": s.get("current_confidence", ""),
                }
            )
    leaders.sort(key=lambda x: abs(int(float(x.get("slip_days", 0) or 0))), reverse=True)
    return leaders


def find_chronic_slip_sources(slips: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Find source×confidence combos with repeated large slips."""
    from collections import defaultdict

    counts: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "large_count": 0, "tickers": set(), "total_abs_slip": 0}
    )
    for s in slips:
        if s.get("slip_days", "") == "":
            continue
        source = s.get("current_source", "") or s.get("prior_source", "") or "UNKNOWN"
        conf = s.get("current_confidence", "") or s.get("prior_confidence", "") or "UNKNOWN"
        key = f"{source}|{conf}"
        try:
            sv = int(float(s["slip_days"]))
        except (ValueError, TypeError):
            continue
        counts[key]["count"] += 1
        counts[key]["total_abs_slip"] += abs(sv)
        counts[key]["tickers"].add(s["ticker"])
        if abs(sv) >= LARGE_SLIP_DAYS:
            counts[key]["large_count"] += 1

    results = []
    for key, data in counts.items():
        source, conf = key.split("|", 1)
        if data["large_count"] >= CHRONIC_SLIP_COUNT:
            results.append(
                {
                    "source": source,
                    "confidence": conf,
                    "total_slips": data["count"],
                    "large_slips": data["large_count"],
                    "mean_abs_slip": round(data["total_abs_slip"] / data["count"], 1) if data["count"] else 0,
                    "tickers": sorted(data["tickers"]),
                }
            )
    results.sort(key=lambda x: -x["large_slips"])
    return results


# ---------------------------------------------------------------------------
# Suggested edits
# ---------------------------------------------------------------------------

# Canonical edit actions (v1: no REFRESH_DATE)
VALID_ACTIONS = frozenset({"REMOVE", "ADD_DISCLOSED_AT", "DEDUP", "DOWNGRADE_CONF"})


def _make_edit(
    ticker: str,
    pdufa_date: str,
    action: str,
    reason: str,
    old_fields: Optional[Dict[str, str]] = None,
    proposed_fields: Optional[Dict[str, str]] = None,
    evidence: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create a single suggested edit with full provenance."""
    return {
        "ticker": ticker,
        "pdufa_date": pdufa_date,
        "action": action,
        "reason": reason,
        "old_fields": old_fields or {},
        "proposed_fields": proposed_fields or {},
        "evidence": evidence or {},
    }


def build_suggested_edits(
    audit: Dict[str, Any],
    slip_data: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Derive a deterministic, ordered list of actionable suggested edits.

    Edit priority: REMOVE > ADD_DISCLOSED_AT > DEDUP > DOWNGRADE_CONF
    """
    edits: List[Dict[str, Any]] = []

    # 1. Past-dated entries → REMOVE
    for rec in audit.get("past_dated", []):
        edits.append(
            _make_edit(
                ticker=rec["ticker"],
                pdufa_date=rec["pdufa_date"],
                action="REMOVE",
                reason="pdufa_date is in the past",
                old_fields={"pdufa_date": rec["pdufa_date"]},
                proposed_fields={},
                evidence={"as_of_date": audit.get("as_of_date", "")},
            )
        )

    # 2. Slip leaders with LOW confidence → REMOVE
    if slip_data:
        leaders = slip_data.get("slip_leaders", [])
        already_removed = {e["ticker"] for e in edits if e["action"] == "REMOVE"}
        for leader in leaders:
            ticker = leader["ticker"]
            if ticker in already_removed:
                continue
            conf = leader.get("current_confidence", "").upper()
            if conf == "LOW":
                edits.append(
                    _make_edit(
                        ticker=ticker,
                        pdufa_date="",
                        action="REMOVE",
                        reason=f"imminent large slip ({leader.get('slip_days', '?')}d) + LOW confidence",
                        old_fields={"confidence": conf},
                        proposed_fields={},
                        evidence={
                            "slip_days": leader.get("slip_days", ""),
                            "current_days": leader.get("current_days", ""),
                            "prior_days": leader.get("prior_days", ""),
                            "source": leader.get("current_source", ""),
                        },
                    )
                )

    # 3. Missing disclosed_at within 90d → ADD_DISCLOSED_AT
    for rec in audit.get("missing_disclosed_at", []):
        edits.append(
            _make_edit(
                ticker=rec["ticker"],
                pdufa_date=rec["pdufa_date"],
                action="ADD_DISCLOSED_AT",
                reason=f"within {rec['days']}d but no as_of_disclosed_at",
                old_fields={"as_of_disclosed_at": ""},
                proposed_fields={"as_of_disclosed_at": "(needs manual lookup)"},
                evidence={"days_to_event": rec["days"]},
            )
        )

    # 4. Duplicates → DEDUP
    for dup_msg in audit.get("duplicates", []):
        edits.append(
            _make_edit(
                ticker="",
                pdufa_date="",
                action="DEDUP",
                reason=dup_msg,
            )
        )

    # 5. Chronic slip sources with MED/ANALYST → DOWNGRADE_CONF
    if slip_data:
        chronic = slip_data.get("chronic_slip_sources", [])
        downgraded_tickers: set = set()
        for entry in chronic:
            source = entry.get("source", "")
            conf = entry.get("confidence", "")
            if conf.upper() in DOWNGRADE_CONFIDENCE_TYPES or source.upper() in DOWNGRADE_SOURCE_TYPES:
                for ticker in entry.get("tickers", []):
                    if ticker in downgraded_tickers:
                        continue
                    downgraded_tickers.add(ticker)
                    edits.append(
                        _make_edit(
                            ticker=ticker,
                            pdufa_date="",
                            action="DOWNGRADE_CONF",
                            reason=(f"chronic large slips ({entry['large_slips']}x) " f"for {source}/{conf}"),
                            old_fields={"confidence": conf, "source": source},
                            proposed_fields={"confidence": "LOW"},
                            evidence={
                                "large_slips": entry["large_slips"],
                                "total_slips": entry["total_slips"],
                                "mean_abs_slip": entry["mean_abs_slip"],
                            },
                        )
                    )

    return edits


# ---------------------------------------------------------------------------
# Packet builder
# ---------------------------------------------------------------------------


def build_maintenance_packet(
    as_of_date: str,
    calendar_path: Optional[Path] = None,
    slips_root: Optional[Path] = None,
    lookback_days: int = 7,
) -> Dict[str, Any]:
    """Build the full maintenance packet."""
    audit = run_maintenance_audit(as_of_date, calendar_path)

    # Load slip data if available
    slip_data: Optional[Dict[str, Any]] = None
    if slips_root and slips_root.is_dir():
        raw_slips = load_slip_artifacts(slips_root, as_of_date, lookback_days)
        if raw_slips:
            slip_leaders = find_slip_leaders(raw_slips.get("slips", []))
            chronic_sources = find_chronic_slip_sources(raw_slips.get("slips", []))
            slip_data = {
                "slip_date": raw_slips["slip_date"],
                "slip_leaders": slip_leaders,
                "chronic_slip_sources": chronic_sources,
                "summary": raw_slips.get("summary", {}),
            }

    edits = build_suggested_edits(audit, slip_data)
    audit["suggested_edits"] = edits
    audit["n_suggested_edits"] = len(edits)
    if slip_data:
        audit["slip_data"] = slip_data

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
        lines.append("**Calendar freshness**: newest disclosed_at = " f"{fresh['newest_disclosed_at']} ({age_str})")
        lines.append("**Disclosed coverage**: " f"{fresh.get('n_with_disclosed', 0)}/{fresh.get('n_total', 0)} entries")
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

    # Slip leaders
    slip_data = packet.get("slip_data", {})
    slip_leaders = slip_data.get("slip_leaders", [])
    if slip_leaders:
        lines.extend(["## Slip Leaders (Imminent + Large Slip)", ""])
        lines.append("| Ticker | Family | Days | Slip | Prior Days | Source | Confidence |")
        lines.append("|--------|--------|------|------|------------|--------|------------|")
        for s in slip_leaders:
            lines.append(
                f"| {s['ticker']} | {s.get('family', '')} | {s.get('current_days', '')} "
                f"| {s.get('slip_days', '')} | {s.get('prior_days', '')} "
                f"| {s.get('current_source', '')} | {s.get('current_confidence', '')} |"
            )
        lines.append("")

    # Chronic slip sources
    chronic = slip_data.get("chronic_slip_sources", [])
    if chronic:
        lines.extend(["## Chronic Slip Sources", ""])
        lines.append("| Source | Confidence | Large Slips | Total | Mean |Slip| | Tickers |")
        lines.append("|--------|------------|------------|-------|------------|---------|")
        for c in chronic:
            tickers_str = ", ".join(c.get("tickers", [])[:5])
            if len(c.get("tickers", [])) > 5:
                tickers_str += f" (+{len(c['tickers']) - 5})"
            lines.append(
                f"| {c['source']} | {c['confidence']} | {c['large_slips']} "
                f"| {c['total_slips']} | {c['mean_abs_slip']:.1f}d | {tickers_str} |"
            )
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
            f"- **Slip leaders**: {len(slip_leaders)}",
            f"- **Chronic slip sources**: {len(chronic)}",
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
    p.add_argument("--calendar", type=Path, default=None, dest="calendar_path")
    p.add_argument("--snap-root", type=Path, default=None)
    p.add_argument("--slips-root", type=Path, default=None)
    p.add_argument("--lookback-days", type=int, default=7)
    p.add_argument(
        "--out-dir",
        type=Path,
        default=PROJECT_ROOT / "output" / "research" / "reg_calendar_maintenance_packet",
    )
    args = p.parse_args()

    packet = build_maintenance_packet(
        args.as_of_date,
        calendar_path=args.calendar_path,
        slips_root=args.slips_root,
        lookback_days=args.lookback_days,
    )
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

    slip_data = packet.get("slip_data", {})
    if slip_data:
        print(f"  Slip leaders: {len(slip_data.get('slip_leaders', []))}")
        print(f"  Chronic sources: {len(slip_data.get('chronic_slip_sources', []))}")


if __name__ == "__main__":
    main()
