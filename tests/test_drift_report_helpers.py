"""Unit tests for metric helper functions in scripts/run_drift_report.py.

Covers: _optionality_std, _composite_iqr, _catalyst_missing_pct_eligible,
_drawdown_coverage_pct, _parse_pipe_separated, _compute_gate_counts,
_compute_strength_counts.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from run_drift_report import (
    _catalyst_missing_pct_eligible,
    _composite_iqr,
    _compute_gate_counts,
    _compute_strength_counts,
    _drawdown_coverage_pct,
    _drawdown_rel_coverage_pct,
    _optionality_std,
    _parse_pipe_separated,
)

try:
    import pandas as pd
except ImportError:
    pytest.skip("pandas required for drift report tests", allow_module_level=True)


def _dev_row(**overrides) -> dict:
    """Build a minimal dev-archetype row with sensible defaults."""
    base = {
        "ticker": "ACME",
        "archetype": "drug_developer",
        "eligible": "1",
        "clinical_optionality_pct_dev": 0.5,
        "composite_score": 50.0,
        "composite_rank": 10,
        "catalyst_mode": "specific_days",
        "catalyst_source": "ctgov",
        "de_drawdown": -0.15,
        "de_drawdown_missing_reason": "",
        "de_drawdown_rel_xbi": -0.05,
        "tier_dev": "A",
        "ineligible_reasons": "",
        "actionable_rank": "1",
    }
    base.update(overrides)
    return base


def _make_rankings(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


# =============================================================================
# _optionality_std
# =============================================================================


class TestOptionalityStd:
    def test_normal_case(self):
        rows = [_dev_row(clinical_optionality_pct_dev=v) for v in [0.3, 0.5, 0.7]]
        result = _optionality_std(_make_rankings(rows))
        assert result is not None
        assert result > 0

    def test_single_row_returns_none(self):
        rows = [_dev_row()]
        result = _optionality_std(_make_rankings(rows))
        assert result is None

    def test_no_dev_tickers_returns_none(self):
        rows = [_dev_row(archetype="commercial_pharma")]
        result = _optionality_std(_make_rankings(rows))
        assert result is None


# =============================================================================
# _composite_iqr
# =============================================================================


class TestCompositeIqr:
    def test_normal_case(self):
        rows = [_dev_row(composite_score=float(i)) for i in range(1, 21)]
        result = _composite_iqr(_make_rankings(rows))
        assert result is not None
        assert result > 0

    def test_constant_values_zero_iqr(self):
        rows = [_dev_row(composite_score=50.0) for _ in range(20)]
        result = _composite_iqr(_make_rankings(rows))
        assert result is not None
        assert result == 0.0

    def test_too_few_values_returns_none(self):
        rows = [_dev_row(composite_score=50.0) for _ in range(3)]
        result = _composite_iqr(_make_rankings(rows))
        assert result is None


# =============================================================================
# _catalyst_missing_pct_eligible
# =============================================================================


class TestCatalystMissingPctEligible:
    def test_all_have_catalyst(self):
        rows = [
            _dev_row(catalyst_mode="specific_days"),
            _dev_row(catalyst_mode="blended_window"),
        ]
        result = _catalyst_missing_pct_eligible(_make_rankings(rows))
        assert result == 0.0

    def test_all_missing(self):
        rows = [
            _dev_row(catalyst_mode="missing"),
            _dev_row(catalyst_mode="missing"),
        ]
        result = _catalyst_missing_pct_eligible(_make_rankings(rows))
        assert result == 100.0

    def test_partial_missing(self):
        rows = [
            _dev_row(catalyst_mode="specific_days"),
            _dev_row(catalyst_mode="missing"),
        ]
        result = _catalyst_missing_pct_eligible(_make_rankings(rows))
        assert result == 50.0

    def test_ineligible_excluded(self):
        rows = [
            _dev_row(eligible="1", catalyst_mode="specific_days"),
            _dev_row(eligible="0", catalyst_mode="missing"),
        ]
        result = _catalyst_missing_pct_eligible(_make_rankings(rows))
        assert result == 0.0


# =============================================================================
# _drawdown_coverage_pct
# =============================================================================


class TestDrawdownCoveragePct:
    def test_all_covered(self):
        rows = [
            _dev_row(de_drawdown_missing_reason=""),
            _dev_row(de_drawdown_missing_reason=""),
        ]
        result = _drawdown_coverage_pct(_make_rankings(rows))
        assert result == 100.0

    def test_none_covered(self):
        rows = [
            _dev_row(de_drawdown_missing_reason="no_price_data"),
            _dev_row(de_drawdown_missing_reason="too_few_bars"),
        ]
        result = _drawdown_coverage_pct(_make_rankings(rows))
        assert result == 0.0

    def test_partial_coverage(self):
        rows = [
            _dev_row(de_drawdown_missing_reason=""),
            _dev_row(de_drawdown_missing_reason="stale"),
        ]
        result = _drawdown_coverage_pct(_make_rankings(rows))
        assert result == 50.0

    def test_no_dev_tickers(self):
        rows = [_dev_row(archetype="commercial_pharma")]
        result = _drawdown_coverage_pct(_make_rankings(rows))
        assert result is None


# =============================================================================
# _drawdown_rel_coverage_pct
# =============================================================================


class TestDrawdownRelCoveragePct:
    def test_all_covered(self):
        rows = [
            _dev_row(de_drawdown_rel_xbi=-0.05),
            _dev_row(de_drawdown_rel_xbi=-0.10),
        ]
        result = _drawdown_rel_coverage_pct(_make_rankings(rows))
        assert result is not None


# =============================================================================
# _parse_pipe_separated
# =============================================================================


class TestParsePipeSeparated:
    def test_single_value(self):
        assert _parse_pipe_separated("alpha") == ["alpha"]

    def test_multiple_values(self):
        assert _parse_pipe_separated("alpha|beta|gamma") == ["alpha", "beta", "gamma"]

    def test_empty_string(self):
        result = _parse_pipe_separated("")
        assert isinstance(result, list)


# =============================================================================
# _compute_gate_counts
# =============================================================================


class TestComputeGateCounts:
    def test_normal_gates(self):
        rows = [
            _dev_row(eligible="1", ineligible_reasons=""),
            _dev_row(eligible="0", ineligible_reasons="sev3_fundamental_red_flag"),
        ]
        result = _compute_gate_counts(_make_rankings(rows))
        assert isinstance(result, dict)


# =============================================================================
# _compute_strength_counts
# =============================================================================


class TestComputeStrengthCounts:
    def test_tier_distribution(self):
        rows = [
            _dev_row(tier_dev="A"),
            _dev_row(tier_dev="A"),
            _dev_row(tier_dev="B"),
            _dev_row(tier_dev="C"),
        ]
        result = _compute_strength_counts(_make_rankings(rows))
        assert isinstance(result, dict)
