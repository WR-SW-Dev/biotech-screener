"""Tests for tools/audit_development_stage_external.py — Spec 068 §12 cases.

Read-only audit; tests exercise the pure-function helpers (alias matching,
phase aggregation, multi-program detection, consensus derivation, status
finalization) plus the spec-mandated guards (Phase 4 ≠ commercial, LOW
alias cannot escalate, multi-program emits ambiguous).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = REPO_ROOT / "tools"
sys.path.insert(0, str(TOOLS_DIR))

import audit_development_stage_external as audit_mod  # noqa: E402

# ---------------------------------------------------------------------------
# Alias matching
# ---------------------------------------------------------------------------


class TestAliasConfidence:
    def test_exact_match_high(self):
        assert audit_mod.alias_confidence("Fate Therapeutics, Inc.", "Fate Therapeutics") == "HIGH"

    def test_substring_parent_subsidiary_high(self):
        # GPCR-style: parent name appears in subsidiary sponsor description
        assert (
            audit_mod.alias_confidence(
                "Structure Therapeutics Inc.",
                "Gasherbrum Bio, Inc., a wholly owned subsidiary of Structure Therapeutics Inc.",
            )
            == "HIGH"
        )

    def test_partial_token_overlap_low(self):
        # "Acme Genomics" vs "Acme Diagnostics": after stripping Inc/Corp the
        # normalized forms are "acme genomics" and "acme diagnostics" — single
        # token match out of two is below the 0.7 MED threshold, returns LOW.
        assert (
            audit_mod.alias_confidence(
                "Acme Genomics Inc.",
                "Acme Diagnostics Corp.",
            )
            == "LOW"
        )

    def test_unrelated_low(self):
        assert (
            audit_mod.alias_confidence(
                "Aardvark Therapeutics, Inc.",
                "Pfizer Inc.",
            )
            == "LOW"
        )

    def test_empty_returns_none(self):
        assert audit_mod.alias_confidence("", "Fate Therapeutics") == "NONE"
        assert audit_mod.alias_confidence("Fate Therapeutics", "") == "NONE"

    def test_aggregate_picks_best(self):
        sponsors = ["Pfizer Inc.", "Fate Therapeutics", "Some Lab"]
        assert audit_mod.aggregate_alias_confidence("Fate Therapeutics, Inc.", sponsors) == "HIGH"


# ---------------------------------------------------------------------------
# CT.gov phase aggregation
# ---------------------------------------------------------------------------


class TestCTGovPhaseAggregation:
    def test_max_active_phase_picks_highest(self):
        trials = [
            {"status": "RECRUITING", "phase": "PHASE2"},
            {"status": "ACTIVE_NOT_RECRUITING", "phase": "PHASE3"},
            {"status": "COMPLETED", "phase": "PHASE3"},  # not active, ignored
        ]
        stage, count = audit_mod.ctgov_max_active_phase(trials)
        assert stage == "phase_3"
        assert count == 2

    def test_phase_4_maps_to_approved_not_commercial(self):
        # Spec 068: Phase 4 must NOT collapse to commercial
        trials = [{"status": "RECRUITING", "phase": "PHASE4"}]
        stage, _ = audit_mod.ctgov_max_active_phase(trials)
        assert stage == "approved"
        assert stage != "commercial"

    def test_no_active_returns_unknown(self):
        trials = [
            {"status": "COMPLETED", "phase": "PHASE3"},
            {"status": "TERMINATED", "phase": "PHASE2"},
        ]
        stage, count = audit_mod.ctgov_max_active_phase(trials)
        assert stage == "unknown"
        assert count == 0

    def test_multi_program_detected(self):
        trials = [
            {"status": "RECRUITING", "phase": "PHASE3"},
            {"status": "ACTIVE_NOT_RECRUITING", "phase": "PHASE1"},
        ]
        assert audit_mod.detect_multi_program(trials) is True

    def test_single_phase_not_multi_program(self):
        trials = [
            {"status": "RECRUITING", "phase": "PHASE3"},
            {"status": "RECRUITING", "phase": "PHASE3"},
        ]
        assert audit_mod.detect_multi_program(trials) is False


# ---------------------------------------------------------------------------
# Spec §12 cases — consensus + status
# ---------------------------------------------------------------------------


class TestSpec12Cases:
    def test_phase3_high_confidence_validated(self):
        """§12 case 1: Phase-3 ticker validated by CT.gov HIGH-confidence sponsor match."""
        consensus, pre = audit_mod.derive_external_consensus(
            archetype="drug_developer",
            tier_commercial="",
            ctgov_stage="phase_3",
            ctgov_active_count=3,
            multi_program=False,
            fda_or_pb_approved=False,
            has_revenue=False,
            pdufa_pending=False,
            alias_conf="HIGH",
            orange_book_stale=False,
        )
        status = audit_mod.finalize_status(
            internal_stage="phase_3",
            consensus_stage=consensus,
            pre_status=pre,
            multi_program_hint=False,
            alias_conf="HIGH",
        )
        assert consensus == "phase_3"
        assert status == "validated"

    def test_commercial_validated_by_fda_and_revenue(self):
        """§12 case 2: Commercial ticker validated by FDA/Orange/Purple Book + revenue line."""
        consensus, pre = audit_mod.derive_external_consensus(
            archetype="commercial_pharma",
            tier_commercial="A",
            ctgov_stage="phase_3",  # Phase 4 trials would also be here
            ctgov_active_count=5,
            multi_program=False,
            fda_or_pb_approved=True,
            has_revenue=True,
            pdufa_pending=False,
            alias_conf="HIGH",
            orange_book_stale=False,
        )
        status = audit_mod.finalize_status(
            internal_stage="commercial",
            consensus_stage=consensus,
            pre_status=pre,
            multi_program_hint=False,
            alias_conf="HIGH",
        )
        assert consensus == "commercial"
        assert status == "validated"

    def test_preclinical_only_from_sec_no_ctgov(self):
        """§12 case 3: Preclinical-only-from-SEC ticker (no CT.gov record)."""
        consensus, pre = audit_mod.derive_external_consensus(
            archetype="drug_developer",
            tier_commercial="",
            ctgov_stage="unknown",
            ctgov_active_count=0,
            multi_program=False,
            fda_or_pb_approved=False,
            has_revenue=False,
            pdufa_pending=False,
            alias_conf="NONE",
            orange_book_stale=False,
        )
        status = audit_mod.finalize_status(
            internal_stage="preclinical",
            consensus_stage=consensus,
            pre_status=pre,
            multi_program_hint=False,
            alias_conf="NONE",
        )
        # No external evidence → status reflects that, not stage mismatch
        assert status == "no_external_evidence"

    def test_multi_program_emits_ambiguous_not_stale(self):
        """§12 case 4: Multi-program ticker emits ambiguous_multi_program, not likely_internal_stale."""
        consensus, pre = audit_mod.derive_external_consensus(
            archetype="drug_developer",
            tier_commercial="",
            ctgov_stage="phase_3",
            ctgov_active_count=4,
            multi_program=True,
            fda_or_pb_approved=False,
            has_revenue=False,
            pdufa_pending=False,
            alias_conf="HIGH",
            orange_book_stale=False,
        )
        # Internal says phase_2 — would normally be likely_internal_stale, but multi-program guards
        status = audit_mod.finalize_status(
            internal_stage="phase_2",
            consensus_stage=consensus,
            pre_status=pre,
            multi_program_hint=(pre == "ambiguous_multi_program_hint"),
            alias_conf="HIGH",
        )
        assert status == "ambiguous_multi_program"
        assert status != "likely_internal_stale"

    def test_platform_diagnostics_emits_platform_status(self):
        """§12 case 5: Platform/diagnostics ticker emits platform_not_ctgov_applicable, not no_external_evidence."""
        consensus, pre = audit_mod.derive_external_consensus(
            archetype="platform_diagnostics",
            tier_commercial="C",
            ctgov_stage="unknown",
            ctgov_active_count=0,
            multi_program=False,
            fda_or_pb_approved=False,
            has_revenue=False,
            pdufa_pending=False,
            alias_conf="NONE",
            orange_book_stale=False,
        )
        status = audit_mod.finalize_status(
            internal_stage="commercial",
            consensus_stage=consensus,
            pre_status=pre,
            multi_program_hint=False,
            alias_conf="NONE",
        )
        assert status == "platform_not_ctgov_applicable"

    def test_low_alias_cannot_escalate_past_validated(self):
        """§12 case 6: LOW-confidence alias cannot escalate past validated."""
        # External evidence says phase_3, internal says phase_2 — would normally be likely_internal_stale.
        # But LOW alias confidence must block that escalation.
        consensus, pre = audit_mod.derive_external_consensus(
            archetype="drug_developer",
            tier_commercial="",
            ctgov_stage="phase_3",
            ctgov_active_count=2,
            multi_program=False,
            fda_or_pb_approved=False,
            has_revenue=False,
            pdufa_pending=False,
            alias_conf="LOW",
            orange_book_stale=False,
        )
        status = audit_mod.finalize_status(
            internal_stage="phase_2",
            consensus_stage=consensus,
            pre_status=pre,
            multi_program_hint=False,
            alias_conf="LOW",
        )
        # Must NOT escalate to likely_internal_stale; must be sponsor_alias_uncertain
        assert status != "likely_internal_stale"
        assert status == "sponsor_alias_uncertain"


# ---------------------------------------------------------------------------
# Phase 4 ≠ commercial guard (explicit Spec 068 §5 callout)
# ---------------------------------------------------------------------------


class TestPhase4NotCommercial:
    def test_phase4_alone_does_not_consense_commercial(self):
        """Phase 4 trials alone do NOT consense to commercial — only to approved."""
        consensus, _ = audit_mod.derive_external_consensus(
            archetype="drug_developer",
            tier_commercial="",
            ctgov_stage="approved",  # PHASE4 maps here
            ctgov_active_count=3,
            multi_program=False,
            fda_or_pb_approved=False,  # no FDA/PB hit
            has_revenue=False,  # no revenue
            pdufa_pending=False,
            alias_conf="HIGH",
            orange_book_stale=False,
        )
        # Without FDA approval AND revenue, must not collapse to commercial
        assert consensus != "commercial"
        assert consensus == "approved"

    def test_phase4_with_fda_and_revenue_consenses_commercial(self):
        """Phase 4 + FDA approval + revenue → commercial is justified."""
        consensus, _ = audit_mod.derive_external_consensus(
            archetype="commercial_pharma",
            tier_commercial="A",
            ctgov_stage="approved",
            ctgov_active_count=3,
            multi_program=False,
            fda_or_pb_approved=True,
            has_revenue=True,
            pdufa_pending=False,
            alias_conf="HIGH",
            orange_book_stale=False,
        )
        assert consensus == "commercial"


# ---------------------------------------------------------------------------
# Material revenue helper
# ---------------------------------------------------------------------------


class TestMaterialRevenue:
    def test_zero_revenue_false(self):
        facts = {"revenue": [{"end": "2025-03-31", "val": 0}]}
        assert audit_mod.has_material_revenue(facts) is False

    def test_large_revenue_true(self):
        facts = {"revenue": [{"end": "2025-06-30", "val": 100_000_000}]}
        assert audit_mod.has_material_revenue(facts) is True

    def test_empty_facts_false(self):
        assert audit_mod.has_material_revenue({}) is False
        assert audit_mod.has_material_revenue({"revenue": []}) is False


# ---------------------------------------------------------------------------
# Decision branch enum sanity
# ---------------------------------------------------------------------------


class TestDecisionBranchEnum:
    def test_decision_branches_set_matches_spec(self):
        assert audit_mod.DECISION_BRANCHES == {"MANUAL_FIX", "RECURRING_VALIDATOR", "ALIAS_MAP_FIRST"}

    def test_validation_statuses_set_matches_spec(self):
        expected = {
            "validated",
            "likely_internal_stale",
            "external_lower_than_internal",
            "ambiguous_multi_program",
            "sponsor_alias_uncertain",
            "platform_not_ctgov_applicable",
            "no_external_evidence",
            "override_disagrees_with_consensus",
        }
        assert audit_mod.VALIDATION_STATUSES == expected


# ---------------------------------------------------------------------------
# SEC cache scan — provenance metadata only, must not affect classification
# ---------------------------------------------------------------------------


class TestSECCacheScan:
    def test_sec_cache_verdicts_set_matches_spec(self):
        expected = {
            "SEC_CACHE_OK_EVENT_COUNT_CONFUSION",
            "SEC_CACHE_STALE_BUT_OPTIONAL",
            "SEC_CACHE_PATH_MOVED",
            "SEC_DISABLED_OPTIONAL",
            "SEC_CACHE_INCOMPLETE_BLOCK_SPEC_068",
        }
        assert audit_mod.SEC_CACHE_VERDICTS == expected

    def test_missing_path_returns_path_moved(self, tmp_path):
        result = audit_mod.scan_sec_cache(tmp_path / "does_not_exist", "2026-04-28")
        assert result["verdict"] == "SEC_CACHE_PATH_MOVED"
        assert result["consumed_by_audit"] is False

    def test_empty_dir_returns_incomplete(self, tmp_path):
        result = audit_mod.scan_sec_cache(tmp_path, "2026-04-28")
        assert result["verdict"] == "SEC_CACHE_INCOMPLETE_BLOCK_SPEC_068"
        assert result["file_count"] == 0

    def test_staging_subdirs_skipped(self, tmp_path):
        # Real file
        good = tmp_path / "8k_catalysts_2026-04-28_abc.json"
        good.write_text("[]")
        # Staging subdir that previously broke os.listdir-based readers
        staging = tmp_path / ".staging_8k_xxx"
        staging.mkdir()
        (staging / "child.json").write_text("[]")
        result = audit_mod.scan_sec_cache(tmp_path, "2026-04-28")
        # Only the real top-level file should be counted
        assert result["file_count"] == 1
        assert result["consumed_by_audit"] is False

    def test_today_present_with_events_yields_ok_confusion(self, tmp_path):
        (tmp_path / "8k_catalysts_2026-04-28_abc.json").write_text(
            json.dumps([{"ticker": "X", "event_type": "DATA_READOUT"}])
        )
        # Add a staging subdir for completeness — must not be counted.
        (tmp_path / ".staging_8k_yyy").mkdir()
        result = audit_mod.scan_sec_cache(tmp_path, "2026-04-28")
        assert result["verdict"] == "SEC_CACHE_OK_EVENT_COUNT_CONFUSION"
        assert result["event_count"] == 1
        assert result["as_of_date_file_present"] is True

    def test_only_old_files_yields_stale(self, tmp_path):
        (tmp_path / "8k_catalysts_2026-01-15_abc.json").write_text(json.dumps([{"x": 1}]))
        result = audit_mod.scan_sec_cache(tmp_path, "2026-04-28")
        assert result["verdict"] == "SEC_CACHE_STALE_BUT_OPTIONAL"

    def test_sec_status_does_not_appear_in_consensus_inputs(self):
        """Defensive: derive_external_consensus must not accept SEC inputs.

        SEC absence/presence cannot affect consensus. If a future change adds
        an `sec_*` parameter, this test will fail and force a re-review.
        """
        import inspect

        sig = inspect.signature(audit_mod.derive_external_consensus)
        for param_name in sig.parameters:
            assert "sec" not in param_name.lower(), (
                f"derive_external_consensus must not depend on SEC inputs; " f"found parameter '{param_name}'"
            )


# ---------------------------------------------------------------------------
# Override revalidation (Spec 068 Lane 1)
# ---------------------------------------------------------------------------


class TestOverrideRevalidation:
    def test_override_disagrees_in_validation_statuses_set(self):
        assert "override_disagrees_with_consensus" in audit_mod.VALIDATION_STATUSES

    def test_loader_missing_file_returns_empty_dict(self, tmp_path):
        result = audit_mod.load_development_stage_overrides(tmp_path / "missing.json")
        assert result == {}

    def test_loader_malformed_json_returns_empty_dict(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{not valid json")
        result = audit_mod.load_development_stage_overrides(bad)
        assert result == {}

    def test_loader_returns_ticker_to_stage_map(self, tmp_path):
        good = tmp_path / "overrides.json"
        good.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "entries": {
                        "AAA": {"stage": "commercial", "evidence": "x"},
                        "BBB": {"stage": "nda_bla", "evidence": "y"},
                        "ccc": {"stage": "phase_3", "evidence": "z"},
                    },
                }
            )
        )
        result = audit_mod.load_development_stage_overrides(good)
        assert result == {"AAA": "commercial", "BBB": "nda_bla", "CCC": "phase_3"}

    def test_loader_ignores_non_dict_payload(self, tmp_path):
        bad = tmp_path / "overrides.json"
        bad.write_text(json.dumps({"entries": "not a dict"}))
        assert audit_mod.load_development_stage_overrides(bad) == {}

    def test_loader_skips_entries_without_string_stage(self, tmp_path):
        bad = tmp_path / "overrides.json"
        bad.write_text(
            json.dumps(
                {
                    "entries": {
                        "OK": {"stage": "commercial"},
                        "BAD1": "not a dict",
                        "BAD2": {"stage": 42},
                        "BAD3": {"no_stage_key": "x"},
                    },
                }
            )
        )
        assert audit_mod.load_development_stage_overrides(bad) == {"OK": "commercial"}
