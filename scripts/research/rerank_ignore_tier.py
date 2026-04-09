#!/usr/bin/env python3
"""Re-rank snapshots with tier contribution removed within a specific bucket.

RESEARCH ONLY — A/B test for tier-flattened sorting within binary_91_180.

Within the target bucket, sets tier_dev (and tier_any) to a constant so
that tier no longer affects ordering. Tier is preserved for eligibility
and labeling but removed from the sort tuple.

Usage:
    python3 scripts/research/rerank_ignore_tier.py \\
        --snapshot-root data/snapshots \\
        --out-root data/snapshots_reranked_notier \\
        --target-bucket less_binary
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from common.ranking_utils import backfill_columns
from common.ranking_utils import safe_float as _safe_float
from decision_engine import DecisionRuleset, assign_catalyst_bucket, compute_actionable_sort_key


def rerank_ignore_tier(
    rows: List[Dict[str, str]],
    ruleset: DecisionRuleset,
    *,
    target_bucket: str = "less_binary",
) -> List[Dict[str, str]]:
    """Re-rank rows with tier removed from sort within target bucket."""
    backfill_columns(rows)

    # Ensure catalyst_bucket is assigned
    for r in rows:
        if not r.get("catalyst_bucket"):
            cd = _safe_float(r.get("catalyst_days"))
            cm = str(r.get("catalyst_mode", ""))
            r["catalyst_bucket"] = assign_catalyst_bucket(cd, cm)

    # Save original tier values, then flatten tier within target bucket
    for r in rows:
        r["_orig_tier_dev"] = r.get("tier_dev", "")
        r["_orig_tier_any"] = r.get("tier_any", "")
        if r.get("catalyst_bucket") == target_bucket and r.get("eligible") == "1":
            # Set tier to "A" so all target-bucket names get tier_ord=1
            # This removes tier discrimination within the bucket
            r["tier_dev"] = "A"
            if r.get("tier_any"):
                r["tier_any"] = "A"

    # Sort using production-identical logic (now with flattened tier)
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

    # Restore original tier values (preserve labeling)
    for r in rows:
        r["tier_dev"] = r.pop("_orig_tier_dev")
        r["tier_any"] = r.pop("_orig_tier_any")

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
        description="Re-rank snapshots with tier removed within target bucket",
    )
    parser.add_argument(
        "--snapshot-root",
        type=Path,
        default=PROJECT_ROOT / "data" / "snapshots",
    )
    parser.add_argument("--out-root", type=Path, required=True)
    parser.add_argument("--target-bucket", default="less_binary")
    parser.add_argument("--date-from", default=None)
    parser.add_argument("--date-to", default=None)
    parser.add_argument("--min-cols", type=int, default=50)
    parser.add_argument("--ruleset", type=Path, default=None)
    args = parser.parse_args()

    # Discover ruleset
    if args.ruleset:
        ruleset = DecisionRuleset.from_json(args.ruleset)
    else:
        snap_dirs = sorted(
            [d for d in args.snapshot_root.iterdir() if d.is_dir() and not d.name.startswith("_")],
            reverse=True,
        )
        ruleset = None
        for sd in snap_dirs:
            rs_path = sd / "decision_ruleset.json"
            if rs_path.exists():
                ruleset = DecisionRuleset.from_json(rs_path)
                print(f"Ruleset: {sd.name} (ID={ruleset.ruleset_id})")
                break
        if ruleset is None:
            print("ERROR: No ruleset found")
            sys.exit(1)

    args.out_root.mkdir(parents=True, exist_ok=True)

    snap_dates = sorted(
        d.name
        for d in args.snapshot_root.iterdir()
        if d.is_dir()
        and not d.name.startswith("_")
        and (d / "rankings.csv").exists()
        and len(d.name) == 10
        and d.name[4] == "-"
        and (args.date_from is None or d.name >= args.date_from)
        and (args.date_to is None or d.name <= args.date_to)
    )

    print(f"Re-ranking {len(snap_dates)} snapshots (ignore tier in {args.target_bucket})")

    n_processed = 0
    for snap_date in snap_dates:
        src = args.snapshot_root / snap_date / "rankings.csv"
        with open(src, "r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        if not rows or len(rows[0]) < args.min_cols:
            continue

        rows = rerank_ignore_tier(
            rows,
            ruleset,
            target_bucket=args.target_bucket,
        )

        out_dir = args.out_root / snap_date
        out_dir.mkdir(parents=True, exist_ok=True)
        fieldnames = list(rows[0].keys())
        with open(out_dir / "rankings.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

        meta_src = args.snapshot_root / snap_date / "metadata.json"
        if meta_src.exists():
            meta = json.loads(meta_src.read_text())
            meta["rerank_ignore_tier_bucket"] = args.target_bucket
            (out_dir / "metadata.json").write_text(json.dumps(meta, indent=2))

        n_processed += 1

    print(f"Done: {n_processed} processed → {args.out_root}")


if __name__ == "__main__":
    main()
