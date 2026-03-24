"""Tests for run_weekly_rebalance.py — rebalance day logic + off-cycle exception detection.

Validates:
  1. is_rebalance_day correctly identifies matching weekdays
  2. detect_off_cycle_exceptions detects new gap-risk HIGH
  3. detect_off_cycle_exceptions detects hard gate FAIL
  4. run_weekly_rebalance returns NO_POSITIONS for missing file
  5. run_weekly_rebalance returns NO_TRADE on non-rebalance day
  6. run_weekly_rebalance triggers on force flag
  7. run_weekly_rebalance triggers on off-cycle exceptions
  8. DAY_MAP covers all weekdays
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.run_weekly_rebalance import DAY_MAP, detect_off_cycle_exceptions, is_rebalance_day, run_weekly_rebalance

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_positions(path, as_of_date, positions):
    """Write a shadow positions JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"as_of_date": as_of_date, "positions": positions}
    with open(path, "w") as f:
        json.dump(doc, f)


def _pos(ticker, dollars, gap_risk="", bucket="binary_91_180"):
    return {
        "ticker": ticker,
        "target_dollars": dollars,
        "bucket": bucket,
        "tier": "A",
        "gap_risk": gap_risk,
        "actionable_rank": 1,
        "weight_pct": 5.0,
        "reason": "",
        "price_coverage": "OK",
        "catalyst_days": "",
    }


def _write_policy(path, rebalance_day="FRIDAY"):
    path.parent.mkdir(parents=True, exist_ok=True)
    policy = {
        "schema": "portfolio_policy.v3",
        "rebalance_day": rebalance_day,
        "total_notional": 500000,
        "bucket_weights": {
            "binary_0_30": 0.10,
            "binary_31_90": 0.10,
            "binary_91_180": 0.25,
            "less_binary": 0.55,
        },
        "max_name_pct": 5.0,
    }
    with open(path, "w") as f:
        json.dump(policy, f)


# ---------------------------------------------------------------------------
# A) DAY_MAP completeness
# ---------------------------------------------------------------------------


class TestDayMap:
    def test_all_weekdays_present(self):
        expected = {"MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"}
        assert set(DAY_MAP.keys()) == expected

    def test_values_are_0_through_6(self):
        assert sorted(DAY_MAP.values()) == [0, 1, 2, 3, 4, 5, 6]


# ---------------------------------------------------------------------------
# B) is_rebalance_day
# ---------------------------------------------------------------------------


class TestIsRebalanceDay:
    def test_friday_on_friday(self):
        # 2026-03-06 is a Friday
        assert is_rebalance_day("2026-03-06", {"rebalance_day": "FRIDAY"})

    def test_friday_on_monday(self):
        # 2026-03-09 is a Monday
        assert not is_rebalance_day("2026-03-09", {"rebalance_day": "FRIDAY"})

    def test_monday_on_monday(self):
        # 2026-03-09 is a Monday
        assert is_rebalance_day("2026-03-09", {"rebalance_day": "MONDAY"})

    def test_default_friday_when_missing(self):
        # Policy without rebalance_day defaults to FRIDAY
        # 2026-03-06 is a Friday
        assert is_rebalance_day("2026-03-06", {})

    def test_case_insensitive(self):
        # Policy key is uppercased internally
        assert is_rebalance_day("2026-03-06", {"rebalance_day": "friday"})


# ---------------------------------------------------------------------------
# C) detect_off_cycle_exceptions
# ---------------------------------------------------------------------------


class TestDetectOffCycleExceptions:
    def test_new_gap_risk_high(self, tmp_path):
        pos_dir = tmp_path / "positions"
        _write_positions(
            pos_dir / "2026-03-07.json",
            "2026-03-07",
            [_pos("AAPL", 5000)],
        )
        _write_positions(
            pos_dir / "2026-03-08.json",
            "2026-03-08",
            [_pos("AAPL", 5000), _pos("GOOG", 3000, gap_risk="HIGH")],
        )
        exceptions = detect_off_cycle_exceptions(pos_dir / "2026-03-08.json")
        assert len(exceptions) == 1
        assert "GOOG" in exceptions[0]
        assert "NEW_GAP_RISK_HIGH" in exceptions[0]

    def test_no_new_gap_risk(self, tmp_path):
        pos_dir = tmp_path / "positions"
        _write_positions(
            pos_dir / "2026-03-07.json",
            "2026-03-07",
            [_pos("GOOG", 3000, gap_risk="HIGH")],
        )
        _write_positions(
            pos_dir / "2026-03-08.json",
            "2026-03-08",
            [_pos("GOOG", 3000, gap_risk="HIGH")],
        )
        exceptions = detect_off_cycle_exceptions(pos_dir / "2026-03-08.json")
        assert len(exceptions) == 0

    def test_hard_gate_fail(self, tmp_path):
        pos_dir = tmp_path / "positions"
        _write_positions(
            pos_dir / "2026-03-08.json",
            "2026-03-08",
            [_pos("AAPL", 5000)],
        )
        snap_dir = tmp_path / "snapshots"
        snap_dir.mkdir()
        manifest = {"overall_status": "FAIL", "gates": []}
        (snap_dir / "run_manifest.json").write_text(json.dumps(manifest))

        exceptions = detect_off_cycle_exceptions(
            pos_dir / "2026-03-08.json",
            snap_dir=snap_dir,
        )
        assert any("HARD_GATE_FAIL" in e for e in exceptions)

    def test_no_exceptions(self, tmp_path):
        pos_dir = tmp_path / "positions"
        _write_positions(
            pos_dir / "2026-03-08.json",
            "2026-03-08",
            [_pos("AAPL", 5000)],
        )
        exceptions = detect_off_cycle_exceptions(pos_dir / "2026-03-08.json")
        assert len(exceptions) == 0


