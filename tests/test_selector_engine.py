"""Tests for selector_engine.py — Spec 050."""

import math

import pytest

from selector_engine import (
    DEFAULT_SELECTOR_CONFIG,
    SELECTOR_COLUMNS,
    BlockWeight,
    SelectorConfig,
    SignalSpec,
    _compute_block_score,
    _compute_cohort_stats,
    _score_signal,
    compute_selector_scores,
)

# ---------------------------------------------------------------------------
# Fixtures: minimal row factories
# ---------------------------------------------------------------------------


def _make_row(**overrides):
    """Build a csv_row dict with reasonable defaults for all selector signals."""
    base = {
        # Clinical
        "clinical_optionality_pct_dev": 0.65,
        "program_count": 3,
        "program_diversification": 0.50,
        "endpoint_strength_score": 0.70,
        "design_quality_score": 0.60,
        "readout_density_90": 2.0,
        "single_asset_risk": "no",
        "execution_momentum": 0.5,
        # Catalyst
        "catalyst_decay_w": 0.80,
        "binary_quality_score": 0.70,
        "cat_priority": 2,
        "catalyst_strength": "NEAR",
        "catalyst_family": "REGULATORY",
        # Survivability
        "financial_score": 0.60,
        "severity": "SEV1",
        "runway_bucket": "adequate",
        # Institutional
        "coinvest_score_z": 1.2,
        "inst_delta_z": 0.8,
        "coinvest_recency_state": "fresh",
        # Market structure
        "de_vol_60d": 0.80,
        "de_beta_xbi_60d": 1.10,
        "de_drawdown": -0.15,
        "de_rsi_14d": 55.0,
    }
    base.update(overrides)
    return base


def _make_cohort(n=30, seed_offset=0):
    """Build a cohort of n rows with varying signal values."""
    rows = []
    for i in range(n):
        f = (i + seed_offset) / max(n - 1, 1)  # 0.0 → 1.0
        rows.append(
            _make_row(
                clinical_optionality_pct_dev=round(f, 4),
                program_count=max(1, int(f * 5)),
                program_diversification=round(f * 0.8, 4),
                endpoint_strength_score=round(0.3 + f * 0.5, 4),
                design_quality_score=round(0.2 + f * 0.6, 4),
                readout_density_90=round(f * 4, 2),
                execution_momentum=round(f, 4),
                catalyst_decay_w=round(f, 4),
                binary_quality_score=round(f * 0.9, 4),
                cat_priority=max(1, int((1 - f) * 5)),
                financial_score=round(0.2 + f * 0.6, 4),
                coinvest_score_z=round(-1 + f * 3, 4),
                inst_delta_z=round(-0.5 + f * 2, 4),
                de_vol_60d=round(0.4 + (1 - f) * 0.8, 4),
                de_beta_xbi_60d=round(0.5 + (1 - f) * 1.0, 4),
                de_drawdown=round(-0.4 + f * 0.3, 4),
                de_rsi_14d=round(30 + f * 40, 2),
            )
        )
    return rows


# ---------------------------------------------------------------------------
# Test: configuration invariants
# ---------------------------------------------------------------------------


class TestSelectorConfig:
    def test_default_block_weights_sum_to_one(self):
        cfg = DEFAULT_SELECTOR_CONFIG
        total = sum(bw.weight for bw in cfg.block_weights)
        assert abs(total - 1.0) < 1e-9

    def test_default_signal_weights_positive(self):
        cfg = DEFAULT_SELECTOR_CONFIG
        for signals in [
            cfg.clinical_signals,
            cfg.catalyst_signals,
            cfg.survivability_signals,
            cfg.institutional_signals,
            cfg.market_structure_signals,
        ]:
            for s in signals:
                assert s.weight > 0, f"{s.name} has non-positive weight"

    def test_config_is_frozen(self):
        cfg = DEFAULT_SELECTOR_CONFIG
        with pytest.raises(AttributeError):
            cfg.missing_signal_penalty = 0.5  # type: ignore[misc]

    def test_selector_columns_list(self):
        assert len(SELECTOR_COLUMNS) == 7
        assert "selector_score" in SELECTOR_COLUMNS
        assert "selector_rank_bucket" in SELECTOR_COLUMNS


# ---------------------------------------------------------------------------
# Test: cohort statistics
# ---------------------------------------------------------------------------


class TestCohortStats:
    def test_basic_stats(self):
        rows = [{"x": 1.0}, {"x": 3.0}, {"x": 5.0}]
        stats = _compute_cohort_stats(rows, "x")
        assert abs(stats.mean - 3.0) < 1e-9
        expected_std = math.sqrt((4 + 0 + 4) / 3)
        assert abs(stats.std - expected_std) < 1e-9

    def test_missing_values_ignored(self):
        rows = [{"x": 1.0}, {"x": ""}, {"x": 5.0}, {"x": None}]
        stats = _compute_cohort_stats(rows, "x")
        assert abs(stats.mean - 3.0) < 1e-9

    def test_single_value_degenerate(self):
        rows = [{"x": 42.0}]
        stats = _compute_cohort_stats(rows, "x")
        assert stats.std == 1.0  # degenerate fallback

    def test_all_missing(self):
        rows = [{"x": ""}, {"x": None}]
        stats = _compute_cohort_stats(rows, "x")
        assert stats.std == 1.0  # degenerate


