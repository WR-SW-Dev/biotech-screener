#!/usr/bin/env python3
"""backfill_resolution_predictions.py — One-shot backfill for prediction fields.

Walks existing catalyst resolution records under data/snapshots/resolutions/
and populates prediction_snapshot_date, prediction_dem_rank, and
prediction_composite_score where they are null. Idempotent — safe to re-run.

Pairs with the writer fix in tools/catalyst_resolution_tracker.py
(populates the same fields going forward at write time).

Usage:
    python tools/backfill_resolution_predictions.py --dry-run
    python tools/backfill_resolution_predictions.py            # apply
    python tools/backfill_resolution_predictions.py --reset    # null out (rollback)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tools.catalyst_resolution_tracker import _safe_float, get_prediction_snapshot  # noqa: E402

RES_DIR = REPO / "data" / "snapshots" / "resolutions"
SNAPS_DIR = REPO / "data" / "snapshots"

SKIP_FILENAMES = {
    "calibration_summary.json",
    "manual_overrides.json",
    "watchlist_current.json",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Report only; no writes")
    ap.add_argument("--reset", action="store_true", help="Null out the 3 fields (rollback)")
    args = ap.parse_args()

    n_total = n_updated = n_skipped_already = n_skipped_no_snap = n_bad = 0
    for f in RES_DIR.rglob("*.json"):
        if f.name in SKIP_FILENAMES:
            continue
        try:
            rec = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            n_bad += 1
            continue
        if not isinstance(rec, dict) or "ticker" not in rec or "catalyst_date" not in rec:
            n_bad += 1
            continue
        n_total += 1

        if args.reset:
            rec["prediction_snapshot_date"] = None
            rec["prediction_dem_rank"] = None
            rec["prediction_composite_score"] = None
            n_updated += 1
        else:
            if rec.get("prediction_composite_score") is not None:
                n_skipped_already += 1
                continue
            try:
                cat_date = date.fromisoformat(rec["catalyst_date"][:10])
            except ValueError:
                n_bad += 1
                continue
            snap = get_prediction_snapshot(rec["ticker"], cat_date, SNAPS_DIR)
            if snap.get("status") != "OK":
                n_skipped_no_snap += 1
                continue
            rec["prediction_snapshot_date"] = snap.get("snapshot_date")
            try:
                rec["prediction_dem_rank"] = int(snap["dem_rank"]) if snap.get("dem_rank") else None
            except (TypeError, ValueError):
                rec["prediction_dem_rank"] = None
            rec["prediction_composite_score"] = _safe_float(snap.get("composite_score"))
            n_updated += 1

        if not args.dry_run:
            f.write_text(json.dumps(rec, indent=2, default=str) + "\n")

    print(f"Total resolution records walked: {n_total}")
    print(f"  Updated:                 {n_updated}")
    print(f"  Already populated (skip): {n_skipped_already}")
    print(f"  No prior snapshot (skip): {n_skipped_no_snap}")
    print(f"  Bad / unparseable:       {n_bad}")
    print(f"Mode: dry_run={args.dry_run}, reset={args.reset}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
