#!/usr/bin/env python3
"""Backfill AACT execution_score history from all available snapshots.

Computes trial deltas between consecutive AACT snapshot pairs and
produces a time series of per-ticker execution_scores for backtesting.

Usage:
    python3 scripts/backfill_aact_deltas.py
    python3 scripts/backfill_aact_deltas.py --inject-rankings
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.build_aact_trial_deltas import build_deltas

AACT_DIR = REPO_ROOT / "data" / "aact" / "snapshots"
OUTPUT_DIR = REPO_ROOT / "artifacts" / "aact_deltas"
SNAPSHOTS_DIR = REPO_ROOT / "data" / "snapshots"


def get_aact_dates() -> list[str]:
    """Get sorted list of AACT snapshot dates with trial_master.json."""
    if not AACT_DIR.exists():
        return []
    return sorted(d.name for d in AACT_DIR.iterdir() if d.is_dir() and (d / "trial_master.json").exists())


def backfill_all() -> dict:
    """Compute deltas for all consecutive AACT snapshot pairs."""
    dates = get_aact_dates()
    print(f"AACT snapshots available: {len(dates)}")
    if len(dates) < 2:
        print("Need at least 2 snapshots for deltas")
        return {"n_pairs": 0, "pairs": []}

    for d in dates:
        print(f"  {d}")

    pairs = []
    for i in range(1, len(dates)):
        prior = dates[i - 1]
        current = dates[i]
        print(f"\nComputing deltas: {current} vs {prior}...")

        result = build_deltas(current, prior)
        if "error" in result:
            print(f"  SKIP: {result['error']}")
            continue

        # Save individual delta file
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        out_path = OUTPUT_DIR / f"aact_deltas_{current}.json"
        out_path.write_text(json.dumps(result, indent=2, default=str))

        n_active = result.get("n_with_activity", 0)
        n_results = result.get("n_results_posted_total", 0)
        n_pcd = result.get("n_pcd_shifts_total", 0)
        print(
            f"  OK: {result['n_tickers']} tickers, {n_active} with activity, "
            f"{n_results} results posted, {n_pcd} PCD shifts"
        )

        pairs.append(
            {
                "current": current,
                "prior": prior,
                "n_tickers": result["n_tickers"],
                "n_with_activity": n_active,
            }
        )

    # Build consolidated time series: ticker → [{date, execution_score}, ...]
    print(f"\n{'='*60}")
    print("Building execution_score time series...")

    ticker_history: dict[str, list[dict]] = {}
    for pair in pairs:
        delta_path = OUTPUT_DIR / f"aact_deltas_{pair['current']}.json"
        delta = json.loads(delta_path.read_text())
        for t in delta.get("tickers", []):
            ticker = t["ticker"]
            ticker_history.setdefault(ticker, []).append(
                {
                    "date": pair["current"],
                    "execution_score": t["execution_score"],
                    "n_results_posted": t["n_results_posted"],
                    "n_pcd_shifts": t["n_pcd_shifts"],
                    "n_status_upgrades": t["n_status_upgrades"],
                    "n_status_downgrades": t["n_status_downgrades"],
                }
            )

    # Save consolidated time series
    ts_path = OUTPUT_DIR / "execution_score_history.json"
    ts_data = {
        "schema": "aact_execution_history.v1",
        "n_pairs": len(pairs),
        "n_tickers": len(ticker_history),
        "date_range": [pairs[0]["current"], pairs[-1]["current"]] if pairs else [],
        "pairs": pairs,
        "ticker_history": ticker_history,
    }
    ts_path.write_text(json.dumps(ts_data, indent=2, default=str))
    print(f"  {len(ticker_history)} tickers with history")
    print(f"  Saved: {ts_path}")

    return ts_data


def inject_into_rankings(ts_data: dict):
    """Inject execution_score into historical rankings.csv files.

    For each AACT delta date, find the nearest ranking snapshot and
    add aact_execution_score column. This enables the ranker harness
    to backtest execution_score as a signal.
    """
    ticker_history = ts_data.get("ticker_history", {})
    if not ticker_history:
        print("No history to inject")
        return

    # Build date → {ticker: score} lookup
    date_scores: dict[str, dict[str, float]] = {}
    for ticker, history in ticker_history.items():
        for entry in history:
            d = entry["date"]
            date_scores.setdefault(d, {})[ticker] = entry["execution_score"]

    aact_dates = sorted(date_scores.keys())
    print(f"\nInjecting execution_score into rankings.csv for {len(aact_dates)} dates...")

    for aact_date in aact_dates:
        scores = date_scores[aact_date]

        # Find nearest ranking snapshot on or before this date
        snap_dates = sorted(
            d.name
            for d in SNAPSHOTS_DIR.iterdir()
            if d.is_dir() and d.name <= aact_date and (d / "rankings.csv").exists() and "__pre_" not in d.name
        )
        if not snap_dates:
            continue
        snap_date = snap_dates[-1]
        rpath = SNAPSHOTS_DIR / snap_date / "rankings.csv"

        # Read, add column, write back
        with open(rpath, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = list(reader.fieldnames or [])
            rows = list(reader)

        if "aact_execution_score" not in fieldnames:
            fieldnames.append("aact_execution_score")

        for row in rows:
            ticker = row.get("ticker", "")
            row["aact_execution_score"] = str(scores.get(ticker, ""))

        with open(rpath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

        n_injected = sum(1 for row in rows if row.get("aact_execution_score", ""))
        print(f"  {snap_date}: {n_injected} tickers with execution_score")


def main():
    parser = argparse.ArgumentParser(description="Backfill AACT execution_score history")
    parser.add_argument(
        "--inject-rankings", action="store_true", help="Also inject scores into historical rankings.csv"
    )
    args = parser.parse_args()

    ts_data = backfill_all()

    if args.inject_rankings and ts_data.get("n_pairs", 0) > 0:
        inject_into_rankings(ts_data)

    print("\nDone. Run the ranker harness to test:")
    print("  python3 scripts/research/ranker_evaluation_harness.py --signal aact_execution_score --top-n 20")


if __name__ == "__main__":
    main()
