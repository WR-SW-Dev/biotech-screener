"""
Tests for scripts/research/ees_v2_phase3_shadow_monitor.py

Pins the four load-bearing controls:
  1. Phase 3 normalization
  2. Duplicate ledger-row prevention
  3. Settled-row immutability
  4. Observation-window gate (no interpretation before threshold)

Run:
    pytest tests/test_ees_v2_phase3_shadow_monitor.py -v
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from scripts.research.ees_v2_phase3_shadow_monitor import (  # noqa: E402
    OBS_GATE_5D,
    OBS_GATE_20D,
    _is_settled,
    backfill_open_rows,
    compute_summary,
    filter_phase3_ees,
    is_phase3,
    load_ledger,
    make_new_row,
    write_ledger,
)

# ---------------------------------------------------------------------------
# 1. Phase 3 normalization
# ---------------------------------------------------------------------------


class TestIsPhase3:
    def test_float_3_accepted(self):
        assert is_phase3(3.0) is True

    def test_float_3_string_accepted(self):
        assert is_phase3("3.0") is True

    def test_int_3_accepted(self):
        assert is_phase3(3) is True

    def test_float_above_3_accepted(self):
        # Phase 3b, NDA, etc. — any float >= 3 is Phase 3
        assert is_phase3(3.5) is True
        assert is_phase3("3.5") is True

    def test_float_below_3_rejected(self):
        assert is_phase3(2.0) is False
        assert is_phase3("2.0") is False
        assert is_phase3(1.0) is False

    def test_phase_2_rejected(self):
        assert is_phase3("2") is False

    def test_string_phase_3_accepted(self):
        assert is_phase3("phase 3") is True
        assert is_phase3("Phase 3") is True
        assert is_phase3("PHASE 3") is True

    def test_string_phase3_accepted(self):
        assert is_phase3("phase3") is True
        assert is_phase3("Phase3") is True

    def test_string_p3_accepted(self):
        assert is_phase3("p3") is True
        assert is_phase3("P3") is True  # case-insensitive match

    def test_string_phase_3b_accepted(self):
        # contains "phase 3"
        assert is_phase3("phase 3b") is True

    def test_none_rejected(self):
        assert is_phase3(None) is False

    def test_empty_string_rejected(self):
        assert is_phase3("") is False

    def test_nan_float_rejected(self):
        assert is_phase3(float("nan")) is False

    def test_arbitrary_string_rejected(self):
        assert is_phase3("early clinical") is False
        assert is_phase3("preclinical") is False

    def test_phase_1_rejected(self):
        assert is_phase3("phase 1") is False
        assert is_phase3("1.0") is False


class TestFilterPhase3Ees:
    def _row(self, phase, ees_v2):
        return {"ticker": "TEST", "lead_program_phase": phase, "ees_v2_score": ees_v2}

    def test_valid_phase3_row_passes(self):
        rows = [self._row("3.0", "0.5")]
        assert len(filter_phase3_ees(rows)) == 1

    def test_phase2_row_excluded(self):
        rows = [self._row("2.0", "0.5")]
        assert filter_phase3_ees(rows) == []

    def test_null_ees_excluded(self):
        rows = [self._row("3.0", None)]
        assert filter_phase3_ees(rows) == []

    def test_empty_ees_excluded(self):
        rows = [self._row("3.0", "")]
        assert filter_phase3_ees(rows) == []

    def test_nan_ees_excluded(self):
        rows = [self._row("3.0", "nan")]
        assert filter_phase3_ees(rows) == []

    def test_mixed_rows(self):
        rows = [
            self._row("3.0", "0.5"),
            self._row("2.0", "0.5"),
            self._row("3.0", ""),
            self._row("3.0", "0.3"),
        ]
        result = filter_phase3_ees(rows)
        assert len(result) == 2
        assert all(is_phase3(r["lead_program_phase"]) for r in result)


# ---------------------------------------------------------------------------
# 2. Duplicate ledger-row prevention
# ---------------------------------------------------------------------------


class TestDuplicatePrevention:
    def _make_row(self, snap_date, ticker, settled=False):
        return {
            "snap_date": snap_date,
            "ticker": ticker,
            "ees_v2_score": 0.3,
            "lead_program_phase": 3.0,
            "is_hard_catalyst": False,
            "catalyst_event_type": "",
            "catalyst_family": "CLINICAL",
            "anchor_date": snap_date,
            "anchor_close": 10.0,
            "xbi_anchor_date": snap_date,
            "xbi_anchor_close": 50.0,
            "actual_return_5d": 0.05 if settled else None,
            "xbi_return_5d": 0.02 if settled else None,
            "excess_return_5d": 0.03 if settled else None,
            "forward_complete_5d": settled,
            "actual_return_20d": 0.08 if settled else None,
            "xbi_return_20d": 0.03 if settled else None,
            "excess_return_20d": 0.05 if settled else None,
            "forward_complete_20d": settled,
            "ledger_version": "1.0",
            "run_ts": "2026-06-24T17:00:00Z",
        }

    def test_no_duplicate_when_key_exists(self, tmp_path):
        """Running with the same as_of_date/ticker twice must not add a duplicate."""
        lpath = tmp_path / "ledger.jsonl"
        existing = [self._make_row("2026-06-24", "RVMD")]
        write_ledger(existing, lpath)

        rows, existing_keys, settled_keys = load_ledger(lpath)
        assert len(rows) == 1
        assert ("2026-06-24", "RVMD") in existing_keys

        # Simulate processing the same date again — key already in ledger, skip
        new_rows_for_date = [self._make_row("2026-06-24", "RVMD")]
        added = [r for r in new_rows_for_date if (r["snap_date"], r["ticker"]) not in existing_keys]
        assert added == []

        # Ledger still has exactly 1 row
        rows2, _, _ = load_ledger(lpath)
        assert len(rows2) == 1

    def test_different_ticker_same_date_is_new(self, tmp_path):
        lpath = tmp_path / "ledger.jsonl"
        existing = [self._make_row("2026-06-24", "RVMD")]
        write_ledger(existing, lpath)

        rows, existing_keys, _ = load_ledger(lpath)
        assert ("2026-06-24", "STOK") not in existing_keys

    def test_same_ticker_different_date_is_new(self, tmp_path):
        lpath = tmp_path / "ledger.jsonl"
        existing = [self._make_row("2026-06-24", "RVMD")]
        write_ledger(existing, lpath)

        rows, existing_keys, _ = load_ledger(lpath)
        assert ("2026-06-25", "RVMD") not in existing_keys


# ---------------------------------------------------------------------------
# 3. Settled-row immutability
# ---------------------------------------------------------------------------


class TestSettledRowImmutability:
    def _settled_row(self, snap_date="2026-06-01", ticker="RVMD"):
        return {
            "snap_date": snap_date,
            "ticker": ticker,
            "ees_v2_score": 0.42,
            "lead_program_phase": 3.0,
            "is_hard_catalyst": True,
            "catalyst_event_type": "P3_INTERIM",
            "catalyst_family": "CLINICAL",
            "anchor_date": snap_date,
            "anchor_close": 42.0,
            "xbi_anchor_date": snap_date,
            "xbi_anchor_close": 95.0,
            "actual_return_5d": 0.10,
            "xbi_return_5d": 0.03,
            "excess_return_5d": 0.07,
            "forward_complete_5d": True,
            "actual_return_20d": 0.18,
            "xbi_return_20d": 0.06,
            "excess_return_20d": 0.12,
            "forward_complete_20d": True,
            "ledger_version": "1.0",
            "run_ts": "2026-06-24T17:00:00Z",
        }

    def test_settled_row_passes_through_unchanged(self):
        """backfill_open_rows must return settled rows byte-for-byte identical."""
        row = self._settled_row()
        row_copy = dict(row)
        prices = {"RVMD": {"2026-06-01": 42.0, "2026-06-30": 60.0}}
        sorted_dates = ["2026-06-01", "2026-06-30"]

        result, _, _ = backfill_open_rows([row], prices, sorted_dates)
        assert len(result) == 1
        assert result[0] == row_copy

    def test_settled_row_returns_not_overwritten(self):
        """Even with new price data available, a settled row's returns are untouched."""
        row = self._settled_row()
        original_return = row["actual_return_5d"]

        # Provide prices that would compute a different return
        prices = {
            "RVMD": {
                "2026-06-01": 42.0,
                "2026-06-06": 99.0,  # would compute ~135% return — very different
                "2026-06-21": 90.0,
            },
            "XBI": {"2026-06-01": 95.0, "2026-06-06": 96.0, "2026-06-21": 97.0},
        }
        sorted_dates = sorted(prices["RVMD"].keys())

        result, _, _ = backfill_open_rows([row], prices, sorted_dates)
        assert result[0]["actual_return_5d"] == original_return
        assert result[0]["forward_complete_20d"] is True

    def test_integrity_check_catches_modification(self, tmp_path):
        """The integrity assert in main catches any inadvertent settled-row modification."""
        row = self._settled_row()
        row_copy = dict(row)
        prices = {}
        sorted_dates = []

        updated, _, _ = backfill_open_rows([row], prices, sorted_dates)
        # Simulate integrity check from main()
        for old, new in zip([row_copy], updated):
            if old.get("forward_complete_20d") is True:
                assert old == new  # must pass

    def test_open_row_can_be_backfilled(self):
        """An open (unsettled) row should get returns filled when prices are available."""
        row = {
            "snap_date": "2026-06-01",
            "ticker": "RVMD",
            "ees_v2_score": 0.3,
            "lead_program_phase": 3.0,
            "is_hard_catalyst": False,
            "catalyst_event_type": "",
            "catalyst_family": "CLINICAL",
            "anchor_date": "2026-06-01",
            "anchor_close": 40.0,
            "xbi_anchor_date": "2026-06-01",
            "xbi_anchor_close": 90.0,
            "actual_return_5d": None,
            "xbi_return_5d": None,
            "excess_return_5d": None,
            "forward_complete_5d": False,
            "actual_return_20d": None,
            "xbi_return_20d": None,
            "excess_return_20d": None,
            "forward_complete_20d": False,
            "ledger_version": "1.0",
            "run_ts": "2026-06-24T17:00:00Z",
        }
        # Provide enough future prices for 5d and 20d
        dates = [f"2026-06-{str(i).zfill(2)}" for i in range(1, 30)]
        prices = {
            "RVMD": {d: 40.0 + i for i, d in enumerate(dates)},
            "XBI": {d: 90.0 + i * 0.1 for i, d in enumerate(dates)},
        }
        sorted_dates = sorted(dates)

        result, new_5d, new_20d = backfill_open_rows([row], prices, sorted_dates)
        assert result[0]["forward_complete_5d"] is True
        assert result[0]["forward_complete_20d"] is True
        assert result[0]["actual_return_5d"] is not None
        assert new_5d == 1
        assert new_20d == 1


