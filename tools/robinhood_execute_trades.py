#!/usr/bin/env python3
"""
Second-stage trade execution: review + approve + place orders.

Workflow:
1. Load trade plan blotter (from robinhood_top30_trade_plan.py)
2. Call review_equity_order for each order
3. Print review results
4. Require explicit "EXECUTE APPROVED ORDERS" to proceed
5. Place orders via place_equity_order

This is a REVIEW-FIRST, APPROVAL-REQUIRED system.
No orders are placed unless explicitly approved.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


# Note: In production, these would be actual Robinhood MCP tool calls
# For now, they're stubs to demonstrate the flow.
def review_equity_order_stub(order: dict, account: str) -> dict:
    """Stub: would call Robinhood review_equity_order MCP tool."""
    return {
        "ticker": order["ticker"],
        "side": order["side"],
        "quantity": order["quantity"],
        "review_status": "OK",  # In production: real review result
        "estimated_fill_time": "0.5s",
        "potential_slippage_bps": 5,
    }


def place_equity_order_stub(order: dict, account: str) -> dict:
    """Stub: would call Robinhood place_equity_order MCP tool."""
    return {
        "ticker": order["ticker"],
        "order_id": f"ORDER_{order['ticker']}_{datetime.now().timestamp()}",
        "status": "PENDING",
        "placed_at": datetime.now().isoformat(),
    }


def load_blotter(blotter_path: Path) -> dict:
    """Load trade plan blotter from artifacts."""
    if not blotter_path.exists():
        raise FileNotFoundError(f"❌ Blotter not found: {blotter_path}")

    with open(blotter_path) as f:
        blotter = json.load(f)

    # Validate blotter structure
    if "plan" not in blotter or "orders" not in blotter["plan"]:
        raise ValueError("❌ Invalid blotter structure")

    return blotter


def review_orders(blotter: dict, account: str) -> list[dict]:
    """Review all orders via review_equity_order."""
    orders = blotter["plan"]["orders"]
    reviews = []

    print("\n" + "=" * 90)
    print("ORDER REVIEW")
    print("=" * 90)

    for i, order in enumerate(orders, 1):
        review = review_equity_order_stub(order, account)
        reviews.append(review)

        status_icon = "✓" if review["review_status"] == "OK" else "⚠️"
        print(
            f"{status_icon} {i:2}. {order['side']:4} {order['quantity']:8.3f} {order['ticker']:6} "
            f"@ ${order['estimated_price']:7.2f} = ${order['notional_dollars']:7.2f}"
        )
        print(f"      Review: {review['review_status']} | Slippage: {review['potential_slippage_bps']} bps")

    return reviews


def place_orders(blotter: dict, reviews: list[dict], account: str) -> dict:
    """Place all reviewed orders."""
    orders = blotter["plan"]["orders"]

    # Verify review count matches
    if len(reviews) != len(orders):
        raise ValueError("❌ Review count mismatch")

    # Check all reviews passed
    failed = [r for r in reviews if r["review_status"] != "OK"]
    if failed:
        raise ValueError(f"❌ {len(failed)} orders failed review. Cannot execute.")

    placed_orders = []

    print("\n" + "=" * 90)
    print("PLACING ORDERS")
    print("=" * 90)

    for i, order in enumerate(orders, 1):
        placed = place_equity_order_stub(order, account)
        placed_orders.append(placed)

        print(
            f"✓ {i:2}. Placed: {order['side']:4} {order['quantity']:8.3f} {order['ticker']:6} "
            f"| Order ID: {placed['order_id']}"
        )

    return {
        "placed_orders": placed_orders,
        "n_placed": len(placed_orders),
        "placed_at": datetime.now().isoformat(),
    }


def prompt_for_approval() -> bool:
    """Require explicit user approval to execute."""
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


def main():
    parser = argparse.ArgumentParser(description="Second-stage: Review and execute approved trade plan.")
    parser.add_argument(
        "--blotter",
        required=True,
        help="Path to trade plan blotter JSON (from robinhood_top30_trade_plan.py)",
    )
    parser.add_argument(
        "--account",
        default="agentic",
        help="Robinhood account to trade",
    )
    parser.add_argument(
        "--skip-approval",
        action="store_true",
        help="Skip approval prompt (for testing only - DEFAULT: require approval)",
    )

    args = parser.parse_args()

    try:
        # Load blotter
        blotter_path = Path(args.blotter)
        blotter = load_blotter(blotter_path)

        print(f"✓ Loaded blotter: {blotter_path}")
        print(f"  Snapshot: {blotter['metadata']['snapshot_date']}")
        print(f"  Orders: {blotter['plan']['n_orders']}")
        print(f"  Gross: ${blotter['plan']['gross_notional_dollars']:.2f}")

        # Review all orders
        reviews = review_orders(blotter, args.account)

        # Prompt for approval
        if args.skip_approval:
            print("\n⚠️  APPROVAL SKIPPED (--skip-approval flag)")
            approved = True
        else:
            approved = prompt_for_approval()

        if not approved:
            sys.exit(0)

        # Place orders
        execution = place_orders(blotter, reviews, args.account)

        # Write execution artifact
        execution_artifact = {
            "blotter_file": str(blotter_path),
            "execution": execution,
            "reviews": reviews,
            "account": args.account,
            "timestamp": datetime.now().isoformat(),
        }

        output_dir = Path("artifacts/trading")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / f"execution_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(output_file, "w") as f:
            json.dump(execution_artifact, f, indent=2)

        print(f"\n✓ Execution logged: {output_file}")
        print(f"✓ {execution['n_placed']} orders placed successfully")

    except (FileNotFoundError, ValueError) as e:
        print(f"{e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
