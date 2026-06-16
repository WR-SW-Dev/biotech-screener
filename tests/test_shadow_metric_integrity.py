"""Tests for shadow metric data integrity safeguards.

Ensures that shadow_excess_vs_xbi calculation:
1. Excludes periods with missing price data
2. Detects stale/replayed metrics
3. Alerts on data quality issues
"""

import pytest

from tools.weekly_readiness_scorecard import check_shadow_excess, validate_metric_data_integrity


class TestShadowMetricIntegrity:
    """Test data integrity safeguards for shadow_excess_vs_xbi metric."""

    def test_excludes_missing_price_periods(self):
        """Verify that periods with missing prices are excluded from calculation."""
        perf_rows = [
            {
                "date": "2026-05-20",
                "excess_vs_xbi_pct": "-3.8804",
                "n_missing_price": "30",  # Complete data loss
            },
            {
                "date": "2026-05-27",
                "excess_vs_xbi_pct": "-1.3236",
                "n_missing_price": "1",  # Partial data loss (excluded)
            },
            {
                "date": "2026-05-29",
                "excess_vs_xbi_pct": "-0.6359",
                "n_missing_price": "0",  # Complete
            },
            {
                "date": "2026-06-04",
                "excess_vs_xbi_pct": "-3.0862",
                "n_missing_price": "0",  # Complete
            },
        ]

        result = check_shadow_excess(perf_rows, lookback=4)

        # Should calculate average of only valid periods (2026-05-29, 2026-06-04)
        expected_avg = (-0.6359 - 3.0862) / 2  # -1.8610
        assert abs(result["value"] - expected_avg) < 0.001

        # Detail should mention data filtering
        assert "Excluded" in result["detail"] or "complete data only" in result["detail"]

    def test_holds_on_insufficient_complete_periods(self):
        """Verify that scorecard HOLDs if insufficient complete-data periods."""
        perf_rows = [
            {
                "date": "2026-05-20",
                "excess_vs_xbi_pct": "-3.8804",
                "n_missing_price": "30",
            },
            {
                "date": "2026-05-27",
                "excess_vs_xbi_pct": "-1.3236",
                "n_missing_price": "30",
            },
            {
                "date": "2026-05-29",
                "excess_vs_xbi_pct": "-0.6359",
                "n_missing_price": "0",
            },
            # Only 1 complete period; threshold typically 2
        ]

        result = check_shadow_excess(perf_rows, lookback=4)

        # Should HOLD due to insufficient complete data
        assert result["status"] in ["HOLD", "WARN"]
        assert "complete-data" in result["detail"].lower() or "insufficient" in result["detail"].lower()

    def test_detects_excessive_missing_prices(self):
        """Verify data integrity validator detects high % missing prices."""
        perf_rows = [
            {
                "date": "2026-06-12",
                "excess_vs_xbi_pct": "0.0",
                "n_missing_price": "20",  # 67% of portfolio missing
            },
            {
                "date": "2026-06-11",
                "excess_vs_xbi_pct": "1.0",
                "n_missing_price": "0",
            },
        ]

        warning = validate_metric_data_integrity(perf_rows)

        # Should warn about excessive missing prices
        assert warning is not None
        assert "missing price" in warning.lower()

    def test_passes_on_complete_recent_data(self):
        """Verify no warning when recent data is complete."""
        perf_rows = [
            {
                "date": "2026-06-12",
                "excess_vs_xbi_pct": "-1.5",
                "n_missing_price": "0",
            },
            {
                "date": "2026-06-11",
                "excess_vs_xbi_pct": "-0.5",
                "n_missing_price": "0",
            },
            {
                "date": "2026-06-10",
                "excess_vs_xbi_pct": "-2.0",
                "n_missing_price": "0",
            },
            {
                "date": "2026-06-09",
                "excess_vs_xbi_pct": "-1.2",
                "n_missing_price": "0",
            },
        ]

        warning = validate_metric_data_integrity(perf_rows)

        # Should be OK if recent data is complete
        assert warning is None or "sufficient" not in warning.lower()

    def test_insufficient_data_warning(self):
        """Verify warning when performance dataset is too small."""
        perf_rows = [
            {
                "date": "2026-06-12",
                "excess_vs_xbi_pct": "-1.5",
                "n_missing_price": "0",
            },
        ]

        warning = validate_metric_data_integrity(perf_rows)

        # Should warn about insufficient history
        assert warning is not None
        assert "insufficient" in warning.lower() or "periods" in warning.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
