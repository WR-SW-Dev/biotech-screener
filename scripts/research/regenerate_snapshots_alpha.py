#!/usr/bin/env python3
"""Regenerate snapshot rankings.csv with re-scored alpha_cohort_pct.

For each snapshot date, builds an OOS alpha table using the specified
train_mode and horizon, re-scores alpha_cohort_raw and alpha_cohort_pct,
and writes the updated CSV to an output directory.

This enables acceptance replay testing of alpha training changes, which
cannot be tested by reranking frozen snapshots alone (alpha_cohort_pct
is baked into the CSV at screen time).

Example:
    python scripts/research/regenerate_snapshots_alpha.py \
        --train-mode trailing-3 --horizon 84 \
        --date-from 2026-02-02 --date-to 2026-03-10
"""

from __future__ import annotations

import argparse
import csv
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from module_5_alpha_cohort import attach_alpha_scores
from scripts.build_alpha_cohort_table_oos import build_oos_table

DEFAULT_SHRINK_K = 50.0
ALPHA_CLIP_MIN = -0.10
ALPHA_CLIP_MAX = 0.10


def discover_snapshot_dates(
    snapshot_root: Path,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> List[str]:
    """Find snapshot dates with rankings.csv."""
    dates = []
    for p in sorted(snapshot_root.iterdir()):
        if not p.is_dir() or len(p.name) != 10 or p.name[4] != "-":
            continue
        if date_from and p.name < date_from:
            continue
        if date_to and p.name > date_to:
            continue
        if (p / "rankings.csv").exists():
            dates.append(p.name)
    return dates


def regenerate_snapshot(
    snapshot_root: Path,
    out_root: Path,
    date_str: str,
    train_mode: str,
    horizon: int,
    min_train_dates: int,
    shrink_k: float,
) -> Optional[str]:
    """Regenerate one snapshot with new alpha scores.

    Returns source tag or None if table build failed.
    """
    src_dir = snapshot_root / date_str
    dst_dir = out_root / date_str
    dst_dir.mkdir(parents=True, exist_ok=True)

    # Build OOS alpha table for this date
    table = build_oos_table(
        as_of_date=date_str,
        train_mode=train_mode,
        horizon=horizon,
        min_train_dates=min_train_dates,
        shrink_k=shrink_k,
    )

    if table is None:
        return None

    # Read source rankings
    src_csv = src_dir / "rankings.csv"
    with open(src_csv, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows: List[Dict[str, Any]] = list(reader)

    # Re-score alpha
    attach_alpha_scores(rows, table, shrink_k, ALPHA_CLIP_MIN, ALPHA_CLIP_MAX)

    # Ensure output columns include alpha fields
    for col in ("alpha_cohort_key", "alpha_cohort_raw", "alpha_cohort_pct"):
        if col not in fieldnames:
            fieldnames.append(col)

    # Write regenerated rankings.csv
    dst_csv = dst_dir / "rankings.csv"
    with open(dst_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            # Convert numeric fields back to strings for CSV
            for col in ("alpha_cohort_raw", "alpha_cohort_pct"):
                if col in row and not isinstance(row[col], str):
                    row[col] = str(row[col])
            writer.writerow(row)

    # Copy other snapshot files (decision_ruleset.json, metadata.json, etc.)
    for src_file in src_dir.iterdir():
        if src_file.name != "rankings.csv" and src_file.is_file():
            shutil.copy2(src_file, dst_dir / src_file.name)

    return f"rebuilt:{train_mode}:h{horizon}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Regenerate snapshots with re-scored alpha_cohort_pct")
    parser.add_argument("--train-mode", type=str, default="trailing-3")
    parser.add_argument("--horizon", type=int, default=84)
    parser.add_argument("--min-train-dates", type=int, default=3)
    parser.add_argument("--shrink-k", type=float, default=DEFAULT_SHRINK_K)
    parser.add_argument(
        "--snapshot-root",
        type=Path,
        default=PROJECT_ROOT / "data" / "snapshots",
    )
    parser.add_argument(
        "--out-root",
        type=Path,
        default=None,
        help="Output dir (default: data/snapshots_regen_{mode}_h{horizon})",
    )
    parser.add_argument("--date-from", type=str, default=None)
    parser.add_argument("--date-to", type=str, default=None)
    parser.add_argument("--log-level", type=str, default="WARNING")
    args = parser.parse_args()

    import logging

    logging.basicConfig(level=getattr(logging, args.log_level.upper()))

    out_root = args.out_root or (
        PROJECT_ROOT / "data" / f"snapshots_regen_{args.train_mode.replace('-', '')}_h{args.horizon}"
    )

    dates = discover_snapshot_dates(args.snapshot_root, args.date_from, args.date_to)
    print(f"Dates: {len(dates)} ({dates[0]} → {dates[-1]})" if dates else "No dates found")
    print(f"Config: {args.train_mode}, horizon={args.horizon}, shrink_k={args.shrink_k}")
    print(f"Output: {out_root}")

    success = 0
    skipped = 0
    for i, d in enumerate(dates, 1):
        result = regenerate_snapshot(
            args.snapshot_root,
            out_root,
            d,
            args.train_mode,
            args.horizon,
            args.min_train_dates,
            args.shrink_k,
        )
        if result:
            success += 1
            print(f"  [{i}/{len(dates)}] {d}: OK ({result})")
        else:
            skipped += 1
            print(f"  [{i}/{len(dates)}] {d}: SKIPPED (insufficient training data)")

    print(f"\nDone: {success} regenerated, {skipped} skipped")
    print(f"Output: {out_root}")


if __name__ == "__main__":
    main()
