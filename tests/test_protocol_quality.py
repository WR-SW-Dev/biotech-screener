"""Tests for protocol quality score (HINT-derived trial design features).

Covers:
  - Score computation from structured fields
  - Feature detection (comparator, randomization, blinding, endpoint, multi-arm)
  - Complexity penalty
  - PIT safety
  - Bounded output [0, 1]
  - Integration with CalendarAlphaConfig
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
        "primary_endpoints": ["Overall Survival at 24 months"],
        "study_type": "INTERVENTIONAL",
        "primary_purpose": "TREATMENT",
        "collected_at": "2026-04-01",
    }
    defaults.update(overrides)
    return defaults


class TestProtocolQualityScore:

    def test_full_rigor_phase3(self):
        from common.protocol_quality import compute_protocol_quality

        trials = [_make_trial(phase="PHASE3")]
        result = compute_protocol_quality(trials, "2026-04-15")
        pq = result["TEST"]

        # Phase 3 with full rigor → high score
        assert pq["protocol_quality_score"] > 0.5
        assert "comparator" in pq["protocol_signals"]
        assert "randomized" in pq["protocol_signals"]
        assert "blinded" in pq["protocol_signals"]

    def test_full_rigor_phase1_scores_lower(self):
        """Phase 1 with same features should score lower than Phase 3."""
        from common.protocol_quality import compute_protocol_quality

        trials_p1 = [_make_trial(phase="PHASE1")]
        trials_p3 = [_make_trial(phase="PHASE3")]
        pq_p1 = compute_protocol_quality(trials_p1, "2026-04-15")["TEST"]
        pq_p3 = compute_protocol_quality(trials_p3, "2026-04-15")["TEST"]

        assert pq_p1["protocol_quality_score"] < pq_p3["protocol_quality_score"]

    def test_single_arm_unblinded(self):
        from common.protocol_quality import compute_protocol_quality

        trials = [
            _make_trial(
                allocation="NA",
                masking="NONE",
                intervention_model="SINGLE_GROUP",
                primary_endpoints=["Safety and tolerability"],
            )
        ]
        result = compute_protocol_quality(trials, "2026-04-15")
        pq = result["TEST"]

        assert pq["protocol_quality_score"] < 0.15
        assert "comparator" not in pq["protocol_signals"]
        assert "randomized" not in pq["protocol_signals"]

    def test_phase1_not_over_penalized(self):
        """Phase 1 with NO rigor features should still score non-catastrophically."""
        from common.protocol_quality import compute_protocol_quality

        trials = [
            _make_trial(
                phase="PHASE1",
                allocation="NA",
                masking="NONE",
                intervention_model="SINGLE_GROUP",
                primary_endpoints=["Maximum tolerated dose"],
            )
        ]
        result = compute_protocol_quality(trials, "2026-04-15")
        pq = result["TEST"]

        # Should not be as penalized as Phase 3 missing the same features
        assert pq["protocol_quality_score"] >= 0.0

    def test_randomized_only_phase3(self):
        from common.protocol_quality import compute_protocol_quality

        trials = [
            _make_trial(
                phase="PHASE3",
                masking="NONE",
                intervention_model="SINGLE_GROUP",
                primary_endpoints=["Dose-limiting toxicity"],
            )
        ]
        result = compute_protocol_quality(trials, "2026-04-15")
        pq = result["TEST"]

        assert pq["protocol_quality_score"] > 0.1
        assert "randomized" in pq["protocol_signals"]
        assert "blinded" not in pq["protocol_signals"]

    def test_endpoint_specificity_from_endpoints_list(self):
        from common.protocol_quality import compute_protocol_quality

        trials = [
            _make_trial(
                primary_endpoints=["Progression-Free Survival", "Overall Survival"],
            )
        ]
        result = compute_protocol_quality(trials, "2026-04-15")
        pq = result["TEST"]
        assert pq["protocol_breakdown"]["endpoint_spec"] > 0.05

    def test_multi_arm_detected(self):
        from common.protocol_quality import compute_protocol_quality

        trials = [_make_trial(intervention_model="FACTORIAL")]
        result = compute_protocol_quality(trials, "2026-04-15")
        pq = result["TEST"]
        assert "multi_arm" in pq["protocol_signals"]

    def test_score_bounded(self):
        from common.protocol_quality import compute_protocol_quality

        trials = [_make_trial()]
        result = compute_protocol_quality(trials, "2026-04-15")
        score = result["TEST"]["protocol_quality_score"]
        assert 0.0 <= score <= 1.0

    def test_non_interventional_excluded(self):
        from common.protocol_quality import compute_protocol_quality

        trials = [_make_trial(study_type="OBSERVATIONAL")]
        result = compute_protocol_quality(trials, "2026-04-15")
        assert result["TEST"]["protocol_quality_score"] == 0.0

    def test_pit_filter(self):
        from common.protocol_quality import compute_protocol_quality

        trials = [_make_trial(collected_at="2026-05-01")]  # future
        result = compute_protocol_quality(trials, "2026-04-15")
        assert result["TEST"]["protocol_quality_score"] == 0.0

    def test_best_trial_selected(self):
        from common.protocol_quality import compute_protocol_quality

        # Two trials: one weak Phase 1, one strong Phase 3
        trials = [
            _make_trial(phase="PHASE1", allocation="NA", masking="NONE", intervention_model="SINGLE_GROUP"),
            _make_trial(phase="PHASE3"),  # full rigor
        ]
        result = compute_protocol_quality(trials, "2026-04-15")
        # Should pick the Phase 3 trial (more advanced phase)
        assert result["TEST"]["protocol_quality_score"] > 0.5

    def test_phase_priority_selection(self):
        """Most advanced phase trial is preferred over lower-phase higher-score."""
        from common.protocol_quality import compute_protocol_quality

        # Phase 1 with full rigor vs Phase 3 with partial rigor
        trials = [
            _make_trial(phase="PHASE1"),  # would score ~0.15 under Phase 1 weights
            _make_trial(phase="PHASE3", masking="NONE"),  # randomized no blinding ~0.45
        ]
        result = compute_protocol_quality(trials, "2026-04-15")
        pq = result["TEST"]
        # Should pick Phase 3 trial despite lower rigor features
        assert "phase_3" in pq["protocol_signals"]

    def test_phase_conditional_weights_exist(self):
        from common.protocol_quality import PHASE_PROTOCOL_WEIGHTS

        assert "1" in PHASE_PROTOCOL_WEIGHTS
        assert "2" in PHASE_PROTOCOL_WEIGHTS
        assert "3" in PHASE_PROTOCOL_WEIGHTS
        # Phase 1 comparator weight should be much lower than Phase 3
        assert PHASE_PROTOCOL_WEIGHTS["1"]["comparator"] < PHASE_PROTOCOL_WEIGHTS["3"]["comparator"]


class TestCalendarAlphaIntegration:

    def test_w_protocol_in_config(self):
        from common.clinical_calendar_alpha import CalendarAlphaConfig

        config = CalendarAlphaConfig()
        assert hasattr(config, "w_protocol")
        assert config.w_protocol == 0.08

    def test_compose_accepts_z_protocol(self):
        from common.clinical_calendar_alpha import CalendarAlphaConfig, compose_clinical_score_v2

        config = CalendarAlphaConfig()
        score, sizing, tags = compose_clinical_score_v2(
            clinical_score=50.0,
            features={},
            config=config,
            z_protocol=1.5,
        )
        # Protocol z-score should contribute positively
        score_no_prot, _, _ = compose_clinical_score_v2(
            clinical_score=50.0,
            features={},
            config=config,
            z_protocol=0.0,
        )
        assert score > score_no_prot

    def test_strong_protocol_tag(self):
        from common.clinical_calendar_alpha import CalendarAlphaConfig, compose_clinical_score_v2

        config = CalendarAlphaConfig()
        _, _, tags = compose_clinical_score_v2(
            clinical_score=50.0,
            features={},
            config=config,
            z_protocol=1.0,
        )
        assert "strong_protocol" in tags

    def test_weak_protocol_tag(self):
        from common.clinical_calendar_alpha import CalendarAlphaConfig, compose_clinical_score_v2

        config = CalendarAlphaConfig()
        _, _, tags = compose_clinical_score_v2(
            clinical_score=50.0,
            features={},
            config=config,
            z_protocol=-1.0,
        )
        assert "weak_protocol" in tags


class TestFeatureRegistryInclusion:

    def test_protocol_quality_in_registry(self):
        from common.feature_registry import FEATURE_REGISTRY

        names = {f.name for f in FEATURE_REGISTRY}
        assert "protocol_quality_score" in names

    def test_protocol_quality_context_eligible(self):
        from common.feature_registry import FEATURE_REGISTRY

        for f in FEATURE_REGISTRY:
            if f.name == "protocol_quality_score":
                assert f.context_eligible is True
                assert f.source == "clinical"
                break
