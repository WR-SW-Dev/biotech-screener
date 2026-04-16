"""Tests for HINT research integration.

Covers:
  - Schema mapper loads and parses HINT data
  - Protocol feature extraction from eligibility text
  - Benchmark runs without error
  - PIT safety tags on all outputs
  - HINT labels marked as benchmark-only
  - No HINT imports in production code
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestHINTAdapter:

    def test_load_hint_raw(self):
        from research.hint_adapter import load_hint_raw

        records = load_hint_raw(phase_filter="3")
        assert len(records) > 1000  # Phase 3 has ~5,400+ records

    def test_record_schema(self):
        from research.hint_adapter import load_hint_raw

        records = load_hint_raw(phase_filter="3")
        rec = records[0]
        assert rec.nctid.startswith("NCT")
        assert rec.phase == "3"
        assert rec.label in (0, 1)
        assert rec.label_source == "hint_top_benchmark"
        assert rec.usage == "offline_eval_only"

    def test_phase_normalization(self):
        from research.hint_adapter import load_hint_raw

        records = load_hint_raw()
        phases = {r.phase for r in records}
        # Should use our internal format, not HINT's "phase 1" etc.
        assert "phase 1" not in phases
        assert "1" in phases or "2" in phases or "3" in phases

    def test_criteria_text_populated(self):
        from research.hint_adapter import load_hint_raw

        records = load_hint_raw(phase_filter="3")
        with_criteria = sum(1 for r in records if r.criteria_text.strip())
        assert with_criteria / len(records) > 0.95  # >95% have criteria

    def test_nct_matching(self):
        import json

        from research.hint_adapter import load_hint_raw, match_hint_to_internal

        hint = load_hint_raw(phase_filter="3")
        our_trials = json.loads((REPO_ROOT / "production_data" / "trial_records.json").read_text())
        our_ncts = {t.get("nct_id", "") for t in our_trials if t.get("nct_id")}
        matched = match_hint_to_internal(hint, our_ncts)
        assert len(matched) > 100  # expect 500+ Phase 3 matches

    def test_sponsor_rates_load(self):
        from research.hint_adapter import load_hint_sponsor_rates

        rates = load_hint_sponsor_rates()
        assert len(rates) > 100
        # Check a known sponsor
        pfizer = rates.get("Pfizer")
        if pfizer:
            assert 0.0 < pfizer["approval_rate"] < 1.0
            assert pfizer["total"] > 100

    def test_hint_splits_load(self):
        from research.hint_adapter import load_hint_splits

        splits = load_hint_splits(phase="III")
        assert len(splits["train"]) > 2000
        assert len(splits["test"]) > 500
        assert len(splits["valid"]) > 100

    def test_to_dict_serialization(self):
        from research.hint_adapter import load_hint_raw

        records = load_hint_raw(phase_filter="3")
        d = records[0].to_dict()
        assert "nctid" in d
        assert "label_source" in d
        assert d["label_source"] == "hint_top_benchmark"


class TestProtocolFeatureExtraction:

    def test_basic_extraction(self):
        from research.hint_feature_extract import extract_protocol_features

        text = """
        Inclusion Criteria:
          - Age >= 18 years
          - Confirmed HER2-positive breast cancer
          - ECOG performance status 0-1
        Exclusion Criteria:
          - Prior treatment with trastuzumab
          - Active brain metastases
        """
        pf = extract_protocol_features("NCT99999999", text)
        assert pf.inclusion_criteria_count >= 2
        assert pf.exclusion_criteria_count >= 1
        assert pf.biomarker_selection_flag is True  # HER2 detected
        assert pf.pit_status == "pre_catalyst_safe"

    def test_randomization_detection(self):
        from research.hint_feature_extract import extract_protocol_features

        text = "This is a randomized, double-blind, placebo-controlled study."
        pf = extract_protocol_features("NCT00000001", text)
        assert pf.randomization_flag is True
        assert pf.blinding_flag is True
        assert pf.comparator_present_flag is True

    def test_empty_text(self):
        from research.hint_feature_extract import extract_protocol_features

        pf = extract_protocol_features("NCT00000002", "")
        assert pf.inclusion_criteria_count == 0
        assert pf.protocol_complexity_score == 0.0
        assert pf.biomarker_selection_flag is False

    def test_complexity_score_bounded(self):
        from research.hint_feature_extract import extract_protocol_features

        # Very long, complex text
        text = "Inclusion Criteria:\n" + "\n".join(f"  - Criterion {i}" for i in range(50))
        text += "\nExclusion Criteria:\n" + "\n".join(f"  - Exclusion {i}" for i in range(30))
        text += "\nbiomarker multi-arm"
        pf = extract_protocol_features("NCT00000003", text)
        assert 0.0 <= pf.protocol_complexity_score <= 1.0

    def test_batch_extraction(self):
        from research.hint_adapter import load_hint_raw
        from research.hint_feature_extract import extract_batch

        records = load_hint_raw(phase_filter="3")[:100]
        features = extract_batch(records)
        assert len(features) == 100
        # All should have PIT-safe status
        for pf in features.values():
            assert pf.pit_status == "pre_catalyst_safe"

    def test_endpoint_specificity(self):
        from research.hint_feature_extract import extract_protocol_features

        text = "Primary endpoint is overall survival and progression-free survival."
        pf = extract_protocol_features("NCT00000004", text)
        assert pf.endpoint_specificity_proxy > 0.0

    def test_frozen_dataclass(self):
        import pytest

        from research.hint_feature_extract import extract_protocol_features

        pf = extract_protocol_features("NCT00000005", "some text")
        with pytest.raises(AttributeError):
            pf.nctid = "changed"  # type: ignore[misc]


class TestBenchmark:

    def test_benchmark_runs(self):
        from research.hint_benchmark import run_benchmark

        result = run_benchmark(phase="3")
        assert result["n_total"] > 1000
        assert "baselines" in result
        assert "hint_phase_base_rate" in result["baselines"]

    def test_benchmark_has_recommendation(self):
        from research.hint_benchmark import run_benchmark

        result = run_benchmark(phase="3")
        assert "recommendation" in result
        assert "overall" in result["recommendation"]

    def test_brier_scores_reasonable(self):
        from research.hint_benchmark import run_benchmark

        result = run_benchmark(phase="3")
        brier = result["baselines"]["hint_phase_base_rate"]["brier"]
        # Brier should be between 0 and 0.5 for any reasonable model
        assert 0.0 < brier < 0.5

    def test_protocol_feature_stats_present(self):
        from research.hint_benchmark import run_benchmark

        result = run_benchmark(phase="3")
        stats = result.get("protocol_feature_stats", {})
        assert "complexity_mean" in stats
        assert "n_with_biomarker" in stats


class TestPITSafety:

    def test_hint_labels_tagged_benchmark_only(self):
        from research.hint_adapter import load_hint_raw

        records = load_hint_raw(phase_filter="3")[:10]
        for rec in records:
            assert rec.label_source == "hint_top_benchmark"
            assert rec.usage == "offline_eval_only"

    def test_protocol_features_tagged_pit_safe(self):
        from research.hint_feature_extract import extract_protocol_features

        pf = extract_protocol_features("NCT00000001", "Inclusion: age >= 18")
        assert pf.pit_status == "pre_catalyst_safe"

    def test_no_hint_imports_in_production(self):
        """Verify HINT/research modules are not imported by production code."""
        import ast

        production_dirs = ["event_ev", "common", "tools", "data_sources"]
        violations = []

        for d in production_dirs:
            dir_path = REPO_ROOT / d
            if not dir_path.exists():
                continue
            for py_file in dir_path.rglob("*.py"):
                try:
                    tree = ast.parse(py_file.read_text())
                except SyntaxError:
                    continue
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            if alias.name.startswith("research.hint"):
                                violations.append(f"{py_file}:{node.lineno}")
                    elif isinstance(node, ast.ImportFrom):
                        if node.module and node.module.startswith("research.hint"):
                            violations.append(f"{py_file}:{node.lineno}")

        assert violations == [], f"Production code imports HINT: {violations}"
