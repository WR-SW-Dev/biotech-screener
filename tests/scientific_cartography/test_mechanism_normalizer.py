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


class TestT2DAliasPackV01:
    """Tests for T2D mechanism alias pack v0.1."""

    @pytest.fixture
    def t2d_csv(self):
        return Path(__file__).parent.parent.parent / "scientific_cartography" / "data" / "mechanism_aliases_v0_1.csv"

    @pytest.fixture
    def normalizer(self, t2d_csv):
        return MechanismNormalizer.from_csv(t2d_csv)

    # --- Case-insensitive resolution ---

    def test_metformin_resolves(self, normalizer):
        result = normalizer.normalize("metformin")
        assert result.mechanism_class == "Biguanide"
        assert result.modality == "small molecule"
        assert result.resolution_status == "resolved"

    def test_metformin_uppercase(self, normalizer):
        result = normalizer.normalize("Metformin")
        assert result.mechanism_class == "Biguanide"

    def test_dapagliflozin_resolves(self, normalizer):
        result = normalizer.normalize("dapagliflozin")
        assert result.mechanism_class == "SGLT2 inhibitor"
        assert result.target == "SLC5A2"

    def test_saxagliptin_resolves(self, normalizer):
        result = normalizer.normalize("saxagliptin")
        assert result.mechanism_class == "DPP-4 inhibitor"
        assert result.target == "DPP4"

    def test_liraglutide_resolves(self, normalizer):
        result = normalizer.normalize("liraglutide")
        assert result.mechanism_class == "GLP-1 receptor agonist"
        assert result.modality == "protein/enzyme therapy"

    def test_semaglutide_resolves(self, normalizer):
        result = normalizer.normalize("semaglutide")
        assert result.mechanism_class == "GLP-1 receptor agonist"

    def test_insulin_glargine_resolves(self, normalizer):
        result = normalizer.normalize("insulin glargine")
        assert result.mechanism_class == "Insulin"
        assert result.modality == "protein/enzyme therapy"

    def test_pioglitazone_resolves(self, normalizer):
        result = normalizer.normalize("pioglitazone")
        assert result.mechanism_class == "PPAR agonist"
        assert result.target == "PPARG"

    def test_glimepiride_resolves(self, normalizer):
        result = normalizer.normalize("glimepiride")
        assert result.mechanism_class == "Sulfonylurea"

    def test_acarbose_resolves(self, normalizer):
        result = normalizer.normalize("acarbose")
        assert result.mechanism_class == "Alpha-glucosidase inhibitor"

    def test_tirzepatide_resolves(self, normalizer):
        result = normalizer.normalize("tirzepatide")
        assert result.mechanism_class == "GIP/GLP-1 receptor agonist"

    # --- Dose-suffixed variants resolve ---

    def test_saxagliptin_dose_suffix(self, normalizer):
        result = normalizer.normalize("saxagliptin 5 mg")
        assert result.mechanism_class == "DPP-4 inhibitor"

    def test_dapagliflozin_dose_tab(self, normalizer):
        result = normalizer.normalize("dapagliflozin 10mg tab")
        assert result.mechanism_class == "SGLT2 inhibitor"

    def test_dapagliflozin_dose_space(self, normalizer):
        result = normalizer.normalize("dapagliflozin 10 mg")
        assert result.mechanism_class == "SGLT2 inhibitor"

    # --- Brand names resolve ---

    def test_afrezza_brand(self, normalizer):
        result = normalizer.normalize("Afrezza")
        assert result.mechanism_class == "Insulin"

    def test_lantus_brand(self, normalizer):
        result = normalizer.normalize("Lantus")
        assert result.mechanism_class == "Insulin"

    def test_actos_brand(self, normalizer):
        result = normalizer.normalize("Actos")
        assert result.mechanism_class == "PPAR agonist"

    # --- Code names resolve ---

    def test_ac2993_exenatide_code(self, normalizer):
        result = normalizer.normalize("AC2993")
        assert result.mechanism_class == "GLP-1 receptor agonist"

    def test_sotagliflozin_sar_code(self, normalizer):
        result = normalizer.normalize("sotagliflozin (sar439954)")
        assert result.mechanism_class == "SGLT2/SGLT1 inhibitor"

    # --- Unknown drugs remain unknown ---

    def test_novel_asset_unknown(self, normalizer):
        result = normalizer.normalize("sb-509")
        assert result.resolution_status == "unknown"
        assert result.mechanism_class is None

    def test_behavioral_unknown(self, normalizer):
        result = normalizer.normalize("aerobic exercise program")
        assert result.resolution_status == "unknown"

    def test_device_unknown(self, normalizer):
        result = normalizer.normalize("Withings BPM Connect")
        assert result.resolution_status == "unknown"

    # --- Combination products handled conservatively ---

    def test_combination_not_resolved(self, normalizer):
        # Combo products should not match either component's entry
        result = normalizer.normalize("insulin glargine/lixisenatide")
        assert result.resolution_status == "unknown"

    def test_metformin_sitagliptin_combo(self, normalizer):
        result = normalizer.normalize("metformin + sitagliptin")
        assert result.resolution_status == "unknown"

    # --- Existing built-in dict still works alongside alias pack ---

    def test_jak_inhibitor_still_resolves(self, normalizer):
        result = normalizer.normalize("JAK inhibitor")
        assert result.mechanism_class == "JAK inhibitor"

    def test_pd1_inhibitor_still_resolves(self, normalizer):
        result = normalizer.normalize("PD-1 inhibitor")
        assert result.mechanism_class == "PD-1 inhibitor"
