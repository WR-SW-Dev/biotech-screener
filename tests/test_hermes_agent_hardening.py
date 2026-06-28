#!/usr/bin/env python3
"""Tests for Hermes agent best-practice hardening.

Covers:
- hermes_path_guard.py: tier/path allow/block logic
- hermes_agent_health.py: registry load, row construction, fleet verdict
- Heartbeat standard: schema validation on existing heartbeat files
- Agent registry: permission_tier consistency (additive to test_agent_registry.py)
- Subagent files: required frontmatter fields present
"""

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = REPO_ROOT / "agents" / "AGENT_REGISTRY.json"
GOVERNANCE_DIR = REPO_ROOT / "artifacts" / "governance"
AGENTS_DIR = REPO_ROOT / ".claude" / "agents"

# ---------------------------------------------------------------------------
# hermes_path_guard tests
# ---------------------------------------------------------------------------

import sys

sys.path.insert(0, str(REPO_ROOT))

from tools.hermes_path_guard import AUTHORITY_TO_TIER, check_path, run_self_test


class TestPathGuard:
    """Verify path guard tier rules."""

    @pytest.mark.parametrize(
        "path,tier,expected",
        [
            # Always frozen — all tiers blocked
            ("ranker/weights.json", 0, False),
            ("ranker/weights.json", 4, False),
            ("selector/model.pkl", 0, False),
            ("data/snapshots/2026-06-26/screen.pkl", 0, False),
            ("data/snapshots_pit/2026-06-26/rankings.csv", 3, False),
            ("portfolio/positions.csv", 2, False),
            (".env", 0, False),
            (".github/workflows/ci.yml", 0, False),
            ("artifacts/generated/output.json", 0, False),
            ("production_data/raw.csv", 1, False),
            # Tier 0 allows
            ("artifacts/my_agent/output.json", 0, True),
            ("logs/my_agent_2026-06-26.log", 0, True),
            # Tier 0 blocks data/
            ("data/aact/snapshots/2026.json", 0, False),
            ("data/sec/filings/form4.json", 0, False),
            # Tier 1 allows proposals
            ("artifacts/ops/held_spec_ledger/2026-06-26.json", 1, True),
            ("artifacts/pending_specs/spec_099.json", 1, True),
            # Tier 2 allows shared artifacts
            ("artifacts/shared/report.json", 2, True),
            ("docs/hermes_skills/screener-ops.md", 2, True),
            # Tier 2 still blocks data/
            ("data/aact/snapshots/2026.json", 2, False),
            ("output/catalyst_ev/events.json", 2, False),
            # Tier 3 allows data/ (except snapshots)
            ("data/aact/snapshots/2026.json", 3, True),
            ("output/catalyst_ev/events.json", 3, True),
            # Tier 3 blocks specs and config
            ("specs/spec_099.md", 3, False),
            (".github/workflows/ci.yml", 3, False),
            ("CLAUDE.md", 3, False),
            # Tier 4 allows specs and CLAUDE.md
            ("specs/spec_099.md", 4, True),
            ("CLAUDE.md", 4, True),
        ],
    )
    def test_path_tier_rules(self, path, tier, expected):
        allowed, reason = check_path(path, tier)
        assert allowed == expected, f"path={path!r} tier={tier}: expected {expected}, got {allowed!r} ({reason})"

    def test_unknown_tier(self):
        allowed, reason = check_path("artifacts/foo.json", 99)
        assert not allowed
        assert "Unknown tier" in reason

    def test_authority_to_tier_complete(self):
        """All authority_level values in registry enum map to a tier."""
        registry = json.loads(REGISTRY_PATH.read_text())
        enum_values = registry.get("enums", {}).get("authority_level", [])
        for al in enum_values:
            assert al in AUTHORITY_TO_TIER, f"authority_level {al!r} not in AUTHORITY_TO_TIER"

    def test_self_test_passes(self):
        """The built-in self-test suite must pass cleanly."""
        rc = run_self_test()
        assert rc == 0, "hermes_path_guard.py --self-test failed"


