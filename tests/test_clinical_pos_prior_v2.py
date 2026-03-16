"""Tests for common/clinical_pos_prior.py (Spec 024)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from common.clinical_pos_prior import enrich_row_with_pos_prior, get_clinical_pos_prior


def _write_v2(tmp_path, overrides=None):
    """Write a minimal v2 prior artifact."""
    data = {
        "schema": "clinical_pos_priors.v2",
        "built_as_of": "2026-03-16",
        "by_phase": {
            "phase2": {"n": 580, "raw_rate": 0.522, "shrunk_rate": 0.513},
            "phase3": {"n": 760, "raw_rate": 0.732, "shrunk_rate": 0.727},
            "phase4": {"n": 120, "raw_rate": 0.575, "shrunk_rate": 0.597},
        },
        "endpoint_modifiers": {
            "overall_survival": {"n": 504, "shrunk_delta": -0.053},
            "other": {"n": 1078, "shrunk_delta": 0.024},
        },
        "biomarker_modifiers": {
            "yes": {"n": 70, "shrunk_delta": 0.0, "policy": "do_not_apply_directly"},
        },
    }
    if overrides:
        data.update(overrides)
    path = tmp_path / "clinical_pos_priors_v2.json"
    path.write_text(json.dumps(data))
    return path


class TestGetClinicalPosPrior:
    def test_v2_phase3(self, tmp_path):
        path = _write_v2(tmp_path)
        result = get_clinical_pos_prior("phase3", prior_path=path, as_of_date="2026-03-16")
        assert result["pos_prior_source"] == "v2_empirical"
        assert abs(result["pos_prior"] - (0.727 + 0.024)) < 0.01  # shrunk + other endpoint modifier

    def test_v2_phase2_os(self, tmp_path):
        path = _write_v2(tmp_path)
        result = get_clinical_pos_prior("phase2", "overall_survival", prior_path=path, as_of_date="2026-03-16")
        assert result["pos_prior_source"] == "v2_empirical"
        assert result["pos_prior"] < 0.513  # OS penalty applied
        assert result["pos_prior_endpoint_modifier"] < 0

    def test_fallback_missing_file(self, tmp_path):
        path = tmp_path / "nonexistent.json"
        result = get_clinical_pos_prior("phase3", prior_path=path)
        assert result["pos_prior_source"] == "wong_fallback"
        assert abs(result["pos_prior"] - 0.58) < 0.01

    def test_fallback_stale(self, tmp_path):
        path = _write_v2(tmp_path, {"built_as_of": "2025-01-01"})
        result = get_clinical_pos_prior("phase3", prior_path=path, as_of_date="2026-03-16")
        assert result["pos_prior_source"] == "wong_fallback"

    def test_fallback_thin_support(self, tmp_path):
        path = _write_v2(
            tmp_path,
            {
                "by_phase": {"phase3": {"n": 5, "raw_rate": 0.90, "shrunk_rate": 0.80}},
            },
        )
        result = get_clinical_pos_prior("phase3", prior_path=path, as_of_date="2026-03-16")
        assert result["pos_prior_source"] == "wong_fallback"

    def test_unknown_phase_fallback(self, tmp_path):
        path = _write_v2(tmp_path)
        result = get_clinical_pos_prior("preclinical", prior_path=path, as_of_date="2026-03-16")
        assert result["pos_prior_source"] == "wong_fallback"

    def test_biomarker_modifier_neutral(self, tmp_path):
        """Biomarker modifier is 0.0 — should not change the prior."""
        path = _write_v2(tmp_path)
        r_bio = get_clinical_pos_prior("phase3", prior_path=path, as_of_date="2026-03-16")
        # No biomarker modifier applied (it's only in biomarker_modifiers, not auto-applied)
        assert r_bio["pos_prior_source"] == "v2_empirical"


class TestEnrichRow:
    def test_enrichment_fields_present(self, tmp_path):
        path = _write_v2(tmp_path)
        row = {"_lead_phase": "phase3", "_endpoint_class": "other"}
        enrich_row_with_pos_prior(row, prior_path=path, as_of_date="2026-03-16")
        assert "pos_prior_source" in row
        assert "pos_prior_phase" in row
        assert "pos_prior_value_v2" in row
        assert row["pos_prior_source"] == "v2_empirical"

    def test_enrichment_missing_phase(self, tmp_path):
        path = _write_v2(tmp_path)
        row = {"_lead_phase": "", "_endpoint_class": "other"}
        enrich_row_with_pos_prior(row, prior_path=path, as_of_date="2026-03-16")
        assert row["pos_prior_source"] == "wong_fallback"
