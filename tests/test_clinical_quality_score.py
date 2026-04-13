"""Tests for common/clinical_quality_score.py — Spec 057 clinical quality layer."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.clinical_quality_score import (
    compute_clinical_quality_scores,
    compute_design_rigor_tier,
    compute_endpoint_strength_tier,
    compute_mechanism_maturity_tier,
    compute_prior_evidence_tier,
)

# ===================================================================
# Endpoint Strength Tier
# ===================================================================


class TestEndpointStrengthTier:
    def test_hard_overall_survival(self):
        score, tier, signal = compute_endpoint_strength_tier(["Overall Survival (OS)"])
        assert score == 1.0
        assert tier == "hard"

    def test_hard_mortality(self):
        score, tier, _ = compute_endpoint_strength_tier(["All-cause mortality at 12 months"])
        assert score == 1.0
        assert tier == "hard"

    def test_hard_mace(self):
        score, tier, _ = compute_endpoint_strength_tier(["Time to first MACE event"])
        assert score == 1.0
        assert tier == "hard"

    def test_semi_hard_pfs(self):
        score, tier, _ = compute_endpoint_strength_tier(["Progression-Free Survival (PFS)"])
        assert score == 0.4
        assert tier == "semi_hard"

    def test_semi_hard_complete_response(self):
        score, tier, _ = compute_endpoint_strength_tier(["Complete response rate per IRC"])
        assert score == 0.4
        assert tier == "semi_hard"

    def test_semi_hard_orr(self):
        score, tier, _ = compute_endpoint_strength_tier(["Objective Response Rate (ORR)"])
        assert score == 0.4
        assert tier == "semi_hard"

    def test_surrogate_biomarker(self):
        score, tier, _ = compute_endpoint_strength_tier(["Change in serum biomarker level"])
        assert score == 0.0
        assert tier == "surrogate"

    def test_surrogate_safety(self):
        score, tier, _ = compute_endpoint_strength_tier(["Number of participants with adverse events"])
        assert score == 0.0
        assert tier == "surrogate"

    def test_surrogate_pk(self):
        score, tier, _ = compute_endpoint_strength_tier(["Pharmacokinetic parameters (Cmax, AUC)"])
        assert score == 0.0
        assert tier == "surrogate"

    def test_unknown_empty(self):
        score, tier, signal = compute_endpoint_strength_tier([])
        assert score == 0.0
        assert tier == "unknown"
        assert signal == ""

    def test_unknown_vague(self):
        score, tier, _ = compute_endpoint_strength_tier(["Change in disease activity score"])
        assert score == 0.0
        assert tier == "unknown"

    def test_title_fallback(self):
        """Title text used when no primary_endpoints provided."""
        score, tier, _ = compute_endpoint_strength_tier([], title="A Study of Overall Survival in NSCLC")
        assert score == 1.0
        assert tier == "hard"

    def test_hard_beats_semi_hard(self):
        """Hard endpoint in same text takes priority over semi-hard."""
        score, tier, _ = compute_endpoint_strength_tier(["Overall Survival and Progression-Free Survival"])
        assert tier == "hard"

    def test_hba1c(self):
        score, tier, _ = compute_endpoint_strength_tier(["Change from baseline in HbA1c at Week 24"])
        assert score == 0.4
        assert tier == "semi_hard"


# ===================================================================
# Design Rigor Tier
# ===================================================================


class TestDesignRigorTier:
    def test_gold_standard_rdb_placebo(self):
        score, tier, signals = compute_design_rigor_tier(
            allocation="RANDOMIZED",
            masking="DOUBLE",
            intervention_model="PARALLEL",
            interventions=["Drug A", "Placebo"],
        )
        assert score == 1.0
        assert tier == "gold_standard"
        assert "randomized" in signals
        assert "masked_double" in signals

    def test_gold_quadruple_masked(self):
        score, tier, signals = compute_design_rigor_tier(
            allocation="RANDOMIZED",
            masking="QUADRUPLE",
            intervention_model="PARALLEL",
            interventions=["Drug A", "Placebo"],
        )
        assert score == 1.0
        assert tier == "gold_standard"

    def test_strong_randomized_single_blind(self):
        score, tier, _ = compute_design_rigor_tier(
            allocation="RANDOMIZED",
            masking="SINGLE",
            intervention_model="PARALLEL",
        )
        assert tier == "strong"
        assert 0.5 < score <= 1.0

    def test_strong_randomized_no_blind_with_control(self):
        score, tier, _ = compute_design_rigor_tier(
            allocation="RANDOMIZED",
            masking="NONE",
            intervention_model="PARALLEL",
            interventions=["Drug A", "Placebo"],
        )
        assert tier == "strong"
        assert score == 0.65

    def test_moderate_randomized_open_label(self):
        score, tier, _ = compute_design_rigor_tier(
            allocation="RANDOMIZED",
            masking="NONE",
            intervention_model="SINGLE_GROUP",
        )
        assert score == 0.5
        assert tier == "moderate"

    def test_weak_single_arm(self):
        score, tier, signals = compute_design_rigor_tier(
            allocation="NON_RANDOMIZED",
            masking="NONE",
            intervention_model="SINGLE_GROUP",
        )
        assert score == 0.0
        assert tier == "weak"
        assert "single_arm" in signals

    def test_observational(self):
        score, tier, _ = compute_design_rigor_tier(
            allocation=None,
            masking=None,
            intervention_model=None,
            study_type="OBSERVATIONAL",
        )
        assert score == -0.5
        assert tier == "observational"

    def test_title_fallback_double_blind(self):
        """When structured fields are None, parse from title."""
        score, tier, signals = compute_design_rigor_tier(
            allocation=None,
            masking=None,
            intervention_model=None,
            title="A Randomized, Double-Blind, Placebo-Controlled Study",
        )
        assert tier == "gold_standard"
        assert "randomized_title" in signals
        assert "double_blind_title" in signals
        assert "placebo_controlled_title" in signals

    def test_unknown_no_data(self):
        score, tier, signals = compute_design_rigor_tier(
            allocation=None,
            masking=None,
            intervention_model=None,
        )
        assert tier == "unknown"
        assert signals == []

    def test_na_allocation_treated_as_missing(self):
        """'NA' from AACT should not count as randomized."""
        score, tier, signals = compute_design_rigor_tier(
            allocation="NA",
            masking="NONE",
            intervention_model="SINGLE_GROUP",
        )
        assert "randomized" not in signals
        assert tier == "weak"

    def test_crossover_implies_control(self):
        score, tier, signals = compute_design_rigor_tier(
            allocation="RANDOMIZED",
            masking="DOUBLE",
            intervention_model="CROSSOVER",
        )
        assert tier == "gold_standard"
        assert any("crossover" in s for s in signals)


# ===================================================================
# Prior Evidence Tier
# ===================================================================


class TestPriorEvidenceTier:
    def _trial(
        self, status="COMPLETED", results_posted="2025-01-01", first_posted="2020-01-01", last_update="2025-06-01"
    ):
        return {
            "status": status,
            "results_first_posted": results_posted,
            "first_posted": first_posted,
            "last_update_posted": last_update,
        }

    def test_positive_many_results(self):
        from datetime import date

        trials = [
            self._trial("COMPLETED", "2024-01-01"),
            self._trial("COMPLETED", "2024-06-01"),
            self._trial("COMPLETED", "2025-01-01"),
        ]
        score, tier, notes = compute_prior_evidence_tier(trials, date(2026, 4, 13))
        assert score == 1.0
        assert tier == "positive"

    def test_negative_many_terminated(self):
        from datetime import date

        trials = [
            self._trial("TERMINATED", None),
            self._trial("TERMINATED", None),
            self._trial("WITHDRAWN", None),
        ]
        score, tier, notes = compute_prior_evidence_tier(trials, date(2026, 4, 13))
        assert score == -1.0
        assert tier == "negative"

    def test_mixed(self):
        from datetime import date

        trials = [
            self._trial("COMPLETED", "2024-01-01"),
            self._trial("TERMINATED", None),
        ]
        score, tier, _ = compute_prior_evidence_tier(trials, date(2026, 4, 13))
        assert tier in ("leaning_positive", "mixed")

    def test_unknown_no_completed(self):
        from datetime import date

        trials = [
            self._trial("RECRUITING", None),
            self._trial("NOT_YET_RECRUITING", None),
        ]
        score, tier, _ = compute_prior_evidence_tier(trials, date(2026, 4, 13))
        assert score == 0.0
        assert tier == "unknown"

    def test_pit_enforcement(self):
        """Trials posted after as_of should be excluded."""
        from datetime import date

        trials = [
            self._trial("COMPLETED", "2024-01-01", first_posted="2027-01-01"),
        ]
        score, tier, _ = compute_prior_evidence_tier(trials, date(2026, 4, 13))
        assert tier == "unknown"

    def test_empty_trials(self):
        from datetime import date

        score, tier, _ = compute_prior_evidence_tier([], date(2026, 4, 13))
        assert tier == "unknown"

    def test_leaning_negative(self):
        from datetime import date

        trials = [
            self._trial("COMPLETED", "2024-01-01"),
            self._trial("TERMINATED", None),
            self._trial("TERMINATED", None),
            self._trial("WITHDRAWN", None),
        ]
        score, tier, _ = compute_prior_evidence_tier(trials, date(2026, 4, 13))
        assert score < 0

    def test_results_posted_after_snapshot_not_visible(self):
        """Results posted after as_of must not count as evidence."""
        from datetime import date

        trials = [
            self._trial("COMPLETED", results_posted="2025-06-01", last_update="2025-06-01"),
        ]
        # At 2025-01-01, results_first_posted (2025-06-01) is in the future
        score, tier, _ = compute_prior_evidence_tier(trials, date(2025, 1, 1))
        # Should see completed_no_results (status observable, but results not yet)
        assert tier != "positive"

    def test_status_updated_after_snapshot_not_observable(self):
        """Trial whose last_update_posted is after as_of = status not yet observable."""
        from datetime import date

        trials = [
            self._trial("TERMINATED", None, first_posted="2020-01-01", last_update="2025-06-01"),
        ]
        # At 2024-01-01, last_update_posted is in the future => status not observable
        score, tier, _ = compute_prior_evidence_tier(trials, date(2024, 1, 1))
        assert tier == "unknown"  # should not count as terminated


# ===================================================================
# Mechanism Maturity Tier
# ===================================================================


class TestMechanismMaturityTier:
    def test_validated_checkpoint_inhibitor(self):
        from datetime import date

        trials = [
            {
                "ticker": "TEST",
                "title": "Anti-PD-1 Antibody in NSCLC",
                "conditions": ["Non-Small Cell Lung Cancer"],
                "interventions": ["Pembrolizumab"],
                "phase": "PHASE3",
                "study_type": "INTERVENTIONAL",
                "first_posted": "2020-01-01",
            }
        ]
        score, tier, _ = compute_mechanism_maturity_tier(trials, date(2026, 4, 13))
        assert score == 1.0
        assert tier == "validated"

    def test_validated_car_t(self):
        from datetime import date

        trials = [
            {
                "ticker": "TEST",
                "title": "CAR-T Cell Therapy",
                "conditions": ["Lymphoma"],
                "interventions": ["Axicabtagene ciloleucel"],
                "phase": "PHASE2",
                "first_posted": "2020-01-01",
            }
        ]
        score, tier, _ = compute_mechanism_maturity_tier(trials, date(2026, 4, 13))
        assert tier == "validated"

    def test_novel_cns(self):
        from datetime import date

        trials = [
            {
                "ticker": "TEST",
                "title": "Novel Agent for Schizophrenia",
                "conditions": ["Schizophrenia"],
                "interventions": ["XYZ-001"],
                "phase": "PHASE1",
                "first_posted": "2020-01-01",
            }
        ]
        score, tier, _ = compute_mechanism_maturity_tier(trials, date(2026, 4, 13))
        assert tier == "novel"

    def test_red_flag_amyloid(self):
        from datetime import date

        trials = [
            {
                "ticker": "TEST",
                "title": "Anti-amyloid beta Antibody for Alzheimer's",
                "conditions": ["Alzheimer Disease"],
                "interventions": ["Anti-Amyloid mAb"],
                "phase": "PHASE3",
                "first_posted": "2020-01-01",
            }
        ]
        score, tier, _ = compute_mechanism_maturity_tier(trials, date(2026, 4, 13))
        assert score == -0.5
        assert tier == "red_flag"

    def test_partially_validated_autoimmune(self):
        from datetime import date

        trials = [
            {
                "ticker": "TEST",
                "title": "Study of XYZ in RA",
                "conditions": ["Rheumatoid Arthritis"],
                "interventions": ["XYZ-002"],
                "phase": "PHASE2",
                "first_posted": "2020-01-01",
            }
        ]
        score, tier, _ = compute_mechanism_maturity_tier(trials, date(2026, 4, 13))
        assert tier == "partially_validated"

    def test_empty_trials(self):
        from datetime import date

        score, tier, _ = compute_mechanism_maturity_tier([], date(2026, 4, 13))
        assert tier == "unknown"

    def test_pit_enforcement(self):
        from datetime import date

        trials = [
            {
                "ticker": "TEST",
                "title": "Anti-PD-1 in Cancer",
                "conditions": ["Cancer"],
                "interventions": ["Anti-PD-1"],
                "phase": "PHASE3",
                "first_posted": "2027-01-01",
            }
        ]
        score, tier, _ = compute_mechanism_maturity_tier(trials, date(2026, 4, 13))
        assert tier == "unknown"


# ===================================================================
# Composite Score
# ===================================================================


class TestCompositeScore:
    def _make_trials(self, **overrides):
        base = {
            "ticker": "TEST",
            "nct_id": "NCT00000001",
            "title": "A Randomized, Double-Blind, Placebo-Controlled Phase 3 Study of Overall Survival",
            "status": "COMPLETED",
            "phase": "PHASE3",
            "study_type": "INTERVENTIONAL",
            "conditions": ["Non-Small Cell Lung Cancer"],
            "interventions": ["Drug A", "Placebo"],
            "first_posted": "2020-01-01",
            "last_update_posted": "2025-01-01",
            "primary_completion_date": "2024-06-01",
            "results_first_posted": "2025-01-01",
            "allocation": "RANDOMIZED",
            "masking": "DOUBLE",
            "intervention_model": "PARALLEL",
            "primary_endpoints": ["Overall Survival"],
        }
        base.update(overrides)
        return [base]

    def test_perfect_score(self):
        """Gold standard trial should score near +1.0."""
        trials = self._make_trials()
        results = compute_clinical_quality_scores(trials, "2026-04-13")
        r = results["TEST"]
        assert r.clinical_quality_score >= 0.8
        assert r.clinical_quality_confidence == "high"
        assert r.endpoint_strength_tier == "hard"
        assert r.design_rigor_tier == "gold_standard"

    def test_worst_score(self):
        """Poor trial should score negative."""
        trials = self._make_trials(
            title="Safety Study",
            status="TERMINATED",
            phase="PHASE1",
            allocation="NON_RANDOMIZED",
            masking="NONE",
            intervention_model="SINGLE_GROUP",
            interventions=["Drug A"],
            results_first_posted=None,
            primary_endpoints=["Number of Adverse Events"],
            conditions=["Depression"],
        )
        results = compute_clinical_quality_scores(trials, "2026-04-13")
        r = results["TEST"]
        assert r.clinical_quality_score <= 0.0

    def test_clamped_to_range(self):
        """Score must be in [-1, +1]."""
        trials = self._make_trials()
        results = compute_clinical_quality_scores(trials, "2026-04-13")
        for r in results.values():
            assert -1.0 <= r.clinical_quality_score <= 1.0

    def test_insufficient_components_zero(self):
        """With <2 components, score should be 0.0."""
        trials = [
            {
                "ticker": "TEST",
                "nct_id": "NCT00000001",
                "title": "",
                "status": "RECRUITING",
                "phase": "",
                "study_type": "OBSERVATIONAL",
                "conditions": [],
                "interventions": [],
                "first_posted": "2025-01-01",
            }
        ]
        results = compute_clinical_quality_scores(trials, "2026-04-13")
        r = results["TEST"]
        assert r.n_components_available < 2 or r.clinical_quality_score == 0.0

    def test_invalid_as_of_date(self):
        results = compute_clinical_quality_scores([], "bad-date")
        assert results == {}

    def test_empty_records(self):
        results = compute_clinical_quality_scores([], "2026-04-13")
        assert results == {}

    def test_multiple_tickers(self):
        """Each ticker should get its own result."""
        trials = [
            {
                "ticker": "AAA",
                "nct_id": "NCT00000001",
                "title": "Overall Survival Study",
                "status": "COMPLETED",
                "phase": "PHASE3",
                "study_type": "INTERVENTIONAL",
                "conditions": ["Cancer"],
                "interventions": ["Drug A", "Placebo"],
                "first_posted": "2020-01-01",
                "results_first_posted": "2024-01-01",
                "allocation": "RANDOMIZED",
                "masking": "DOUBLE",
                "intervention_model": "PARALLEL",
                "primary_endpoints": ["Overall Survival"],
            },
            {
                "ticker": "BBB",
                "nct_id": "NCT00000002",
                "title": "PK Study",
                "status": "RECRUITING",
                "phase": "PHASE1",
                "study_type": "INTERVENTIONAL",
                "conditions": ["Healthy"],
                "interventions": ["Drug B"],
                "first_posted": "2025-01-01",
                "allocation": "NON_RANDOMIZED",
                "masking": "NONE",
                "intervention_model": "SINGLE_GROUP",
                "primary_endpoints": ["Pharmacokinetic parameters"],
            },
        ]
        results = compute_clinical_quality_scores(trials, "2026-04-13")
        assert "AAA" in results
        assert "BBB" in results
        assert results["AAA"].clinical_quality_score > results["BBB"].clinical_quality_score

    def test_confidence_decreases_with_unknowns(self):
        """Confidence should be lower when fewer components are available."""
        # Full data
        full_trials = self._make_trials()
        full_results = compute_clinical_quality_scores(full_trials, "2026-04-13")

        # Minimal data
        sparse_trials = [
            {
                "ticker": "SPARSE",
                "nct_id": "NCT00000002",
                "title": "A study",
                "status": "RECRUITING",
                "phase": "PHASE1",
                "study_type": "INTERVENTIONAL",
                "conditions": [],
                "interventions": ["Drug X"],
                "first_posted": "2025-01-01",
            }
        ]
        sparse_results = compute_clinical_quality_scores(sparse_trials, "2026-04-13")

        full_conf = full_results["TEST"].confidence_raw
        sparse_conf = sparse_results["SPARSE"].confidence_raw
        assert full_conf >= sparse_conf

    def test_result_dataclass_fields(self):
        """All expected fields should be present."""
        trials = self._make_trials()
        results = compute_clinical_quality_scores(trials, "2026-04-13")
        r = results["TEST"]
        assert hasattr(r, "clinical_quality_score")
        assert hasattr(r, "clinical_quality_confidence")
        assert hasattr(r, "endpoint_strength")
        assert hasattr(r, "endpoint_strength_tier")
        assert hasattr(r, "design_rigor")
        assert hasattr(r, "design_rigor_tier")
        assert hasattr(r, "prior_evidence")
        assert hasattr(r, "prior_evidence_tier")
        assert hasattr(r, "mechanism_maturity")
        assert hasattr(r, "mechanism_maturity_tier")
        assert hasattr(r, "n_components_available")
        assert hasattr(r, "notes")
        assert isinstance(r.notes, str)
        assert isinstance(r.design_signals, list)
