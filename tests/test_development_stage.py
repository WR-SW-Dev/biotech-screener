#!/usr/bin/env python3
"""Tests for the display-only development_stage column wiring.

Covers:
  - _normalize_phase_to_development_stage normalization for all known variants
  - _derive_development_stage precedence (archetype > tier_commercial > M4 > prog)
  - lead_program_phase_raw passthrough
  - Invariance: deriving development_stage on a row dict does NOT mutate any
    scoring / selector / ranker / decision-engine field.
"""

import copy

from run_screen import DEVELOPMENT_STAGE_VALUES, _derive_development_stage, _normalize_phase_to_development_stage
from run_screen_columns import PHASE2_PORTFOLIO_COLUMNS, SNAPSHOT_COLUMNS


class TestPhaseNormalization:
    def test_preclinical(self):
        assert _normalize_phase_to_development_stage("preclinical") == "preclinical"

    def test_phase_1_with_space(self):
        assert _normalize_phase_to_development_stage("phase 1") == "phase_1"

    def test_phase1_no_space(self):
        assert _normalize_phase_to_development_stage("phase1") == "phase_1"

    def test_phase_1_2(self):
        assert _normalize_phase_to_development_stage("phase 1/2") == "phase_1_2"

    def test_phase1_phase2(self):
        assert _normalize_phase_to_development_stage("phase1/phase2") == "phase_1_2"

    def test_phase_2(self):
        assert _normalize_phase_to_development_stage("phase 2") == "phase_2"

    def test_phase_2_3(self):
        assert _normalize_phase_to_development_stage("phase 2/3") == "phase_2_3"

    def test_phase2_phase3(self):
        assert _normalize_phase_to_development_stage("phase2/phase3") == "phase_2_3"

    def test_phase_3(self):
        assert _normalize_phase_to_development_stage("phase 3") == "phase_3"

    def test_approved(self):
        assert _normalize_phase_to_development_stage("approved") == "approved"

    def test_nda_bla_slash(self):
        assert _normalize_phase_to_development_stage("nda/bla") == "nda_bla"

    def test_nda_alone(self):
        assert _normalize_phase_to_development_stage("nda") == "nda_bla"

    def test_bla_alone(self):
        assert _normalize_phase_to_development_stage("bla") == "nda_bla"

    def test_uppercase_input(self):
        assert _normalize_phase_to_development_stage("PHASE 3") == "phase_3"

    def test_with_whitespace(self):
        assert _normalize_phase_to_development_stage("  phase 2  ") == "phase_2"

    def test_empty_string_is_unknown(self):
        assert _normalize_phase_to_development_stage("") == "unknown"

    def test_none_is_unknown(self):
        assert _normalize_phase_to_development_stage(None) == "unknown"

    def test_unrecognized_is_unknown(self):
        assert _normalize_phase_to_development_stage("phase_99") == "unknown"

    def test_numeric_phase_codes(self):
        # rankings.csv stores lead_program_phase as float strings.
        assert _normalize_phase_to_development_stage("0.0") == "preclinical"
        assert _normalize_phase_to_development_stage("1.0") == "phase_1"
        assert _normalize_phase_to_development_stage("2.0") == "phase_2"
        assert _normalize_phase_to_development_stage("3.0") == "phase_3"
        assert _normalize_phase_to_development_stage("4.0") == "approved"

    def test_numeric_phase_codes_int_string(self):
        assert _normalize_phase_to_development_stage("1") == "phase_1"
        assert _normalize_phase_to_development_stage("3") == "phase_3"

    def test_intermediate_numeric_codes(self):
        assert _normalize_phase_to_development_stage("1.5") == "phase_1_2"
        assert _normalize_phase_to_development_stage("2.5") == "phase_2_3"

    def test_all_outputs_in_enum(self):
        for v in (
            "preclinical",
            "phase 1",
            "phase 1/2",
            "phase 2",
            "phase 2/3",
            "phase 3",
            "approved",
            "nda/bla",
            "",
            None,
            "garbage",
        ):
            assert _normalize_phase_to_development_stage(v) in DEVELOPMENT_STAGE_VALUES


