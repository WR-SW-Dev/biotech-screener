"""Tests for build_weekly_orders.py."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.build_weekly_orders import (
    SCHEMA_VERSION,
    build_receipt,
    check_buy_safety,
    compute_order_deltas,
    estimate_slippage,
    write_execution_md,
    write_orders_csv,
    write_orders_json,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _pos(ticker, dollars, bucket="binary_91_180", gap_risk="", price_coverage="OK", tier="A"):
    return {
        "ticker": ticker,
        "target_dollars": dollars,
        "bucket": bucket,
        "gap_risk": gap_risk,
        "price_coverage": price_coverage,
        "tier": tier,
    }


# ---------------------------------------------------------------------------
# compute_order_deltas
# ---------------------------------------------------------------------------


class TestComputeOrderDeltas:
    def test_new_positions_are_buys(self):
        prior = []
        target = [_pos("AAPL", 5000), _pos("GOOG", 3000)]
        orders, stats = compute_order_deltas(prior, target)
        assert stats["n_buys"] == 2
        assert stats["n_sells"] == 0
        assert all(o["action"] == "BUY" for o in orders)
        assert all(o["reason"] == "NEW" for o in orders)

    def test_exits_are_sells(self):
        prior = [_pos("AAPL", 5000), _pos("GOOG", 3000)]
        target = []
        orders, stats = compute_order_deltas(prior, target)
        assert stats["n_sells"] == 2
        assert stats["n_buys"] == 0
        assert all(o["action"] == "SELL" for o in orders)
        assert all(o["reason"] == "EXIT" for o in orders)

    def test_add_and_trim(self):
        prior = [_pos("AAPL", 5000), _pos("GOOG", 3000)]
        target = [_pos("AAPL", 7000), _pos("GOOG", 1000)]
        orders, stats = compute_order_deltas(prior, target)
        aapl = [o for o in orders if o["ticker"] == "AAPL"][0]
        goog = [o for o in orders if o["ticker"] == "GOOG"][0]
        assert aapl["action"] == "BUY"
        assert aapl["reason"] == "ADD"
        assert goog["action"] == "SELL"
        assert goog["reason"] == "TRIM"

    def test_min_trade_filter(self):
        prior = [_pos("AAPL", 5000)]
        target = [_pos("AAPL", 5100)]  # delta = 100 < 250 min
        orders, stats = compute_order_deltas(prior, target, min_trade_usd=250)
        assert len(orders) == 0
        assert stats["n_filtered_below_min"] == 1

    def test_deterministic_ordering(self):
        """Sells first, then buys; within each, by abs_delta desc then ticker."""
        prior = [_pos("AAA", 5000), _pos("BBB", 3000)]
        target = [_pos("AAA", 2000), _pos("BBB", 1000), _pos("CCC", 4000), _pos("DDD", 2000)]
        orders, stats = compute_order_deltas(prior, target)
        actions = [o["action"] for o in orders]
        # Sells should come first
        sell_idx = [i for i, a in enumerate(actions) if a == "SELL"]
        buy_idx = [i for i, a in enumerate(actions) if a == "BUY"]
        if sell_idx and buy_idx:
            assert max(sell_idx) < min(buy_idx)

    def test_max_orders_keeps_sells(self):
        """When truncating, all sells are kept, buys are cut."""
        prior = [_pos(f"S{i}", 5000) for i in range(5)]  # 5 exits
        target = [_pos(f"B{i}", 3000) for i in range(10)]  # 10 new buys
        orders, stats = compute_order_deltas(prior, target, max_orders=8)
        sells = [o for o in orders if o["action"] == "SELL"]
        buys = [o for o in orders if o["action"] == "BUY"]
        assert len(sells) == 5  # All sells kept
        assert len(buys) == 3  # 8 - 5 = 3 buys kept
        assert len(orders) == 8

    def test_gap_risk_cap(self):
        """HIGH gap-risk positions get capped."""
        policy = {"account_usd": 100_000}
        prior = []
        target = [_pos("RISKY", 10000, gap_risk="HIGH")]
        orders, _ = compute_order_deltas(prior, target, gap_risk_cap_pct=0.5, policy=policy)
        assert len(orders) == 1
        # cap = 100000 * 0.5 / 100 = 500 (target capped from 10000 to 500)
        assert orders[0]["target_usd"] == 500.0
        assert orders[0]["abs_delta_usd"] == 500.0


# ---------------------------------------------------------------------------
# Slippage
# ---------------------------------------------------------------------------


class TestSlippage:
    def test_slippage_math(self):
        orders = [
            {"abs_delta_usd": 10000, "action": "BUY"},
            {"abs_delta_usd": 5000, "action": "SELL"},
        ]
        slip = estimate_slippage(orders, slippage_bps=25)
        assert slip["gross_notional"] == 15000
        assert slip["estimated_drag_usd"] == 37.50  # 15000 * 25 / 10000
        assert slip["slippage_bps"] == 25

    def test_zero_orders(self):
        slip = estimate_slippage([], slippage_bps=25)
        assert slip["estimated_drag_usd"] == 0
        assert slip["drag_pct_of_gross"] == 0


# ---------------------------------------------------------------------------
# Safety checks
# ---------------------------------------------------------------------------


class TestBuySafety:
    def test_nogo_blocks_buys(self, tmp_path):
        gng_path = tmp_path / "GO_NOGO.json"
        with open(gng_path, "w") as f:
            json.dump({"verdict": "NOGO"}, f)
        orders = [{"action": "BUY", "ticker": "AAPL", "price_coverage": "OK", "gap_risk": ""}]
        warnings = check_buy_safety(orders, gng_path, dry_run=False)
        assert any("blocked" in w.lower() for w in warnings)

    def test_nogo_ok_in_dry_run(self, tmp_path):
        gng_path = tmp_path / "GO_NOGO.json"
        with open(gng_path, "w") as f:
            json.dump({"verdict": "NOGO"}, f)
        orders = [{"action": "BUY", "ticker": "AAPL", "price_coverage": "OK", "gap_risk": ""}]
        warnings = check_buy_safety(orders, gng_path, dry_run=True)
        assert not any("blocked" in w.lower() for w in warnings)

    def test_missing_price_flagged(self):
        orders = [{"action": "BUY", "ticker": "AAPL", "price_coverage": "MISSING", "gap_risk": ""}]
        warnings = check_buy_safety(orders, None)
        assert any("missing price" in w.lower() for w in warnings)

    def test_go_no_warnings(self, tmp_path):
        gng_path = tmp_path / "GO_NOGO.json"
        with open(gng_path, "w") as f:
            json.dump({"verdict": "GO"}, f)
        orders = [{"action": "BUY", "ticker": "AAPL", "price_coverage": "OK", "gap_risk": ""}]
        warnings = check_buy_safety(orders, gng_path, dry_run=False)
        assert len(warnings) == 0


# ---------------------------------------------------------------------------
# Receipt
# ---------------------------------------------------------------------------


class TestReceipt:
    def test_receipt_has_orders_hash(self, tmp_path):
        receipt = build_receipt(None, None, None, b'{"orders": []}')
        assert "orders_hash" in receipt
        assert len(receipt["orders_hash"]) == 16

    def test_receipt_stable(self, tmp_path):
        data = b'{"orders": [{"ticker": "AAPL"}]}'
        r1 = build_receipt(None, None, None, data)
        r2 = build_receipt(None, None, None, data)
        assert r1["orders_hash"] == r2["orders_hash"]

    def test_receipt_includes_file_hashes(self, tmp_path):
        policy = tmp_path / "policy.json"
        policy.write_text('{"account_usd": 500000}')
        receipt = build_receipt(policy, None, None, b"[]")
        assert "policy_hash" in receipt


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------


class TestWriters:
    def test_csv_output(self, tmp_path):
        orders = [
            {"ticker": "AAPL", "action": "BUY", "abs_delta_usd": 5000, "reason": "NEW"},
            {"ticker": "GOOG", "action": "SELL", "abs_delta_usd": 3000, "reason": "EXIT"},
        ]
        path = write_orders_csv(orders, tmp_path / "orders.csv", {"AAPL": 150.0})
        with open(path) as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 2
        assert rows[0]["action"] == "BUY"
        assert rows[0]["limit_price"] == "150.00"
        assert rows[1]["limit_price"] == ""  # no price for GOOG

    def test_json_output(self, tmp_path):
        orders = [{"ticker": "AAPL", "action": "BUY", "abs_delta_usd": 5000}]
        stats = {
            "n_orders": 1,
            "n_buys": 1,
            "n_sells": 0,
            "gross_trade_usd": 5000,
            "net_trade_usd": 5000,
            "total_buy_usd": 5000,
            "total_sell_usd": 0,
            "n_new": 1,
            "n_exit": 0,
            "n_add": 0,
            "n_trim": 0,
            "n_filtered_below_min": 0,
            "n_truncated_max_orders": 0,
        }
        slippage = {"slippage_bps": 25, "gross_notional": 5000, "estimated_drag_usd": 12.5, "drag_pct_of_gross": 0.25}
        data = write_orders_json(orders, stats, slippage, [], tmp_path / "orders.json")
        doc = json.loads(data)
        assert doc["schema"] == SCHEMA_VERSION
        assert len(doc["orders"]) == 1

    def test_execution_md(self, tmp_path):
        orders = [
            {
                "ticker": "AAPL",
                "action": "BUY",
                "abs_delta_usd": 5000,
                "bucket": "binary_91_180",
                "reason": "NEW",
                "gap_risk": "",
                "price_coverage": "OK",
            }
        ]
        stats = {
            "n_orders": 1,
            "n_buys": 1,
            "n_sells": 0,
            "gross_trade_usd": 5000,
            "net_trade_usd": 5000,
            "total_buy_usd": 5000,
            "total_sell_usd": 0,
            "n_new": 1,
            "n_exit": 0,
            "n_add": 0,
            "n_trim": 0,
            "n_filtered_below_min": 0,
            "n_truncated_max_orders": 0,
        }
        slippage = {"slippage_bps": 25, "gross_notional": 5000, "estimated_drag_usd": 12.5, "drag_pct_of_gross": 0.25}
        path = write_execution_md(orders, stats, slippage, [], "2026-03-08", tmp_path / "EXECUTION.md")
        text = path.read_text()
        assert "Weekly Execution Plan" in text
        assert "AAPL" in text
        assert "Checklist" in text

    def test_dry_run_banner(self, tmp_path):
        path = write_execution_md(
            [],
            {
                "n_orders": 0,
                "n_buys": 0,
                "n_sells": 0,
                "gross_trade_usd": 0,
                "net_trade_usd": 0,
                "total_buy_usd": 0,
                "total_sell_usd": 0,
                "n_new": 0,
                "n_exit": 0,
                "n_add": 0,
                "n_trim": 0,
                "n_filtered_below_min": 0,
                "n_truncated_max_orders": 0,
            },
            {"slippage_bps": 25, "gross_notional": 0, "estimated_drag_usd": 0, "drag_pct_of_gross": 0},
            [],
            "2026-03-08",
            tmp_path / "EXECUTION.md",
            dry_run=True,
        )
        text = path.read_text()
        assert "DRY RUN" in text
