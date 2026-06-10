"""Tests for tools/build_price_action_watch.py — all 11 alert codes + builder.

Covers:
- Each alert code trigger condition and boundary values
- QUIET_BEFORE_CATALYST compound biotech anomaly
- REACTION_MISMATCH stock/options divergence
- compute_stock_metrics edge cases
- classify_alerts exhaustive code coverage
- format_watch_md output
"""

import math

import pytest

from tools.build_price_action_watch import THRESHOLDS, _sf, classify_alerts, compute_stock_metrics, format_watch_md

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_stock(ret_1d=None, ret_5d=None, move_intensity=None, latest_price=100.0):
    d = {"latest_price": latest_price}
    if ret_1d is not None:
        d["return_1d_pct"] = ret_1d
    if ret_5d is not None:
        d["return_5d_pct"] = ret_5d
    if move_intensity is not None:
        d["move_intensity"] = move_intensity
    return d


def _make_options(**kw):
    """Build an options dict from keyword args. All values are strings (CSV-like)."""
    return {k: str(v) for k, v in kw.items()}


# ---------------------------------------------------------------------------
# _sf helper
# ---------------------------------------------------------------------------


class TestSafeFloat:
    def test_none(self):
        assert math.isnan(_sf(None))

    def test_empty(self):
        assert math.isnan(_sf(""))

    def test_valid(self):
        assert _sf("3.14") == pytest.approx(3.14)

    def test_invalid(self):
        assert math.isnan(_sf("abc"))

    def test_int(self):
        assert _sf(42) == 42.0


# ---------------------------------------------------------------------------
# compute_stock_metrics
# ---------------------------------------------------------------------------


class TestComputeStockMetrics:
    def test_empty_series(self):
        assert compute_stock_metrics([]) == {}

    def test_single_point(self):
        assert compute_stock_metrics([("2026-03-28", 100.0)]) == {}

    def test_two_points_return(self):
        m = compute_stock_metrics([("2026-03-27", 100.0), ("2026-03-28", 110.0)])
        assert m["return_1d_pct"] == pytest.approx(10.0)
        assert m["latest_price"] == 110.0
        assert m["prior_price"] == 100.0
        assert m["return_5d_pct"] is None  # Not enough data

    def test_negative_return(self):
        m = compute_stock_metrics([("2026-03-27", 100.0), ("2026-03-28", 90.0)])
        assert m["return_1d_pct"] == pytest.approx(-10.0)

    def test_five_day_return(self):
        series = [
            ("2026-03-21", 100.0),
            ("2026-03-22", 101.0),
            ("2026-03-23", 102.0),
            ("2026-03-24", 103.0),
            ("2026-03-25", 104.0),
            ("2026-03-28", 110.0),
        ]
        m = compute_stock_metrics(series)
        # Fix: calculate correctly from 5 calendar days back (2026-03-23 at 102.0)
        # (110 - 102) / 102 * 100 = 7.843...
        assert m["return_5d_pct"] == pytest.approx(7.84, abs=0.01)

    def test_move_intensity(self):
        # Constant small moves, then a big move
        series = [
            ("2026-03-20", 100.0),
            ("2026-03-21", 101.0),
            ("2026-03-22", 102.0),
            ("2026-03-23", 103.0),
            ("2026-03-24", 104.0),
            ("2026-03-25", 114.4),  # ~10% move vs ~1% avg
        ]
        m = compute_stock_metrics(series)
        assert m["move_intensity"] is not None
        assert m["move_intensity"] > 2.0  # Should be well above spike threshold

    def test_zero_prior_price(self):
        m = compute_stock_metrics([("2026-03-27", 0.0), ("2026-03-28", 10.0)])
        assert m["return_1d_pct"] is None  # nan → None


# ---------------------------------------------------------------------------
# Alert code tests — one class per code
# ---------------------------------------------------------------------------


