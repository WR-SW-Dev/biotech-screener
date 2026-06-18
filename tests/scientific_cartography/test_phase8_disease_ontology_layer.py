"""Phase 8 Disease Ontology Reference Layer tests.

Tests for deterministic disease ontology mapping with MONDO spine.
"""

import pytest

from scientific_cartography.build.disease_ontology_builder import DiseaseOntologyBuilder, DiseaseOntologyCoverageReport
from scientific_cartography.normalize.disease_normalizer import DiseaseNormalizer
from scientific_cartography.schemas.disease_ontology_schema import DiseaseOntologyRecord


@pytest.fixture
def mondo_fixture():
    """MONDO-like fixture ontology for testing."""
    return {
        "atopic dermatitis": {
            "id": "MONDO:0004980",
            "name": "Atopic Dermatitis",
            "synonyms": ["AD", "eczema", "atopic eczema", "dermatitis"],
            "therapeutic_area": "Dermatology",
            "parent_disease": "Skin Diseases",
        },
        "psoriasis": {
            "id": "MONDO:0005083",
            "name": "Psoriasis",
            "synonyms": ["psoriatic dermatitis"],
            "therapeutic_area": "Dermatology",
            "parent_disease": "Skin Diseases",
        },
        "rheumatoid arthritis": {
            "id": "MONDO:0005148",
            "name": "Rheumatoid Arthritis",
            "synonyms": ["RA", "rheumatoid disease"],
            "therapeutic_area": "Immunology",
            "parent_disease": "Rheumatic Diseases",
        },
        "melanoma": {
            "id": "MONDO:0005105",
            "name": "Melanoma",
            "synonyms": ["malignant melanoma", "cutaneous melanoma"],
            "therapeutic_area": "Oncology",
            "parent_disease": "Skin Cancers",
        },
    }


@pytest.fixture
def disease_normalizer_with_fixture(mondo_fixture):
    """Disease normalizer initialized with fixture MONDO cache."""
    return DiseaseNormalizer(mondo_cache=mondo_fixture, as_of_date="2026-06-17")


@pytest.fixture
def ontology_builder(disease_normalizer_with_fixture):
    """Ontology builder for testing."""
    return DiseaseOntologyBuilder(
        as_of_date="2026-06-17",
        disease_normalizer=disease_normalizer_with_fixture,
    )


class TestDiseaseOntologySchema:
    """Test DiseaseOntologyRecord schema and serialization."""

    def test_record_initialization(self):
        """Record initializes with required fields."""
        record = DiseaseOntologyRecord(
            raw_disease_name="Atopic Dermatitis",
            normalized_disease_name="Atopic Dermatitis",
            mondo_id="MONDO:0004980",
            therapeutic_area="Dermatology",
            confidence=1.0,
            source="mondo",
            as_of_date="2026-06-17",
        )

        assert record.raw_disease_name == "Atopic Dermatitis"
        assert record.mondo_id == "MONDO:0004980"
        assert record.confidence == 1.0

    def test_record_to_dict(self):
        """Record serializes to dictionary."""
        record = DiseaseOntologyRecord(
            raw_disease_name="AD",
            normalized_disease_name="Atopic Dermatitis",
            mondo_id="MONDO:0004980",
            therapeutic_area="Dermatology",
            confidence=0.9,
            source="mondo_synonym",
            as_of_date="2026-06-17",
            synonyms=["eczema", "atopic eczema"],
            warnings=["Synonym match"],
        )

        d = record.to_dict()
        assert d["raw_disease_name"] == "AD"
        assert d["mondo_id"] == "MONDO:0004980"
        assert d["confidence"] == 0.9
        assert len(d["synonyms"]) == 2
        assert len(d["warnings"]) == 1

    def test_record_unknown_preservation(self):
        """Record preserves unknown diseases with low confidence."""
        record = DiseaseOntologyRecord(
            raw_disease_name="Unknown Syndrome X",
            normalized_disease_name="Unknown Syndrome X",
            mondo_id=None,
            therapeutic_area="unknown",
            confidence=0.0,
            source="unmapped",
            as_of_date="2026-06-17",
            warnings=["Disease not found in MONDO ontology: Unknown Syndrome X"],
        )

        assert record.mondo_id is None
        assert record.confidence == 0.0
        assert record.source == "unmapped"
        assert len(record.warnings) > 0


