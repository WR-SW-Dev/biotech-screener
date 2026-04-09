#!/usr/bin/env python3
"""Herald confidence calibration -- are confidence scores well-calibrated?

Bins classified records by confidence bucket and computes actual accuracy
per bin using available ground-truth proxies (CRT, price-reaction, human).

Reuses common.stats.calibration for ECE, Brier, reliability curves.

Usage:
    python scripts/research/herald_confidence_calibration.py --as-of-date 2026-04-05
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

CLASSIFIED_DIR = PROJECT_ROOT / "data" / "press_releases" / "classified"
RESOLUTIONS_DIR = PROJECT_ROOT / "data" / "snapshots" / "resolutions"
PRICE_CSV = PROJECT_ROOT / "production_data" / "price_history.csv"
GROUND_TRUTH_DIR = PROJECT_ROOT / "artifacts" / "herald_ground_truth"
OUTPUT_DIR = PROJECT_ROOT / "artifacts" / "herald_precision"

SCHEMA = "herald_calibration.v1"

# Fixed bins matching the local classifier's discrete output values
CONF_BINS = [(0.0, 0.3), (0.3, 0.5), (0.5, 0.7), (0.7, 0.9), (0.9, 1.01)]

logger = logging.getLogger(__name__)


def _load_classified(classified_dir: Path, max_days: int = 30) -> list[dict]:
    records = []
    for f in sorted(classified_dir.glob("classified_*.jsonl"), reverse=True)[:max_days]:
        for line in f.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return records


def _load_resolutions(resolutions_dir: Path) -> list[dict]:
    resolutions = []
    if not resolutions_dir.exists():
        return resolutions
    for month_dir in resolutions_dir.iterdir():
        if not month_dir.is_dir():
            continue
        for f in month_dir.glob("*.json"):
            try:
                resolutions.append(json.loads(f.read_text()))
            except Exception:
                pass
    return resolutions


def _load_prices(price_csv: Path, tickers: set[str]) -> dict[str, dict[str, float]]:
    cutoff = (date.today() - timedelta(days=180)).isoformat()
    prices: dict[str, dict[str, float]] = defaultdict(dict)
    if not price_csv.exists():
        return dict(prices)
    with open(price_csv) as f:
        for row in csv.DictReader(f):
            tk = row.get("ticker", "").strip()
            dt = row.get("date", "").strip()
            cl = row.get("close", "")
            if tk in tickers and dt >= cutoff and cl:
                try:
                    prices[tk][dt] = float(cl)
                except ValueError:
                    pass
    return dict(prices)


def _load_ground_truth(gt_dir: Path) -> list[dict]:
    files = sorted(gt_dir.glob("sample_*.jsonl"), reverse=True)
    if not files:
        return []
    records = []
    for line in files[0].read_text().splitlines():
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return records


def _get_1d_return(prices: dict[str, dict[str, float]], ticker: str, dt_str: str) -> float | None:
    tk_prices = prices.get(ticker, {})
    if not tk_prices:
        return None
    sorted_dates = sorted(tk_prices.keys())
    idx = None
    for i, d in enumerate(sorted_dates):
        if d >= dt_str:
            idx = i
            break
    if idx is None or idx == 0:
        return None
    p0 = tk_prices.get(sorted_dates[idx - 1])
    p1 = tk_prices.get(sorted_dates[idx])
    if p0 and p1 and p0 > 0:
        return (p1 / p0) - 1
    return None


def build_calibration_dataset(
    classified: list[dict],
    resolutions: list[dict],
    prices: dict[str, dict[str, float]],
    ground_truth: list[dict],
) -> list[dict[str, Any]]:
    """Build paired (confidence, correct) dataset from all available sources.

    Three correctness proxies:
    1. CRT: outcome_guess matches CRT outcome
    2. Price-direction: direction_guess matches 1d return sign
    3. Human: event_category matches gt_event_category
    """
    pairs: list[dict[str, Any]] = []

    # Build CRT index
    res_index: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for r in resolutions:
        tk = r.get("ticker", "")
        cd = r.get("catalyst_date", "")
        if tk and cd:
            res_index[tk].append((cd, r))

    # Build ground truth index
    gt_index: dict[str, dict] = {}
    for r in ground_truth:
        eid = r.get("event_id", "")
        if eid and r.get("gt_event_category"):
            gt_index[eid] = r

    for rec in classified:
        conf = rec.get("confidence")
        if conf is None:
            continue
        try:
            conf = float(conf)
        except (ValueError, TypeError):
            continue

        tk = rec.get("ticker", "")
        pub = rec.get("published_at_utc", "")[:10]

        # Method 1: CRT match
        if tk in res_index and pub:
            try:
                pub_d = datetime.strptime(pub, "%Y-%m-%d").date()
            except ValueError:
                pub_d = None
            if pub_d:
                for cat_date_str, res in res_index[tk]:
                    try:
                        cat_d = datetime.strptime(cat_date_str, "%Y-%m-%d").date()
                    except ValueError:
                        continue
                    if abs((pub_d - cat_d).days) <= 3:
                        correct = rec.get("event_outcome_guess", "").lower() == (res.get("outcome", "") or "").lower()
                        pairs.append({"confidence": conf, "correct": correct, "method": "crt"})
                        break

        # Method 2: Price direction
        if tk and pub and rec.get("price_direction_guess") in ("up", "down"):
            ret = _get_1d_return(prices, tk, pub)
            if ret is not None:
                predicted_up = rec["price_direction_guess"] == "up"
                actual_up = ret > 0
                correct = predicted_up == actual_up
                pairs.append({"confidence": conf, "correct": correct, "method": "price_direction"})

        # Method 3: Human ground truth
        eid = rec.get("event_id", "")
        if eid in gt_index:
            gt = gt_index[eid]
            correct = rec.get("event_category") == gt.get("gt_event_category")
            pairs.append({"confidence": conf, "correct": correct, "method": "human"})

    return pairs


def compute_calibration_curve(
    pairs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute calibration curve, ECE, and Brier score."""
    bins_data = []
    total_brier = 0.0
    total_ece = 0.0
    n_total = len(pairs)

    for lo, hi in CONF_BINS:
        in_bin = [p for p in pairs if lo <= p["confidence"] < hi]
        if not in_bin:
            bins_data.append(
                {
                    "bin": f"{lo:.1f}-{hi:.1f}",
                    "n": 0,
                    "avg_confidence": 0,
                    "accuracy": 0,
                    "gap": 0,
                }
            )
            continue

        n = len(in_bin)
        avg_conf = sum(p["confidence"] for p in in_bin) / n
        accuracy = sum(1 for p in in_bin if p["correct"]) / n
        gap = abs(accuracy - avg_conf)

        bins_data.append(
            {
                "bin": f"{lo:.1f}-{hi:.1f}",
                "n": n,
                "avg_confidence": round(avg_conf, 3),
                "accuracy": round(accuracy, 3),
                "gap": round(gap, 3),
            }
        )

        total_ece += gap * (n / max(n_total, 1))

    # Brier score
    for p in pairs:
        c = p["confidence"]
        y = 1.0 if p["correct"] else 0.0
        total_brier += (c - y) ** 2
    brier = total_brier / max(n_total, 1)

    # By method breakdown
    by_method: dict[str, dict] = {}
    for method in ("crt", "price_direction", "human"):
        method_pairs = [p for p in pairs if p["method"] == method]
        if method_pairs:
            n = len(method_pairs)
            acc = sum(1 for p in method_pairs if p["correct"]) / n
            by_method[method] = {"n": n, "accuracy": round(acc, 3)}

    return {
        "n_obs": n_total,
        "bins": bins_data,
        "ece": round(total_ece, 4),
        "brier_score": round(brier, 4),
        "by_method": by_method,
    }


