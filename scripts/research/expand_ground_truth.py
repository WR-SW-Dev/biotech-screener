#!/usr/bin/env python3
"""Expand ground-truth labels using vol-adjusted price-reaction heuristic.

Reads unlabeled Herald records and auto-labels based on whether the
price reaction was large enough to indicate a material event (vs informational).

Label logic:
  - |return| > vol-adjusted threshold -> gt_event_category = Herald's prediction
  - |return| <= threshold AND informational_only=True -> gt_event_category = "other"
  - |return| <= threshold AND informational_only=False -> low confidence

Usage:
    python3 scripts/research/expand_ground_truth.py
    python3 scripts/research/expand_ground_truth.py --batch data/ground_truth/batch_2026-04-05.jsonl
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

GT_DIR = PROJECT_ROOT / "data" / "ground_truth"
PRICE_CSV = PROJECT_ROOT / "production_data" / "price_history.csv"


def _load_prices() -> dict[str, dict[str, float]]:
    prices: dict[str, dict[str, float]] = {}
    with open(PRICE_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            t = row.get("ticker", "")
            d = row.get("date", "")
            c = row.get("close", "")
            if t and d and c:
                try:
                    prices.setdefault(t, {})[d] = float(c)
                except ValueError:
                    pass
    return prices


def _get_return(prices: dict[str, dict[str, float]], ticker: str, dt: str) -> float | None:
    tk_prices = prices.get(ticker, {})
    sorted_dates = sorted(tk_prices.keys())
    idx = None
    for i, d in enumerate(sorted_dates):
        if d >= dt:
            idx = i
            break
    if idx is None or idx + 1 >= len(sorted_dates):
        return None
    p0 = tk_prices[sorted_dates[idx]]
    p1 = tk_prices[sorted_dates[idx + 1]]
    if p0 <= 0:
        return None
    return (p1 / p0) - 1


def _compute_vol_thresholds(
    prices: dict[str, dict[str, float]],
    multiplier: float = 2.0,
    floor_pct: float = 10.0,
) -> dict[str, float]:
    thresholds: dict[str, float] = {}
    for tk, tk_prices in prices.items():
        sorted_dates = sorted(tk_prices.keys())
        if len(sorted_dates) < 20:
            thresholds[tk] = floor_pct
            continue
        abs_rets = []
        for i in range(1, len(sorted_dates)):
            p0 = tk_prices[sorted_dates[i - 1]]
            p1 = tk_prices[sorted_dates[i]]
            if p0 > 0:
                abs_rets.append(abs((p1 / p0) - 1) * 100)
        if not abs_rets:
            thresholds[tk] = floor_pct
            continue
        abs_rets.sort()
        median = abs_rets[len(abs_rets) // 2]
        thresholds[tk] = max(floor_pct, median * multiplier)
    return thresholds


def expand_labels(batch_path: Path) -> dict:
    records = []
    with open(batch_path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))

    unlabeled = [r for r in records if not r.get("gt_label_source") or r["gt_label_source"] == "unlabeled"]
    if not unlabeled:
        print("No unlabeled records found")
        return {"n_labeled": 0, "n_unlabeled": 0}

    print("Loading prices...")
    prices = _load_prices()
    thresholds = _compute_vol_thresholds(prices)

    labeled_count = 0
    low_confidence = 0
    results = []

    for rec in unlabeled:
        ticker = rec.get("ticker", "")
        dt = rec.get("published_at_utc", "")[:10]
        ret = _get_return(prices, ticker, dt)
        thresh = thresholds.get(ticker, 10.0)

        if ret is None:
            rec["gt_label_source"] = "unlabeled"
            rec["gt_auto_confidence"] = 0.0
            results.append(rec)
            continue

        abs_ret_pct = abs(ret) * 100
        is_informational = rec.get("informational_only", False)
        herald_category = rec.get("event_category", "other")

        if abs_ret_pct > thresh:
            rec["gt_event_category"] = herald_category
            rec["gt_informational_only"] = False
            rec["gt_label_source"] = "price_reaction_auto"
            rec["gt_auto_confidence"] = min(0.9, 0.5 + (abs_ret_pct - thresh) / 20)
            labeled_count += 1
        elif is_informational:
            rec["gt_event_category"] = "other"
            rec["gt_informational_only"] = True
            rec["gt_label_source"] = "price_reaction_auto"
            rec["gt_auto_confidence"] = 0.7
            labeled_count += 1
        else:
            rec["gt_event_category"] = herald_category
            rec["gt_informational_only"] = None
            rec["gt_label_source"] = "price_reaction_low_conf"
            rec["gt_auto_confidence"] = 0.3
            low_confidence += 1
            labeled_count += 1

        rec["gt_return_pct"] = round(ret * 100, 2)
        rec["gt_threshold_pct"] = round(thresh, 1)
        results.append(rec)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_path = GT_DIR / f"batch_auto_{today}.jsonl"
    GT_DIR.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for rec in results:
            f.write(json.dumps(rec, default=str) + "\n")

    summary = {
        "input": str(batch_path),
        "output": str(out_path),
        "n_unlabeled_input": len(unlabeled),
        "n_auto_labeled": labeled_count,
        "n_low_confidence": low_confidence,
        "n_no_price": len(unlabeled) - labeled_count,
    }
    print("Expansion complete:")
    print(f"  Input: {len(unlabeled)} unlabeled records")
    print(f"  Auto-labeled: {labeled_count} ({low_confidence} low-confidence)")
    print(f"  No price data: {len(unlabeled) - labeled_count}")
    print(f"  Output: {out_path}")
    return summary


def main():
    parser = argparse.ArgumentParser(description="Expand ground truth via price reaction")
    parser.add_argument(
        "--batch",
        type=Path,
        default=GT_DIR / "batch_2026-04-05.jsonl",
    )
    args = parser.parse_args()
    expand_labels(args.batch)


if __name__ == "__main__":
    main()
