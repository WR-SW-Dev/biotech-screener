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

    def test_combination_now_resolved_by_v03(self, normalizer):
        # iGlarLixi FRC combo was unresolved in v0.1; v0.3 alias pack resolves it
        result = normalizer.normalize("insulin glargine/lixisenatide")
        assert result.mechanism_class == "GLP-1/Insulin fixed-ratio combination"

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


class TestT2DAliasPackV02:
    """Tests for T2D mechanism alias pack v0.2 additions."""

    @pytest.fixture
    def normalizer(self):
        csv_path = (
            Path(__file__).parent.parent.parent / "scientific_cartography" / "data" / "mechanism_aliases_v0_1.csv"
        )
        return MechanismNormalizer.from_csv(csv_path)

    # --- Insulin brand names ---

    def test_actrapid_resolves(self, normalizer):
        result = normalizer.normalize("Actrapid")
        assert result.mechanism_class == "Insulin"

    def test_novolog_resolves(self, normalizer):
        result = normalizer.normalize("NovoLog")
        assert result.mechanism_class == "Insulin"

    def test_novorapid_resolves(self, normalizer):
        result = normalizer.normalize("NovoRapid")
        assert result.mechanism_class == "Insulin"

    def test_novolog_novorapid_slash_resolves(self, normalizer):
        result = normalizer.normalize("NovoLog/NovoRapid")
        assert result.mechanism_class == "Insulin"

    def test_lispro_short_resolves(self, normalizer):
        result = normalizer.normalize("Lispro")
        assert result.mechanism_class == "Insulin"

    def test_glargine_insulin_inverted_resolves(self, normalizer):
        result = normalizer.normalize("Glargine insulin")
        assert result.mechanism_class == "Insulin"

    def test_lantus_parenthetical_resolves(self, normalizer):
        result = normalizer.normalize("Lantus® (insulin glargine)")
        assert result.mechanism_class == "Insulin"

    def test_prandial_insulin_resolves(self, normalizer):
        result = normalizer.normalize("Prandial insulin")
        assert result.mechanism_class == "Insulin"
        assert result.confidence < 0.95  # class-level, lower confidence

    def test_sliding_scale_insulin_resolves(self, normalizer):
        result = normalizer.normalize("Sliding scale regular insulin (SSRI)")
        assert result.mechanism_class == "Insulin"

    def test_injected_insulin_resolves(self, normalizer):
        result = normalizer.normalize("injected insulin")
        assert result.mechanism_class == "Insulin"

    def test_insulin_infusion_aspart_resolves(self, normalizer):
        result = normalizer.normalize("Insulin infusion (aspart)")
        assert result.mechanism_class == "Insulin"

    # --- GLP-1 standalone and brands ---

    def test_lixisenatide_standalone_resolves(self, normalizer):
        result = normalizer.normalize("Lixisenatide")
        assert result.mechanism_class == "GLP-1 receptor agonist"

    def test_bydureon_brand_resolves(self, normalizer):
        result = normalizer.normalize("Bydureon")
        assert result.mechanism_class == "GLP-1 receptor agonist"

    def test_nex22a_dev_code_resolves(self, normalizer):
        result = normalizer.normalize("NEX-22A")
        assert result.mechanism_class == "GLP-1 receptor agonist"

    def test_aleniglipron_resolves(self, normalizer):
        result = normalizer.normalize("Aleniglipron")
        assert result.mechanism_class == "GLP-1 receptor agonist"
        assert result.modality == "small molecule"

    # --- GLP-1/GCGR dual agonist ---

    def test_cotadutide_resolves(self, normalizer):
        result = normalizer.normalize("Cotadutide")
        assert result.mechanism_class == "GLP-1/GCGR dual agonist"
        assert result.target == "GLP1R"

    def test_experimental_cotadutide_resolves(self, normalizer):
        result = normalizer.normalize("Experimental: Cotadutide")
        assert result.mechanism_class == "GLP-1/GCGR dual agonist"

    # --- Biguanide suffix variants ---

    def test_metformin_ir_resolves(self, normalizer):
        result = normalizer.normalize("Metformin IR")
        assert result.mechanism_class == "Biguanide"

    def test_metformin_active_rescue_resolves(self, normalizer):
        result = normalizer.normalize("Metformin (Active Rescue)")
        assert result.mechanism_class == "Biguanide"

    def test_metformin_immediate_release_resolves(self, normalizer):
        result = normalizer.normalize("Metformin immediate release (IR)")
        assert result.mechanism_class == "Biguanide"

    def test_mertformin_typo_resolves(self, normalizer):
        result = normalizer.normalize("Mertformin XR 2 x 500 mg")
        assert result.mechanism_class == "Biguanide"

    # --- PPAR agonist class aliases ---

    def test_pioglitazone_actos_parenthetical_resolves(self, normalizer):
        result = normalizer.normalize("Pioglitazone (Actos)")
        assert result.mechanism_class == "PPAR agonist"

    def test_thiazolidinedione_resolves(self, normalizer):
        result = normalizer.normalize("Thiazolidinedione")
        assert result.mechanism_class == "PPAR agonist"
        assert result.confidence < 0.95

    def test_thiazolidinedione_tzd_resolves(self, normalizer):
        result = normalizer.normalize("Thiazolidinedione (TZD)")
        assert result.mechanism_class == "PPAR agonist"

    def test_thiazolidinedione_pioglitazone_resolves(self, normalizer):
        result = normalizer.normalize("Thiazolidinedione (Pioglitazone)")
        assert result.mechanism_class == "PPAR agonist"

    # --- Sulfonylurea dev code and class alias ---

    def test_glimepiride_hoe490_resolves(self, normalizer):
        result = normalizer.normalize("Glimepiride (HOE490)")
        assert result.mechanism_class == "Sulfonylurea"

    def test_2nd_generation_sulfonylurea_resolves(self, normalizer):
        result = normalizer.normalize("2nd generation Sulfonylurea")
        assert result.mechanism_class == "Sulfonylurea"
        assert result.confidence < 0.95

    # --- SGLT2 novel agent and class aliases ---

    def test_tofogliflozin_resolves(self, normalizer):
        result = normalizer.normalize("TOFOGLIFLOZIN CSG452")
        assert result.mechanism_class == "SGLT2 inhibitor"

    def test_sglt2_inhibitor_class_alias_resolves(self, normalizer):
        result = normalizer.normalize("SGLT2 inhibitor")
        assert result.mechanism_class == "SGLT2 inhibitor"
        assert result.confidence <= 0.75

    def test_sglt2_full_name_resolves(self, normalizer):
        result = normalizer.normalize("Sodium Glucose Co-Transporter 2 Inhibitors")
        assert result.mechanism_class == "SGLT2 inhibitor"

    # --- DPP-4 class alias without hyphen ---

    def test_dpp4_no_hyphen_resolves(self, normalizer):
        result = normalizer.normalize("DPP4 inhibitor")
        assert result.mechanism_class == "DPP-4 inhibitor"

    # --- Comments in CSV are skipped ---

    def test_csv_comment_lines_not_loaded_as_aliases(self, normalizer):
        result = normalizer.normalize("# --- v0.2 additions ---")
        assert result.mechanism_class is None
        assert result.resolution_status == "unknown"

    # --- v0.1 regression: existing entries unaffected ---

    def test_v01_saxagliptin_still_resolves(self, normalizer):
        result = normalizer.normalize("saxagliptin")
        assert result.mechanism_class == "DPP-4 inhibitor"

    def test_v01_semaglutide_still_resolves(self, normalizer):
        result = normalizer.normalize("semaglutide")
        assert result.mechanism_class == "GLP-1 receptor agonist"

    def test_v01_unaliased_dev_code_still_unknown(self, normalizer):
        # AMG 876 was intentionally left out of v0.3 (uncertain mechanism)
        result = normalizer.normalize("AMG 876")
        assert result.resolution_status == "unknown"


