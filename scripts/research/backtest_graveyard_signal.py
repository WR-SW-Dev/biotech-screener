#!/usr/bin/env python3
"""Backtest graveyard signal — does graveyard burden predict forward returns?

Phase B research: computes graveyard-derived features for each ticker,
joins with forward returns from rankings snapshots, and reports IC/spread.

Output:
    output/research/graveyard_signal_backtest.json
    output/research/graveyard_signal_backtest.md

Usage:
    python scripts/research/backtest_graveyard_signal.py
    python scripts/research/backtest_graveyard_signal.py --horizons 20,63
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("graveyard_backtest")


def load_graveyard_features(rollup_path: Path) -> Dict[str, Dict]:
    """Load graveyard rollup as feature dict keyed by ticker."""
    if not rollup_path.exists():
        return {}
    with open(rollup_path) as f:
        data = json.load(f)
    return data.get("tickers", {})


def load_rankings_snapshot(snapshot_dir: Path) -> List[Dict]:
    """Load rankings.csv from a snapshot directory."""
    rankings_path = snapshot_dir / "rankings.csv"
    if not rankings_path.exists():
        return []
    with open(rankings_path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _safe_float(val, default=None):
    try:
        v = float(val)
        return v if v == v else default  # NaN check
    except (TypeError, ValueError):
        return default


def compute_graveyard_z(features: Dict[str, Dict]) -> Dict[str, float]:
    """Z-score graveyard_severity_per_trial across tickers."""
    vals = {}
    for ticker, info in features.items():
        spt = info.get("graveyard_severity_per_trial")
        if spt is not None:
            vals[ticker] = spt

    if len(vals) < 5:
        return {}

    values = list(vals.values())
    mean = sum(values) / len(values)
    std = (sum((v - mean) ** 2 for v in values) / len(values)) ** 0.5
    if std < 1e-9:
        return {}

    return {t: round((v - mean) / std, 4) for t, v in vals.items()}


def spearman_ic(x: List[float], y: List[float]) -> Optional[float]:
    """Compute Spearman rank correlation."""
    if len(x) < 5 or len(x) != len(y):
        return None

    def _rank(vals):
        indexed = sorted(enumerate(vals), key=lambda p: p[1])
        ranks = [0.0] * len(vals)
        for rank, (idx, _) in enumerate(indexed):
            ranks[idx] = rank + 1
        return ranks

    rx = _rank(x)
    ry = _rank(y)
    n = len(rx)
    mean_rx = sum(rx) / n
    mean_ry = sum(ry) / n
    cov = sum((a - mean_rx) * (b - mean_ry) for a, b in zip(rx, ry))
    std_x = (sum((a - mean_rx) ** 2 for a in rx)) ** 0.5
    std_y = (sum((b - mean_ry) ** 2 for b in ry)) ** 0.5
    if std_x < 1e-9 or std_y < 1e-9:
        return None
    return round(cov / (std_x * std_y), 4)


def backtest_graveyard_signal(
    *,
    rollup_path: Path = PROJECT_ROOT / "data" / "graveyard" / "graveyard_company_rollup.json",
    snapshots_dir: Path = PROJECT_ROOT / "data" / "snapshots",
    output_dir: Path = PROJECT_ROOT / "output" / "research",
    horizons: List[int] = None,
    max_dates: int = 30,
) -> Dict[str, Any]:
    """Backtest graveyard burden signal against forward returns."""
    if horizons is None:
        horizons = [20, 63]

    features = load_graveyard_features(rollup_path)
    if not features:
        return {"error": "no graveyard rollup data"}

    z_scores = compute_graveyard_z(features)
    logger.info("Graveyard z-scores: %d tickers", len(z_scores))

    # Find available snapshot dates (exclude __pre_ dirs and non-date dirs)
    import re

    date_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    snapshot_dates = sorted(
        d.name
        for d in snapshots_dir.iterdir()
        if d.is_dir() and date_pattern.match(d.name) and (d / "rankings.csv").exists()
    )
    # Drop the most recent 30 trading days (no forward returns available)
    if len(snapshot_dates) > 30:
        snapshot_dates = snapshot_dates[:-30]
    if max_dates > 0:
        snapshot_dates = snapshot_dates[-max_dates:]
    logger.info("Snapshot dates: %d", len(snapshot_dates))

    # Load price history for forward returns
    price_path = PROJECT_ROOT / "production_data" / "price_history.csv"
    prices: Dict[str, Dict[str, float]] = defaultdict(dict)
    if price_path.exists():
        with open(price_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                ticker = row.get("ticker", "")
                date = row.get("date", "")
                close = _safe_float(row.get("close"))
                if ticker and date and close:
                    prices[ticker][date] = close
        logger.info("Price history: %d tickers", len(prices))

    # Compute IC for each snapshot date × horizon
    ic_results: Dict[int, List[float]] = {h: [] for h in horizons}
    quintile_results: Dict[int, Dict[str, List[float]]] = {h: {"Q1": [], "Q5": []} for h in horizons}

    for snap_date in snapshot_dates:
        rows = load_rankings_snapshot(snapshots_dir / snap_date)
        if not rows:
            continue

        for horizon in horizons:
            xs = []
            ys = []
            q_data = []

            for row in rows:
                ticker = row.get("ticker", "")
                if ticker not in z_scores:
                    continue

                z = z_scores[ticker]
                # Compute forward return
                ticker_prices = prices.get(ticker, {})
                # Find nearest price on or before snap_date
                avail_dates = sorted(ticker_prices.keys())
                p0_dates = [d for d in avail_dates if d <= snap_date]
                if not p0_dates:
                    continue
                p0 = ticker_prices[p0_dates[-1]]

                # Find price ~horizon trading days later
                future_dates = [d for d in avail_dates if d > snap_date]
                if len(future_dates) < horizon:
                    continue
                p1 = ticker_prices[future_dates[min(horizon - 1, len(future_dates) - 1)]]
                if p0 is None or p1 is None or p0 <= 0:
                    continue

                fwd_ret = (p1 - p0) / p0
                xs.append(z)
                ys.append(fwd_ret)
                q_data.append((z, fwd_ret))

            ic = spearman_ic(xs, ys)
            if ic is not None:
                ic_results[horizon].append(ic)

            # Quintile spread
            if len(q_data) >= 10:
                q_data.sort(key=lambda p: p[0])
                n = len(q_data)
                q1_size = max(n // 5, 1)
                q1_rets = [r for _, r in q_data[:q1_size]]
                q5_rets = [r for _, r in q_data[-q1_size:]]
                if q1_rets:
                    quintile_results[horizon]["Q1"].append(sum(q1_rets) / len(q1_rets))
                if q5_rets:
                    quintile_results[horizon]["Q5"].append(sum(q5_rets) / len(q5_rets))

    # Summarize
    summary = {}
    for h in horizons:
        ics = ic_results[h]
        q1s = quintile_results[h]["Q1"]
        q5s = quintile_results[h]["Q5"]

        mean_ic = round(sum(ics) / len(ics), 4) if ics else None
        mean_q1 = round(sum(q1s) / len(q1s), 4) if q1s else None
        mean_q5 = round(sum(q5s) / len(q5s), 4) if q5s else None
        spread = round(mean_q5 - mean_q1, 4) if mean_q1 is not None and mean_q5 is not None else None

        summary[f"{h}d"] = {
            "n_dates": len(ics),
            "mean_ic": mean_ic,
            "mean_q1_return": mean_q1,
            "mean_q5_return": mean_q5,
            "quintile_spread": spread,
        }

    result = {
        "schema": "graveyard_signal_backtest.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_tickers_with_z": len(z_scores),
        "n_snapshot_dates": len(snapshot_dates),
        "horizons": summary,
        "signal": "graveyard_severity_per_trial (z-scored)",
        "note": "Positive z = higher graveyard burden. Negative IC means burden predicts lower returns (expected).",
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "graveyard_signal_backtest.json"
    with open(json_path, "w") as f:
        json.dump(result, f, indent=2)
    logger.info("Wrote %s", json_path)

    # Markdown report
    md_lines = ["# Graveyard Signal Backtest", ""]
    md_lines.append(f"Signal: `graveyard_severity_per_trial` (z-scored, {len(z_scores)} tickers)")
    md_lines.append(f"Dates: {len(snapshot_dates)} snapshots")
    md_lines.append("")
    md_lines.append("| Horizon | N dates | Mean IC | Q1 return | Q5 return | Q5-Q1 spread |")
    md_lines.append("|---------|---------|---------|-----------|-----------|--------------|")
    for h in horizons:
        s = summary[f"{h}d"]
        md_lines.append(
            f"| {h}d | {s['n_dates']} | {s['mean_ic']} | {s['mean_q1_return']} | {s['mean_q5_return']} | {s['quintile_spread']} |"
        )
    md_lines.append("")
    md_lines.append("Positive z = higher graveyard burden. Negative IC = burden predicts lower returns (expected).")
    md_lines.append("")

    md_path = output_dir / "graveyard_signal_backtest.md"
    md_path.write_text("\n".join(md_lines))
    logger.info("Wrote %s", md_path)

    return result


def main():
    parser = argparse.ArgumentParser(description="Backtest graveyard signal (Spec 033, Phase B)")
    parser.add_argument("--horizons", default="20,63", help="Comma-separated horizons in trading days")
    parser.add_argument("--max-dates", type=int, default=30)
    args = parser.parse_args()

    horizons = [int(h) for h in args.horizons.split(",")]
    result = backtest_graveyard_signal(horizons=horizons, max_dates=args.max_dates)
    if "error" in result:
        logger.error(result["error"])
        sys.exit(1)

    for h, s in result.get("horizons", {}).items():
        logger.info("%s: IC=%s, Q5-Q1=%s", h, s["mean_ic"], s["quintile_spread"])


if __name__ == "__main__":
    main()
