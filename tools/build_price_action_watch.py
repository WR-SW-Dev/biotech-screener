#!/usr/bin/env python3
"""Price action watch — stock + options big-move alerts on model-relevant names.

Monitors a capped watchlist (review queue, trade plan, shadow positions,
catalyst delta, A-tier near-term) for significant stock and options moves.

Read-only — does not affect rankings, scoring, or execution.

Output:
    artifacts/price_action_watch/{date}_watch.json
    artifacts/price_action_watch/{date}_watch.md

Usage:
    python tools/build_price_action_watch.py --as-of-date 2026-03-27
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("price_action_watch")

SCHEMA_VERSION = "price_action_watch.v1"
WATCHLIST_MAX = 40

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------
THRESHOLDS = {
    # Stock moves (1d return %)
    "stock_move_up": 5.0,
    "stock_move_down": -5.0,
    "stock_big_move_up": 10.0,
    "stock_big_move_down": -10.0,
    # Gap (open vs prior close, %)
    "gap_up": 3.0,
    "gap_down": -3.0,
    # Relative volume (vs 20d average)
    "rvol_spike": 2.5,
    # Options surface
    "iv_ramp_high": 0.10,  # atm_iv_change_5d
    "iv_crush": -0.10,  # atm_iv_change_5d
    "surface_move_high": 0.80,  # actual_implied_move_pctile
    "skew_flip": 0.40,  # |opt_rr_25d| threshold — biotech skew is structurally elevated
}


def _sf(val: Any) -> float:
    if val is None or val == "":
        return math.nan
    try:
        return float(val)
    except (ValueError, TypeError):
        return math.nan


def _load_json(path: Path) -> Optional[Dict]:
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _load_csv_tickers(path: Path) -> Set[str]:
    if not path.exists():
        return set()
    try:
        with open(path, encoding="utf-8") as f:
            return {row["ticker"] for row in csv.DictReader(f) if row.get("ticker")}
    except (KeyError, OSError):
        return set()


# ---------------------------------------------------------------------------
# Price data
# ---------------------------------------------------------------------------
def load_recent_prices(
    price_csv: Path,
    tickers: Set[str],
    as_of_date: str,
    lookback_days: int = 25,
) -> Dict[str, List[tuple]]:
    """Load recent price data for tickers. Returns {ticker: [(date, close), ...]}."""
    prices: Dict[str, List[tuple]] = {}
    if not price_csv.exists():
        return prices
    with open(price_csv, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            t = row.get("ticker", "")
            d = row.get("date", "")
            c = row.get("close", "")
            if t in tickers and d and c and d <= as_of_date:
                try:
                    prices.setdefault(t, []).append((d, float(c)))
                except ValueError:
                    pass
    for t in prices:
        prices[t].sort()
        prices[t] = prices[t][-lookback_days:]
    return prices


def compute_stock_metrics(series: List[tuple]) -> Dict[str, Any]:
    """Compute stock price metrics from a sorted (date, close) series."""
    if len(series) < 2:
        return {}

    latest_date, latest_price = series[-1]
    prior_date, prior_price = series[-2]

    ret_1d = (latest_price - prior_price) / prior_price * 100 if prior_price > 0 else math.nan

    # 5d return
    ret_5d = math.nan
    if len(series) >= 6:
        p5 = series[-6][1]
        if p5 > 0:
            ret_5d = (latest_price - p5) / p5 * 100

    # 20d average volume proxy: use price volatility as rvol proxy
    # (we don't have volume data in price_history.csv, so use return dispersion)
    returns = []
    for i in range(1, len(series)):
        p0 = series[i - 1][1]
        p1 = series[i][1]
        if p0 > 0:
            returns.append(abs((p1 - p0) / p0))
    avg_move = sum(returns) / len(returns) if returns else 0
    latest_move = abs(ret_1d / 100) if not math.isnan(ret_1d) else 0
    rvol = latest_move / avg_move if avg_move > 0 else math.nan

    return {
        "latest_date": latest_date,
        "latest_price": round(latest_price, 2),
        "prior_price": round(prior_price, 2),
        "return_1d_pct": round(ret_1d, 2) if not math.isnan(ret_1d) else None,
        "return_5d_pct": round(ret_5d, 2) if not math.isnan(ret_5d) else None,
        "rvol": round(rvol, 2) if not math.isnan(rvol) else None,
    }


# ---------------------------------------------------------------------------
# Alert classification
# ---------------------------------------------------------------------------
def classify_alerts(
    ticker: str,
    stock: Dict[str, Any],
    options: Dict[str, str],
) -> List[str]:
    """Classify alerts for one name. Returns list of alert codes."""
    alerts = []

    # Stock moves
    ret = stock.get("return_1d_pct")
    if ret is not None:
        if ret >= THRESHOLDS["stock_big_move_up"]:
            alerts.append("STOCK_BIG_MOVE_UP")
        elif ret >= THRESHOLDS["stock_move_up"]:
            alerts.append("STOCK_MOVE_UP")
        elif ret <= THRESHOLDS["stock_big_move_down"]:
            alerts.append("STOCK_BIG_MOVE_DOWN")
        elif ret <= THRESHOLDS["stock_move_down"]:
            alerts.append("STOCK_MOVE_DOWN")

    # Relative volume
    rvol = stock.get("rvol")
    if rvol is not None and rvol >= THRESHOLDS["rvol_spike"]:
        alerts.append("RVOL_SPIKE")

    # Options surface
    iv_change = _sf(options.get("atm_iv_change_5d", ""))
    if not math.isnan(iv_change):
        if iv_change >= THRESHOLDS["iv_ramp_high"]:
            alerts.append("IV_RAMP_HIGH")
        elif iv_change <= THRESHOLDS["iv_crush"]:
            alerts.append("IV_CRUSH")

    move_pctile = _sf(options.get("actual_implied_move_pctile", ""))
    if not math.isnan(move_pctile) and move_pctile >= THRESHOLDS["surface_move_high"]:
        alerts.append("OPTIONS_SURFACE_MOVE_HIGH")

    rr = _sf(options.get("opt_rr_25d", ""))
    if not math.isnan(rr) and abs(rr) >= THRESHOLDS["skew_flip"]:
        alerts.append("SKEW_EXTREME")

    # Stock/options divergence: stock down but IV ramping (or vice versa)
    if ret is not None and not math.isnan(iv_change):
        if ret <= -3.0 and iv_change >= 0.05:
            alerts.append("STOCK_DOWN_IV_UP")
        elif ret >= 3.0 and iv_change <= -0.05:
            alerts.append("STOCK_UP_IV_DOWN")

    return alerts


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------
def build_price_action_watch(
    as_of_date: str,
    *,
    snapshots_dir: Path = REPO_ROOT / "data" / "snapshots",
    artifacts_dir: Path = REPO_ROOT / "artifacts",
    price_csv: Path = REPO_ROOT / "production_data" / "price_history.csv",
) -> Dict[str, Any]:
    """Build price action watch artifact."""
    snap_dir = snapshots_dir / as_of_date
    rankings_path = snap_dir / "rankings.csv"
    if not rankings_path.exists():
        return {"error": f"rankings.csv not found for {as_of_date}"}

    # Load rankings
    rankings: Dict[str, Dict[str, str]] = {}
    with open(rankings_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("ticker"):
                rankings[row["ticker"]] = row

    # Build watchlist (same sources as options_watch)
    review_queue = _load_csv_tickers(snap_dir / "review_queue.csv")
    trade_plan = _load_csv_tickers(artifacts_dir / "live_shadow" / "trade_plan" / as_of_date / "trade_plan.csv")

    position_tickers: Set[str] = set()
    pos_data = _load_json(artifacts_dir / "live_shadow" / "positions" / f"{as_of_date}.json")
    if pos_data:
        position_tickers = {p["ticker"] for p in pos_data.get("positions", []) if p.get("ticker")}

    catalyst_delta_tickers: Set[str] = set()
    cd_data = _load_json(artifacts_dir / "catalyst_delta" / f"{as_of_date}_delta.json")
    if cd_data:
        catalyst_delta_tickers = {d["ticker"] for d in cd_data.get("deltas", []) if d.get("ticker")}

    # A-tier near-term
    a_near = {
        t
        for t, r in rankings.items()
        if r.get("tier_dev") == "A"
        and not math.isnan(_sf(r.get("catalyst_days", "")))
        and _sf(r.get("catalyst_days", "")) <= 30
    }

    watchlist = review_queue | trade_plan | position_tickers | catalyst_delta_tickers | a_near
    watchlist = {t for t in watchlist if t in rankings}
    if len(watchlist) > WATCHLIST_MAX:
        # Prioritize by rank
        ranked = sorted(watchlist, key=lambda t: _sf(rankings[t].get("actionable_rank", "9999")))
        watchlist = set(ranked[:WATCHLIST_MAX])

    # Load prices
    prices = load_recent_prices(price_csv, watchlist, as_of_date)

    # Classify each name
    rows = []
    for ticker in sorted(watchlist):
        series = prices.get(ticker, [])
        stock_metrics = compute_stock_metrics(series)
        options_data = rankings.get(ticker, {})

        alerts = classify_alerts(ticker, stock_metrics, options_data)

        r = rankings.get(ticker, {})
        entry = {
            "ticker": ticker,
            "tier": r.get("tier_dev", ""),
            "actionable_rank": int(_sf(r.get("actionable_rank", "0"))) if r.get("actionable_rank") else None,
            "catalyst_days": int(_sf(r.get("catalyst_days", ""))) if r.get("catalyst_days") else None,
            "is_hard_catalyst": r.get("is_hard_catalyst", "") == "1",
            "return_1d_pct": stock_metrics.get("return_1d_pct"),
            "return_5d_pct": stock_metrics.get("return_5d_pct"),
            "rvol": stock_metrics.get("rvol"),
            "latest_price": stock_metrics.get("latest_price"),
            "atm_iv_change_5d": round(_sf(r.get("atm_iv_change_5d", "")), 4) if r.get("atm_iv_change_5d") else None,
            "actual_implied_move_pctile": (
                round(_sf(r.get("actual_implied_move_pctile", "")), 4) if r.get("actual_implied_move_pctile") else None
            ),
            "opt_rr_25d": round(_sf(r.get("opt_rr_25d", "")), 4) if r.get("opt_rr_25d") else None,
            "alerts": alerts,
            "n_alerts": len(alerts),
        }
        rows.append(entry)

    # Sort: most alerts first, then by return magnitude
    rows.sort(key=lambda r: (-r["n_alerts"], -abs(r.get("return_1d_pct") or 0)))

    n_alerted = sum(1 for r in rows if r["alerts"])

    result = {
        "schema": SCHEMA_VERSION,
        "as_of_date": as_of_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "watchlist_size": len(rows),
        "n_alerted": n_alerted,
        "thresholds": THRESHOLDS,
        "sources": {
            "review_queue": len(review_queue),
            "trade_plan": len(trade_plan),
            "positions": len(position_tickers),
            "catalyst_delta": len(catalyst_delta_tickers),
            "a_near": len(a_near),
        },
        "rows": rows,
    }

    # Write artifacts
    out_dir = artifacts_dir / "price_action_watch"
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / f"{as_of_date}_watch.json"
    md_path = out_dir / f"{as_of_date}_watch.md"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)
    logger.info("Wrote %s", json_path)

    md_path.write_text(format_watch_md(result), encoding="utf-8")
    logger.info("Wrote %s", md_path)

    result["_json_path"] = str(json_path)
    result["_md_path"] = str(md_path)
    return result


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------
def format_watch_md(d: Dict[str, Any]) -> str:
    lines = []
    lines.append(f"# Price Action Watch — {d['as_of_date']}")
    lines.append("")
    lines.append(f"Watchlist: {d['watchlist_size']} names | Alerted: {d['n_alerted']}")
    lines.append("")

    rows = d.get("rows", [])
    alerted = [r for r in rows if r["alerts"]]

    if alerted:
        lines.append("## Alerts")
        lines.append("")
        lines.append("| Ticker | Tier | Rank | 1d | 5d | RVOL | IV 5d | Alerts |")
        lines.append("|--------|------|------|----|----|------|-------|--------|")
        for r in alerted:
            ret1 = f"{r['return_1d_pct']:+.1f}%" if r.get("return_1d_pct") is not None else "-"
            ret5 = f"{r['return_5d_pct']:+.1f}%" if r.get("return_5d_pct") is not None else "-"
            rvol = f"{r['rvol']:.1f}x" if r.get("rvol") is not None else "-"
            iv5d = f"{r['atm_iv_change_5d']:+.3f}" if r.get("atm_iv_change_5d") is not None else "-"
            alerts_str = ", ".join(r["alerts"])
            rank = r.get("actionable_rank", "?")
            lines.append(f"| {r['ticker']} | {r['tier']} | {rank} | {ret1} | {ret5} | {rvol} | {iv5d} | {alerts_str} |")
        lines.append("")
    else:
        lines.append("No alerts triggered.")
        lines.append("")

    lines.append(f"*Generated: {d.get('generated_at', '')}*")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Price action watch — stock + options big-move alerts")
    parser.add_argument("--as-of-date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    parser.add_argument("--snapshots-dir", type=Path, default=REPO_ROOT / "data" / "snapshots")
    parser.add_argument("--artifacts-dir", type=Path, default=REPO_ROOT / "artifacts")
    parser.add_argument("--price-csv", type=Path, default=REPO_ROOT / "production_data" / "price_history.csv")
    args = parser.parse_args()

    result = build_price_action_watch(
        args.as_of_date,
        snapshots_dir=args.snapshots_dir,
        artifacts_dir=args.artifacts_dir,
        price_csv=args.price_csv,
    )

    if "error" in result:
        logger.error(result["error"])
        sys.exit(1)

    logger.info("Watch: %d names, %d alerted", result["watchlist_size"], result["n_alerted"])


if __name__ == "__main__":
    main()
