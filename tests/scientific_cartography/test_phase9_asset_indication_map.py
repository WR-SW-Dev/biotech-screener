"""Phase 9 Asset Indication Map tests.

Tests for diagnostic reference layer that wraps ProgramRecords
and enriches with Phase 8 disease ontology resolution.
"""

import pytest

from scientific_cartography.build.asset_indication_map_builder import AssetIndicationMapBuilder
from scientific_cartography.build.disease_ontology_builder import DiseaseOntologyBuilder
from scientific_cartography.normalize.disease_normalizer import DiseaseNormalizer
from scientific_cartography.schemas.asset_indication_map_schema import (
    AssetIndicationMapCoverageReport,
    AssetIndicationMapRecord,
)
from scientific_cartography.schemas.program_schema import ProgramRecord


@pytest.fixture
def mondo_fixture():
    """MONDO fixture for testing."""
    return {
        "atopic dermatitis": {
            "id": "MONDO:0004980",
            "name": "Atopic Dermatitis",
            "synonyms": ["AD", "eczema"],
            "therapeutic_area": "Dermatology",
        },
        "multiple myeloma": {
            "id": "MONDO:0018874",
            "name": "Multiple Myeloma",
            "synonyms": ["MM", "myeloma"],
            "therapeutic_area": "Oncology",
        },
    }


@pytest.fixture
def disease_normalizer(mondo_fixture):
    """Disease normalizer with fixture."""
    return DiseaseNormalizer(mondo_cache=mondo_fixture, as_of_date="2026-06-17")


@pytest.fixture
def disease_ontology_builder(disease_normalizer):
    """Disease ontology builder."""
    return DiseaseOntologyBuilder(
        as_of_date="2026-06-17",
        disease_normalizer=disease_normalizer,
    )


@pytest.fixture
def asset_indication_builder(disease_ontology_builder):
    """Asset indication map builder."""
    return AssetIndicationMapBuilder(
        as_of_date="2026-06-17",
        disease_ontology_builder=disease_ontology_builder,
    )


class TestAssetIndicationMapSchema:
    """Test schema and serialization."""

    def test_record_initialization(self):
        """Record initializes with required fields."""
        record = AssetIndicationMapRecord(
            record_id="abc123",
            asset_name="VX-548",
            raw_indication="Pain",
            normalized_disease_name="Pain",
            as_of_date="2026-06-17",
        )

        assert record.record_id == "abc123"
        assert record.asset_name == "VX-548"
        assert record.governance["production_model_change"] is False

    def test_record_to_dict(self):
        """Record serializes to dictionary."""
        record = AssetIndicationMapRecord(
            record_id="test123",
            company_name="Vertex",
            ticker="VRTX",
            asset_name="VX-548",
            raw_indication="Atopic Dermatitis",
            normalized_disease_name="Atopic Dermatitis",
            mondo_id="MONDO:0004980",
            therapeutic_area="Dermatology",
            overall_confidence=0.95,
            as_of_date="2026-06-17",
        )

        d = record.to_dict()
        assert d["ticker"] == "VRTX"
        assert d["mondo_id"] == "MONDO:0004980"
        assert d["governance"]["production_model_change"] is False

    def test_coverage_report_initialization(self):
        """Coverage report initializes."""
        report = AssetIndicationMapCoverageReport(as_of_date="2026-06-17")
        assert report.total_records == 0
        assert report.governance["read_only_diagnostic"] is True


