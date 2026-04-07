"""Tests for common.startup_preflight module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """Create a minimal valid data directory."""
    d = tmp_path / "data"
    d.mkdir()
    (d / "universe.json").write_text(json.dumps([{"ticker": "ACME"}]))
    (d / "financial_records.json").write_text(json.dumps([{"ticker": "ACME"}]))
    return d


class TestPreflightResult:
    def test_ok_when_no_hard_errors(self):
        from common.startup_preflight import PreflightResult

        r = PreflightResult(hard=[], soft=["minor warning"])
        assert r.ok is True

    def test_not_ok_when_hard_errors(self):
        from common.startup_preflight import PreflightResult

        r = PreflightResult(hard=["missing file"], soft=[])
        assert r.ok is False

    def test_summary_includes_all(self):
        from common.startup_preflight import PreflightResult

        r = PreflightResult(hard=["err1"], soft=["warn1"])
        s = r.summary()
        assert "err1" in s
        assert "warn1" in s


class TestDataFileChecks:
    def test_passes_with_valid_dir(self, data_dir: Path):
        from common.startup_preflight import run_preflight

        result = run_preflight(data_dir, check_env=False, check_files=True)
        assert result.ok

    def test_fails_on_missing_dir(self, tmp_path: Path):
        from common.startup_preflight import run_preflight

        result = run_preflight(tmp_path / "nonexistent", check_env=False, check_files=True)
        assert not result.ok
        assert any("does not exist" in h for h in result.hard)

    def test_fails_on_missing_universe(self, data_dir: Path):
        from common.startup_preflight import run_preflight

        (data_dir / "universe.json").unlink()
        result = run_preflight(data_dir, check_env=False, check_files=True)
        assert not result.ok
        assert any("universe.json" in h for h in result.hard)

    def test_fails_on_empty_file(self, data_dir: Path):
        from common.startup_preflight import run_preflight

        (data_dir / "universe.json").write_text("")
        result = run_preflight(data_dir, check_env=False, check_files=True)
        assert not result.ok
        assert any("empty" in h for h in result.hard)

    def test_warns_on_missing_optional(self, data_dir: Path):
        from common.startup_preflight import run_preflight

        result = run_preflight(data_dir, check_env=False, check_files=True)
        # Optional files like trial_records.json are missing → soft warnings
        assert any("trial_records.json" in s for s in result.soft)


class TestEnvChecks:
    def test_warns_on_missing_env_vars(self, data_dir: Path, monkeypatch):
        from common.startup_preflight import run_preflight

        # Clear all checked env vars
        for var in ["FRED_API_KEY", "MD_AUTH_TOKEN", "XAI_API_KEY"]:
            monkeypatch.delenv(var, raising=False)

        result = run_preflight(data_dir, check_env=True, check_files=False)
        # All env vars are soft requirements currently
        assert result.ok
        assert len(result.soft) > 0

    def test_no_warnings_when_env_set(self, data_dir: Path, monkeypatch):
        from common.startup_preflight import _ENV_SCHEMA, run_preflight

        for var_name, _, _ in _ENV_SCHEMA:
            monkeypatch.setenv(var_name, "test_value")

        result = run_preflight(data_dir, check_env=True, check_files=False)
        # No env-related warnings
        env_warnings = [s for s in result.soft if "ENV missing" in s]
        assert len(env_warnings) == 0
