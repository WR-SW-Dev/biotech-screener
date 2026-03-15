#!/usr/bin/env python3
"""Harvest live options telemetry from snapshot rankings (Spec 021, Phase 3).

Builds a daily (date, ticker) panel from rankings.csv snapshots with
live chain-derived fields for RR/skew trend studies.

Usage:
    python scripts/research/build_live_options_timeseries.py \
        --snapshots-dir data/snapshots \
        --output data/research/live_options_timeseries.csv
"""
from __future__ import annotations

import argparse
import csv
import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

TELEMETRY_COLUMNS = [
    "date",
    "ticker",
    "catalyst_days",
    "catalyst_event_type",
    "catalyst_source",
    "is_hard_catalyst",
    "catalyst_family",
    "opt_atm_iv",
    "opt_rr_25d",
    "opt_put_call_skew",
    "opt_term_slope",
    "implied_event_move",
    "cheap_vol_score",
    "vol_classification",
    "market_model_disagreement",
    "pos_divergence",
    "ts_flag",
    "ts_flag_type",
]


def harvest_snapshots(snapshots_dir: Path) -> List[Dict[str, Any]]:
    """Read rankings.csv from each dated snapshot directory."""
    date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    rows: List[Dict[str, Any]] = []

    for d in sorted(snapshots_dir.iterdir()):
        if not d.is_dir() or not date_re.match(d.name):
            continue
        csv_path = d / "rankings.csv"
        if not csv_path.exists():
            continue
        try:
            with open(csv_path, newline="", encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    ticker = (row.get("ticker") or "").strip().upper()
                    if not ticker:
                        continue
                    entry = {"date": d.name, "ticker": ticker}
                    for col in TELEMETRY_COLUMNS[2:]:
                        entry[col] = row.get(col, "")
                    rows.append(entry)
        except (OSError, csv.Error) as exc:
            logger.warning("Skipping %s: %s", csv_path, exc)

    return rows


def compute_trailing_changes(
    rows: List[Dict[str, Any]],
) -> None:
    """Add trailing 5d and 7d changes for RR and skew (in-place)."""
    # Index by ticker → sorted list of (date, row_idx)
    from collections import defaultdict

    ticker_index: Dict[str, List[int]] = defaultdict(list)
    for i, r in enumerate(rows):
        ticker_index[r["ticker"]].append(i)

    for ticker, indices in ticker_index.items():
        # Already sorted by date (snapshots were iterated in order)
        for pos, idx in enumerate(indices):
            row = rows[idx]
            for field, lag in [
                ("opt_rr_25d", 5),
                ("opt_rr_25d", 7),
                ("opt_put_call_skew", 7),
            ]:
                col_name = f"{field}_change_{lag}d"
                current = row.get(field, "")
                if not current or current == "":
                    row[col_name] = ""
                    continue
                try:
                    current_val = float(current)
                except (ValueError, TypeError):
                    row[col_name] = ""
                    continue

                # Look back lag positions
                if pos >= lag:
                    prior_idx = indices[pos - lag]
                    prior_val_str = rows[prior_idx].get(field, "")
                    try:
                        prior_val = float(prior_val_str)
                        row[col_name] = round(current_val - prior_val, 6)
                    except (ValueError, TypeError):
                        row[col_name] = ""
                else:
                    row[col_name] = ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Harvest live options telemetry")
    parser.add_argument("--snapshots-dir", type=Path, default=PROJECT_ROOT / "data" / "snapshots")
    parser.add_argument(
        "--output", type=Path, default=PROJECT_ROOT / "data" / "research" / "live_options_timeseries.csv"
    )
    args = parser.parse_args()

    logger.info("Harvesting snapshots from %s ...", args.snapshots_dir)
    rows = harvest_snapshots(args.snapshots_dir)
    logger.info("Harvested %d rows", len(rows))

    if not rows:
        logger.warning("No snapshot data found")
        return 1

    logger.info("Computing trailing changes ...")
    compute_trailing_changes(rows)

    # Output columns
    output_cols = TELEMETRY_COLUMNS + [
        "opt_rr_25d_change_5d",
        "opt_rr_25d_change_7d",
        "opt_put_call_skew_change_7d",
    ]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=output_cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    # Coverage summary
    n_with_rr = sum(1 for r in rows if r.get("opt_rr_25d", "") not in ("", "0", "0.0"))
    n_with_skew = sum(1 for r in rows if r.get("opt_put_call_skew", "") not in ("", "0", "0.0"))
    n_with_iv = sum(1 for r in rows if r.get("opt_atm_iv", "") not in ("", "0", "0.0"))
    n_dates = len(set(r["date"] for r in rows))
    n_tickers = len(set(r["ticker"] for r in rows))

    summary = {
        "n_rows": len(rows),
        "n_dates": n_dates,
        "n_tickers": n_tickers,
        "n_with_rr_25d": n_with_rr,
        "n_with_skew": n_with_skew,
        "n_with_atm_iv": n_with_iv,
        "rr_coverage_pct": round(100 * n_with_rr / len(rows), 1) if rows else 0,
        "skew_coverage_pct": round(100 * n_with_skew / len(rows), 1) if rows else 0,
        "iv_coverage_pct": round(100 * n_with_iv / len(rows), 1) if rows else 0,
    }

    import json

    summary_dir = PROJECT_ROOT / "output" / "live_options_timeseries"
    summary_dir.mkdir(parents=True, exist_ok=True)
    (summary_dir / "coverage_summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    logger.info("Output → %s (%d rows, %d dates, %d tickers)", args.output, len(rows), n_dates, n_tickers)
    logger.info(
        "RR coverage: %d (%.1f%%), Skew: %d (%.1f%%), IV: %d (%.1f%%)",
        n_with_rr,
        summary["rr_coverage_pct"],
        n_with_skew,
        summary["skew_coverage_pct"],
        n_with_iv,
        summary["iv_coverage_pct"],
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
