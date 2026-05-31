"""Tests for tools/sync_hermes_skills.py metadata."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from tools.sync_hermes_skills import (  # noqa: E402
    SOURCE_AUTHORITY_HERMES_AUTHORITATIVE,
    SOURCE_AUTHORITY_HERMES_NATIVE,
    source_authority_for,
)


def test_source_authority_for_cursor_skill():
    assert source_authority_for("screener-ops", "screener-ops.md") == "skills/screener_ops/SKILL.md"


def test_source_authority_for_reference():
    assert source_authority_for("excel-xlsx", "excel-xlsx.md") == "skills/excel-xlsx/REFERENCE.md"


def test_source_authority_for_hermes_native():
    assert source_authority_for("town-operator-bridge", "town-operator-bridge.md") == SOURCE_AUTHORITY_HERMES_NATIVE


def test_source_authority_for_memory_steward():
    assert source_authority_for("memory-steward", "memory-steward.md") == SOURCE_AUTHORITY_HERMES_AUTHORITATIVE


def test_meta_json_has_source_authority_on_all_skills():
    meta = json.loads((REPO / "docs/hermes_skills/_meta.json").read_text())
    skills = meta["skills"]
    assert skills
    missing = [k for k, v in skills.items() if not v.get("source_authority")]
    assert not missing, f"missing source_authority: {missing}"
    assert "source_authority_legend" in meta