class TestStockMoveUp:
    def test_triggers_at_threshold(self):
        alerts = classify_alerts("TEST", _make_stock(ret_1d=5.0), {})
        assert "STOCK_MOVE_UP" in alerts

    def test_not_triggers_below(self):
        alerts = classify_alerts("TEST", _make_stock(ret_1d=4.99), {})
        assert "STOCK_MOVE_UP" not in alerts

    def test_big_move_takes_priority(self):
        alerts = classify_alerts("TEST", _make_stock(ret_1d=10.0), {})
        assert "STOCK_BIG_MOVE_UP" in alerts
        assert "STOCK_MOVE_UP" not in alerts


class TestStockMoveDown:
    def test_triggers_at_threshold(self):
        alerts = classify_alerts("TEST", _make_stock(ret_1d=-5.0), {})
        assert "STOCK_MOVE_DOWN" in alerts

    def test_not_triggers_above(self):
        alerts = classify_alerts("TEST", _make_stock(ret_1d=-4.99), {})
        assert "STOCK_MOVE_DOWN" not in alerts

    def test_big_move_takes_priority(self):
        alerts = classify_alerts("TEST", _make_stock(ret_1d=-10.0), {})
        assert "STOCK_BIG_MOVE_DOWN" in alerts
        assert "STOCK_MOVE_DOWN" not in alerts


class TestStockBigMoveUp:
    def test_triggers_at_threshold(self):
        alerts = classify_alerts("TEST", _make_stock(ret_1d=10.0), {})
        assert "STOCK_BIG_MOVE_UP" in alerts

    def test_not_triggers_below(self):
        alerts = classify_alerts("TEST", _make_stock(ret_1d=9.99), {})
        assert "STOCK_BIG_MOVE_UP" not in alerts


class TestStockBigMoveDown:
    def test_triggers_at_threshold(self):
        alerts = classify_alerts("TEST", _make_stock(ret_1d=-10.0), {})
        assert "STOCK_BIG_MOVE_DOWN" in alerts

    def test_not_triggers_above(self):
        alerts = classify_alerts("TEST", _make_stock(ret_1d=-9.99), {})
        assert "STOCK_BIG_MOVE_DOWN" not in alerts


class TestMoveIntensitySpike:
    def test_triggers_at_threshold(self):
        alerts = classify_alerts("TEST", _make_stock(move_intensity=2.5), {})
        assert "MOVE_INTENSITY_SPIKE" in alerts

    def test_not_triggers_below(self):
        alerts = classify_alerts("TEST", _make_stock(move_intensity=2.49), {})
        assert "MOVE_INTENSITY_SPIKE" not in alerts

    def test_no_move_intensity(self):
        alerts = classify_alerts("TEST", _make_stock(), {})
        assert "MOVE_INTENSITY_SPIKE" not in alerts


class TestIvRampHigh:
    def test_triggers_at_threshold(self):
        alerts = classify_alerts("TEST", _make_stock(), _make_options(atm_iv_change_5d=0.10))
        assert "IV_RAMP_HIGH" in alerts

    def test_not_triggers_below(self):
        alerts = classify_alerts("TEST", _make_stock(), _make_options(atm_iv_change_5d=0.09))
        assert "IV_RAMP_HIGH" not in alerts


class TestIvCrush:
    def test_triggers_at_threshold(self):
        alerts = classify_alerts("TEST", _make_stock(), _make_options(atm_iv_change_5d=-0.10))
        assert "IV_CRUSH" in alerts

    def test_not_triggers_above(self):
        alerts = classify_alerts("TEST", _make_stock(), _make_options(atm_iv_change_5d=-0.09))
        assert "IV_CRUSH" not in alerts


class TestOptionsSurfaceMoveHigh:
    def test_triggers_at_threshold(self):
        alerts = classify_alerts("TEST", _make_stock(), _make_options(actual_implied_move_pctile=0.80))
        assert "OPTIONS_SURFACE_MOVE_HIGH" in alerts

    def test_not_triggers_below(self):
        alerts = classify_alerts("TEST", _make_stock(), _make_options(actual_implied_move_pctile=0.79))
        assert "OPTIONS_SURFACE_MOVE_HIGH" not in alerts


