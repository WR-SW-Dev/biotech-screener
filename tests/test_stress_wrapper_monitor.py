"""Tests for the DEM stress-wrapper shadow monitor + per-name fill extension.

VALIDATION_INFRASTRUCTURE / STRESS_WRAPPER_SHADOW / NO_MODEL_CHANGE.
"""

from __future__ import annotations

from tools.fill_forward_returns import compute_name_forward_returns
from tools.stress_wrapper_monitor import (
    EES_FALSE_TRIGGER,
    REPEAT_OFFENDER_TRIGGER,
    ROLLING_XS_TRIGGER,
    build_repeat_offender_table,
    evaluate_wrapper_active,
    weekly_windows,
)

# --- per-name fill extension ---


def test_compute_name_forward_returns_structure_pending():
    meta = [("ABC", 1, "top30"), ("XYZ", 45, "rank31_60")]
    # empty universe_dates -> no forward endpoint -> returns pending but structured
    out = compute_name_forward_returns(meta, "2026-06-15", [], 100.0)
    assert set(out) == {"ABC", "XYZ"}
    assert out["ABC"]["rank"] == 1 and out["ABC"]["cohort"] == "top30"
    assert out["XYZ"]["cohort"] == "rank31_60"
    for label in ("1d", "5d", "20d"):
        assert out["ABC"][label]["ret"] is None
        assert out["ABC"][label]["xs"] is None


def test_compute_name_forward_returns_dedupes():
    out = compute_name_forward_returns([("ABC", 1, "top30"), ("ABC", 1, "top30")], "2026-06-15", [], 100.0)
    assert list(out) == ["ABC"]


# --- repeat-offender table ---


def _win(date, top30, per_name):
    return {
        "week": date[:7],
        "date": date,
        "capture": {"top30": [{"ticker": t, "rank": r} for t, r in top30]},
        "fill": {"xs_5d": 0.0, "per_name": per_name},
    }


def test_repeat_offender_flagged_when_drags_twice_and_still_held():
    windows = [
        _win("2026-06-01", [("DRAG", 5), ("GOOD", 1)], {"DRAG": {"5d": {"xs": -0.03}}, "GOOD": {"5d": {"xs": 0.02}}}),
        _win("2026-06-08", [("DRAG", 6), ("GOOD", 1)], {"DRAG": {"5d": {"xs": -0.04}}, "GOOD": {"5d": {"xs": 0.01}}}),
    ]
    table = build_repeat_offender_table(windows, min_neg=2)
    by = {r["ticker"]: r for r in table}
    assert by["DRAG"]["neg_windows"] == 2
    assert by["DRAG"]["is_repeat_offender"] is True
    assert by["DRAG"]["currently_top30"] is True
    assert by["GOOD"]["is_repeat_offender"] is False
    # offenders sort first
    assert table[0]["ticker"] == "DRAG"


def test_not_offender_if_dropped_from_top30():
    windows = [
        _win("2026-06-01", [("DRAG", 5)], {"DRAG": {"5d": {"xs": -0.03}}}),
        _win("2026-06-08", [("DRAG", 6)], {"DRAG": {"5d": {"xs": -0.04}}}),
        _win("2026-06-15", [("OTHER", 1)], {"OTHER": {"5d": {"xs": 0.01}}}),  # DRAG no longer held
    ]
    table = build_repeat_offender_table(windows, min_neg=2)
    by = {r["ticker"]: r for r in table}
    assert by["DRAG"]["neg_windows"] == 2
    assert by["DRAG"]["currently_top30"] is False
    assert by["DRAG"]["is_repeat_offender"] is False  # not currently held -> not actionable


def test_min_neg_threshold_respected():
    windows = [
        _win("2026-06-01", [("X", 5)], {"X": {"5d": {"xs": -0.03}}}),
        _win("2026-06-08", [("X", 5)], {"X": {"5d": {"xs": 0.02}}}),
    ]
    table = build_repeat_offender_table(windows, min_neg=2)
    assert table[0]["is_repeat_offender"] is False  # only 1 neg window


# --- wrapper-active triggers ---


def test_wrapper_inactive_when_no_triggers():
    w = evaluate_wrapper_active(rolling_4w_xs=0.01, repeat_offender_count=0, ees_false_count=0)
    assert w["active"] is False


def test_wrapper_active_on_rolling_drawdown():
    w = evaluate_wrapper_active(ROLLING_XS_TRIGGER - 0.01, 0, 0)
    assert w["active"] is True and w["triggers"]["rolling_4w_xs_le_-5pp"] is True


def test_wrapper_active_on_repeat_offenders():
    w = evaluate_wrapper_active(0.0, REPEAT_OFFENDER_TRIGGER, 0)
    assert w["active"] is True and w["triggers"]["repeat_offenders_ge_2"] is True


def test_wrapper_active_on_ees_false():
    w = evaluate_wrapper_active(0.0, 0, EES_FALSE_TRIGGER)
    assert w["active"] is True and w["triggers"]["ees_false_top30_ge_5"] is True


def test_wrapper_handles_missing_inputs():
    w = evaluate_wrapper_active(None, 0, None)
    assert w["active"] is False  # missing data does not falsely fire


# --- window selection ---


def test_weekly_windows_one_per_iso_week_filled_only():
    captures = [{"date": "2026-06-15"}, {"date": "2026-06-16"}, {"date": "2026-06-22"}]
    fills = {
        "2026-06-15": {"capture_date": "2026-06-15", "xs_5d": 0.01},
        "2026-06-16": {"capture_date": "2026-06-16", "xs_5d": 0.02},
        "2026-06-22": {"capture_date": "2026-06-22", "xs_5d": None},
    }  # unfilled -> excluded
    wins = weekly_windows(captures, fills, None)
    assert [w["date"] for w in wins] == ["2026-06-15"]
