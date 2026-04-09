#!/usr/bin/env python3
"""Export ranked action lists (core + binary) from a snapshot's rankings.csv.

Reads ``data/snapshots/<date>/rankings.csv`` and writes two CSVs plus a
markdown summary:

* ``output/action_lists/<date>_core.csv``   — 91-180d + no_upcoming/missing
* ``output/action_lists/<date>_binary.csv`` — 0-30d + 31-90d catalysts

Usage:
    python tools/export_action_lists.py --date 2026-03-08
    python tools/export_action_lists.py --snapshot-dir data/snapshots/2026-03-08
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOTS_ROOT = PROJECT_ROOT / "data" / "snapshots"
OUTPUT_ROOT = PROJECT_ROOT / "output" / "action_lists"

# Bucket membership for each book
BINARY_BUCKETS = frozenset({"binary_now", "build_window"})
CORE_BUCKETS = frozenset({"less_binary", "core"})

# Columns to include in output CSVs
OUTPUT_COLUMNS = [
    "date",
    "ticker",
    "actionable_rank",
    "target_weight_pct",
    "tier_any",
    "catalyst_days",
    "catalyst_bucket",
    "catalyst_mode",
    "alpha_cohort_key",
    "clinical_optionality_pct_dev",
    "mom_state",
    "tier_any_reason",
]


def _safe_float(val: Any, default: float = 0.0) -> float:
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _load_rankings(snapshot_dir: Path) -> List[Dict[str, str]]:
    csv_path = snapshot_dir / "rankings.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"rankings.csv not found in {snapshot_dir}")
    with open(csv_path) as f:
        return list(csv.DictReader(f))


def _eligible_rows(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Filter to eligible rows with actionable_rank."""
    out = []
    for r in rows:
        if str(r.get("eligible", "")).strip() != "1":
            continue
        rank = r.get("actionable_rank", "").strip()
        if not rank:
            continue
        out.append(r)
    return out


def _assign_bucket_from_row(row: Dict[str, str]) -> str:
    """Read catalyst_bucket from row, falling back to on-the-fly assignment."""
    bucket = row.get("catalyst_bucket", "").strip()
    if bucket:
        return bucket
    # Fallback for older snapshots without catalyst_bucket column
    mode = row.get("catalyst_mode", "").strip()
    if mode in ("no_upcoming", "missing"):
        return "core"
    days = _safe_float(row.get("catalyst_days"), default=float("inf"))
    if days <= 30:
        return "binary_now"
    if days <= 90:
        return "build_window"
    if days <= 180:
        return "less_binary"
    return "core"


def split_by_book(
    rows: List[Dict[str, str]],
    as_of_date: str,
) -> tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    """Split eligible rows into (core, binary) action lists.

    Each output row includes OUTPUT_COLUMNS with the date prepended.
    Rows are sorted by actionable_rank ascending.
    """
    core, binary = [], []
    for r in _eligible_rows(rows):
        bucket = _assign_bucket_from_row(r)
        out_row = {"date": as_of_date}
        for col in OUTPUT_COLUMNS:
            if col == "date":
                continue
            out_row[col] = r.get(col, "")
        out_row["catalyst_bucket"] = bucket

        if bucket in BINARY_BUCKETS:
            binary.append(out_row)
        elif bucket in CORE_BUCKETS:
            core.append(out_row)
        # else: unknown bucket → skip

    def _rank_key(row):
        return _safe_float(row.get("actionable_rank"), default=9999)

    core.sort(key=_rank_key)
    binary.sort(key=_rank_key)
    return core, binary


def write_csv(rows: List[Dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_summary_md(
    core: List[Dict[str, str]],
    binary: List[Dict[str, str]],
    as_of_date: str,
    path: Path,
) -> None:
    """Write a markdown summary with top 20 of each list."""
    lines = [f"# Action Lists — {as_of_date}\n"]

    for label, rows in [("Binary Book (0-90d catalyst)", binary), ("Core Book (91d+ / no catalyst)", core)]:
        lines.append(f"\n## {label} ({len(rows)} names)\n")
        if not rows:
            lines.append("_No names in this book._\n")
            continue
        # Header
        lines.append("| # | Ticker | Rank | Weight% | Tier | Cat Days | Bucket | Momentum |")
        lines.append("|---|--------|------|---------|------|----------|--------|----------|")
        for i, r in enumerate(rows[:20], 1):
            lines.append(
                f"| {i} | {r.get('ticker', '')} "
                f"| {r.get('actionable_rank', '')} "
                f"| {r.get('target_weight_pct', '')} "
                f"| {r.get('tier_any', '')} "
                f"| {r.get('catalyst_days', '')} "
                f"| {r.get('catalyst_bucket', '')} "
                f"| {r.get('mom_state', '')} |"
            )
        if len(rows) > 20:
            lines.append(f"\n_... and {len(rows) - 20} more names._\n")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def export_action_lists(
    snapshot_dir: Path,
    output_dir: Optional[Path] = None,
    as_of_date: Optional[str] = None,
) -> tuple[Path, Path, Path]:
    """Main entry point: read snapshot, split, write outputs.

    Returns (core_csv_path, binary_csv_path, summary_md_path).
    """
    rows = _load_rankings(snapshot_dir)
    date = as_of_date or snapshot_dir.name
    out = output_dir or OUTPUT_ROOT

    core, binary = split_by_book(rows, date)

    core_path = out / f"{date}_core.csv"
    binary_path = out / f"{date}_binary.csv"
    summary_path = out / f"{date}_summary.md"

    write_csv(core, core_path)
    write_csv(binary, binary_path)
    write_summary_md(core, binary, date, summary_path)

    print(f"Core book:   {len(core)} names → {core_path}")
    print(f"Binary book: {len(binary)} names → {binary_path}")
    print(f"Summary:     {summary_path}")

    return core_path, binary_path, summary_path


def main():
    parser = argparse.ArgumentParser(description="Export core + binary action lists from snapshot")
    parser.add_argument("--date", help="Snapshot date (YYYY-MM-DD)")
    parser.add_argument("--snapshot-dir", help="Path to snapshot directory")
    parser.add_argument("--output-dir", help="Output directory (default: output/action_lists/)")
    args = parser.parse_args()

    if args.snapshot_dir:
        snap_dir = Path(args.snapshot_dir)
    elif args.date:
        snap_dir = SNAPSHOTS_ROOT / args.date
    else:
        print("Error: provide --date or --snapshot-dir", file=sys.stderr)
        sys.exit(1)

    if not snap_dir.is_dir():
        print(f"Error: {snap_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    out_dir = Path(args.output_dir) if args.output_dir else None
    export_action_lists(snap_dir, out_dir, args.date or snap_dir.name)


if __name__ == "__main__":
    main()
