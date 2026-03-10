"""Tests for broker order functionality in tools/build_trade_plan.py.

Validates:
  1. load_last_close — correct last close, missing ticker
  2. compute_broker_orders — integer, fractional, missing price, sell side
  3. write_broker_orders_csv — file written with correct columns
  4. Integration: end-to-end with tmp trade plan
"""

from __future__ import annotations

import csv
import math
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.build_trade_plan import BROKER_ORDER_COLUMNS, compute_broker_orders, load_last_close, write_broker_orders_csv


def _write_price_csv(path: Path, rows: list) -> Path:
    """Helper: write a minimal price_history.csv from list of tuples."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["ticker", "date", "open", "high", "low", "close", "volume"])
        for r in rows:
            writer.writerow(r)
    return path


# ---- load_last_close ----


class TestLoadLastClose:
    def test_load_last_close_happy(self, tmp_path):
        """Returns correct last close for known tickers."""
        csv_path = _write_price_csv(
            tmp_path / "prices.csv",
            [
                ("AAPL", "2026-03-07", 150, 155, 149, 50.25, 1000),
                ("AAPL", "2026-03-08", 152, 158, 151, 51.00, 1200),
                ("GOOG", "2026-03-07", 100, 101, 99, 100.50, 500),
            ],
        )
        result = load_last_close(["AAPL", "GOOG"], csv_path)
        assert result["AAPL"] == 51.00  # latest date wins
        assert result["GOOG"] == 100.50

    def test_load_last_close_missing_ticker(self, tmp_path):
        """Returns empty dict for missing ticker."""
        csv_path = _write_price_csv(
            tmp_path / "prices.csv",
            [("AAPL", "2026-03-08", 50, 51, 49, 50.25, 1000)],
        )
        result = load_last_close(["MISSING"], csv_path)
        assert result == {}


# ---- compute_broker_orders ----


class TestComputeBrokerOrders:
    def test_compute_broker_orders_integer(self):
        """BUY $10k at $50/share -> qty=200 (integer mode, floor division)."""
        trades = [{"ticker": "ABC", "action": "BUY", "delta_usd": 10000, "bucket": "core", "gap_risk": "LOW"}]
        prices = {"ABC": 50.0}
        orders = compute_broker_orders(trades, prices, fractional=False)
        assert len(orders) == 1
        o = orders[0]
        assert o["symbol"] == "ABC"
        assert o["side"] == "BUY"
        assert o["qty"] == 200
        assert o["order_type"] == "LIMIT"
        assert o["limit_price"] == 50.0
        assert o["notional_usd"] == 10000.0

    def test_compute_broker_orders_fractional(self):
        """Fractional mode gives exact ratio (rounded to 4 dp)."""
        trades = [{"ticker": "XYZ", "action": "BUY", "delta_usd": 10000, "bucket": "core", "gap_risk": ""}]
        prices = {"XYZ": 33.33}
        orders = compute_broker_orders(trades, prices, fractional=True)
        o = orders[0]
        expected_qty = round(10000 / 33.33, 4)
        assert o["qty"] == expected_qty
        assert o["order_type"] == "LIMIT"

    def test_compute_broker_orders_missing_price(self):
        """Missing price -> order_type=REVIEW, qty=0."""
        trades = [{"ticker": "NOPX", "action": "BUY", "delta_usd": 5000, "bucket": "satellite"}]
        prices = {}
        orders = compute_broker_orders(trades, prices, fractional=False)
        o = orders[0]
        assert o["order_type"] == "REVIEW"
        assert o["qty"] == 0
        assert o["notes"] == "missing_price"
        assert o["original_delta_usd"] == 5000.0

    def test_compute_broker_orders_sell(self):
        """SELL action -> side=SELL, qty positive."""
        trades = [{"ticker": "DEF", "action": "SELL", "delta_usd": -8000, "bucket": "core", "gap_risk": ""}]
        prices = {"DEF": 40.0}
        orders = compute_broker_orders(trades, prices, fractional=False)
        o = orders[0]
        assert o["side"] == "SELL"
        assert o["qty"] == math.floor(8000 / 40.0)  # 200
        assert o["qty"] > 0
        assert o["order_type"] == "LIMIT"
        assert o["original_delta_usd"] == -8000.0


# ---- write_broker_orders_csv ----


class TestWriteBrokerOrdersCsv:
    def test_write_broker_orders_csv(self, tmp_path):
        """File written, columns correct."""
        orders = [
            {
                "symbol": "AAA",
                "side": "BUY",
                "qty": 100,
                "order_type": "LIMIT",
                "limit_price": 25.0,
                "notional_usd": 2500.0,
                "original_delta_usd": 2500.0,
                "bucket": "core",
                "gap_risk": "LOW",
                "notes": "",
            }
        ]
        out = tmp_path / "orders" / "broker_orders.csv"
        ret = write_broker_orders_csv(orders, out)
        assert ret == out
        assert out.is_file()

        with open(out, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            header = reader.fieldnames

        assert header == BROKER_ORDER_COLUMNS
        assert len(rows) == 1
        assert rows[0]["symbol"] == "AAA"
        assert rows[0]["qty"] == "100"


# ---- Integration ----


class TestBrokerOrdersIntegration:
    def test_broker_orders_integration(self, tmp_path):
        """End-to-end: price CSV -> load_last_close -> compute -> write -> read back."""
        csv_path = _write_price_csv(
            tmp_path / "prices.csv",
            [
                ("IONS", "2026-03-07", 40, 42, 39, 41.0, 300),
                ("IONS", "2026-03-08", 41, 43, 40, 42.5, 400),
                ("ARWR", "2026-03-08", 20, 22, 19, 21.0, 600),
            ],
        )

        # Load prices
        prices = load_last_close(["IONS", "ARWR", "MISSING"], csv_path)
        assert "IONS" in prices
        assert "ARWR" in prices
        assert "MISSING" not in prices

        # Build trades
        trades = [
            {"ticker": "IONS", "action": "BUY", "delta_usd": 5000, "bucket": "binary_91_180", "gap_risk": "HIGH"},
            {"ticker": "ARWR", "action": "SELL", "delta_usd": -3000, "bucket": "core", "gap_risk": ""},
            {"ticker": "MISSING", "action": "BUY", "delta_usd": 2000, "bucket": "satellite"},
        ]

        # Compute orders
        orders = compute_broker_orders(trades, prices, fractional=False)
        assert len(orders) == 3

        ions_order = orders[0]
        assert ions_order["symbol"] == "IONS"
        assert ions_order["side"] == "BUY"
        assert ions_order["qty"] == math.floor(5000 / 42.5)  # 117
        assert ions_order["order_type"] == "LIMIT"

        arwr_order = orders[1]
        assert arwr_order["side"] == "SELL"
        assert arwr_order["qty"] == math.floor(3000 / 21.0)  # 142

        missing_order = orders[2]
        assert missing_order["order_type"] == "REVIEW"
        assert missing_order["qty"] == 0

        # Write and read back
        out_path = tmp_path / "out" / "broker_orders.csv"
        write_broker_orders_csv(orders, out_path)
        assert out_path.is_file()

        with open(out_path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 3
        symbols = [r["symbol"] for r in rows]
        assert symbols == ["IONS", "ARWR", "MISSING"]