class TestSkewExtreme:
    def test_triggers_with_history(self):
        """Z-score path: RR is extreme vs own trailing distribution."""
        # stdev must be > 0.01 for z-score path to fire
        rr_history = [0.05, 0.02, 0.08, 0.04, 0.03, 0.06]  # stdev ~0.022
        # Current RR = 0.50 → way outside the distribution
        alerts = classify_alerts(
            "TEST",
            _make_stock(),
            _make_options(opt_rr_25d=0.50),
            rr_history=rr_history,
        )
        assert "SKEW_EXTREME" in alerts

    def test_no_trigger_normal_rr(self):
        rr_history = [0.05, 0.04, 0.06, 0.05, 0.04, 0.05]
        alerts = classify_alerts(
            "TEST",
            _make_stock(),
            _make_options(opt_rr_25d=0.06),
            rr_history=rr_history,
        )
        assert "SKEW_EXTREME" not in alerts

    def test_fallback_no_history_high_rr(self):
        """Fallback path: no history, use |RR| >= 0.50 threshold."""
        alerts = classify_alerts(
            "TEST",
            _make_stock(),
            _make_options(opt_rr_25d=0.55),
            rr_history=None,
        )
        assert "SKEW_EXTREME" in alerts

    def test_fallback_no_history_low_rr(self):
        alerts = classify_alerts(
            "TEST",
            _make_stock(),
            _make_options(opt_rr_25d=0.30),
            rr_history=None,
        )
        assert "SKEW_EXTREME" not in alerts

    def test_below_abs_floor(self):
        """RR below skew_abs_floor — no alert even with extreme z-score."""
        alerts = classify_alerts(
            "TEST",
            _make_stock(),
            _make_options(opt_rr_25d=0.10),
            rr_history=[0.01, 0.01, 0.01, 0.01, 0.01],
        )
        assert "SKEW_EXTREME" not in alerts

    def test_insufficient_history_uses_fallback(self):
        """Fewer than skew_min_obs → fallback path."""
        alerts = classify_alerts(
            "TEST",
            _make_stock(),
            _make_options(opt_rr_25d=0.55),
            rr_history=[0.10, 0.11],  # Only 2 obs, need 5
        )
        assert "SKEW_EXTREME" in alerts  # Falls through to |RR| >= 0.50


class TestStockDownIvUp:
    def test_triggers(self):
        alerts = classify_alerts(
            "TEST",
            _make_stock(ret_1d=-3.0),
            _make_options(atm_iv_change_5d=0.05),
        )
        assert "STOCK_DOWN_IV_UP" in alerts

    def test_not_triggers_stock_not_down_enough(self):
        alerts = classify_alerts(
            "TEST",
            _make_stock(ret_1d=-2.0),
            _make_options(atm_iv_change_5d=0.05),
        )
        assert "STOCK_DOWN_IV_UP" not in alerts


class TestStockUpIvDown:
    def test_triggers(self):
        alerts = classify_alerts(
            "TEST",
            _make_stock(ret_1d=3.0),
            _make_options(atm_iv_change_5d=-0.05),
        )
        assert "STOCK_UP_IV_DOWN" in alerts