# ---------------------------------------------------------------------------
# hermes_agent_health tests
# ---------------------------------------------------------------------------

from tools.hermes_agent_health import AgentRow, build_rows, fleet_verdict, load_registry, report_json, report_text


class TestAgentHealth:
    """Verify health board logic."""

    def test_load_registry(self):
        registry = load_registry()
        assert "agents" in registry
        assert len(registry["agents"]) > 0

    def test_build_rows_completes(self):
        registry = load_registry()
        rows = build_rows(registry)
        assert len(rows) > 0

    def test_fleet_verdict_type(self):
        registry = load_registry()
        rows = build_rows(registry)
        verdict = fleet_verdict(rows)
        assert verdict in ("GREEN", "AMBER", "RED")

    def test_report_text_contains_verdict(self):
        registry = load_registry()
        rows = build_rows(registry)
        text = report_text(rows, registry)
        assert "Fleet verdict" in text
        assert "Agent" in text

    def test_report_json_schema(self):
        registry = load_registry()
        rows = build_rows(registry)
        data = report_json(rows, registry)
        assert "fleet_verdict" in data
        assert "agents" in data
        assert "as_of" in data
        for agent in data["agents"]:
            assert "agent_id" in agent
            assert "health_status" in agent
            assert agent["health_status"] in ("GREEN", "AMBER", "RED", "SKIP", "UNKNOWN")

    def test_no_active_supervised_missing_health(self):
        """Every active+supervised agent should have a health_status (not blank)."""
        registry = load_registry()
        rows = build_rows(registry)
        for row in rows:
            assert row.health_status, f"{row.agent_id} has empty health_status"

    def test_skip_for_deprecated(self):
        """Deprecated agents must map to SKIP."""
        registry = load_registry()
        for agent_id, entry in registry["agents"].items():
            if entry.get("status") == "deprecated":
                row = AgentRow(
                    agent_id=agent_id,
                    role=entry.get("role", ""),
                    status="deprecated",
                    cadence=entry.get("cadence", "unknown"),
                    authority_level=entry.get("authority_level", "observe_only"),
                    supervised=False,
                    heartbeat=None,
                )
                assert row.health_status == "SKIP", f"{agent_id} deprecated but health_status={row.health_status}"


# ---------------------------------------------------------------------------
# Heartbeat schema tests
# ---------------------------------------------------------------------------

REQUIRED_HB_FIELDS = {"agent_id", "run_ts", "as_of_date", "status", "schema"}


class TestHeartbeatSchema:
    """Validate existing heartbeat files conform to the standard schema."""

    def _all_heartbeats(self):
        return list(GOVERNANCE_DIR.rglob("latest_heartbeat.json"))

    def test_heartbeat_files_exist(self):
        """At least one heartbeat file should exist (hermes-skill-sync-agent)."""
        hbs = self._all_heartbeats()
        assert len(hbs) > 0, "No latest_heartbeat.json files found under artifacts/governance/"

    @pytest.mark.parametrize("hb_path", list(GOVERNANCE_DIR.rglob("latest_heartbeat.json")))
    def test_heartbeat_required_fields(self, hb_path):
        data = json.loads(hb_path.read_text())
        missing = REQUIRED_HB_FIELDS - set(data.keys())
        assert not missing, f"{hb_path}: missing fields {missing}"

    @pytest.mark.parametrize("hb_path", list(GOVERNANCE_DIR.rglob("latest_heartbeat.json")))
    def test_heartbeat_status_valid(self, hb_path):
        data = json.loads(hb_path.read_text())
        valid = {"OK", "WARN", "FAIL", "ERROR", "SKIP", "DRIFT_WARNING", "DRIFT_CRITICAL", "DRIFT_INFO"}
        assert data["status"] in valid, f"{hb_path}: invalid status {data['status']!r}"

    @pytest.mark.parametrize("hb_path", list(GOVERNANCE_DIR.rglob("latest_heartbeat.json")))
    def test_heartbeat_run_ts_parseable(self, hb_path):
        from datetime import datetime

        data = json.loads(hb_path.read_text())
        ts = data.get("run_ts", "")
        dt = datetime.fromisoformat(ts)
        assert dt.year >= 2026, f"{hb_path}: run_ts year {dt.year} unexpected"


