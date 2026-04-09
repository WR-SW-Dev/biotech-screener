#!/usr/bin/env python3
"""Build Weekly Orders — convert target portfolio diff into executable orders.

Reads current holdings (prior positions) and target holdings (from policy +
latest snapshot), computes delta notional per ticker, applies execution rules,
and writes broker-friendly orders + audit receipt.

Usage:
    python3 tools/build_weekly_orders.py --as-of-date 2026-03-08
    python3 tools/build_weekly_orders.py --as-of-date 2026-03-08 --dry-run
    python3 tools/build_weekly_orders.py --as-of-date 2026-03-08 --slippage-bps 25
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.live_shadow_portfolio import (
    BUCKET_DISPLAY,
    PRICE_HISTORY_PATH,
    SHADOW_ROOT,
    SNAPSHOTS_ROOT,
    build_positions,
    load_policy,
    load_price_map,
    load_prior_positions,
    load_rankings,
)

SCHEMA_VERSION = "weekly_orders.v1"

DEFAULT_MIN_TRADE_USD = 250.0
DEFAULT_MAX_ORDERS = 80
DEFAULT_SLIPPAGE_BPS = 25.0

ORDERS_CSV_COLUMNS = [
    "action",
    "ticker",
    "notional_usd",
    "limit_price",
    "note",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha256_file(path: Path) -> str:
    """Compute SHA-256 of a file's contents."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def compute_order_deltas(
    prior_positions: List[Dict[str, Any]],
    target_positions: List[Dict[str, Any]],
    *,
    min_trade_usd: float = DEFAULT_MIN_TRADE_USD,
    max_orders: int = DEFAULT_MAX_ORDERS,
    gap_risk_cap_pct: float = 0.5,
    policy: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Compute order deltas between prior and target positions.

    Returns (orders, stats) where orders are sorted by priority.
    """
    prior_map = {p["ticker"]: p for p in prior_positions}
    target_map = {p["ticker"]: p for p in target_positions}
    all_tickers = sorted(set(prior_map) | set(target_map))

    raw_orders: List[Dict[str, Any]] = []

    for ticker in all_tickers:
        prior = prior_map.get(ticker)
        target = target_map.get(ticker)

        prior_usd = prior.get("target_dollars", 0.0) if prior else 0.0
        target_usd = target.get("target_dollars", 0.0) if target else 0.0

        # Gap-risk cap: enforce ceiling on target for HIGH gap-risk
        ref = target or prior
        if ref and ref.get("gap_risk") == "HIGH" and policy:
            acct = policy.get("account_usd", 500_000)
            cap_usd = acct * gap_risk_cap_pct / 100.0
            target_usd = min(target_usd, cap_usd)

        delta = target_usd - prior_usd

        if abs(delta) < min_trade_usd:
            continue

        action = "BUY" if delta > 0 else "SELL"

        # Classify reason
        if prior_usd <= 0 and target_usd > 0:
            reason = "NEW"
        elif prior_usd > 0 and target_usd <= 0:
            reason = "EXIT"
        elif delta > 0:
            reason = "ADD"
        else:
            reason = "TRIM"

        order = {
            "ticker": ticker,
            "action": action,
            "delta_usd": round(delta, 2),
            "abs_delta_usd": round(abs(delta), 2),
            "prior_usd": round(prior_usd, 2),
            "target_usd": round(target_usd, 2),
            "bucket": ref.get("bucket", "") if ref else "",
            "reason": reason,
            "gap_risk": ref.get("gap_risk", "") if ref else "",
            "price_coverage": ref.get("price_coverage", "") if ref else "",
            "tier": ref.get("tier", "") if ref else "",
        }
        raw_orders.append(order)

    # Enforce max_orders: always include sells, then largest buys
    sells = [o for o in raw_orders if o["action"] == "SELL"]
    buys = [o for o in raw_orders if o["action"] == "BUY"]

    # Sort sells by abs_delta desc, buys by abs_delta desc
    sells.sort(key=lambda o: (-o["abs_delta_usd"], o["ticker"]))
    buys.sort(key=lambda o: (-o["abs_delta_usd"], o["ticker"]))

    if len(sells) + len(buys) > max_orders:
        remaining = max(0, max_orders - len(sells))
        buys = buys[:remaining]

    # Final order: sells first, then buys (deterministic)
    orders = sells + buys

    # Stats
    total_buy = sum(o["abs_delta_usd"] for o in orders if o["action"] == "BUY")
    total_sell = sum(o["abs_delta_usd"] for o in orders if o["action"] == "SELL")

    stats = {
        "n_orders": len(orders),
        "n_buys": sum(1 for o in orders if o["action"] == "BUY"),
        "n_sells": sum(1 for o in orders if o["action"] == "SELL"),
        "gross_trade_usd": round(total_buy + total_sell, 2),
        "net_trade_usd": round(total_buy - total_sell, 2),
        "total_buy_usd": round(total_buy, 2),
        "total_sell_usd": round(total_sell, 2),
        "n_new": sum(1 for o in orders if o["reason"] == "NEW"),
        "n_exit": sum(1 for o in orders if o["reason"] == "EXIT"),
        "n_add": sum(1 for o in orders if o["reason"] == "ADD"),
        "n_trim": sum(1 for o in orders if o["reason"] == "TRIM"),
        "n_filtered_below_min": len(all_tickers) - len(raw_orders),
        "n_truncated_max_orders": max(
            0, len(sells) + len(buys) + (len(raw_orders) - len(sells) - len(buys)) - max_orders
        ),
    }

    return orders, stats


# ---------------------------------------------------------------------------
# Slippage
# ---------------------------------------------------------------------------


def estimate_slippage(
    orders: List[Dict[str, Any]],
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
) -> Dict[str, Any]:
    """Estimate execution cost drag."""
    total_notional = sum(o["abs_delta_usd"] for o in orders)
    est_drag = total_notional * slippage_bps / 10_000
    return {
        "slippage_bps": slippage_bps,
        "gross_notional": round(total_notional, 2),
        "estimated_drag_usd": round(est_drag, 2),
        "drag_pct_of_gross": round(est_drag / total_notional * 100, 4) if total_notional > 0 else 0.0,
    }


# ---------------------------------------------------------------------------
# Safety checks
# ---------------------------------------------------------------------------


def check_buy_safety(
    orders: List[Dict[str, Any]],
    go_nogo_path: Optional[Path] = None,
    *,
    dry_run: bool = False,
) -> List[str]:
    """Return list of warnings/blocks for buy orders."""
    warnings = []

    # Check GO_NOGO
    if go_nogo_path and go_nogo_path.is_file():
        with open(go_nogo_path) as f:
            gng = json.load(f)
        if gng.get("verdict") != "GO" and not dry_run:
            warnings.append(f"GO_NOGO verdict is {gng.get('verdict')} — BUY orders blocked")

    # Check buy-side flags
    for o in orders:
        if o["action"] != "BUY":
            continue
        if o.get("price_coverage") == "MISSING":
            warnings.append(f"BUY {o['ticker']}: missing price coverage")
        if o.get("gap_risk") == "HIGH":
            warnings.append(f"BUY {o['ticker']}: HIGH gap-risk")

    return warnings


# ---------------------------------------------------------------------------
# Receipt (deterministic hashes)
# ---------------------------------------------------------------------------


def build_receipt(
    policy_path: Optional[Path],
    snapshot_path: Optional[Path],
    positions_path: Optional[Path],
    orders_json: bytes,
) -> Dict[str, Any]:
    """Build deterministic receipt with input/output hashes."""
    receipt: Dict[str, Any] = {
        "schema": "execution_receipt.v1",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    if policy_path and policy_path.is_file():
        receipt["policy_hash"] = _sha256_file(policy_path)
    if snapshot_path and snapshot_path.is_file():
        receipt["snapshot_hash"] = _sha256_file(snapshot_path)
    if positions_path and positions_path.is_file():
        receipt["positions_hash"] = _sha256_file(positions_path)

    receipt["orders_hash"] = _sha256_bytes(orders_json)
    return receipt


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------


def write_orders_csv(
    orders: List[Dict[str, Any]],
    path: Path,
    prices: Optional[Dict[str, float]] = None,
) -> Path:
    """Write broker-friendly orders.csv."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=ORDERS_CSV_COLUMNS)
        w.writeheader()
        for o in orders:
            limit = ""
            if prices and o["ticker"] in prices:
                limit = f"{prices[o['ticker']]:.2f}"
            w.writerow(
                {
                    "action": o["action"],
                    "ticker": o["ticker"],
                    "notional_usd": f"{o['abs_delta_usd']:.2f}",
                    "limit_price": limit,
                    "note": o["reason"],
                }
            )
    return path