def main():
    parser = argparse.ArgumentParser(description="Herald confidence calibration")
    parser.add_argument("--classified-dir", type=Path, default=CLASSIFIED_DIR)
    parser.add_argument("--resolutions-dir", type=Path, default=RESOLUTIONS_DIR)
    parser.add_argument("--price-csv", type=Path, default=PRICE_CSV)
    parser.add_argument("--ground-truth-dir", type=Path, default=GROUND_TRUTH_DIR)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--as-of-date", default=date.today().isoformat())
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    classified = _load_classified(args.classified_dir)
    resolutions = _load_resolutions(args.resolutions_dir)
    tickers = {r.get("ticker", "") for r in classified}
    prices = _load_prices(args.price_csv, tickers)
    ground_truth = _load_ground_truth(args.ground_truth_dir)

    logger.info(
        "Loaded %d classified, %d resolutions, %d ground truth",
        len(classified),
        len(resolutions),
        len(ground_truth),
    )

    pairs = build_calibration_dataset(classified, resolutions, prices, ground_truth)
    logger.info("Built %d calibration pairs", len(pairs))

    cal = compute_calibration_curve(pairs)

    report = {
        "schema": SCHEMA,
        "as_of_date": args.as_of_date,
        **cal,
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.output_dir / f"calibration_{args.as_of_date}.json"
    out_path.write_text(json.dumps(report, indent=2))

    print(f"\nHERALD CONFIDENCE CALIBRATION -- {args.as_of_date}")
    print(f"  Observations: {cal['n_obs']}")
    print(f"  ECE: {cal['ece']:.3f}")
    print(f"  Brier: {cal['brier_score']:.3f}")
    for b in cal["bins"]:
        if b["n"] > 0:
            print(
                f"  {b['bin']}: n={b['n']}, conf={b['avg_confidence']:.2f}, acc={b['accuracy']:.2f}, gap={b['gap']:.2f}"
            )
    for method, info in cal.get("by_method", {}).items():
        print(f"  {method}: n={info['n']}, accuracy={info['accuracy']:.2f}")
    print(f"\n  Saved: {out_path}")


if __name__ == "__main__":
    main()
