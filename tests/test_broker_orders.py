"""Tests for broker-ready trade plan generation.

Validates:
  1. load_last_close — correct last close, missing ticker
  2. compute_broker_orders — integer, fractional, missing price, sell side
  3. write_broker_orders_csv — file written with correct columns
  4. Integration: end-to-end with tmp trade plan
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.build_trade_plan import BROKER_ORDER_COLUMNS, compute_broker_orders, load_last_close, write_broker_orders_csv


def _write_price_csv(tmp_path: Path, rows: list) -> Path:
    p = tmp_path / "price_history.csv"
    with open(p, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["ticker", "date", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        writer.writerows(rows)
    return p


class TestLoadLastClose:
    def test_happy(self, tmp_path):
        csv_path = _write_price_csv(
            tmp_path,
            [
                {
                    "ticker": "AAPL",
                    "date": "2026-03-07",
                    "open": "50",
                    "high": "51",
                    "low": "49",
                    "close": "50.25",
                    "volume": "1000",
                },
                {
                    "ticker": "AAPL",
                    "date": "2026-03-08",
                    "open": "50",
                    "high": "52",
                    "low": "49",
                    "close": "51.00",
                    "volume": "1200",
                },
                {
                    "ticker": "GOOG",
                    "date": "2026-03-07",
                    "open": "100",
                    "high": "101",
                    "low": "99",
                    "close": "100.50",
                    "volume": "500",
                },
            ],
        )
        result = load_last_close(["AAPL", "GOOG"], csv_path)
        assert result["AAPL"] == 51.00  # latest date
        assert result["GOOG"] == 100.50

    def test_missing_ticker(self, tmp_path):
        csv_path = _write_price_csv(
            tmp_path,
            [
                {
                    "ticker": "AAPL",
                    "date": "2026-03-07",
                    "open": "50",
                    "high": "51",
                    "low": "49",
                    "close": "50.25",
                    "volume": "1000",
                },
            ],
        )
        result = load_last_close(["AAPL", "MISSING"], csv_path)
        assert "AAPL" in result
        assert "MISSING" not in result


class TestComputeBrokerOrders:
    def test_integer_shares(self):
        trades = [{"ticker": "AAPL", "action": "BUY", "delta_usd": 10000, "bucket": "binary_91_180", "gap_risk": ""}]
        prices = {"AAPL": 50.0}
        orders = compute_broker_orders(trades, prices, fractional=False)
        assert len(orders) == 1
        assert orders[0]["qty"] == 200  # floor(10000/50)
        assert orders[0]["side"] == "BUY"
        assert orders[0]["order_type"] == "LIMIT"
        assert orders[0]["limit_price"] == 50.0

    def test_fractional_shares(self):
        trades = [{"ticker": "AAPL", "action": "BUY", "delta_usd": 10000, "bucket": "binary_91_180", "gap_risk": ""}]
        prices = {"AAPL": 33.33}
        orders = compute_broker_orders(trades, prices, fractional=True)
        assert orders[0]["qty"] == round(10000 / 33.33, 4)

    def test_missing_price(self):
        trades = [{"ticker": "AAPL", "action": "BUY", "delta_usd": 10000, "bucket": "binary_91_180", "gap_risk": ""}]
        prices = {}
        orders = compute_broker_orders(trades, prices, fractional=False)
        assert orders[0]["qty"] == 0
        assert orders[0]["order_type"] == "REVIEW"
        assert orders[0]["notes"] == "missing_price"

    def test_sell_side(self):
        trades = [{"ticker": "AAPL", "action": "SELL", "delta_usd": -5000, "bucket": "less_binary", "gap_risk": ""}]
        prices = {"AAPL": 25.0}
        orders = compute_broker_orders(trades, prices, fractional=False)
        assert orders[0]["side"] == "SELL"
        assert orders[0]["qty"] == 200  # floor(5000/25)


class TestWriteBrokerOrdersCsv:
    def test_file_written(self, tmp_path):
        orders = [
            {
                "symbol": "AAPL",
                "side": "BUY",
                "qty": 200,
                "order_type": "LIMIT",
                "limit_price": 50.0,
                "notional_usd": 10000.0,
                "original_delta_usd": 10000.0,
                "bucket": "binary_91_180",
                "gap_risk": "",
                "notes": "",
            },
        ]
        out_path = tmp_path / "broker_orders.csv"
        result = write_broker_orders_csv(orders, out_path)
        assert result.is_file()
        with open(result) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 1
        assert set(reader.fieldnames) == set(BROKER_ORDER_COLUMNS)
        assert rows[0]["symbol"] == "AAPL"


class TestBrokerOrdersIntegration:
    def test_end_to_end(self, tmp_path):
        # Create price CSV
        csv_path = _write_price_csv(
            tmp_path,
            [
                {
                    "ticker": "AAPL",
                    "date": "2026-03-08",
                    "open": "50",
                    "high": "52",
                    "low": "49",
                    "close": "50.0",
                    "volume": "1000",
                },
                {
                    "ticker": "GOOG",
                    "date": "2026-03-08",
                    "open": "100",
                    "high": "105",
                    "low": "99",
                    "close": "100.0",
                    "volume": "500",
                },
            ],
        )
        trades = [
            {"ticker": "AAPL", "action": "BUY", "delta_usd": 10000, "bucket": "binary_91_180", "gap_risk": ""},
            {"ticker": "GOOG", "action": "BUY", "delta_usd": 5000, "bucket": "less_binary", "gap_risk": "HIGH"},
            {"ticker": "MISS", "action": "BUY", "delta_usd": 3000, "bucket": "binary_31_90", "gap_risk": ""},
        ]
        prices = load_last_close(["AAPL", "GOOG", "MISS"], csv_path)
        orders = compute_broker_orders(trades, prices, fractional=False)
        out_path = write_broker_orders_csv(orders, tmp_path / "broker_orders.csv")

        assert out_path.is_file()
        assert len(orders) == 3
        assert orders[0]["qty"] == 200  # 10000/50
        assert orders[1]["qty"] == 50  # 5000/100
        assert orders[2]["order_type"] == "REVIEW"
