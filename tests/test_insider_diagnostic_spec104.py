"""
Spec 104: Insider Diagnostic Stabilization
Guard tests ensuring insider signal remains diagnostic-only,
never promoted to alpha without explicit decision.
"""

import json
import sys
from pathlib import Path

import pytest

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from run_screen_columns import SNAPSHOT_COLUMNS
from tools.measure_insider_coverage import measure_snapshot


class TestInsiderNotInAlphaRegistry:
    """Verify insider is NOT registered as active/required signal."""

    def test_insider_in_snapshot_columns(self):
        """Insider should be exported in SNAPSHOT_COLUMNS."""
        assert "insider_net_buy_value_90d" in SNAPSHOT_COLUMNS, "insider_net_buy_value_90d must be exported to CSV"

    def test_insider_not_in_selector_or_ranker(self):
        """Verify insider is NOT contributing to selector/ranker scoring."""
        try:
            from ranker_module import ranker_engine
        except ImportError:
            pytest.skip("ranker_module not available")

        try:
            from decision_engine import selector_engine
        except ImportError:
            pytest.skip("decision_engine not available")

        selector_signals = getattr(selector_engine, "SIGNALS", [])
        ranker_signals = getattr(ranker_engine, "SIGNALS", [])

        assert (
            "insider_net_buy_value_90d" not in selector_signals
        ), "insider_net_buy_value_90d must NOT be in selector signals"
        assert (
            "insider_net_buy_value_90d" not in ranker_signals
        ), "insider_net_buy_value_90d must NOT be in ranker signals"


class TestInsiderSemantics:
    """Verify blank vs zero distinction is preserved in measurement."""

    def test_measurement_script_distinguishes_blank_from_zero(self):
        """Test that measure_insider_coverage.py classifies blank separately from zero."""
        # Create minimal test snapshot
        test_snapshot_dir = Path("data/snapshots/2026-05-14_test")
        test_snapshot_dir.mkdir(parents=True, exist_ok=True)

        test_csv = test_snapshot_dir / "rankings.csv"
        csv_content = "ticker,insider_net_buy_value_90d\n" "TICK1,\n" "TICK2,0.0\n" "TICK3,100000\n" "TICK4,-50000\n"
        test_csv.write_text(csv_content)

        try:
            result = measure_snapshot(test_csv)
            assert result["blank_count"] == 1, "Should count 1 blank (empty string)"
            assert result["zero_count"] == 1, "Should count 1 zero (0.0)"
            assert result["positive_count"] == 1, "Should count 1 positive"
            assert result["negative_count"] == 1, "Should count 1 negative"
        finally:
            test_csv.unlink()
            test_snapshot_dir.rmdir()

    def test_blank_not_conflated_with_zero(self):
        """Verify measurement output keeps blank_pct and zero_pct separate."""
        test_snapshot_dir = Path("data/snapshots/2026-05-14_test2")
        test_snapshot_dir.mkdir(parents=True, exist_ok=True)

        test_csv = test_snapshot_dir / "rankings.csv"
        csv_content = "ticker,insider_net_buy_value_90d\n" "TICK1,\n" "TICK2,0.0\n" "TICK3,0.0\n" "TICK4,100\n"
        test_csv.write_text(csv_content)

        try:
            result = measure_snapshot(test_csv)
            assert result["blank_pct"] != result["zero_pct"], "blank_pct and zero_pct must be separate metrics"
        finally:
            test_csv.unlink()
            test_snapshot_dir.rmdir()


class TestInsiderNotInExpectationModel:
    """Verify insider_net_buy_value_90d is NOT consumed by ExpectationErrorModel."""

    def test_expectation_model_does_not_read_insider(self):
        """Code review: ExpectationErrorModel feature list excludes insider."""
        try:
            from event_ev.expectation_error_model import ExpectationErrorModel

            model = ExpectationErrorModel()
            required_features = getattr(model, "REQUIRED_FEATURES", [])

            assert (
                "insider_net_buy_value_90d" not in required_features
            ), "ExpectationErrorModel must NOT include insider_net_buy_value_90d"
        except ImportError:
            pytest.skip("ExpectationErrorModel not available")

    def test_insider_not_in_expectation_feature_fetch(self):
        """Verify expectation model feature fetcher excludes insider."""
        import inspect

        try:
            from event_ev.expectation_error_model import ExpectationErrorModel

            model = ExpectationErrorModel()

            # Check feature_fetch or _fetch_features method
            if hasattr(model, "_fetch_features"):
                source = inspect.getsource(model._fetch_features)
                assert "insider_net_buy_value_90d" not in source, "insider_net_buy_value_90d must not be fetched"
        except (ImportError, OSError):
            pytest.skip("ExpectationErrorModel or source unavailable")


class TestInsiderDiagnosticArtifacts:
    """Verify measurement script produces correct diagnostic artifacts."""

    def test_measurement_emits_json_per_snapshot(self):
        """Test that measure_snapshot outputs valid JSON structure."""
        test_snapshot_dir = Path("data/snapshots/2026-05-14_test3")
        test_snapshot_dir.mkdir(parents=True, exist_ok=True)

        test_csv = test_snapshot_dir / "rankings.csv"
        csv_content = "ticker,insider_net_buy_value_90d\n" "TICK1,100000\n" "TICK2,0.0\n"
        test_csv.write_text(csv_content)

        try:
            result = measure_snapshot(test_csv)

            # Verify JSON-serializable
            json_str = json.dumps(result)
            assert json_str is not None

            # Verify structure
            assert "total_rows" in result
            assert "blank_pct" in result
            assert "zero_pct" in result
            assert "nonblank_pct" in result
            assert "activity_pct" in result
        finally:
            test_csv.unlink()
            test_snapshot_dir.rmdir()

    def test_date_range_generator(self):
        """Test that date range generation works correctly."""
        from datetime import datetime

        from tools.measure_insider_coverage import _date_range

        dates = _date_range("2026-05-10", "2026-05-15")

        # Should have 6 consecutive days
        assert len(dates) == 6, "Should generate 6 consecutive days"

        # All dates should be valid
        for date_str in dates:
            try:
                datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                pytest.fail(f"Invalid date format: {date_str}")
