"""Tests for common.stats.multiple_testing module."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.stats.multiple_testing import benjamini_hochberg, hansen_spa, whites_reality_check


class TestBenjaminiHochberg:
    def test_all_significant(self):
        """All very small p-values should all be rejected."""
        pvals = {"sig_a": 0.001, "sig_b": 0.002, "sig_c": 0.003}
        result = benjamini_hochberg(pvals, alpha=0.10)
        assert result["n_rejected"] == 3
        assert len(result["rejected_names"]) == 3

    def test_none_significant(self):
        """Large p-values should not be rejected."""
        pvals = {"a": 0.5, "b": 0.6, "c": 0.8}
        result = benjamini_hochberg(pvals, alpha=0.10)
        assert result["n_rejected"] == 0

    def test_partial_rejection(self):
        """Mix of significant and non-significant should correctly partition."""
        pvals = {"real": 0.001, "noise_1": 0.4, "noise_2": 0.7}
        result = benjamini_hochberg(pvals, alpha=0.10)
        assert result["results"]["real"]["rejected"]
        assert not result["results"]["noise_1"]["rejected"]
        assert not result["results"]["noise_2"]["rejected"]

    def test_q_values_monotone(self):
        """Q-values should be monotonically increasing with p-values."""
        pvals = {"a": 0.01, "b": 0.05, "c": 0.10, "d": 0.20, "e": 0.50}
        result = benjamini_hochberg(pvals, alpha=0.10)
        q_vals = [result["results"][k]["q_value"] for k in sorted(pvals, key=pvals.get)]
        for i in range(len(q_vals) - 1):
            assert q_vals[i] <= q_vals[i + 1]

    def test_list_input(self):
        """Should work with list input too."""
        result = benjamini_hochberg([0.01, 0.05, 0.50], alpha=0.10)
        assert result["n_tests"] == 3


class TestWhitesRealityCheck:
    def test_clear_winner(self):
        """Strategy with large positive mean should be significant."""
        np.random.seed(42)
        T = 60
        stats = {
            "good": list(np.random.randn(T) * 0.01 + 0.03),
            "noise_1": list(np.random.randn(T) * 0.05),
            "noise_2": list(np.random.randn(T) * 0.05),
        }
        result = whites_reality_check(stats, n_bootstrap=5000, block_length=4, seed=42)
        assert result["best_strategy"] == "good"
        assert result["significant_at_05"]

    def test_all_noise(self):
        """All noise strategies should not be significant."""
        np.random.seed(42)
        T = 60
        stats = {
            f"noise_{i}": list(np.random.randn(T) * 0.05)
            for i in range(10)
        }
        result = whites_reality_check(stats, n_bootstrap=5000, seed=42)
        # With all noise, best may or may not be significant
        # but p-value should be > 0.05 most of the time
        assert result["wrc_p_value"] > 0.01  # not wildly significant


class TestHansenSPA:
    def test_basic(self):
        """Hansen SPA runs without error."""
        np.random.seed(42)
        T = 48
        bench = list(np.random.randn(T) * 0.02)
        strats = {
            "better": list(np.random.randn(T) * 0.02 + 0.02),
            "worse": list(np.random.randn(T) * 0.02 - 0.01),
        }
        result = hansen_spa(bench, strats, n_bootstrap=2000, seed=42)
        assert result["best_strategy"] == "better"
        assert "spa_p_value" in result
