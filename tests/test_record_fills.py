"""Tests for record_fills.py."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.record_fills import (
    apply_fills,
    compute_execution_quality,
    compute_slippage_bps,
    generate_fill_template,
    mark_all_filled,
    record_fills,
    write_fill_summary,
)


def _write_trades_csv(path: Path, trades: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = [
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
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(trades)


def _read_fills(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------------------
# Slippage math
# ---------------------------------------------------------------------------


class TestSlippage:
    def test_zero_slippage(self):
        assert compute_slippage_bps(5000, 5000) == 0.0

    def test_positive_slippage(self):
        # Paid 5050 for 5000 target = +100 bps
        assert compute_slippage_bps(5000, 5050) == 100.0

    def test_negative_slippage(self):
        # Paid 4950 for 5000 target = -100 bps (better execution)
        assert compute_slippage_bps(5000, 4950) == -100.0

    def test_zero_target(self):
        assert compute_slippage_bps(0, 100) == 0.0


# ---------------------------------------------------------------------------
# Template generation
# ---------------------------------------------------------------------------


class TestGenerateTemplate:
    def test_creates_pending_rows(self, tmp_path):
        trades_csv = tmp_path / "trades" / "trades.csv"
        _write_trades_csv(
            trades_csv,
            [
                {
                    "ticker": "AAPL",
                    "action": "BUY",
                    "delta_usd": "5000",
                    "target_usd": "5000",
                    "prior_usd": "0",
                    "bucket": "binary_91_180",
                    "tier": "A",
                    "catalyst_days": "100",
                    "gap_risk": "",
                    "reason": "NEW_ENTRY",
                },
                {
                    "ticker": "GOOG",
                    "action": "SELL",
                    "delta_usd": "-3000",
                    "target_usd": "0",
                    "prior_usd": "3000",
                    "bucket": "less_binary",
                    "tier": "B",
                    "catalyst_days": "",
                    "gap_risk": "",
                    "reason": "EXIT",
                },
            ],
        )
        fills_csv = tmp_path / "trades" / "fills.csv"
        generate_fill_template(trades_csv, fills_csv)

        fills = _read_fills(fills_csv)
        assert len(fills) == 2
        assert all(f["status"] == "PENDING" for f in fills)
        assert fills[0]["ticker"] == "AAPL"
        assert fills[0]["target_usd"] == "5000"
        assert fills[0]["fill_price"] == ""

    def test_missing_trades_raises(self, tmp_path):
        import pytest

        with pytest.raises(FileNotFoundError):
            generate_fill_template(tmp_path / "nope.csv", tmp_path / "fills.csv")


# ---------------------------------------------------------------------------
# Apply fills
# ---------------------------------------------------------------------------


class TestApplyFills:
    def test_merges_fill_data(self, tmp_path):
        trades_csv = tmp_path / "trades.csv"
        _write_trades_csv(
            trades_csv,
            [
                {
                    "ticker": "AAPL",
                    "action": "BUY",
                    "delta_usd": "5000",
                    "target_usd": "5000",
                    "prior_usd": "0",
                    "bucket": "b",
                    "tier": "A",
                    "catalyst_days": "",
                    "gap_risk": "",
                    "reason": "NEW_ENTRY",
                },
            ],
        )
        fills_csv = tmp_path / "fills.csv"
        generate_fill_template(trades_csv, fills_csv)

        # Create fills input
        input_csv = tmp_path / "input.csv"
        with open(input_csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["ticker", "fill_price", "fill_shares", "status"])
            w.writeheader()
            w.writerow({"ticker": "AAPL", "fill_price": "150.0", "fill_shares": "33", "status": "FILLED"})

        apply_fills(fills_csv, input_csv)
        fills = _read_fills(fills_csv)
        assert fills[0]["status"] == "FILLED"
        assert fills[0]["fill_price"] == "150.0"
        assert fills[0]["fill_shares"] == "33"
        assert float(fills[0]["fill_usd"]) == 4950.0
        # slippage: (4950/5000 - 1) * 10000 = -100 bps
        assert float(fills[0]["slippage_bps"]) == -100.0


# ---------------------------------------------------------------------------
# Mark all filled
# ---------------------------------------------------------------------------


class TestMarkAllFilled:
    def test_sets_all_to_filled(self, tmp_path):
        trades_csv = tmp_path / "trades.csv"
        _write_trades_csv(
            trades_csv,
            [
                {
                    "ticker": "AAPL",
                    "action": "BUY",
                    "delta_usd": "5000",
                    "target_usd": "5000",
                    "prior_usd": "0",
                    "bucket": "b",
                    "tier": "A",
                    "catalyst_days": "",
                    "gap_risk": "",
                    "reason": "NEW_ENTRY",
                },
                {
                    "ticker": "GOOG",
                    "action": "BUY",
                    "delta_usd": "3000",
                    "target_usd": "3000",
                    "prior_usd": "0",
                    "bucket": "b",
                    "tier": "B",
                    "catalyst_days": "",
                    "gap_risk": "",
                    "reason": "NEW_ENTRY",
                },
            ],
        )
        fills_csv = tmp_path / "fills.csv"
        generate_fill_template(trades_csv, fills_csv)
        mark_all_filled(fills_csv, fill_date="2026-03-06")

        fills = _read_fills(fills_csv)
        assert all(f["status"] == "FILLED" for f in fills)
        assert all(f["slippage_bps"] == "0.0" for f in fills)
        assert all(f["fill_date"] == "2026-03-06" for f in fills)
        assert float(fills[0]["fill_usd"]) == 5000.0


# ---------------------------------------------------------------------------
# Execution quality
# ---------------------------------------------------------------------------


class TestExecutionQuality:
    def test_computes_metrics(self, tmp_path):
        fills_csv = tmp_path / "fills.csv"
        with open(fills_csv, "w", newline="") as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    "ticker",
                    "action",
                    "target_usd",
                    "fill_price",
                    "fill_shares",
                    "fill_usd",
                    "slippage_bps",
                    "fill_date",
                    "status",
                ],
            )
            w.writeheader()
            w.writerow(
                {
                    "ticker": "AAPL",
                    "action": "BUY",
                    "target_usd": "5000",
                    "fill_price": "150",
                    "fill_shares": "33",
                    "fill_usd": "4950",
                    "slippage_bps": "-100",
                    "fill_date": "2026-03-06",
                    "status": "FILLED",
                }
            )
            w.writerow(
                {
                    "ticker": "GOOG",
                    "action": "BUY",
                    "target_usd": "3000",
                    "fill_price": "",
                    "fill_shares": "",
                    "fill_usd": "",
                    "slippage_bps": "",
                    "fill_date": "",
                    "status": "SKIPPED",
                }
            )

        q = compute_execution_quality(fills_csv)
        assert q["total"] == 2
        assert q["n_filled"] == 1
        assert q["fill_rate"] == 0.5
        assert q["mean_slippage_bps"] == -100.0

    def test_empty_fills(self, tmp_path):
        fills_csv = tmp_path / "fills.csv"
        with open(fills_csv, "w", newline="") as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    "ticker",
                    "action",
                    "target_usd",
                    "fill_price",
                    "fill_shares",
                    "fill_usd",
                    "slippage_bps",
                    "fill_date",
                    "status",
                ],
            )
            w.writeheader()
        q = compute_execution_quality(fills_csv)
        assert q["total"] == 0
        assert q["fill_rate"] == 0.0

    def test_median_even_count(self, tmp_path):
        """Median with even number of fills should average the two middle values."""
        fills_csv = tmp_path / "fills.csv"
        fields = [
            "ticker",
            "action",
            "target_usd",
            "fill_price",
            "fill_shares",
            "fill_usd",
            "slippage_bps",
            "fill_date",
            "status",
        ]
        with open(fills_csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            # 4 fills with slippages: 10, 20, 30, 40 → median = (20+30)/2 = 25
            for slip in [10, 20, 30, 40]:
                w.writerow(
                    {
                        "ticker": f"T{slip}",
                        "action": "BUY",
                        "target_usd": "1000",
                        "fill_price": "10",
                        "fill_shares": "100",
                        "fill_usd": "1000",
                        "slippage_bps": str(slip),
                        "fill_date": "2026-03-08",
                        "status": "FILLED",
                    }
                )
        q = compute_execution_quality(fills_csv)
        assert q["median_slippage_bps"] == 25.0

    def test_median_odd_count(self, tmp_path):
        """Median with odd number of fills should return the middle value."""
        fills_csv = tmp_path / "fills.csv"
        fields = [
            "ticker",
            "action",
            "target_usd",
            "fill_price",
            "fill_shares",
            "fill_usd",
            "slippage_bps",
            "fill_date",
            "status",
        ]
        with open(fills_csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for slip in [10, 30, 50]:
                w.writerow(
                    {
                        "ticker": f"T{slip}",
                        "action": "BUY",
                        "target_usd": "1000",
                        "fill_price": "10",
                        "fill_shares": "100",
                        "fill_usd": "1000",
                        "slippage_bps": str(slip),
                        "fill_date": "2026-03-08",
                        "status": "FILLED",
                    }
                )
        q = compute_execution_quality(fills_csv)
        assert q["median_slippage_bps"] == 30.0


# ---------------------------------------------------------------------------
# Fill summary
# ---------------------------------------------------------------------------


class TestFillSummary:
    def test_writes_markdown(self, tmp_path):
        fills_csv = tmp_path / "fills.csv"
        with open(fills_csv, "w", newline="") as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    "ticker",
                    "action",
                    "target_usd",
                    "fill_price",
                    "fill_shares",
                    "fill_usd",
                    "slippage_bps",
                    "fill_date",
                    "status",
                ],
            )
            w.writeheader()
            w.writerow(
                {
                    "ticker": "AAPL",
                    "action": "BUY",
                    "target_usd": "5000",
                    "fill_price": "150",
                    "fill_shares": "33",
                    "fill_usd": "4950",
                    "slippage_bps": "-100",
                    "fill_date": "2026-03-06",
                    "status": "FILLED",
                }
            )

        out = tmp_path / "fill_summary.md"
        write_fill_summary(fills_csv, out)
        assert out.is_file()
        text = out.read_text()
        assert "Fill Summary" in text
        assert "Filled" in text


# ---------------------------------------------------------------------------
# record_fills orchestrator
# ---------------------------------------------------------------------------


class TestRecordFills:
    def test_end_to_end(self, tmp_path):
        trades_root = tmp_path / "trades"
        trades_csv = trades_root / "2026-03-06" / "trades.csv"
        _write_trades_csv(
            trades_csv,
            [
                {
                    "ticker": "AAPL",
                    "action": "BUY",
                    "delta_usd": "5000",
                    "target_usd": "5000",
                    "prior_usd": "0",
                    "bucket": "b",
                    "tier": "A",
                    "catalyst_days": "",
                    "gap_risk": "",
                    "reason": "NEW_ENTRY",
                },
            ],
        )
        result = record_fills(
            "2026-03-06",
            trades_root=trades_root,
            do_mark_all_filled=True,
        )
        assert result["action"] == "record"
        assert result["quality"]["fill_rate"] == 1.0
        assert (trades_root / "2026-03-06" / "fills.csv").is_file()
        assert (trades_root / "2026-03-06" / "fill_summary.md").is_file()
