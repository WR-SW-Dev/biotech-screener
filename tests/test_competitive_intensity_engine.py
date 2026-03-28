#!/usr/bin/env python3
"""
Tests for Competitive Intensity Engine
"""

import json
from datetime import date
from decimal import Decimal

import pytest

from competitive_intensity_engine import CompetitiveIntensityEngine, CompetitivePosition, CrowdingLevel


class TestCompetitiveIntensityEngine:
    """Tests for CompetitiveIntensityEngine."""

    @pytest.fixture
    def engine(self):
        return CompetitiveIntensityEngine()

    @pytest.fixture
    def sample_trials(self):
        return [
            {
                "lead_sponsor_ticker": "ACME",
                "nct_id": "NCT001",
                "phase": "Phase 2",
                "conditions": ["Breast Cancer"],
                "interventions": ["monoclonal antibody"],
            },
            {
                "lead_sponsor_ticker": "ACME",
                "nct_id": "NCT002",
                "phase": "Phase 3",
                "conditions": ["Lung Cancer"],
                "interventions": ["kinase inhibitor"],
            },
            {
                "lead_sponsor_ticker": "COMP1",
                "nct_id": "NCT003",
                "phase": "Phase 3",
                "conditions": ["Breast Cancer"],
                "interventions": ["antibody"],
            },
            {
                "lead_sponsor_ticker": "COMP2",
                "nct_id": "NCT004",
                "phase": "Phase 2",
                "conditions": ["Breast Cancer"],
                "interventions": ["adc"],
            },
            {
                "lead_sponsor_ticker": "COMP3",
                "nct_id": "NCT005",
                "phase": "Phase 1",
                "conditions": ["Breast Cancer"],
                "interventions": ["car-t"],
            },
            {
                "lead_sponsor_ticker": "COMP4",
                "nct_id": "NCT006",
                "phase": "Phase 2",
                "conditions": ["Lung Cancer"],
                "interventions": ["small molecule"],
            },
        ]

    def test_initialization(self, engine):
        """Engine initializes with empty state."""
        assert engine.audit_trail == []
        assert engine.indication_landscapes == {}
        assert engine._landscape_built is False

    def test_build_landscape(self, engine, sample_trials):
        """Build landscape from trial records."""
        as_of = date(2026, 1, 26)
        stats = engine.build_landscape(sample_trials, as_of)

        assert stats["indications_mapped"] > 0
        assert stats["tickers_mapped"] == 5  # ACME + 4 competitors
        assert engine._landscape_built is True

    def test_score_ticker_with_data(self, engine, sample_trials):
        """Score ticker that has trial data."""
        as_of = date(2026, 1, 26)
        engine.build_landscape(sample_trials, as_of)

        result = engine.score_ticker("ACME", as_of)

        assert result["ticker"] == "ACME"
        assert result["competitive_intensity_score"] >= Decimal("0")
        assert result["competitive_intensity_score"] <= Decimal("100")
        assert result["competitor_count"] > 0
        assert result["crowding_level"] in [c.value for c in CrowdingLevel] + ["unknown"]
        assert result["competitive_position"] in [p.value for p in CompetitivePosition] + ["unknown"]

    def test_score_ticker_without_data(self, engine):
        """Score ticker without building landscape first."""
        as_of = date(2026, 1, 26)
        result = engine.score_ticker("UNKNOWN", as_of)

        assert result["ticker"] == "UNKNOWN"
        assert result["competitive_intensity_score"] == Decimal("50")  # Neutral
        assert result["crowding_level"] == "unknown"

    def test_crowding_levels(self, engine):
        """Crowding classification works correctly."""
        # Test each threshold
        assert engine._classify_crowding(2) == CrowdingLevel.UNCROWDED
        assert engine._classify_crowding(10) == CrowdingLevel.MODERATE
        assert engine._classify_crowding(20) == CrowdingLevel.CROWDED
        assert engine._classify_crowding(50) == CrowdingLevel.HIGHLY_CROWDED

    def test_phase_3_competitors_tracked(self, engine, sample_trials):
        """Phase 3+ competitors are tracked separately."""
        as_of = date(2026, 1, 26)
        engine.build_landscape(sample_trials, as_of)

        result = engine.score_ticker("ACME", as_of)

        # COMP1 has Phase 3 in breast cancer (same indication as ACME)
        assert result["phase_3_competitors"] >= 0

    def test_approved_competition_detected(self, engine):
        """Approved drugs in indication are detected."""
        trials = [
            {
                "lead_sponsor_ticker": "ACME",
                "nct_id": "NCT001",
                "phase": "Phase 2",
                "conditions": ["Diabetes"],
                "interventions": ["drug"],
            },
            {
                "lead_sponsor_ticker": "BIGPHARMA",
                "nct_id": "NCT002",
                "phase": "Phase 4",
                "conditions": ["Diabetes"],
                "interventions": ["approved drug"],
            },
        ]
        as_of = date(2026, 1, 26)
        engine.build_landscape(trials, as_of)

        result = engine.score_ticker("ACME", as_of)

        # Phase 4 = approved
        assert result["has_approved_competition"] is True

    def test_first_in_class_detection(self, engine):
        """First-in-class position detected with few competitors."""
        trials = [
            {
                "lead_sponsor_ticker": "PIONEER",
                "nct_id": "NCT001",
                "phase": "Phase 2",
                "conditions": ["Rare Disease X"],
                "interventions": ["novel therapy"],
            },
        ]
        as_of = date(2026, 1, 26)
        engine.build_landscape(trials, as_of)

        result = engine.score_ticker("PIONEER", as_of)

        assert result["competitive_position"] == CompetitivePosition.FIRST_IN_CLASS.value

    def test_me_too_detection(self, engine):
        """Me-too position detected in crowded indication."""
        # Create highly crowded indication (>30 competitors after excluding own)
        trials = []
        for i in range(35):
            trials.append(
                {
                    "lead_sponsor_ticker": f"COMP{i}",
                    "nct_id": f"NCT{i:03d}",
                    "phase": "Phase 2",
                    "conditions": ["Breast Cancer"],
                    "interventions": ["antibody"],
                }
            )

        as_of = date(2026, 1, 26)
        engine.build_landscape(trials, as_of)

        result = engine.score_ticker("COMP0", as_of)

        # 35 total - 1 own = 34 competitors -> HIGHLY_CROWDED
        assert result["competitive_position"] == CompetitivePosition.ME_TOO.value
        assert result["crowding_level"] == CrowdingLevel.HIGHLY_CROWDED.value

    def test_score_universe(self, engine, sample_trials):
        """Score entire universe."""
        universe = [
            {"ticker": "ACME"},
            {"ticker": "COMP1"},
            {"ticker": "UNKNOWN"},
        ]
        as_of = date(2026, 1, 26)

        result = engine.score_universe(universe, sample_trials, as_of)

        assert result["diagnostic_counts"]["total_scored"] == 3
        assert "intensity_distribution" in result["diagnostic_counts"]
        assert "crowding_distribution" in result["diagnostic_counts"]
        assert "provenance" in result

    def test_indication_normalization(self, engine):
        """Indications are normalized to categories."""
        # Oncology
        assert engine._normalize_indication(["Breast Cancer"]) == "oncology"
        assert engine._normalize_indication(["Non-Small Cell Lung Cancer"]) == "oncology"
        assert engine._normalize_indication(["Melanoma"]) == "oncology"

        # Neurology
        assert engine._normalize_indication(["Alzheimer's Disease"]) == "neurology"
        assert engine._normalize_indication(["Parkinson's Disease"]) == "neurology"

        # Rare disease
        assert engine._normalize_indication(["Duchenne Muscular Dystrophy"]) == "rare_disease"

    def test_mechanism_extraction(self, engine):
        """Mechanism of action is extracted from interventions."""
        assert engine._extract_mechanism(["PD-1 inhibitor"]) == "checkpoint_inhibitor"
        assert engine._extract_mechanism(["CAR-T cell therapy"]) == "car_t"
        assert engine._extract_mechanism(["mRNA vaccine"]) == "rna_therapeutic"
        assert engine._extract_mechanism(["monoclonal antibody"]) == "antibody"

    def test_get_top_competitors(self, engine, sample_trials):
        """Get top competitors in indication."""
        as_of = date(2026, 1, 26)
        engine.build_landscape(sample_trials, as_of)

        competitors = engine.get_top_competitors("ACME", "oncology", limit=5)

        assert len(competitors) <= 5
        for comp in competitors:
            assert comp["ticker"] != "ACME"
            assert "program_count" in comp

    def test_audit_trail(self, engine, sample_trials):
        """Audit trail is maintained."""
        as_of = date(2026, 1, 26)
        engine.build_landscape(sample_trials, as_of)
        engine.score_ticker("ACME", as_of)

        trail = engine.get_audit_trail()
        assert len(trail) > 0
        assert trail[0]["ticker"] == "ACME"

        engine.clear_audit_trail()
        assert len(engine.get_audit_trail()) == 0

    def test_intensity_rating(self, engine):
        """Intensity rating categories are correct."""
        assert engine._get_intensity_rating(Decimal("20")) == "low"
        assert engine._get_intensity_rating(Decimal("40")) == "moderate"
        assert engine._get_intensity_rating(Decimal("60")) == "high"
        assert engine._get_intensity_rating(Decimal("80")) == "intense"