class TestAssetIndicationMapBuilder:
    """Test builder and disease enrichment."""

    def test_builds_record_from_program(self, asset_indication_builder):
        """Creates map record from ProgramRecord."""
        program = ProgramRecord(
            program_id="prog1",
            asset_id="asset1",
            asset_name="VX-548",
            company_id="VRTX",
            ticker="VRTX",
            company_name="Vertex",
            disease_id="disease1",
            disease_name="Atopic Dermatitis",
            source_priority="ctgov",
            as_of_date="2026-06-17",
        )

        records, coverage = asset_indication_builder.build_from_programs([program])

        assert len(records) == 1
        record = records[0]
        assert record.asset_name == "VX-548"
        assert record.ticker == "VRTX"

    def test_disease_ontology_enrichment(self, asset_indication_builder):
        """Disease ontology mapping populates mondo_id and therapeutic_area."""
        program = ProgramRecord(
            program_id="prog1",
            asset_id="asset1",
            asset_name="VX-548",
            disease_name="Atopic Dermatitis",
            source_priority="ctgov",
            as_of_date="2026-06-17",
        )

        records, _ = asset_indication_builder.build_from_programs([program])

        assert len(records) == 1
        record = records[0]
        assert record.mondo_id == "MONDO:0004980"
        assert record.therapeutic_area == "Dermatology"
        assert record.normalized_disease_name == "Atopic Dermatitis"

    def test_unknown_disease_preserved(self, asset_indication_builder):
        """Unknown disease is preserved with mondo_id null and warning."""
        program = ProgramRecord(
            program_id="prog1",
            asset_id="asset1",
            asset_name="Asset X",
            disease_name="Unknown Syndrome X",
            source_priority="ctgov",
            as_of_date="2026-06-17",
        )

        records, coverage = asset_indication_builder.build_from_programs([program])

        assert len(records) == 1
        record = records[0]
        assert record.mondo_id is None
        assert record.normalized_disease_name == "Unknown Syndrome X"
        assert any("not mapped" in w.lower() for w in record.warnings)
        assert coverage.unknown_disease_count == 1

    def test_ticker_preserved(self, asset_indication_builder):
        """Ticker and company fields preserved from ProgramRecord."""
        program = ProgramRecord(
            program_id="prog1",
            asset_id="asset1",
            asset_name="VX-548",
            company_id="VRTX",
            ticker="VRTX",
            company_name="Vertex Pharmaceuticals",
            disease_name="Atopic Dermatitis",
            source_priority="ctgov",
            as_of_date="2026-06-17",
        )

        records, _ = asset_indication_builder.build_from_programs([program])

        record = records[0]
        assert record.ticker == "VRTX"
        assert record.company_id == "VRTX"
        assert record.company_name == "Vertex Pharmaceuticals"

    def test_source_priority_assigned(self, asset_indication_builder):
        """Source priority is assigned deterministically."""
        program = ProgramRecord(
            program_id="prog1",
            asset_id="asset1",
            asset_name="Asset1",
            disease_name="Atopic Dermatitis",
            source_priority="ctgov",
            as_of_date="2026-06-17",
        )

        records, _ = asset_indication_builder.build_from_programs([program])

        record = records[0]
        assert record.source_type == "ctgov"
        assert record.source_priority == 3  # ctgov = 3

    def test_confidence_capped_with_unknown_disease(self, asset_indication_builder):
        """Confidence is capped when disease ontology is unknown."""
        program = ProgramRecord(
            program_id="prog1",
            asset_id="asset1",
            asset_name="Asset1",
            disease_name="Unknown Disease",
            confidence=0.95,
            source_priority="ctgov",
            as_of_date="2026-06-17",
        )

        records, _ = asset_indication_builder.build_from_programs([program])

        record = records[0]
        # Overall confidence should be capped by unknown disease
        assert record.overall_confidence == 0.0

    def test_same_company_asset_disease(self, asset_indication_builder):
        """Records map same company-asset-disease relationships."""
        program1 = ProgramRecord(
            program_id="prog1",
            asset_id="asset1",
            asset_name="VX-548",
            company_id="VRTX",
            disease_name="Atopic Dermatitis",
            source_priority="ctgov",
            as_of_date="2026-06-17",
        )

        program2 = ProgramRecord(
            program_id="prog2",
            asset_id="asset1",  # Same asset
            asset_name="VX-548",
            company_id="VRTX",  # Same company
            disease_name="Atopic Dermatitis",  # Same disease
            source_priority="manual",  # Different source
            as_of_date="2026-06-17",
        )

        records, _ = asset_indication_builder.build_from_programs([program1, program2])

        # Should have 2 records (one per source)
        assert len(records) == 2
        # Both records map the same company-asset-disease relationship
        assert records[0].company_id == records[1].company_id
        assert records[0].asset_name == records[1].asset_name
        # Both come from same raw indication (even if ontology varies)
        assert records[0].raw_indication == records[1].raw_indication
        # At least one should have MONDO mapping (ctgov source)
        assert records[0].mondo_id is not None or records[1].mondo_id is not None

    def test_different_assets_not_collapsed(self, asset_indication_builder):
        """Different assets for same company/disease do not collapse."""
        program1 = ProgramRecord(
            program_id="prog1",
            asset_id="asset1",
            asset_name="Asset1",
            company_id="VRTX",
            disease_name="Atopic Dermatitis",
            source_priority="ctgov",
            as_of_date="2026-06-17",
        )

        program2 = ProgramRecord(
            program_id="prog2",
            asset_id="asset2",  # Different asset
            asset_name="Asset2",
            company_id="VRTX",  # Same company
            disease_name="Atopic Dermatitis",  # Same disease
            source_priority="ctgov",
            as_of_date="2026-06-17",
        )

        records, _ = asset_indication_builder.build_from_programs([program1, program2])

        # Should keep both records
        assert len(records) == 2
        assert records[0].asset_name != records[1].asset_name

    def test_different_diseases_not_collapsed(self, asset_indication_builder):
        """Different diseases for same asset do not collapse."""
        program1 = ProgramRecord(
            program_id="prog1",
            asset_id="asset1",
            asset_name="VX-548",
            company_id="VRTX",
            disease_name="Atopic Dermatitis",
            source_priority="ctgov",
            as_of_date="2026-06-17",
        )

        program2 = ProgramRecord(
            program_id="prog2",
            asset_id="asset1",  # Same asset
            asset_name="VX-548",
            company_id="VRTX",  # Same company
            disease_name="Multiple Myeloma",  # Different disease
            source_priority="ctgov",
            as_of_date="2026-06-17",
        )

        records, _ = asset_indication_builder.build_from_programs([program1, program2])

        # Should keep both records
        assert len(records) == 2
        assert records[0].mondo_id != records[1].mondo_id