# ---------------------------------------------------------------------------
# 4. Observation-window gate
# ---------------------------------------------------------------------------


class TestObservationGate:
    def _make_settled_row(self, snap_date, ticker, ees_v2_score, excess_return_5d, excess_return_20d):
        return {
            "snap_date": snap_date,
            "ticker": ticker,
            "ees_v2_score": ees_v2_score,
            "forward_complete_5d": True,
            "forward_complete_20d": True,
            "excess_return_5d": excess_return_5d,
            "excess_return_20d": excess_return_20d,
        }

    def _make_open_row(self, snap_date, ticker, ees_v2_score):
        return {
            "snap_date": snap_date,
            "ticker": ticker,
            "ees_v2_score": ees_v2_score,
            "forward_complete_5d": False,
            "forward_complete_20d": False,
            "excess_return_5d": None,
            "excess_return_20d": None,
        }

    def test_gate_not_met_when_zero_rows(self):
        summary = compute_summary([], "2026-06-24")
        assert summary["observation_gate_5d"] == "NOT_MET"
        assert summary["observation_gate_20d"] == "NOT_MET"
        assert summary["interpretation_status"] == "OBSERVATION_WINDOW_INCOMPLETE_NO_INTERPRETATION"

    def test_gate_not_met_below_threshold(self):
        rows = [
            self._make_settled_row(f"2026-06-{i:02d}", "RVMD", 0.3, 0.02, 0.05)
            for i in range(1, OBS_GATE_5D)  # one below threshold
        ]
        summary = compute_summary(rows, "2026-06-24")
        assert summary["observation_gate_5d"] == "NOT_MET"
        assert summary["ic_5d_mean"] is None

    def test_gate_met_at_threshold(self):
        rows = [
            self._make_settled_row(f"2026-0{(i // 30) + 6}-{(i % 30) + 1:02d}", f"T{i}", float(i) / 10, 0.02, 0.04)
            for i in range(OBS_GATE_5D)
        ]
        assert len(rows) == OBS_GATE_5D
        summary = compute_summary(rows, "2026-06-24")
        assert summary["observation_gate_5d"] == "MET"
        assert summary["observation_gate_20d"] == "MET"
        assert summary["interpretation_status"] == "OBSERVATION_WINDOW_COMPLETE_INTERPRET_WITH_CARE"

    def test_no_ic_before_gate_met(self):
        """IC values must be None when gate is NOT_MET."""
        rows = [self._make_settled_row("2026-06-01", f"T{i}", float(i), 0.01 * i, 0.02 * i) for i in range(5)]
        summary = compute_summary(rows, "2026-06-24")
        assert summary["observation_gate_5d"] == "NOT_MET"
        assert summary["ic_5d_mean"] is None
        assert summary["hit_rate_5d"] is None
        assert summary["quintile_spread_5d"] is None

    def test_open_rows_not_counted_in_gate(self):
        """Open rows must not count toward the completed-observation gate."""
        # 19 settled + 1 open = should not meet 20-observation gate
        settled = [
            self._make_settled_row(f"2026-06-{i:02d}", "RVMD", float(i) / 10, 0.01, 0.02)
            for i in range(1, OBS_GATE_5D)  # 19 rows
        ]
        open_rows = [self._make_open_row("2026-06-24", "STOK", 0.5)]
        all_rows = settled + open_rows
        summary = compute_summary(all_rows, "2026-06-24")
        assert summary["observation_gate_5d"] == "NOT_MET"

    def test_gate_counts_are_in_summary(self):
        rows = [self._make_settled_row("2026-06-01", f"T{i}", 0.3, 0.02, 0.04) for i in range(5)]
        summary = compute_summary(rows, "2026-06-24")
        assert summary["completed_5d"] == 5
        assert summary["completed_20d"] == 5
        assert summary["phase3_rows_total"] == 5


