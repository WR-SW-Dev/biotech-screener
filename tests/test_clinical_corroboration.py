"""Tests for clinical exact-date corroboration evaluator."""

from common.clinical_corroboration import DOWNGRADED_PRECISION, evaluate_corroboration, should_downgrade_precision
from common.event_quality_features import compute_clinical_91_180_quality, compute_clinical_days_precision


def _event(source="CTGOV", event_date="2026-06-15", event_type="CLINICAL_PCD"):
    return {"source": source, "event_date": event_date, "event_type": event_type}


# ---------------------------------------------------------------------------
# 1. evaluate_corroboration
# ---------------------------------------------------------------------------


class TestEvaluateCorroboration:
    def test_ctgov_stands_alone(self):
        result = evaluate_corroboration("CTGOV", "2026-06-15", [], "CLINICAL")
        assert result["corroborated"] is True
        assert result["trust_status"] == "exact"
        assert "trusted" in result["trust_reason"]

    def test_company_guidance_stands_alone(self):
        result = evaluate_corroboration("COMPANY_GUIDANCE", "2026-06-15", [], "CLINICAL")
        assert result["corroborated"] is True
        assert result["trust_status"] == "exact"

    def test_sec_8k_without_corroboration_downgrades(self):
        result = evaluate_corroboration("SEC_8K", "2026-06-15", [], "CLINICAL")
        assert result["needs_corroboration"] is True
        assert result["corroborated"] is False
        assert result["trust_status"] == "downgraded"

    def test_sec_8k_filing_without_corroboration_downgrades(self):
        result = evaluate_corroboration("SEC_8K_FILING", "2026-06-15", [], "CLINICAL")
        assert result["corroborated"] is False
        assert result["trust_status"] == "downgraded"

    def test_sec_8k_with_ctgov_corroboration_survives(self):
        events = [
            _event(source="CTGOV", event_date="2026-06-10"),  # within 30d
        ]
        result = evaluate_corroboration("SEC_8K", "2026-06-15", events, "CLINICAL")
        assert result["corroborated"] is True
        assert result["trust_status"] == "exact"
        assert "CTGOV" in result["corroborating_sources"]

    def test_sec_8k_with_company_guidance_corroboration(self):
        events = [
            _event(source="COMPANY_GUIDANCE", event_date="2026-06-20"),
        ]
        result = evaluate_corroboration("SEC_8K", "2026-06-15", events, "CLINICAL")
        assert result["corroborated"] is True
        assert "COMPANY_GUIDANCE" in result["corroborating_sources"]

    def test_sec_8k_with_distant_ctgov_not_corroborated(self):
        events = [
            _event(source="CTGOV", event_date="2026-09-15"),  # 92d away
        ]
        result = evaluate_corroboration("SEC_8K", "2026-06-15", events, "CLINICAL")
        assert result["corroborated"] is False
        assert result["trust_status"] == "downgraded"

    def test_regulatory_family_not_applicable(self):
        result = evaluate_corroboration("SEC_8K", "2026-06-15", [], "REGULATORY")
        assert result["trust_status"] == "not_applicable"
        assert result["corroborated"] is True  # not affected

    def test_unknown_source_gets_benefit_of_doubt(self):
        result = evaluate_corroboration("NEW_SOURCE", "2026-06-15", [], "CLINICAL")
        assert result["corroborated"] is True  # not classified as noisy
        assert result["trust_status"] == "exact"

    def test_sec_multi_also_noisy(self):
        result = evaluate_corroboration("SEC_MULTI", "2026-06-15", [], "CLINICAL")
        assert result["corroborated"] is False
        assert result["trust_status"] == "downgraded"

    def test_same_source_does_not_self_corroborate(self):
        events = [
            _event(source="SEC_8K", event_date="2026-06-15"),  # same source
        ]
        result = evaluate_corroboration("SEC_8K", "2026-06-15", events, "CLINICAL")
        assert result["corroborated"] is False

    def test_corroboration_window_boundary(self):
        events = [
            _event(source="CTGOV", event_date="2026-07-15"),  # exactly 30d away
        ]
        result = evaluate_corroboration("SEC_8K", "2026-06-15", events, "CLINICAL")
        assert result["corroborated"] is True

        events_outside = [
            _event(source="CTGOV", event_date="2026-07-16"),  # 31d away
        ]
        result2 = evaluate_corroboration("SEC_8K", "2026-06-15", events_outside, "CLINICAL")
        assert result2["corroborated"] is False

    def test_empty_family_not_affected(self):
        result = evaluate_corroboration("SEC_8K", "2026-06-15", [], "")
        assert result["corroborated"] is True
        assert result["trust_status"] == "not_applicable"


