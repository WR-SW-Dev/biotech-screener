#!/usr/bin/env python3
"""
forward_eval_ic_ledger.py — Extract and persist forward_eval IC values from recent snapshots.

Reads the gate_verdict_ledger to find snapshots where forward_eval was evaluated,
re-runs the forward_eval_gate logic to extract mean_ic, and logs to a dedicated ledger.

Used by Path C monitoring: tracks mean_ic trend through 2026-06-03 window (floor 0.0200).
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

# Repo root
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.forward_eval_gate import evaluate_rolling_ic

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("forward_eval_ic_ledger")


def extract_forward_eval_ic(
    snapshot_dir: Path,
    as_of_date: str,
    price_cache_base: Path,
    horizon: int = 20,
    lookback_n: int = 10,
) -> dict | None:
    """Run forward_eval_gate for a given snapshot and extract mean_ic.

    Returns dict with:
    - as_of_date: snapshot date
    - mean_ic: rolling IC mean (rounded to 4 decimals)
    - median_ic: rolling IC median
    - n_evaluated: number of dates evaluated
    - status: 'PASS', 'WARN', or 'ERROR'
    - timestamp: when extracted

    Returns None if extraction fails.
    """
    try:
        status, msg, value, _ = evaluate_rolling_ic(
            snapshot_dir=snapshot_dir,
            price_cache_base=price_cache_base,
            current_date=as_of_date,
            horizon=horizon,
            lookback_n=lookback_n,
            ic_warn_floor=0.02,
            min_dates=1,
        )

        if "mean_ic" not in value:
            logger.warning(f"{as_of_date}: forward_eval status={status}, no mean_ic (cold start?)")
            return None

        return {
            "as_of_date": as_of_date,
            "mean_ic": value.get("mean_ic"),
            "median_ic": value.get("median_ic"),
            "n_evaluated": value.get("n_evaluated"),
            "ics": value.get("ics", []),
            "status": status,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
    except Exception as e:
        logger.error(f"{as_of_date}: forward_eval extraction failed: {e}")
        return None


def read_gate_verdict_ledger(ledger_path: Path) -> list[dict]:
    """Parse gate_verdict_ledger.jsonl and extract forward_eval verdicts."""
    if not ledger_path.exists():
        return []

    verdicts = []
    with open(ledger_path) as f:
        for line in f:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                if "forward_eval" in record.get("gates", {}):
                    verdicts.append(record)
            except json.JSONDecodeError:
                continue

    return verdicts


def append_to_ledger(ledger_path: Path, entry: dict) -> None:
    """Append entry to forward_eval_ic_ledger.jsonl."""
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with open(ledger_path, "a") as f:
        f.write(json.dumps(entry) + "\n")


def main():
    """Extract forward_eval IC from recent snapshots and log to ledger."""
    repo_root = REPO_ROOT
    snapshot_dir = repo_root / "data" / "snapshots"
    cache_base = repo_root / "data" / "caches" / "price_pit"
    gate_ledger = repo_root / "artifacts" / "gate_verdict_ledger.jsonl"
    ic_ledger = repo_root / "artifacts" / "forward_eval_ic_ledger.jsonl"

    # Read existing IC ledger to avoid duplicates
    existing_dates = set()
    if ic_ledger.exists():
        with open(ic_ledger) as f:
            for line in f:
                if line.strip():
                    try:
                        entry = json.loads(line)
                        existing_dates.add(entry["as_of_date"])
                    except json.JSONDecodeError:
                        continue

    # Find snapshots from gate verdict ledger
    verdicts = read_gate_verdict_ledger(gate_ledger)

    # Process recent snapshots (last 20 from verdicts)
    processed = 0
    for record in verdicts[-20:]:
        as_of_date = record.get("as_of_date")

        if not as_of_date or as_of_date in existing_dates:
            continue

        # Check if snapshot exists
        snap_path = snapshot_dir / as_of_date
        if not snap_path.exists():
            logger.debug(f"{as_of_date}: snapshot not found, skipping")
            continue

        # Extract IC
        ic_data = extract_forward_eval_ic(snap_path, as_of_date, cache_base)
        if ic_data:
            append_to_ledger(ic_ledger, ic_data)
            logger.info(
                f"{as_of_date}: extracted mean_ic={ic_data['mean_ic']:.4f} "
                f"(status={ic_data['status']}, n={ic_data['n_evaluated']})"
            )
            processed += 1

    logger.info(f"Processed {processed} new snapshot(s) for IC extraction")
    return 0


if __name__ == "__main__":
    sys.exit(main())