# ---------------------------------------------------------------------------
# Agent registry permission tier consistency
# ---------------------------------------------------------------------------


class TestRegistryPermissionTiers:
    """Additive checks on top of test_agent_registry.py."""

    def test_authority_level_enum_values(self):
        registry = json.loads(REGISTRY_PATH.read_text())
        allowed = set(registry.get("enums", {}).get("authority_level", []))
        for agent_id, entry in registry["agents"].items():
            al = entry.get("authority_level", "")
            assert al in allowed, f"{agent_id}: authority_level={al!r} not in enum"

    def test_permission_tier_consistent_when_present(self):
        """If permission_tier is present, it must match authority_level derivation."""
        registry = json.loads(REGISTRY_PATH.read_text())
        for agent_id, entry in registry["agents"].items():
            al = entry.get("authority_level", "")
            pt = entry.get("permission_tier")
            if pt is None:
                continue
            expected = AUTHORITY_TO_TIER.get(al)
            assert expected is not None, f"{agent_id}: unknown authority_level {al!r}"
            assert pt == expected, f"{agent_id}: permission_tier={pt} but authority_level={al!r} => expected {expected}"

    def test_supervised_agents_have_hermes_prefix_check(self):
        """Agents whose ID starts with 'hermes-' should be supervised."""
        registry = json.loads(REGISTRY_PATH.read_text())
        for agent_id, entry in registry["agents"].items():
            if not agent_id.startswith("hermes-"):
                continue
            status = entry.get("status", "active")
            if status in ("deprecated", "suppressed"):
                continue
            supervised = entry.get("supervised_by_orchestrator", False)
            assert supervised, f"{agent_id}: active hermes-* agent not supervised_by_orchestrator"


# ---------------------------------------------------------------------------
# Subagent file presence and frontmatter
# ---------------------------------------------------------------------------

REQUIRED_SUBAGENT_FRONTMATTER = {"name", "description", "tools", "model"}


def _parse_frontmatter(text: str) -> dict:
    """Extract YAML frontmatter fields (simple key: value parsing)."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    fm_text = text[3:end]
    result = {}
    for line in fm_text.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            result[k.strip()] = v.strip()
    return result


class TestSubagentFiles:
    """Verify .claude/agents/*.md files have required frontmatter."""

    @pytest.fixture(params=list(AGENTS_DIR.glob("*.md")))
    def agent_file(self, request):
        return request.param

    def test_frontmatter_present(self, agent_file):
        text = agent_file.read_text()
        assert text.startswith("---"), f"{agent_file.name}: missing frontmatter (must start with ---)"

    def test_required_frontmatter_fields(self, agent_file):
        text = agent_file.read_text()
        fm = _parse_frontmatter(text)
        missing = REQUIRED_SUBAGENT_FRONTMATTER - set(fm.keys())
        assert not missing, f"{agent_file.name}: missing frontmatter fields {missing}"

    def test_no_production_write_in_read_only_agents(self, agent_file):
        """Agents with read-only scope must include production path prohibition."""
        text = agent_file.read_text()
        if "read-only" in text.lower() or "read only" in text.lower():
            prohibited_phrases = [
                "do not write to production",
                "do not write to snapshots",
                "do not run git commit",
                "never write",
            ]
            found = any(p in text.lower() for p in prohibited_phrases)
            assert found, (
                f"{agent_file.name}: declares read-only scope but lacks explicit "
                f"production-write prohibition statement"
            )
