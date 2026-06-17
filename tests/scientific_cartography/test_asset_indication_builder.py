"""Tests for Phase 2 asset-indication builder."""

import pytest

from scientific_cartography.build.asset_indication_builder import AssetIndicationBuilder
from scientific_cartography.ingest.ctgov_ingest import CTGovIngest
from scientific_cartography.ingest.existing_universe_ingest import ExistingUniverseIngest
from scientific_cartography.normalize.asset_alias_resolver import AssetAliasResolver
from scientific_cartography.normalize.disease_normalizer import DiseaseNormalizer
from scientific_cartography.normalize.sponsor_resolver import SponsorResolver
from scientific_cartography.normalize.stage_normalizer import StageNormalizer
from scientific_cartography.schemas.company_schema import CompanyRecord
from scientific_cartography.schemas.trial_schema import TrialRecord


class TestAssetIndicationBuilder:
    """Test ProgramRecord building."""

    @pytest.fixture
    def normalizers(self):
        disease_norm = DiseaseNormalizer(as_of_date="2026-06-16")
        stage_norm = StageNormalizer()
        asset_resolver = AssetAliasResolver(as_of_date="2026-06-16")
        company_records = [
            CompanyRecord(
                company_id="COMP_111",
                ticker="COGT",
                company_name="Cognito Therapeutics",
                is_public=True,
                as_of_date="2026-06-16",
            ),
        ]
        sponsor_resolver = SponsorResolver(company_records=company_records)

        return disease_norm, stage_norm, asset_resolver, sponsor_resolver

    @pytest.fixture
    def builder(self, normalizers):
        disease_norm, stage_norm, asset_resolver, sponsor_resolver = normalizers
        return AssetIndicationBuilder(
            disease_normalizer=disease_norm,
            stage_normalizer=stage_norm,
            asset_alias_resolver=asset_resolver,
            sponsor_resolver=sponsor_resolver,
            as_of_date="2026-06-16",
        )

    def test_build_from_clean_trial(self, builder):
        """Should build ProgramRecords from clean trial data."""
        trials = [
            TrialRecord(
                nct_id="NCT03456789",
                brief_title="Study of Drug A in Disease",
                sponsor="Cognito Therapeutics",
                conditions=["Disease A"],
                interventions=["Drug A"],
                phases=["Phase 2"],
                overall_status="Active",
                source_ref="NCT03456789",
                as_of_date="2026-06-16",
            )
        ]

        programs, diagnostics = builder.build_from_trials(trials, [])

        assert len(programs) > 0
        assert programs[0].program_id
        assert programs[0].asset_name == "Drug A"
        assert programs[0].disease_name  # Should have normalized disease
        assert programs[0].as_of_date == "2026-06-16"
        assert "NCT03456789" in programs[0].source_refs

    def test_program_records_have_source_refs(self, builder):
        """Every ProgramRecord should have source_refs."""
        trials = [
            TrialRecord(
                nct_id="NCT12345678",
                brief_title="Test",
                sponsor="Cognito Therapeutics",
                conditions=["Condition A"],
                interventions=["Drug A"],
                phases=["Phase 1"],
                as_of_date="2026-06-16",
            )
        ]

        programs, _ = builder.build_from_trials(trials, [])

        for program in programs:
            assert program.source_refs is not None
            assert len(program.source_refs) > 0

    def test_build_multiple_interventions_and_conditions(self, builder):
        """Should create programs for each intervention/condition pair."""
        trials = [
            TrialRecord(
                nct_id="NCT99999999",
                brief_title="Multi-arm trial",
                sponsor="Cognito Therapeutics",
                conditions=["Disease A", "Disease B"],
                interventions=["Drug A", "Drug B"],
                phases=["Phase 2"],
                as_of_date="2026-06-16",
            )
        ]

        programs, diagnostics = builder.build_from_trials(trials, [])

        # Should create 2x2 = 4 programs
        assert len(programs) == 4
        assert diagnostics["total_programs"] == 4

    def test_unknown_disease_preservation(self, builder):
        """Unknown diseases should remain unknown with low confidence."""
        trials = [
            TrialRecord(
                nct_id="NCT88888888",
                brief_title="Test",
                sponsor="Cognito Therapeutics",
                conditions=["Completely Unknown Disease XYZ 123"],
                interventions=["Drug A"],
                phases=["Phase 1"],
                as_of_date="2026-06-16",
            )
        ]

        programs, diagnostics = builder.build_from_trials(trials, [])

        assert len(programs) > 0
        assert diagnostics["programs_with_unknown_disease"] > 0
        # Disease should be preserved with low confidence
        assert programs[0].disease_name == "Completely Unknown Disease XYZ 123"

    def test_unknown_sponsor_preservation(self, builder):
        """Unknown sponsors should be preserved."""
        trials = [
            TrialRecord(
                nct_id="NCT77777777",
                brief_title="Test",
                sponsor="Unknown Startup Inc",
                conditions=["Disease A"],
                interventions=["Drug A"],
                phases=["Phase 1"],
                as_of_date="2026-06-16",
            )
        ]

        programs, diagnostics = builder.build_from_trials(trials, [])

        assert len(programs) > 0
        assert diagnostics["programs_with_unknown_sponsor"] > 0
        # Sponsor name should be preserved
        assert programs[0].company_name == "Unknown Startup Inc"
        assert programs[0].ticker is None

    def test_stage_normalization_in_programs(self, builder):
        """Clinical stage should be normalized in programs."""
        trials = [
            TrialRecord(
                nct_id="NCT66666666",
                brief_title="Test",
                sponsor="Cognito Therapeutics",
                conditions=["Disease A"],
                interventions=["Drug A"],
                phases=["Phase 3"],
                as_of_date="2026-06-16",
            )
        ]

        programs, _ = builder.build_from_trials(trials, [])

        assert len(programs) > 0
        assert programs[0].clinical_stage == "phase3"

    def test_diagnostics_report(self, builder):
        """Should generate diagnostics report."""
        trials = [
            TrialRecord(
                nct_id="NCT55555555",
                brief_title="Test 1",
                sponsor="Cognito Therapeutics",
                conditions=["Disease A"],
                interventions=["Drug A"],
                phases=["Phase 1"],
                as_of_date="2026-06-16",
            ),
            TrialRecord(
                nct_id="NCT44444444",
                brief_title="Test 2",
                sponsor="Unknown Sponsor",
                conditions=["Unknown Disease"],
                interventions=["Drug B"],
                phases=["Phase 2"],
                as_of_date="2026-06-16",
            ),
        ]

        programs, diagnostics = builder.build_from_trials(trials, [])

        assert diagnostics["total_trials"] == 2
        assert diagnostics["total_programs"] >= 2
        assert diagnostics["programs_with_unknown_sponsor"] > 0
        assert diagnostics["programs_with_unknown_disease"] > 0

    def test_deterministic_program_id(self, builder):
        """Program IDs should be deterministic."""
        trials = [
            TrialRecord(
                nct_id="NCT33333333",
                brief_title="Test",
                sponsor="Cognito Therapeutics",
                conditions=["Disease A"],
                interventions=["Drug A"],
                phases=["Phase 1"],
                as_of_date="2026-06-16",
            )
        ]

        programs1, _ = builder.build_from_trials(trials, [])
        programs2, _ = builder.build_from_trials(trials, [])

        assert programs1[0].program_id == programs2[0].program_id

    def test_skip_trial_without_conditions(self, builder):
        """Should skip trials without conditions."""
        trials = [
            TrialRecord(
                nct_id="NCT22222222",
                brief_title="Test",
                sponsor="Cognito Therapeutics",
                conditions=[],  # No conditions
                interventions=["Drug A"],
                phases=["Phase 1"],
                as_of_date="2026-06-16",
            )
        ]

        programs, diagnostics = builder.build_from_trials(trials, [])

        # Should be skipped or have warning
        assert len(programs) == 0 or diagnostics["programs_with_unknown_disease"] == len(programs)

    def test_skip_trial_without_interventions(self, builder):
        """Should skip trials without interventions."""
        trials = [
            TrialRecord(
                nct_id="NCT11111111",
                brief_title="Test",
                sponsor="Cognito Therapeutics",
                conditions=["Disease A"],
                interventions=[],  # No interventions
                phases=["Phase 1"],
                as_of_date="2026-06-16",
            )
        ]

        programs, diagnostics = builder.build_from_trials(trials, [])

        # Should be skipped or have warning
        assert len(programs) == 0
