#!/usr/bin/env python3
"""Backfill prediction fields into existing postmortem artifacts.

Reads each postmortem artifact, looks up the matching CRT resolution record
(keyed by ticker + event_date), and writes prediction_composite_score +
metadata into resolution_source.  Falls back to the pre_event snapshot_date
already stored in the artifact when no CRT record exists.

Safe to re-run: skips artifacts that already have a non-null
prediction_composite_score.  Does not touch selector/ranker/scoring logic.
"""

import csv
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
PM_DIR = REPO / "artifacts" / "postmortem"
RESOL_DIR = REPO / "data" / "snapshots" / "resolutions"
SNAPS_DIR = REPO / "data" / "snapshots"


def _load_crt_index():
    """Index all CRT records by (ticker, catalyst_date)."""
    idx = {}
    for month_dir in sorted(RESOL_DIR.iterdir()):
        if not month_dir.is_dir():
            continue
        for f in month_dir.glob("*.json"):
            try:
                d = json.loads(f.read_text())
                t, dt = d.get("ticker"), d.get("catalyst_date")
                if t and dt:
                    idx[(t, dt)] = d
            except Exception:
                pass
    return idx


def _snapshot_composite(ticker, snap_date):
    """Read composite_score for ticker from a specific snapshot date."""
    path = SNAPS_DIR / snap_date / "rankings.csv"
    if not path.exists():
        return None
    try:
        with open(path) as f:
            for row in csv.DictReader(f):
                if row.get("ticker") == ticker:
                    v = row.get("composite_score", "").strip()
                    return float(v) if v else None
    except Exception:
        pass
    return None


def main():
    crt = _load_crt_index()
    updated = skipped = no_data = 0

    for date_dir in sorted(PM_DIR.iterdir()):
        if not (date_dir.is_dir() and len(date_dir.name) == 10):
            continue
        event_date = date_dir.name

        for f in sorted(date_dir.glob("*.json")):
            ticker = f.stem
            try:
                d = json.loads(f.read_text())
            except Exception:
                continue
            if "pre_event" not in d:
                continue

            rs = d.get("resolution_source", {})
            if rs.get("prediction_composite_score") is not None:
                skipped += 1
                continue

            crt_rec = crt.get((ticker, event_date))
            if crt_rec:
                pred_score = crt_rec.get("prediction_composite_score")
                pred_snap = crt_rec.get("prediction_snapshot_date")
                pred_rank = crt_rec.get("prediction_dem_rank")
                pred_match = crt_rec.get("prediction_match_type")
            else:
                # Fallback: read directly from the pre_event snapshot already
                # recorded in the artifact.
                snap_date = d.get("pre_event", {}).get("snapshot_date")
                pred_score = _snapshot_composite(ticker, snap_date) if snap_date else None
                pred_snap = snap_date
                pred_rank = d.get("pre_event", {}).get("actionable_rank")
                pred_match = "snapshot_fallback" if pred_score is not None else None

            if "resolution_source" not in d:
                d["resolution_source"] = {}
            d["resolution_source"]["prediction_composite_score"] = pred_score
            d["resolution_source"]["prediction_snapshot_date"] = pred_snap
            d["resolution_source"]["prediction_dem_rank"] = pred_rank
            d["resolution_source"]["prediction_match_type"] = pred_match

            f.write_text(json.dumps(d, indent=2) + "\n")
            src = "crt" if crt_rec else "snap_fallback"
            print(f"  {ticker}@{event_date}: score={pred_score}  src={src}")
            updated += 1

    print(f"\nDone  updated={updated}  already_ok={skipped}  no_data={no_data}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
