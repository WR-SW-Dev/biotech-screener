"""Tests for common.stats.robustness module."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.stats.robustness import leave_one_slice_out, multi_slice_robustness


class TestLeaveOneSliceOut:
    def _make_snapshots(self, n_months=24, n_stocks=60):
        """Create synthetic snapshots with known properties."""
        np.random.seed(42)
        snapshots = {}
        regimes = ["bear", "bull", "neutral"]
        for m in range(n_months):
            date = f"202{m // 12}-{(m % 12) + 1:02d}-01"
            regime = regimes[m % 3]
            rows = []
            for i in range(n_stocks):
                signal = np.random.randn()
                fwd = 0.3 * signal + np.random.randn() * 2
                rows.append({
                    "ticker": f"T{i}",
                    "eligible": "1.0",
                    "actionable_rank": str(i + 1),
                    "test_signal": str(signal),
                    "fwd_excess_xbi_63d": str(fwd),
                    "regime_63d": regime,
                    "market_cap_bucket": "small" if i < 30 else "micro",
                })
            snapshots[date] = rows
        return snapshots

    def test_basic_structure(self):
        """LOSO should produce results for each slice value."""
        snapshots = self._make_snapshots()
        result = leave_one_slice_out(
            snapshots, "test_signal", slice_col="regime_63d",
        )
        assert "full_sample" in result
        assert "leave_one_out" in result
        assert "stability_verdict" in result
        assert "bear" in result["leave_one_out"]
        assert "bull" in result["leave_one_out"]

    def test_no_slice_col(self):
        """Missing slice column should error gracefully."""
        snapshots = self._make_snapshots()
        result = leave_one_slice_out(
            snapshots, "test_signal", slice_col="nonexistent_col",
        )
        assert "error" in result

    def test_multi_slice(self):
        """Multi-slice robustness should test across dimensions."""
        snapshots = self._make_snapshots()
        result = multi_slice_robustness(
            snapshots, "test_signal", higher_is_better=True,
        )
        assert "overall_verdict" in result
        assert "year" in result["slices"]
        assert "regime" in result["slices"]
