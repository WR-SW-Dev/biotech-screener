#!/usr/bin/env python3
"""Backfill runway severity scores into historical snapshots.

Reads rankings.csv for each snapshot, scores with RunwaySeverityModel,
and writes a sidecar file runway_severity_overlay.json. Does NOT modify
rankings.csv (read-only backfill).

Output per snapshot:
    data/snapshots/{date}/runway_severity_overlay.json

Usage:
    python scripts/research/backfill_runway_severity.py
    python scripts/research/backfill_runway_severity.py --start 2025-01-01
    python scripts/research/backfill_runway_severity.py --start 2025-01-01 --end 2026-04-15
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("backfill_runway_severity")

SNAPSHOTS_DIR = PROJECT_ROOT / "data" / "snapshots"


def discover_snapshot_dates(start: str = "2020-01-01", end: str = "2099-12-31") -> List[str]:
    """Find snapshot dates with rankings.csv."""
    dates = []
    for d in sorted(SNAPSHOTS_DIR.iterdir()):
        if not d.is_dir() or "__pre" in d.name:
            continue
        if not (d / "rankings.csv").exists():
            continue
        if d.name < start or d.name > end:
            continue
        dates.append(d.name)
    return dates


def score_snapshot(snap_date: str) -> Dict[str, Any]:
    """Score one snapshot and return summary."""
    from event_ev.runway_severity import RunwaySeverityModel

    rpath = SNAPSHOTS_DIR / snap_date / "rankings.csv"
    rows = []
    with open(rpath, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(row)

    if not rows:
        return {"date": snap_date, "n": 0, "status": "empty"}

    model = RunwaySeverityModel()
    results = model.score_batch(rows, snap_date)

    overlays = [r.to_dict() for r in results]

    # Summary stats
    n = len(results)
    n_with_runway = sum(1 for r in results if r.months_to_cash_out is not None)
    n_gate_fail = sum(1 for r in results if not r.financing_truth_gate)
    buckets = {}
    for r in results:
        b = r.severity_bucket
        buckets[b] = buckets.get(b, 0) + 1

    severities = [r.runway_severity_score for r in results if r.months_to_cash_out is not None]
    ev_severities = [r.ev_severity_score for r in results if r.months_to_cash_out is not None]

    summary = {
        "schema": "runway_severity_backfill.v1",
        "snapshot_date": snap_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model_version": results[0].model_version if results else "unknown",
        "n_tickers": n,
        "n_with_runway": n_with_runway,
        "n_gate_fail": n_gate_fail,
        "buckets": buckets,
        "truth_severity_mean": round(sum(severities) / len(severities), 4) if severities else None,
        "ev_severity_mean": round(sum(ev_severities) / len(ev_severities), 4) if ev_severities else None,
        "overlays": overlays,
    }

    # Write sidecar
    out_path = SNAPSHOTS_DIR / snap_date / "runway_severity_overlay.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)

    return summary


def main():
    parser = argparse.ArgumentParser(description="Backfill runway severity")
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default="2099-12-31")
    parser.add_argument("--force", action="store_true", help="Overwrite existing overlays")
    args = parser.parse_args()

    dates = discover_snapshot_dates(args.start, args.end)
    logger.info("Found %d snapshots in range %s to %s", len(dates), args.start, args.end)

    scored = 0
    skipped = 0
    errors = 0

    for snap_date in dates:
        out_path = SNAPSHOTS_DIR / snap_date / "runway_severity_overlay.json"
        if out_path.exists() and not args.force:
            skipped += 1
            continue

        try:
            summary = score_snapshot(snap_date)
            scored += 1
            if scored % 50 == 0 or scored <= 3:
                logger.info(
                    "[%d/%d] %s: %d tickers, %d with runway, %d gate fails",
                    scored,
                    len(dates),
                    snap_date,
                    summary.get("n_tickers", 0),
                    summary.get("n_with_runway", 0),
                    summary.get("n_gate_fail", 0),
                )
        except Exception as e:
            logger.warning("Error scoring %s: %s", snap_date, e)
            errors += 1

    logger.info("Done: %d scored, %d skipped, %d errors", scored, skipped, errors)


if __name__ == "__main__":
    main()
