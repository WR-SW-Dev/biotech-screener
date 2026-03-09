"""Tests for pre-trade ruleset_active gate (check_ruleset_active)."""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.pre_trade_check import _get_manifest_active_id, check_ruleset_active


def _write_manifest(tmp_path, active_id="bebe73f8", extra_entries=None):
    """Write a minimal manifest.json with one active entry."""
    entries = [
        {
            "id": active_id,
            "file": "test.json",
            "status": "active",
        }
    ]
    if extra_entries:
        entries.extend(extra_entries)
    manifest = {"schema_version": 1, "rulesets": entries}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def _write_snap_metadata(snap_dir, ruleset_id="bebe73f8"):
    """Write a minimal metadata.json in the snapshot directory."""
    snap_dir.mkdir(parents=True, exist_ok=True)
    meta = {"ruleset_id": ruleset_id, "as_of_date": "2026-03-08"}
    (snap_dir / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    return snap_dir


class TestGetManifestActiveId:
    def test_returns_active_id(self, tmp_path):
        manifest_path = _write_manifest(tmp_path, "abc12345")
        assert _get_manifest_active_id(manifest_path) == "abc12345"

    def test_returns_none_when_no_active(self, tmp_path):
        manifest = {"schema_version": 1, "rulesets": [{"id": "x", "status": "retired"}]}
        path = tmp_path / "manifest.json"
        path.write_text(json.dumps(manifest))
        assert _get_manifest_active_id(path) is None

    def test_returns_none_when_missing(self, tmp_path):
        assert _get_manifest_active_id(tmp_path / "nonexistent.json") is None


class TestCheckRulesetActive:
    def test_matching_id_passes(self, tmp_path):
        manifest_path = _write_manifest(tmp_path, "bebe73f8")
        snap_dir = _write_snap_metadata(tmp_path / "snap", "bebe73f8")
        result = check_ruleset_active(snap_dir, manifest_path=manifest_path)
        assert result.status == "PASS"

    def test_mismatched_id_fails(self, tmp_path):
        manifest_path = _write_manifest(tmp_path, "bebe73f8")
        snap_dir = _write_snap_metadata(tmp_path / "snap", "e966af9d")
        result = check_ruleset_active(snap_dir, manifest_path=manifest_path)
        assert result.status == "FAIL"
        assert "e966af9d" in result.detail
        assert "bebe73f8" in result.detail

    def test_mismatched_id_relaxed_warns(self, tmp_path):
        manifest_path = _write_manifest(tmp_path, "bebe73f8")
        snap_dir = _write_snap_metadata(tmp_path / "snap", "e966af9d")
        result = check_ruleset_active(snap_dir, relaxed=True, manifest_path=manifest_path)
        assert result.status == "WARN"
        assert "[RELAXED]" in result.detail

    def test_missing_metadata_fails(self, tmp_path):
        manifest_path = _write_manifest(tmp_path)
        snap_dir = tmp_path / "snap"
        snap_dir.mkdir()
        result = check_ruleset_active(snap_dir, manifest_path=manifest_path)
        assert result.status == "FAIL"
        assert "metadata.json" in result.detail

    def test_empty_ruleset_id_fails(self, tmp_path):
        manifest_path = _write_manifest(tmp_path)
        snap_dir = _write_snap_metadata(tmp_path / "snap", "")
        result = check_ruleset_active(snap_dir, manifest_path=manifest_path)
        assert result.status == "FAIL"
        assert "no ruleset_id" in result.detail

    def test_missing_manifest_warns(self, tmp_path):
        snap_dir = _write_snap_metadata(tmp_path / "snap", "bebe73f8")
        result = check_ruleset_active(snap_dir, manifest_path=tmp_path / "nonexistent.json")
        assert result.status == "WARN"
        assert "Cannot determine" in result.detail

    def test_can_trade_false_on_mismatch(self, tmp_path):
        """Integration: mismatched ruleset should cause can_trade=False."""
        manifest_path = _write_manifest(tmp_path, "bebe73f8")
        snap_dir = _write_snap_metadata(tmp_path / "snap", "e966af9d")
        result = check_ruleset_active(snap_dir, manifest_path=manifest_path)
        # Verify the check returns FAIL which would set can_trade=False
        assert result.status == "FAIL"

    def test_can_trade_true_on_relaxed_mismatch(self, tmp_path):
        """Integration: relaxed mismatch should allow can_trade=True (WARN not FAIL)."""
        manifest_path = _write_manifest(tmp_path, "bebe73f8")
        snap_dir = _write_snap_metadata(tmp_path / "snap", "e966af9d")
        result = check_ruleset_active(snap_dir, relaxed=True, manifest_path=manifest_path)
        assert result.status == "WARN"
