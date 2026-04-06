#!/usr/bin/env python3
"""Backfill timing calibration ledger from historical snapshots.

For each pair of consecutive snapshots, checks whether catalysts predicted
in snapshot N actually arrived by snapshot N+1 (or later). This resolves
the cold-start problem for the calibration dashboard and base-rate trend.

Resolution logic:
  - For each catalyst in snapshot T with catalyst_days = D:
    - Expected event date = T + D days
    - Look at the same ticker in the NEXT snapshot T+1:
      - If catalyst_days decreased proportionally → ON_TIME (still tracking)
      - If catalyst_days reset to a much larger value → SLIP (date pushed out)
      - If ticker dropped from rankings → check if event passed (ON_TIME) or removed
    - For catalysts where expected_date < T+1, check if they appeared resolved

Usage:
    python scripts/research/backfill_timing_calibration.py
    python scripts/research/backfill_timing_calibration.py --min-date 2025-06-01
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import sys
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from tools.compute_timing_hazard import (
    NEAR_TERM_DAYS,
    NEAR_TERM_HARD_PROB,
    NEAR_TERM_REGULATORY_PROB,
    NEAR_TERM_SOFT_PROB,
    ROLLING_FALLBACK,
    classify_family_bucket,
    classify_hardness,
    classify_horizon_bucket,
)

SNAPSHOTS_DIR = PROJECT_ROOT / "data" / "snapshots"
OUTPUT_PATH = PROJECT_ROOT / "artifacts" / "timing_hazard" / "calibration_ledger.jsonl"

logger = logging.getLogger(__name__)


def _sf(v, default=None):
    if v is None or v == "":
        return default
    try:
        f = float(v)
        return f if not math.isnan(f) else default
    except (ValueError, TypeError):
        return default


def _get_clean_snapshots(min_date: str = "2025-01-01") -> list[str]:
    """Get sorted list of clean snapshot dates."""
    dates = []
    for d in SNAPSHOTS_DIR.iterdir():
        if not d.is_dir():
            continue
        name = d.name
        if "__pre_" in name or name.startswith("_"):
            continue
        if len(name) != 10:
            continue
        if name < min_date:
            continue
        if not (d / "rankings.csv").exists():
            continue
        dates.append(name)
    dates.sort()
    return dates


def _load_catalyst_map(snapshot_date: str) -> dict[str, dict]:
    """Load catalyst data keyed by ticker from a snapshot's rankings.csv."""
    path = SNAPSHOTS_DIR / snapshot_date / "rankings.csv"
    if not path.exists():
        return {}
    result = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rank = _sf(row.get("actionable_rank"))
            if rank is None or rank > 60:
                continue
            ticker = row.get("ticker", "")
            if not ticker:
                continue
            cat_days = _sf(row.get("catalyst_days"))
            if cat_days is None or cat_days <= 0:
                continue
            result[ticker] = {
                "catalyst_days": cat_days,
                "catalyst_event_type": row.get("catalyst_event_type", ""),
                "catalyst_family": row.get("catalyst_family", ""),
                "catalyst_source": row.get("catalyst_source", ""),
                "is_hard_catalyst": _sf(row.get("is_hard_catalyst"), 0) == 1.0,
                "clinical_days_precision": row.get("clinical_days_precision", "UNKNOWN"),
                "clinical_date_confidence": _sf(row.get("clinical_date_confidence"), 0.5),
            }
    return result


def _resolve_outcome(
    ticker: str,
    pred: dict,
    snap_date: date,
    next_snap_date: date,
    next_map: dict[str, dict],
) -> tuple[str | None, int | None]:
    """Determine if a catalyst prediction resolved ON_TIME or SLIP.

    Returns (outcome, delay_days) or (None, None) if unresolvable.
    """
    cat_days = pred["catalyst_days"]
    expected_date = snap_date + timedelta(days=int(cat_days))
    # If the expected date hasn't passed by next snapshot, skip (still pending)
    if expected_date > next_snap_date + timedelta(days=7):
        return None, None

    next_entry = next_map.get(ticker)

    # Case 1: Ticker gone from next snapshot — event likely resolved
    if next_entry is None:
        # Expected date was before next snapshot → probably on time
        if expected_date <= next_snap_date:
            return "ON_TIME", 0
        return None, None

    # Case 2: Ticker still present with catalyst data
    next_days = next_entry["catalyst_days"]
    next_expected = next_snap_date + timedelta(days=int(next_days))

    # If the next expected date is much later than original → SLIP
    slip_days = (next_expected - expected_date).days
    if slip_days > 14:
        return "SLIP", slip_days

    # If expected date passed and ticker still has a catalyst → might be new event
    if expected_date <= next_snap_date and next_days > 14:
        # This looks like the old event resolved and a new one appeared
        return "ON_TIME", 0

    # Expected date approaching/passed and next catalyst_days is small → ON_TIME
    if expected_date <= next_snap_date + timedelta(days=7):
        return "ON_TIME", max(0, (next_expected - expected_date).days)

    return None, None


