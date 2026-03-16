"""Tests for build_clinical_pos_priors_v3.py — all synthetic, no file I/O."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.research.build_clinical_pos_priors_v3 import (
    ENDPOINT_MODIFIER_CAP,
    WONG_REFERENCE,
    _bounded_endpoint_delta,
    _effective_sample_size,
    _endpoint_key,
    _phase_key,
    _shrink_rate,
    _status_key,
    main,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_catalog_record(
    nct_id: str,
    phase: str = "phase2",
    status: str = "COMPLETED",
    endpoint: str = "other",
    is_terminated: bool = False,
    has_posted_results: bool = False,
) -> Dict[str, Any]:
    return {
        "nct_id": nct_id,
        "phase": phase,
        "status": status,
        "design": {"endpoint_class": endpoint, "enrollment_bucket": "medium", "biomarker_selected": False},
        "lifecycle": {
            "is_completed": status == "COMPLETED",
            "is_terminated": is_terminated,
            "has_posted_results": has_posted_results,
        },
    }


def _make_label_record(
    nct_id: str,
    binary_outcome: int,
    phase: str = "phase2",
    confidence: str = "high",
) -> Dict[str, Any]:
    return {
        "nct_id": nct_id,
        "ticker": "TEST",
        "phase": phase,
        "binary_outcome": binary_outcome,
        "confidence": confidence,
        "outcome_basis": "pvalue",
    }


def _write_artifacts(tmp: Path, catalog_records: List[Dict], label_records: List[Dict]):
    """Write catalog + labels files for integration tests."""
    catalog_path = tmp / "catalog.json"
    catalog_path.write_text(
        json.dumps(
            {
                "schema_version": "clinical_history_catalog.v1",
                "built_as_of": "2026-03-16",
                "n_records": len(catalog_records),
                "records": catalog_records,
            }
        )
    )

    labels_path = tmp / "labels.json"
    labels_path.write_text(
        json.dumps(
            {
                "schema": "clinical_outcome_labels.v2",
                "built_as_of": "2026-03-16",
                "n_labels": len(label_records),
                "labels": label_records,
            }
        )
    )

    return catalog_path, labels_path


# ===========================================================================
# Unit tests: phase/endpoint/status normalization
# ===========================================================================


class TestPhaseKey:
    def test_standard_phases(self):
        assert _phase_key("phase2") == "phase2"
        assert _phase_key("phase3") == "phase3"
        assert _phase_key("phase4") == "phase4"

    def test_combined_phases(self):
        assert _phase_key("phase1_2") == "phase1_2"
        assert _phase_key("phase2_3") == "phase2_3"

    def test_unknown_fallback(self):
        assert _phase_key("na") == "unknown"
        assert _phase_key("n/a") == "unknown"
        assert _phase_key("") == "unknown"
        assert _phase_key("nonsense") == "unknown"

    def test_case_insensitive(self):
        assert _phase_key("Phase2") == "phase2"
        assert _phase_key("PHASE3") == "phase3"


class TestEndpointKey:
    def test_known_endpoints(self):
        assert _endpoint_key("overall_survival") == "overall_survival"
        assert _endpoint_key("other") == "other"

    def test_unknown_fallback(self):
        assert _endpoint_key("") == "other"
        assert _endpoint_key("something_else") == "other"


class TestStatusKey:
    def test_normalizes(self):
        assert _status_key("completed") == "COMPLETED"
        assert _status_key("TERMINATED") == "TERMINATED"
        assert _status_key("") == ""


# ===========================================================================
# Unit tests: shrinkage and support
# ===========================================================================


class TestEffectiveSampleSize:
    def test_labeled_only(self):
        assert _effective_sample_size(100, 0) == 100.0

    def test_unlabeled_half_weight(self):
        assert _effective_sample_size(100, 200) == 200.0

    def test_zero(self):
        assert _effective_sample_size(0, 0) == 0.0


class TestShrinkRate:
    def test_no_empirical_returns_reference(self):
        rate, source = _shrink_rate(None, 0.5, 0, 0, 50, 150.0)
        assert rate == 0.5
        assert source == "reference_no_empirical"

    def test_thin_support_returns_reference(self):
        rate, source = _shrink_rate(0.8, 0.5, 10, 10, 50, 150.0)
        assert rate == 0.5
        assert source == "reference_thin_support"

    def test_sufficient_support_shrinks(self):
        rate, source = _shrink_rate(0.8, 0.5, 200, 100, 50, 150.0)
        assert source == "shrunk_empirical"
        # Should be between empirical (0.8) and reference (0.5)
        assert 0.5 < rate < 0.8

    def test_high_n_approaches_empirical(self):
        rate, _ = _shrink_rate(0.8, 0.5, 10000, 0, 50, 150.0)
        assert abs(rate - 0.8) < 0.02

    def test_low_n_approaches_reference(self):
        rate, _ = _shrink_rate(0.8, 0.5, 55, 0, 50, 150.0)
        # ESS=55, prior_strength=150 → weight_emp ~0.27
        assert rate < 0.60


class TestBoundedEndpointDelta:
    def test_small_delta_passes_through(self):
        delta = _bounded_endpoint_delta(0.55, 0.50)
        assert delta == pytest.approx(0.05)

    def test_positive_cap(self):
        delta = _bounded_endpoint_delta(0.90, 0.50)
        assert delta == ENDPOINT_MODIFIER_CAP

    def test_negative_cap(self):
        delta = _bounded_endpoint_delta(0.10, 0.50)
        assert delta == -ENDPOINT_MODIFIER_CAP

    def test_none_inputs(self):
        assert _bounded_endpoint_delta(None, 0.5) == 0.0
        assert _bounded_endpoint_delta(0.5, None) == 0.0


# ===========================================================================
# Integration tests: full pipeline via main()
# ===========================================================================


class TestMainIntegration:
    def _run_main(self, catalog_records, label_records, extra_args=None):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            cat_path, lab_path = _write_artifacts(tmp, catalog_records, label_records)
            out_path = tmp / "priors_v3.json"
            argv = [
                "--catalog",
                str(cat_path),
                "--labels",
                str(lab_path),
                "--out",
                str(out_path),
            ]
            if extra_args:
                argv.extend(extra_args)
            rc = main(argv)
            assert rc == 0
            return json.loads(out_path.read_text())

    def test_schema_version(self):
        cats = [_make_catalog_record(f"NCT{i:08d}", has_posted_results=True) for i in range(60)]
        labs = [_make_label_record(f"NCT{i:08d}", 1 if i < 40 else 0) for i in range(60)]
        result = self._run_main(cats, labs)
        assert result["schema_version"] == "clinical_pos_priors.v3"

    def test_survivorship_lowers_rate(self):
        """Adding terminated trials should produce adjusted rate < observed rate."""
        # 80 labeled (60 success, 20 failure)
        cats = []
        labs = []
        for i in range(80):
            cats.append(_make_catalog_record(f"NCT{i:08d}", has_posted_results=True))
            labs.append(_make_label_record(f"NCT{i:08d}", 1 if i < 60 else 0))

        # 100 terminated unlabeled
        for i in range(80, 180):
            cats.append(
                _make_catalog_record(
                    f"NCT{i:08d}",
                    status="TERMINATED",
                    is_terminated=True,
                )
            )

        result = self._run_main(cats, labs)
        p2 = result["phase_priors"]["phase2"]
        assert p2["observed_rate_posted_results_only"] == pytest.approx(0.75, abs=0.01)
        assert p2["survivorship_adjusted_rate"] < p2["observed_rate_posted_results_only"]

    def test_terminated_fail_prob_adjustable(self):
        """Different terminated-fail-prob should change adjusted rate."""
        cats = []
        labs = []
        for i in range(60):
            cats.append(_make_catalog_record(f"NCT{i:08d}", has_posted_results=True))
            labs.append(_make_label_record(f"NCT{i:08d}", 1 if i < 40 else 0))
        for i in range(60, 160):
            cats.append(_make_catalog_record(f"NCT{i:08d}", status="TERMINATED", is_terminated=True))

        r1 = self._run_main(cats, labs, ["--terminated-fail-prob", "0.50"])
        r2 = self._run_main(cats, labs, ["--terminated-fail-prob", "0.95"])

        adj1 = r1["phase_priors"]["phase2"]["survivorship_adjusted_rate"]
        adj2 = r2["phase_priors"]["phase2"]["survivorship_adjusted_rate"]
        # Higher fail prob → lower adjusted rate
        assert adj2 < adj1

    def test_worst_case_rate(self):
        """Worst case treats all unlabeled as failures."""
        cats = []
        labs = []
        for i in range(60):
            cats.append(_make_catalog_record(f"NCT{i:08d}", has_posted_results=True))
            labs.append(_make_label_record(f"NCT{i:08d}", 1 if i < 40 else 0))
        for i in range(60, 160):
            cats.append(_make_catalog_record(f"NCT{i:08d}", status="TERMINATED", is_terminated=True))

        result = self._run_main(cats, labs)
        p2 = result["phase_priors"]["phase2"]
        # 40 successes out of 60 labeled + 100 terminated = 160 total
        expected_worst = 40 / 160
        assert p2["worst_case_rate_all_unlabeled_fail"] == pytest.approx(expected_worst, abs=0.01)

    def test_completed_no_results(self):
        """Completed-no-results trials contribute to survivorship adjustment."""
        cats = []
        labs = []
        for i in range(60):
            cats.append(_make_catalog_record(f"NCT{i:08d}", has_posted_results=True))
            labs.append(_make_label_record(f"NCT{i:08d}", 1 if i < 40 else 0))
        # 50 completed but no results posted
        for i in range(60, 110):
            cats.append(
                _make_catalog_record(
                    f"NCT{i:08d}",
                    status="COMPLETED",
                    has_posted_results=False,
                )
            )

        result = self._run_main(cats, labs)
        p2 = result["phase_priors"]["phase2"]
        assert p2["counts"]["n_completed_no_results_unlabeled"] == 50

    def test_endpoint_modifier_bounded(self):
        """Endpoint deltas should be capped at ENDPOINT_MODIFIER_CAP."""
        cats = []
        labs = []
        # All successes with OS endpoint
        for i in range(60):
            cats.append(_make_catalog_record(f"NCT{i:08d}", endpoint="overall_survival", has_posted_results=True))
            labs.append(_make_label_record(f"NCT{i:08d}", 1))

        result = self._run_main(cats, labs)
        for ep, mod in result["endpoint_modifiers"].items():
            assert abs(mod["modifier_delta"]) <= ENDPOINT_MODIFIER_CAP + 1e-9

    def test_biomarker_neutral(self):
        """Biomarker modifier should be zero."""
        cats = [_make_catalog_record(f"NCT{i:08d}", has_posted_results=True) for i in range(60)]
        labs = [_make_label_record(f"NCT{i:08d}", 1 if i < 40 else 0) for i in range(60)]
        result = self._run_main(cats, labs)
        assert result["biomarker_modifier"]["modifier_delta"] == 0.0

    def test_uncertainty_bounds(self):
        """Uncertainty bounds should bracket the adjusted rate."""
        cats = []
        labs = []
        for i in range(80):
            cats.append(_make_catalog_record(f"NCT{i:08d}", has_posted_results=True))
            labs.append(_make_label_record(f"NCT{i:08d}", 1 if i < 50 else 0))
        for i in range(80, 180):
            cats.append(_make_catalog_record(f"NCT{i:08d}", status="TERMINATED", is_terminated=True))

        result = self._run_main(cats, labs)
        p2 = result["phase_priors"]["phase2"]
        bounds = p2["uncertainty_bounds"]
        adj = p2["survivorship_adjusted_rate"]
        assert bounds["lower_worst_case"] <= adj
        assert adj <= bounds["upper_observed"]

    def test_source_artifacts_present(self):
        """Output should include source artifact hashes."""
        cats = [_make_catalog_record(f"NCT{i:08d}", has_posted_results=True) for i in range(60)]
        labs = [_make_label_record(f"NCT{i:08d}", 1 if i < 40 else 0) for i in range(60)]
        result = self._run_main(cats, labs)
        assert "source_artifacts" in result
        assert "sha256" in result["source_artifacts"]["clinical_history_catalog"]
        assert "sha256" in result["source_artifacts"]["clinical_outcome_labels_v2"]

    def test_empty_phase_gets_reference(self):
        """Phase with no data should fall back to Wong reference."""
        cats = [_make_catalog_record(f"NCT{i:08d}", phase="phase2", has_posted_results=True) for i in range(60)]
        labs = [_make_label_record(f"NCT{i:08d}", 1 if i < 40 else 0, phase="phase2") for i in range(60)]
        result = self._run_main(cats, labs)
        # phase3 has no data → should be reference
        p3 = result["phase_priors"]["phase3"]
        assert p3["source"] == "reference_no_empirical"
        assert p3["shrunk_rate"] == WONG_REFERENCE["phase3"]

    def test_withdrawn_counted_separately(self):
        """WITHDRAWN trials should be counted in withdrawn_unlabeled, not terminated."""
        cats = []
        labs = []
        for i in range(60):
            cats.append(_make_catalog_record(f"NCT{i:08d}", has_posted_results=True))
            labs.append(_make_label_record(f"NCT{i:08d}", 1 if i < 40 else 0))
        for i in range(60, 80):
            cats.append(_make_catalog_record(f"NCT{i:08d}", status="WITHDRAWN"))
        for i in range(80, 100):
            cats.append(_make_catalog_record(f"NCT{i:08d}", status="TERMINATED", is_terminated=True))

        result = self._run_main(cats, labs)
        p2 = result["phase_priors"]["phase2"]
        assert p2["counts"]["n_withdrawn_unlabeled"] == 20
        assert p2["counts"]["n_terminated_unlabeled"] == 20

    def test_low_confidence_labels_excluded(self):
        """Low-confidence labels should be excluded by default."""
        cats = [_make_catalog_record(f"NCT{i:08d}", has_posted_results=True) for i in range(60)]
        # 30 high-confidence, 30 low-confidence
        labs = []
        for i in range(30):
            labs.append(_make_label_record(f"NCT{i:08d}", 1, confidence="high"))
        for i in range(30, 60):
            labs.append(_make_label_record(f"NCT{i:08d}", 0, confidence="low"))

        result = self._run_main(cats, labs)
        # Only 30 high-confidence labels should be admitted
        assert result["overall"]["counts"]["n_labeled_total"] == 30

    def test_deterministic(self):
        """Same inputs should produce same outputs."""
        cats = []
        labs = []
        for i in range(80):
            cats.append(_make_catalog_record(f"NCT{i:08d}", has_posted_results=True))
            labs.append(_make_label_record(f"NCT{i:08d}", 1 if i < 50 else 0))
        for i in range(80, 130):
            cats.append(_make_catalog_record(f"NCT{i:08d}", status="TERMINATED", is_terminated=True))

        r1 = self._run_main(cats, labs)
        r2 = self._run_main(cats, labs)
        # Remove date-dependent fields
        for r in (r1, r2):
            r.pop("built_as_of", None)
            r.pop("source_artifacts", None)
        assert r1 == r2
