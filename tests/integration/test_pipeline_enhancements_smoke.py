"""
Smoke test: pipeline with enhancement engines enabled.

Exercises the enhancement orchestration path that existing smoke tests
skip (they use enable_enhancements=False). Verifies that:
1. Pipeline completes when enhancement modules are available
2. Pipeline degrades gracefully when enhancement modules are missing
3. Output structure includes enhancement metadata
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow

from run_screen import run_screening_pipeline

_BASE_KWARGS = dict(
    as_of_date="2026-01-15",
    pit_mode="strict",
    enable_short_interest=False,
    enable_coinvest=False,
    no_clinical_filter=True,
    ctgov_cache_dir=False,
)


def _patch_trial_records(data_dir: Path) -> None:
    """Ensure trial records have required fields."""
    trial_path = data_dir / "trial_records.json"
    if not trial_path.exists():
        return
    trials = json.loads(trial_path.read_text())
    for rec in trials:
        if "ticker" not in rec and "sponsor_ticker" in rec:
            rec["ticker"] = rec["sponsor_ticker"]
        if "last_update_posted" not in rec:
            rec["last_update_posted"] = "2026-01-10"
    trial_path.write_text(json.dumps(trials, indent=2))


@pytest.fixture
def patched_data_dir(sample_data_dir: Path) -> Path:
    _patch_trial_records(sample_data_dir)
    return sample_data_dir


class TestEnhancementsEnabled:
    """Pipeline should complete with enhancements enabled."""

    def test_pipeline_completes_with_enhancements(self, patched_data_dir: Path):
        """Enhancement engines load and run without crashing the pipeline."""
        result = run_screening_pipeline(
            data_dir=patched_data_dir,
            enable_enhancements=True,
            **_BASE_KWARGS,
        )

        assert "run_metadata" in result
        assert "summary" in result
        assert result["summary"]["total_evaluated"] > 0

    def test_enhancement_metadata_present(self, patched_data_dir: Path):
        """When enhancements are enabled, metadata should reflect it."""
        result = run_screening_pipeline(
            data_dir=patched_data_dir,
            enable_enhancements=True,
            **_BASE_KWARGS,
        )

        meta = result.get("run_metadata", {})
        assert meta.get("enhancements_enabled") is True

    def test_pipeline_completes_without_enhancements(self, patched_data_dir: Path):
        """Baseline: pipeline completes with enhancements disabled."""
        result = run_screening_pipeline(
            data_dir=patched_data_dir,
            enable_enhancements=False,
            **_BASE_KWARGS,
        )

        assert "run_metadata" in result
        meta = result.get("run_metadata", {})
        assert meta.get("enhancements_enabled") is False


class TestEnhancementDegradation:
    """Pipeline should degrade gracefully when optional modules are missing."""

    def test_pipeline_with_coinvest_enabled(self, patched_data_dir: Path):
        """Coinvest overlay should not crash even without coinvest_signals.json."""
        result = run_screening_pipeline(
            data_dir=patched_data_dir,
            enable_enhancements=True,
            enable_coinvest=True,
            **{k: v for k, v in _BASE_KWARGS.items() if k != "enable_coinvest"},
        )

        assert "run_metadata" in result
        assert result["summary"]["total_evaluated"] > 0

    def test_pipeline_with_short_interest(self, patched_data_dir: Path):
        """Short interest should degrade gracefully without data file."""
        result = run_screening_pipeline(
            data_dir=patched_data_dir,
            enable_enhancements=True,
            enable_short_interest=True,
            **{k: v for k, v in _BASE_KWARGS.items() if k != "enable_short_interest"},
        )

        assert "run_metadata" in result
        assert result["summary"]["total_evaluated"] > 0


class TestOutputStructure:
    """Verify output keys are present regardless of enhancement state."""

    def test_all_module_keys_present(self, patched_data_dir: Path):
        result = run_screening_pipeline(
            data_dir=patched_data_dir,
            enable_enhancements=True,
            **_BASE_KWARGS,
        )

        for key in [
            "module_1_universe",
            "module_2_financial",
            "module_3_catalyst",
            "module_4_clinical",
            "module_5_composite",
            "summary",
        ]:
            assert key in result, f"Missing key: {key}"

    def test_summary_structure(self, patched_data_dir: Path):
        result = run_screening_pipeline(
            data_dir=patched_data_dir,
            enable_enhancements=True,
            **_BASE_KWARGS,
        )

        summary = result["summary"]
        assert "total_evaluated" in summary
        assert "active_universe" in summary
        assert isinstance(summary["total_evaluated"], int)