class TestQuietBeforeCatalyst:
    """QUIET_BEFORE_CATALYST fires when hard catalyst <=14d but no IV buildup."""

    def test_triggers_classic_case(self):
        alerts = classify_alerts(
            "TEST",
            _make_stock(ret_1d=0.5),
            _make_options(
                is_hard_catalyst=1,
                catalyst_days=10,
                atm_iv_change_5d=0.01,
                actual_implied_move_pctile=0.30,
                opt_event_premium="NO",
            ),
        )
        assert "QUIET_BEFORE_CATALYST" in alerts

    def test_not_triggers_if_iv_ramping(self):
        alerts = classify_alerts(
            "TEST",
            _make_stock(ret_1d=0.5),
            _make_options(
                is_hard_catalyst=1,
                catalyst_days=10,
                atm_iv_change_5d=0.12,  # IV is building
                actual_implied_move_pctile=0.30,
                opt_event_premium="NO",
            ),
        )
        assert "QUIET_BEFORE_CATALYST" not in alerts

    def test_not_triggers_if_surface_move_high(self):
        alerts = classify_alerts(
            "TEST",
            _make_stock(ret_1d=0.5),
            _make_options(
                is_hard_catalyst=1,
                catalyst_days=10,
                atm_iv_change_5d=0.01,
                actual_implied_move_pctile=0.50,  # Event premium visible
                opt_event_premium="NO",
            ),
        )
        assert "QUIET_BEFORE_CATALYST" not in alerts

    def test_not_triggers_if_event_premium_yes(self):
        alerts = classify_alerts(
            "TEST",
            _make_stock(ret_1d=0.5),
            _make_options(
                is_hard_catalyst=1,
                catalyst_days=10,
                atm_iv_change_5d=0.01,
                actual_implied_move_pctile=0.30,
                opt_event_premium="YES",
            ),
        )
        assert "QUIET_BEFORE_CATALYST" not in alerts

    def test_not_triggers_if_catalyst_too_far(self):
        alerts = classify_alerts(
            "TEST",
            _make_stock(ret_1d=0.5),
            _make_options(
                is_hard_catalyst=1,
                catalyst_days=15,  # > 14
                atm_iv_change_5d=0.01,
                actual_implied_move_pctile=0.30,
                opt_event_premium="NO",
            ),
        )
        assert "QUIET_BEFORE_CATALYST" not in alerts

    def test_not_triggers_if_not_hard_catalyst(self):
        alerts = classify_alerts(
            "TEST",
            _make_stock(ret_1d=0.5),
            _make_options(
                is_hard_catalyst=0,
                catalyst_days=10,
                atm_iv_change_5d=0.01,
                actual_implied_move_pctile=0.30,
                opt_event_premium="NO",
            ),
        )
        assert "QUIET_BEFORE_CATALYST" not in alerts

    def test_boundary_catalyst_days_14(self):
        """Exactly 14 days should still trigger."""
        alerts = classify_alerts(
            "TEST",
            _make_stock(ret_1d=0.5),
            _make_options(
                is_hard_catalyst=1,
                catalyst_days=14,
                atm_iv_change_5d=0.01,
                actual_implied_move_pctile=0.30,
                opt_event_premium="NO",
            ),
        )
        assert "QUIET_BEFORE_CATALYST" in alerts


class TestPostEventFade:
    def test_triggers(self):
        alerts = classify_alerts(
            "TEST",
            _make_stock(ret_1d=-3.0, ret_5d=15.0),
            {},
        )
        assert "POST_EVENT_FADE" in alerts

    def test_not_triggers_5d_below_threshold(self):
        alerts = classify_alerts(
            "TEST",
            _make_stock(ret_1d=-3.0, ret_5d=14.9),
            {},
        )
        assert "POST_EVENT_FADE" not in alerts


class TestPostEventBounce:
    def test_triggers(self):
        alerts = classify_alerts(
            "TEST",
            _make_stock(ret_1d=3.0, ret_5d=-15.0),
            {},
        )
        assert "POST_EVENT_BOUNCE" in alerts

    def test_not_triggers_5d_above_threshold(self):
        alerts = classify_alerts(
            "TEST",
            _make_stock(ret_1d=3.0, ret_5d=-14.9),
            {},
        )
        assert "POST_EVENT_BOUNCE" not in alerts


class TestReactionMismatch:
    """Big stock move but options didn't reprice — stale data or structural anomaly."""

    def test_triggers_big_up_no_iv_change(self):
        alerts = classify_alerts(
            "TEST",
            _make_stock(ret_1d=6.0),
            _make_options(atm_iv_change_5d=0.01),
        )
        assert "REACTION_MISMATCH" in alerts

    def test_triggers_big_down_no_iv_change(self):
        alerts = classify_alerts(
            "TEST",
            _make_stock(ret_1d=-5.0),
            _make_options(atm_iv_change_5d=-0.01),
        )
        assert "REACTION_MISMATCH" in alerts

    def test_triggers_no_iv_data(self):
        """Missing IV data should still fire since isnan(iv_change) → abs < 0.02."""
        alerts = classify_alerts(
            "TEST",
            _make_stock(ret_1d=7.0),
            {},  # No IV data at all
        )
        assert "REACTION_MISMATCH" in alerts

    def test_not_triggers_small_move(self):
        alerts = classify_alerts(
            "TEST",
            _make_stock(ret_1d=4.99),
            _make_options(atm_iv_change_5d=0.01),
        )
        assert "REACTION_MISMATCH" not in alerts

    def test_not_triggers_if_iv_repriced(self):
        alerts = classify_alerts(
            "TEST",
            _make_stock(ret_1d=6.0),
            _make_options(atm_iv_change_5d=0.05),
        )
        assert "REACTION_MISMATCH" not in alerts


