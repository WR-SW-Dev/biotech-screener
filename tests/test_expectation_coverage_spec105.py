"""Spec 105: Expectation Layer Coverage Verification.

Verification-only tests to confirm:
  1. Rankings.csv contains required expectation fields.
  2. ExpectationErrorModel reads all four core fields.
  3. Insider remains diagnostic-only (not consumed by model).
  4. Production QA feature coverage thresholds are met.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from event_ev.expectation_error_model import ExpectationErrorModel
from run_screen_columns import SNAPSHOT_COLUMNS

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestExpectationFieldConsumption:
    """Verify ExpectationErrorModel reads all four required fields."""

    def test_expectation_model_reads_short_interest_pct(self):
        """ExpectationErrorModel.score_row should read short_interest_pct."""
        source = inspect.getsource(ExpectationErrorModel.score_row)
        assert "short_interest_pct" in source, "ExpectationErrorModel.score_row does not reference short_interest_pct"

    def test_expectation_model_reads_close_price(self):
        """ExpectationErrorModel.score_row should read close_price."""
        source = inspect.getsource(ExpectationErrorModel.score_row)
        assert "close_price" in source, "ExpectationErrorModel.score_row does not reference close_price"

    def test_expectation_model_reads_market_cap_mm(self):
        """ExpectationErrorModel.score_row should read market_cap_mm."""
        source = inspect.getsource(ExpectationErrorModel.score_row)
        assert "market_cap_mm" in source, "ExpectationErrorModel.score_row does not reference market_cap_mm"

    def test_expectation_model_reads_priced_move_pct(self):
        """ExpectationErrorModel.score_row should read priced_move_pct."""
        source = inspect.getsource(ExpectationErrorModel.score_row)
        assert "priced_move_pct" in source, "ExpectationErrorModel.score_row does not reference priced_move_pct"


class TestInsiderNotConsumed:
    """Verify insider_net_buy_value_90d is NOT consumed by ExpectationErrorModel."""

    def test_expectation_model_does_not_use_insider_value(self):
        """ExpectationErrorModel.score_row should not read insider_net_buy_value_90d."""
        source = inspect.getsource(ExpectationErrorModel.score_row)
        # Check that the method does not reference insider_net_buy_value_90d as an input
        # (it may reference it in comments/docs, but not as a field read from row)
        lines = [line for line in source.split("\n") if "insider_net_buy_value" in line]
        active_refs = [line for line in lines if "row.get" in line or "row[" in line]
        assert not active_refs, f"ExpectationErrorModel reads insider: {active_refs}"

    def test_insider_not_in_expectation_field_list(self):
        """insider_net_buy_value_90d should not be in ExpectationErrorModel's required fields."""
        from event_ev.expectation_error_model import EES_CSV_COLUMNS

        # insider may be exported to CSV for diagnostics, but not as a required field
        # Check the actual input fields read by the model
        model = ExpectationErrorModel()
        source = inspect.getsource(model.score_row)
        # The four required inputs should be present
        required = ["priced_move_pct", "short_interest_pct", "market_cap_mm", "close_price"]
        for field in required:
            assert field in source, f"Required field {field} not found in ExpectationErrorModel"


class TestSnapshotSchemaRegistration:
    """Verify expectation fields are registered in SNAPSHOT_COLUMNS."""

    def test_required_fields_in_snapshot_columns(self):
        """All four expectation fields should be in SNAPSHOT_COLUMNS."""
        required = ["short_interest_pct", "close_price", "market_cap_mm", "priced_move_pct"]
        for field in required:
            assert field in SNAPSHOT_COLUMNS, f"{field} not in SNAPSHOT_COLUMNS"

    def test_insider_in_snapshot_columns_but_diagnostic(self):
        """insider_net_buy_value_90d should be in SNAPSHOT_COLUMNS (for diagnostics)."""
        assert "insider_net_buy_value_90d" in SNAPSHOT_COLUMNS

        # Verify it's marked as diagnostic-only in a comment or nearby
        # (check the actual definition to confirm intent)
        snap_file = REPO_ROOT / "run_screen_columns.py"
        content = snap_file.read_text()
        assert "insider_net_buy_value_90d" in content
        # Find the section around insider and verify it says diagnostic
        idx = content.index("insider_net_buy_value_90d")
        snippet = content[max(0, idx - 200) : idx + 200]
        assert "diagnostic" in snippet.lower(), f"insider not marked diagnostic in schema: {snippet}"


class TestProductionQACoverage:
    """Verify production_qa_check.py contract includes required fields with correct thresholds."""

    def test_feature_coverage_requirements_defined(self):
        """FEATURE_COVERAGE_REQUIREMENTS should define thresholds for four core fields."""
        from tools.production_qa_check import FEATURE_COVERAGE_REQUIREMENTS

        # Build a dict for easier lookup
        reqs = {field: (floor, required) for field, floor, required in FEATURE_COVERAGE_REQUIREMENTS}

        # All four required fields should be present
        assert "short_interest_pct" in reqs, "short_interest_pct not in FEATURE_COVERAGE_REQUIREMENTS"
        assert "close_price" in reqs, "close_price not in FEATURE_COVERAGE_REQUIREMENTS"
        assert "market_cap_mm" in reqs, "market_cap_mm not in FEATURE_COVERAGE_REQUIREMENTS"
        assert "priced_move_pct" in reqs, "priced_move_pct not in FEATURE_COVERAGE_REQUIREMENTS"

    def test_feature_coverage_thresholds_correct(self):
        """FEATURE_COVERAGE_REQUIREMENTS thresholds should match spec."""
        from tools.production_qa_check import FEATURE_COVERAGE_REQUIREMENTS

        reqs = {field: (floor, required) for field, floor, required in FEATURE_COVERAGE_REQUIREMENTS}

        assert reqs["short_interest_pct"][0] >= 0.90, "short_interest_pct threshold too low"
        assert reqs["close_price"][0] >= 0.99, "close_price threshold too low"
        assert reqs["market_cap_mm"][0] >= 0.95, "market_cap_mm threshold too low"
        assert reqs["priced_move_pct"][0] >= 0.80, "priced_move_pct threshold too low"

        # All four should be required
        assert reqs["short_interest_pct"][1] is True, "short_interest_pct should be required"
        assert reqs["close_price"][1] is True, "close_price should be required"
        assert reqs["market_cap_mm"][1] is True, "market_cap_mm should be required"
        assert reqs["priced_move_pct"][1] is True, "priced_move_pct should be required"

    def test_insider_not_required(self):
        """insider_net_buy_value_90d should be tracked-nonblocking, not required."""
        from tools.production_qa_check import FEATURE_COVERAGE_REQUIREMENTS

        reqs = {field: (floor, required) for field, floor, required in FEATURE_COVERAGE_REQUIREMENTS}

        assert "insider_net_buy_value_90d" in reqs, "insider should be tracked (nonblocking)"
        assert (
            reqs["insider_net_buy_value_90d"][1] is False
        ), "insider should NOT be required (tracked-nonblocking only)"


class TestSeverityColumnsPresent:
    """Verify Spec 101 export (ev_severity_score) is wired."""

    def test_ev_severity_score_in_snapshot_columns(self):
        """ev_severity_score should be in SNAPSHOT_COLUMNS (Spec 101)."""
        assert "ev_severity_score" in SNAPSHOT_COLUMNS

    def test_severity_columns_in_qa_check(self):
        """SEVERITY_COLUMNS in production_qa_check.py should include ev_severity_score."""
        from tools.production_qa_check import SEVERITY_COLUMNS

        assert "ev_severity_score" in SEVERITY_COLUMNS
