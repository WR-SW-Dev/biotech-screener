#!/usr/bin/env python3
"""Backtest catalyst history signals (Spec 034, Phase D).

Tests whether catalyst history features predict forward returns:
1. negative_reg_count — do tickers with more negative regulatory events underperform?
2. event_churn — does date-revision frequency predict lower catalyst reliability?
3. multi_source_confirmation — does multi-source coverage improve precision?
4. event_density — does higher event activity predict better/worse returns?

Output:
    output/research/catalyst_history_signal_backtest.json
    output/research/catalyst_history_signal_backtest.md

Usage:
    python scripts/research/backtest_catalyst_history_signal.py
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("catalyst_history_backtest")

NEGATIVE_EVENT_TYPES = frozenset({"FDA_CRL", "FDA_RTF", "FDA_WARNING_LETTER", "CLINICAL_HOLD", "SAFETY_SIGNAL"})


def load_events(events_path: Path) -> List[Dict]:
    events = []
    if not events_path.exists():
        return events
    with open(events_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return events


def _safe_float(val, default=None):
    try:
        v = float(val)
        return v if v == v else default
    except (TypeError, ValueError):
        return default


def spearman_ic(x: List[float], y: List[float]) -> Optional[float]:
    if len(x) < 5 or len(x) != len(y):
        return None

    def _rank(vals):
        indexed = sorted(enumerate(vals), key=lambda p: p[1])
        ranks = [0.0] * len(vals)
        for rank_i, (idx, _) in enumerate(indexed):
            ranks[idx] = rank_i + 1
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


def compute_history_features(events: List[Dict], as_of_date: str) -> Dict[str, Dict[str, float]]:
    """Compute per-ticker features from event history as of a date.

    Only uses events with pit_available_at <= as_of_date.
    """
    # PIT filter
    pit_events = [e for e in events if (e.get("pit_available_at") or e.get("event_date", "9999"))[:10] <= as_of_date]

    ticker_events: Dict[str, List[Dict]] = defaultdict(list)
    for e in pit_events:
        ticker_events[e.get("ticker", "")].append(e)

    features: Dict[str, Dict[str, float]] = {}
    for ticker, evts in ticker_events.items():
        if not ticker:
            continue

        # Event counts
        n_total = len(evts)
        n_365d = sum(1 for e in evts if _days_since(e.get("event_date", ""), as_of_date) <= 365)

        # Negative regulatory count (365d)
        n_neg_365d = sum(
            1
            for e in evts
            if e.get("event_type", "") in NEGATIVE_EVENT_TYPES
            and _days_since(e.get("event_date", ""), as_of_date) <= 365
        )

        # Source diversity
        sources = set(e.get("source_family", "") for e in evts)
        n_sources = len(sources)
        multi_source = 1.0 if n_sources >= 2 else 0.0

        # Date revision proxy: count unique (event_type, source_family) groups
        # with multiple distinct event_dates
        event_groups: Dict[str, set] = defaultdict(set)
        for e in evts:
            key = f"{e.get('event_type', '')}|{e.get('source_family', '')}"
            event_groups[key].add(e.get("event_date", ""))
        n_revisions = sum(1 for dates in event_groups.values() if len(dates) > 1)
        churn_rate = n_revisions / max(len(event_groups), 1)

        features[ticker] = {
            "n_events_total": n_total,
            "n_events_365d": n_365d,
            "n_neg_reg_365d": n_neg_365d,
            "n_sources": n_sources,
            "multi_source": multi_source,
            "n_revisions": n_revisions,
            "churn_rate": churn_rate,
        }

    return features


def _days_since(date_str: str, as_of: str) -> int:
    try:
        d = datetime.fromisoformat(date_str[:10])
        a = datetime.fromisoformat(as_of[:10])
        return (a - d).days
    except (ValueError, TypeError):
        return 9999


def z_score(vals: Dict[str, float]) -> Dict[str, float]:
    if len(vals) < 5:
        return {}
    values = list(vals.values())
    mean = sum(values) / len(values)
    std = (sum((v - mean) ** 2 for v in values) / len(values)) ** 0.5
    if std < 1e-9:
        return {}
    return {t: round((v - mean) / std, 4) for t, v in vals.items()}


def backtest_signal(
    signal_name: str,
    signal_z: Dict[str, float],
    snapshot_dates: List[str],
    snapshots_dir: Path,
    prices: Dict[str, Dict[str, float]],
    horizons: List[int],
) -> Dict[str, Any]:
    """Backtest a single signal across dates and horizons."""
    ic_results: Dict[int, List[float]] = {h: [] for h in horizons}
    quintile_results: Dict[int, Dict[str, List[float]]] = {h: {"Q1": [], "Q5": []} for h in horizons}

    for snap_date in snapshot_dates:
        rankings_path = snapshots_dir / snap_date / "rankings.csv"
        if not rankings_path.exists():
            continue

        with open(rankings_path, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        for horizon in horizons:
            xs, ys, q_data = [], [], []

            for row in rows:
                ticker = row.get("ticker", "")
                if ticker not in signal_z:
                    continue

                z = signal_z[ticker]
                ticker_prices = prices.get(ticker, {})
                avail_dates = sorted(ticker_prices.keys())
                p0_dates = [d for d in avail_dates if d <= snap_date]
                if not p0_dates:
                    continue
                p0 = ticker_prices[p0_dates[-1]]

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

            if len(q_data) >= 10:
                q_data.sort(key=lambda p: p[0])
                n = len(q_data)
                q_size = max(n // 5, 1)
                q1_rets = [r for _, r in q_data[:q_size]]
                q5_rets = [r for _, r in q_data[-q_size:]]
                if q1_rets:
                    quintile_results[horizon]["Q1"].append(sum(q1_rets) / len(q1_rets))
                if q5_rets:
                    quintile_results[horizon]["Q5"].append(sum(q5_rets) / len(q5_rets))

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

    return {"signal": signal_name, "horizons": summary}


def main():
    parser = argparse.ArgumentParser(description="Backtest catalyst history signals (Spec 034 Phase D)")
    parser.add_argument(
        "--events", type=Path, default=PROJECT_ROOT / "data" / "catalyst_history" / "catalyst_history_events.jsonl"
    )
    parser.add_argument("--horizons", default="20,63", help="Comma-separated horizons")
    parser.add_argument("--max-dates", type=int, default=50)
    args = parser.parse_args()

    horizons = [int(h) for h in args.horizons.split(",")]

    events = load_events(args.events)
    logger.info("Loaded %d events", len(events))

    # Load prices
    price_path = PROJECT_ROOT / "production_data" / "price_history.csv"
    prices: Dict[str, Dict[str, float]] = defaultdict(dict)
    with open(price_path) as f:
        for row in csv.DictReader(f):
            t = row.get("ticker", "")
            d = row.get("date", "")
            c = _safe_float(row.get("close"))
            if t and d and c:
                prices[t][d] = c
    logger.info("Price history: %d tickers", len(prices))

    # Find snapshot dates
    snapshots_dir = PROJECT_ROOT / "data" / "snapshots"
    date_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    snapshot_dates = sorted(
        d.name
        for d in snapshots_dir.iterdir()
        if d.is_dir() and date_pattern.match(d.name) and (d / "rankings.csv").exists()
    )
    if len(snapshot_dates) > 30:
        snapshot_dates = snapshot_dates[:-30]
    if args.max_dates > 0:
        snapshot_dates = snapshot_dates[-args.max_dates :]
    logger.info("Snapshot dates: %d", len(snapshot_dates))

    # Use a mid-range date for feature computation (features are relatively stable)
    feature_date = snapshot_dates[-1] if snapshot_dates else "2026-03-01"
    features = compute_history_features(events, feature_date)
    logger.info("Features computed for %d tickers as of %s", len(features), feature_date)

    # --- Test 4 signals ---
    signals_to_test = {
        "neg_reg_count_365d": {t: f["n_neg_reg_365d"] for t, f in features.items()},
        "event_churn_rate": {t: f["churn_rate"] for t, f in features.items()},
        "multi_source_flag": {t: f["multi_source"] for t, f in features.items()},
        "event_density_365d": {t: f["n_events_365d"] for t, f in features.items()},
    }

    results = []
    for signal_name, raw_vals in signals_to_test.items():
        zs = z_score(raw_vals)
        if not zs:
            logger.warning("Skipping %s (insufficient data)", signal_name)
            continue

        logger.info("Testing %s (%d tickers)", signal_name, len(zs))
        result = backtest_signal(signal_name, zs, snapshot_dates, snapshots_dir, prices, horizons)
        results.append(result)

        for h, s in result["horizons"].items():
            logger.info("  %s %s: IC=%s, Q5-Q1=%s", signal_name, h, s["mean_ic"], s["quintile_spread"])

    # Write outputs
    output_dir = PROJECT_ROOT / "output" / "research"
    output_dir.mkdir(parents=True, exist_ok=True)

    output = {
        "schema": "catalyst_history_signal_backtest.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "feature_date": feature_date,
        "n_snapshot_dates": len(snapshot_dates),
        "signals": results,
    }

    json_path = output_dir / "catalyst_history_signal_backtest.json"
    with open(json_path, "w") as f:
        json.dump(output, f, indent=2)
    logger.info("Wrote %s", json_path)

    # Markdown
    md_lines = ["# Catalyst History Signal Backtest", ""]
    md_lines.append(f"Feature date: {feature_date} | Snapshots: {len(snapshot_dates)}")
    md_lines.append("")
    md_lines.append("| Signal | Horizon | N dates | Mean IC | Q1 ret | Q5 ret | Q5-Q1 |")
    md_lines.append("|--------|---------|---------|---------|--------|--------|-------|")
    for r in results:
        for h, s in r["horizons"].items():
            md_lines.append(
                f"| {r['signal']} | {h} | {s['n_dates']} | {s['mean_ic']} | "
                f"{s['mean_q1_return']} | {s['mean_q5_return']} | {s['quintile_spread']} |"
            )
    md_lines.append("")
    md_lines.append("Positive IC = higher signal predicts higher returns.")
    md_lines.append("For neg_reg and churn, we EXPECT negative IC (more = worse).")
    md_lines.append("")

    md_path = output_dir / "catalyst_history_signal_backtest.md"
    md_path.write_text("\n".join(md_lines))
    logger.info("Wrote %s", md_path)


if __name__ == "__main__":
    main()
