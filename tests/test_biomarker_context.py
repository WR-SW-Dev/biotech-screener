"""Tests for conditional biomarker scoring.

Covers:
  - Biomarker detection from trial fields
  - Phase-conditional relevance
  - Indication bucket classification
  - Protocol quality interaction
  - Score clamping and bounds
  - No-biomarker returns zero
  - Old global boost neutralized
"""

from __future__ import annotations

from typing import Any, Dict


def _make_trial(**overrides: Any) -> Dict[str, Any]:
    defaults = {
        "ticker": "TEST",
        "nct_id": "NCT00000001",
        "phase": "PHASE3",
        "allocation": "RANDOMIZED",
        "masking": "DOUBLE",
        "intervention_model": "PARALLEL",
        "primary_endpoints": ["Progression-Free Survival"],
        "study_type": "INTERVENTIONAL",
        "conditions": ["Non-Small Cell Lung Cancer"],
        "interventions": ["pembrolizumab"],
        "title": "Phase 3 Study of PD-L1 Positive NSCLC",
        "collected_at": "2026-04-01",
    }
    defaults.update(overrides)
    return defaults


class TestBiomarkerDetection:

    def test_pdl1_detected(self):
        from common.biomarker_context import compute_biomarker_context_score

        trials = [_make_trial(title="Study in PD-L1 positive patients")]
        result = compute_biomarker_context_score(trials, "2026-04-15")
        assert result["TEST"]["biomarker_detected"] is True

    def test_her2_detected(self):
        from common.biomarker_context import compute_biomarker_context_score

        trials = [_make_trial(conditions=["HER2-positive breast cancer"])]
        result = compute_biomarker_context_score(trials, "2026-04-15")
        assert result["TEST"]["biomarker_detected"] is True

    def test_no_biomarker(self):
        from common.biomarker_context import compute_biomarker_context_score

        trials = [
            _make_trial(
                title="Phase 3 Study of Drug X",
                conditions=["Chronic Pain"],
                interventions=["drug_x"],
            )
        ]
        result = compute_biomarker_context_score(trials, "2026-04-15")
        assert result["TEST"]["biomarker_detected"] is False
        assert result["TEST"]["biomarker_context_score"] == 0.0


class TestPhaseConditioning:

    def test_phase3_oncology_highest(self):
        """Phase 3 biomarker should score >= Phase 1 (may both hit cap in ideal conditions)."""
        from common.biomarker_context import compute_biomarker_context_score

        # Use moderate protocol quality to avoid both hitting the 0.30 cap
        pq = {"TEST": {"protocol_quality_score": 0.35, "protocol_signals": "randomized"}}

        trials_p3 = [_make_trial(phase="PHASE3")]
        result_p3 = compute_biomarker_context_score(trials_p3, "2026-04-15", protocol_quality=pq)

        trials_p1 = [_make_trial(phase="PHASE1")]
        result_p1 = compute_biomarker_context_score(trials_p1, "2026-04-15", protocol_quality=pq)

        assert result_p3["TEST"]["biomarker_context_score"] >= result_p1["TEST"]["biomarker_context_score"]

    def test_phase1_low_but_nonzero(self):
        from common.biomarker_context import compute_biomarker_context_score

        # Phase 1 with weak design — should be low
        trials = [
            _make_trial(
                phase="PHASE1",
                allocation="NA",
                masking="NONE",
                intervention_model="SINGLE_GROUP",
            )
        ]
        pq = {"TEST": {"protocol_quality_score": 0.15, "protocol_signals": ""}}
        result = compute_biomarker_context_score(trials, "2026-04-15", protocol_quality=pq)
        score = result["TEST"]["biomarker_context_score"]
        assert 0.0 < score < 0.20


