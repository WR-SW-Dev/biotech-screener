"""Tests for ruleset governance gate in run_daily_production."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from tools.run_daily_production import check_ruleset_governance


def _write_manifest(tmp_path: Path, entries: list[dict]) -> Path:
    manifest = {"schema_version": 1, "rulesets": entries}
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps(manifest))
    return p


def _write_ruleset(tmp_path: Path, filename: str = "active.json") -> Path:
    """Write a minimal ruleset JSON and return the path."""
    p = tmp_path / filename
    p.write_text(json.dumps({"drawdown_gate": -0.40}, sort_keys=True))
    return p


def _ruleset_id_for(path: Path) -> str:
    """Compute ruleset ID the same way DecisionRuleset.from_json does."""
    import hashlib

    d = json.loads(path.read_text())
    return hashlib.sha256(json.dumps(d, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:8]


class TestRulesetGovernanceGate:
    def test_active_ruleset_passes(self, tmp_path):
        rs_path = _write_ruleset(tmp_path)
        rid = _ruleset_id_for(rs_path)
        manifest = _write_manifest(
            tmp_path,
            [
                {"id": rid, "file": "active.json", "status": "active"},
            ],
        )
        result = check_ruleset_governance(rs_path, manifest)
        assert result.status == "PASS"

    def test_candidate_without_flag_fails(self, tmp_path):
        rs_path = _write_ruleset(tmp_path)
        rid = _ruleset_id_for(rs_path)
        manifest = _write_manifest(
            tmp_path,
            [
                {"id": rid, "file": "active.json", "status": "candidate"},
            ],
        )
        result = check_ruleset_governance(rs_path, manifest, allow_candidate=False)
        assert result.status == "FAIL"
        assert "candidate" in result.detail.lower()

    def test_candidate_with_flag_warns(self, tmp_path):
        rs_path = _write_ruleset(tmp_path)
        rid = _ruleset_id_for(rs_path)
        manifest = _write_manifest(
            tmp_path,
            [
                {"id": rid, "file": "active.json", "status": "candidate"},
            ],
        )
        result = check_ruleset_governance(rs_path, manifest, allow_candidate=True)
        assert result.status == "WARN"
        assert "RELAXED_CANDIDATE" in result.detail

    def test_retired_ruleset_fails(self, tmp_path):
        rs_path = _write_ruleset(tmp_path)
        rid = _ruleset_id_for(rs_path)
        manifest = _write_manifest(
            tmp_path,
            [
                {"id": rid, "file": "active.json", "status": "retired"},
            ],
        )
        # Even with allow_candidate, retired should FAIL
        result = check_ruleset_governance(rs_path, manifest, allow_candidate=True)
        assert result.status == "FAIL"

    def test_missing_manifest_fails(self, tmp_path):
        rs_path = _write_ruleset(tmp_path)
        missing = tmp_path / "nonexistent.json"
        result = check_ruleset_governance(rs_path, missing)
        assert result.status == "FAIL"
        assert "manifest" in result.detail.lower()

    def test_unknown_ruleset_fails(self, tmp_path):
        rs_path = _write_ruleset(tmp_path)
        manifest = _write_manifest(
            tmp_path,
            [
                {"id": "aaaaaaaa", "file": "other.json", "status": "active"},
            ],
        )
        result = check_ruleset_governance(rs_path, manifest)
        assert result.status == "FAIL"
        assert "not found" in result.detail.lower()

    def test_governance_mode_stamp_strict(self, tmp_path):
        rs_path = _write_ruleset(tmp_path)
        rid = _ruleset_id_for(rs_path)
        manifest = _write_manifest(
            tmp_path,
            [
                {"id": rid, "file": "active.json", "status": "active"},
            ],
        )
        result = check_ruleset_governance(rs_path, manifest)
        assert result.value == "STRICT"

    def test_governance_mode_stamp_relaxed(self, tmp_path):
        rs_path = _write_ruleset(tmp_path)
        rid = _ruleset_id_for(rs_path)
        manifest = _write_manifest(
            tmp_path,
            [
                {"id": rid, "file": "active.json", "status": "candidate"},
            ],
        )
        result = check_ruleset_governance(rs_path, manifest, allow_candidate=True)
        assert result.value == "RELAXED_CANDIDATE"

    def test_pinned_id_fallback(self, tmp_path):
        """When no ruleset_path given, uses PHASE2_PINNED_RULESET_ID."""
        from run_screen import PHASE2_PINNED_RULESET_ID

        manifest = _write_manifest(
            tmp_path,
            [
                {"id": PHASE2_PINNED_RULESET_ID, "file": "active.json", "status": "active"},
            ],
        )
        result = check_ruleset_governance(None, manifest)
        assert result.status == "PASS"