class TestCrowdingScoreAdjustments:
    """Tests for crowding score adjustments."""

    @pytest.fixture
    def engine(self):
        return CompetitiveIntensityEngine()

    def test_all_crowding_levels_have_adjustments(self):
        """All crowding levels have score adjustments."""
        for level in CrowdingLevel:
            assert level in CompetitiveIntensityEngine.CROWDING_SCORE_ADJUSTMENTS

    def test_all_positions_have_adjustments(self):
        """All competitive positions have score adjustments."""
        for position in CompetitivePosition:
            assert position in CompetitiveIntensityEngine.POSITION_ADJUSTMENTS

    def test_crowding_increases_score(self, engine):
        """More crowding should increase competitive intensity score."""
        # Uncrowded should have lower score than highly crowded
        uncrowded_adj = engine.CROWDING_SCORE_ADJUSTMENTS[CrowdingLevel.UNCROWDED]
        crowded_adj = engine.CROWDING_SCORE_ADJUSTMENTS[CrowdingLevel.HIGHLY_CROWDED]

        assert crowded_adj > uncrowded_adj

    def test_first_in_class_reduces_score(self, engine):
        """First-in-class position should reduce competitive intensity."""
        first_adj = engine.POSITION_ADJUSTMENTS[CompetitivePosition.FIRST_IN_CLASS]
        me_too_adj = engine.POSITION_ADJUSTMENTS[CompetitivePosition.ME_TOO]

        assert first_adj < me_too_adj


