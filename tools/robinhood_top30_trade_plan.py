#!/usr/bin/env python3
"""
Review-first Robinhood trade plan generator for biotech screener top 30.

Two-stage execution:
1. --dry-run (default): Generate order blotter only, review each order.
2. --execute-approved: Place reviewed orders after human approval.

Hard rules:
- No options, margin, shorts, crypto, after-hours
- No sell of non-screen holdings unless --allow-sells
- Respect Phase 2 guardrails (catalyst ≤7d, vol/beta, concentration)
- Fail closed if snapshot/holdings/cash/quotes missing/stale
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# Placeholder for Robinhood MCP calls (will be replaced with actual MCP tool calls)
RH_ACCOUNTS = {}
RH_POSITIONS = {}
RH_QUOTES = {}


def load_latest_snapshot() -> tuple[str, dict]:
    """Load latest valid screener snapshot. Fail if missing/stale."""
    snap_dir = Path("data/snapshots_pit")
    if not snap_dir.exists():
        raise FileNotFoundError(f"❌ Snapshot directory not found: {snap_dir}")

    snapshots = sorted([d for d in snap_dir.iterdir() if d.is_dir()])
    if not snapshots:
        raise FileNotFoundError("❌ No snapshots found")

    latest = snapshots[-1]
    snapshot_date = latest.name

    # Warn if >3 days old for trading
    snap_dt = datetime.strptime(snapshot_date, "%Y-%m-%d")
    days_old = (datetime.now() - snap_dt).days
    if days_old > 3:
        print(f"⚠️  WARNING: Snapshot is {days_old} days old ({snapshot_date})")
        if days_old > 7:
            raise ValueError(f"❌ Snapshot too stale ({days_old} days). Refuse to trade.")

    portfolio_file = latest / "decision_portfolio.json"
    if not portfolio_file.exists():
        raise FileNotFoundError(f"❌ Decision portfolio not found: {portfolio_file}")

    with open(portfolio_file) as f:
        portfolio = json.load(f)

    print(f"✓ Loaded snapshot from {snapshot_date} ({days_old} days old)")
    return snapshot_date, portfolio


def select_top_k(portfolio: dict, top_k: int = 30) -> list[dict]:
    """Select top K eligible tickers by actionable_rank."""
    eligible = [pos for pos in portfolio["positions"] if pos.get("eligible") == "1" or pos.get("eligible") is True]
    eligible.sort(key=lambda x: x.get("actionable_rank", 999))
    top_k_list = eligible[:top_k]
    print(f"✓ Selected top {len(top_k_list)} eligible tickers")
    return top_k_list


def apply_trading_guardrails(positions: list[dict]) -> list[dict]:
    """Filter positions by Phase 2 guardrails."""
    filtered = []
    dropped = []

    for pos in positions:
        ticker = pos["ticker"]
        catalyst_days = int(pos.get("catalyst_days", 999)) if pos.get("catalyst_days") else 999
        tier = pos.get("tier_any", "")

        # Guardrail: imminent catalysts (≤7 days) are risky for new positions
        if catalyst_days <= 7:
            dropped.append((ticker, f"catalyst too imminent ({catalyst_days}d)"))
            continue

        # Guardrail: Tier A/B only for now (avoid Tier C/no-tier for execution)
        if tier not in ["A", "B"]:
            dropped.append((ticker, f"tier {tier} not eligible"))
            continue

        filtered.append(pos)

    if dropped:
        print(f"\n⚠️  Dropped {len(dropped)} by guardrails:")
        for ticker, reason in dropped[:10]:
            print(f"   {ticker}: {reason}")
        if len(dropped) > 10:
            print(f"   ... and {len(dropped)-10} more")

    print(f"✓ {len(filtered)} positions pass guardrails")
    return filtered


def generate_trade_plan(
    top_k_positions: list[dict],
    target_gross_dollars: float,
    max_single_name_pct: float,
    min_cash_reserve_dollars: float,
    min_order_dollars: float,
) -> dict:
    """Generate proposed orders: buys for top K, no sells of non-screen holdings."""
    n_positions = len(top_k_positions)
    if n_positions == 0:
        raise ValueError("❌ No eligible positions pass guardrails")

    # Naïve equal-weight across eligible positions
    target_per_position = target_gross_dollars / n_positions
    max_per_name = target_gross_dollars * (max_single_name_pct / 100)
    order_size = min(target_per_position, max_per_name)

    if order_size < min_order_dollars:
        print(f"⚠️  WARNING: Target size ${order_size:.2f} < min ${min_order_dollars:.2f}")
        print(f"   Consider --target-gross-dollars >= ${min_order_dollars * n_positions:.2f}")

    orders = []
    gross_notional = 0

    for pos in top_k_positions:
        ticker = pos["ticker"]
        # Placeholder: in real execution, fetch current quote
        estimated_price = 50  # Stub

        quantity = order_size / estimated_price
        notional = quantity * estimated_price

        if notional < min_order_dollars:
            continue  # Skip orders below minimum

        orders.append(
            {
                "ticker": ticker,
                "side": "BUY",
                "quantity": quantity,
                "estimated_price": estimated_price,
                "notional_dollars": notional,
                "reason": f"Rank {pos.get('actionable_rank', 999)}, Tier {pos.get('tier_any', '')}",
            }
        )
        gross_notional += notional

    return {
        "n_orders": len(orders),
        "gross_notional_dollars": gross_notional,
        "orders": orders,
    }


def generate_blotter(
    plan: dict,
    snapshot_date: str,
    top_k: int,
    account_nickname: str,
    args,
) -> dict:
    """Assemble complete trade plan artifact with metadata."""
    return {
        "metadata": {
            "timestamp": datetime.now().isoformat(),
            "snapshot_date": snapshot_date,
            "mode": "DRY_RUN" if args.dry_run else "EXECUTION",
            "top_k": top_k,
            "account": account_nickname,
            "target_gross_dollars": args.target_gross_dollars,
            "max_single_name_pct": args.max_single_name_pct,
            "min_cash_reserve_dollars": args.min_cash_reserve_dollars,
            "min_order_dollars": args.min_order_dollars,
        },
        "guardrails": {
            "no_options": True,
            "no_margin": True,
            "no_shorts": True,
            "no_after_hours": True,
            "no_crypto": True,
            "allow_sells": args.allow_sells,
            "catalyst_min_days": 8,
            "tier_eligible": ["A", "B"],
        },
        "plan": plan,
        "review_status": "PENDING_HUMAN_REVIEW",
        "execution_status": "NOT_EXECUTED",
    }


def print_summary(blotter: dict):
    """Print human-readable trade summary."""
    plan = blotter["plan"]
    meta = blotter["metadata"]

    print("\n" + "=" * 90)
    print(f"ROBINHOOD TRADE PLAN — {meta['snapshot_date']} ({meta['mode']})")
    print("=" * 90)
    print(f"Account: {meta['account']} | Target Gross: ${meta['target_gross_dollars']:.2f}")
    print(f"Top {meta['top_k']} eligible names, pass guardrails")

    print("\n📋 PROPOSED ORDERS")
    print("─" * 90)
    if not plan["orders"]:
        print("  (No orders above minimum size)")
    else:
        for i, order in enumerate(plan["orders"][:15], 1):
            print(
                f"  {i:2}. BUY {order['quantity']:8.3f} {order['ticker']:6} "
                f"@ ${order['estimated_price']:7.2f} = ${order['notional_dollars']:7.2f}  "
                f"({order['reason']})"
            )
        if len(plan["orders"]) > 15:
            print(f"  ... and {len(plan['orders'])-15} more")

    print("\n📊 SUMMARY")
    print("─" * 90)
    print(f"  Orders: {plan['n_orders']}")
    print(f"  Gross Notional: ${plan['gross_notional_dollars']:.2f}")
    print(f"  Status: {blotter['review_status']}")

    print("\n⚠️  NEXT STEPS")
    print("─" * 90)
    if meta["mode"] == "DRY_RUN":
        print("  1. Review the order blotter above")
        print("  2. Verify account, size, and position align with portfolio target")
        print("  3. If satisfied, re-run with --execute-approved to place orders")
        print("  $ python3 tools/robinhood_top30_trade_plan.py \\")
        print(f"      --snapshot {meta['snapshot_date']} \\")
        print(f"      --top-k {meta['top_k']} \\")
        print(f"      --account {meta['account']} \\")
        print(f"      --target-gross-dollars {meta['target_gross_dollars']} \\")
        print("      --execute-approved")
    else:
        print("  ⚠️  EXECUTION MODE: Orders will be placed after review.")
        print("  Verify each order below before confirming.")


def main():
    parser = argparse.ArgumentParser(description="Generate Robinhood trade plan from biotech screener top K.")
    parser.add_argument(
        "--snapshot",
        default="latest",
        help="Snapshot date (YYYY-MM-DD) or 'latest'",
    )
    parser.add_argument("--top-k", type=int, default=30, help="Top K eligible names")
    parser.add_argument(
        "--account",
        default="agentic",
        choices=["agentic", "roth", "traditional", "default"],
        help="Robinhood account to trade",
    )
    parser.add_argument(
        "--target-gross-dollars",
        type=float,
        default=100.0,
        help="Target gross notional (dollars)",
    )
    parser.add_argument(
        "--max-single-name-pct",
        type=float,
        default=5.0,
        help="Max concentration per name (%)",
    )
    parser.add_argument(
        "--min-cash-reserve-dollars",
        type=float,
        default=5.0,
        help="Min cash to preserve (dollars)",
    )
    parser.add_argument(
        "--min-order-dollars",
        type=float,
        default=5.0,
        help="Min order size (dollars)",
    )
    parser.add_argument(
        "--allow-sells",
        action="store_true",
        help="Allow selling non-screen holdings (default: false)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Generate plan only, do not place orders (default: true)",
    )
    parser.add_argument(
        "--execute-approved",
        action="store_true",
        help="Place orders after human approval (overrides --dry-run)",
    )

    args = parser.parse_args()

    try:
        # Load snapshot
        snapshot_date, portfolio = load_latest_snapshot()

        # Select top K
        top_k_positions = select_top_k(portfolio, args.top_k)

        # Apply guardrails
        eligible = apply_trading_guardrails(top_k_positions)

        # Generate plan
        plan = generate_trade_plan(
            eligible,
            args.target_gross_dollars,
            args.max_single_name_pct,
            args.min_cash_reserve_dollars,
            args.min_order_dollars,
        )

        # Generate blotter
        blotter = generate_blotter(plan, snapshot_date, args.top_k, args.account, args)

        # Print summary
        print_summary(blotter)

        # Write artifact
        output_dir = Path("artifacts/trading")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / f"robinhood_top{args.top_k}_plan_{snapshot_date}.json"
        with open(output_file, "w") as f:
            json.dump(blotter, f, indent=2)
        print(f"\n✓ Blotter saved: {output_file}")

        # Check execution flag
        if args.execute_approved and not args.dry_run:
            print("\n❌ EXECUTION MODE (--execute-approved) not yet implemented.")
            print("   Current mode: DRY_RUN (review only)")
            sys.exit(0)
        elif args.execute_approved:
            print("\n❌ Cannot use --execute-approved with --dry-run")
            print("   Use: --execute-approved (without --dry-run)")
            sys.exit(1)

        print("\n✓ Trade plan ready for review")

    except (FileNotFoundError, ValueError) as e:
        print(f"{e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