# ---------------------------------------------------------------------------
# Test: signal scoring
# ---------------------------------------------------------------------------


class TestSignalScoring:
    def test_numeric_signal_z_score(self):
        """Higher value → higher score when higher_is_better=True."""
        rows = [{"val": 0.0}, {"val": 1.0}, {"val": 2.0}]
        stats = {"val": _compute_cohort_stats(rows, "val")}
        spec = SignalSpec("val", 1.0, higher_is_better=True)

        score_low, _ = _score_signal(rows[0], spec, stats)
        score_high, _ = _score_signal(rows[2], spec, stats)
        assert score_high > score_low

    def test_numeric_signal_inverted(self):
        """Higher value → lower score when higher_is_better=False."""
        rows = [{"val": 0.0}, {"val": 1.0}, {"val": 2.0}]
        stats = {"val": _compute_cohort_stats(rows, "val")}
        spec = SignalSpec("val", 1.0, higher_is_better=False)

        score_low, _ = _score_signal(rows[0], spec, stats)
        score_high, _ = _score_signal(rows[2], spec, stats)
        assert score_low > score_high

    def test_missing_numeric_flagged(self):
        row = {"val": ""}
        stats = {"val": _compute_cohort_stats([{"val": 1.0}, {"val": 2.0}], "val")}
        spec = SignalSpec("val", 1.0)
        score, is_missing = _score_signal(row, spec, stats)
        assert is_missing is True
        assert score == 0.0

    def test_categorical_signal(self):
        spec = SignalSpec("sev", 1.0, categorical=True, value_map=(("NONE", 0.0), ("SEV1", 0.5), ("SEV3", 1.0)))
        score_none, missing_none = _score_signal({"sev": "NONE"}, spec, {})
        score_sev3, missing_sev3 = _score_signal({"sev": "SEV3"}, spec, {})
        assert not missing_none
        assert not missing_sev3
        assert score_sev3 > score_none

    def test_categorical_missing(self):
        spec = SignalSpec("x", 1.0, categorical=True, value_map=(("A", 1.0),))
        _, is_missing = _score_signal({"x": None}, spec, {})
        assert is_missing is True

    def test_numeric_score_bounded(self):
        """Scores should be in [0, 1] after z→percentile rescaling."""
        rows = [{"val": -100.0}, {"val": 0.0}, {"val": 100.0}]
        stats = {"val": _compute_cohort_stats(rows, "val")}
        spec = SignalSpec("val", 1.0)
        for row in rows:
            score, _ = _score_signal(row, spec, stats)
            assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# Test: block scoring
# ---------------------------------------------------------------------------


class TestBlockScoring:
    def test_all_present(self):
        rows = _make_cohort(10)
        from selector_engine import _compute_cohort_stats as ccs

        stats = {}
        for key in [
            "clinical_optionality_pct_dev",
            "program_count",
            "program_diversification",
            "endpoint_strength_score",
            "design_quality_score",
            "readout_density_90",
            "execution_momentum",
        ]:
            stats[key] = ccs(rows, key)

        score, missing = _compute_block_score(rows[5], DEFAULT_SELECTOR_CONFIG.clinical_signals, stats, 0.10)
        assert 0.0 <= score <= 1.0
        assert missing == 0  # single_asset_risk is categorical, should resolve

    def test_all_missing(self):
        empty_row = {}
        score, missing = _compute_block_score(empty_row, DEFAULT_SELECTOR_CONFIG.clinical_signals, {}, 0.10)
        assert missing > 0
        assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# Test: full selector computation
# ---------------------------------------------------------------------------


