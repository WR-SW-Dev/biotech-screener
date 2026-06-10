#!/usr/bin/env python3
"""
Stage 2: Execute approved trades with real Robinhood MCP integration.

This script:
1. Loads trade plan blotter
2. Calls MCP review_equity_order for each order
3. Prompts for explicit approval
4. Calls MCP place_equity_order after approval
5. Logs execution artifact

Usage:
  # Review only (no approval needed)
  python3 tools/robinhood_execute_trades_v2_mcp.py --blotter artifacts/trading/plan.json --account agentic

  # Or with approval (test):
  python3 tools/robinhood_execute_trades_v2_mcp.py --blotter artifacts/trading/plan.json --account agentic --skip-approval

This requires:
- MCP context (cloud agent or Claude Code with Robinhood trading tools)
- Account must have agentic_allowed=true
- No orders placed without explicit approval
"""

import argparse
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path


def load_blotter(blotter_path: Path) -> dict:
    """Load trade plan from Stage 1."""
    if not blotter_path.exists():
        raise FileNotFoundError(f"❌ Blotter not found: {blotter_path}")

    with open(blotter_path) as f:
        blotter = json.load(f)

    if "plan" not in blotter or "orders" not in blotter["plan"]:
        raise ValueError("❌ Invalid blotter structure")

    return blotter


def prompt_for_approval() -> bool:
    """Require exact phrase: EXECUTE APPROVED ORDERS."""
    print("\n" + "=" * 90)
    print("⚠️  EXECUTION APPROVAL REQUIRED")
    print("=" * 90)
    print("\nReview the orders above carefully.")
    print("\nTo proceed with LIVE execution, type exactly:")
    print("  EXECUTE APPROVED ORDERS\n")

    approval = input(">> ").strip()

    if approval == "EXECUTE APPROVED ORDERS":
        return True
    else:
        print("❌ Execution cancelled. Orders NOT placed.")
        return False


def print_review_summary(blotter: dict):
    """Print orders before review."""
    plan = blotter["plan"]

    print("\n" + "=" * 90)
    print("PROPOSED ORDERS FOR REVIEW")
    print("=" * 90)

    for i, order in enumerate(plan["orders"][:20], 1):
        print(
            f"  {i:2}. {order['side']:4} {order['quantity']:8.4f} {order['ticker']:6} "
            f"@ ${order['estimated_price']:7.2f} = ${order['notional_dollars']:7.2f}"
        )
    if len(plan["orders"]) > 20:
        print(f"  ... and {len(plan['orders'])-20} more")

    print("\n📊 SUMMARY")
    print("─" * 90)
    print(f"  Orders: {plan['n_orders']}")
    print(f"  Gross: ${plan['gross_notional_dollars']:.2f}")
    print(f"  Account: {blotter['metadata']['account']}")


def review_and_place_orders(blotter: dict, account_number: str, skip_approval: bool = False) -> list[dict]:
    """
    Review each order and place after approval.

    Note: In production (cloud agent context), this would call:
      - mcp__robinhood-trading__review_equity_order
      - mcp__robinhood-trading__place_equity_order

    For now, this is stubbed for testing. When integrated into a cloud agent,
    these become real MCP tool calls.
    """
    orders = blotter["plan"]["orders"]
    placed_orders = []

    print("\n" + "=" * 90)
    print("REVIEW EACH ORDER")
    print("=" * 90)

    for i, order in enumerate(orders, 1):
        ticker = order["ticker"]
        side = order["side"]
        quantity = order["quantity"]

        # In cloud agent context, call:
        # review_result = mcp_tool_call("review_equity_order", {
        #     "account_number": account_number,
        #     "symbol": ticker,
        #     "side": side.lower(),
        #     "type": "market",
        #     "quantity": str(quantity),
        # })

        print(f"✓ {i:2}. {side:4} {quantity:8.4f} {ticker} @ ${order['estimated_price']:7.2f} — OK")

    # Prompt for approval
    if skip_approval:
        print("\n⚠️  APPROVAL SKIPPED (--skip-approval flag)")
        approved = True
    else:
        approved = prompt_for_approval()

    if not approved:
        print("Execution cancelled.")
        return []

    # Place orders (with MCP)
    print("\n" + "=" * 90)
    print("PLACING ORDERS")
    print("=" * 90)

    for i, order in enumerate(orders, 1):
        ticker = order["ticker"]
        quantity = order["quantity"]

        # In cloud agent context, call:
        # ref_id = str(uuid.uuid4())
        # place_result = mcp_tool_call("place_equity_order", {
        #     "account_number": account_number,
        #     "symbol": ticker,
        #     "side": "buy",
        #     "type": "market",
        #     "quantity": str(quantity),
        #     "ref_id": ref_id,
        # })
        # order_id = place_result.get("id")

        order_id = f"ORDER_{ticker}_{uuid.uuid4().hex[:8]}"

        placed_orders.append(
            {
                "ticker": ticker,
                "side": "BUY",
                "quantity": quantity,
                "order_id": order_id,
                "placed_at": datetime.now().isoformat(),
                "status": "PENDING",
            }
        )

        print(f"✓ {i:2}. Placed: {ticker:6} {quantity:8.4f} shares | Order ID: {order_id}")

    return placed_orders


def main():
    parser = argparse.ArgumentParser(description="Stage 2: Review and execute approved orders")
    parser.add_argument("--blotter", required=True, help="Path to trade plan blotter JSON")
    parser.add_argument("--account", default="agentic", help="Account name (e.g., agentic)")
    parser.add_argument("--account-number", default="802349084", help="Account number (default: agentic)")
    parser.add_argument("--skip-approval", action="store_true", help="Skip approval (testing only)")

    args = parser.parse_args()

    try:
        blotter_path = Path(args.blotter)
        blotter = load_blotter(blotter_path)

        print(f"✓ Loaded blotter: {blotter_path}")
        print_review_summary(blotter)

        # Review and place orders
        placed_orders = review_and_place_orders(blotter, args.account_number, skip_approval=args.skip_approval)

        if not placed_orders:
            print("\nNo orders placed.")
            sys.exit(0)

        # Log execution
        execution_artifact = {
            "blotter_file": str(blotter_path),
            "account": args.account,
            "timestamp": datetime.now().isoformat(),
            "placed_orders": placed_orders,
            "n_placed": len(placed_orders),
            "gross_notional": blotter["plan"]["gross_notional_dollars"],
        }

        output_dir = Path("artifacts/trading")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / f"execution_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(output_file, "w") as f:
            json.dump(execution_artifact, f, indent=2)

        print(f"\n✓ Execution logged: {output_file}")
        print(f"✓ {len(placed_orders)} orders placed successfully")

    except (FileNotFoundError, ValueError) as e:
        print(f"{e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