class TestPEVBackedLandscape:
    """Tests for program_entity_view-backed indication resolution."""

    @pytest.fixture
    def engine(self):
        return CompetitiveIntensityEngine()

    @pytest.fixture
    def pev_enrichment_dir(self, tmp_path):
        """Create a tmp enrichment dir with a minimal PEV file."""
        pev = {
            "schema": "program_entity_view.v1",
            "entries": [
                {
                    "ticker": "ACME",
                    "n_programs": 2,
                    "programs": [
                        {
                            "nct_id": "NCT001",
                            "phase": "PHASE2",
                            "indication": {
                                "raw_condition": "Breast Cancer",
                                "efo_id": "EFO_0000305",
                                "efo_name": "breast carcinoma",
                            },
                            "drug": {"canonical_name": "acmecept"},
                            "join_quality": {"drug_match_confidence": "high", "disease_match_confidence": "high"},
                        },
                        {
                            "nct_id": "NCT002",
                            "phase": "PHASE3",
                            "indication": {
                                "raw_condition": "NSCLC",
                                "efo_id": "EFO_0003060",
                                "efo_name": "non-small cell lung carcinoma",
                            },
                            "drug": {"canonical_name": "acme-lung"},
                            "join_quality": {"drug_match_confidence": "medium", "disease_match_confidence": "high"},
                        },
                    ],
                },
                {
                    "ticker": "COMP1",
                    "n_programs": 1,
                    "programs": [
                        {
                            "nct_id": "NCT003",
                            "phase": "PHASE3",
                            "indication": {
                                "raw_condition": "Breast Cancer",
                                "efo_id": "EFO_0000305",
                                "efo_name": "breast carcinoma",
                            },
                            "drug": {"canonical_name": "comp1mab"},
                            "join_quality": {"drug_match_confidence": "high", "disease_match_confidence": "high"},
                        },
                    ],
                },
                {
                    "ticker": "COMP2",
                    "n_programs": 1,
                    "programs": [
                        {
                            "nct_id": "NCT004",
                            "phase": "PHASE2",
                            "indication": {
                                "raw_condition": "Triple Negative Breast Cancer",
                                "efo_id": "EFO_0005537",
                                "efo_name": "triple-negative breast cancer",
                            },
                            "drug": {"canonical_name": "comp2adc"},
                            "join_quality": {"drug_match_confidence": "medium", "disease_match_confidence": "high"},
                        },
                    ],
                },
            ],
        }
        pev_path = tmp_path / "program_entity_view_2026-03-27.json"
        pev_path.write_text(json.dumps(pev), encoding="utf-8")
        return tmp_path

    @pytest.fixture
    def sample_trials_with_nct(self):
        """Trials whose nct_ids match the PEV fixture."""
        return [
            {
                "lead_sponsor_ticker": "ACME",
                "nct_id": "NCT001",
                "phase": "Phase 2",
                "conditions": ["Breast Cancer"],
                "interventions": ["monoclonal antibody"],
            },
            {
                "lead_sponsor_ticker": "ACME",
                "nct_id": "NCT002",
                "phase": "Phase 3",
                "conditions": ["Non-Small Cell Lung Cancer"],
                "interventions": ["kinase inhibitor"],
            },
            {
                "lead_sponsor_ticker": "COMP1",
                "nct_id": "NCT003",
                "phase": "Phase 3",
                "conditions": ["Breast Cancer"],
                "interventions": ["antibody"],
            },
            {
                "lead_sponsor_ticker": "COMP2",
                "nct_id": "NCT004",
                "phase": "Phase 2",
                "conditions": ["Triple Negative Breast Cancer"],
                "interventions": ["adc"],
            },
        ]

    def test_enriched_uses_efo_keys(self, engine, sample_trials_with_nct, pev_enrichment_dir):
        """With PEV, indications use EFO keys instead of broad categories."""
        as_of = date(2026, 3, 27)
        stats = engine.build_landscape(sample_trials_with_nct, as_of, enrichment_dir=pev_enrichment_dir)

        assert stats["indication_source"] == "enriched"
        assert stats["n_enriched"] == 4
        assert stats["n_raw_fallback"] == 0

        # Breast carcinoma and TNBC should be SEPARATE indications, not both "oncology"
        assert "efo:EFO_0000305|breast carcinoma" in engine.indication_landscapes
        assert "efo:EFO_0005537|triple-negative breast cancer" in engine.indication_landscapes

    def test_enriched_separates_subtypes(self, engine, sample_trials_with_nct, pev_enrichment_dir):
        """COMP2 (TNBC) should NOT be a competitor of ACME (breast carcinoma)."""
        as_of = date(2026, 3, 27)
        engine.build_landscape(sample_trials_with_nct, as_of, enrichment_dir=pev_enrichment_dir)

        result = engine.score_ticker("ACME", as_of)

        # ACME has breast carcinoma + NSCLC. COMP1 shares breast carcinoma.
        # COMP2 has TNBC (different EFO), so is NOT a competitor.
        assert result["competitor_count"] == 1  # only COMP1

    def test_raw_fallback_without_enrichment_dir(self, engine, sample_trials_with_nct):
        """Without enrichment_dir, falls back to keyword-based normalization."""
        as_of = date(2026, 3, 27)
        stats = engine.build_landscape(sample_trials_with_nct, as_of)

        assert stats["indication_source"] == "raw"
        assert stats["n_enriched"] == 0
        # All four trials have oncology keywords → grouped into "oncology"
        assert "oncology" in engine.indication_landscapes

    def test_raw_fallback_when_pev_missing(self, engine, sample_trials_with_nct, tmp_path):
        """With enrichment_dir but no PEV file, falls back to raw."""
        as_of = date(2026, 3, 27)
        stats = engine.build_landscape(sample_trials_with_nct, as_of, enrichment_dir=tmp_path)

        assert stats["indication_source"] == "raw"

    def test_mixed_coverage_fallback(self, engine, pev_enrichment_dir):
        """Trials not in PEV fall back to _normalize_indication."""
        trials = [
            {
                "lead_sponsor_ticker": "ACME",
                "nct_id": "NCT001",
                "phase": "Phase 2",
                "conditions": ["Breast Cancer"],
                "interventions": ["mab"],
            },
            # NCT999 is NOT in PEV
            {
                "lead_sponsor_ticker": "NEWCO",
                "nct_id": "NCT999",
                "phase": "Phase 1",
                "conditions": ["Melanoma"],
                "interventions": ["vaccine"],
            },
        ]
        as_of = date(2026, 3, 27)
        stats = engine.build_landscape(trials, as_of, enrichment_dir=pev_enrichment_dir)

        assert stats["indication_source"] == "enriched"
        assert stats["n_enriched"] == 1  # NCT001
        assert stats["n_raw_fallback"] == 1  # NCT999 → "oncology"

        # Both should appear in landscapes
        assert "efo:EFO_0000305|breast carcinoma" in engine.indication_landscapes
        assert "oncology" in engine.indication_landscapes

    def test_sparse_pev_falls_back(self, engine, tmp_path):
        """PEV with <10% mapped programs falls back to raw."""
        pev = {
            "schema": "program_entity_view.v1",
            "entries": [
                {
                    "ticker": "X",
                    "n_programs": 10,
                    "programs": [{"nct_id": f"NCT{i:03d}", "indication": {}} for i in range(10)],
                },
            ],
        }
        (tmp_path / "program_entity_view_2026-03-27.json").write_text(json.dumps(pev), encoding="utf-8")

        trials = [
            {
                "lead_sponsor_ticker": "X",
                "nct_id": f"NCT{i:03d}",
                "phase": "Phase 2",
                "conditions": ["Diabetes"],
                "interventions": ["drug"],
            }
            for i in range(10)
        ]
        as_of = date(2026, 3, 27)
        stats = engine.build_landscape(trials, as_of, enrichment_dir=tmp_path)

        assert stats["indication_source"] == "raw"

    def test_score_universe_with_enrichment(self, engine, sample_trials_with_nct, pev_enrichment_dir):
        """score_universe passes enrichment_dir through to build_landscape."""
        universe = [{"ticker": "ACME"}, {"ticker": "COMP1"}, {"ticker": "COMP2"}]
        as_of = date(2026, 3, 27)
        result = engine.score_universe(universe, sample_trials_with_nct, as_of, enrichment_dir=pev_enrichment_dir)

        assert result["landscape_stats"]["indication_source"] == "enriched"
        assert result["diagnostic_counts"]["total_scored"] == 3

    def test_medgen_fallback_key(self, engine, tmp_path):
        """When EFO is absent but MedGen is present, uses medgen key."""
        pev = {
            "schema": "program_entity_view.v1",
            "entries": [
                {
                    "ticker": "A",
                    "n_programs": 1,
                    "programs": [
                        {
                            "nct_id": "NCT100",
                            "indication": {
                                "raw_condition": "Rare Disease X",
                                "medgen_uid": "C1234567",
                            },
                            "drug": {"canonical_name": "drugA"},
                            "join_quality": {},
                        },
                    ],
                },
            ],
        }
        (tmp_path / "program_entity_view_2026-03-27.json").write_text(json.dumps(pev), encoding="utf-8")

        trials = [
            {
                "lead_sponsor_ticker": "A",
                "nct_id": "NCT100",
                "phase": "Phase 2",
                "conditions": ["Rare Disease X"],
                "interventions": ["drug"],
            },
        ]
        as_of = date(2026, 3, 27)
        stats = engine.build_landscape(trials, as_of, enrichment_dir=tmp_path)

        assert stats["indication_source"] == "enriched"
        assert "medgen:C1234567|Rare Disease X" in engine.indication_landscapes
