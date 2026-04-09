#!/usr/bin/env python3
"""Backfill calendar slip artifacts from historical weekly snapshots.

Walks all snapshot dates in a range, computes slip artifacts for each
consecutive pair, writes to the same artifact structure used by the live
slip tracker.  Then builds the first real source reliability table.

Deterministic and resumable: skips dates that already have artifacts.

Usage:
    python3 scripts/backfill_calendar_slips.py --start 2025-01-01 --end 2026-03-10
    python3 scripts/backfill_calendar_slips.py --start 2025-06-01 --end 2026-03-10 --force

Output:
    artifacts/calendar_slips/<date>/slips.csv  (per-week)
    artifacts/calendar_slips/<date>/slip_summary.json
    artifacts/calendar_slips/<date>/slip_summary.md
    artifacts/calendar_source_reliability/<end_date>/source_reliability.json
    artifacts/calendar_source_reliability/<end_date>/source_reliability.md
    output/research/slip_backfill_report.md  (validation report)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from common.regulatory_calendar import CalendarPolicy, load_and_validate, select_quality_entries
from common.source_reliability import (
    aggregate_reliability,
    apply_reliability_policy,
    render_reliability_md,
    write_reliability_json,
)
from tools.build_source_reliability import load_historical_slips
from tools.track_calendar_slips import ARTIFACTS_ROOT as SLIPS_ARTIFACTS_ROOT
from tools.track_calendar_slips import (
    check_calendar_slips,
    compute_slip_summary,
    compute_slips,
    find_prior_snapshot,
    load_snapshot_calendar,
    write_slip_artifacts,
)

DEFAULT_SNAP_ROOT = PROJECT_ROOT / "data" / "snapshots"
DEFAULT_RELIABILITY_ROOT = PROJECT_ROOT / "artifacts" / "calendar_source_reliability"
DEFAULT_REPORT_DIR = PROJECT_ROOT / "output" / "research"


# ---------------------------------------------------------------------------
# Snapshot discovery
# ---------------------------------------------------------------------------


def discover_snapshot_dates(
    snap_root: Path,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> List[str]:
    """Return sorted date strings with rankings.csv in range [start, end]."""
    dates = []
    if not snap_root.is_dir():
        return dates
    for entry in snap_root.iterdir():
        if not entry.is_dir():
            continue
        name = entry.name
        if len(name) != 10:
            continue
        if not (entry / "rankings.csv").is_file():
            continue
        if start and name < start:
            continue
        if end and name > end:
            continue
        dates.append(name)
    dates.sort()
    return dates


# ---------------------------------------------------------------------------
# Backfill
# ---------------------------------------------------------------------------


def backfill_slips(
    snap_root: Path,
    out_root: Path,
    dates: List[str],
    *,
    force: bool = False,
    lookback_days: int = 14,
) -> Dict[str, Any]:
    """Backfill slip artifacts for all dates.

    Returns summary dict with counts and per-date results.
    """
    from datetime import datetime

    results: List[Dict[str, Any]] = []
    skipped = 0
    errors = 0
    written = 0

    for date_str in dates:
        # Resumable: skip if artifact exists
        existing = out_root / date_str / "slips.csv"
        if existing.is_file() and not force:
            skipped += 1
            continue

        # Find prior snapshot
        prior = find_prior_snapshot(date_str, snap_root, lookback_days)
        if prior is None:
            results.append({"date": date_str, "status": "SKIP", "reason": "no prior"})
            continue

        prior_date, prior_dir = prior
        current_dir = snap_root / date_str

        d_current = datetime.strptime(date_str, "%Y-%m-%d")
        d_prior = datetime.strptime(prior_date, "%Y-%m-%d")
        elapsed = (d_current - d_prior).days

        try:
            prior_cal = load_snapshot_calendar(prior_dir)
            current_cal = load_snapshot_calendar(current_dir)

            slips = compute_slips(prior_cal, current_cal, prior_date, date_str, elapsed)
            summary = compute_slip_summary(slips)
            gate = check_calendar_slips(summary)

            write_slip_artifacts(
                slips,
                summary,
                prior_date,
                date_str,
                out_root=out_root,
                gate_result=gate,
            )

            results.append(
                {
                    "date": date_str,
                    "status": "OK",
                    "prior_date": prior_date,
                    "elapsed": elapsed,
                    "n_slips": len(slips),
                    "large_slip_count": summary.get("large_slip_count", 0),
                    "gate_status": gate.get("status", "?"),
                }
            )
            written += 1
        except Exception as exc:
            results.append({"date": date_str, "status": "ERROR", "reason": str(exc)})
            errors += 1

    return {
        "total_dates": len(dates),
        "written": written,
        "skipped": skipped,
        "errors": errors,
        "results": results,
    }


# ---------------------------------------------------------------------------
# Before/after selection diff
# ---------------------------------------------------------------------------


def compute_selection_diff(
    reliability_table: List[Dict[str, Any]],
    calendar_path: Optional[Path] = None,
    as_of_date: str = "",
) -> List[Dict[str, Any]]:
    """Compare date selection with and without reliability.

    Returns list of changed entries with old/new priority info.
    """
    records, _errors = load_and_validate(path=calendar_path, as_of_date=as_of_date)
    if not records:
        return []

    policy = CalendarPolicy()

    # Baseline (no reliability)
    baseline, _diag_base = select_quality_entries(records, as_of_date, policy=policy)
    baseline_order = [r["ticker"] for r in baseline]
    baseline_map = {r["ticker"]: i for i, r in enumerate(baseline)}

    # Reliability-aware
    aware, diag_aware = select_quality_entries(records, as_of_date, policy=policy, reliability_table=reliability_table)
    aware_order = [r["ticker"] for r in aware]
    aware_map = {r["ticker"]: i for i, r in enumerate(aware)}

    if baseline_order == aware_order:
        return []

    changes = []
    all_tickers = set(baseline_map) | set(aware_map)
    for ticker in sorted(all_tickers):
        base_rank = baseline_map.get(ticker)
        aware_rank = aware_map.get(ticker)
        if base_rank != aware_rank:
            # Find the record
            rec = next((r for r in records if r["ticker"] == ticker), {})
            changes.append(
                {
                    "ticker": ticker,
                    "source": rec.get("source", ""),
                    "confidence": rec.get("confidence", ""),
                    "base_rank": base_rank if base_rank is not None else "ABSENT",
                    "aware_rank": aware_rank if aware_rank is not None else "ABSENT",
                    "rank_delta": (aware_rank or 0) - (base_rank or 0),
                    "reliability_action": rec.get("_reliability_action", "ALLOW"),
                    "reliability_reason": rec.get("_reliability_reason", ""),
                }
            )

    return sorted(changes, key=lambda c: abs(c.get("rank_delta", 0)), reverse=True)


# ---------------------------------------------------------------------------
# Validation report
# ---------------------------------------------------------------------------


def build_validation_report(
    backfill_result: Dict[str, Any],
    buckets: List[Dict[str, Any]],
    selection_diff: List[Dict[str, Any]],
    *,
    n_weeks: int = 0,
    n_slip_rows: int = 0,
    as_of_date: str = "",
) -> str:
    """Build markdown validation report."""
    lines = [
        f"# Slip Backfill Validation Report — {as_of_date}",
        "",
        "## Backfill Summary",
        "",
        f"- Dates processed: {backfill_result['total_dates']}",
        f"- Artifacts written: {backfill_result['written']}",
        f"- Skipped (existing): {backfill_result['skipped']}",
        f"- Errors: {backfill_result['errors']}",
        "",
        "## Reliability Table",
        "",
        f"- Weeks aggregated: {n_weeks}",
        f"- Total slip observations: {n_slip_rows}",
        f"- Buckets: {len(buckets)}",
        "",
    ]

    # Bucket counts by action
    action_counts: Dict[str, int] = {}
    for b in buckets:
        a = b.get("action", "UNKNOWN")
        action_counts[a] = action_counts.get(a, 0) + 1

    lines.append("### Action Distribution")
    lines.append("")
    for action in ("ALLOW", "DEMOTE", "SUPPRESS", "UNKNOWN"):
        lines.append(f"- {action}: {action_counts.get(action, 0)}")
    lines.append("")

    # Full bucket table
    lines.append("### All Buckets")
    lines.append("")
    lines.append("| Source | Confidence | Family | N | Median |Slip| | Large Rate | Action |")
    lines.append("|--------|-----------|--------|---|-------------|------------|--------|")
    for b in sorted(buckets, key=lambda x: (-x.get("large_slip_rate", 0), -x.get("median_abs_slip_days", 0))):
        lines.append(
            f"| {b['source']} | {b['confidence']} | {b['family']} "
            f"| {b['sample_count']} | {b['median_abs_slip_days']:.0f}d "
            f"| {b['large_slip_rate']:.0%} | **{b.get('action', '?')}** |"
        )
    lines.append("")

    # Top worst buckets
    worst = [b for b in buckets if b.get("action") in ("DEMOTE", "SUPPRESS")]
    if worst:
        lines.append("### Worst Buckets (DEMOTE / SUPPRESS)")
        lines.append("")
        for b in worst:
            lines.append(
                f"- **{b['source']}|{b['confidence']}|{b['family']}**: " f"{b['action']} — {b.get('reason', '')}"
            )
        lines.append("")

    # Selection diff
    lines.append("## Selection Diff (Before vs After Reliability)")
    lines.append("")
    if not selection_diff:
        lines.append("No changes to date selection ordering.")
    else:
        lines.append(f"**{len(selection_diff)} entries changed ranking:**")
        lines.append("")
        lines.append("| Ticker | Source | Base Rank | Aware Rank | Delta | Action | Reason |")
        lines.append("|--------|--------|-----------|------------|-------|--------|--------|")
        for c in selection_diff:
            lines.append(
                f"| {c['ticker']} | {c['source']} "
                f"| {c['base_rank']} | {c['aware_rank']} | {c['rank_delta']:+d} "
                f"| {c['reliability_action']} | {c['reliability_reason']} |"
            )
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------


def run_backfill(
    start: str,
    end: str,
    *,
    snap_root: Path = DEFAULT_SNAP_ROOT,
    slips_out_root: Path = SLIPS_ARTIFACTS_ROOT,
    reliability_out_root: Path = DEFAULT_RELIABILITY_ROOT,
    report_dir: Path = DEFAULT_REPORT_DIR,
    force: bool = False,
    n_weeks: int = 26,
) -> Dict[str, Any]:
    """Full backfill pipeline: slips → reliability → diff → report."""
    print(f"Discovering snapshots in [{start}, {end}]...")
    dates = discover_snapshot_dates(snap_root, start, end)
    print(f"Found {len(dates)} snapshot dates")

    if len(dates) < 2:
        return {"error": "Need at least 2 snapshot dates", "status": "SKIP"}

    # Step 1: Backfill slip artifacts
    print("Backfilling slip artifacts...")
    backfill_result = backfill_slips(snap_root, slips_out_root, dates, force=force)
    print(
        f"  Written: {backfill_result['written']}, "
        f"Skipped: {backfill_result['skipped']}, "
        f"Errors: {backfill_result['errors']}"
    )

    # Step 2: Build reliability table
    print("Building reliability table...")
    slip_rows, dates_used = load_historical_slips(slips_out_root, end, n_weeks)
    if not slip_rows:
        return {
            "status": "SKIP",
            "error": "No slip data after backfill",
            "backfill": backfill_result,
        }

    buckets = aggregate_reliability(slip_rows)
    apply_reliability_policy(buckets)

    # Write reliability artifacts
    rel_json_path = reliability_out_root / end / "source_reliability.json"
    rel_md_path = reliability_out_root / end / "source_reliability.md"

    write_reliability_json(
        buckets,
        rel_json_path,
        as_of_date=end,
        n_weeks=len(dates_used),
        n_slip_rows=len(slip_rows),
    )
    rel_md = render_reliability_md(buckets, as_of_date=end, n_weeks=len(dates_used))
    rel_md_path.parent.mkdir(parents=True, exist_ok=True)
    rel_md_path.write_text(rel_md, encoding="utf-8")

    print(f"  {len(buckets)} buckets from {len(dates_used)} weeks, {len(slip_rows)} slip rows")
    for b in buckets:
        if b.get("action") in ("DEMOTE", "SUPPRESS"):
            print(f"  ** {b['source']}|{b['confidence']}|{b['family']}: {b['action']} — {b.get('reason', '')}")

    # Step 3: Selection diff
    print("Computing selection diff...")
    calendar_path = PROJECT_ROOT / "production_data" / "pdufa_dates.json"
    selection_diff = compute_selection_diff(buckets, calendar_path, end)
    print(f"  {len(selection_diff)} entries changed ranking")

    # Step 4: Validation report
    report = build_validation_report(
        backfill_result,
        buckets,
        selection_diff,
        n_weeks=len(dates_used),
        n_slip_rows=len(slip_rows),
        as_of_date=end,
    )
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "slip_backfill_report.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"\nReport: {report_path}")

    return {
        "status": "OK",
        "backfill": backfill_result,
        "n_weeks": len(dates_used),
        "n_slip_rows": len(slip_rows),
        "n_buckets": len(buckets),
        "buckets": buckets,
        "selection_diff": selection_diff,
        "paths": {
            "reliability_json": str(rel_json_path),
            "reliability_md": str(rel_md_path),
            "report": str(report_path),
        },
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill calendar slip artifacts + build reliability table")
    parser.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--snap-root", type=str, help="Snapshot directory root")
    parser.add_argument("--force", action="store_true", help="Overwrite existing artifacts")
    parser.add_argument("--n-weeks", type=int, default=26, help="Rolling window for reliability")
    args = parser.parse_args()

    snap_root = Path(args.snap_root) if args.snap_root else DEFAULT_SNAP_ROOT

    result = run_backfill(
        args.start,
        args.end,
        snap_root=snap_root,
        force=args.force,
        n_weeks=args.n_weeks,
    )

    if result.get("error"):
        print(f"ERROR: {result['error']}", file=sys.stderr)
        sys.exit(1)

    # Print summary
    print("\n" + "=" * 60)
    print("BACKFILL COMPLETE")
    print("=" * 60)
    print(f"Weeks: {result['n_weeks']}")
    print(f"Slip rows: {result['n_slip_rows']}")
    print(f"Buckets: {result['n_buckets']}")

    action_counts: Dict[str, int] = {}
    for b in result["buckets"]:
        a = b.get("action", "UNKNOWN")
        action_counts[a] = action_counts.get(a, 0) + 1
    for action in ("ALLOW", "DEMOTE", "SUPPRESS", "UNKNOWN"):
        if action in action_counts:
            print(f"  {action}: {action_counts[action]}")

    if result["selection_diff"]:
        print(f"\nSelection changes: {len(result['selection_diff'])}")
        for c in result["selection_diff"][:5]:
            print(f"  {c['ticker']}: {c['base_rank']} → {c['aware_rank']} ({c['reliability_action']})")
    else:
        print("\nNo selection changes (policy has no effect on current calendar)")


if __name__ == "__main__":
    main()