class TestComputeSelectorScores:
    def test_empty_input(self):
        results = compute_selector_scores([])
        assert results == []

    def test_single_row(self):
        results = compute_selector_scores([_make_row()])
        assert len(results) == 1
        assert results[0].selector_score == 0.5  # single row → median
        assert results[0].selector_rank_bucket == "top10"

    def test_deterministic(self):
        """Same inputs produce identical outputs."""
        rows = _make_cohort(30)
        r1 = compute_selector_scores(rows)
        r2 = compute_selector_scores(rows)
        for a, b in zip(r1, r2):
            assert a == b

    def test_percentile_distribution(self):
        """All scores should be in [0, 1]."""
        rows = _make_cohort(50)
        results = compute_selector_scores(rows)
        for r in results:
            assert 0.0 <= r.selector_score <= 1.0

    def test_rank_bucket_assignment(self):
        """Check that rank buckets are assigned correctly."""
        rows = _make_cohort(150)
        results = compute_selector_scores(rows)
        buckets = [r.selector_rank_bucket for r in results]
        assert buckets.count("top10") == 10
        assert buckets.count("top30") == 20  # 30-10
        assert buckets.count("top60") == 30  # 60-30
        assert buckets.count("top120") == 60  # 120-60
        assert buckets.count("below") == 30  # 150-120

    def test_higher_quality_row_scores_higher(self):
        """A row with all-better signals should outscore an all-worse row."""
        good = _make_row(
            clinical_optionality_pct_dev=0.95,
            program_count=5,
            endpoint_strength_score=0.95,
            catalyst_decay_w=0.95,
            binary_quality_score=0.95,
            financial_score=0.90,
            severity="NONE",
            coinvest_score_z=2.5,
            inst_delta_z=2.0,
            de_vol_60d=0.3,
            de_beta_xbi_60d=0.5,
        )
        bad = _make_row(
            clinical_optionality_pct_dev=0.05,
            program_count=1,
            endpoint_strength_score=0.10,
            catalyst_decay_w=0.05,
            binary_quality_score=0.10,
            financial_score=0.10,
            severity="SEV2",
            coinvest_score_z=-1.5,
            inst_delta_z=-1.0,
            de_vol_60d=1.5,
            de_beta_xbi_60d=2.0,
        )
        # Add neutral filler so z-scoring has a real distribution
        filler = _make_cohort(28)
        rows = [good, bad] + filler
        results = compute_selector_scores(rows)
        assert results[0].selector_score > results[1].selector_score

    def test_missing_signals_penalized(self):
        """Rows with missing data should score lower than complete rows."""
        complete = _make_row()
        incomplete = _make_row()
        # Remove several signals
        for key in [
            "coinvest_score_z",
            "inst_delta_z",
            "endpoint_strength_score",
            "binary_quality_score",
            "financial_score",
        ]:
            incomplete[key] = ""
        filler = _make_cohort(28)
        rows = [complete, incomplete] + filler
        results = compute_selector_scores(rows)
        assert results[0].selector_score > results[1].selector_score

    def test_block_scores_populated(self):
        rows = _make_cohort(20)
        results = compute_selector_scores(rows)
        for r in results:
            assert 0.0 <= r.clinical_block <= 1.0
            assert 0.0 <= r.catalyst_block <= 1.0
            assert 0.0 <= r.survivability_block <= 1.0
            assert 0.0 <= r.institutional_block <= 1.0
            assert 0.0 <= r.market_structure_block <= 1.0

    def test_custom_config(self):
        """Custom block weights should change relative ordering."""
        # Build rows where clinical and institutional signals conflict:
        # Row 0: great clinical, poor institutional
        # Row 1: poor clinical, great institutional
        rows = _make_cohort(20)
        # Override two rows to create a conflict
        rows[0] = _make_row(
            clinical_optionality_pct_dev=0.95,
            endpoint_strength_score=0.95,
            coinvest_score_z=-1.0,
            inst_delta_z=-0.5,
        )
        rows[1] = _make_row(
            clinical_optionality_pct_dev=0.10,
            endpoint_strength_score=0.10,
            coinvest_score_z=2.5,
            inst_delta_z=2.0,
        )
        # Default: clinical=35%, institutional=10% → row 0 should outscore row 1
        r_default = compute_selector_scores(rows)
        assert r_default[0].selector_score > r_default[1].selector_score

        # Institutional-heavy: clinical=5%, institutional=80% → row 1 should outscore row 0
        cfg = SelectorConfig(
            block_weights=(
                BlockWeight("clinical", 0.05),
                BlockWeight("catalyst", 0.05),
                BlockWeight("survivability", 0.05),
                BlockWeight("institutional", 0.80),
                BlockWeight("market_structure", 0.05),
            ),
        )
        r_custom = compute_selector_scores(rows, config=cfg)
        assert r_custom[1].selector_score > r_custom[0].selector_score


# ---------------------------------------------------------------------------
# Golden record tests
# ---------------------------------------------------------------------------


class TestGoldenRecords:
    """Known input/output pairs for regression testing."""

    def test_three_row_golden(self):
        """Three-row cohort with known relative ordering."""
        rows = [
            _make_row(  # Best: high everything
                clinical_optionality_pct_dev=0.90,
                catalyst_decay_w=0.90,
                financial_score=0.80,
                coinvest_score_z=2.0,
                de_vol_60d=0.40,
            ),
            _make_row(  # Middle: average
                clinical_optionality_pct_dev=0.50,
                catalyst_decay_w=0.50,
                financial_score=0.50,
                coinvest_score_z=0.0,
                de_vol_60d=0.80,
            ),
            _make_row(  # Worst: low everything
                clinical_optionality_pct_dev=0.10,
                catalyst_decay_w=0.10,
                financial_score=0.20,
                coinvest_score_z=-1.5,
                de_vol_60d=1.40,
            ),
        ]
        results = compute_selector_scores(rows)
        # Verify ordering: best > middle > worst
        assert results[0].selector_score > results[1].selector_score
        assert results[1].selector_score > results[2].selector_score
        # Verify buckets (3 rows: all in top10)
        assert results[0].selector_rank_bucket == "top10"
