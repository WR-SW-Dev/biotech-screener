#!/usr/bin/env python3
"""IV build curve analysis for hard catalysts (Spec 021, Phase 1).

Measures how IV evolves as hard catalysts approach, using the existing
historical IV feature panel joined to dated snapshot catalyst dates.

Outputs normalized T-minus-event curves by broad event bucket, plus
deviation-from-baseline for individual names.

Usage:
    python scripts/research/eval_iv_build_curves.py \
        --iv-features data/research/historical_iv_features.csv \
        --snapshots-dir data/snapshots \
        --event-subset hard \
        --feature atm_iv \
        --window-days 60 \
        --output-dir output/eval_iv_build_curves
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
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from common.hard_catalyst import classify_hard_catalyst  # noqa: E402

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

STUDY_SCHEMA = "iv_build_curves.v1"

# Broad event buckets
BUCKET_MAP = {
    "FDA_PDUFA_DATE": "REGULATORY",
    "FDA_ADCOM": "REGULATORY",
    "FDA_CRL": "REGULATORY",
    "FDA_APPROVAL": "REGULATORY",
    "DATA_READOUT": "CLINICAL",
    "CT_PRIMARY_COMPLETION": "CLINICAL",
    "CT_STUDY_COMPLETION": "CLINICAL",
}


def _sf(v: Any, default: float = float("nan")) -> float:
    if v is None or v == "":
        return default
    try:
        f = float(v)
        return f if not math.isnan(f) else default
    except (ValueError, TypeError):
        return default


def _bucket_for_event_type(et: str, family: str) -> str:
    if et in BUCKET_MAP:
        return BUCKET_MAP[et]
    if family == "REGULATORY":
        return "REGULATORY"
    if family == "CLINICAL":
        return "CLINICAL"
    return "OTHER_HARD"


def load_iv_features(path: Path) -> Dict[str, Dict[str, Dict[str, float]]]:
    """Load historical_iv_features.csv → {ticker: {date: {field: val}}}."""
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
                "rr_25d": _sf(row.get("rr_25d")),
                "atm_straddle_price": _sf(row.get("atm_straddle_price")),
            }
    return dict(index)


def load_snapshot_catalyst_rows(
    snapshots_dir: Path,
    event_subset: str,
    hard_filter_mode: str,
    max_catalyst_days: int,
) -> List[Dict[str, Any]]:
    """Load catalyst rows from snapshots with hard filtering."""
    date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    rows = []

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
                    if math.isnan(cat_days) or cat_days <= 0 or cat_days > max_catalyst_days:
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

                    rows.append(
                        {
                            "date": d.name,
                            "ticker": ticker,
                            "catalyst_days": int(cat_days),
                            "catalyst_event_type": et,
                            "catalyst_source": src,
                            "catalyst_family": family,
                        }
                    )
        except (OSError, csv.Error) as exc:
            logger.warning("Skipping %s: %s", csv_path, exc)

    return rows


def build_curve_panel(
    catalyst_rows: List[Dict[str, Any]],
    iv_index: Dict[str, Dict[str, Dict[str, float]]],
    feature: str,
) -> List[Dict[str, Any]]:
    """Build panel: one row per (date, ticker) with days_to_event and feature value."""
    panel = []
    for cr in catalyst_rows:
        ticker = cr["ticker"]
        dt = cr["date"]
        days_to = cr["catalyst_days"]
        bucket = _bucket_for_event_type(cr["catalyst_event_type"], cr["catalyst_family"])

        ticker_data = iv_index.get(ticker, {})
        feat_row = ticker_data.get(dt, {})
        val = feat_row.get(feature, float("nan"))

        panel.append(
            {
                "date": dt,
                "ticker": ticker,
                "days_to_event": days_to,
                "bucket": bucket,
                "catalyst_event_type": cr["catalyst_event_type"],
                "catalyst_family": cr["catalyst_family"],
                feature: val,
            }
        )

    return panel


def compute_baselines(
    panel: List[Dict[str, Any]],
    feature: str,
    min_obs: int,
) -> Dict[str, Dict[int, Dict[str, Any]]]:
    """Compute per-bucket, per-days_to_event baseline statistics.

    Returns {bucket: {days_to_event: {median, p25, p75, count}}}.
    """
    # Group by (bucket, days_to_event)
    groups: Dict[str, Dict[int, List[float]]] = defaultdict(lambda: defaultdict(list))
    for row in panel:
        val = _sf(row.get(feature))
        if math.isnan(val):
            continue
        groups[row["bucket"]][row["days_to_event"]].append(val)

    baselines: Dict[str, Dict[int, Dict[str, Any]]] = {}
    for bucket, days_map in groups.items():
        baselines[bucket] = {}
        for dte, vals in sorted(days_map.items()):
            if len(vals) < min_obs:
                baselines[bucket][dte] = {"median": None, "p25": None, "p75": None, "count": len(vals)}
                continue
            vals_sorted = sorted(vals)
            n = len(vals_sorted)
            baselines[bucket][dte] = {
                "median": round(statistics.median(vals_sorted), 6),
                "p25": round(vals_sorted[n // 4], 6),
                "p75": round(vals_sorted[(3 * n) // 4], 6),
                "count": n,
            }

    return baselines


def enrich_panel_with_deviation(
    panel: List[Dict[str, Any]],
    baselines: Dict[str, Dict[int, Dict[str, Any]]],
    feature: str,
) -> None:
    """Add deviation-from-baseline to each panel row (in-place)."""
    dev_col = f"{feature}_dev_from_baseline"
    for row in panel:
        val = _sf(row.get(feature))
        bucket = row["bucket"]
        dte = row["days_to_event"]

        baseline = (baselines.get(bucket) or {}).get(dte, {})
        med = baseline.get("median")

        if math.isnan(val) or med is None:
            row[dev_col] = ""
        else:
            row[dev_col] = round(val - med, 6)


def main() -> int:
    parser = argparse.ArgumentParser(description="IV build curve analysis (Spec 021)")
    parser.add_argument("--iv-features", type=Path, required=True)
    parser.add_argument("--snapshots-dir", type=Path, required=True)
    parser.add_argument("--event-subset", default="hard", choices=["hard", "all"])
    parser.add_argument("--hard-filter-mode", default="retro", choices=["retro", "snapshot_native"])
    parser.add_argument("--feature", default="atm_iv", choices=["atm_iv", "actual_implied_move", "rr_25d"])
    parser.add_argument("--window-days", type=int, default=60)
    parser.add_argument("--bucket-mode", default="family", choices=["family"])
    parser.add_argument("--min-obs", type=int, default=10)
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "output" / "eval_iv_build_curves")
    args = parser.parse_args()

    if not args.iv_features.exists():
        logger.error(
            "Missing %s — run build_historical_iv_surface.py then build_historical_iv_features.py first",
            args.iv_features,
        )
        return 1

    logger.info("Loading IV features from %s ...", args.iv_features)
    iv_index = load_iv_features(args.iv_features)
    logger.info("Loaded %d tickers", len(iv_index))

    logger.info("Loading snapshot catalyst rows ...")
    catalyst_rows = load_snapshot_catalyst_rows(
        args.snapshots_dir,
        args.event_subset,
        args.hard_filter_mode,
        args.window_days,
    )
    logger.info("Loaded %d catalyst rows", len(catalyst_rows))

    if not catalyst_rows:
        logger.warning("No qualifying catalyst rows found")
        return 1

    logger.info("Building curve panel for feature=%s ...", args.feature)
    panel = build_curve_panel(catalyst_rows, iv_index, args.feature)

    n_with_feature = sum(1 for r in panel if not math.isnan(_sf(r.get(args.feature))))
    logger.info(
        "Panel: %d rows, %d with %s (%.1f%%)",
        len(panel),
        n_with_feature,
        args.feature,
        100 * n_with_feature / len(panel) if panel else 0,
    )

    logger.info("Computing baselines ...")
    baselines = compute_baselines(panel, args.feature, args.min_obs)

    enrich_panel_with_deviation(panel, baselines, args.feature)

    # Write outputs
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # Panel CSV
    panel_path = args.output_dir / "iv_build_curve_panel.csv"
    if panel:
        fields = list(panel[0].keys())
        with open(panel_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(panel)
        logger.info("Panel → %s", panel_path)

    # Baselines CSV
    baseline_rows = []
    for bucket, days_map in sorted(baselines.items()):
        for dte, stats in sorted(days_map.items()):
            baseline_rows.append({"bucket": bucket, "days_to_event": dte, **stats})
    if baseline_rows:
        bl_path = args.output_dir / "iv_build_curve_baselines.csv"
        with open(bl_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(baseline_rows[0].keys()))
            w.writeheader()
            w.writerows(baseline_rows)
        logger.info("Baselines → %s", bl_path)

    # Summary JSON
    buckets_summary = {}
    for bucket, days_map in baselines.items():
        valid_days = {d: s for d, s in days_map.items() if s.get("median") is not None}
        buckets_summary[bucket] = {
            "n_days_with_baseline": len(valid_days),
            "n_total_days": len(days_map),
            "days_range": [min(days_map.keys()), max(days_map.keys())] if days_map else [],
        }

    summary = {
        "schema": STUDY_SCHEMA,
        "feature": args.feature,
        "event_subset": args.event_subset,
        "hard_filter_mode": args.hard_filter_mode,
        "window_days": args.window_days,
        "min_obs": args.min_obs,
        "n_panel_rows": len(panel),
        "n_with_feature": n_with_feature,
        "n_unique_tickers": len(set(r["ticker"] for r in panel)),
        "n_unique_dates": len(set(r["date"] for r in panel)),
        "buckets": buckets_summary,
    }

    json_path = args.output_dir / "summary.json"
    json_path.write_text(json.dumps(summary, indent=2, default=str) + "\n")

    # Summary MD
    md = [
        "# IV Build Curve Analysis",
        "",
        f"**Feature**: {args.feature}",
        f"**Event subset**: {args.event_subset} ({args.hard_filter_mode})",
        f"**Window**: {args.window_days} days",
        f"**Panel**: {len(panel)} rows, {n_with_feature} with feature ({100 * n_with_feature / len(panel):.1f}%)",
        f"**Tickers**: {len(set(r['ticker'] for r in panel))}",
        "",
        "## Baseline Curves by Bucket",
        "",
    ]

    for bucket in sorted(baselines):
        days_map = baselines[bucket]
        valid = {d: s for d, s in days_map.items() if s.get("median") is not None}
        md.append(f"### {bucket} ({len(valid)} valid day-points)")
        md.append("")
        if valid:
            md.append("| Days to Event | Median | P25 | P75 | N |")
            md.append("|---------------|--------|-----|-----|---|")
            for dte in sorted(valid):
                s = valid[dte]
                md.append(f"| {dte} | {s['median']:.4f} | {s['p25']:.4f} | {s['p75']:.4f} | {s['count']} |")
        else:
            md.append("Insufficient data for baseline.")
        md.append("")

    md_path = args.output_dir / "summary.md"
    md_path.write_text("\n".join(md))
    logger.info("Summary → %s", md_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
