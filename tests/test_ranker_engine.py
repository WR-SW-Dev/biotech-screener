"""Tests for ranker_engine.py — Spec 050."""

import pytest

from ranker_engine import (
    DEFAULT_RANKER_CONFIG,
    RANKER_COLUMNS,
    RankerConfig,
    _check_activation_gate,
    compute_ranker_adjustments,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_row(**overrides):
    """Build a csv_row dict with reasonable defaults for ranker signals."""
    base = {
        # Gate signals
        "catalyst_days": 60,
        "opt_has_data": "1",
        # Options block
        "actual_implied_move_pctile": 0.65,
        "opt_event_premium": 0.30,
        "opt_term_slope": 0.10,
        "ovf_composite": 0.55,
        "opt_rr_25d": -0.02,
        "opt_iv_regime": "NORMAL",
        # Institutional block
        "inst_delta_z": 0.80,
        "coinvest_filing_age_days": 45,
        "inst_delta_net": 2,
        # AACT block
        "aact_execution_score": 0.60,
        "execution_momentum": 0.50,
        # Catalyst nuance
        "catalyst_family": "REGULATORY",
        "cat_priority": 1,
        "catalyst_type_tier": "T1",
        # Microstructure
        "total_volume_z": 0.50,
        "pre_event_put_call_ratio": 0.40,
    }
    base.update(overrides)
    return base


def _make_cohort(n=20):
    """Build a ranker-eligible cohort with varying signals."""
    rows = []
    for i in range(n):
        f = i / max(n - 1, 1)
        rows.append(
            _make_row(
                catalyst_days=max(1, int(10 + f * 100)),
                actual_implied_move_pctile=round(f, 4),
                opt_event_premium=round(-0.2 + f * 0.6, 4),
                ovf_composite=round(f * 0.8, 4),
                inst_delta_z=round(-1 + f * 3, 4),
                coinvest_filing_age_days=max(1, int((1 - f) * 120)),
                inst_delta_net=int(-2 + f * 6),
                aact_execution_score=round(f, 4),
                execution_momentum=round(f * 0.8, 4),
                total_volume_z=round(-1 + f * 2, 4),
                pre_event_put_call_ratio=round(0.2 + (1 - f) * 0.6, 4),
            )
        )
    return rows


# ---------------------------------------------------------------------------
# Test: configuration
# ---------------------------------------------------------------------------


class TestRankerConfig:
    def test_default_block_weights_sum_to_one(self):
        cfg = DEFAULT_RANKER_CONFIG
        total = (
            cfg.options_weight
            + cfg.institutional_weight
            + cfg.aact_weight
            + cfg.catalyst_nuance_weight
            + cfg.microstructure_weight
        )
        assert abs(total - 1.0) < 1e-9

    def test_config_is_frozen(self):
        cfg = DEFAULT_RANKER_CONFIG
        with pytest.raises(AttributeError):
            cfg.max_adjustment_pct = 0.5  # type: ignore[misc]

    def test_ranker_columns_list(self):
        assert len(RANKER_COLUMNS) == 6
        assert "ranker_active" in RANKER_COLUMNS
        assert "final_score" in RANKER_COLUMNS


# ---------------------------------------------------------------------------
# Test: activation gate
# ---------------------------------------------------------------------------


class TestActivationGate:
    def test_active_when_all_conditions_met(self):
        row = _make_row(catalyst_days=60, opt_has_data="1")
        active, reason = _check_activation_gate(row, "top30", DEFAULT_RANKER_CONFIG)
        assert active is True
        assert reason == ""

    def test_inactive_wrong_bucket(self):
        row = _make_row()
        active, reason = _check_activation_gate(row, "top120", DEFAULT_RANKER_CONFIG)
        assert active is False
        assert "bucket" in reason

    def test_inactive_below_bucket(self):
        row = _make_row()
        active, reason = _check_activation_gate(row, "below", DEFAULT_RANKER_CONFIG)
        assert active is False

    def test_inactive_no_catalyst(self):
        row = _make_row(catalyst_days=0)
        active, reason = _check_activation_gate(row, "top30", DEFAULT_RANKER_CONFIG)
        assert active is False
        assert "no_catalyst" in reason

    def test_inactive_catalyst_too_far(self):
        row = _make_row(catalyst_days=200)
        active, reason = _check_activation_gate(row, "top30", DEFAULT_RANKER_CONFIG)
        assert active is False
        assert "catalyst_too_far" in reason

    def test_inactive_no_options_when_required(self):
        """Options gate only applies when activation_require_options=True."""
        cfg = RankerConfig(activation_require_options=True)
        row = _make_row(opt_has_data="0")
        active, reason = _check_activation_gate(row, "top10", cfg)
        assert active is False
        assert "no_options_data" in reason

    def test_active_no_options_when_not_required(self):
        """Default config does not require options (analyst rank model)."""
        row = _make_row(opt_has_data="0")
        active, reason = _check_activation_gate(row, "top10", DEFAULT_RANKER_CONFIG)
        assert active is True  # options gate disabled by default

    def test_boundary_catalyst_days_120(self):
        row = _make_row(catalyst_days=120)
        active, _ = _check_activation_gate(row, "top30", DEFAULT_RANKER_CONFIG)
        assert active is True

    def test_boundary_catalyst_days_121(self):
        row = _make_row(catalyst_days=121)
        active, _ = _check_activation_gate(row, "top30", DEFAULT_RANKER_CONFIG)
        assert active is False


# ---------------------------------------------------------------------------
# Test: full ranker computation
# ---------------------------------------------------------------------------


class TestComputeRankerAdjustments:
    def test_empty_input(self):
        results = compute_ranker_adjustments([], [], [])
        assert results == []

    def test_inactive_row_passthrough(self):
        """Inactive rows get ranker_active=False, adjustment=0, final=selector."""
        row = _make_row(catalyst_days=0)  # no catalyst → gate fails
        results = compute_ranker_adjustments([row], [0.75], ["top30"])
        assert len(results) == 1
        assert results[0].ranker_active is False
        assert results[0].ranker_adjustment == 0.0
        assert results[0].final_score == 0.75

    def test_active_row_has_adjustment(self):
        rows = _make_cohort(10)
        scores = [0.5 + i * 0.05 for i in range(10)]
        buckets = ["top10"] * 10
        results = compute_ranker_adjustments(rows, scores, buckets)
        # At least some should be active with non-zero adjustment
        active_results = [r for r in results if r.ranker_active]
        assert len(active_results) > 0
        any_nonzero = any(r.ranker_adjustment != 0.0 for r in active_results)
        assert any_nonzero

    def test_deterministic(self):
        rows = _make_cohort(15)
        scores = [0.5 + i * 0.03 for i in range(15)]
        buckets = ["top30"] * 15
        r1 = compute_ranker_adjustments(rows, scores, buckets)
        r2 = compute_ranker_adjustments(rows, scores, buckets)
        for a, b in zip(r1, r2):
            assert a == b

    def test_bounding_enforced(self):
        """Ranker adjustment must not exceed ±max_adjustment_pct * selector_score."""
        rows = _make_cohort(20)
        scores = [0.6] * 20
        buckets = ["top10"] * 20
        cfg = RankerConfig(max_adjustment_pct=0.15)
        results = compute_ranker_adjustments(rows, scores, buckets, config=cfg)
        for r in results:
            if r.ranker_active:
                max_abs = 0.15 * max(0.6, 0.01)
                assert abs(r.ranker_adjustment) <= max_abs + 1e-9

    def test_bounding_with_extreme_signals(self):
        """Even with extreme signal values, adjustment stays bounded."""
        row = _make_row(
            actual_implied_move_pctile=100.0,
            inst_delta_z=50.0,
            aact_execution_score=100.0,
            total_volume_z=50.0,
        )
        results = compute_ranker_adjustments([row], [0.80], ["top10"])
        assert len(results) == 1
        r = results[0]
        max_abs = 0.15 * 0.80
        assert abs(r.ranker_adjustment) <= max_abs + 1e-9

    def test_final_score_equals_selector_plus_adjustment(self):
        rows = _make_cohort(10)
        scores = [0.5 + i * 0.04 for i in range(10)]
        buckets = ["top30"] * 10
        results = compute_ranker_adjustments(rows, scores, buckets)
        for i, r in enumerate(results):
            expected = round(scores[i] + r.ranker_adjustment, 6)
            assert abs(r.final_score - expected) < 1e-9

    def test_mixed_active_inactive(self):
        """Mix of gate-passing and gate-failing rows."""
        rows = [
            _make_row(catalyst_days=60, opt_has_data="1"),  # active
            _make_row(catalyst_days=0, opt_has_data="1"),  # no catalyst
            _make_row(catalyst_days=60, opt_has_data="0"),  # active (options not required by default)
            _make_row(catalyst_days=200, opt_has_data="1"),  # too far
        ]
        scores = [0.8, 0.7, 0.6, 0.5]
        buckets = ["top10", "top30", "top30", "top30"]
        results = compute_ranker_adjustments(rows, scores, buckets)
        assert results[0].ranker_active is True
        assert results[1].ranker_active is False
        assert results[2].ranker_active is True  # options gate off by default
        assert results[3].ranker_active is False
        assert results[3].ranker_active is False

    def test_block_scores_populated(self):
        rows = _make_cohort(5)
        scores = [0.6] * 5
        buckets = ["top10"] * 5
        results = compute_ranker_adjustments(rows, scores, buckets)
        for r in results:
            if r.ranker_active:
                # Block scores should be finite
                assert r.options_block == r.options_block  # not NaN
                assert r.inst_block == r.inst_block
                assert r.aact_block == r.aact_block

    def test_custom_config_changes_gate(self):
        """Custom activation threshold changes which rows are active."""
        row = _make_row(catalyst_days=150)
        # Default: max 120d → inactive
        r_default = compute_ranker_adjustments([row], [0.7], ["top30"])
        assert r_default[0].ranker_active is False

        # Custom: max 200d → active
        cfg = RankerConfig(activation_max_catalyst_days=200)
        r_custom = compute_ranker_adjustments([row], [0.7], ["top30"], config=cfg)
        assert r_custom[0].ranker_active is True