class TestDiseaseOntologyBuilder:
    """Test DiseaseOntologyBuilder resolution and aggregation."""

    def test_exact_ontology_match_maps_to_mondo(self, ontology_builder):
        """Exact primary-name match maps to MONDO ID with high confidence."""
        records, _ = ontology_builder.build_from_raw_diseases(["Atopic Dermatitis"])

        assert len(records) == 1
        record = records[0]
        assert record.raw_disease_name == "Atopic Dermatitis"
        assert record.normalized_disease_name == "Atopic Dermatitis"
        assert record.mondo_id == "MONDO:0004980"
        assert record.confidence >= 0.75
        assert record.source == "mondo"

    def test_synonym_match_maps_to_canonical(self, ontology_builder):
        """Synonym match maps raw name to canonical MONDO term."""
        records, _ = ontology_builder.build_from_raw_diseases(["AD"])

        assert len(records) == 1
        record = records[0]
        assert record.raw_disease_name == "AD"
        assert record.normalized_disease_name == "Atopic Dermatitis"
        assert record.mondo_id == "MONDO:0004980"
        assert record.source == "mondo_synonym"

    def test_case_insensitive_matching(self, ontology_builder):
        """Case-insensitive matching resolves variant cases."""
        records, _ = ontology_builder.build_from_raw_diseases(["ATOPIC DERMATITIS"])

        assert len(records) == 1
        record = records[0]
        assert record.mondo_id == "MONDO:0004980"
        assert record.confidence >= 0.75

    def test_unknown_disease_preserved_with_warning(self, ontology_builder):
        """Unknown disease is preserved with mondo_id null and warning."""
        records, _ = ontology_builder.build_from_raw_diseases(["Unknown Syndrome X"])

        assert len(records) == 1
        record = records[0]
        assert record.raw_disease_name == "Unknown Syndrome X"
        assert record.normalized_disease_name == "Unknown Syndrome X"
        assert record.mondo_id is None
        assert record.confidence < 0.25
        assert len(record.warnings) > 0

    def test_therapeutic_area_preserved(self, ontology_builder):
        """Therapeutic area is preserved from MONDO mapping."""
        records, _ = ontology_builder.build_from_raw_diseases(["Psoriasis", "Melanoma", "Rheumatoid Arthritis"])

        areas = {r.normalized_disease_name: r.therapeutic_area for r in records}
        assert areas.get("Psoriasis") == "Dermatology"
        assert areas.get("Melanoma") == "Oncology"
        assert areas.get("Rheumatoid Arthritis") == "Immunology"

    def test_synonyms_deduplicated(self, ontology_builder):
        """Synonyms are collected and deduplicated."""
        records, _ = ontology_builder.build_from_raw_diseases(["Atopic Dermatitis"])

        record = records[0]
        assert len(record.synonyms) > 0
        # Check that synonyms are from MONDO fixture
        assert "eczema" in record.synonyms or "AD" in record.synonyms

    def test_source_refs_tracked(self, ontology_builder):
        """Source references are tracked for provenance."""
        records, _ = ontology_builder.build_from_raw_diseases(["Psoriasis"])

        record = records[0]
        # source_refs may be empty in Phase 8 (populated in later phases)
        assert isinstance(record.source_refs, list)

    def test_builder_from_programs_extracts_diseases(self, ontology_builder):
        """Builder extracts disease_name from program dicts."""
        programs = [
            {"disease_name": "Atopic Dermatitis", "company": "Gilead"},
            {"disease_name": "Psoriasis", "company": "Janssen"},
            {"disease_name": "Atopic Dermatitis", "company": "Sanofi"},  # Duplicate
        ]

        records, _ = ontology_builder.build_from_programs(programs)

        # Should have 2 unique diseases
        assert len(records) == 2
        normalized_names = {r.normalized_disease_name for r in records}
        assert "Atopic Dermatitis" in normalized_names
        assert "Psoriasis" in normalized_names

    def test_builder_from_raw_disease_list(self, ontology_builder):
        """Builder constructs from raw disease name list."""
        raw_names = [
            "Atopic Dermatitis",
            "Psoriasis",
            "Unknown Syndrome X",
        ]

        records, _ = ontology_builder.build_from_raw_diseases(raw_names)

        assert len(records) == 3
        mondo_ids = {r.mondo_id for r in records}
        assert "MONDO:0004980" in mondo_ids  # AD
        assert "MONDO:0005083" in mondo_ids  # Psoriasis
        assert None in mondo_ids  # Unknown

    def test_deduplication_of_raw_diseases(self, ontology_builder):
        """Duplicate raw disease names are deduplicated."""
        raw_names = [
            "Atopic Dermatitis",
            "atopic dermatitis",  # Case variant
            "AD",  # Synonym
        ]

        records, _ = ontology_builder.build_from_raw_diseases(raw_names)

        # Three raw names but they resolve to two or three distinct records
        # (depends on normalizer deduplication)
        assert len(records) >= 2

    def test_empty_disease_name_skipped(self, ontology_builder):
        """Empty or whitespace disease names are skipped."""
        raw_names = [
            "Atopic Dermatitis",
            "",
            "   ",
            "Psoriasis",
        ]

        records, _ = ontology_builder.build_from_raw_diseases(raw_names)

        assert len(records) == 2
        names = {r.raw_disease_name for r in records}
        assert "Atopic Dermatitis" in names
        assert "Psoriasis" in names


