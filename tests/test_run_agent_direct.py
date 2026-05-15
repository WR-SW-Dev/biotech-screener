"""Tests for tools/run_agent_direct.py."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


@pytest.fixture
def direct_mod(tmp_path, monkeypatch):
    import tools.run_agent_direct as mod

    mod = importlib.reload(mod)
    monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)
    return mod


def test_main_returns_nonzero_when_agent_run_errors(direct_mod, tmp_path, monkeypatch):
    """Cron callers must see agent/API failure as process failure."""
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_agent_direct.py",
            "--agent",
            "sentinel",
            "--message",
            "DAILY",
            "--log-dir",
            str(tmp_path / "logs"),
        ],
    )
    monkeypatch.setattr(direct_mod, "resolve_model", lambda agent, default: default)
    monkeypatch.setattr(
        direct_mod,
        "run_agent",
        lambda agent, message, model, max_tokens: {"agent": agent, "status": "error", "error": "boom"},
    )

    rc = direct_mod.main()

    assert rc == 1
    logs = list((tmp_path / "logs").glob("sentinel_*.json"))
    assert len(logs) == 1
    assert json.loads(logs[0].read_text())["status"] == "error"


def test_log_filename_is_unique_for_same_second_reruns(direct_mod, tmp_path, monkeypatch):
    """Rapid reruns should not overwrite direct-agent logs."""
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_agent_direct.py",
            "--agent",
            "sentinel",
            "--message",
            "DAILY",
            "--log-dir",
            str(tmp_path / "logs"),
        ],
    )
    monkeypatch.setattr(direct_mod, "resolve_model", lambda agent, default: default)
    monkeypatch.setattr(
        direct_mod,
        "run_agent",
        lambda agent, message, model, max_tokens: {
            "agent": agent,
            "status": "success",
            "response": "HEARTBEAT_OK",
            "usage": {"input_tokens": 1, "output_tokens": 1},
        },
    )

    assert direct_mod.main() == 0
    assert direct_mod.main() == 0

    logs = list((tmp_path / "logs").glob("sentinel_*.json"))
    assert len(logs) == 2
    assert logs[0].name != logs[1].name


def test_preflight_blocks_scoped_agent(direct_mod, tmp_path, monkeypatch, capsys):
    """Preflight should block agent execution if scope keyword matches not_allowed."""
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_agent_direct.py",
            "--agent",
            "fleet_steward",
            "--message",
            "TEST",
            "--log-dir",
            str(tmp_path / "logs"),
        ],
    )
    monkeypatch.setattr(direct_mod, "resolve_model", lambda agent, default: default)

    # Mock preflight to return a report with blocked item
    blocking_report = {
        "timestamp": "2026-05-15T16:00:00Z",
        "current_branch_state": "on main, clean",
        "latest_snapshot": "2026-05-15, QA PASS",
        "git_head": "abc1234 test commit",
        "blocked_specs": ["none"],
        "contradictions": [],
        "active_quarantine_freeze": ["13F cohort quarantine: ACTIVE"],
        "allowed_next_action": "Monitor 13F ingest",
        "not_allowed": [
            "Ranker/selector/sizing changes (frozen during cohort quarantine)",
            "Spec 089 KG implementation",
        ],
    }
    monkeypatch.setattr(direct_mod, "run_preflight", lambda agent: blocking_report)

    rc = direct_mod.main()

    assert rc == 1
    captured = capsys.readouterr()
    assert "[PREFLIGHT BLOCKED]" in captured.err
    assert "fleet_steward" in captured.err
    assert "Ranker/selector/sizing" in captured.err


def test_preflight_warns_but_proceeds_on_contradiction(direct_mod, tmp_path, monkeypatch, capsys):
    """Preflight should warn on contradictions but not block execution."""
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_agent_direct.py",
            "--agent",
            "ops",
            "--message",
            "TEST",
            "--log-dir",
            str(tmp_path / "logs"),
        ],
    )
    monkeypatch.setattr(direct_mod, "resolve_model", lambda agent, default: default)

    # Mock preflight with contradictions but no blocking items
    warning_report = {
        "timestamp": "2026-05-15T16:00:00Z",
        "current_branch_state": "on main, clean",
        "latest_snapshot": "2026-05-15, QA PASS",
        "git_head": "abc1234 test commit",
        "blocked_specs": ["none"],
        "contradictions": ["inst_delta_z carried but cohort incomplete"],
        "active_quarantine_freeze": ["13F cohort quarantine: ACTIVE"],
        "allowed_next_action": "Monitor and observe",
        "not_allowed": ["Ranker changes (frozen)"],
    }
    monkeypatch.setattr(direct_mod, "run_preflight", lambda agent: warning_report)
    monkeypatch.setattr(
        direct_mod,
        "run_agent",
        lambda agent, message, model, max_tokens: {
            "agent": agent,
            "status": "success",
            "response": "HEARTBEAT_OK",
            "usage": {"input_tokens": 1, "output_tokens": 1},
        },
    )

    rc = direct_mod.main()

    assert rc == 0
    captured = capsys.readouterr()
    assert "[PREFLIGHT_WARN] contradiction:" in captured.err
    assert "inst_delta_z" in captured.err


def test_preflight_unavailable_is_non_blocking(direct_mod, tmp_path, monkeypatch):
    """If preflight is unavailable, agent should still run (non-blocking)."""
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_agent_direct.py",
            "--agent",
            "sentinel",
            "--message",
            "TEST",
            "--log-dir",
            str(tmp_path / "logs"),
        ],
    )
    monkeypatch.setattr(direct_mod, "resolve_model", lambda agent, default: default)
    monkeypatch.setattr(direct_mod, "run_preflight", lambda agent: None)  # Preflight unavailable
    monkeypatch.setattr(
        direct_mod,
        "run_agent",
        lambda agent, message, model, max_tokens: {
            "agent": agent,
            "status": "success",
            "response": "HEARTBEAT_OK",
            "usage": {"input_tokens": 1, "output_tokens": 1},
        },
    )

    rc = direct_mod.main()

    assert rc == 0
    logs = list((tmp_path / "logs").glob("sentinel_*.json"))
    assert len(logs) == 1
    log_content = json.loads(logs[0].read_text())
    assert log_content["status"] == "success"
    assert "preflight" not in log_content  # Preflight not in log if None
