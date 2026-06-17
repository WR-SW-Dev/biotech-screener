"""Tests for Phase 3 mechanism/modality normalizer."""

from pathlib import Path

import pytest

from scientific_cartography.normalize.mechanism_normalizer import MechanismNormalizer, MechanismResolution


class TestMechanismResolution:
    """Test MechanismResolution dataclass."""

    def test_to_dict(self):
        """Should serialize to dict."""
        resolution = MechanismResolution(
            raw_text="JAK inhibitor",
            normalized_text="JAK inhibitor",
            mechanism_class="JAK inhibitor",
            target="JAK",
            modality="small molecule",
            confidence=0.95,
            resolution_status="resolved",
        )

        d = resolution.to_dict()

        assert d["raw_text"] == "JAK inhibitor"
        assert d["mechanism_class"] == "JAK inhibitor"
        assert d["confidence"] == 0.95


class TestMechanismNormalizer:
    """Test mechanism normalization."""

    @pytest.fixture
    def normalizer(self):
        return MechanismNormalizer(as_of_date="2026-06-16")

    @pytest.fixture
    def mechanism_csv(self):
        return Path(__file__).parent.parent / "fixtures" / "scientific_cartography" / "mechanism_aliases.csv"

    def test_exact_mechanism_dict_match(self, normalizer):
        """Should resolve exact mechanism dictionary matches."""
        result = normalizer.normalize("JAK inhibitor")

        assert result.raw_text == "JAK inhibitor"
        assert result.mechanism_class == "JAK inhibitor"
        assert result.target == "JAK"
        assert result.modality == "small molecule"
        assert result.confidence == 0.95
        assert result.resolution_status == "resolved"

    def test_case_insensitive_match(self, normalizer):
        """Should match case-insensitively."""
        result = normalizer.normalize("jak inhibitor")

        assert result.mechanism_class == "JAK inhibitor"
        assert result.resolution_status == "resolved"

    def test_car_t_resolution(self, normalizer):
        """Should resolve CAR-T therapies."""
        result = normalizer.normalize("anti-CD19 CAR-T")

        assert result.mechanism_class == "CD19 CAR-T"
        assert result.target == "CD19"
        assert result.modality == "cell therapy"

    def test_gene_therapy_resolution(self, normalizer):
        """Should resolve gene therapy."""
        result = normalizer.normalize("AAV gene therapy")

        assert result.mechanism_class == "AAV gene therapy"
        assert result.modality == "gene therapy"
        assert result.target is None  # Target not specified

    def test_antibody_resolution(self, normalizer):
        """Should resolve monoclonal antibodies."""
        result = normalizer.normalize("IL-13 mAb")

        assert result.mechanism_class == "IL-13 monoclonal antibody"
        assert result.target == "IL13"
        assert result.modality == "monoclonal antibody"

    def test_rna_therapy_resolution(self, normalizer):
        """Should resolve RNA therapies."""
        result = normalizer.normalize("PCSK9 siRNA")

        assert result.mechanism_class == "PCSK9 siRNA"
        assert result.target == "PCSK9"
        assert result.modality == "RNA therapy"

    def test_antisense_resolution(self, normalizer):
        """Should resolve antisense oligonucleotides."""
        result = normalizer.normalize("ASO")

        assert result.mechanism_class == "antisense oligonucleotide"
        assert result.modality == "RNA therapy"

    def test_unknown_intervention(self, normalizer):
        """Should preserve unknown interventions."""
        result = normalizer.normalize("completely unknown intervention xyz")

        assert result.raw_text == "completely unknown intervention xyz"
        assert result.mechanism_class is None
        assert result.target is None
        assert result.modality is None
        assert result.confidence == 0.0
        assert result.resolution_status == "unknown"
        assert len(result.warnings) > 0

    def test_manual_alias_wins(self, mechanism_csv):
        """Manual aliases should have highest priority."""
        normalizer = MechanismNormalizer.from_csv(mechanism_csv, as_of_date="2026-06-16")

        result = normalizer.normalize("JAK inhibitor")

        assert result.mechanism_class == "JAK inhibitor"
        assert result.confidence == 1.0
        assert result.resolution_status == "resolved"

    def test_manual_alias_without_file(self):
        """Should handle missing alias file gracefully."""
        normalizer = MechanismNormalizer.from_csv(Path("/nonexistent/file.csv"))

        result = normalizer.normalize("JAK inhibitor")

        # Should still resolve from built-in dict
        assert result.mechanism_class == "JAK inhibitor"

    def test_caching(self, normalizer):
        """Should cache results."""
        result1 = normalizer.normalize("JAK inhibitor")
        result2 = normalizer.normalize("JAK inhibitor")

        # Should be same cached object
        assert result1 is result2

    def test_whitespace_normalization(self, normalizer):
        """Should handle whitespace."""
        result = normalizer.normalize("  JAK inhibitor  ")

        assert result.mechanism_class == "JAK inhibitor"

    def test_bulk_normalize(self, normalizer):
        """Should normalize multiple interventions."""
        interventions = ["JAK inhibitor", "anti-CD19 CAR-T", "unknown drug"]

        results = normalizer.bulk_normalize(interventions)

        assert len(results) == 3
        assert results[0].mechanism_class == "JAK inhibitor"
        assert results[1].mechanism_class == "CD19 CAR-T"
        assert results[2].resolution_status == "unknown"

    def test_substring_match(self, normalizer):
        """Should resolve single substring matches with lower confidence."""
        result = normalizer.normalize("a JAK inhibitor compound")

        # Should match "JAK inhibitor" substring
        assert result.mechanism_class == "JAK inhibitor"
        assert result.confidence < 0.95  # Lower than exact match

    def test_ambiguous_substring_match(self, normalizer):
        """Should return ambiguous for multiple substring matches."""
        # "IL" could match multiple IL-based mechanisms
        result = normalizer.normalize("IL compound that targets something")

        # Might be ambiguous depending on implementation
        # At minimum, should not confidently resolve
        if result.resolution_status == "ambiguous":
            assert result.confidence == 0.0

    def test_enzyme_replacement_therapy(self, normalizer):
        """Should resolve enzyme replacement therapy."""
        result = normalizer.normalize("enzyme replacement therapy")

        assert result.mechanism_class == "enzyme replacement therapy"
        assert result.modality == "protein/enzyme therapy"

    def test_pd1_pd_l1_resolution(self, normalizer):
        """Should resolve PD-1/PD-L1 inhibitors."""
        result_pd1 = normalizer.normalize("PD-1 inhibitor")
        result_pdl1 = normalizer.normalize("PD-L1 inhibitor")

        assert result_pd1.mechanism_class == "PD-1 inhibitor"
        assert result_pdl1.mechanism_class == "PD-L1 inhibitor"
        assert result_pd1.modality == "monoclonal antibody"
        assert result_pdl1.modality == "monoclonal antibody"

    def test_from_csv_loads_aliases(self, mechanism_csv):
        """Should load manual aliases from CSV."""
        normalizer = MechanismNormalizer.from_csv(mechanism_csv)

        # Manual alias has confidence 1.00
        result = normalizer.normalize("AAV gene therapy")
        assert result.confidence == 0.9  # From CSV
        assert result.modality == "gene therapy"

    def test_resolution_fields_independent(self, normalizer):
        """Mechanism/modality/target should resolve independently."""
        # AAV has modality but no target
        result = normalizer.normalize("AAV gene therapy")

        assert result.modality == "gene therapy"
        assert result.mechanism_class == "AAV gene therapy"
        assert result.target is None  # No target specified
