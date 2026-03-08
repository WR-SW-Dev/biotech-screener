#!/usr/bin/env python3
"""Build Rebalance Orders — diff positions into executable order sheet.

Reads current vs prior positions, computes deltas, converts to shares,
applies cash-buffer scaling, and writes orders.csv + orders.md.

Usage:
    python3 tools/build_rebalance_orders.py --as-of-date 2026-03-08
    python3 tools/build_rebalance_orders.py --as-of-date 2026-03-08 --round-lots --min-trade-usd 1000
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.live_shadow_portfolio import PRICE_HISTORY_PATH, SHADOW_ROOT, load_price_map

POSITIONS_DIR = SHADOW_ROOT / "positions"
ORDERS_ROOT = SHADOW_ROOT / "orders"

DEFAULT_MIN_TRADE_USD = 750.0
DEFAULT_MAX_ORDERS = 200
DEFAULT_CASH_BUFFER_USD = 1000.0

ORDERS_COLUMNS = [
    "ticker",
    "side",
    "shares",
    "est_price",
    "est_notional",
    "bucket",
    "reason",
    "gap_risk",
    "price_coverage",
    "prev_bucket",
    "new_bucket",
    "prev_rank",
    "new_rank",
    "prev_catalyst_days",
    "new_catalyst_days",
    "tier",
    "momentum_tag",
]

BUCKET_DISPLAY = {
    "binary_0_30": "Binary 0-30d",
    "binary_31_90": "Binary 31-90d",
    "binary_91_180": "Binary 91-180d",
    "less_binary": "Less Binary",
}


def _load_positions(path: Path) -> Tuple[str, List[Dict[str, Any]]]:
    with open(path) as f:
        doc = json.load(f)
    return doc.get("as_of_date", path.stem), doc.get("positions", [])


def _find_prior(as_of_date: str, positions_dir: Path) -> Optional[Path]:
    if not positions_dir.is_dir():
        return None
    candidates = [p for p in positions_dir.iterdir() if p.suffix == ".json" and p.stem < as_of_date]
    return max(candidates, key=lambda p: p.stem) if candidates else None


def _classify_reason(prev_usd: float, target_usd: float) -> str:
    if prev_usd <= 0 and target_usd > 0:
        return "NEW"
    if prev_usd > 0 and target_usd <= 0:
        return "EXIT"
    if target_usd > prev_usd:
        return "ADD"
    return "TRIM"


def build_rebalance_orders(
    as_of_date: str,
    *,
    positions_dir: Path = POSITIONS_DIR,
    prev_date: Optional[str] = None,
    price_path: Path = PRICE_HISTORY_PATH,
    min_trade_usd: float = DEFAULT_MIN_TRADE_USD,
    max_orders: int = DEFAULT_MAX_ORDERS,
    round_lots: bool = False,
    cash_buffer_usd: float = DEFAULT_CASH_BUFFER_USD,
    allow_sells_only: bool = False,
    allow_missing_price: bool = False,
    out_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Build executable order sheet from position diff.

    Returns dict with orders list, paths, skipped items, summary stats.
    """
    current_path = positions_dir / f"{as_of_date}.json"
    if not current_path.is_file():
        raise FileNotFoundError(f"No positions file for {as_of_date}")

    _, current_positions = _load_positions(current_path)

    # Find prior
    if prev_date:
        prev_path = positions_dir / f"{prev_date}.json"
    else:
        prev_path = _find_prior(as_of_date, positions_dir)

    prior_map: Dict[str, Dict[str, Any]] = {}
    if prev_path and prev_path.is_file():
        _, prev_positions = _load_positions(prev_path)
        prior_map = {p["ticker"]: p for p in prev_positions}

    current_map = {p["ticker"]: p for p in current_positions}

    # Load prices for share conversion
    prices = load_price_map(price_path, as_of_date)

    all_tickers = sorted(set(prior_map) | set(current_map))
    orders: List[Dict[str, Any]] = []
    skipped: List[Dict[str, str]] = []

    for ticker in all_tickers:
        prev = prior_map.get(ticker)
        curr = current_map.get(ticker)

        prev_usd = prev.get("target_dollars", 0.0) if prev else 0.0
        target_usd = curr.get("target_dollars", 0.0) if curr else 0.0
        delta_usd = target_usd - prev_usd

        if abs(delta_usd) < min_trade_usd:
            continue

        if allow_sells_only and delta_usd > 0:
            continue

        ref = curr or prev
        price = prices.get(ticker)
        price_coverage = "OK" if price and price > 0 else "MISSING"

        if not price or price <= 0:
            skipped.append(
                {
                    "ticker": ticker,
                    "reason": "missing_price",
                    "delta_usd": f"{delta_usd:.2f}",
                    "bucket": ref.get("bucket", ""),
                }
            )
            continue

        # Focus bucket missing-price guard
        if not allow_missing_price and ref.get("price_coverage") == "MISSING":
            if ref.get("bucket") == "binary_91_180" and delta_usd > 0:
                skipped.append(
                    {
                        "ticker": ticker,
                        "reason": "focus_bucket_missing_price",
                        "delta_usd": f"{delta_usd:.2f}",
                        "bucket": ref.get("bucket", ""),
                    }
                )
                continue

        side = "BUY" if delta_usd > 0 else "SELL"
        reason = _classify_reason(prev_usd, target_usd)

        if round_lots:
            shares = int(math.floor(abs(delta_usd) / price / 100) * 100)
        else:
            shares = int(math.floor(abs(delta_usd) / price))

        if shares <= 0:
            continue

        est_notional = round(shares * price, 2)

        orders.append(
            {
                "ticker": ticker,
                "side": side,
                "shares": shares,
                "est_price": round(price, 4),
                "est_notional": est_notional,
                "bucket": ref.get("bucket", ""),
                "reason": reason,
                "gap_risk": ref.get("gap_risk", ""),
                "price_coverage": price_coverage,
                "prev_bucket": prev.get("bucket", "") if prev else "",
                "new_bucket": curr.get("bucket", "") if curr else "",
                "prev_rank": prev.get("actionable_rank", "") if prev else "",
                "new_rank": curr.get("actionable_rank", "") if curr else "",
                "prev_catalyst_days": prev.get("catalyst_days", "") if prev else "",
                "new_catalyst_days": curr.get("catalyst_days", "") if curr else "",
                "tier": ref.get("tier", ""),
                "momentum_tag": ref.get("mom_state", ""),
            }
        )

    # Cash-buffer scaling: if total buys exceed account minus buffer, scale buys down
    total_buys = sum(o["est_notional"] for o in orders if o["side"] == "BUY")
    total_sells = sum(o["est_notional"] for o in orders if o["side"] == "SELL")
    account_usd = sum(p.get("target_dollars", 0) for p in current_positions)
    available = account_usd + total_sells - cash_buffer_usd

    if total_buys > available and available > 0:
        scale = available / total_buys
        for o in orders:
            if o["side"] == "BUY":
                price = o["est_price"]
                new_notional = o["est_notional"] * scale
                if round_lots:
                    o["shares"] = int(math.floor(new_notional / price / 100) * 100)
                else:
                    o["shares"] = int(math.floor(new_notional / price))
                o["est_notional"] = round(o["shares"] * price, 2)

    # Remove zero-share orders after scaling
    orders = [o for o in orders if o["shares"] > 0]

    # Deterministic sort: sells first if trimming needed, then by abs(notional) desc, ticker
    orders.sort(key=lambda o: (0 if o["side"] == "SELL" else 1, -o["est_notional"], o["ticker"]))

    # Max orders cutoff (keep all sells, trim buys)
    if len(orders) > max_orders:
        sells = [o for o in orders if o["side"] == "SELL"]
        buys = [o for o in orders if o["side"] == "BUY"]
        remaining = max_orders - len(sells)
        orders = sells + buys[: max(0, remaining)]

    # Write outputs
    if out_dir is None:
        out_dir = ORDERS_ROOT / as_of_date
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = _write_orders_csv(orders, out_dir / "orders.csv")
    md_path = _write_orders_md(orders, skipped, as_of_date, out_dir / "orders.md")

    return {
        "as_of_date": as_of_date,
        "n_orders": len(orders),
        "n_buys": sum(1 for o in orders if o["side"] == "BUY"),
        "n_sells": sum(1 for o in orders if o["side"] == "SELL"),
        "gross_notional": round(sum(o["est_notional"] for o in orders), 2),
        "net_notional": round(
            sum(o["est_notional"] for o in orders if o["side"] == "BUY")
            - sum(o["est_notional"] for o in orders if o["side"] == "SELL"),
            2,
        ),
        "n_skipped": len(skipped),
        "csv_path": str(csv_path),
        "md_path": str(md_path),
        "orders": orders,
        "skipped": skipped,
    }


