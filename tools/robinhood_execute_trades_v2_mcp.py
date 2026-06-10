#!/usr/bin/env python3
"""
Stage 2: STUB SIMULATOR for trade execution approval flow.

⚠️  THIS SCRIPT USES STUB ORDER IDS. NO REAL ORDERS ARE PLACED.

For live Robinhood trading, use a Claude Code agent with direct MCP calls:
  - mcp__robinhood-trading__review_equity_order
  - mcp__robinhood-trading__place_equity_order

This stub simulator:
1. Loads trade plan blotter
2. Reviews orders (stub: always "OK")
3. Prompts for explicit approval
4. Simulates order placement with fake order IDs
5. Logs simulation artifact with execution_mode: "STUB_SIMULATION"

Usage:
  python3 tools/robinhood_execute_trades_v2_mcp.py --blotter artifacts/trading/plan.json --account agentic

Note:
  --skip-approval is allowed for testing only.
  --live-mcp flag not yet implemented (fails closed).
  Real execution requires Claude Code agent orchestration.
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

    # Simulate order placement (stub, no real MCP calls)
    print("\n" + "=" * 90)
    print("SIMULATING ORDER PLACEMENT (STUB EXECUTION)")
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

        stub_order_id = f"STUB_ORDER_{ticker}_{uuid.uuid4().hex[:8]}"

        placed_orders.append(
            {
                "ticker": ticker,
                "side": "BUY",
                "quantity": quantity,
                "order_id": stub_order_id,
                "placed_at": datetime.now().isoformat(),
                "status": "SIMULATED",
                "note": "Stub order ID only — no real order placed",
            }
        )

        print(f"◯ {i:2}. Simulated: {ticker:6} {quantity:8.4f} shares | Stub ID: {stub_order_id}")

    return placed_orders


def main():
    parser = argparse.ArgumentParser(description="Stage 2: STUB simulator for trade execution approval flow")
    parser.add_argument("--blotter", required=True, help="Path to trade plan blotter JSON")
    parser.add_argument("--account", default="agentic", help="Account name (e.g., agentic)")
    parser.add_argument("--account-number", default="802349084", help="Account number (default: agentic)")
    parser.add_argument("--skip-approval", action="store_true", help="Skip approval (testing only)")
    parser.add_argument("--live-mcp", action="store_true", help="(not yet implemented) real Robinhood execution")

    args = parser.parse_args()

    # Fail closed: --live-mcp not implemented yet
    if args.live_mcp:
        print("❌ LIVE_MCP execution is not implemented in this script.")
        print("   For real Robinhood trading, use a Claude Code agent with direct MCP calls:")
        print("   - mcp__robinhood-trading__review_equity_order")
        print("   - mcp__robinhood-trading__place_equity_order")
        sys.exit(1)

    # Prevent dangerous combo
    if args.skip_approval and args.live_mcp:
        print("❌ FATAL: --skip-approval + --live-mcp is not allowed.")
        print("   Real trading requires explicit human approval.")
        sys.exit(1)

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

        # Log execution artifact (stub simulation)
        execution_artifact = {
            "execution_mode": "STUB_SIMULATION",
            "live_orders_placed": False,
            "note": "This is a stub simulator. No real orders were placed. See execution_mode field.",
            "blotter_file": str(blotter_path),
            "account": args.account,
            "timestamp": datetime.now().isoformat(),
            "simulated_orders": placed_orders,
            "n_simulated": len(placed_orders),
            "gross_notional": blotter["plan"]["gross_notional_dollars"],
        }

        output_dir = Path("artifacts/trading")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / f"execution_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(output_file, "w") as f:
            json.dump(execution_artifact, f, indent=2)

        print(f"\n✓ Simulation logged: {output_file}")
        print(f"✓ {len(placed_orders)} stub orders simulated successfully")
        print("\n⚠️  REMINDER: This is stub simulation only. No real orders placed.")
        print("   For live execution, use a Claude Code agent with direct Robinhood MCP integration.")

    except (FileNotFoundError, ValueError) as e:
        print(f"{e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
