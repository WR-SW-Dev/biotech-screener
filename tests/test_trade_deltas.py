"""Tests for trade delta computation and weekly rebalance orchestration.

Validates:
  1. Delta math (buy/sell/no-op)
  2. Min-trade threshold filtering
  3. Deterministic ordering (abs(delta) desc, ticker asc)
  4. Gap-risk propagation into trades.csv
  5. Reason codes (NEW_ENTRY, EXIT, REWEIGHT, BUCKET_CHANGE)
  6. Trade summary markdown
  7. No-trades summary
  8. Weekly rebalance day detection
  9. Off-cycle exception detection
  10. End-to-end with two position files
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.build_trade_deltas import (
    TRADES_COLUMNS,
    build_trade_packet,
    compute_trade_deltas,
    write_trade_summary,
    write_trades_csv,
)
from tools.run_weekly_rebalance import detect_off_cycle_exceptions, is_rebalance_day, run_weekly_rebalance

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pos(
    ticker: str,
    dollars: float,
    bucket: str = "binary_91_180",
    gap_risk: str = "",
    tier: str = "A",
    catalyst_days: str = "",
) -> Dict[str, Any]:
    return {
        "ticker": ticker,
        "target_dollars": dollars,
        "bucket": bucket,
        "gap_risk": gap_risk,
        "tier": tier,
        "catalyst_days": catalyst_days,
        "weight_pct": 1.0,
        "actionable_rank": 1,
        "size_band": "M",
        "catalyst_mode": "specific_days",
        "mom_state": "tailwind",
        "price_coverage": "OK",
    }


def _write_positions(path: Path, as_of_date: str, positions: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "schema": "live_shadow_positions.v1",
        "as_of_date": as_of_date,
        "positions": positions,
        "summary": {"total_positions": len(positions)},
    }
    with open(path, "w") as f:
        json.dump(doc, f)


# ---------------------------------------------------------------------------
# A) Delta math
# ---------------------------------------------------------------------------


class TestDeltaMath:

    def test_buy_detected(self):
        prior = [_pos("A", 5000)]
        current = [_pos("A", 8000)]
        trades = compute_trade_deltas(prior, current)
        assert len(trades) == 1
        assert trades[0]["action"] == "BUY"
        assert trades[0]["delta_usd"] == 3000.0

    def test_sell_detected(self):
        prior = [_pos("A", 8000)]
        current = [_pos("A", 5000)]
        trades = compute_trade_deltas(prior, current)
        assert len(trades) == 1
        assert trades[0]["action"] == "SELL"
        assert trades[0]["delta_usd"] == -3000.0

    def test_new_entry(self):
        prior = []
        current = [_pos("A", 5000)]
        trades = compute_trade_deltas(prior, current)
        assert len(trades) == 1
        assert trades[0]["action"] == "BUY"
        assert trades[0]["reason"] == "NEW_ENTRY"
        assert trades[0]["prior_usd"] == 0.0

    def test_exit(self):
        prior = [_pos("A", 5000)]
        current = []
        trades = compute_trade_deltas(prior, current)
        assert len(trades) == 1
        assert trades[0]["action"] == "SELL"
        assert trades[0]["reason"] == "EXIT"
        assert trades[0]["target_usd"] == 0.0

    def test_no_change_no_trade(self):
        prior = [_pos("A", 5000)]
        current = [_pos("A", 5000)]
        trades = compute_trade_deltas(prior, current)
        assert len(trades) == 0


# ---------------------------------------------------------------------------
# B) Min-trade threshold
# ---------------------------------------------------------------------------


class TestMinTradeThreshold:

    def test_below_threshold_filtered(self):
        prior = [_pos("A", 5000)]
        current = [_pos("A", 5400)]
        trades = compute_trade_deltas(prior, current, min_trade_usd=500)
        assert len(trades) == 0

    def test_at_threshold_included(self):
        prior = [_pos("A", 5000)]
        current = [_pos("A", 5500)]
        trades = compute_trade_deltas(prior, current, min_trade_usd=500)
        assert len(trades) == 1

    def test_custom_threshold(self):
        prior = [_pos("A", 5000)]
        current = [_pos("A", 5100)]
        trades = compute_trade_deltas(prior, current, min_trade_usd=50)
        assert len(trades) == 1


# ---------------------------------------------------------------------------
# C) Deterministic ordering
# ---------------------------------------------------------------------------


class TestDeterministicOrdering:

    def test_sorted_by_abs_delta_desc(self):
        prior = [_pos("A", 10000), _pos("B", 10000), _pos("C", 10000)]
        current = [_pos("A", 11000), _pos("B", 15000), _pos("C", 12000)]
        trades = compute_trade_deltas(prior, current)
        deltas = [abs(t["delta_usd"]) for t in trades]
        assert deltas == sorted(deltas, reverse=True)

    def test_tiebreak_by_ticker(self):
        prior = [_pos("B", 10000), _pos("A", 10000)]
        current = [_pos("B", 12000), _pos("A", 12000)]
        trades = compute_trade_deltas(prior, current)
        assert trades[0]["ticker"] == "A"
        assert trades[1]["ticker"] == "B"


# ---------------------------------------------------------------------------
# D) Gap-risk propagation
# ---------------------------------------------------------------------------


class TestGapRiskPropagation:

    def test_gap_risk_in_trades(self):
        prior = []
        current = [_pos("X", 5000, gap_risk="HIGH")]
        trades = compute_trade_deltas(prior, current)
        assert trades[0]["gap_risk"] == "HIGH"

    def test_no_gap_risk_empty(self):
        prior = []
        current = [_pos("Y", 5000)]
        trades = compute_trade_deltas(prior, current)
        assert trades[0]["gap_risk"] == ""


# ---------------------------------------------------------------------------
# E) Reason codes
# ---------------------------------------------------------------------------


class TestReasonCodes:

    def test_bucket_change_reason(self):
        prior = [_pos("A", 5000, bucket="binary_0_30")]
        current = [_pos("A", 6000, bucket="binary_31_90")]
        trades = compute_trade_deltas(prior, current)
        assert "BUCKET_CHANGE" in trades[0]["reason"]

    def test_reweight_reason(self):
        prior = [_pos("A", 5000)]
        current = [_pos("A", 8000)]
        trades = compute_trade_deltas(prior, current)
        assert "REWEIGHT" in trades[0]["reason"]


# ---------------------------------------------------------------------------
# F) CSV output
# ---------------------------------------------------------------------------


class TestCSVOutput:

    def test_csv_columns(self, tmp_path):
        trades = [
            {
                "ticker": "A",
                "action": "BUY",
                "delta_usd": 1000,
                "target_usd": 5000,
                "prior_usd": 4000,
                "bucket": "binary_91_180",
                "tier": "A",
                "catalyst_days": "120",
                "gap_risk": "",
                "reason": "REWEIGHT",
            }
        ]
        csv_path = write_trades_csv(trades, tmp_path / "trades.csv")
        with open(csv_path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 1
        assert set(rows[0].keys()) == set(TRADES_COLUMNS)

    def test_empty_trades_writes_header(self, tmp_path):
        csv_path = write_trades_csv([], tmp_path / "trades.csv")
        with open(csv_path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 0


# ---------------------------------------------------------------------------
# G) Trade summary
# ---------------------------------------------------------------------------


class TestTradeSummary:

    def test_summary_created(self, tmp_path):
        prior = [_pos("A", 5000), _pos("B", 5000)]
        current = [_pos("A", 8000), _pos("C", 3000)]
        trades = compute_trade_deltas(prior, current)
        out = tmp_path / "summary.md"
        write_trade_summary(trades, "2026-03-06", "2026-03-08", prior, current, out)
        text = out.read_text()
        assert "Trade Summary" in text
        assert "Rebalance" in text
        assert "Largest Trades" in text
        assert "Bucket Drift" in text

    def test_summary_flags_gap_risk_buys(self, tmp_path):
        prior = []
        current = [_pos("X", 5000, gap_risk="HIGH")]
        trades = compute_trade_deltas(prior, current)
        out = tmp_path / "summary.md"
        write_trade_summary(trades, "", "2026-03-08", prior, current, out)
        text = out.read_text()
        assert "gap-risk HIGH" in text
        assert "X" in text


# ---------------------------------------------------------------------------
# H) Rebalance day detection
# ---------------------------------------------------------------------------


class TestRebalanceDay:

    def test_friday_is_rebalance(self):
        policy = {"rebalance_day": "FRIDAY"}
        assert is_rebalance_day("2026-03-06", policy) is True  # Friday

    def test_thursday_is_not_rebalance(self):
        policy = {"rebalance_day": "FRIDAY"}
        assert is_rebalance_day("2026-03-05", policy) is False  # Thursday

    def test_custom_day(self):
        policy = {"rebalance_day": "MONDAY"}
        assert is_rebalance_day("2026-03-09", policy) is True  # Monday


# ---------------------------------------------------------------------------
# I) Off-cycle exceptions
# ---------------------------------------------------------------------------


class TestOffCycleExceptions:

    def test_new_gap_risk_high_triggers(self, tmp_path):
        pos_dir = tmp_path / "positions"
        # Prior: no HIGH gap risk
        _write_positions(pos_dir / "2026-03-06.json", "2026-03-06", [_pos("A", 5000)])
        # Current: A now HIGH
        _write_positions(
            pos_dir / "2026-03-08.json",
            "2026-03-08",
            [_pos("A", 5000, gap_risk="HIGH")],
        )
        exceptions = detect_off_cycle_exceptions(pos_dir / "2026-03-08.json")
        assert any("NEW_GAP_RISK_HIGH" in e for e in exceptions)

    def test_no_exceptions_when_stable(self, tmp_path):
        pos_dir = tmp_path / "positions"
        _write_positions(pos_dir / "2026-03-06.json", "2026-03-06", [_pos("A", 5000)])
        _write_positions(pos_dir / "2026-03-08.json", "2026-03-08", [_pos("A", 5000)])
        exceptions = detect_off_cycle_exceptions(pos_dir / "2026-03-08.json")
        assert exceptions == []


# ---------------------------------------------------------------------------
# J) End-to-end
# ---------------------------------------------------------------------------


class TestEndToEnd:

    def test_build_trade_packet(self, tmp_path):
        pos_dir = tmp_path / "positions"
        _write_positions(
            pos_dir / "2026-03-06.json",
            "2026-03-06",
            [_pos("A", 10000), _pos("B", 5000)],
        )
        _write_positions(
            pos_dir / "2026-03-08.json",
            "2026-03-08",
            [_pos("A", 12000), _pos("C", 3000)],
        )
        out_dir = tmp_path / "trades"
        result = build_trade_packet(
            pos_dir / "2026-03-08.json",
            pos_dir / "2026-03-06.json",
            out_dir=out_dir,
        )
        assert result["n_trades"] >= 2  # B sold, C bought, A reweighted
        assert (out_dir / "trades.csv").is_file()
        assert (out_dir / "trade_summary.md").is_file()

    def test_first_snapshot_all_buys(self, tmp_path):
        pos_dir = tmp_path / "positions"
        _write_positions(
            pos_dir / "2026-03-08.json",
            "2026-03-08",
            [_pos("A", 10000), _pos("B", 5000)],
        )
        out_dir = tmp_path / "trades"
        result = build_trade_packet(
            pos_dir / "2026-03-08.json",
            out_dir=out_dir,
            positions_dir=pos_dir,
        )
        assert result["n_buys"] == 2
        assert result["n_sells"] == 0

    def test_run_weekly_no_trade_day(self, tmp_path):
        pos_dir = tmp_path / "positions"
        # 2026-03-05 is Thursday
        _write_positions(pos_dir / "2026-03-05.json", "2026-03-05", [_pos("A", 5000)])
        policy_path = tmp_path / "policy.json"
        with open(policy_path, "w") as f:
            json.dump({"rebalance_day": "FRIDAY", "account_usd": 100000}, f)

        result = run_weekly_rebalance(
            "2026-03-05",
            policy_path=policy_path,
            positions_dir=pos_dir,
        )
        assert result["decision"] == "NO_TRADE"

    def test_run_weekly_rebalance_day(self, tmp_path):
        pos_dir = tmp_path / "positions"
        # 2026-03-06 is Friday
        _write_positions(pos_dir / "2026-03-06.json", "2026-03-06", [_pos("A", 5000)])
        policy_path = tmp_path / "policy.json"
        with open(policy_path, "w") as f:
            json.dump({"rebalance_day": "FRIDAY", "account_usd": 100000}, f)

        result = run_weekly_rebalance(
            "2026-03-06",
            policy_path=policy_path,
            positions_dir=pos_dir,
        )
        assert result["decision"] == "REBALANCE"
