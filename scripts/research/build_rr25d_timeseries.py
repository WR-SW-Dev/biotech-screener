#!/usr/bin/env python3
"""RR_25d directional timeseries and shift detection (Spec 021, Phase 3b).

Builds a per-(date, ticker) panel from snapshot rankings and historical IV
features, computing trailing RR trends and directional shift flags for
hard-catalyst names.

RR sign convention: call_iv - put_iv (Massive chain convention)
  positive = call skew / bullish lean
  negative = put skew / bearish lean

Usage:
    python scripts/research/build_rr25d_timeseries.py \
        --snapshots-dir data/snapshots \
        --iv-features data/research/historical_iv_features.csv \
        --output data/research/rr25d_timeseries.csv \
        --candidates-output output/rr25d_shift_candidates/rr25d_shift_candidates.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from common.hard_catalyst import classify_hard_catalyst  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

OUTPUT_COLUMNS = [
    "date",
    "ticker",
    "catalyst_days",
    "catalyst_family",
    "catalyst_event_type",
    "catalyst_source",
    "is_hard_catalyst",
    "opt_rr_25d_raw",
    "rr_source",
    "rr_25d_canonical",
    "opt_put_call_skew",
    "rr_25d_trend_5d",
    "rr_25d_trend_7d",
    "rr_25d_sign",
    "rr_25d_sign_flip_7d",
    "rr_25d_neg_streak_14d",
    "rr_25d_neg_streak_30d",
    "rr_25d_abs",
    "rr_25d_abs_change_7d",
    "rr_directional_shift_flag",
]


def _sf(v: Any, default: float = float("nan")) -> float:
    if v is None or v == "":
        return default
    try:
        f = float(v)
        return f if not math.isnan(f) else default
    except (ValueError, TypeError):
        return default


def load_iv_rr_history(
    path: Path,
) -> Dict[str, Dict[str, float]]:
    """Load historical rr_25d from IV features → {ticker: {date: rr_25d}}."""
    index: Dict[str, Dict[str, float]] = defaultdict(dict)
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            ticker = (row.get("ticker") or "").strip().upper()
            dt = (row.get("date") or "").strip()
            rr = _sf(row.get("rr_25d"))
            if ticker and dt and not math.isnan(rr):
                index[ticker][dt] = rr
    return dict(index)


def harvest_snapshot_rows(
    snapshots_dir: Path,
) -> List[Dict[str, Any]]:
    """Read rankings.csv from each dated snapshot."""
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

                    et = row.get("catalyst_event_type", "")
                    src = row.get("catalyst_source", "")
                    hc = classify_hard_catalyst(et, src)

                    rows.append(
                        {
                            "date": d.name,
                            "ticker": ticker,
                            "catalyst_days": row.get("catalyst_days", ""),
                            "catalyst_family": row.get("catalyst_family", ""),
                            "catalyst_event_type": et,
                            "catalyst_source": src,
                            "is_hard_catalyst": "1" if hc["is_hard_catalyst"] else "0",
                            "opt_rr_25d_raw": row.get("opt_rr_25d", ""),
                            "opt_put_call_skew": row.get("opt_put_call_skew", ""),
                        }
                    )
        except (OSError, csv.Error) as exc:
            logger.warning("Skipping %s: %s", csv_path, exc)

    return rows


def enrich_with_history_and_signals(
    rows: List[Dict[str, Any]],
    rr_history: Dict[str, Dict[str, float]],
) -> None:
    """Add canonical RR, trailing trends, and shift flags (in-place)."""
    # Index by ticker for trailing computation
    ticker_rows: Dict[str, List[int]] = defaultdict(list)
    for i, r in enumerate(rows):
        ticker_rows[r["ticker"]].append(i)

    for ticker, indices in ticker_rows.items():
        hist = rr_history.get(ticker, {})

        # Build merged RR series: snapshot value preferred, then historical
        for idx in indices:
            r = rows[idx]
            raw = _sf(r.get("opt_rr_25d_raw"))

            if not math.isnan(raw):
                # Live snapshot value — already Massive convention (call - put)
                r["rr_25d_canonical"] = round(raw, 4)
                r["rr_source"] = "massive_chain"
            elif r["date"] in hist:
                # Historical IV features — same convention
                r["rr_25d_canonical"] = round(hist[r["date"]], 4)
                r["rr_source"] = "historical_features"
            else:
                r["rr_25d_canonical"] = ""
                r["rr_source"] = ""

        # Compute trailing signals
        for pos, idx in enumerate(indices):
            r = rows[idx]
            rr = _sf(r.get("rr_25d_canonical"))

            # rr_25d_sign
            if math.isnan(rr):
                r["rr_25d_sign"] = ""
            elif rr > 0:
                r["rr_25d_sign"] = "1"
            elif rr < 0:
                r["rr_25d_sign"] = "-1"
            else:
                r["rr_25d_sign"] = "0"

            # rr_25d_abs
            r["rr_25d_abs"] = round(abs(rr), 4) if not math.isnan(rr) else ""

            # Trailing trends (observation-based, not calendar)
            for lag, col in [(5, "rr_25d_trend_5d"), (7, "rr_25d_trend_7d")]:
                if pos >= lag:
                    prior_rr = _sf(rows[indices[pos - lag]].get("rr_25d_canonical"))
                    if not math.isnan(rr) and not math.isnan(prior_rr):
                        r[col] = round(rr - prior_rr, 6)
                    else:
                        r[col] = ""
                else:
                    r[col] = ""

            # rr_25d_abs_change_7d
            if pos >= 7:
                prior_abs = _sf(rows[indices[pos - 7]].get("rr_25d_abs"))
                cur_abs = _sf(r.get("rr_25d_abs"))
                if not math.isnan(cur_abs) and not math.isnan(prior_abs):
                    r["rr_25d_abs_change_7d"] = round(cur_abs - prior_abs, 6)
                else:
                    r["rr_25d_abs_change_7d"] = ""
            else:
                r["rr_25d_abs_change_7d"] = ""

            # rr_25d_sign_flip_7d: was negative median over prior 7, now >= 0
            if pos >= 7 and not math.isnan(rr) and rr >= 0:
                prior_rrs = []
                for j in range(max(0, pos - 7), pos):
                    v = _sf(rows[indices[j]].get("rr_25d_canonical"))
                    if not math.isnan(v):
                        prior_rrs.append(v)
                if prior_rrs and statistics.median(prior_rrs) < 0:
                    r["rr_25d_sign_flip_7d"] = "1"
                else:
                    r["rr_25d_sign_flip_7d"] = "0"
            else:
                r["rr_25d_sign_flip_7d"] = ""

            # Negative streaks
            for window, col in [(14, "rr_25d_neg_streak_14d"), (30, "rr_25d_neg_streak_30d")]:
                streak = 0
                for j in range(pos, max(pos - window, -1), -1):
                    v = _sf(rows[indices[j]].get("rr_25d_canonical"))
                    if math.isnan(v):
                        break
                    if v < 0:
                        streak += 1
                    else:
                        break
                r[col] = streak

            # Directional shift flag
            is_hard = r.get("is_hard_catalyst") == "1"
            cat_days = _sf(r.get("catalyst_days"))
            near_catalyst = 0 < cat_days <= 90
            neg_streak = r.get("rr_25d_neg_streak_14d", 0)
            trend_7d = _sf(r.get("rr_25d_trend_7d"))

            if (
                is_hard
                and near_catalyst
                and not math.isnan(rr)
                and rr >= 0
                and isinstance(neg_streak, int)
                and neg_streak >= 5
                and not math.isnan(trend_7d)
                and trend_7d >= 0.05
            ):
                r["rr_directional_shift_flag"] = "1"
            else:
                r["rr_directional_shift_flag"] = "0"


def main() -> int:
    parser = argparse.ArgumentParser(description="RR_25d directional timeseries builder")
    parser.add_argument("--snapshots-dir", type=Path, default=PROJECT_ROOT / "data" / "snapshots")
    parser.add_argument(
        "--iv-features", type=Path, default=PROJECT_ROOT / "data" / "research" / "historical_iv_features.csv"
    )
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "data" / "research" / "rr25d_timeseries.csv")
    parser.add_argument(
        "--candidates-output",
        type=Path,
        default=PROJECT_ROOT / "output" / "rr25d_shift_candidates" / "rr25d_shift_candidates.csv",
    )
    args = parser.parse_args()

    logger.info("Loading historical RR from %s ...", args.iv_features)
    rr_history = load_iv_rr_history(args.iv_features)
    logger.info("Loaded RR history for %d tickers", len(rr_history))

    logger.info("Harvesting snapshot rows ...")
    rows = harvest_snapshot_rows(args.snapshots_dir)
    logger.info("Harvested %d rows", len(rows))

    if not rows:
        logger.warning("No data")
        return 1

    logger.info("Computing signals ...")
    enrich_with_history_and_signals(rows, rr_history)

    # Write full timeseries
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    n_with_rr = sum(1 for r in rows if r.get("rr_25d_canonical") not in ("", None))
    n_shifts = sum(1 for r in rows if r.get("rr_directional_shift_flag") == "1")
    logger.info("Timeseries → %s (%d rows, %d with RR, %d shift flags)", args.output, len(rows), n_with_rr, n_shifts)

    # Write shift candidates
    candidates = [
        r
        for r in rows
        if r.get("is_hard_catalyst") == "1"
        and 0 < _sf(r.get("catalyst_days")) <= 90
        and r.get("rr_25d_canonical") not in ("", None)
    ]
    candidates.sort(
        key=lambda r: (
            -(1 if r.get("rr_directional_shift_flag") == "1" else 0),
            -_sf(r.get("rr_25d_trend_7d"), 0),
            _sf(r.get("catalyst_days"), 9999),
            -abs(_sf(r.get("rr_25d_canonical"), 0)),
        )
    )

    args.candidates_output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.candidates_output, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(candidates)

    logger.info("Candidates → %s (%d rows)", args.candidates_output, len(candidates))

    # Coverage summary
    summary = {
        "n_total": len(rows),
        "n_with_rr": n_with_rr,
        "rr_coverage_pct": round(100 * n_with_rr / len(rows), 1) if rows else 0,
        "n_hard_catalyst": sum(1 for r in rows if r.get("is_hard_catalyst") == "1"),
        "n_shift_flags": n_shifts,
        "n_candidates": len(candidates),
        "rr_convention": "call_iv - put_iv (positive = bullish)",
    }
    summary_dir = args.candidates_output.parent
    (summary_dir / "coverage_summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
