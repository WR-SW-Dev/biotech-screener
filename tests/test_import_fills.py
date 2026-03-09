"""Tests for broker fill import pipeline.

Validates:
  1. detect_broker_format — IBKR and generic detection
  2. normalize_broker_csv — side mapping, qty/price extraction
  3. match_fills_to_trades — correct matching, partial, unmatched
  4. write_matched_fills — output matches FILLS_COLUMNS
  5. import_fills integration
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.import_fills import (
    detect_broker_format,
    import_fills,
    match_fills_to_trades,
    normalize_broker_csv,
    write_matched_fills,
)
from tools.record_fills import FILLS_COLUMNS


def _write_csv(path: Path, fieldnames: list, rows: list) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return path


class TestDetectBrokerFormat:
    def test_ibkr(self, tmp_path):
        p = _write_csv(
            tmp_path / "ibkr.csv",
            ["Symbol", "Buy/Sell", "Quantity", "Price", "Date/Time", "Commission"],
            [
                {
                    "Symbol": "AAPL",
                    "Buy/Sell": "BOT",
                    "Quantity": "100",
                    "Price": "50.0",
                    "Date/Time": "2026-03-07",
                    "Commission": "1.0",
                }
            ],
        )
        assert detect_broker_format(p) == "ibkr"

    def test_generic(self, tmp_path):
        p = _write_csv(
            tmp_path / "generic.csv",
            ["symbol", "side", "qty", "price", "date"],
            [{"symbol": "AAPL", "side": "BUY", "qty": "100", "price": "50.0", "date": "2026-03-07"}],
        )
        assert detect_broker_format(p) == "generic"


class TestNormalizeBrokerCsv:
    def test_ibkr_normalization(self, tmp_path):
        p = _write_csv(
            tmp_path / "ibkr.csv",
            ["Symbol", "Buy/Sell", "Quantity", "Price", "Date/Time"],
            [
                {
                    "Symbol": "AAPL",
                    "Buy/Sell": "BOT",
                    "Quantity": "100",
                    "Price": "50.25",
                    "Date/Time": "2026-03-07 10:30",
                },
                {
                    "Symbol": "GOOG",
                    "Buy/Sell": "SLD",
                    "Quantity": "50",
                    "Price": "100.50",
                    "Date/Time": "2026-03-07 11:00",
                },
            ],
        )
        fills = normalize_broker_csv(p, broker="ibkr")
        assert len(fills) == 2
        assert fills[0]["side"] == "BUY"
        assert fills[0]["qty"] == 100.0
        assert fills[0]["price"] == 50.25
        assert fills[1]["side"] == "SELL"

    def test_generic_normalization(self, tmp_path):
        p = _write_csv(
            tmp_path / "generic.csv",
            ["symbol", "side", "qty", "price", "date"],
            [{"symbol": "AAPL", "side": "BUY", "qty": "100", "price": "50.0", "date": "2026-03-07"}],
        )
        fills = normalize_broker_csv(p, broker="generic")
        assert len(fills) == 1
        assert fills[0]["symbol"] == "AAPL"
        assert fills[0]["side"] == "BUY"


class TestMatchFillsToTrades:
    def _make_trades_csv(self, tmp_path, trades):
        return _write_csv(
            tmp_path / "trade_plan.csv",
            [
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
            ],
            trades,
        )

    def test_correct_matching(self, tmp_path):
        trades_csv = self._make_trades_csv(
            tmp_path,
            [
                {
                    "ticker": "AAPL",
                    "action": "BUY",
                    "delta_usd": "10000",
                    "target_usd": "10000",
                    "prior_usd": "0",
                    "bucket": "binary_91_180",
                    "tier": "A",
                    "catalyst_days": "120",
                    "gap_risk": "",
                    "reason": "NEW_ENTRY",
                },
            ],
        )
        fills = [{"symbol": "AAPL", "side": "BUY", "qty": 200, "price": 50.0, "date": "2026-03-07"}]
        matched = match_fills_to_trades(fills, trades_csv)
        assert len(matched) == 1
        assert matched[0]["status"] == "FILLED"
        assert matched[0]["fill_usd"] == "10000.0"

    def test_partial_fill(self, tmp_path):
        trades_csv = self._make_trades_csv(
            tmp_path,
            [
                {
                    "ticker": "AAPL",
                    "action": "BUY",
                    "delta_usd": "10000",
                    "target_usd": "10000",
                    "prior_usd": "0",
                    "bucket": "binary_91_180",
                    "tier": "A",
                    "catalyst_days": "120",
                    "gap_risk": "",
                    "reason": "NEW_ENTRY",
                },
            ],
        )
        fills = [{"symbol": "AAPL", "side": "BUY", "qty": 50, "price": 50.0, "date": "2026-03-07"}]
        matched = match_fills_to_trades(fills, trades_csv)
        assert matched[0]["status"] == "PARTIAL"
        assert matched[0]["fill_usd"] == "2500.0"

    def test_unmatched_fill(self, tmp_path):
        trades_csv = self._make_trades_csv(
            tmp_path,
            [
                {
                    "ticker": "AAPL",
                    "action": "BUY",
                    "delta_usd": "10000",
                    "target_usd": "10000",
                    "prior_usd": "0",
                    "bucket": "binary_91_180",
                    "tier": "A",
                    "catalyst_days": "120",
                    "gap_risk": "",
                    "reason": "NEW_ENTRY",
                },
            ],
        )
        fills = [
            {"symbol": "AAPL", "side": "BUY", "qty": 200, "price": 50.0, "date": "2026-03-07"},
            {"symbol": "GOOG", "side": "BUY", "qty": 30, "price": 100.0, "date": "2026-03-07"},
        ]
        matched = match_fills_to_trades(fills, trades_csv)
        assert len(matched) == 2
        # GOOG is unmatched → SKIPPED
        goog = [m for m in matched if m["ticker"] == "GOOG"][0]
        assert goog["status"] == "SKIPPED"


class TestWriteMatchedFills:
    def test_output_format(self, tmp_path):
        matched = [
            {
                "ticker": "AAPL",
                "action": "BUY",
                "target_usd": "10000",
                "fill_price": "50.0",
                "fill_shares": "200",
                "fill_usd": "10000.0",
                "slippage_bps": "0.0",
                "fill_date": "2026-03-07",
                "status": "FILLED",
            }
        ]
        out_path = write_matched_fills(matched, tmp_path / "fills.csv")
        assert out_path.is_file()
        with open(out_path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert set(reader.fieldnames) == set(FILLS_COLUMNS)
        assert len(rows) == 1


class TestImportFillsIntegration:
    def test_end_to_end(self, tmp_path):
        # Create trade plan
        trade_dir = tmp_path / "trades" / "2026-03-07"
        _write_csv(
            trade_dir / "trade_plan.csv",
            [
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
            ],
            [
                {
                    "ticker": "AAPL",
                    "action": "BUY",
                    "delta_usd": "10000",
                    "target_usd": "10000",
                    "prior_usd": "0",
                    "bucket": "binary_91_180",
                    "tier": "A",
                    "catalyst_days": "120",
                    "gap_risk": "",
                    "reason": "NEW_ENTRY",
                },
                {
                    "ticker": "GOOG",
                    "action": "SELL",
                    "delta_usd": "-5000",
                    "target_usd": "0",
                    "prior_usd": "5000",
                    "bucket": "less_binary",
                    "tier": "B",
                    "catalyst_days": "",
                    "gap_risk": "",
                    "reason": "EXIT",
                },
            ],
        )
        # Create broker CSV (generic)
        broker_csv = _write_csv(
            tmp_path / "broker_fills.csv",
            ["symbol", "side", "qty", "price", "date"],
            [
                {"symbol": "AAPL", "side": "BUY", "qty": "198", "price": "50.50", "date": "2026-03-07"},
                {"symbol": "GOOG", "side": "SELL", "qty": "50", "price": "100.0", "date": "2026-03-07"},
            ],
        )
        out_path = import_fills(
            broker_csv,
            "2026-03-07",
            broker="generic",
            trades_root=tmp_path / "trades",
        )
        assert out_path.is_file()
        with open(out_path) as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 2
        aapl = [r for r in rows if r["ticker"] == "AAPL"][0]
        assert aapl["status"] == "FILLED"  # 198*50.50 = 9999 ≈ 10000 (>=90%)


class TestFillPriceUsedInPerformance:
    """Validate that fill prices can be loaded for cost basis override."""

    def test_fills_csv_readable(self, tmp_path):
        matched = [
            {
                "ticker": "AAPL",
                "action": "BUY",
                "target_usd": "10000",
                "fill_price": "50.25",
                "fill_shares": "199",
                "fill_usd": "9999.75",
                "slippage_bps": "-0.25",
                "fill_date": "2026-03-07",
                "status": "FILLED",
            }
        ]
        fills_path = write_matched_fills(matched, tmp_path / "fills.csv")
        # Verify we can load and parse fill prices
        with open(fills_path) as f:
            rows = list(csv.DictReader(f))
        assert float(rows[0]["fill_price"]) == 50.25
