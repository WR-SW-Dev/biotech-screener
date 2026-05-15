#!/usr/bin/env python3
"""Diagnostic script to understand why ev_severity_score is blank in production.

Answers three key questions:
1. Does the column exist at all?
2. Are values present or all blank?
3. Is the issue in compute (score_batch) or integration (enrich_csv_rows)?
"""

import csv
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def diagnose_snapshot(snapshot_date: str):
    """Run full diagnostic on a snapshot."""
    snap_path = Path("data/snapshots") / snapshot_date / "rankings.csv"

    if not snap_path.exists():
        logger.error(f"Snapshot not found: {snap_path}")
        return False

    logger.info(f"Reading {snap_path}")
    rows = list(csv.DictReader(snap_path.open()))
    logger.info(f"Loaded {len(rows)} rows")

    if not rows:
        logger.error("Snapshot is empty")
        return False

    sample_keys = list(rows[0].keys())
    logger.info(f"Columns in snapshot: {len(sample_keys)}")

    # Question 1: Column exists?
    has_col = "ev_severity_score" in rows[0]
    logger.info(f"Column 'ev_severity_score' exists: {has_col}")

    if has_col:
        # Question 2: Values populated?
        vals = [str(r.get("ev_severity_score", "")).strip() for r in rows]
        nonblank = sum(1 for v in vals if v and v not in ("None", "nan", "NaN"))
        logger.info(f"  → {nonblank}/{len(rows)} rows have non-blank values")

        if nonblank == 0:
            logger.warning("  → All values are blank/None. Column was created but never populated.")
            sample_vals = vals[:5]
            logger.info(f"  → Sample values: {sample_vals}")

            # Check related fields that should be populated if score_batch ran
            related_cols = [
                "runway_severity_score",
                "financing_truth_gate",
                "severity_bucket",
            ]
            for col in related_cols:
                if col in rows[0]:
                    col_nonblank = sum(1 for r in rows if (r.get(col) or "") not in ("", "None", "nan", "NaN", "False"))
                    logger.info(f"  → {col}: {col_nonblank}/{len(rows)} populated")
        else:
            logger.info("  ✓ Column has values. Issue is not blank-after-compute.")
    else:
        logger.error("  ✗ Column does not exist. enrich_csv_rows() was never called or failed silently.")
        logger.info(f"  → First 10 column names: {sample_keys[:10]}")

        # Check if runway_severity is in snapshot at all
        if "runway_severity_score" not in rows[0]:
            logger.error("  → runway_severity_score also missing. Entire runway module was skipped.")
        else:
            logger.info("  → runway_severity_score exists. Partial enrichment occurred.")

    # Question 3: Try to compute directly to confirm score_batch works
    logger.info("\nAttempting direct score_batch() test...")
    try:
        from event_ev.runway_severity import RunwaySeverityModel

        model = RunwaySeverityModel()
        test_rows = rows[:5]
        test_overlays = model.score_batch(test_rows, snapshot_date)

        if test_overlays:
            sample_score = test_overlays[0].ev_severity_score
            logger.info(f"  ✓ score_batch() returned scores. Sample: {sample_score}")

            if sample_score is None:
                logger.warning("  → score_batch returned None. May be upstream data issue.")
            else:
                logger.info("  → Compute works. Issue is in enrich_csv_rows() or write-back.")
        else:
            logger.error("  ✗ score_batch returned empty list.")

    except Exception as e:
        logger.warning(f"  ✗ score_batch raised: {e}")

    return True


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Diagnose ev_severity_score issues")
    parser.add_argument(
        "--date",
        default="2026-05-15",
        help="Snapshot date (YYYY-MM-DD)",
    )
    args = parser.parse_args()

    success = diagnose_snapshot(args.date)
    sys.exit(0 if success else 1)