# ---------------------------------------------------------------------------
# 2. should_downgrade_precision
# ---------------------------------------------------------------------------


class TestShouldDowngradePrecision:
    def test_noisy_uncorroborated_clinical_downgrades(self):
        assert should_downgrade_precision("SEC_8K", "CLINICAL", False) is True
        assert should_downgrade_precision("SEC_8K_FILING", "CLINICAL", False) is True

    def test_noisy_corroborated_clinical_ok(self):
        assert should_downgrade_precision("SEC_8K", "CLINICAL", True) is False

    def test_trusted_uncorroborated_ok(self):
        assert should_downgrade_precision("CTGOV", "CLINICAL", False) is False
        assert should_downgrade_precision("COMPANY_GUIDANCE", "CLINICAL", False) is False

    def test_regulatory_never_downgraded(self):
        assert should_downgrade_precision("SEC_8K", "REGULATORY", False) is False


# ---------------------------------------------------------------------------
# 3. Precision integration
# ---------------------------------------------------------------------------


class TestPrecisionIntegration:
    def test_sec_8k_corroborated_gets_day(self):
        precision = compute_clinical_days_precision("specific_days", "SEC_8K_FILING", corroborated=True)
        assert precision == "DAY"

    def test_sec_8k_uncorroborated_gets_month(self):
        precision = compute_clinical_days_precision("specific_days", "SEC_8K_FILING", corroborated=False)
        assert precision == DOWNGRADED_PRECISION  # MONTH

    def test_ctgov_not_affected_by_corroboration(self):
        # CTGOV_CALENDAR is not in NOISY set, so corroboration doesn't change anything
        prec_yes = compute_clinical_days_precision("specific_days", "CTGOV_CALENDAR", corroborated=True)
        prec_no = compute_clinical_days_precision("specific_days", "CTGOV_CALENDAR", corroborated=False)
        assert prec_yes == prec_no  # same either way

    def test_default_corroborated_true_backward_compat(self):
        """Without corroborated param, behaves like before (corroborated=True)."""
        precision = compute_clinical_days_precision("specific_days", "SEC_8K_FILING")
        assert precision == "DAY"  # old behavior

    def test_confidence_drops_with_downgrade(self):
        """Uncorroborated SEC_8K CLINICAL gets lower confidence."""
        row_corr = {
            "catalyst_family": "CLINICAL",
            "catalyst_mode": "specific_days",
            "catalyst_source": "SEC_8K_FILING",
            "catalyst_corroborated": "1",
        }
        row_uncorr = {
            "catalyst_family": "CLINICAL",
            "catalyst_mode": "specific_days",
            "catalyst_source": "SEC_8K_FILING",
            "catalyst_corroborated": "0",
        }

        result_corr = compute_clinical_91_180_quality(row_corr)
        result_uncorr = compute_clinical_91_180_quality(row_uncorr)

        # Corroborated: DAY precision → 0.95+0.05=1.0 confidence
        # Uncorroborated: MONTH precision → 0.60 confidence (no bonus)
        assert result_corr["clinical_date_confidence"] > result_uncorr["clinical_date_confidence"]
        assert result_corr["clinical_days_precision"] == "DAY"
        assert result_uncorr["clinical_days_precision"] == "MONTH"


# ---------------------------------------------------------------------------
# 4. run_screen.py integration helper
# ---------------------------------------------------------------------------


class TestCheckCatalystCorroboration:
    def test_clinical_sec_8k_with_events(self):
        """Integration test using the run_screen helper function shape."""
        from run_screen import _check_catalyst_corroboration

        m3 = {
            "ACME": {
                "integration": {"next_catalyst_date": "2026-06-15"},
                "events": [
                    {"source": "SEC_8K", "event_date": "2026-06-15", "event_type": "DATA_READOUT"},
                    {"source": "CTGOV", "event_date": "2026-06-10", "event_type": "CLINICAL_PCD"},
                ],
            }
        }
        result = _check_catalyst_corroboration(m3, "ACME", "SEC_8K", "CLINICAL")
        assert result["corroborated"] is True
        assert "CTGOV" in result["corroborating_sources"]

    def test_regulatory_passthrough(self):
        from run_screen import _check_catalyst_corroboration

        result = _check_catalyst_corroboration(None, "ACME", "SEC_8K", "REGULATORY")
        assert result["trust_status"] == "not_applicable"

    def test_no_m3_data(self):
        from run_screen import _check_catalyst_corroboration

        result = _check_catalyst_corroboration(None, "ACME", "SEC_8K", "CLINICAL")
        assert result["corroborated"] is False
        assert result["trust_status"] == "downgraded"
