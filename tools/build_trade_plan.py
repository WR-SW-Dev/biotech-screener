#!/usr/bin/env python3
"""Build Trade Plan — weekly-actionable artifact bridging rankings to money.

Combines position deltas (from build_trade_deltas) with:
  - Trailing performance dashboard (1w / 4w per bucket)
  - Turnover breakdown by bucket
  - Reason-code annotated trade list

Outputs:
    artifacts/live_shadow/trade_plan/YYYY-MM-DD/trade_plan.csv
    artifacts/live_shadow/trade_plan/YYYY-MM-DD/trade_plan.md

Usage:
    python3 tools/build_trade_plan.py --as-of-date 2026-03-08
"""
from __future__ import annotations

import argparse
import csv
import logging
import math
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.build_trade_deltas import (
    BUCKET_DISPLAY,
    DEFAULT_MIN_TRADE_USD,
    POSITIONS_DIR,
    compute_trade_deltas,
    find_prior_positions,
    load_positions_json,
)
from tools.live_shadow_portfolio import BUCKET_NAMES, PERFORMANCE_CSV, SHADOW_ROOT

TRADE_PLAN_ROOT = SHADOW_ROOT / "trade_plan"
PRICE_HISTORY_CSV = PROJECT_ROOT / "production_data" / "price_history.csv"

BROKER_ORDER_COLUMNS = [
    "symbol",
    "side",
    "qty",
    "order_type",
    "limit_price",
    "notional_usd",
    "original_delta_usd",
    "bucket",
    "gap_risk",
    "notes",
]

TRADE_PLAN_COLUMNS = [
    "ticker",
    "action",
    "delta_usd",
    "target_usd",
    "prior_usd",
    "bucket",
    "tier",
    "catalyst_days",
    "gap_risk",
    "reason",
    "risk_permission",
]

SCHEMA_VERSION = "trade_plan.v1"


# ---------------------------------------------------------------------------
# Trailing performance (rolling dashboard)
# ---------------------------------------------------------------------------