# ---------------------------------------------------------------------------
# No-alert cases
# ---------------------------------------------------------------------------


class TestNoAlerts:
    def test_flat_day(self):
        alerts = classify_alerts("TEST", _make_stock(ret_1d=0.5, move_intensity=0.8), {})
        assert alerts == []

    def test_missing_data(self):
        alerts = classify_alerts("TEST", {}, {})
        assert alerts == []


# ---------------------------------------------------------------------------
# Multiple alerts
# ---------------------------------------------------------------------------


class TestMultipleAlerts:
    def test_big_move_with_intensity_spike(self):
        alerts = classify_alerts(
            "TEST",
            _make_stock(ret_1d=12.0, move_intensity=3.0),
            {},
        )
        assert "STOCK_BIG_MOVE_UP" in alerts
        assert "MOVE_INTENSITY_SPIKE" in alerts
        assert "REACTION_MISMATCH" in alerts  # big move + no IV data

    def test_quiet_before_catalyst_and_skew(self):
        alerts = classify_alerts(
            "TEST",
            _make_stock(ret_1d=0.0),
            _make_options(
                is_hard_catalyst=1,
                catalyst_days=7,
                atm_iv_change_5d=0.01,
                actual_implied_move_pctile=0.20,
                opt_event_premium="NO",
                opt_rr_25d=0.60,
            ),
            rr_history=None,
        )
        assert "QUIET_BEFORE_CATALYST" in alerts
        assert "SKEW_EXTREME" in alerts


# ---------------------------------------------------------------------------
# format_watch_md
# ---------------------------------------------------------------------------


class TestFormatWatchMd:
    def test_basic_output(self):
        d = {
            "as_of_date": "2026-03-28",
            "watchlist_size": 2,
            "n_alerted": 1,
            "generated_at": "2026-03-28T21:00:00Z",
            "rows": [
                {
                    "ticker": "CELC",
                    "tier": "A",
                    "actionable_rank": 3,
                    "return_1d_pct": 12.5,
                    "return_5d_pct": 8.2,
                    "move_intensity": 3.1,
                    "atm_iv_change_5d": 0.045,
                    "alerts": ["STOCK_BIG_MOVE_UP", "MOVE_INTENSITY_SPIKE"],
                    "n_alerts": 2,
                },
            ],
        }
        md = format_watch_md(d)
        assert "# Price Action Watch" in md
        assert "CELC" in md
        assert "STOCK_BIG_MOVE_UP" in md

    def test_no_alerts(self):
        d = {
            "as_of_date": "2026-03-28",
            "watchlist_size": 5,
            "n_alerted": 0,
            "generated_at": "2026-03-28T21:00:00Z",
            "rows": [],
        }
        md = format_watch_md(d)
        assert "No alerts triggered" in md


# ---------------------------------------------------------------------------
# Thresholds consistency
# ---------------------------------------------------------------------------


class TestThresholdsConsistency:
    def test_all_expected_keys(self):
        expected = {
            "stock_move_up",
            "stock_move_down",
            "stock_big_move_up",
            "stock_big_move_down",
            "move_intensity_spike",
            "iv_ramp_high",
            "iv_crush",
            "surface_move_high",
            "skew_zscore",
            "skew_abs_floor",
            "skew_min_obs",
        }
        assert set(THRESHOLDS.keys()) == expected

    def test_big_move_exceeds_normal_move(self):
        assert THRESHOLDS["stock_big_move_up"] > THRESHOLDS["stock_move_up"]
        assert THRESHOLDS["stock_big_move_down"] < THRESHOLDS["stock_move_down"]