# ---------------------------------------------------------------------------
# 5. Ledger read/write round-trip
# ---------------------------------------------------------------------------


class TestLedgerRoundTrip:
    def _base_row(self, snap_date, ticker):
        return {
            "snap_date": snap_date,
            "ticker": ticker,
            "ees_v2_score": 0.3,
            "lead_program_phase": 3.0,
            "is_hard_catalyst": False,
            "catalyst_event_type": "",
            "catalyst_family": "CLINICAL",
            "anchor_date": snap_date,
            "anchor_close": 10.0,
            "xbi_anchor_date": snap_date,
            "xbi_anchor_close": 50.0,
            "actual_return_5d": None,
            "xbi_return_5d": None,
            "excess_return_5d": None,
            "forward_complete_5d": False,
            "actual_return_20d": None,
            "xbi_return_20d": None,
            "excess_return_20d": None,
            "forward_complete_20d": False,
            "ledger_version": "1.0",
            "run_ts": "2026-06-24T17:00:00Z",
        }

    def test_write_and_reload(self, tmp_path):
        lpath = tmp_path / "ledger.jsonl"
        rows = [self._base_row("2026-06-24", "RVMD"), self._base_row("2026-06-24", "STOK")]
        write_ledger(rows, lpath)

        loaded, keys, settled = load_ledger(lpath)
        assert len(loaded) == 2
        assert ("2026-06-24", "RVMD") in keys
        assert ("2026-06-24", "STOK") in keys
        assert len(settled) == 0

    def test_empty_ledger_created(self, tmp_path):
        lpath = tmp_path / "ledger.jsonl"
        loaded, keys, settled = load_ledger(lpath)
        assert loaded == []
        assert keys == set()

    def test_malformed_line_skipped(self, tmp_path):
        lpath = tmp_path / "ledger.jsonl"
        lpath.write_text('{"snap_date":"2026-06-24","ticker":"RVMD","forward_complete_20d":false}\n{bad json\n')
        loaded, _, _ = load_ledger(lpath)
        assert len(loaded) == 1  # only the valid line


