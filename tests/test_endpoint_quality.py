"""Tests for endpoint quality v2.

Covers:
  - Endpoint bucket classification
  - Phase-aware scoring
  - Multi-endpoint handling
  - Score bounds
  - Diagnostic signal generation
"""

from __future__ import annotations

from typing import Any, Dict


def _make_trial(**overrides: Any) -> Dict[str, Any]:
    defaults = {
        "ticker": "TEST",
        "phase": "PHASE3",
        "allocation": "RANDOMIZED",
        "masking": "DOUBLE",
        "intervention_model": "PARALLEL",
        "primary_endpoints": ["Overall Survival (OS)"],
        "study_type": "INTERVENTIONAL",
        "collected_at": "2026-04-01",
    }
    defaults.update(overrides)
    return defaults


class TestEndpointClassification:

    def test_os_is_hard_clinical(self):
        from common.endpoint_quality import classify_endpoint

        bucket, strength = classify_endpoint("Overall Survival (OS)")
        assert bucket == "hard_clinical"
        assert strength == 1.0

    def test_pfs_is_validated_surrogate(self):
        from common.endpoint_quality import classify_endpoint

        bucket, _ = classify_endpoint("Progression-Free Survival (PFS)")
        assert bucket == "validated_surrogate"

    def test_orr_is_objective_response(self):
        from common.endpoint_quality import classify_endpoint

        bucket, _ = classify_endpoint("Objective Response Rate (ORR)")
        assert bucket == "objective_response"

    def test_teae_is_safety(self):
        from common.endpoint_quality import classify_endpoint

        bucket, _ = classify_endpoint("Number of Participants with TEAEs")
        assert bucket == "safety_tolerability"

    def test_cmax_is_pk(self):
        from common.endpoint_quality import classify_endpoint

        bucket, _ = classify_endpoint("Cmax")
        assert bucket == "pk_pd_exploratory"

    def test_qol_is_symptom_functional(self):
        from common.endpoint_quality import classify_endpoint

        bucket, _ = classify_endpoint("Quality of Life score")
        assert bucket == "symptom_functional"

    def test_empty_is_vague(self):
        from common.endpoint_quality import classify_endpoint

        bucket, _ = classify_endpoint("")
        assert bucket == "vague_other"


class TestPhaseAwareScoring:

    def test_os_phase3_scores_highest(self):
        from common.endpoint_quality import compute_endpoint_quality

        trials = [_make_trial(phase="PHASE3", primary_endpoints=["Overall Survival"])]
        result = compute_endpoint_quality(trials, "2026-04-15")
        assert result["TEST"]["endpoint_quality_score"] >= 1.0

    def test_safety_phase3_scores_low(self):
        from common.endpoint_quality import compute_endpoint_quality

        trials = [_make_trial(phase="PHASE3", primary_endpoints=["Safety and Tolerability"])]
        result = compute_endpoint_quality(trials, "2026-04-15")
        score = result["TEST"]["endpoint_quality_score"]
        assert score < 0.20
        assert "endpoint_safety_only_late_phase" in result["TEST"]["endpoint_signals"]

    def test_safety_phase1_not_penalized(self):
        from common.endpoint_quality import compute_endpoint_quality

        trials = [_make_trial(phase="PHASE1", primary_endpoints=["Safety and Tolerability"])]
        result = compute_endpoint_quality(trials, "2026-04-15")
        score = result["TEST"]["endpoint_quality_score"]
        # Phase 1 safety is normal — should not be as penalized as Phase 3
        assert score >= 0.30

    def test_phase3_better_than_phase1_for_same_endpoint(self):
        from common.endpoint_quality import compute_endpoint_quality

        trials_p3 = [_make_trial(phase="PHASE3", primary_endpoints=["Overall Survival"])]
        trials_p1 = [_make_trial(phase="PHASE1", primary_endpoints=["Overall Survival"])]

        r3 = compute_endpoint_quality(trials_p3, "2026-04-15")
        r1 = compute_endpoint_quality(trials_p1, "2026-04-15")

        assert r3["TEST"]["endpoint_quality_score"] >= r1["TEST"]["endpoint_quality_score"]


class TestMultiEndpoint:

    def test_multi_endpoint_penalty(self):
        from common.endpoint_quality import compute_endpoint_quality

        # 5 endpoints = 2 above threshold → penalty
        many_eps = [f"Endpoint {i}" for i in range(5)]
        trials = [_make_trial(primary_endpoints=many_eps)]
        result = compute_endpoint_quality(trials, "2026-04-15")
        assert "endpoint_multi_primary_penalty" in result["TEST"]["endpoint_signals"]

    def test_two_endpoints_no_penalty(self):
        from common.endpoint_quality import compute_endpoint_quality

        trials = [_make_trial(primary_endpoints=["OS", "PFS"])]
        result = compute_endpoint_quality(trials, "2026-04-15")
        assert "endpoint_multi_primary_penalty" not in result["TEST"]["endpoint_signals"]


class TestScoreBounds:

    def test_score_bounded_0_1(self):
        from common.endpoint_quality import compute_endpoint_quality

        trials = [_make_trial()]
        result = compute_endpoint_quality(trials, "2026-04-15")
        score = result["TEST"]["endpoint_quality_score"]
        assert 0.0 <= score <= 1.0

    def test_no_endpoints_returns_zero(self):
        from common.endpoint_quality import compute_endpoint_quality

        trials = [_make_trial(primary_endpoints=[])]
        result = compute_endpoint_quality(trials, "2026-04-15")
        assert result["TEST"]["endpoint_quality_score"] == 0.0


class TestAuditability:

    def test_breakdown_fields(self):
        from common.endpoint_quality import compute_endpoint_quality

        trials = [_make_trial()]
        result = compute_endpoint_quality(trials, "2026-04-15")
        bd = result["TEST"]["endpoint_breakdown"]
        assert "best_strength" in bd
        assert "phase_mult" in bd
        assert "n_endpoints" in bd

    def test_bucket_list_populated(self):
        from common.endpoint_quality import compute_endpoint_quality

        trials = [_make_trial(primary_endpoints=["OS", "Safety"])]
        result = compute_endpoint_quality(trials, "2026-04-15")
        buckets = result["TEST"]["endpoint_buckets"]
        assert len(buckets) == 2
