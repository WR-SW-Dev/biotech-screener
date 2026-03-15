#!/usr/bin/env python3
"""Empirical post-event IV crush calibration (Spec 021, Phase 2).

For hard catalysts that resolved during the historical IV window, measure
pre/post ATM IV to calibrate crush ratios by event bucket.

Usage:
    python scripts/research/measure_iv_crush.py \
        --iv-features data/research/historical_iv_features.csv \
        --snapshots-dir data/snapshots \
        --price-csv production_data/price_history.csv \
        --event-subset hard \
        --output-dir output/iv_crush_calibration
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
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from common.hard_catalyst import classify_hard_catalyst  # noqa: E402

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

STUDY_SCHEMA = "iv_crush_calibration.v1"

BUCKET_MAP = {
    "FDA_PDUFA_DATE": "REGULATORY",
    "FDA_ADCOM": "REGULATORY",
    "FDA_CRL": "REGULATORY",
    "FDA_APPROVAL": "REGULATORY",
    "DATA_READOUT": "CLINICAL",
}


def _sf(v: Any, default: float = float("nan")) -> float:
    if v is None or v == "":
        return default
    try:
        f = float(v)
        return f if not math.isnan(f) else default
    except (ValueError, TypeError):
        return default


def _bucket(et: str, family: str) -> str:
    if et in BUCKET_MAP:
        return BUCKET_MAP[et]
    if family == "REGULATORY":
        return "REGULATORY"
    return "CLINICAL"


def load_iv_features(path: Path) -> Dict[str, Dict[str, Dict[str, float]]]:
    """Load → {ticker: {date: {atm_iv, actual_implied_move}}}."""
    index: Dict[str, Dict[str, Dict[str, float]]] = defaultdict(dict)
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            ticker = (row.get("ticker") or "").strip().upper()
            dt = (row.get("date") or "").strip()
            if not ticker or not dt:
                continue
            index[ticker][dt] = {
                "atm_iv": _sf(row.get("atm_iv")),
                "actual_implied_move": _sf(row.get("actual_implied_move")),
            }
    return dict(index)


def _trading_day_offset(ticker_dates: List[str], anchor: str, offset: int) -> Optional[str]:
    """Find the trading day at +/- offset from anchor in sorted dates list."""
    try:
        idx = ticker_dates.index(anchor)
    except ValueError:
        # Find nearest date
        for i, d in enumerate(ticker_dates):
            if d >= anchor:
                idx = i
                break
        else:
            return None

    target = idx + offset
    if 0 <= target < len(ticker_dates):
        return ticker_dates[target]
    return None


def find_resolved_events(
    snapshots_dir: Path,
    iv_index: Dict[str, Dict[str, Dict[str, float]]],
    event_subset: str,
    hard_filter_mode: str,
    event_window: int,
    pre_offsets: List[int],
    post_offsets: List[int],
) -> List[Dict[str, Any]]:
    """Find hard catalyst events that resolved during the IV history window."""
    date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    events = []
    seen = set()  # (ticker, estimated_event_date) dedup

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

                    cat_days = _sf(row.get("catalyst_days"))
                    if math.isnan(cat_days) or cat_days <= 0 or cat_days > event_window:
                        continue

                    et = row.get("catalyst_event_type", "")
                    src = row.get("catalyst_source", "")
                    family = row.get("catalyst_family", "")

                    if event_subset == "hard":
                        if hard_filter_mode == "snapshot_native":
                            if str(row.get("is_hard_catalyst", "0")).strip() != "1":
                                continue
                        else:
                            hc = classify_hard_catalyst(et, src)
                            if not hc["is_hard_catalyst"]:
                                continue

                    # Estimate event date
                    snap_date = date.fromisoformat(d.name)
                    est_event = snap_date + timedelta(days=int(cat_days))
                    est_str = est_event.isoformat()

                    # Dedup: keep the closest snapshot to the event
                    key = (ticker, est_str)
                    if key in seen:
                        continue
                    seen.add(key)

                    # Check if we have IV data around the event
                    ticker_data = iv_index.get(ticker, {})
                    if not ticker_data:
                        continue
                    ticker_dates = sorted(ticker_data.keys())

                    # Measure pre/post IV
                    measurements = {
                        "ticker": ticker,
                        "snap_date": d.name,
                        "estimated_event_date": est_str,
                        "catalyst_days": int(cat_days),
                        "catalyst_event_type": et,
                        "catalyst_source": src,
                        "bucket": _bucket(et, family),
                    }

                    has_pre = False
                    has_post = False

                    for off in pre_offsets:
                        dt = _trading_day_offset(ticker_dates, est_str, -off)
                        if dt and dt in ticker_data:
                            measurements[f"atm_iv_t_minus_{off}"] = ticker_data[dt]["atm_iv"]
                            if not math.isnan(ticker_data[dt]["atm_iv"]):
                                has_pre = True
                        else:
                            measurements[f"atm_iv_t_minus_{off}"] = float("nan")

                    for off in post_offsets:
                        dt = _trading_day_offset(ticker_dates, est_str, off)
                        if dt and dt in ticker_data:
                            measurements[f"atm_iv_t_plus_{off}"] = ticker_data[dt]["atm_iv"]
                            if not math.isnan(ticker_data[dt]["atm_iv"]):
                                has_post = True
                        else:
                            measurements[f"atm_iv_t_plus_{off}"] = float("nan")

                    # Compute crush ratios
                    pre1 = measurements.get("atm_iv_t_minus_1", float("nan"))
                    for off in post_offsets:
                        post_val = measurements.get(f"atm_iv_t_plus_{off}", float("nan"))
                        if not math.isnan(pre1) and not math.isnan(post_val) and pre1 > 0:
                            measurements[f"crush_ratio_t{off}"] = round(post_val / pre1, 4)
                        else:
                            measurements[f"crush_ratio_t{off}"] = float("nan")

                    if has_pre and has_post:
                        events.append(measurements)

        except (OSError, csv.Error) as exc:
            logger.warning("Skipping %s: %s", csv_path, exc)

    return events


def summarize_by_bucket(
    events: List[Dict[str, Any]],
    post_offsets: List[int],
    min_obs: int,
) -> Dict[str, Dict[str, Any]]:
    """Compute per-bucket crush summary."""
    buckets: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for e in events:
        buckets[e["bucket"]].append(e)

    summary = {}
    for bucket, evts in sorted(buckets.items()):
        bucket_summary: Dict[str, Any] = {"n_events": len(evts)}
        for off in post_offsets:
            key = f"crush_ratio_t{off}"
            vals = [e[key] for e in evts if not math.isnan(e.get(key, float("nan")))]
            if len(vals) >= min_obs:
                bucket_summary[f"crush_t{off}_median"] = round(statistics.median(vals), 4)
                bucket_summary[f"crush_t{off}_mean"] = round(sum(vals) / len(vals), 4)
                bucket_summary[f"crush_t{off}_p25"] = round(sorted(vals)[len(vals) // 4], 4)
                bucket_summary[f"crush_t{off}_n"] = len(vals)
            else:
                bucket_summary[f"crush_t{off}_median"] = None
                bucket_summary[f"crush_t{off}_n"] = len(vals)
        summary[bucket] = bucket_summary

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="IV crush calibration (Spec 021)")
    parser.add_argument("--iv-features", type=Path, required=True)
    parser.add_argument("--snapshots-dir", type=Path, required=True)
    parser.add_argument("--price-csv", type=Path, required=True)
    parser.add_argument("--event-subset", default="hard", choices=["hard", "all"])
    parser.add_argument("--hard-filter-mode", default="retro", choices=["retro", "snapshot_native"])
    parser.add_argument("--event-window", type=int, default=60)
    parser.add_argument("--pre-offsets", default="3,1")
    parser.add_argument("--post-offsets", default="1,3,5")
    parser.add_argument("--min-obs", type=int, default=5)
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "output" / "iv_crush_calibration")
    args = parser.parse_args()

    if not args.iv_features.exists():
        logger.error("Missing %s", args.iv_features)
        return 1

    pre_offsets = [int(x) for x in args.pre_offsets.split(",")]
    post_offsets = [int(x) for x in args.post_offsets.split(",")]

    logger.info("Loading IV features ...")
    iv_index = load_iv_features(args.iv_features)

    logger.info("Finding resolved events ...")
    events = find_resolved_events(
        args.snapshots_dir,
        iv_index,
        args.event_subset,
        args.hard_filter_mode,
        args.event_window,
        pre_offsets,
        post_offsets,
    )
    logger.info("Found %d events with pre+post IV data", len(events))

    if not events:
        logger.warning("No events with crush data")
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "summary.json").write_text(json.dumps({"schema": STUDY_SCHEMA, "n_events": 0}))
        return 0

    bucket_summary = summarize_by_bucket(events, post_offsets, args.min_obs)

    # Write outputs
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # Event CSV
    ev_path = args.output_dir / "iv_crush_events.csv"
    fields = list(events[0].keys())
    with open(ev_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(events)
    logger.info("Events → %s", ev_path)

    # Summary JSON
    summary = {
        "schema": STUDY_SCHEMA,
        "event_subset": args.event_subset,
        "hard_filter_mode": args.hard_filter_mode,
        "n_events": len(events),
        "n_tickers": len(set(e["ticker"] for e in events)),
        "buckets": bucket_summary,
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")

    # Summary MD
    md = [
        "# IV Crush Calibration",
        "",
        f"**Events**: {len(events)}",
        f"**Tickers**: {len(set(e['ticker'] for e in events))}",
        f"**Event subset**: {args.event_subset} ({args.hard_filter_mode})",
        "",
        "## Crush Ratios by Bucket",
        "",
    ]
    for bucket, bs in sorted(bucket_summary.items()):
        md.append(f"### {bucket} (n={bs['n_events']})")
        md.append("")
        md.append("| Horizon | Median Crush | N |")
        md.append("|---------|-------------|---|")
        for off in post_offsets:
            med = bs.get(f"crush_t{off}_median")
            n = bs.get(f"crush_t{off}_n", 0)
            md.append(f"| T+{off} | {med if med else '—'} | {n} |")
        md.append("")

    # Print top events for context
    md.append("## Sample Events")
    md.append("")
    md.append("| Ticker | Event Date | Type | Bucket | IV T-1 | IV T+1 | Crush T+1 |")
    md.append("|--------|-----------|------|--------|--------|--------|-----------|")
    for e in sorted(events, key=lambda x: x.get("crush_ratio_t1", 99))[:15]:
        md.append(
            f"| {e['ticker']} | {e['estimated_event_date']} | {e['catalyst_event_type']} "
            f"| {e['bucket']} | {e.get('atm_iv_t_minus_1', '—'):.3f} "
            f"| {e.get('atm_iv_t_plus_1', '—'):.3f} "
            f"| {e.get('crush_ratio_t1', '—')} |"
        )
    md.append("")

    (args.output_dir / "summary.md").write_text("\n".join(md))
    logger.info("Summary → %s", args.output_dir / "summary.md")

    # Print key results
    for bucket, bs in bucket_summary.items():
        med = bs.get("crush_t1_median")
        if med:
            logger.info("  %s crush T+1 median: %.4f (n=%d)", bucket, med, bs.get("crush_t1_n", 0))

    return 0


if __name__ == "__main__":
    sys.exit(main())