def _write_orders_csv(orders: List[Dict[str, Any]], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=ORDERS_COLUMNS)
        w.writeheader()
        w.writerows(orders)
    return path


def _write_orders_md(
    orders: List[Dict[str, Any]],
    skipped: List[Dict[str, str]],
    as_of_date: str,
    path: Path,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    buys = [o for o in orders if o["side"] == "BUY"]
    sells = [o for o in orders if o["side"] == "SELL"]
    gross = sum(o["est_notional"] for o in orders)
    net = sum(o["est_notional"] for o in buys) - sum(o["est_notional"] for o in sells)

    lines = [
        "# Rebalance Orders",
        "",
        f"**Date**: {as_of_date}",
        f"**Generated**: {ts}",
        "",
        "## Summary",
        "",
        f"- **Buys**: {len(buys)} (${sum(o['est_notional'] for o in buys):,.0f})",
        f"- **Sells**: {len(sells)} (${sum(o['est_notional'] for o in sells):,.0f})",
        f"- **Gross notional**: ${gross:,.0f}",
        f"- **Net notional**: ${net:+,.0f}",
        f"- **Total orders**: {len(orders)}",
        "",
    ]

    # Top 10 largest
    top10 = sorted(orders, key=lambda o: -o["est_notional"])[:10]
    lines.append("## Top 10 Largest Orders")
    lines.append("")
    lines.append("| Ticker | Side | Shares | Price | Notional | Bucket | Reason |")
    lines.append("|--------|------|--------|-------|----------|--------|--------|")
    for o in top10:
        lines.append(
            f"| {o['ticker']} | {o['side']} | {o['shares']} "
            f"| ${o['est_price']:.2f} | ${o['est_notional']:,.0f} "
            f"| {BUCKET_DISPLAY.get(o['bucket'], o['bucket'])} | {o['reason']} |"
        )
    lines.append("")

    # Churn reasons
    reason_counts: Dict[str, int] = {}
    bucket_transitions = 0
    for o in orders:
        reason_counts[o["reason"]] = reason_counts.get(o["reason"], 0) + 1
        pb = o.get("prev_bucket", "")
        nb = o.get("new_bucket", "")
        if pb and nb and pb != nb:
            bucket_transitions += 1

    lines.append("## Churn Reasons")
    lines.append("")
    for reason, count in sorted(reason_counts.items()):
        lines.append(f"- **{reason}**: {count}")
    lines.append(f"- **Bucket transitions**: {bucket_transitions}")
    lines.append(f"- **Missing-price skips**: {sum(1 for s in skipped if s['reason'] == 'missing_price')}")
    gap_risk_caps = sum(1 for o in orders if o.get("gap_risk") == "HIGH")
    lines.append(f"- **Gap-risk HIGH orders**: {gap_risk_caps}")
    lines.append("")

    # Skipped
    if skipped:
        lines.append("## Skipped")
        lines.append("")
        lines.append("| Ticker | Reason | Delta $ | Bucket |")
        lines.append("|--------|--------|---------|--------|")
        for s in skipped:
            lines.append(f"| {s['ticker']} | {s['reason']} | ${s['delta_usd']} | {s['bucket']} |")
        lines.append("")

    with open(path, "w") as f:
        f.write("\n".join(lines))
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build rebalance order sheet")
    parser.add_argument("--as-of-date", required=True, help="Current date (YYYY-MM-DD)")
    parser.add_argument("--prev-date", type=str, help="Previous date (default: auto-detect)")
    parser.add_argument("--min-trade-usd", type=float, default=DEFAULT_MIN_TRADE_USD)
    parser.add_argument("--max-orders", type=int, default=DEFAULT_MAX_ORDERS)
    parser.add_argument("--round-lots", action="store_true")
    parser.add_argument("--cash-buffer-usd", type=float, default=DEFAULT_CASH_BUFFER_USD)
    parser.add_argument("--allow-sells-only", action="store_true")
    parser.add_argument("--allow-missing-price", action="store_true")
    parser.add_argument("--out-dir", type=str)
    args = parser.parse_args()

    result = build_rebalance_orders(
        args.as_of_date,
        prev_date=args.prev_date,
        min_trade_usd=args.min_trade_usd,
        max_orders=args.max_orders,
        round_lots=args.round_lots,
        cash_buffer_usd=args.cash_buffer_usd,
        allow_sells_only=args.allow_sells_only,
        allow_missing_price=args.allow_missing_price,
        out_dir=Path(args.out_dir) if args.out_dir else None,
    )

    print(f"Orders for {result['as_of_date']}: {result['n_orders']} total")
    print(f"  Buys: {result['n_buys']}, Sells: {result['n_sells']}")
    print(f"  Gross: ${result['gross_notional']:,.0f}, Net: ${result['net_notional']:+,.0f}")
    if result["n_skipped"]:
        print(f"  Skipped: {result['n_skipped']}")
    print(f"  CSV: {result['csv_path']}")
    print(f"  Summary: {result['md_path']}")


if __name__ == "__main__":
    main()