def load_performance_rows(
    perf_csv: Path = PERFORMANCE_CSV,
) -> List[Dict[str, str]]:
    """Load performance.csv rows sorted by date ascending."""
    if not perf_csv.is_file():
        return []
    with open(perf_csv, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    rows.sort(key=lambda r: r.get("date", ""))
    return rows


def compute_trailing_metrics(
    perf_rows: List[Dict[str, str]],
    n_weeks: int,
) -> Dict[str, Any]:
    """Compute trailing metrics over the last N rows (weeks).

    Returns dict with per-bucket and portfolio-level metrics:
      - net_pct, excess_vs_xbi, hit_rate, worst_week
    """
    if not perf_rows:
        return {"n_weeks": 0}

    tail = perf_rows[-n_weeks:]

    def _safe_float(v: str) -> Optional[float]:
        if not v or v.strip().lower() in ("nan", "none", ""):
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

    # Portfolio-level
    pnl_pcts = [_safe_float(r.get("pnl_pct", "")) for r in tail]
    pnl_pcts_valid = [p for p in pnl_pcts if p is not None]
    excess_pcts = [_safe_float(r.get("excess_vs_xbi_pct", "")) for r in tail]
    excess_valid = [e for e in excess_pcts if e is not None]

    portfolio = {
        "n_weeks": len(tail),
        "net_pct": round(statistics.mean(pnl_pcts_valid), 4) if pnl_pcts_valid else None,
        "excess_vs_xbi": round(statistics.mean(excess_valid), 4) if excess_valid else None,
        "hit_rate": round(sum(1 for p in pnl_pcts_valid if p > 0) / len(pnl_pcts_valid), 4) if pnl_pcts_valid else None,
        "worst_week": round(min(pnl_pcts_valid), 4) if pnl_pcts_valid else None,
    }

    # Per-bucket
    buckets = {}
    for b in BUCKET_NAMES:
        col = f"sleeve_{b}_pnl"
        vals = [_safe_float(r.get(col, "")) for r in tail]
        valid = [v for v in vals if v is not None]
        buckets[b] = {
            "n_weeks": len(valid),
            "total_pnl": round(sum(valid), 2) if valid else 0.0,
            "avg_pnl": round(statistics.mean(valid), 2) if valid else None,
            "hit_rate": round(sum(1 for v in valid if v > 0) / len(valid), 4) if valid else None,
            "worst_week": round(min(valid), 2) if valid else None,
        }

    return {"portfolio": portfolio, "buckets": buckets}


# ---------------------------------------------------------------------------
# Turnover by bucket
# ---------------------------------------------------------------------------


def compute_bucket_turnover(
    trades: List[Dict[str, Any]],
    prior_positions: List[Dict[str, Any]],
    current_positions: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """Compute turnover breakdown per bucket.

    Returns {bucket: {n_trades, buy_usd, sell_usd, net_usd, names_added, names_dropped}}.
    """
    result = {}
    for b in BUCKET_NAMES:
        b_trades = [t for t in trades if t.get("bucket") == b]
        buys = [t for t in b_trades if t["action"] == "BUY"]
        sells = [t for t in b_trades if t["action"] == "SELL"]

        prior_in_b = {p["ticker"] for p in prior_positions if p.get("bucket") == b}
        current_in_b = {p["ticker"] for p in current_positions if p.get("bucket") == b}

        result[b] = {
            "n_trades": len(b_trades),
            "buy_usd": round(sum(t["delta_usd"] for t in buys), 2),
            "sell_usd": round(sum(abs(t["delta_usd"]) for t in sells), 2),
            "net_usd": round(sum(t["delta_usd"] for t in b_trades), 2),
            "names_added": sorted(current_in_b - prior_in_b),
            "names_dropped": sorted(prior_in_b - current_in_b),
        }
    return result


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------


def write_trade_plan_csv(
    trades: List[Dict[str, Any]],
    out_path: Path,
) -> Path:
    """Write trade_plan.csv with deterministic columns."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=TRADE_PLAN_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(trades)
    return out_path


def write_trade_plan_md(
    trades: List[Dict[str, Any]],
    bucket_turnover: Dict[str, Dict[str, Any]],
    trailing_1w: Dict[str, Any],
    trailing_4w: Dict[str, Any],
    prior_date: str,
    current_date: str,
    prior_positions: List[Dict[str, Any]],
    current_positions: List[Dict[str, Any]],
    out_path: Path,
    risk_permission: str = "ADD_OK",
) -> Path:
    """Write trade_plan.md — the actionable weekly artifact."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = []

    if risk_permission == "NO_ADD_RISK":
        lines.append("> **NO_ADD_RISK: trailing alpha negative — BUY orders suppressed**")
        lines.append("")
    lines.append("# Weekly Trade Plan")
    lines.append("")
    lines.append(f"**Rebalance**: {prior_date or '(first)'} → {current_date}")
    lines.append(f"**Generated**: {current_date}")
    lines.append(f"**Execution**: NEXT_OPEN after {current_date}")
    lines.append("")

    # --- Summary ---
    buys = [t for t in trades if t["action"] == "BUY"]
    sells = [t for t in trades if t["action"] == "SELL"]
    total_buy = sum(t["delta_usd"] for t in buys)
    total_sell = sum(abs(t["delta_usd"]) for t in sells)

    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **Buys**: {len(buys)} (${total_buy:,.0f})")
    lines.append(f"- **Sells**: {len(sells)} (${total_sell:,.0f})")
    lines.append(f"- **Gross notional**: ${total_buy + total_sell:,.0f}")
    lines.append(f"- **Net delta**: ${total_buy - total_sell:+,.0f}")
    lines.append("")

    # --- Trailing Alpha Dashboard ---
    lines.append("## Trailing Alpha Dashboard")
    lines.append("")
    lines.append("| Bucket | 1w P&L | 4w Avg P&L | 4w Hit Rate | 4w Worst |")
    lines.append("|--------|--------|------------|-------------|----------|")

    for b in BUCKET_NAMES:
        label = BUCKET_DISPLAY.get(b, b)
        if b == "binary_91_180":
            label = f"**{label}**"
        t1 = trailing_1w.get("buckets", {}).get(b, {})
        t4 = trailing_4w.get("buckets", {}).get(b, {})

        pnl_1w = f"${t1.get('total_pnl', 0):+,.0f}" if t1.get("n_weeks", 0) > 0 else "—"
        avg_4w = f"${t4.get('avg_pnl', 0):+,.0f}" if t4.get("avg_pnl") is not None else "—"
        hr_4w = f"{t4['hit_rate']:.0%}" if t4.get("hit_rate") is not None else "—"
        worst_4w = f"${t4['worst_week']:+,.0f}" if t4.get("worst_week") is not None else "—"

        lines.append(f"| {label} | {pnl_1w} | {avg_4w} | {hr_4w} | {worst_4w} |")
    lines.append("")

    # Portfolio-level trailing
    p4 = trailing_4w.get("portfolio", {})
    if p4.get("n_weeks", 0) > 0:
        lines.append("**Portfolio (trailing 4w)**:")
        if p4.get("net_pct") is not None:
            lines.append(f"- Avg return: {p4['net_pct']:+.2f}%")
        if p4.get("excess_vs_xbi") is not None:
            lines.append(f"- Avg excess vs XBI: {p4['excess_vs_xbi']:+.2f}%")
        if p4.get("hit_rate") is not None:
            lines.append(f"- Hit rate: {p4['hit_rate']:.0%}")
        if p4.get("worst_week") is not None:
            lines.append(f"- Worst week: {p4['worst_week']:+.2f}%")
        lines.append("")

    # --- Trade List ---
    lines.append("## Trades")
    lines.append("")
    # Sells first, then buys (execution order)
    sorted_trades = sorted(trades, key=lambda t: (0 if t["action"] == "SELL" else 1, -abs(t["delta_usd"]), t["ticker"]))

    lines.append("| Ticker | Action | Delta $ | Target $ | Bucket | Gap Risk | Reason |")
    lines.append("|--------|--------|---------|----------|--------|----------|--------|")
    for t in sorted_trades:
        lines.append(
            f"| {t['ticker']} | {t['action']} "
            f"| ${t['delta_usd']:+,.0f} | ${t['target_usd']:,.0f} "
            f"| {BUCKET_DISPLAY.get(t.get('bucket', ''), t.get('bucket', ''))} "
            f"| {t.get('gap_risk') or '-'} | {t['reason']} |"
        )
    lines.append("")

    # --- Turnover by Bucket ---
    lines.append("## Turnover by Bucket")
    lines.append("")
    lines.append("| Bucket | Trades | Buy $ | Sell $ | Net $ | Added | Dropped |")
    lines.append("|--------|--------|-------|--------|-------|-------|---------|")
    for b in BUCKET_NAMES:
        bt = bucket_turnover.get(b, {})
        added = ", ".join(bt.get("names_added", [])[:5])
        dropped = ", ".join(bt.get("names_dropped", [])[:5])
        if len(bt.get("names_added", [])) > 5:
            added += f" +{len(bt['names_added']) - 5}"
        if len(bt.get("names_dropped", [])) > 5:
            dropped += f" +{len(bt['names_dropped']) - 5}"
        lines.append(
            f"| {BUCKET_DISPLAY.get(b, b)} "
            f"| {bt.get('n_trades', 0)} "
            f"| ${bt.get('buy_usd', 0):,.0f} "
            f"| ${bt.get('sell_usd', 0):,.0f} "
            f"| ${bt.get('net_usd', 0):+,.0f} "
            f"| {added or '-'} "
            f"| {dropped or '-'} |"
        )
    lines.append("")

    # --- Risk Flags ---
    gap_risk_buys = [t for t in buys if t.get("gap_risk") == "HIGH"]
    if gap_risk_buys:
        lines.append("## Risk Flags")
        lines.append("")
        lines.append(
            f"**{len(gap_risk_buys)} BUY(s) with gap-risk HIGH**: " f"{', '.join(t['ticker'] for t in gap_risk_buys)}"
        )
        lines.append("")

    text = "\n".join(lines)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(text)
    return out_path


# ---------------------------------------------------------------------------
# Broker-ready orders
# ---------------------------------------------------------------------------


def load_last_close(
    tickers: List[str],
    price_csv: Path = PRICE_HISTORY_CSV,
) -> Dict[str, float]:
    """Read price_history.csv, return {ticker: last_close}. Skip tickers with no data."""
    if not price_csv.is_file():
        return {}
    wanted = set(tickers)
    # Track (date, close) per ticker; keep the latest date
    latest: Dict[str, tuple] = {}
    with open(price_csv, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            t = row.get("ticker", "")
            if t not in wanted:
                continue
            d = row.get("date", "")
            close_str = row.get("close", "")
            try:
                close = float(close_str)
            except (ValueError, TypeError):
                continue
            if close <= 0:
                continue
            prev = latest.get(t)
            if prev is None or d > prev[0]:
                latest[t] = (d, close)
    return {t: v[1] for t, v in latest.items()}


def compute_broker_orders(trades: List[Dict], prices: Dict[str, float], *, fractional: bool = False) -> List[Dict]:
    """Convert trade dicts to broker order rows.

    Schema: symbol, side, qty, order_type, limit_price, notional_usd,
            original_delta_usd, bucket, gap_risk, notes.
    """
    orders = []
    for t in trades:
        ticker = t.get("ticker", "")
        action = t.get("action", "BUY")
        delta_usd = float(t.get("delta_usd", 0))
        price = prices.get(ticker)

        side = "BUY" if action == "BUY" else "SELL"

        if price is None or price <= 0:
            orders.append(
                {
                    "symbol": ticker,
                    "side": side,
                    "qty": 0,
                    "order_type": "REVIEW",
                    "limit_price": "",
                    "notional_usd": 0.0,
                    "original_delta_usd": round(delta_usd, 2),
                    "bucket": t.get("bucket", ""),
                    "gap_risk": t.get("gap_risk", ""),
                    "notes": "missing_price",
                }
            )
            continue

        abs_delta = abs(delta_usd)
        if fractional:
            qty = round(abs_delta / price, 4)
        else:
            qty = math.floor(abs_delta / price)

        notional = round(qty * price, 2)

        orders.append(
            {
                "symbol": ticker,
                "side": side,
                "qty": qty,
                "order_type": "LIMIT",
                "limit_price": round(price, 4),
                "notional_usd": notional,
                "original_delta_usd": round(delta_usd, 2),
                "bucket": t.get("bucket", ""),
                "gap_risk": t.get("gap_risk", ""),
                "notes": "",
            }
        )
    return orders


def write_broker_orders_csv(orders: List[Dict], out_path: Path) -> Path:
    """Write broker_orders.csv next to trade_plan.csv."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=BROKER_ORDER_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(orders)
    return out_path


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def build_trade_plan(
    as_of_date: str,
    *,
    positions_dir: Path = POSITIONS_DIR,
    perf_csv: Path = PERFORMANCE_CSV,
    min_trade_usd: float = DEFAULT_MIN_TRADE_USD,
    out_dir: Optional[Path] = None,
    skip_pre_trade_check: bool = False,
    broker_orders: bool = False,
    fractional: bool = False,
    price_source: Optional[Path] = None,
    manifest_path: Optional[Path] = None,
    snap_dir: Optional[Path] = None,
    current_positions: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build the complete weekly trade plan artifact.

    Args:
        current_positions: If provided, use these instead of reading from disk.
            Useful when caps have been applied in-memory.

    Returns dict with trades, paths, trailing metrics, bucket turnover.
    """
    if current_positions is not None:
        current_date = as_of_date
    else:
        current_path = positions_dir / f"{as_of_date}.json"
        if not current_path.is_file():
            return {"error": f"No positions file for {as_of_date}"}
        current_date, current_positions = load_positions_json(current_path)

    prior_path = find_prior_positions(current_date, positions_dir)
    if prior_path:
        prior_date, prior_positions = load_positions_json(prior_path)
    else:
        prior_date = ""
        prior_positions = []

    # Compute trade deltas
    trades = compute_trade_deltas(prior_positions, current_positions, min_trade_usd)

    # Bucket turnover
    bucket_turnover = compute_bucket_turnover(trades, prior_positions, current_positions)

    # Trailing performance
    perf_rows = load_performance_rows(perf_csv)
    trailing_1w = compute_trailing_metrics(perf_rows, 1)
    trailing_4w = compute_trailing_metrics(perf_rows, 4)

    # Pre-trade sanity gate — block trade plan on FAIL
    ptc = None
    if not skip_pre_trade_check:
        try:
            from tools.pre_trade_check import run_pre_trade_check, write_pre_trade_json, write_pre_trade_md

            _ptc_out = out_dir if out_dir is not None else TRADE_PLAN_ROOT / as_of_date
            _ptc_out.mkdir(parents=True, exist_ok=True)

            ptc_kwargs: Dict[str, Any] = dict(
                positions_dir=positions_dir,
                deviation_max_pct=100,  # bucket deviation checked separately
                max_turnover_pct=40.0,
                perf_csv=perf_csv,
            )
            if manifest_path is not None:
                ptc_kwargs["manifest_path"] = manifest_path
            if snap_dir is not None:
                ptc_kwargs["snap_dir"] = snap_dir
            ptc = run_pre_trade_check(as_of_date, **ptc_kwargs)
            write_pre_trade_json(ptc, _ptc_out / "pre_trade.json")
            write_pre_trade_md(ptc, _ptc_out / "pre_trade.md")

            if not ptc.can_trade:
                return {
                    "error": "pre_trade_check FAIL — trades blocked",
                    "pre_trade_overall": ptc.overall,
                    "pre_trade_checks": ptc.checks,
                    "can_trade": False,
                }
        except Exception as e:
            logger.warning("Pre-trade check failed (continuing): %s", e)

    # Readiness gate — block trades on HOLD verdict (policy-controlled)
    try:
        from tools.weekly_readiness_scorecard import (
            DEFAULT_READINESS_POLICY,
            ReadinessPolicy,
            evaluate_readiness_gate,
            load_history,
            load_json_safe,
        )

        _readiness_dir = PROJECT_ROOT / "artifacts" / "readiness"
        _sc_path = _readiness_dir / f"scorecard_{as_of_date}.json"
        _sc = load_json_safe(_sc_path)
        if _sc is not None:
            _policy = (
                ReadinessPolicy.from_json(DEFAULT_READINESS_POLICY)
                if DEFAULT_READINESS_POLICY.exists()
                else ReadinessPolicy.default()
            )
            _history = load_history(_readiness_dir / "history.jsonl")
            _gate = evaluate_readiness_gate(_sc, _policy, _history)
            if not _gate["can_trade"]:
                return {
                    "error": f"readiness gate {_gate['gate_status']} — trades blocked",
                    "readiness_verdict": _gate["verdict"],
                    "readiness_detail": _gate["detail"],
                    "can_trade": False,
                }
    except Exception as e:
        logger.warning("Readiness gate failed (continuing): %s", e)

    # Alpha health gate — determine risk permission
    risk_permission = "ADD_OK"
    if ptc is not None:
        try:
            ah_check = next(
                (c for c in ptc.checks if c["name"] == "alpha_health"),
                None,
            )
            if ah_check and ah_check.get("status") == "WARN":
                ah_val = ah_check.get("value", {})
                if isinstance(ah_val, dict) and ah_val.get("decision") == "NO_ADD_RISK":
                    risk_permission = "NO_ADD_RISK"
        except Exception as e:
            logger.warning("Alpha health gate extraction failed (continuing): %s", e)

    # Annotate trades with risk_permission and filter BUYs if NO_ADD_RISK
    for t in trades:
        t["risk_permission"] = risk_permission
    if risk_permission == "NO_ADD_RISK":
        trades = [t for t in trades if t["action"] != "BUY"]

    # Write outputs
    if out_dir is None:
        out_dir = TRADE_PLAN_ROOT / as_of_date
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = write_trade_plan_csv(trades, out_dir / "trade_plan.csv")
    md_path = write_trade_plan_md(
        trades,
        bucket_turnover,
        trailing_1w,
        trailing_4w,
        prior_date,
        current_date,
        prior_positions,
        current_positions,
        out_dir / "trade_plan.md",
        risk_permission=risk_permission,
    )

    result = {
        "schema": SCHEMA_VERSION,
        "as_of_date": current_date,
        "prior_date": prior_date,
        "n_trades": len(trades),
        "n_buys": sum(1 for t in trades if t["action"] == "BUY"),
        "n_sells": sum(1 for t in trades if t["action"] == "SELL"),
        "total_buy_usd": round(sum(t["delta_usd"] for t in trades if t["action"] == "BUY"), 2),
        "total_sell_usd": round(sum(abs(t["delta_usd"]) for t in trades if t["action"] == "SELL"), 2),
        "bucket_turnover": bucket_turnover,
        "trailing_1w": trailing_1w,
        "trailing_4w": trailing_4w,
        "csv_path": str(csv_path),
        "md_path": str(md_path),
        "trades": trades,
        "risk_permission": risk_permission,
    }

    # Broker orders (opt-in)
    if broker_orders and trades:
        tickers = [t["ticker"] for t in trades]
        pcv = price_source or PRICE_HISTORY_CSV
        prices = load_last_close(tickers, pcv)
        orders = compute_broker_orders(trades, prices, fractional=fractional)
        bo_path = write_broker_orders_csv(orders, out_dir / "broker_orders.csv")
        result["broker_orders_path"] = str(bo_path)
        result["broker_orders"] = orders

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Build weekly trade plan")
    parser.add_argument("--as-of-date", type=str, required=True, help="Snapshot date (YYYY-MM-DD)")
    parser.add_argument("--min-trade", type=float, default=DEFAULT_MIN_TRADE_USD)
    parser.add_argument("--out-dir", type=str, help="Override output directory")
    parser.add_argument("--broker-orders", action="store_true", default=False, help="Generate broker_orders.csv")
    parser.add_argument("--fractional", action="store_true", default=False, help="Use fractional shares")
    parser.add_argument("--price-source", type=str, help="Price CSV path (default: production_data/price_history.csv)")
    args = parser.parse_args()

    out_dir = Path(args.out_dir) if args.out_dir else None
    price_source = Path(args.price_source) if args.price_source else None
    result = build_trade_plan(
        args.as_of_date,
        min_trade_usd=args.min_trade,
        out_dir=out_dir,
        broker_orders=args.broker_orders,
        fractional=args.fractional,
        price_source=price_source,
    )

    if "error" in result:
        print(f"ERROR: {result['error']}", file=sys.stderr)
        sys.exit(1)

    print(f"Trade plan for {result['as_of_date']}")
    print(f"  Prior: {result['prior_date'] or '(first)'}")
    print(f"  Trades: {result['n_trades']} ({result['n_buys']} buys, {result['n_sells']} sells)")
    print(f"  Buy: ${result['total_buy_usd']:,.0f} | Sell: ${result['total_sell_usd']:,.0f}")
    print(f"  CSV: {result['csv_path']}")
    print(f"  MD: {result['md_path']}")
    if result.get("broker_orders_path"):
        print(f"  Broker orders: {result['broker_orders_path']}")


if __name__ == "__main__":
    main()