class TestCoverageReport:
    """Test coverage reporting."""

    def test_counts_unique_values(self, asset_indication_builder):
        """Coverage report counts unique companies/tickers/assets/diseases."""
        programs = [
            ProgramRecord(
                program_id="prog1",
                asset_id="asset1",
                asset_name="VX-548",
                company_id="VRTX",
                ticker="VRTX",
                disease_name="Atopic Dermatitis",
                source_priority="ctgov",
                as_of_date="2026-06-17",
            ),
            ProgramRecord(
                program_id="prog2",
                asset_id="asset2",
                asset_name="ACLX1",
                company_id="ACLX",
                ticker="ACLX",
                disease_name="Multiple Myeloma",
                source_priority="ctgov",
                as_of_date="2026-06-17",
            ),
            ProgramRecord(
                program_id="prog3",
                asset_id="asset1",  # Duplicate asset
                asset_name="VX-548",
                company_id="VRTX",  # Duplicate company
                disease_name="Multiple Myeloma",
                source_priority="ctgov",
                as_of_date="2026-06-17",
            ),
        ]

        _, coverage = asset_indication_builder.build_from_programs(programs)

        assert coverage.total_records == 3
        assert coverage.unique_companies == 2  # VRTX, ACLX
        assert coverage.unique_tickers == 2  # VRTX, ACLX
        assert coverage.unique_assets == 2  # asset1, asset2
        assert coverage.unique_mondo_diseases == 2  # AD, MM

    def test_records_by_source_type(self, asset_indication_builder):
        """Coverage report records source_type distribution."""
        programs = [
            ProgramRecord(
                program_id="prog1",
                asset_id="asset1",
                asset_name="Asset1",
                disease_name="Atopic Dermatitis",
                source_priority="ctgov",
                as_of_date="2026-06-17",
            ),
            ProgramRecord(
                program_id="prog2",
                asset_id="asset2",
                asset_name="Asset2",
                disease_name="Multiple Myeloma",
                source_priority="manual",
                as_of_date="2026-06-17",
            ),
        ]

        _, coverage = asset_indication_builder.build_from_programs(programs)

        assert coverage.records_by_source_type.get("ctgov", 0) == 1
        assert coverage.records_by_source_type.get("manual", 0) == 1

    def test_governance_flags(self, asset_indication_builder):
        """Governance flags are present and production changes are false."""
        program = ProgramRecord(
            program_id="prog1",
            asset_id="asset1",
            asset_name="Asset1",
            disease_name="Atopic Dermatitis",
            source_priority="ctgov",
            as_of_date="2026-06-17",
        )

        records, coverage = asset_indication_builder.build_from_programs([program])

        record = records[0]
        assert record.governance["read_only_diagnostic"] is True
        assert record.governance["production_model_change"] is False
        assert record.governance["ranker_change"] is False

        assert coverage.governance["read_only_diagnostic"] is True
        assert coverage.governance["production_model_change"] is False
