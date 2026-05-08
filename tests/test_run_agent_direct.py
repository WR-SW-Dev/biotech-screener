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