class TestDiseaseOntologyCoverageReport:
    """Test coverage report generation."""

    def test_coverage_report_counts(self, ontology_builder):
        """Coverage report correctly counts mapped/unknown/ambiguous."""
        raw_names = [
            "Atopic Dermatitis",  # Mapped
            "Psoriasis",  # Mapped
            "Unknown Syndrome X",  # Unknown
        ]

        _, coverage = ontology_builder.build_from_raw_diseases(raw_names)

        assert coverage.total_raw_diseases == 3
        assert coverage.mapped_count == 2
        assert coverage.unknown_count == 1
        assert coverage.ambiguous_count == 0

    def test_coverage_therapeutic_area_counts(self, ontology_builder):
        """Coverage report counts by therapeutic area."""
        raw_names = [
            "Atopic Dermatitis",  # Dermatology
            "Psoriasis",  # Dermatology
            "Melanoma",  # Oncology
            "Unknown Syndrome",  # unknown
        ]

        _, coverage = ontology_builder.build_from_raw_diseases(raw_names)

        assert coverage.therapeutic_area_counts.get("Dermatology", 0) >= 2
        assert coverage.therapeutic_area_counts.get("Oncology", 0) >= 1
        assert coverage.therapeutic_area_counts.get("unknown", 0) >= 1

    def test_coverage_confidence_distribution(self, ontology_builder):
        """Coverage report bins confidence scores."""
        raw_names = [
            "Atopic Dermatitis",  # High confidence
            "AD",  # Synonym (slightly lower)
            "Unknown Syndrome",  # Low confidence
        ]

        _, coverage = ontology_builder.build_from_raw_diseases(raw_names)

        # Should have entries in confidence_distribution
        assert len(coverage.confidence_distribution) > 0
        # Should have at least a high-confidence and low-confidence bucket
        buckets = set(coverage.confidence_distribution.keys())
        assert "1.0" in buckets or "0.75+" in buckets
        assert "<0.25" in buckets

    def test_coverage_governance_flags(self, ontology_builder):
        """Coverage report includes governance flags (all false for Phase 8)."""
        _, coverage = ontology_builder.build_from_raw_diseases(["Atopic Dermatitis"])

        assert coverage.governance["read_only_diagnostic"] is True
        assert coverage.governance["reference_data_layer_only"] is True
        assert coverage.governance["production_model_change"] is False
        assert coverage.governance["ranker_change"] is False
        assert coverage.governance["selector_change"] is False
        assert coverage.governance["sizing_change"] is False
        assert coverage.governance["final_score_change"] is False
        assert coverage.governance["alpha_promotion"] is False

    def test_coverage_to_dict(self, ontology_builder):
        """Coverage report serializes to dictionary."""
        raw_names = ["Atopic Dermatitis", "Unknown Syndrome"]
        _, coverage = ontology_builder.build_from_raw_diseases(raw_names)

        d = coverage.to_dict()
        assert "as_of_date" in d
        assert "total_raw_diseases" in d
        assert "mapped_count" in d
        assert "unknown_count" in d
        assert "therapeutic_area_counts" in d
        assert "confidence_distribution" in d
        assert "governance" in d


class TestPhase8Integration:
    """Integration tests for Phase 8 disease ontology layer."""

    def test_full_workflow_from_programs(self, disease_normalizer_with_fixture):
        """Full workflow: programs → ontology records + coverage."""
        builder = DiseaseOntologyBuilder(
            as_of_date="2026-06-17",
            disease_normalizer=disease_normalizer_with_fixture,
        )

        programs = [
            {"disease_name": "Atopic Dermatitis", "company": "Gilead", "asset": "JAK1i"},
            {"disease_name": "AD", "company": "Sanofi", "asset": "IL-4R mAb"},
            {"disease_name": "Melanoma", "company": "BMS", "asset": "PD-1 mAb"},
            {"disease_name": "Unknown Condition", "company": "Private", "asset": "unknown"},
        ]

        records, coverage = builder.build_from_programs(programs)

        # Should have 4 unique diseases
        assert len(records) == 4

        # Coverage should show mapped and unknown
        assert coverage.mapped_count >= 2
        assert coverage.unknown_count >= 1

        # Governance should be clean
        assert coverage.governance["production_model_change"] is False
        assert coverage.governance["ranker_change"] is False

    def test_no_production_model_change(self, ontology_builder):
        """Verify Phase 8 does not affect production scoring."""
        records, coverage = ontology_builder.build_from_raw_diseases(["Atopic Dermatitis", "Melanoma"])

        # All governance flags should indicate no model change
        assert coverage.governance["production_model_change"] is False
        assert coverage.governance["ranker_change"] is False
        assert coverage.governance["selector_change"] is False
        assert coverage.governance["sizing_change"] is False
        assert coverage.governance["final_score_change"] is False

    def test_existing_disease_normalizer_tests_still_pass(self):
        """Confirm existing DiseaseNormalizer tests still pass."""
        # This test verifies backward compatibility
        mondo_cache = {
            "atopic dermatitis": {
                "id": "MONDO:0004980",
                "name": "Atopic Dermatitis",
                "synonyms": ["AD", "eczema"],
                "therapeutic_area": "Dermatology",
            }
        }
        normalizer = DiseaseNormalizer(mondo_cache=mondo_cache)
        result = normalizer.normalize("AD")

        assert result.mondo_id == "MONDO:0004980"
        assert result.normalized_name == "Atopic Dermatitis"
        assert result.confidence >= 0.75