def write_orders_json(
    orders: List[Dict[str, Any]],
    stats: Dict[str, Any],
    slippage: Dict[str, Any],
    warnings: List[str],
    path: Path,
) -> bytes:
    """Write full orders.json and return serialized bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "schema": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "stats": stats,
        "slippage": slippage,
        "warnings": warnings,
        "orders": orders,
    }
    data = json.dumps(doc, indent=2).encode("utf-8")
    with open(path, "wb") as f:
        f.write(data)
    return data


def write_execution_md(
    orders: List[Dict[str, Any]],
    stats: Dict[str, Any],
    slippage: Dict[str, Any],
    warnings: List[str],
    as_of_date: str,
    path: Path,
    *,
    dry_run: bool = False,
) -> Path:
    """Write human-readable EXECUTION.md checklist."""
    path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = []
    if dry_run:
        lines.append("# [DRY RUN] Weekly Execution Plan")
    else:
        lines.append("# Weekly Execution Plan")
    lines.append("")
    lines.append(f"**Date**: {as_of_date}")
    lines.append(f"**Generated**: {ts}")
    lines.append("")

    # Warnings
    if warnings:
        lines.append("## Warnings")
        lines.append("")
        for w in warnings:
            lines.append(f"- {w}")
        lines.append("")

    # Summary
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **Total orders**: {stats['n_orders']}")
    lines.append(f"- **Buys**: {stats['n_buys']} (${stats['total_buy_usd']:,.0f})")
    lines.append(f"- **Sells**: {stats['n_sells']} (${stats['total_sell_usd']:,.0f})")
    lines.append(f"- **Gross trade**: ${stats['gross_trade_usd']:,.0f}")
    lines.append(f"- **Net trade**: ${stats['net_trade_usd']:+,.0f}")
    lines.append(f"- **Est slippage**: ${slippage['estimated_drag_usd']:,.0f} ({slippage['slippage_bps']} bps)")
    lines.append("")

    # What changed
    lines.append("## What Changed This Week")
    lines.append("")
    lines.append(f"- **New positions**: {stats['n_new']}")
    lines.append(f"- **Exits**: {stats['n_exit']}")
    lines.append(f"- **Adds**: {stats['n_add']}")
    lines.append(f"- **Trims**: {stats['n_trim']}")
    lines.append(f"- **Below min-trade filter**: {stats['n_filtered_below_min']}")
    lines.append("")

    # Order table
    if orders:
        lines.append("## Orders")
        lines.append("")
        lines.append("| # | Action | Ticker | Notional | Bucket | Reason | Flags |")
        lines.append("|---|--------|--------|----------|--------|--------|-------|")
        for i, o in enumerate(orders, 1):
            flags = []
            if o.get("gap_risk") == "HIGH":
                flags.append("GAP")
            if o.get("price_coverage") == "MISSING":
                flags.append("NO_PRICE")
            flag_str = ",".join(flags) or "-"
            lines.append(
                f"| {i} | {o['action']} | {o['ticker']} "
                f"| ${o['abs_delta_usd']:,.0f} "
                f"| {BUCKET_DISPLAY.get(o['bucket'], o['bucket'])} "
                f"| {o['reason']} | {flag_str} |"
            )
        lines.append("")

    # Checklist
    lines.append("## Execution Checklist")
    lines.append("")
    lines.append("- [ ] Confirm GO_NOGO verdict is GO")
    lines.append("- [ ] Review warnings above")
    lines.append("- [ ] Execute SELL orders first")
    lines.append("- [ ] Execute BUY orders")
    lines.append("- [ ] Record fills in fills tracker")
    lines.append("")

    with open(path, "w") as f:
        f.write("\n".join(lines))
    return path


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def build_weekly_orders(
    as_of_date: str,
    *,
    snapshot_root: Path = SNAPSHOTS_ROOT,
    shadow_root: Path = SHADOW_ROOT,
    policy_path: Optional[Path] = None,
    price_path: Path = PRICE_HISTORY_PATH,
    account_usd: Optional[float] = None,
    min_trade_usd: float = DEFAULT_MIN_TRADE_USD,
    max_orders: int = DEFAULT_MAX_ORDERS,
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
    dry_run: bool = False,
    out_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Build executable weekly orders.

    Returns dict with orders, stats, paths.
    """
    # Load policy + build target positions from snapshot
    policy = load_policy(policy_path)
    if account_usd is not None:
        policy["account_usd"] = account_usd

    snap_dir = snapshot_root / as_of_date
    rankings = load_rankings(snap_dir)
    target_data = build_positions(rankings, policy, account_usd)
    target_positions = target_data["positions"]

    # Load prior positions
    positions_dir = shadow_root / "positions"
    prior = load_prior_positions(as_of_date, positions_dir)
    prior_positions = prior[1] if prior else []

    # Gap-risk cap from policy
    gap_cfg = policy.get("gap_risk", {})
    gap_cap_pct = gap_cfg.get("high_cap_pct", 0.5)

    # Compute deltas
    orders, stats = compute_order_deltas(
        prior_positions,
        target_positions,
        min_trade_usd=min_trade_usd,
        max_orders=max_orders,
        gap_risk_cap_pct=gap_cap_pct,
        policy=policy,
    )

    # Slippage estimate
    slippage = estimate_slippage(orders, slippage_bps)

    # Safety checks
    go_nogo_path = shadow_root / "go_nogo" / as_of_date / "GO_NOGO.json"
    warnings = check_buy_safety(orders, go_nogo_path, dry_run=dry_run)

    # Prices for limit reference
    prices = load_price_map(price_path, as_of_date)

    # Write outputs
    if out_dir is None:
        out_dir = shadow_root / "orders" / as_of_date
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = write_orders_csv(orders, out_dir / "orders.csv", prices)
    orders_bytes = write_orders_json(orders, stats, slippage, warnings, out_dir / "orders.json")
    md_path = write_execution_md(
        orders,
        stats,
        slippage,
        warnings,
        as_of_date,
        out_dir / "EXECUTION.md",
        dry_run=dry_run,
    )

    # Receipt
    snapshot_csv = snap_dir / "rankings.csv"
    positions_path = None
    if prior:
        # Find the actual prior file
        for p in positions_dir.iterdir():
            if p.suffix == ".json" and p.stem < as_of_date:
                positions_path = p

    from tools.live_shadow_portfolio import DEFAULT_POLICY_PATH

    actual_policy_path = policy_path or DEFAULT_POLICY_PATH
    receipt = build_receipt(
        actual_policy_path if actual_policy_path.is_file() else None,
        snapshot_csv if snapshot_csv.is_file() else None,
        positions_path,
        orders_bytes,
    )
    receipt["as_of_date"] = as_of_date
    receipt["dry_run"] = dry_run
    receipt_path = out_dir / "receipt.json"
    with open(receipt_path, "w") as f:
        json.dump(receipt, f, indent=2)

    return {
        "as_of_date": as_of_date,
        "stats": stats,
        "slippage": slippage,
        "warnings": warnings,
        "orders": orders,
        "csv_path": str(csv_path),
        "json_path": str(out_dir / "orders.json"),
        "md_path": str(md_path),
        "receipt_path": str(receipt_path),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Build weekly executable orders")
    parser.add_argument("--as-of-date", type=str, required=True)
    parser.add_argument("--snapshot-root", type=str)
    parser.add_argument("--shadow-root", type=str)
    parser.add_argument("--policy", type=str)
    parser.add_argument("--price-history", type=str)
    parser.add_argument("--account-usd", type=float)
    parser.add_argument("--min-trade-usd", type=float, default=DEFAULT_MIN_TRADE_USD)
    parser.add_argument("--max-orders", type=int, default=DEFAULT_MAX_ORDERS)
    parser.add_argument("--slippage-bps", type=float, default=DEFAULT_SLIPPAGE_BPS)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--out-dir", type=str)
    args = parser.parse_args()

    result = build_weekly_orders(
        args.as_of_date,
        snapshot_root=Path(args.snapshot_root) if args.snapshot_root else SNAPSHOTS_ROOT,
        shadow_root=Path(args.shadow_root) if args.shadow_root else SHADOW_ROOT,
        policy_path=Path(args.policy) if args.policy else None,
        price_path=Path(args.price_history) if args.price_history else PRICE_HISTORY_PATH,
        account_usd=args.account_usd,
        min_trade_usd=args.min_trade_usd,
        max_orders=args.max_orders,
        slippage_bps=args.slippage_bps,
        dry_run=args.dry_run,
        out_dir=Path(args.out_dir) if args.out_dir else None,
    )

    stats = result["stats"]
    slip = result["slippage"]
    print(f"Orders for {result['as_of_date']}: {stats['n_orders']} total")
    print(f"  Buys: {stats['n_buys']} (${stats['total_buy_usd']:,.0f})")
    print(f"  Sells: {stats['n_sells']} (${stats['total_sell_usd']:,.0f})")
    print(f"  Gross: ${stats['gross_trade_usd']:,.0f}, Net: ${stats['net_trade_usd']:+,.0f}")
    print(f"  Est slippage: ${slip['estimated_drag_usd']:,.0f} ({slip['slippage_bps']} bps)")
    if result["warnings"]:
        print(f"  Warnings: {len(result['warnings'])}")
    print(f"  CSV: {result['csv_path']}")
    print(f"  Plan: {result['md_path']}")
    print(f"  Receipt: {result['receipt_path']}")

    sys.exit(0)


if __name__ == "__main__":
    main()