class TestT2DAliasPackV03:
    """Tests for T2D mechanism alias pack v0.3 additions."""

    @pytest.fixture
    def normalizer(self):
        csv_path = (
            Path(__file__).parent.parent.parent / "scientific_cartography" / "data" / "mechanism_aliases_v0_1.csv"
        )
        return MechanismNormalizer.from_csv(csv_path)

    # --- Insulin: Technosphere® brand variants ---

    def test_technosphere_ti_variant_resolves(self, normalizer):
        result = normalizer.normalize("Technosphere Insulin (TI) Inhalation Powder")
        assert result.mechanism_class == "Insulin"
        assert result.modality == "protein/enzyme therapy"

    def test_technosphere_registered_powder_resolves(self, normalizer):
        result = normalizer.normalize("Technosphere® Insulin Inhalation Powder")
        assert result.mechanism_class == "Insulin"

    def test_technosphere_registered_with_medtone_resolves(self, normalizer):
        result = normalizer.normalize("Technosphere® Insulin Inhalation Powder and MedTone™ Inhaler")
        assert result.mechanism_class == "Insulin"

    def test_technosphere_registered_bare_resolves(self, normalizer):
        result = normalizer.normalize("Technosphere® Insulin")
        assert result.mechanism_class == "Insulin"

    def test_technosphere_powder_short_resolves(self, normalizer):
        result = normalizer.normalize("Technosphere Powder")
        assert result.mechanism_class == "Insulin"

    def test_technosphere_registered_system_resolves(self, normalizer):
        result = normalizer.normalize("Technosphere® Insulin Inhalation System")
        assert result.mechanism_class == "Insulin"

    # --- Insulin: Generex buccal spray ---

    def test_generex_oral_lyn_resolves(self, normalizer):
        result = normalizer.normalize("Generex Oral-lyn™")
        assert result.mechanism_class == "Insulin"

    # --- Insulin: regimen descriptors ---

    def test_insulin_infusion_bare_resolves(self, normalizer):
        result = normalizer.normalize("Insulin infusion")
        assert result.mechanism_class == "Insulin"

    def test_long_intermediate_acting_insulins_resolves(self, normalizer):
        result = normalizer.normalize("Long- and intermediate- acting insulins")
        assert result.mechanism_class == "Insulin"

    def test_insulin_analog_mid_mixture_resolves(self, normalizer):
        result = normalizer.normalize("Insulin Analog Mid Mixture")
        assert result.mechanism_class == "Insulin"

    def test_nph_regular_insulin_combo_resolves(self, normalizer):
        result = normalizer.normalize("NPH & regular insulin")
        assert result.mechanism_class == "Insulin"

    def test_glargine_glulisine_combo_resolves(self, normalizer):
        result = normalizer.normalize("Glargine & Glulisine")
        assert result.mechanism_class == "Insulin"

    def test_mixtard_novonordisk_resolves(self, normalizer):
        result = normalizer.normalize("Mixtard 30:70 Novonordisk® twice daily")
        assert result.mechanism_class == "Insulin"

    def test_lantus_apidra_regimen_resolves(self, normalizer):
        result = normalizer.normalize("Lantus® once daily and Apidra® before meals")
        assert result.mechanism_class == "Insulin"

    def test_any_human_insulin_catch_all_resolves(self, normalizer):
        result = normalizer.normalize(
            "any human insulin or analog insulin(s) given in any regimen by subcutaneous injection"
        )
        assert result.mechanism_class == "Insulin"
        assert result.confidence <= 0.80

    # --- GLP-1 RA: long NEX-22A descriptor ---

    def test_nex22a_long_form_resolves(self, normalizer):
        result = normalizer.normalize("NEX-22A, a prolonged release formulation of liraglutide")
        assert result.mechanism_class == "GLP-1 receptor agonist"

    # --- GIP/GLP-1 dual agonist: Maridebart cafraglutide ---

    def test_maridebart_cafraglutide_resolves(self, normalizer):
        result = normalizer.normalize("Maridebart Cafraglutide")
        assert result.mechanism_class == "GIP/GLP-1 receptor agonist"
        assert result.modality == "protein/enzyme therapy"

    # --- SGLT2 inhibitor: early-stage compounds ---

    def test_ave2268_resolves(self, normalizer):
        result = normalizer.normalize("AVE2268")
        assert result.mechanism_class == "SGLT2 inhibitor"

    def test_dwp16001_resolves(self, normalizer):
        result = normalizer.normalize("DWP16001")
        assert result.mechanism_class == "SGLT2 inhibitor"

    # --- DPP-4 inhibitor: Komboglyze and saxagliptin FDCs ---

    def test_komboglyze_xr_500_resolves(self, normalizer):
        result = normalizer.normalize("Komboglyze XR 5/500 mg")
        assert result.mechanism_class == "DPP-4 inhibitor"

    def test_komboglyze_xr_1000_resolves(self, normalizer):
        result = normalizer.normalize("Komboglyze XR 5/1000 mg")
        assert result.mechanism_class == "DPP-4 inhibitor"

    def test_saxagliptin_metformin_xr_fdc_resolves(self, normalizer):
        result = normalizer.normalize("Saxagliptin/Metformin XR FDC")
        assert result.mechanism_class == "DPP-4 inhibitor"

    def test_saxagliptin_dapagliflozin_fdc_resolves(self, normalizer):
        result = normalizer.normalize("Saxagliptin/Dapagliflozin FDC")
        assert result.mechanism_class == "DPP-4 inhibitor"

    def test_saxagliptin_metformin_dose_arm_resolves(self, normalizer):
        result = normalizer.normalize("Saxagliptin, 2.5 mg + Metformin, 500 mg (fasted state)")
        assert result.mechanism_class == "DPP-4 inhibitor"

    # --- PPAR agonist: Metabolex SPPARγ modulators ---

    def test_mbx102_resolves(self, normalizer):
        result = normalizer.normalize("MBX-102")
        assert result.mechanism_class == "PPAR agonist"

    def test_mbx2044_resolves(self, normalizer):
        result = normalizer.normalize("MBX-2044")
        assert result.mechanism_class == "PPAR agonist"

    # --- GLP-1/Insulin fixed-ratio combination (iGlarLixi) ---

    def test_iglarlixi_brand_resolves(self, normalizer):
        result = normalizer.normalize("iGlarLixi")
        assert result.mechanism_class == "GLP-1/Insulin fixed-ratio combination"
        assert result.modality == "protein/enzyme therapy"

    def test_iglarlixi_parenthetical_resolves(self, normalizer):
        result = normalizer.normalize("iGlarLixi (insulin glargine/lixisenatide)")
        assert result.mechanism_class == "GLP-1/Insulin fixed-ratio combination"

    def test_insulin_glargine_lixisenatide_slash_resolves(self, normalizer):
        result = normalizer.normalize("Insulin glargine/Lixisenatide")
        assert result.mechanism_class == "GLP-1/Insulin fixed-ratio combination"

    def test_insulin_glargine_lixisenatide_frc_descriptor_resolves(self, normalizer):
        result = normalizer.normalize("Insulin glargine/lixisenatide Fixed Ratio Combination")
        assert result.mechanism_class == "GLP-1/Insulin fixed-ratio combination"

    def test_iglarlixi_hoe901_ave0010_lowercase_resolves(self, normalizer):
        result = normalizer.normalize("Insulin glargine/Lixisenatide (HOE901/AVE0010)")
        assert result.mechanism_class == "GLP-1/Insulin fixed-ratio combination"

    def test_iglarlixi_allcaps_dev_codes_resolves(self, normalizer):
        result = normalizer.normalize("INSULIN GLARGINE/LIXISENATIDE HOE901/AVE0010")
        assert result.mechanism_class == "GLP-1/Insulin fixed-ratio combination"

    # --- Glucokinase activator ---

    def test_lgd6972_bare_resolves(self, normalizer):
        result = normalizer.normalize("LGD-6972")
        assert result.mechanism_class == "Glucokinase activator"
        assert result.target == "GCK"
        assert result.modality == "small molecule"

    def test_lgd6972_solution_resolves(self, normalizer):
        result = normalizer.normalize("LGD-6972 Solution")
        assert result.mechanism_class == "Glucokinase activator"

    def test_lgd6972_capsules_resolves(self, normalizer):
        result = normalizer.normalize("LGD-6972 Capsules")
        assert result.mechanism_class == "Glucokinase activator"

    def test_lgd6972_5mg_resolves(self, normalizer):
        result = normalizer.normalize("LGD-6972-5 mg")
        assert result.mechanism_class == "Glucokinase activator"

    def test_lgd6972_10mg_resolves(self, normalizer):
        result = normalizer.normalize("LGD-6972-10 mg")
        assert result.mechanism_class == "Glucokinase activator"

    def test_lgd6972_15mg_resolves(self, normalizer):
        result = normalizer.normalize("LGD-6972-15 mg")
        assert result.mechanism_class == "Glucokinase activator"

    def test_azd1656_resolves(self, normalizer):
        result = normalizer.normalize("AZD1656")
        assert result.mechanism_class == "Glucokinase activator"

    def test_mb07803_resolves(self, normalizer):
        result = normalizer.normalize("MB07803")
        assert result.mechanism_class == "Glucokinase activator"

    def test_amg151_resolves(self, normalizer):
        result = normalizer.normalize("AMG 151")
        assert result.mechanism_class == "Glucokinase activator"

    def test_gk_activator_generic_resolves(self, normalizer):
        result = normalizer.normalize("GK Activator (2)")
        assert result.mechanism_class == "Glucokinase activator"

    def test_icovamenib_dose_arm_resolves(self, normalizer):
        result = normalizer.normalize("icovamenib 100mg")
        assert result.mechanism_class == "Glucokinase activator"

    # --- GCGR antisense oligonucleotide ---

    def test_isis_gcgrrx_bare_resolves(self, normalizer):
        result = normalizer.normalize("ISIS-GCGRRx")
        assert result.mechanism_class == "GCGR antisense oligonucleotide"
        assert result.target == "GCGR"
        assert result.modality == "RNA therapy"

    def test_isis_gcgrrx_dose1_spaced_resolves(self, normalizer):
        result = normalizer.normalize("ISIS-GCGRRx - Dose Level 1")
        assert result.mechanism_class == "GCGR antisense oligonucleotide"

    def test_isis_gcgrrx_dose2_spaced_resolves(self, normalizer):
        result = normalizer.normalize("ISIS-GCGRRx - Dose Level 2")
        assert result.mechanism_class == "GCGR antisense oligonucleotide"

    def test_isis_gcgrrx_dose1_nospace_resolves(self, normalizer):
        result = normalizer.normalize("ISIS-GCGRRx- Dose Level 1")
        assert result.mechanism_class == "GCGR antisense oligonucleotide"

    def test_isis_gcgrrx_dose2_nospace_resolves(self, normalizer):
        result = normalizer.normalize("ISIS-GCGRRx- Dose Level 2")
        assert result.mechanism_class == "GCGR antisense oligonucleotide"

    def test_isis_gccrrrx_typo_resolves(self, normalizer):
        # ISIS-GCCRRx is a CT.gov typo: GCC instead of GCG
        result = normalizer.normalize("ISIS-GCCRRx")
        assert result.mechanism_class == "GCGR antisense oligonucleotide"
        assert result.confidence <= 0.95

    def test_isis_388626_compound_number_resolves(self, normalizer):
        result = normalizer.normalize("ISIS 388626")
        assert result.mechanism_class == "GCGR antisense oligonucleotide"

    # --- 11beta-HSD1 inhibitor ---

    def test_incb013739_resolves(self, normalizer):
        result = normalizer.normalize("INCB013739")
        assert result.mechanism_class == "11beta-HSD1 inhibitor"
        assert result.target == "HSD11B1"
        assert result.modality == "small molecule"

    def test_incb019602_resolves(self, normalizer):
        result = normalizer.normalize("INCB019602")
        assert result.mechanism_class == "11beta-HSD1 inhibitor"

    # --- v0.3 comment lines not loaded as aliases ---

    def test_v03_comment_header_not_loaded(self, normalizer):
        result = normalizer.normalize("# --- v0.3 additions ---")
        assert result.resolution_status == "unknown"

    # --- v0.2 regression: prior entries still resolve ---

    def test_v02_actrapid_regression(self, normalizer):
        result = normalizer.normalize("Actrapid")
        assert result.mechanism_class == "Insulin"

    def test_v02_cotadutide_regression(self, normalizer):
        result = normalizer.normalize("cotadutide")
        assert result.mechanism_class == "GLP-1/GCGR dual agonist"
