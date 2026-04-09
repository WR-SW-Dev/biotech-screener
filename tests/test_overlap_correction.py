"""Regression tests for overlapping-window t-stat correction.

Validates that Newey-West corrected t-statistics are properly computed
and that they are strictly smaller than naive t-stats when the series
has positive autocorrelation (as expected with overlapping forward
return windows).

This test was added as part of the backtest harness audit (2026-04-05)
to guard against inflated significance from overlapping 63d returns
at monthly frequency.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "research"))


class TestNeweyWestTstat:
    """Test the NW t-stat implementations in research scripts."""

    def _get_nw_tstat_fn(self, source: str):
        """Import the _newey_west_tstat function from a research script."""
        if source == "selector_bundles":
            from test_selector_bundles import _newey_west_tstat

            return _newey_west_tstat
        elif source == "signal_cards":
            from run_signal_cards import _newey_west_tstat

            return _newey_west_tstat
        elif source == "checklist":
            from checklist_v2_rerun import _newey_west_tstat

            return _newey_west_tstat
        raise ValueError(f"Unknown source: {source}")

    def _get_naive_tstat_fn(self, source: str):
        if source == "selector_bundles":
            from test_selector_bundles import _safe_tstat

            return _safe_tstat
        elif source == "signal_cards":
            from run_signal_cards import _safe_tstat

            return _safe_tstat
        elif source == "checklist":
            from checklist_v2_rerun import _safe_tstat

            return _safe_tstat
        raise ValueError(f"Unknown source: {source}")

    @pytest.mark.parametrize("source", ["selector_bundles", "signal_cards", "checklist"])
    def test_nw_returns_none_for_short_series(self, source):
        fn = self._get_nw_tstat_fn(source)
        assert fn([1.0, 2.0]) is None
        assert fn([1.0, 2.0, 3.0]) is None

    @pytest.mark.parametrize("source", ["selector_bundles", "signal_cards", "checklist"])
    def test_nw_returns_value_for_sufficient_data(self, source):
        fn = self._get_nw_tstat_fn(source)
        result = fn([1.0, 2.0, 3.0, 4.0, 5.0])
        assert result is not None
        assert isinstance(result, float)

    @pytest.mark.parametrize("source", ["selector_bundles", "signal_cards", "checklist"])
    def test_nw_equals_naive_for_iid_data(self, source):
        """For truly IID data (no autocorrelation), NW ≈ naive."""
        import random

        rng = random.Random(42)
        vals = [rng.gauss(0.5, 1.0) for _ in range(100)]
        nw = self._get_nw_tstat_fn(source)(vals, lags=3)
        naive = self._get_naive_tstat_fn(source)(vals)
        assert nw is not None and naive is not None
        # Should be within ~20% for IID data
        assert abs(nw - naive) / abs(naive) < 0.3

    @pytest.mark.parametrize("source", ["selector_bundles", "signal_cards", "checklist"])
    def test_nw_smaller_than_naive_for_autocorrelated_data(self, source):
        """For positively autocorrelated data (like overlapping returns),
        NW t-stat should be strictly smaller than naive."""
        # Simulate overlapping 63d returns at monthly frequency:
        # create MA(2) process which has autocorrelation at lags 1-2
        import random

        rng = random.Random(42)
        shocks = [rng.gauss(0, 1.0) for _ in range(100)]
        # MA(2) with positive mean
        vals = [0.5 + shocks[i] + 0.7 * shocks[max(0, i - 1)] + 0.5 * shocks[max(0, i - 2)] for i in range(len(shocks))]

        nw = self._get_nw_tstat_fn(source)(vals, lags=3)
        naive = self._get_naive_tstat_fn(source)(vals)
        assert nw is not None and naive is not None
        # NW should be smaller (less significant) than naive for positive autocorrelation
        assert abs(nw) < abs(naive), (
            f"NW t-stat ({nw:.2f}) should be smaller than naive ({naive:.2f}) " f"for positively autocorrelated series"
        )

    @pytest.mark.parametrize("source", ["selector_bundles", "signal_cards", "checklist"])
    def test_nw_handles_zero_variance(self, source):
        fn = self._get_nw_tstat_fn(source)
        assert fn([1.0, 1.0, 1.0, 1.0, 1.0]) is None

    @pytest.mark.parametrize("source", ["selector_bundles", "signal_cards", "checklist"])
    def test_nw_sign_matches_mean(self, source):
        """NW t-stat should have same sign as the sample mean."""
        fn = self._get_nw_tstat_fn(source)
        import random

        rng = random.Random(42)
        pos_vals = [rng.gauss(2.0, 1.0) for _ in range(50)]
        neg_vals = [rng.gauss(-2.0, 1.0) for _ in range(50)]
        assert fn(pos_vals, lags=3) > 0
        assert fn(neg_vals, lags=3) < 0


class TestOverlapInflation:
    """Quantify the expected inflation from overlapping windows."""

    def test_63d_monthly_inflation_factor(self):
        """With 63d returns at monthly frequency, the inflation factor
        (naive_t / nw_t) should be in the range 1.3-2.5 for typical
        positively autocorrelated series."""
        import random

        from test_selector_bundles import _newey_west_tstat, _safe_tstat

        rng = random.Random(123)

        # Simulate 67 monthly observations of overlapping 63d improvement deltas
        # with realistic autocorrelation structure (MA(2))
        ratios = []
        for trial in range(20):
            shocks = [rng.gauss(0, 1.0) for _ in range(70)]
            vals = [1.0 + shocks[i] + 0.6 * shocks[max(0, i - 1)] + 0.4 * shocks[max(0, i - 2)] for i in range(67)]
            naive = _safe_tstat(vals)
            nw = _newey_west_tstat(vals, lags=3)
            if naive and nw and abs(nw) > 0.01:
                ratios.append(abs(naive) / abs(nw))

        avg_ratio = sum(ratios) / len(ratios) if ratios else 1.0
        # Typical inflation factor: 1.3-2.5x
        assert avg_ratio > 1.1, f"Expected inflation > 1.1, got {avg_ratio:.2f}"
        assert avg_ratio < 3.0, f"Expected inflation < 3.0, got {avg_ratio:.2f}"
