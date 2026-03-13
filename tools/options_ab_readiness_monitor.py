#!/usr/bin/env python3
"""Options A/B readiness monitor.

Scans snapshot history for options_quality_composite population and
reports whether the clinical_plus_options candidate (73113d54) has
accumulated enough TT-populated snapshots for a meaningful weekly A/B.

Tracks the exact preconditions the A/B harness
(eval_b91_options_quality_weekly_ab.py) needs:
  - options_quality_composite populated (non-empty, non-zero)
  - REGULATORY + less_binary segment coverage (the target for the candidate)
  - ab_ready status from metadata.json
  - consecutive gaps (credential expiry, API outage)

Trigger threshold (configurable):
  - MIN_AB_READY_WEEKS: minimum weekly periods with ab_ready=true
  - Requires n_regulatory_less_binary_oqc > 0 in at least one snapshot

Usage:
    python tools/options_ab_readiness_monitor.py [--snapshot-root data/snapshots]
    python tools/options_ab_readiness_monitor.py --json  # machine-readable output
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

MIN_AB_READY_WEEKS = 10
"""Minimum weekly snapshots with ab_ready=true before triggering A/B."""

MIN_REG_LB_OQC_SNAPSHOTS = 1
"""At least one snapshot must have REGULATORY+less_binary OQC > 0."""


# ---------------------------------------------------------------------------
# Core scan
# ---------------------------------------------------------------------------


def scan_snapshot(snap_dir: Path) -> Optional[Dict[str, Any]]:
    """Extract options coverage metrics from a single snapshot date."""
    rankings_path = snap_dir / "rankings.csv"
    if not rankings_path.exists():
        return None

    try:
        with open(rankings_path, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    except Exception:
        return None

    if not rows:
        return None

    n_total = len(rows)
    n_has_data = sum(1 for r in rows if str(r.get("opt_has_data", "0")).strip() == "1")
    n_oqc = sum(1 for r in rows if r.get("options_quality_composite", "").strip() not in ("", "0", "0.0"))
    n_reg_lb_oqc = sum(
        1
        for r in rows
        if r.get("options_quality_composite", "").strip() not in ("", "0", "0.0")
        and str(r.get("catalyst_family", "")).strip() == "REGULATORY"
        and str(r.get("catalyst_bucket", "")).strip() == "less_binary"
    )

    # Check metadata for ab_ready if available
    meta_ab_ready = None
    meta_path = snap_dir / "metadata.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
            meta_ab_ready = meta.get("options_diagnostics", {}).get("ab_ready")
        except Exception:
            pass

    ab_ready = n_oqc > 0

    return {
        "date": snap_dir.name,
        "n_total": n_total,
        "n_has_data": n_has_data,
        "n_oqc_nonzero": n_oqc,
        "n_regulatory_less_binary_oqc": n_reg_lb_oqc,
        "ab_ready": ab_ready,
        "meta_ab_ready": meta_ab_ready,
    }


def scan_all_snapshots(snapshot_root: Path) -> List[Dict[str, Any]]:
    """Scan all snapshot dates and return sorted results."""
    results = []
    for entry in sorted(snapshot_root.iterdir()):
        if not entry.is_dir():
            continue
        # Skip non-date directories (e.g. _archive_weekends, __pre_ dirs)
        name = entry.name
        if not name[:4].isdigit() or "__" in name:
            continue
        metrics = scan_snapshot(entry)
        if metrics is not None:
            results.append(metrics)
    return results


def compute_readiness(
    snapshots: List[Dict[str, Any]],
    min_weeks: int = MIN_AB_READY_WEEKS,
    min_reg_lb: int = MIN_REG_LB_OQC_SNAPSHOTS,
) -> Dict[str, Any]:
    """Compute A/B readiness from snapshot scan results."""
    ab_ready_snapshots = [s for s in snapshots if s["ab_ready"]]
    n_ab_ready = len(ab_ready_snapshots)

    has_reg_lb = sum(1 for s in snapshots if s["n_regulatory_less_binary_oqc"] > 0)

    # Find gaps (consecutive non-ab_ready after first ab_ready)
    gaps = []
    in_gap = False
    gap_start = None
    found_first = False
    for s in snapshots:
        if s["ab_ready"]:
            found_first = True
            if in_gap:
                gaps.append({"start": gap_start, "end": s["date"]})
                in_gap = False
        elif found_first:
            if not in_gap:
                gap_start = s["date"]
                in_gap = True
    if in_gap:
        gaps.append({"start": gap_start, "end": "ongoing"})

    # Determine trigger status
    weeks_met = n_ab_ready >= min_weeks
    reg_lb_met = has_reg_lb >= min_reg_lb

    if weeks_met and reg_lb_met:
        trigger = "READY"
        trigger_detail = (
            f"Trigger met: {n_ab_ready} ab_ready snapshots (>= {min_weeks}), "
            f"{has_reg_lb} with REGULATORY+less_binary OQC (>= {min_reg_lb}). "
            f"Run eval_b91_options_quality_weekly_ab.py"
        )
    elif weeks_met and not reg_lb_met:
        trigger = "BLOCKED"
        trigger_detail = (
            f"Enough snapshots ({n_ab_ready} >= {min_weeks}) but "
            f"zero REGULATORY+less_binary OQC coverage. "
            f"Candidate cannot diverge from baseline until REGULATORY family appears."
        )
    else:
        remaining = min_weeks - n_ab_ready
        trigger = "ACCUMULATING"
        trigger_detail = (
            f"{n_ab_ready}/{min_weeks} ab_ready snapshots. "
            f"Need {remaining} more. "
            f"REGULATORY+less_binary coverage: {has_reg_lb} snapshots."
        )

    return {
        "schema": "options_ab_readiness.v1",
        "trigger": trigger,
        "trigger_detail": trigger_detail,
        "thresholds": {
            "min_ab_ready_weeks": min_weeks,
            "min_reg_lb_oqc_snapshots": min_reg_lb,
        },
        "totals": {
            "total_snapshots": len(snapshots),
            "ab_ready_snapshots": n_ab_ready,
            "snapshots_with_reg_lb_oqc": has_reg_lb,
        },
        "gaps": gaps,
        "candidate_id": "73113d54",
        "ab_harness": "scripts/research/eval_b91_options_quality_weekly_ab.py",
    }


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------


def print_report(
    snapshots: List[Dict[str, Any]],
    readiness: Dict[str, Any],
) -> None:
    """Print human-readable readiness report."""
    print("=" * 70)
    print("OPTIONS A/B READINESS MONITOR")
    print("=" * 70)
    print("  Candidate: 73113d54 (clinical_plus_options)")
    print(f"  Trigger: {readiness['trigger']}")
    print(f"  Detail: {readiness['trigger_detail']}")
    print()

    totals = readiness["totals"]
    print(f"  Total snapshots scanned: {totals['total_snapshots']}")
    print(f"  ab_ready snapshots: {totals['ab_ready_snapshots']}")
    print(f"  With REGULATORY+less_binary OQC: {totals['snapshots_with_reg_lb_oqc']}")
    print()

    if readiness["gaps"]:
        print("  Coverage gaps (after first ab_ready):")
        for gap in readiness["gaps"]:
            print(f"    {gap['start']} → {gap['end']}")
        print()

    # Show recent snapshots
    recent = snapshots[-10:] if len(snapshots) > 10 else snapshots
    if recent:
        print("  Recent snapshots:")
        print(f"  {'Date':<14} {'has_data':>8} {'OQC':>5} {'REG_LB':>6} {'ab_ready':>8}")
        print(f"  {'-'*14} {'-'*8} {'-'*5} {'-'*6} {'-'*8}")
        for s in recent:
            ab = "YES" if s["ab_ready"] else "no"
            print(
                f"  {s['date']:<14} {s['n_has_data']:>8} "
                f"{s['n_oqc_nonzero']:>5} {s['n_regulatory_less_binary_oqc']:>6} "
                f"{ab:>8}"
            )
    print()

    thresholds = readiness["thresholds"]
    progress = totals["ab_ready_snapshots"]
    target = thresholds["min_ab_ready_weeks"]
    pct = min(100.0, progress / max(target, 1) * 100)
    bar_len = 30
    filled = int(bar_len * pct / 100)
    bar = "#" * filled + "-" * (bar_len - filled)
    print(f"  Progress: [{bar}] {pct:.0f}% ({progress}/{target} weeks)")
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> None:
    p = argparse.ArgumentParser(
        description="Check options A/B readiness for candidate 73113d54.",
    )
    p.add_argument(
        "--snapshot-root",
        type=Path,
        default=Path("data/snapshots"),
        help="Root directory of snapshots",
    )
    p.add_argument(
        "--min-weeks",
        type=int,
        default=MIN_AB_READY_WEEKS,
        help=f"Minimum ab_ready weekly snapshots (default: {MIN_AB_READY_WEEKS})",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Output JSON instead of human-readable report",
    )
    args = p.parse_args(argv)

    snapshots = scan_all_snapshots(args.snapshot_root)
    readiness = compute_readiness(snapshots, min_weeks=args.min_weeks)

    if args.json:
        # Include per-snapshot detail in JSON mode
        readiness["snapshots"] = snapshots
        print(json.dumps(readiness, indent=2, default=str))
    else:
        print_report(snapshots, readiness)

    # Exit code reflects trigger status
    if readiness["trigger"] == "READY":
        sys.exit(0)
    elif readiness["trigger"] == "BLOCKED":
        sys.exit(2)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