# ---------------------------------------------------------------------------
# D) run_weekly_rebalance
# ---------------------------------------------------------------------------


class TestRunWeeklyRebalance:
    def test_no_positions_file(self, tmp_path):
        pos_dir = tmp_path / "positions"
        pos_dir.mkdir(parents=True)
        policy_path = tmp_path / "policy.json"
        _write_policy(policy_path)

        result = run_weekly_rebalance(
            "2026-03-08",
            policy_path=policy_path,
            positions_dir=pos_dir,
        )
        assert result["decision"] == "NO_POSITIONS"

    def test_no_trade_on_non_rebalance_day(self, tmp_path):
        pos_dir = tmp_path / "positions"
        # 2026-03-09 is a Monday, policy says FRIDAY
        _write_positions(
            pos_dir / "2026-03-09.json",
            "2026-03-09",
            [_pos("AAPL", 5000)],
        )
        policy_path = tmp_path / "policy.json"
        _write_policy(policy_path, rebalance_day="FRIDAY")

        # Patch SNAPSHOTS_ROOT to avoid filesystem leakage
        with patch("tools.run_weekly_rebalance.SNAPSHOTS_ROOT", tmp_path / "snapshots"):
            result = run_weekly_rebalance(
                "2026-03-09",
                policy_path=policy_path,
                positions_dir=pos_dir,
            )
        assert result["decision"] == "NO_TRADE"
        assert result["is_rebalance_day"] is False
        assert result["n_trades"] == 0

    def test_force_flag_triggers_trade(self, tmp_path):
        pos_dir = tmp_path / "positions"
        # 2026-03-09 is a Monday, not rebalance day
        _write_positions(
            pos_dir / "2026-03-08.json",
            "2026-03-08",
            [_pos("AAPL", 5000)],
        )
        _write_positions(
            pos_dir / "2026-03-09.json",
            "2026-03-09",
            [_pos("AAPL", 5000), _pos("GOOG", 3000)],
        )
        policy_path = tmp_path / "policy.json"
        _write_policy(policy_path, rebalance_day="FRIDAY")

        with patch("tools.run_weekly_rebalance.SNAPSHOTS_ROOT", tmp_path / "snapshots"):
            with patch("tools.run_weekly_rebalance.TRADES_ROOT", tmp_path / "trades"):
                result = run_weekly_rebalance(
                    "2026-03-09",
                    policy_path=policy_path,
                    positions_dir=pos_dir,
                    force=True,
                )
        assert result["decision"] == "OFF_CYCLE"
        assert result["forced"] is True

    def test_rebalance_day_triggers_trade(self, tmp_path):
        pos_dir = tmp_path / "positions"
        # 2026-03-06 is a Friday
        _write_positions(
            pos_dir / "2026-03-05.json",
            "2026-03-05",
            [_pos("AAPL", 5000)],
        )
        _write_positions(
            pos_dir / "2026-03-06.json",
            "2026-03-06",
            [_pos("AAPL", 5000), _pos("MSFT", 3000)],
        )
        policy_path = tmp_path / "policy.json"
        _write_policy(policy_path, rebalance_day="FRIDAY")

        with patch("tools.run_weekly_rebalance.SNAPSHOTS_ROOT", tmp_path / "snapshots"):
            with patch("tools.run_weekly_rebalance.TRADES_ROOT", tmp_path / "trades"):
                result = run_weekly_rebalance(
                    "2026-03-06",
                    policy_path=policy_path,
                    positions_dir=pos_dir,
                )
        assert result["decision"] == "REBALANCE"
        assert result["is_rebalance_day"] is True
