"""Tests for tools/sync_hermes_skills.py metadata."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from tools.sync_hermes_skills import (  # noqa: E402
    REFERENCE_MAP,
    SKILL_MAP,
    SOURCE_AUTHORITY_HERMES_AUTHORITATIVE,
    SOURCE_AUTHORITY_HERMES_NATIVE,
    SOURCE_AUTHORITY_HERMES_SKILL,
    all_sync_pairs,
    source_authority_for,
)


def test_source_authority_for_cursor_skill():
    assert source_authority_for("screener-ops", "screener-ops.md") == "skills/screener_ops/SKILL.md"


def test_source_authority_for_reference():
    assert source_authority_for("excel-xlsx", "excel-xlsx.md") == "skills/excel-xlsx/REFERENCE.md"


def test_source_authority_for_hermes_native():
    assert (
        source_authority_for("governance-spec-enforcement", "governance-spec-enforcement.md")
        == SOURCE_AUTHORITY_HERMES_NATIVE
    )


def test_source_authority_for_hermes_skill():
    assert source_authority_for("town-operator-bridge", "town-operator-bridge.md") == SOURCE_AUTHORITY_HERMES_SKILL


def test_source_authority_for_memory_steward():
    assert source_authority_for("memory-steward", "memory-steward.md") == SOURCE_AUTHORITY_HERMES_AUTHORITATIVE


def test_all_sync_pairs_covers_every_map_entry():
    """Regression: a key in both SKILL_MAP and REFERENCE_MAP must yield both
    pairs. The old {**SKILL_MAP, **REFERENCE_MAP} merge silently dropped the
    SKILL_MAP entry on collision (e.g. self-improving), leaving its mirror
    un-synced."""
    pairs = all_sync_pairs()
    assert len(pairs) == len(SKILL_MAP) + len(REFERENCE_MAP)
    for k, v in SKILL_MAP.items():
        assert (k, v) in pairs
    for k, v in REFERENCE_MAP.items():
        assert (k, v) in pairs


def test_dual_mapped_skill_keeps_both_mirrors():
    pairs = all_sync_pairs()
    assert ("self-improving", "self-improving.md") in pairs
    assert ("self-improving", "self-improving-reference.md") in pairs


def test_meta_json_has_source_authority_on_all_skills():
    meta = json.loads((REPO / "docs/hermes_skills/_meta.json").read_text())
    skills = meta["skills"]
    assert skills
    missing = [k for k, v in skills.items() if not v.get("source_authority")]
    assert not missing, f"missing source_authority: {missing}"
    assert "source_authority_legend" in meta