class TestDevelopmentStageDerivation:
    """Precedence: archetype commercial_* > tier_commercial > M4 > lead_program_phase."""

    def test_commercial_archetype_biotech(self):
        row = {"archetype": "commercial_biotech", "tier_commercial": ""}
        stage, source, raw = _derive_development_stage(row, "")
        assert stage == "commercial"
        assert source == "archetype"

    def test_commercial_archetype_pharma(self):
        row = {"archetype": "commercial_pharma", "tier_commercial": ""}
        stage, source, _ = _derive_development_stage(row, "phase 3")
        # Commercial archetype wins even when M4 has a clinical phase set.
        assert stage == "commercial"
        assert source == "archetype"

    def test_tier_commercial_wins_over_module_4(self):
        row = {"archetype": "drug_developer", "tier_commercial": "B"}
        stage, source, _ = _derive_development_stage(row, "phase 3")
        assert stage == "commercial"
        assert source == "tier_commercial"

    def test_module_4_lead_phase_used_when_no_commercial_signal(self):
        row = {"archetype": "drug_developer", "tier_commercial": ""}
        stage, source, raw = _derive_development_stage(row, "phase 2")
        assert stage == "phase_2"
        assert source == "module_4_lead_phase"
        assert raw == "phase 2"

    def test_lead_program_phase_fallback(self):
        row = {
            "archetype": "drug_developer",
            "tier_commercial": "",
            "lead_program_phase": "phase 3",
        }
        stage, source, raw = _derive_development_stage(row, "")
        assert stage == "phase_3"
        assert source == "lead_program_phase"
        assert raw == "phase 3"

    def test_unknown_when_all_sources_blank(self):
        row = {"archetype": "drug_developer", "tier_commercial": ""}
        stage, source, raw = _derive_development_stage(row, "")
        assert stage == "unknown"
        assert source == "unknown"
        assert raw == ""

    def test_platform_archetype_uses_phase_data(self):
        # Platforms do NOT match commercial_* prefix; they should fall through
        # to phase data.
        row = {"archetype": "platform_diagnostics", "tier_commercial": ""}
        stage, source, _ = _derive_development_stage(row, "phase 1")
        assert stage == "phase_1"
        assert source == "module_4_lead_phase"

    def test_tier_commercial_empty_string_does_not_trigger(self):
        row = {"archetype": "drug_developer", "tier_commercial": ""}
        stage, source, _ = _derive_development_stage(row, "phase 2/3")
        assert stage == "phase_2_3"
        assert source == "module_4_lead_phase"

    def test_lead_program_phase_raw_carries_module_4_when_commercial(self):
        # When commercial wins, raw_phase should still carry the underlying
        # phase if M4 had one (operator context).
        row = {"archetype": "commercial_biotech", "tier_commercial": "A"}
        _, _, raw = _derive_development_stage(row, "approved")
        assert raw == "approved"

    def test_unicode_phase_strings_normalized(self):
        row = {"archetype": "drug_developer", "tier_commercial": ""}
        stage, _, _ = _derive_development_stage(row, "Phase 2")
        assert stage == "phase_2"


class TestSchemaIntegrity:
    """Confirm the new columns are wired into the output schema."""

    def test_development_stage_in_snapshot_columns(self):
        assert "development_stage" in SNAPSHOT_COLUMNS

    def test_development_stage_source_in_snapshot_columns(self):
        assert "development_stage_source" in SNAPSHOT_COLUMNS

    def test_lead_program_phase_raw_in_snapshot_columns(self):
        assert "lead_program_phase_raw" in SNAPSHOT_COLUMNS

    def test_stage_bucket_still_present(self):
        # The display-only column is additive — stage_bucket must remain.
        assert "stage_bucket" in SNAPSHOT_COLUMNS

    def test_development_stage_in_phase2_portfolio_columns(self):
        assert "development_stage" in PHASE2_PORTFOLIO_COLUMNS
        assert "development_stage_source" in PHASE2_PORTFOLIO_COLUMNS

    def test_no_duplicate_columns(self):
        assert len(SNAPSHOT_COLUMNS) == len(set(SNAPSHOT_COLUMNS))
        assert len(PHASE2_PORTFOLIO_COLUMNS) == len(set(PHASE2_PORTFOLIO_COLUMNS))


class TestInvariance:
    """The derivation must be a pure read on the row dict — no mutation."""

    def test_derivation_does_not_mutate_input_row(self):
        row = {
            "ticker": "ARVN",
            "archetype": "drug_developer",
            "tier_commercial": "",
            "lead_program_phase": "phase 2",
            # scoring fields the derivation must NEVER touch:
            "composite_score": 12.34,
            "final_score": 0.987,
            "actionable_rank": 7,
            "stage_bucket": "late",
            "clinical_score": 31.235,
            "clinical_alpha_z": 0.5179,
        }
        before = copy.deepcopy(row)
        _derive_development_stage(row, "phase 3")
        assert row == before, "_derive_development_stage must be pure-read; row was mutated"

    def test_derivation_only_reads_named_fields(self):
        # If the only fields present are those documented in the precedence
        # rules, derivation must still work without KeyError.
        row = {"archetype": "drug_developer"}
        stage, source, raw = _derive_development_stage(row, "phase 1")
        assert stage == "phase_1"
        assert source == "module_4_lead_phase"
        assert raw == "phase 1"