def _slip_threshold(catalyst_days: float) -> int:
    """Compute adaptive slip threshold based on how far out the catalyst is.

    Near-term (0-30d): 14 days is a meaningful slip.
    Medium (31-90d): 21 days — some imprecision expected.
    Far (91-180d): 30 days — soft dates, monthly granularity common.
    Very far (180d+): 60 days — estimates shift by quarters routinely.
    """
    if catalyst_days <= 30:
        return 14
    if catalyst_days <= 90:
        return 21
    if catalyst_days <= 180:
        return 30
    return 60


def _resolve_outcome_multi(
    ticker: str,
    pred: dict,
    snap_date: date,
    future_snapshots: list[tuple[date, dict[str, dict]]],
) -> tuple[str | None, int | None, str | None]:
    """Multi-snapshot look-ahead resolution.

    Scans future snapshots until the expected event date has passed.
    Returns (outcome, delay_days, resolution_date) or (None, None, None).
    """
    cat_days = pred["catalyst_days"]
    expected_date = snap_date + timedelta(days=int(cat_days))
    threshold = _slip_threshold(cat_days)

    # Track consecutive pushouts for early slip confirmation
    consecutive_pushouts = 0
    EARLY_SLIP_CONFIRMATIONS = 2  # require 2+ consecutive pushouts before expected date

    for future_date, future_map in future_snapshots:
        # Before expected date window: only detect slips with confirmation
        if future_date < expected_date - timedelta(days=7):
            future_entry = future_map.get(ticker)
            if future_entry is not None:
                future_days = future_entry["catalyst_days"]
                future_expected = future_date + timedelta(days=int(future_days))
                slip_days = (future_expected - expected_date).days
                if slip_days > threshold:
                    consecutive_pushouts += 1
                    if consecutive_pushouts >= EARLY_SLIP_CONFIRMATIONS:
                        return "SLIP", slip_days, str(future_date)
                else:
                    consecutive_pushouts = 0  # reset on non-pushout
            continue

        future_entry = future_map.get(ticker)

        # Ticker gone from universe after expected date → ON_TIME
        if future_entry is None:
            return "ON_TIME", 0, str(future_date)

        future_days = future_entry["catalyst_days"]
        future_expected = future_date + timedelta(days=int(future_days))
        slip_days = (future_expected - expected_date).days

        # Date pushed out significantly → SLIP
        if slip_days > threshold:
            return "SLIP", slip_days, str(future_date)

        # Expected date passed, ticker has a new far-out catalyst → old event resolved
        if expected_date <= future_date and future_days > 14:
            return "ON_TIME", 0, str(future_date)

        # Expected date passed and catalyst_days is small → still tracking, ON_TIME
        if expected_date <= future_date + timedelta(days=7):
            return "ON_TIME", max(0, slip_days), str(future_date)

    return None, None, None


def _compute_on_time_prob(pred: dict) -> tuple[float, str]:
    """Compute the probability that would have been assigned."""
    cat_days = pred["catalyst_days"]
    family = pred["catalyst_family"]
    is_hard = pred["is_hard_catalyst"]

    if cat_days <= NEAR_TERM_DAYS:
        if family == "REGULATORY":
            return NEAR_TERM_REGULATORY_PROB, "near_term_rule"
        elif is_hard:
            return NEAR_TERM_HARD_PROB, "near_term_rule"
        else:
            return NEAR_TERM_SOFT_PROB, "near_term_rule"
    return ROLLING_FALLBACK, "rolling_base_rate"


