"""Tests for build_trade_plan.py — trade plan artifact + trailing dashboard.

Validates:
  1. Reason codes deterministic (NEW_ENTRY, EXIT, REWEIGHT, BUCKET_CHANGE)
  2. Trade plan totals reconcile to position deltas
  3. Trailing rolling metrics computed correctly
  4. Bucket turnover breakdown
  5. CSV + MD output format
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pos(ticker, dollars, bucket="binary_91_180", tier="A", gap_risk="", catalyst_days=""):
    return {
        "ticker": ticker,
        "target_dollars": dollars,
        "bucket": bucket,
        "tier": tier,
        "gap_risk": gap_risk,
        "catalyst_days": catalyst_days,
        "actionable_rank": 1,
        "weight_pct": 5.0,
        "reason": "",
        "price_coverage": "OK",
    }


def _write_positions(path, as_of_date, positions):
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"as_of_date": as_of_date, "positions": positions}
    with open(path, "w") as f:
        json.dump(doc, f)


def _write_perf_csv(path, rows):
    from tools.live_shadow_portfolio import PERF_COLUMNS

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PERF_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# A) Reason codes are deterministic
# ---------------------------------------------------------------------------


class TestReasonCodes:
    def test_new_entry(self):
        from tools.build_trade_deltas import compute_trade_deltas

        trades = compute_trade_deltas([], [_pos("AAPL", 5000)], min_trade_usd=100)
        assert len(trades) == 1
        assert trades[0]["reason"] == "NEW_ENTRY"

    def test_exit(self):
        from tools.build_trade_deltas import compute_trade_deltas

        trades = compute_trade_deltas([_pos("AAPL", 5000)], [], min_trade_usd=100)
        assert len(trades) == 1
        assert trades[0]["reason"] == "EXIT"

    def test_reweight(self):
        from tools.build_trade_deltas import compute_trade_deltas

        trades = compute_trade_deltas(
            [_pos("AAPL", 5000)],
            [_pos("AAPL", 8000)],
            min_trade_usd=100,
        )
        assert len(trades) == 1
        assert "REWEIGHT" in trades[0]["reason"]

    def test_bucket_change(self):
        from tools.build_trade_deltas import compute_trade_deltas

        trades = compute_trade_deltas(
            [_pos("AAPL", 5000, bucket="binary_31_90")],
            [_pos("AAPL", 5000, bucket="binary_91_180")],
            min_trade_usd=0,
        )
        # No dollar delta, so no trade generated (delta=0)
        assert len(trades) == 0

    def test_bucket_change_with_reweight(self):
        from tools.build_trade_deltas import compute_trade_deltas

        trades = compute_trade_deltas(
            [_pos("AAPL", 5000, bucket="binary_31_90")],
            [_pos("AAPL", 7000, bucket="binary_91_180")],
            min_trade_usd=100,
        )
        assert len(trades) == 1
        assert "BUCKET_CHANGE" in trades[0]["reason"]
        assert "REWEIGHT" in trades[0]["reason"]


# ---------------------------------------------------------------------------
# B) Trade plan totals reconcile with position deltas
# ---------------------------------------------------------------------------


class TestTotalsReconcile:
    def test_buy_sell_totals(self, tmp_path):
        from tools.build_trade_plan import build_trade_plan

        pos_dir = tmp_path / "positions"
        _write_positions(
            pos_dir / "2026-03-01.json",
            "2026-03-01",
            [
                _pos("AAPL", 5000),
                _pos("GOOG", 3000),
            ],
        )
        _write_positions(
            pos_dir / "2026-03-08.json",
            "2026-03-08",
            [
                _pos("AAPL", 7000),
                _pos("MSFT", 4000),
            ],
        )

        perf_csv = tmp_path / "performance.csv"
        _write_perf_csv(perf_csv, [])

        result = build_trade_plan(
            "2026-03-08",
            positions_dir=pos_dir,
            perf_csv=perf_csv,
            min_trade_usd=100,
            out_dir=tmp_path / "out",
            skip_pre_trade_check=True,
        )

        # AAPL: 5000→7000 = +2000 BUY
        # GOOG: 3000→0 = -3000 SELL
        # MSFT: 0→4000 = +4000 BUY
        assert result["n_buys"] == 2
        assert result["n_sells"] == 1
        assert result["total_buy_usd"] == 6000.0  # 2000 + 4000
        assert result["total_sell_usd"] == 3000.0

        # Verify trades sum to position deltas
        trades = result["trades"]
        net_from_trades = sum(t["delta_usd"] for t in trades)
        # Net = (7000 + 4000) - (5000 + 3000) = 3000
        assert net_from_trades == 3000.0

    def test_first_snapshot_all_buys(self, tmp_path):
        from tools.build_trade_plan import build_trade_plan

        pos_dir = tmp_path / "positions"
        _write_positions(
            pos_dir / "2026-03-08.json",
            "2026-03-08",
            [
                _pos("AAPL", 5000),
                _pos("GOOG", 3000),
            ],
        )

        result = build_trade_plan(
            "2026-03-08",
            positions_dir=pos_dir,
            perf_csv=tmp_path / "perf.csv",
            min_trade_usd=100,
            out_dir=tmp_path / "out",
            skip_pre_trade_check=True,
        )

        assert result["n_buys"] == 2
        assert result["n_sells"] == 0
        assert all(t["reason"] == "NEW_ENTRY" for t in result["trades"])


# ---------------------------------------------------------------------------
# C) Trailing metrics computation
# ---------------------------------------------------------------------------


class TestTrailingMetrics:
    def test_trailing_4w(self):
        from tools.build_trade_plan import compute_trailing_metrics

        rows = [
            {"date": "2026-02-15", "pnl_pct": "1.0", "excess_vs_xbi_pct": "0.5", "sleeve_binary_91_180_pnl": "100"},
            {"date": "2026-02-22", "pnl_pct": "-0.5", "excess_vs_xbi_pct": "-0.2", "sleeve_binary_91_180_pnl": "-50"},
            {"date": "2026-03-01", "pnl_pct": "2.0", "excess_vs_xbi_pct": "1.0", "sleeve_binary_91_180_pnl": "200"},
            {"date": "2026-03-08", "pnl_pct": "0.5", "excess_vs_xbi_pct": "0.3", "sleeve_binary_91_180_pnl": "80"},
        ]

        result = compute_trailing_metrics(rows, 4)
        p = result["portfolio"]
        assert p["n_weeks"] == 4
        assert p["hit_rate"] == 0.75  # 3 out of 4 positive
        assert p["worst_week"] == -0.5

        b = result["buckets"]["binary_91_180"]
        assert b["total_pnl"] == 330.0  # 100 - 50 + 200 + 80
        assert b["worst_week"] == -50.0
        assert b["hit_rate"] == 0.75

    def test_trailing_1w(self):
        from tools.build_trade_plan import compute_trailing_metrics

        rows = [
            {"date": "2026-03-01", "pnl_pct": "2.0", "excess_vs_xbi_pct": "1.0", "sleeve_binary_91_180_pnl": "200"},
            {"date": "2026-03-08", "pnl_pct": "-0.3", "excess_vs_xbi_pct": "-0.1", "sleeve_binary_91_180_pnl": "-30"},
        ]

        result = compute_trailing_metrics(rows, 1)
        p = result["portfolio"]
        assert p["n_weeks"] == 1
        assert p["net_pct"] == -0.3
        assert p["hit_rate"] == 0.0

    def test_empty_perf(self):
        from tools.build_trade_plan import compute_trailing_metrics

        result = compute_trailing_metrics([], 4)
        assert result["n_weeks"] == 0


# ---------------------------------------------------------------------------
# D) Bucket turnover breakdown
# ---------------------------------------------------------------------------


class TestBucketTurnover:
    def test_bucket_turnover(self):
        from tools.build_trade_plan import compute_bucket_turnover

        prior = [
            _pos("AAPL", 5000, bucket="binary_91_180"),
            _pos("GOOG", 3000, bucket="binary_31_90"),
        ]
        current = [
            _pos("AAPL", 7000, bucket="binary_91_180"),
            _pos("MSFT", 4000, bucket="binary_91_180"),
        ]
        trades = [
            {"ticker": "AAPL", "action": "BUY", "delta_usd": 2000, "bucket": "binary_91_180"},
            {"ticker": "MSFT", "action": "BUY", "delta_usd": 4000, "bucket": "binary_91_180"},
            {"ticker": "GOOG", "action": "SELL", "delta_usd": -3000, "bucket": "binary_31_90"},
        ]

        bt = compute_bucket_turnover(trades, prior, current)

        assert bt["binary_91_180"]["n_trades"] == 2
        assert bt["binary_91_180"]["buy_usd"] == 6000
        assert bt["binary_91_180"]["names_added"] == ["MSFT"]
        assert bt["binary_31_90"]["n_trades"] == 1
        assert bt["binary_31_90"]["sell_usd"] == 3000
        assert bt["binary_31_90"]["names_dropped"] == ["GOOG"]

    def test_empty_turnover(self):
        from tools.build_trade_plan import compute_bucket_turnover

        bt = compute_bucket_turnover([], [], [])
        for b in ["binary_0_30", "binary_31_90", "binary_91_180", "less_binary"]:
            assert bt[b]["n_trades"] == 0
            assert bt[b]["buy_usd"] == 0


# ---------------------------------------------------------------------------
# E) CSV + MD output format
# ---------------------------------------------------------------------------


class TestOutputFormat:
    def test_csv_columns(self, tmp_path):
        from tools.build_trade_plan import TRADE_PLAN_COLUMNS, write_trade_plan_csv

        trades = [
            {
                "ticker": "AAPL",
                "action": "BUY",
                "delta_usd": 5000,
                "target_usd": 5000,
                "prior_usd": 0,
                "bucket": "binary_91_180",
                "tier": "A",
                "catalyst_days": "45",
                "gap_risk": "",
                "reason": "NEW_ENTRY",
            },
        ]
        path = write_trade_plan_csv(trades, tmp_path / "plan.csv")

        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            assert set(reader.fieldnames) == set(TRADE_PLAN_COLUMNS)
            rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["ticker"] == "AAPL"
        assert rows[0]["action"] == "BUY"

    def test_md_has_required_sections(self, tmp_path):
        from tools.build_trade_plan import build_trade_plan

        pos_dir = tmp_path / "positions"
        _write_positions(
            pos_dir / "2026-03-01.json",
            "2026-03-01",
            [
                _pos("AAPL", 5000),
            ],
        )
        _write_positions(
            pos_dir / "2026-03-08.json",
            "2026-03-08",
            [
                _pos("AAPL", 7000),
                _pos("GOOG", 3000),
            ],
        )

        result = build_trade_plan(
            "2026-03-08",
            positions_dir=pos_dir,
            perf_csv=tmp_path / "perf.csv",
            min_trade_usd=100,
            out_dir=tmp_path / "out",
            skip_pre_trade_check=True,
        )

        md_text = Path(result["md_path"]).read_text()
        assert "# Weekly Trade Plan" in md_text
        assert "## Summary" in md_text
        assert "## Trades" in md_text
        assert "## Turnover by Bucket" in md_text
        assert "## Trailing Alpha Dashboard" in md_text
        assert "AAPL" in md_text
        assert "GOOG" in md_text
