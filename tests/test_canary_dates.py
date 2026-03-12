"""Tests for scripts/run_canary_dates.py — PIT canary date set."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

# Also load DiffThresholds for comparison
from scripts.replay_diff import DiffThresholds
from scripts.run_canary_dates import (  # noqa: F401 — ARCHIVE_DIR, FIXTURE_DIR used in subclasses
    CANARY_DATES,
    CanaryPolicy,
    main,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TestCanaryConstants:
    """Verify canary date set configuration."""

    def test_canary_dates_not_empty(self):
        assert len(CANARY_DATES) >= 2

    def test_canary_dates_iso_format(self):
        import re

        for d in CANARY_DATES:
            assert re.match(r"^\d{4}-\d{2}-\d{2}$", d), f"Bad date format: {d}"

    def test_canary_dates_quarterly_spread(self):
        """Dates should span at least 6 months."""
        from datetime import date

        dates = sorted(date.fromisoformat(d) for d in CANARY_DATES)
        span = (dates[-1] - dates[0]).days
        assert span >= 180, f"Canary dates span only {span} days"


class TestCanaryThresholds:
    """Verify canary thresholds are looser than production."""

    @pytest.fixture
    def prod_thresholds(self):
        path = PROJECT_ROOT / "production_data" / "diff_thresholds" / "v1.json"
        if not path.exists():
            pytest.skip("Production thresholds v1.json not found")
        return DiffThresholds.from_json(str(path))

    @pytest.fixture
    def canary_thresholds(self):
        path = PROJECT_ROOT / "production_data" / "diff_thresholds" / "canary_v1.json"
        if not path.exists():
            pytest.skip("Canary thresholds canary_v1.json not found")
        return DiffThresholds.from_json(str(path))

    def test_canary_fail_thresholds_looser(self, prod_thresholds, canary_thresholds):
        """Canary FAIL thresholds should be at least as permissive as production."""
        # For "lower is worse" metrics (spearman_rho, overlap_pct), canary <= prod
        assert canary_thresholds.fail_rank_spearman_rho <= prod_thresholds.fail_rank_spearman_rho
        assert canary_thresholds.fail_top20_overlap_pct <= prod_thresholds.fail_top20_overlap_pct
        assert canary_thresholds.fail_top60_overlap_pct <= prod_thresholds.fail_top60_overlap_pct
        # For "higher is worse" metrics (change count), canary >= prod
        assert canary_thresholds.fail_eligibility_change_count >= prod_thresholds.fail_eligibility_change_count

    def test_canary_warn_thresholds_looser(self, prod_thresholds, canary_thresholds):
        """Canary WARN thresholds should be at least as permissive as production."""
        assert canary_thresholds.warn_rank_spearman_rho <= prod_thresholds.warn_rank_spearman_rho
        assert canary_thresholds.warn_top20_overlap_pct <= prod_thresholds.warn_top20_overlap_pct
        assert canary_thresholds.warn_top60_overlap_pct <= prod_thresholds.warn_top60_overlap_pct


class TestCanaryExitCode:
    """Verify canary exit codes."""

    def test_exit_code_valid_range(self):
        """Main should return 0 (INFO), 1 (BLOCK), or 2 (WARN)."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            # Point to non-existent thresholds — falls back to defaults
            # With no matching archives/fixtures, all dates SKIP → INFO → exit 0
            rc = main(
                [
                    "--thresholds",
                    str(Path(tmp) / "nonexistent.json"),
                    "--ruleset",
                    str(Path(tmp) / "nonexistent_ruleset.json"),
                ]
            )
            assert rc in (0, 1, 2), f"Canary exit code must be 0, 1, or 2, got {rc}"


class TestCanaryPolicy:
    """Verify CanaryPolicy loading and defaults."""

    def test_default(self):
        p = CanaryPolicy.default()
        assert p.structural_block_enabled is True
        assert p.statistical_warn_enabled is True
        assert p.consecutive_warn_to_block == 0
        assert p.ratchet_after_n_runs == 0

    def test_from_json(self, tmp_path):
        path = tmp_path / "policy.json"
        path.write_text(
            json.dumps(
                {
                    "schema": "canary_policy.v1",
                    "structural_block_enabled": False,
                    "statistical_warn_enabled": True,
                    "consecutive_warn_to_block": 5,
                    "ratchet_after_n_runs": 10,
                }
            )
        )
        p = CanaryPolicy.from_json(path)
        assert p.structural_block_enabled is False
        assert p.consecutive_warn_to_block == 5
        assert p.ratchet_after_n_runs == 10

    def test_from_json_ignores_unknown_keys(self, tmp_path):
        path = tmp_path / "policy.json"
        path.write_text(
            json.dumps(
                {
                    "schema": "canary_policy.v1",
                    "structural_block_enabled": True,
                    "unknown_future_field": 42,
                }
            )
        )
        p = CanaryPolicy.from_json(path)
        assert p.structural_block_enabled is True
        assert not hasattr(p, "unknown_future_field")
