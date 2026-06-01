#!/usr/bin/env python3
"""
Tests for Path C drawdown vs XBI metric computation.
"""

import csv
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from tools.compute_path_c_drawdown import compute_drawdown_vs_xbi


@pytest.fixture
def temp_price_history():
    """Fixture: Create a temporary price history CSV for testing."""
    with TemporaryDirectory() as tmpdir:
        csv_path = Path(tmpdir) / "price_history.csv"

        # Create minimal price history with known portfolio + XBI
        # Scenario: portfolio outperforms XBI by 2pp
        data = [
            ["ticker", "date", "close"],
            # Baseline: 2026-05-29
            ["DNTH", "2026-05-29", "100.00"],
            ["NRIX", "2026-05-29", "100.00"],
            ["XBI", "2026-05-29", "100.00"],
            # Latest: assume +3pp return
            ["DNTH", "2026-05-31", "101.50"],
            ["NRIX", "2026-05-31", "101.50"],
            ["XBI", "2026-05-31", "101.00"],  # XBI only +1pp
        ]

        with open(csv_path, "w") as f:
            writer = csv.writer(f)
            writer.writerows(data)

        yield csv_path


def test_drawdown_pass(temp_price_history):
    """Test: Portfolio outperforms XBI, status is PASS."""
    portfolio = {"DNTH": 50.0, "NRIX": 50.0}  # 50/50 split
    result = compute_drawdown_vs_xbi(
        portfolio,
        snapshot_date="2026-05-31",
        baseline_date="2026-05-29",
        price_history_path=temp_price_history,
    )

    # Portfolio: +1.5pp, XBI: +1.0pp, drawdown = +0.5pp (PASS)
    assert result["status"] == "PASS"
    assert result["pp"] is not None
    assert result["pp"] > 0  # Portfolio outperforms


def test_drawdown_hard_exit(temp_price_history):
    """Test: Portfolio underperforms XBI by >2pp, status is FAIL_HARD_EXIT."""
    with TemporaryDirectory() as tmpdir:
        csv_path = Path(tmpdir) / "price_history.csv"

        # Scenario: portfolio underperforms by 3pp
        data = [
            ["ticker", "date", "close"],
            ["DNTH", "2026-05-29", "100.00"],
            ["NRIX", "2026-05-29", "100.00"],
            ["XBI", "2026-05-29", "100.00"],
            # Portfolio +1pp, XBI +4pp → drawdown = -3pp
            ["DNTH", "2026-05-31", "100.50"],
            ["NRIX", "2026-05-31", "100.50"],
            ["XBI", "2026-05-31", "104.00"],
        ]

        with open(csv_path, "w") as f:
            writer = csv.writer(f)
            writer.writerows(data)

        portfolio = {"DNTH": 50.0, "NRIX": 50.0}
        result = compute_drawdown_vs_xbi(
            portfolio,
            snapshot_date="2026-05-31",
            baseline_date="2026-05-29",
            price_history_path=csv_path,
        )

        assert result["status"] == "FAIL_HARD_EXIT"
        assert result["pp"] is not None
        assert result["pp"] <= -2.00


def test_drawdown_data_unavailable_missing_ticker():
    """Test: Missing ticker in price history, status is DATA_UNAVAILABLE."""
    with TemporaryDirectory() as tmpdir:
        csv_path = Path(tmpdir) / "price_history.csv"

        # Missing NRIX
        data = [
            ["ticker", "date", "close"],
            ["DNTH", "2026-05-29", "100.00"],
            ["DNTH", "2026-05-31", "101.00"],
            ["XBI", "2026-05-29", "100.00"],
            ["XBI", "2026-05-31", "101.00"],
        ]

        with open(csv_path, "w") as f:
            writer = csv.writer(f)
            writer.writerows(data)

        portfolio = {"DNTH": 50.0, "NRIX": 50.0}
        result = compute_drawdown_vs_xbi(
            portfolio,
            snapshot_date="2026-05-31",
            baseline_date="2026-05-29",
            price_history_path=csv_path,
        )

        assert result["status"] == "DATA_UNAVAILABLE"
        assert result["pp"] is None


def test_drawdown_data_unavailable_missing_xbi():
    """Test: Missing XBI in price history, status is DATA_UNAVAILABLE."""
    with TemporaryDirectory() as tmpdir:
        csv_path = Path(tmpdir) / "price_history.csv"

        # Missing XBI
        data = [
            ["ticker", "date", "close"],
            ["DNTH", "2026-05-29", "100.00"],
            ["DNTH", "2026-05-31", "101.00"],
            ["NRIX", "2026-05-29", "100.00"],
            ["NRIX", "2026-05-31", "101.00"],
        ]

        with open(csv_path, "w") as f:
            writer = csv.writer(f)
            writer.writerows(data)

        portfolio = {"DNTH": 50.0, "NRIX": 50.0}
        result = compute_drawdown_vs_xbi(
            portfolio,
            snapshot_date="2026-05-31",
            baseline_date="2026-05-29",
            price_history_path=csv_path,
        )

        assert result["status"] == "DATA_UNAVAILABLE"
        assert result["pp"] is None


def test_drawdown_data_unavailable_missing_file():
    """Test: Price history file does not exist, status is DATA_UNAVAILABLE."""
    portfolio = {"DNTH": 50.0, "NRIX": 50.0}
    result = compute_drawdown_vs_xbi(
        portfolio,
        snapshot_date="2026-05-31",
        baseline_date="2026-05-29",
        price_history_path=Path("/nonexistent/path.csv"),
    )

    assert result["status"] == "DATA_UNAVAILABLE"
    assert result["pp"] is None
    assert result["latest_date"] is None
