#!/usr/bin/env python3
"""Re-rank snapshots with a bucket-specific sort anchor override.

RESEARCH ONLY — A/B test for bucket-specific sort anchors.

For names in the target bucket (default: binary_91_180 / less_binary),
replaces the sort anchor (tiebreaker_pct) with a specified feature.
Names in other buckets are untouched.

Supported anchor modes:
  - clinical: use clinical_score_z_tier (strongest positive IC in 91-180)
  - alpha_momentum: use de_alpha_60d (price momentum)
  - catalyst_decay: use catalyst_decay_w
  - clinical_plus_alpha: blend clinical_score_z_tier + de_alpha_60d

Usage:
    python3 scripts/research/rerank_bucket_anchor.py \\
        --snapshot-root data/snapshots \\
        --out-root data/snapshots_reranked_clinical \\
        --anchor-mode clinical \\
        --target-bucket less_binary
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from common.ranking_utils import backfill_columns
from common.ranking_utils import safe_float as _safe_float
from decision_engine import DecisionRuleset, assign_catalyst_bucket, compute_actionable_sort_key

# Anchor modes: feature(s) used to replace tiebreaker_pct within target bucket.
# The value is injected as tiebreaker_pct (0-100 scale), so we normalize.
ANCHOR_MODES = {
    "default": None,  # no override
    "clinical": ["clinical_score_z_tier"],
    "alpha_momentum": ["de_alpha_60d"],
    "catalyst_decay": ["catalyst_decay_w"],
    "clinical_plus_alpha": ["clinical_score_z_tier", "de_alpha_60d"],
    "clinical_plus_catalyst": ["clinical_score_z_tier", "catalyst_decay_w"],
}


def _compute_bucket_anchor(
    row: Dict[str, str],
    mode: str,
) -> Optional[float]:
    """Compute a synthetic tiebreaker_pct from the specified features.

    Returns a value on roughly 0-100 scale (higher = sorts earlier).
    """
    if mode == "clinical":
        # clinical_score_z_tier: typically -3 to +3, map to 0-100
        v = _safe_float(row.get("clinical_score_z_tier"))
        if v is None:
            return None
        return 50.0 + v * 15.0  # z=0 → 50, z=+2 → 80, z=-2 → 20

    if mode == "alpha_momentum":
        # de_alpha_60d: typically -0.5 to +0.5
        v = _safe_float(row.get("de_alpha_60d"))
        if v is None:
            return None
        return 50.0 + v * 50.0  # alpha=0 → 50, alpha=+0.5 → 75

    if mode == "catalyst_decay":
        # catalyst_decay_w: 0 to 1
        v = _safe_float(row.get("catalyst_decay_w"))
        if v is None:
            return None
        return v * 100.0  # 0→0, 1→100

    if mode == "clinical_plus_alpha":
        cz = _safe_float(row.get("clinical_score_z_tier"))
        alpha = _safe_float(row.get("de_alpha_60d"))
        if cz is None and alpha is None:
            return None
        cz_norm = 50.0 + (cz or 0) * 15.0
        alpha_norm = 50.0 + (alpha or 0) * 50.0
        return 0.6 * cz_norm + 0.4 * alpha_norm

    if mode == "clinical_plus_catalyst":
        cz = _safe_float(row.get("clinical_score_z_tier"))
        cat = _safe_float(row.get("catalyst_decay_w"))
        if cz is None and cat is None:
            return None
        cz_norm = 50.0 + (cz or 0) * 15.0
        cat_norm = (cat or 0) * 100.0
        return 0.6 * cz_norm + 0.4 * cat_norm

    return None


def rerank_with_bucket_anchor(
    rows: List[Dict[str, str]],
    ruleset: DecisionRuleset,
    *,
    anchor_mode: str = "clinical",
    target_bucket: str = "less_binary",
) -> List[Dict[str, str]]:
    """Re-rank rows with a bucket-specific sort anchor override."""
    backfill_columns(rows)

    # Ensure catalyst_bucket is assigned
    for r in rows:
        if not r.get("catalyst_bucket"):
            cd = _safe_float(r.get("catalyst_days"))
            cm = str(r.get("catalyst_mode", ""))
            r["catalyst_bucket"] = assign_catalyst_bucket(cd, cm)

    # Override tiebreaker_pct for target bucket names
    if anchor_mode != "default":
        anchor_col = "alpha_cohort_pct" if ruleset.sort_anchor == "alpha_cohort" else "clinical_optionality_pct_dev"
        for r in rows:
            if r.get("catalyst_bucket") == target_bucket and r.get("eligible") == "1":
                new_val = _compute_bucket_anchor(r, anchor_mode)
                if new_val is not None:
                    r[anchor_col] = str(new_val)

    # Sort using production-identical logic
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
        description="Re-rank snapshots with bucket-specific sort anchor",
    )
    parser.add_argument(
        "--snapshot-root",
        type=Path,
        default=PROJECT_ROOT / "data" / "snapshots",
    )
    parser.add_argument(
        "--out-root",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--anchor-mode",
        choices=list(ANCHOR_MODES.keys()),
        default="clinical",
    )
    parser.add_argument(
        "--target-bucket",
        default="less_binary",
    )
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
        and (args.date_from is None or d.name >= args.date_from)
        and (args.date_to is None or d.name <= args.date_to)
    )

    print(f"Re-ranking {len(snap_dates)} snapshots " f"(anchor={args.anchor_mode}, bucket={args.target_bucket})")

    n_processed = 0
    for snap_date in snap_dates:
        src = args.snapshot_root / snap_date / "rankings.csv"
        with open(src, "r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        if not rows or len(rows[0]) < args.min_cols:
            continue

        rows = rerank_with_bucket_anchor(
            rows,
            ruleset,
            anchor_mode=args.anchor_mode,
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
            meta["rerank_anchor_mode"] = args.anchor_mode
            meta["rerank_target_bucket"] = args.target_bucket
            (out_dir / "metadata.json").write_text(json.dumps(meta, indent=2))

        n_processed += 1

    print(f"Done: {n_processed} processed → {args.out_root}")


if __name__ == "__main__":
    main()