class TestIndicationConditioning:

    def test_oncology_higher_than_broad(self):
        from common.biomarker_context import compute_biomarker_context_score

        # Use moderate protocol quality to avoid cap saturation
        pq = {"TEST": {"protocol_quality_score": 0.35, "protocol_signals": "randomized"}}

        onc = [_make_trial(conditions=["EGFR-mutant NSCLC"])]
        result_onc = compute_biomarker_context_score(onc, "2026-04-15", protocol_quality=pq)

        broad = [_make_trial(conditions=["Chronic fatigue"], title="Biomarker-selected fatigue study")]
        result_broad = compute_biomarker_context_score(broad, "2026-04-15", protocol_quality=pq)

        assert result_onc["TEST"]["biomarker_context_score"] >= result_broad["TEST"]["biomarker_context_score"]
        # Verify different indication signals even if scores tie
        assert "targeted" in result_onc["TEST"]["biomarker_signals"]
        assert "broad" in result_broad["TEST"]["biomarker_signals"]

    def test_indication_bucket_signals(self):
        from common.biomarker_context import compute_biomarker_context_score

        trials = [_make_trial(conditions=["HER2+ Breast Cancer"])]
        result = compute_biomarker_context_score(trials, "2026-04-15")
        assert "biomarker_oncology_targeted" in result["TEST"]["biomarker_signals"]


class TestProtocolQualityInteraction:

    def test_strong_design_amplifies(self):
        """Strong protocol quality should produce higher biomarker score than weak."""
        from common.biomarker_context import compute_biomarker_context_score

        # Use Phase 2 non-oncology to stay below cap and see differentiation
        trials = [
            _make_trial(phase="PHASE2", conditions=["Chronic kidney disease"], title="Biomarker-selected CKD study")
        ]
        strong_pq = {"TEST": {"protocol_quality_score": 0.7, "protocol_signals": "comparator,specific_endpoint"}}
        weak_pq = {"TEST": {"protocol_quality_score": 0.15, "protocol_signals": ""}}

        result_strong = compute_biomarker_context_score(trials, "2026-04-15", protocol_quality=strong_pq)
        result_weak = compute_biomarker_context_score(trials, "2026-04-15", protocol_quality=weak_pq)

        assert result_strong["TEST"]["biomarker_context_score"] > result_weak["TEST"]["biomarker_context_score"]

    def test_weak_design_dampened_signal(self):
        from common.biomarker_context import compute_biomarker_context_score

        trials = [_make_trial()]
        weak_pq = {"TEST": {"protocol_quality_score": 0.10, "protocol_signals": ""}}
        result = compute_biomarker_context_score(trials, "2026-04-15", protocol_quality=weak_pq)
        assert "biomarker_weak_design_dampened" in result["TEST"]["biomarker_signals"]


class TestScoreBounds:

    def test_score_clamped_to_max(self):
        from common.biomarker_context import compute_biomarker_context_score

        trials = [_make_trial()]
        pq = {
            "TEST": {
                "protocol_quality_score": 0.9,
                "protocol_signals": "comparator,randomized,blinded,specific_endpoint",
            }
        }
        result = compute_biomarker_context_score(trials, "2026-04-15", protocol_quality=pq)
        assert result["TEST"]["biomarker_context_score"] <= 0.30

    def test_score_floor_at_minus_005(self):
        from common.biomarker_context import compute_biomarker_context_score

        # Even worst-case should not go below -0.05
        trials = [
            _make_trial(
                phase="PHASE1",
                conditions=["General wellness"],
                title="Biomarker-selected wellness study",
            )
        ]
        pq = {"TEST": {"protocol_quality_score": 0.05, "protocol_signals": ""}}
        result = compute_biomarker_context_score(trials, "2026-04-15", protocol_quality=pq)
        assert result["TEST"]["biomarker_context_score"] >= -0.05


class TestOldBoostNeutralized:

    def test_pos_prior_engine_biomarker_neutral(self):
        """The old 1.20x flat biomarker boost must be neutralized."""
        from decimal import Decimal

        from pos_prior_engine import PoSPriorEngine

        assert PoSPriorEngine.MODIFIERS["biomarker_enriched"] == Decimal("1.00")


class TestBreakdownAuditability:

    def test_breakdown_fields_present(self):
        from common.biomarker_context import compute_biomarker_context_score

        trials = [_make_trial()]
        result = compute_biomarker_context_score(trials, "2026-04-15")
        bd = result["TEST"]["biomarker_breakdown"]
        assert "phase_relevance" in bd
        assert "indication_mult" in bd
        assert "protocol_quality_mult" in bd
        assert "endpoint_bonus" in bd
        assert "comparator_bonus" in bd