def backfill_calibration(min_date: str = "2025-01-01", max_lookahead: int = 12) -> dict:
    """Backfill the calibration ledger from historical snapshots.

    Args:
        min_date: Earliest snapshot date to include.
        max_lookahead: Max number of future snapshots to check for resolution.
            Higher = more resolutions but slower. 12 ≈ ~3 months of weekly snapshots.
    """
    snapshots = _get_clean_snapshots(min_date)
    if len(snapshots) < 2:
        return {"error": "Need at least 2 snapshots", "n_resolved": 0}

    # Pre-load all catalyst maps (memory OK for ~400 snapshots × ~60 tickers)
    logger.info("Loading %d snapshots...", len(snapshots))
    snap_maps: dict[str, dict[str, dict]] = {}
    for s in snapshots:
        snap_maps[s] = _load_catalyst_map(s)

    entries = []
    seen_keys: set[tuple[str, str]] = set()  # (prediction_date, ticker) dedup
    n_unresolvable = 0

    for i in range(len(snapshots) - 1):
        snap_date_str = snapshots[i]
        snap_date = date.fromisoformat(snap_date_str)
        current_map = snap_maps[snap_date_str]

        # Build future snapshot list for multi-look-ahead
        future_end = min(i + 1 + max_lookahead, len(snapshots))
        future_snapshots = [
            (date.fromisoformat(snapshots[j]), snap_maps[snapshots[j]]) for j in range(i + 1, future_end)
        ]

        for ticker, pred in current_map.items():
            key = (snap_date_str, ticker)
            if key in seen_keys:
                continue

            # Skip FAR catalysts (>90d): dates are estimated, not scheduled.
            # Revisions are normal imprecision, not meaningful slips.
            # FAR horizon = >90d per classify_horizon_bucket().
            if pred["catalyst_days"] > 90:
                n_unresolvable += 1
                continue

            outcome, delay, resolution_date = _resolve_outcome_multi(ticker, pred, snap_date, future_snapshots)
            if outcome is None:
                n_unresolvable += 1
                continue

            seen_keys.add(key)
            on_time_prob, prob_method = _compute_on_time_prob(pred)
            family = pred["catalyst_family"]
            hardness = classify_hardness(pred["is_hard_catalyst"], pred["catalyst_source"])
            horizon = classify_horizon_bucket(pred["catalyst_days"])
            family_bucket = classify_family_bucket(family, pred["catalyst_event_type"])

            slip_prob = 1.0 - on_time_prob
            entries.append(
                {
                    "prediction_date": snap_date_str,
                    "ticker": ticker,
                    "catalyst_days": int(pred["catalyst_days"]),
                    "catalyst_event_type": pred["catalyst_event_type"],
                    "catalyst_family": family,
                    "is_hard_catalyst": pred["is_hard_catalyst"],
                    "family_bucket": family_bucket,
                    "horizon_bucket": horizon,
                    "hardness": hardness,
                    "source_provenance": pred["catalyst_source"],
                    "on_time_prob": round(on_time_prob, 3),
                    "on_time_prob_logistic": None,
                    "probability_method": prob_method,
                    "slip_prob_30d": round(slip_prob * 0.55, 3),
                    "slip_prob_60d_plus": round(slip_prob * 0.45, 3),
                    "timing_confidence_bucket": "BACKFILL",
                    "execution_warning_flag": False,
                    "warning_labels": [],
                    "actual_outcome": outcome,
                    "actual_delay_days": delay,
                    "outcome_recorded_at": resolution_date,
                }
            )

    return {
        "n_snapshots": len(snapshots),
        "n_resolved": len(entries),
        "n_unresolvable": n_unresolvable,
        "entries": entries,
    }


def main():
    parser = argparse.ArgumentParser(description="Backfill timing calibration ledger")
    parser.add_argument("--min-date", default="2025-06-01", help="Earliest snapshot to include")
    parser.add_argument("--dry-run", action="store_true", help="Print stats without writing")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    result = backfill_calibration(args.min_date)

    if "error" in result:
        print(f"ERROR: {result['error']}")
        sys.exit(1)

    entries = result["entries"]
    n_on_time = sum(1 for e in entries if e["actual_outcome"] == "ON_TIME")
    n_slip = sum(1 for e in entries if e["actual_outcome"] == "SLIP")

    print("TIMING CALIBRATION BACKFILL")
    print(f"  Snapshots: {result.get('n_snapshots', result.get('n_snapshot_pairs', '?'))}")
    print(f"  Resolved: {result['n_resolved']}")
    print(f"  Unresolvable: {result['n_unresolvable']}")
    print(f"  ON_TIME: {n_on_time} ({n_on_time / max(len(entries), 1) * 100:.1f}%)")
    print(f"  SLIP: {n_slip} ({n_slip / max(len(entries), 1) * 100:.1f}%)")

    # Breakdown by family
    from collections import Counter

    by_family = Counter()
    by_family_outcome = Counter()
    for e in entries:
        fb = e["family_bucket"]
        by_family[fb] += 1
        by_family_outcome[(fb, e["actual_outcome"])] += 1
    print("\n  By family:")
    for fb in sorted(by_family):
        n = by_family[fb]
        ot = by_family_outcome.get((fb, "ON_TIME"), 0)
        sl = by_family_outcome.get((fb, "SLIP"), 0)
        print(f"    {fb:12s}: {n:4d} (on_time={ot}, slip={sl}, rate={ot / max(n, 1):.1%})")

    if args.dry_run:
        print("\n  [DRY RUN — not writing]")
        return

    # Write to ledger (append, preserving existing forward entries)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Read existing entries to avoid duplicates
    existing_keys = set()
    if OUTPUT_PATH.exists():
        with open(OUTPUT_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                    key = (e.get("prediction_date", ""), e.get("ticker", ""))
                    existing_keys.add(key)
                except json.JSONDecodeError:
                    pass

    n_new = 0
    with open(OUTPUT_PATH, "a") as f:
        for entry in entries:
            key = (entry["prediction_date"], entry["ticker"])
            if key in existing_keys:
                continue
            f.write(json.dumps(entry, default=str) + "\n")
            n_new += 1

    print(f"\n  Written: {n_new} new entries (skipped {len(entries) - n_new} duplicates)")
    print(f"  Ledger: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
