"""Tests for common.stats.cross_sectional module."""
import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.stats.cross_sectional import (
    fama_macbeth,
    newey_west_se,
    ols_regression,
    run_incremental_test,
)


class TestOLSRegression:
    def test_simple_regression(self):
        """OLS on y = 2 + 3*x with no noise."""
        np.random.seed(42)
        n = 100
        x = np.random.randn(n)
        y = 2.0 + 3.0 * x
        X = np.column_stack([np.ones(n), x])
        result = ols_regression(y, X, ["intercept", "x"])
        assert abs(result["coefficients"]["intercept"] - 2.0) < 1e-10
        assert abs(result["coefficients"]["x"] - 3.0) < 1e-10
        assert result["r_squared"] > 0.999

    def test_noisy_regression(self):
        """OLS on y = 1 + 2*x + noise recovers approximately."""
        np.random.seed(42)
        n = 200
        x = np.random.randn(n)
        y = 1.0 + 2.0 * x + np.random.randn(n) * 0.5
        X = np.column_stack([np.ones(n), x])
        result = ols_regression(y, X, ["intercept", "x"])
        assert abs(result["coefficients"]["intercept"] - 1.0) < 0.2
        assert abs(result["coefficients"]["x"] - 2.0) < 0.2
        assert result["t_stats"]["x"] > 5.0

    def test_underdetermined(self):
        """OLS with more features than observations returns error."""
        y = np.array([1.0, 2.0])
        X = np.array([[1, 2, 3], [4, 5, 6]])
        result = ols_regression(y, X)
        assert "error" in result


class TestNeweyWest:
    def test_iid_series(self):
        """NW SE on iid series should be close to classical SE."""
        np.random.seed(42)
        series = np.random.randn(100)
        nw = newey_west_se(series, lags=3)
        classical = np.std(series, ddof=1) / np.sqrt(len(series))
        assert abs(nw - classical) < 0.02

    def test_autocorrelated_series(self):
        """NW SE on autocorrelated series should be larger than classical."""
        np.random.seed(42)
        n = 200
        series = np.zeros(n)
        series[0] = np.random.randn()
        for i in range(1, n):
            series[i] = 0.7 * series[i - 1] + np.random.randn()
        nw = newey_west_se(series, lags=6)
        classical = np.std(series, ddof=1) / np.sqrt(n)
        assert nw > classical  # NW should be larger for autocorrelated data

    def test_short_series(self):
        """NW on very short series doesn't crash."""
        assert not math.isnan(newey_west_se(np.array([1.0, 2.0]), lags=1))
        assert math.isnan(newey_west_se(np.array([1.0]), lags=1))


class TestFamaMacBeth:
    def _make_snapshots(self, n_months=24, n_stocks=50, beta_true=0.5):
        """Create synthetic snapshots with known signal-return relationship."""
        np.random.seed(42)
        snapshots = {}
        for m in range(n_months):
            date = f"2024-{m + 1:02d}-01"
            rows = []
            for i in range(n_stocks):
                signal = np.random.randn()
                fwd = beta_true * signal + np.random.randn() * 2.0
                rows.append({
                    "ticker": f"T{i}",
                    "eligible": "1.0",
                    "signal_a": str(signal),
                    "fwd_excess_xbi_63d": str(fwd),
                })
            snapshots[date] = rows
        return snapshots

    def test_detects_real_signal(self):
        """FM should find a significant coefficient for a real signal."""
        snapshots = self._make_snapshots(beta_true=0.5)
        result = fama_macbeth(
            snapshots, "fwd_excess_xbi_63d", ["signal_a"],
            nw_lags=3, zscore_x=True,
        )
        assert "error" not in result
        sig = result["signals"]["signal_a"]
        assert sig["mean_coefficient"] > 0
        assert abs(sig["newey_west_t"]) > 2.0

    def test_detects_noise(self):
        """FM should NOT find significance for pure noise."""
        snapshots = self._make_snapshots(beta_true=0.0)
        result = fama_macbeth(
            snapshots, "fwd_excess_xbi_63d", ["signal_a"],
            nw_lags=3, zscore_x=True,
        )
        sig = result["signals"]["signal_a"]
        assert abs(sig["newey_west_t"]) < 2.0

    def test_incremental_test(self):
        """Incremental test should detect a signal beyond controls."""
        np.random.seed(42)
        snapshots = {}
        for m in range(36):
            date = f"2024-{m + 1:02d}-01"
            rows = []
            for i in range(80):
                ctrl = np.random.randn()
                cand = np.random.randn()
                fwd = 0.3 * ctrl + 0.5 * cand + np.random.randn() * 2
                rows.append({
                    "ticker": f"T{i}",
                    "eligible": "1.0",
                    "control_signal": str(ctrl),
                    "candidate_signal": str(cand),
                    "fwd_excess_xbi_63d": str(fwd),
                })
            snapshots[date] = rows

        result = run_incremental_test(
            snapshots, "candidate_signal", ["control_signal"],
        )
        assert result["verdict"] == "INCREMENTAL"
