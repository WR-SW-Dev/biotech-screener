#!/usr/bin/env python3
"""Tests for broker fill import pipeline.

Covers:
- Broker format detection (IBKR vs generic)
- CSV normalization (side mapping, field extraction)
- Fill-to-trade matching (FILLED, PARTIAL, SKIPPED)
- Output writing with correct FILLS_COLUMNS
- End-to-end integration
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.import_fills import (
    IBKR_SIDE_MAP,
    detect_broker_format,
    import_fills,
    match_fills_to_trades,
    normalize_broker_csv,
    write_matched_fills,
)
from tools.record_fills import FILLS_COLUMNS

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TRADE_PLAN_HEADERS = [
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
]


def _write_csv(path: Path, headers: list, rows: list) -> Path:
    """Write a CSV file from a list of lists (header + value rows)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(headers)
        for row in rows:
            w.writerow(row)
    return path


def _write_trade_plan(path: Path, rows: list) -> Path:
    """Write trade_plan.csv from a list of dicts."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=TRADE_PLAN_HEADERS)
        w.writeheader()
        w.writerows(rows)
    return path


def _trade_row(ticker, action, delta_usd, **overrides):
    """Build a single trade-plan dict with sensible defaults."""
    row = {
        "ticker": ticker,
        "action": action,
        "delta_usd": str(delta_usd),
        "target_usd": str(abs(delta_usd)),
        "prior_usd": "0",
        "bucket": "binary_91_180",
        "tier": "A",
        "catalyst_days": "120",
        "gap_risk": "",
        "reason": "test",
    }
    row.update(overrides)
    return row


# ---------------------------------------------------------------------------
# 1. detect_broker_format — IBKR
# ---------------------------------------------------------------------------


def test_detect_broker_ibkr(tmp_path):
    csv_path = _write_csv(
        tmp_path / "ibkr.csv",
        ["Symbol", "Buy/Sell", "Quantity", "Price", "Date/Time"],
        [["AAPL", "BOT", "100", "150.00", "2026-03-06 10:00:00"]],
    )
    assert detect_broker_format(csv_path) == "ibkr"


# ---------------------------------------------------------------------------
# 2. detect_broker_format — generic
# ---------------------------------------------------------------------------


def test_detect_broker_generic(tmp_path):
    csv_path = _write_csv(
        tmp_path / "generic.csv",
        ["symbol", "side", "qty", "price", "date"],
        [["AAPL", "BUY", "100", "150.00", "2026-03-06"]],
    )
    assert detect_broker_format(csv_path) == "generic"


# ---------------------------------------------------------------------------
# 3. normalize_broker_csv — IBKR side mapping
# ---------------------------------------------------------------------------


def test_normalize_ibkr(tmp_path):
    csv_path = _write_csv(
        tmp_path / "ibkr.csv",
        ["Symbol", "Buy/Sell", "Quantity", "Price", "Date/Time"],
        [
            ["AAPL", "BOT", "100", "150.25", "2026-03-06 10:00:00"],
            ["GILD", "SLD", "50", "82.50", "2026-03-06 11:00:00"],
        ],
    )
    fills = normalize_broker_csv(csv_path, broker="ibkr")

    assert len(fills) == 2

    assert fills[0]["symbol"] == "AAPL"
    assert fills[0]["side"] == IBKR_SIDE_MAP["BOT"]  # "BUY"
    assert float(fills[0]["qty"]) == 100.0
    assert float(fills[0]["price"]) == 150.25

    assert fills[1]["symbol"] == "GILD"
    assert fills[1]["side"] == IBKR_SIDE_MAP["SLD"]  # "SELL"
    assert float(fills[1]["qty"]) == 50.0
    assert float(fills[1]["price"]) == 82.50


# ---------------------------------------------------------------------------
# 4. normalize_broker_csv — generic passthrough
# ---------------------------------------------------------------------------


def test_normalize_generic(tmp_path):
    csv_path = _write_csv(
        tmp_path / "generic.csv",
        ["symbol", "side", "qty", "price", "date"],
        [["MRNA", "BUY", "200", "45.00", "2026-03-06"]],
    )
    fills = normalize_broker_csv(csv_path, broker="generic")

    assert len(fills) == 1
    assert fills[0]["symbol"] == "MRNA"
    assert fills[0]["side"] == "BUY"
    assert float(fills[0]["qty"]) == 200.0
    assert float(fills[0]["price"]) == 45.00
    assert fills[0]["date"] == "2026-03-06"


# ---------------------------------------------------------------------------
# 5. match_fills_to_trades — full match (status=FILLED, fill_usd correct)
# ---------------------------------------------------------------------------


def test_match_fills_to_trades(tmp_path):
    trades_csv = _write_trade_plan(
        tmp_path / "trade_plan.csv",
        [
            _trade_row("AAPL", "BUY", 15000),
        ],
    )
    fills = [
        {"symbol": "AAPL", "side": "BUY", "qty": 100, "price": 150.00, "date": "2026-03-06"},
    ]
    matched = match_fills_to_trades(fills, trades_csv)

    assert len(matched) == 1
    row = matched[0]
    assert row["ticker"] == "AAPL"
    assert row["action"] == "BUY"
    assert float(row["fill_usd"]) == 15000.0
    assert row["status"] == "FILLED"


# ---------------------------------------------------------------------------
# 6. match_fills_to_trades — partial fill
# ---------------------------------------------------------------------------


def test_match_fills_partial(tmp_path):
    trades_csv = _write_trade_plan(
        tmp_path / "trade_plan.csv",
        [
            _trade_row("GILD", "BUY", 20000),
        ],
    )
    # Fill only $4,125 of a $20,000 target — clearly partial
    fills = [
        {"symbol": "GILD", "side": "BUY", "qty": 50, "price": 82.50, "date": "2026-03-06"},
    ]
    matched = match_fills_to_trades(fills, trades_csv)

    assert len(matched) == 1
    assert matched[0]["status"] == "PARTIAL"


# ---------------------------------------------------------------------------
# 7. match_fills_to_trades — unmatched trade → SKIPPED
# ---------------------------------------------------------------------------


def test_match_fills_unmatched(tmp_path):
    trades_csv = _write_trade_plan(
        tmp_path / "trade_plan.csv",
        [
            _trade_row("MRNA", "BUY", 10000),
        ],
    )
    # No fills at all
    matched = match_fills_to_trades([], trades_csv)

    assert len(matched) == 1
    assert matched[0]["status"] == "SKIPPED"
    assert matched[0]["ticker"] == "MRNA"


# ---------------------------------------------------------------------------
# 8. write_matched_fills — output file exists with correct columns
# ---------------------------------------------------------------------------


def test_write_matched_fills(tmp_path):
    matched = [
        {
            "ticker": "AAPL",
            "action": "BUY",
            "target_usd": "15000",
            "fill_price": "150.00",
            "fill_shares": "100",
            "fill_usd": "15000.00",
            "slippage_bps": "0.0",
            "fill_date": "2026-03-06",
            "status": "FILLED",
        },
    ]
    out_path = tmp_path / "fills.csv"
    write_matched_fills(matched, out_path)

    assert out_path.is_file()

    with open(out_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert list(reader.fieldnames) == FILLS_COLUMNS
    assert len(rows) == 1
    assert rows[0]["ticker"] == "AAPL"
    assert rows[0]["status"] == "FILLED"


# ---------------------------------------------------------------------------
# 9. import_fills — end-to-end integration
# ---------------------------------------------------------------------------


def test_import_fills_integration(tmp_path):
    trade_date = "2026-03-06"
    trades_root = tmp_path / "trades"
    trade_dir = trades_root / trade_date
    trade_dir.mkdir(parents=True)

    _write_trade_plan(
        trade_dir / "trade_plan.csv",
        [
            _trade_row("AAPL", "BUY", 15000),
            _trade_row("GILD", "SELL", -8000, prior_usd="8000", target_usd="0", bucket="exit", reason="trim"),
        ],
    )

    # Broker CSV in IBKR format
    broker_csv = _write_csv(
        tmp_path / "ibkr_export.csv",
        ["Symbol", "Buy/Sell", "Quantity", "Price", "Date/Time"],
        [
            ["AAPL", "BOT", "100", "150.00", "2026-03-06 10:00:00"],
            ["GILD", "SLD", "100", "80.00", "2026-03-06 11:00:00"],
        ],
    )

    import_fills(
        broker_csv,
        trade_date,
        broker="auto",
        trades_root=trades_root,
    )

    fills_csv = trade_dir / "fills.csv"
    assert fills_csv.is_file()

    with open(fills_csv, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    tickers = [r["ticker"] for r in rows]
    assert "AAPL" in tickers
    assert "GILD" in tickers
    assert len(rows) == 2