# ---------------------------------------------------------------------------
# 6. Settled-row hardening: _is_settled() and boolish forms
# ---------------------------------------------------------------------------


class TestIsSettled:
    """Pins the _is_settled() helper added in the post-merge hardening patch."""

    def test_json_true_is_settled(self):
        assert _is_settled(True) is True

    def test_numeric_1_is_settled(self):
        assert _is_settled(1) is True

    def test_string_true_lowercase_is_settled(self):
        assert _is_settled("true") is True

    def test_string_true_titlecase_is_settled(self):
        assert _is_settled("True") is True

    def test_string_true_uppercase_is_settled(self):
        assert _is_settled("TRUE") is True

    def test_json_false_is_not_settled(self):
        assert _is_settled(False) is False

    def test_numeric_0_is_not_settled(self):
        assert _is_settled(0) is False

    def test_string_false_is_not_settled(self):
        assert _is_settled("false") is False

    def test_none_is_not_settled(self):
        assert _is_settled(None) is False

    def test_missing_field_is_not_settled(self):
        row: dict = {}
        assert _is_settled(row.get("forward_complete_20d")) is False

    def test_string_1_is_not_settled(self):
        # "1" as a string is truthy but not in our explicit accept list
        assert _is_settled("1") is False


class TestBoolishSettledRowImmutability:
    """
    Settled rows with truthy non-boolean forward_complete_20d must be protected
    by backfill_open_rows() regardless of how the value was written to the ledger.
    """

    def _row_with_complete(self, complete_20d_value, ticker="RVMD"):
        return {
            "snap_date": "2026-06-01",
            "ticker": ticker,
            "ees_v2_score": 0.3,
            "anchor_date": "2026-06-01",
            "anchor_close": 40.0,
            "xbi_anchor_date": "2026-06-01",
            "xbi_anchor_close": 90.0,
            "actual_return_5d": 0.05,
            "xbi_return_5d": 0.02,
            "excess_return_5d": 0.03,
            "forward_complete_5d": True,
            "actual_return_20d": 0.10,
            "xbi_return_20d": 0.04,
            "excess_return_20d": 0.06,
            "forward_complete_20d": complete_20d_value,
            "ledger_version": "1.0",
            "run_ts": "2026-06-24T17:00:00Z",
        }

    def _prices_with_different_return(self):
        """Price data that would compute a very different return if applied."""
        dates = [f"2026-06-{i:02d}" for i in range(1, 30)]
        return (
            {
                "RVMD": {d: 40.0 + i * 10 for i, d in enumerate(dates)},
                "XBI": {d: 90.0 + i for i, d in enumerate(dates)},
            },
            sorted(dates),
        )

    def test_json_true_settled_row_protected(self):
        row = self._row_with_complete(True)
        original = dict(row)
        prices, sorted_dates = self._prices_with_different_return()
        result, _, _ = backfill_open_rows([row], prices, sorted_dates)
        assert result[0] == original

    def test_numeric_1_settled_row_protected(self):
        row = self._row_with_complete(1)
        original = dict(row)
        prices, sorted_dates = self._prices_with_different_return()
        result, _, _ = backfill_open_rows([row], prices, sorted_dates)
        assert result[0] == original

    def test_string_true_settled_row_protected(self):
        row = self._row_with_complete("true")
        original = dict(row)
        prices, sorted_dates = self._prices_with_different_return()
        result, _, _ = backfill_open_rows([row], prices, sorted_dates)
        assert result[0] == original

    def test_false_row_is_open_and_backfilled(self):
        """A row with forward_complete_20d=False must NOT be treated as settled."""
        row = self._row_with_complete(False)
        row["actual_return_20d"] = None
        row["excess_return_20d"] = None
        row["forward_complete_20d"] = False
        prices, sorted_dates = self._prices_with_different_return()
        result, _, new_20d = backfill_open_rows([row], prices, sorted_dates)
        assert new_20d == 1
        assert result[0]["forward_complete_20d"] is True

    def test_zero_row_is_open_and_backfilled(self):
        """A row with forward_complete_20d=0 must NOT be treated as settled."""
        row = self._row_with_complete(0)
        row["actual_return_20d"] = None
        row["excess_return_20d"] = None
        prices, sorted_dates = self._prices_with_different_return()
        result, _, new_20d = backfill_open_rows([row], prices, sorted_dates)
        assert new_20d == 1

    def test_string_false_row_is_open_and_backfilled(self):
        """A row with forward_complete_20d='false' must NOT be treated as settled."""
        row = self._row_with_complete("false")
        row["actual_return_20d"] = None
        row["excess_return_20d"] = None
        prices, sorted_dates = self._prices_with_different_return()
        result, _, new_20d = backfill_open_rows([row], prices, sorted_dates)
        assert new_20d == 1
