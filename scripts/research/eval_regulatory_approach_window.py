#!/usr/bin/env python3
"""Regulatory approach-window event study.

Instead of asking 'are there enough names in 91-180d today?', asks:
'across all resolved regulatory events, did options quality in the
approach window predict event outcomes?'

Uses the historical IV feature panel + snapshot catalyst dates to build
an event-anchored dataset where each row is one resolved regulatory event
with pre-event options features measured at T-210 to T-31.

Usage:
    python scripts/research/eval_regulatory_approach_window.py \
        --iv-features data/research/historical_iv_features.csv \
        --snapshots-dir data/snapshots \
        --price-csv production_data/price_history.csv \
        --output-dir output/regulatory_approach_window
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
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
_SCRIPTS = PROJECT_ROOT / "scripts"
sys.path.insert(0, str(_SCRIPTS))
_RESEARCH = _SCRIPTS / "research"
sys.path.insert(0, str(_RESEARCH))

from backtest_signal_robustness import spearman_rank_corr  # noqa: E402
from options_prospective_analysis import load_price_series, resolve_event_outcome  # noqa: E402

from common.hard_catalyst import classify_hard_catalyst  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

STUDY_SCHEMA = "regulatory_approach_window.v1"

# Approach windows (days before event)
WINDOWS = [
    ("T-210_to_T-91", 210, 91),
    ("T-90_to_T-31", 90, 31),
    ("T-30_to_T-1", 30, 1),
]

# Regulatory event types
REGULATORY_EVENT_TYPES = {
    "FDA_PDUFA_DATE",
    "FDA_ADCOM",
    "FDA_CRL",
    "FDA_APPROVAL",
    "FDA_DECISION",
    "REGULATORY_DECISION",
}


def _sf(v, default=float("nan")):
    if v is None or v == "":
        return default
    try:
        f = float(v)
        return f if not math.isnan(f) else default
    except (ValueError, TypeError):
        return default


def load_iv_features(path: Path) -> Dict[str, Dict[str, Dict[str, float]]]:
    """Load → {ticker: {date: {atm_iv, rr_25d, actual_implied_move, total_volume}}}."""
    index: Dict[str, Dict[str, Dict[str, float]]] = defaultdict(dict)
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            ticker = (row.get("ticker") or "").strip().upper()
            dt = (row.get("date") or "").strip()
            if not ticker or not dt:
                continue
            index[ticker][dt] = {
                "atm_iv": _sf(row.get("atm_iv")),
                "rr_25d": _sf(row.get("rr_25d")),
                "actual_implied_move": _sf(row.get("actual_implied_move")),
                "total_volume": _sf(row.get("total_volume")),
                "put_call_volume_ratio": _sf(row.get("put_call_volume_ratio")),
            }
    return dict(index)


def find_resolved_regulatory_events(
    snapshots_dir: Path,
    prices: Dict[str, Dict[str, float]],
) -> List[Dict[str, Any]]:
    """Find regulatory events from snapshots that have resolved outcomes."""
    date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    events = []
    seen: set = set()

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
                    family = row.get("catalyst_family", "")

                    # Only regulatory events
                    if family != "REGULATORY" and et not in REGULATORY_EVENT_TYPES:
                        continue

                    hc = classify_hard_catalyst(et, src)
                    cat_days = _sf(row.get("catalyst_days"))
                    if math.isnan(cat_days) or cat_days <= 0 or cat_days > 210:
                        continue

                    # Estimate event date
                    snap_date = date.fromisoformat(d.name)
                    est_event = snap_date + timedelta(days=int(cat_days))
                    est_str = est_event.isoformat()

                    # Dedup by (ticker, estimated_event_date)
                    key = (ticker, est_str)
                    if key in seen:
                        continue

                    # Check if event has resolved (outcome available)
                    ticker_prices = prices.get(ticker, {})
                    sorted_dates = sorted(ticker_prices.keys()) if ticker_prices else []
                    outcome = resolve_event_outcome(
                        ticker_prices,
                        sorted_dates,
                        d.name,
                        int(cat_days),
                    )
                    signed_gap = _sf(outcome.get("signed_gap"))
                    abs_gap = _sf(outcome.get("abs_gap"))

                    if math.isnan(signed_gap):
                        continue  # Event hasn't resolved yet

                    seen.add(key)
                    events.append(
                        {
                            "ticker": ticker,
                            "snap_date": d.name,
                            "estimated_event_date": est_str,
                            "catalyst_days_at_snap": int(cat_days),
                            "catalyst_event_type": et,
                            "catalyst_source": src,
                            "is_hard_catalyst": hc["is_hard_catalyst"],
                            "signed_gap": signed_gap,
                            "abs_gap": abs_gap,
                            "oqc": _sf(row.get("options_quality_composite")),
                        }
                    )
        except (OSError, csv.Error) as exc:
            logger.warning("Skipping %s: %s", csv_path, exc)

    return events


def compute_approach_features(
    events: List[Dict[str, Any]],
    iv_index: Dict[str, Dict[str, Dict[str, float]]],
) -> None:
    """Add pre-event options features for each approach window (in-place)."""
    for ev in events:
        ticker = ev["ticker"]
        est_event = date.fromisoformat(ev["estimated_event_date"])
        ticker_data = iv_index.get(ticker, {})
        ticker_dates = sorted(ticker_data.keys())

        for window_name, far, near in WINDOWS:
            start = est_event - timedelta(days=far)
            end = est_event - timedelta(days=near)

            # Collect feature values in this window
            window_ivs = []
            window_moves = []
            window_vols = []
            window_rrs = []

            for dt in ticker_dates:
                d = date.fromisoformat(dt)
                if start <= d <= end:
                    feat = ticker_data[dt]
                    iv = feat.get("atm_iv", float("nan"))
                    if not math.isnan(iv):
                        window_ivs.append(iv)
                    move = feat.get("actual_implied_move", float("nan"))
                    if not math.isnan(move):
                        window_moves.append(move)
                    vol = feat.get("total_volume", float("nan"))
                    if not math.isnan(vol):
                        window_vols.append(vol)
                    rr = feat.get("rr_25d", float("nan"))
                    if not math.isnan(rr):
                        window_rrs.append(rr)

            prefix = window_name
            ev[f"{prefix}_n_iv_obs"] = len(window_ivs)
            ev[f"{prefix}_mean_iv"] = round(statistics.mean(window_ivs), 6) if window_ivs else float("nan")
            ev[f"{prefix}_mean_move"] = round(statistics.mean(window_moves), 6) if window_moves else float("nan")
            ev[f"{prefix}_mean_vol"] = round(statistics.mean(window_vols), 1) if window_vols else float("nan")
            ev[f"{prefix}_mean_rr"] = round(statistics.mean(window_rrs), 6) if window_rrs else float("nan")

            # IV trend within window (last - first)
            if len(window_ivs) >= 5:
                ev[f"{prefix}_iv_trend"] = round(window_ivs[-1] - window_ivs[0], 6)
            else:
                ev[f"{prefix}_iv_trend"] = float("nan")


def run_ic_tests(
    events: List[Dict[str, Any]],
    min_obs: int,
) -> Dict[str, Any]:
    """Run IC tests for approach-window features vs outcomes."""
    results = {}
    targets = ["signed_gap", "abs_gap"]

    for window_name, _, _ in WINDOWS:
        features = [
            f"{window_name}_mean_iv",
            f"{window_name}_mean_move",
            f"{window_name}_mean_vol",
            f"{window_name}_mean_rr",
            f"{window_name}_iv_trend",
        ]
        for feat in features:
            for tgt in targets:
                pairs = [(_sf(e.get(feat)), _sf(e.get(tgt))) for e in events]
                pairs = [(s, t) for s, t in pairs if not math.isnan(s) and not math.isnan(t)]
                key = f"ic_{feat}_vs_{tgt}"
                if len(pairs) < min_obs:
                    results[key] = {"status": "insufficient", "n": len(pairs)}
                    continue
                sx, tx = zip(*pairs)
                ic = spearman_rank_corr(list(sx), list(tx))
                results[key] = {"status": "ok", "n": len(pairs), "ic": round(ic, 6)}

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Regulatory approach-window event study")
    parser.add_argument("--iv-features", type=Path, required=True)
    parser.add_argument("--snapshots-dir", type=Path, required=True)
    parser.add_argument("--price-csv", type=Path, required=True)
    parser.add_argument("--min-obs", type=int, default=10)
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "output" / "regulatory_approach_window")
    args = parser.parse_args()

    logger.info("Loading IV features ...")
    iv_index = load_iv_features(args.iv_features)

    logger.info("Loading prices ...")
    prices = load_price_series(args.price_csv)

    logger.info("Finding resolved regulatory events ...")
    events = find_resolved_regulatory_events(args.snapshots_dir, prices)
    logger.info("Found %d resolved regulatory events", len(events))

    if not events:
        logger.warning("No resolved regulatory events")
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "report.json").write_text(json.dumps({"schema": STUDY_SCHEMA, "n_events": 0}))
        return 0

    logger.info("Computing approach-window features ...")
    compute_approach_features(events, iv_index)

    logger.info("Running IC tests ...")
    ic_results = run_ic_tests(events, args.min_obs)

    # Write outputs
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # Event CSV
    if events:
        fields = list(events[0].keys())
        with open(args.output_dir / "events.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(events)

    # Report
    n_hard = sum(1 for e in events if e.get("is_hard_catalyst"))
    tickers = sorted(set(e["ticker"] for e in events))

    report = {
        "schema": STUDY_SCHEMA,
        "n_events": len(events),
        "n_hard": n_hard,
        "n_tickers": len(tickers),
        "tickers": tickers,
        "ic_results": ic_results,
    }
    (args.output_dir / "report.json").write_text(json.dumps(report, indent=2, default=str) + "\n")

    # Markdown
    md = [
        "# Regulatory Approach-Window Event Study",
        "",
        f"**Events**: {len(events)} ({n_hard} hard)",
        f"**Tickers**: {len(tickers)}",
        "",
        "## IC Results",
        "",
        "| Feature | Target | IC | N |",
        "|---------|--------|----|---|",
    ]
    for key in sorted(ic_results):
        v = ic_results[key]
        ic_str = f"{v['ic']:.4f}" if v.get("status") == "ok" else "—"
        md.append(f"| {key} | | {ic_str} | {v.get('n', 0)} |")

    md += ["", "## Event Summary", ""]
    for ev in sorted(events, key=lambda e: e["estimated_event_date"])[:20]:
        md.append(
            f"- {ev['ticker']} {ev['estimated_event_date']} ({ev['catalyst_event_type']}): gap={ev['signed_gap']:.3f}"
        )

    md.append("")
    (args.output_dir / "report.md").write_text("\n".join(md))

    logger.info("Report → %s", args.output_dir)

    # Print key results
    for key, v in sorted(ic_results.items()):
        if v.get("status") == "ok" and abs(v["ic"]) >= 0.05:
            logger.info("  %s: IC=%.4f (n=%d)", key, v["ic"], v["n"])

    return 0


if __name__ == "__main__":
    sys.exit(main())
