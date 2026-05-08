"""Tests for agents/ops_supervisor/supervisor.py."""

from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUPERVISOR_PATH = REPO / "agents" / "ops_supervisor" / "supervisor.py"


def _load_supervisor():
    spec = importlib.util.spec_from_file_location("ops_supervisor_module", SUPERVISOR_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_classify_anomaly_treats_changed_text_as_new_unknown():
    """Same agent/status but different anomaly text should not be carried."""
    mod = _load_supervisor()
    prior = [
        {
            "agent": "qa",
            "raw_status": "WARN",
            "raw_text": "WARN: old schema gap",
            "classification": "carried",
        }
    ]
    current = {"agent": "qa", "raw_status": "WARN", "raw_text": "WARN: new row-count drift"}

    result = mod.classify_anomaly(current, date.fromisoformat("2026-05-08"), prior, {}, None)

    assert result["classification"] == "new"
    assert result["supervisor_severity"] == "ORANGE"
