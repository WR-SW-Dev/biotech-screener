#!/usr/bin/env python3
"""Re-rank snapshots with binary_quality_score tiebreak in binary_91_180.

RESEARCH ONLY — A/B test for binary quality overlay.

Takes existing snapshots, computes binary_quality_score for each name,
and applies it as a small rank adjustment ONLY within the binary_91_180
bucket (catalyst_bucket == "less_binary").  Names in other buckets are
untouched.

The adjustment is:
    effective_rank = current_rank - (weight * binary_quality_score)

Since binary_quality_score is [0, 1], at weight=1.0 the maximum rank
shift is 1 position.  At weight=3.0, a perfect PDUFA/Phase 3 can jump
up to 3 positions.

Usage:
    python3 scripts/research/rerank_binary_quality.py \\
        --snapshot-root data/snapshots \\
        --out-root data/snapshots_reranked_bqs \\
        --weight 2.0
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from common.binary_quality_score import compute_binary_quality_score
from common.ranking_utils import backfill_columns
from common.ranking_utils import safe_float as _safe_float
from decision_engine import DecisionRuleset, assign_catalyst_bucket, compute_actionable_sort_key


def rerank_with_binary_quality(
    rows: List[Dict[str, str]],
    ruleset: DecisionRuleset,
    *,
    weight: float = 2.0,
    target_bucket: str = "less_binary",
) -> List[Dict[str, str]]:
    """Re-rank rows with binary_quality_score tiebreak in target bucket.

    Steps:
    1. Backfill missing columns
    2. Compute binary_quality_score for all rows
    3. Compute standard sort key
    4. For names in the target bucket, apply quality adjustment
    5. Re-sort and assign fresh actionable_rank
    """
    backfill_columns(rows)

    # Ensure catalyst_bucket is assigned
    for r in rows:
        if not r.get("catalyst_bucket"):
            cd_raw = r.get("catalyst_days", "")
            cd = _safe_float(cd_raw)
            cm = str(r.get("catalyst_mode", ""))
            r["catalyst_bucket"] = assign_catalyst_bucket(cd, cm)

    # Compute binary_quality_score for all rows
    for r in rows:
        bqs = compute_binary_quality_score(r)
        r["binary_quality_score"] = str(bqs)

    # Apply quality adjustment to effective_comp_rank for target bucket names.
    # The adjustment modifies the sort anchor BEFORE computing the sort key,
    # so the tuple structure is unchanged and non-target names are unaffected.
    #
    # For names in target bucket:
    #   tiebreaker_pct += weight * binary_quality_score
    # Since higher tiebreaker_pct → sorts earlier (negated in sort key),
    # higher quality → earlier sort position within the bucket.
    for r in rows:
        if r.get("catalyst_bucket") == target_bucket and r.get("eligible") == "1":
            bqs = float(r.get("binary_quality_score", "0"))
            # Boost tiebreaker_pct by quality * weight (scale: quality is 0-1,
            # tiebreaker_pct is 0-100, so weight=2.0 → max +2.0 pct boost)
            key = "alpha_cohort_pct" if ruleset.sort_anchor == "alpha_cohort" else "clinical_optionality_pct_dev"
            current = _safe_float(r.get(key))
            if current is not None:
                r[key] = str(current + bqs * weight)

    # Sort using production-identical logic (now with adjusted anchor)
    rows.sort(
        key=lambda r: compute_actionable_sort_key(
            decision_fields=r,
            archetype=r.get("archetype", ""),
            optionality=_safe_float(r.get("clinical_optionality_pct_dev")),
            composite_rank=r.get("composite_rank"),
            ticker=r.get("ticker", ""),
            catalyst_event_type=r.get("catalyst_event_type", ""),
            catalyst_source=r.get("catalyst_source", ""),
            ruleset=ruleset,
            tiebreaker_pct=(
                _safe_float(r.get("alpha_cohort_pct"))
                if ruleset.sort_anchor == "alpha_cohort"
                else (
                    _safe_float(r.get("commercial_quality_pct"))
                    if r.get("archetype", "").startswith("commercial_")
                    else _safe_float(r.get("clinical_optionality_pct_dev"))
                )
            ),
        )
    )

    # Assign fresh actionable_rank
    rank = 1
    for r in rows:
        if r.get("eligible") == "1":
            r["actionable_rank"] = str(rank)
            rank += 1
        else:
            r["actionable_rank"] = ""

    return rows


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Re-rank snapshots with binary_quality_score tiebreak",
    )
    parser.add_argument(
        "--snapshot-root",
        type=Path,
        default=PROJECT_ROOT / "data" / "snapshots",
    )
    parser.add_argument(
        "--out-root",
        type=Path,
        default=PROJECT_ROOT / "data" / "snapshots_reranked_bqs",
    )
    parser.add_argument(
        "--weight",
        type=float,
        default=2.0,
        help="Quality adjustment weight (default: 2.0). " "Max rank shift = weight * 1.0 positions.",
    )
    parser.add_argument(
        "--target-bucket",
        type=str,
        default="less_binary",
        help="Catalyst bucket to apply quality tiebreak to (default: less_binary = binary_91_180).",
    )
    parser.add_argument("--date-from", type=str, default=None)
    parser.add_argument("--date-to", type=str, default=None)
    parser.add_argument("--min-cols", type=int, default=50)
    parser.add_argument(
        "--ruleset",
        type=Path,
        default=None,
        help="Ruleset JSON. Default: latest snapshot's decision_ruleset.json.",
    )
    args = parser.parse_args()

    # Discover ruleset
    if args.ruleset:
        ruleset = DecisionRuleset.from_json(args.ruleset)
        print(f"Ruleset: {args.ruleset.name} (ID={ruleset.ruleset_id})")
    else:
        # Find latest snapshot with a ruleset
        snap_dirs = sorted(
            [d for d in args.snapshot_root.iterdir() if d.is_dir() and not d.name.startswith("_")],
            reverse=True,
        )
        ruleset = None
        for sd in snap_dirs:
            rs_path = sd / "decision_ruleset.json"
            if rs_path.exists():
                ruleset = DecisionRuleset.from_json(rs_path)
                print(f"Ruleset: {rs_path.name} from {sd.name} (ID={ruleset.ruleset_id})")
                break
        if ruleset is None:
            print("ERROR: No ruleset found in any snapshot.")
            sys.exit(1)

    args.out_root.mkdir(parents=True, exist_ok=True)

    # Discover snapshot dates
    snap_dates = sorted(
        d.name
        for d in args.snapshot_root.iterdir()
        if d.is_dir()
        and not d.name.startswith("_")
        and (d / "rankings.csv").exists()
        and (args.date_from is None or d.name >= args.date_from)
        and (args.date_to is None or d.name <= args.date_to)
    )

    print(f"Processing {len(snap_dates)} snapshots (weight={args.weight}, bucket={args.target_bucket})")

    n_processed = 0
    n_skipped = 0
    rank_shifts: List[int] = []

    for snap_date in snap_dates:
        src = args.snapshot_root / snap_date / "rankings.csv"
        with open(src, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        if not rows or len(rows[0]) < args.min_cols:
            n_skipped += 1
            continue

        # Capture original ranks for churn measurement
        orig_ranks = {}
        for r in rows:
            t = r.get("ticker", "")
            ar = r.get("actionable_rank", "")
            if t and ar:
                try:
                    orig_ranks[t] = int(float(ar))
                except (ValueError, TypeError):
                    pass

        # Re-rank
        rows = rerank_with_binary_quality(
            rows,
            ruleset,
            weight=args.weight,
            target_bucket=args.target_bucket,
        )

        # Measure rank shifts
        for r in rows:
            t = r.get("ticker", "")
            new_ar = r.get("actionable_rank", "")
            if t in orig_ranks and new_ar:
                shift = abs(int(new_ar) - orig_ranks[t])
                if shift > 0:
                    rank_shifts.append(shift)

        # Write output
        out_dir = args.out_root / snap_date
        out_dir.mkdir(parents=True, exist_ok=True)
        fieldnames = list(rows[0].keys())
        with open(out_dir / "rankings.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

        # Copy metadata if exists
        meta_src = args.snapshot_root / snap_date / "metadata.json"
        if meta_src.exists():
            meta = json.loads(meta_src.read_text())
            meta["rerank_binary_quality_weight"] = args.weight
            meta["rerank_target_bucket"] = args.target_bucket
            (out_dir / "metadata.json").write_text(json.dumps(meta, indent=2))

        n_processed += 1

    print(f"\nDone: {n_processed} processed, {n_skipped} skipped")
    if rank_shifts:
        avg_shift = sum(rank_shifts) / len(rank_shifts)
        max_shift = max(rank_shifts)
        pct_moved = len(rank_shifts) / max(1, n_processed * 20) * 100  # approx per top-20
        print(f"Rank churn: {len(rank_shifts)} names moved, avg shift={avg_shift:.1f}, max={max_shift}")
        print(f"Approx {pct_moved:.1f}% of top-20 holdings affected per date")
    print(f"Output: {args.out_root}")


if __name__ == "__main__":
    main()
