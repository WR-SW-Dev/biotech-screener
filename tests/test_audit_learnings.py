"""Tests for tools/audit_learnings.py."""

from __future__ import annotations

import json
from pathlib import Path

from tools.audit_learnings import build_report, parse_learnings

SAMPLE = """
# Learnings

## [LRN-20260601-001] test_pattern

**Status**: pending

### Summary
One.

### Metadata
- Pattern-Key: sample_pattern
- Recurrence-Count: 3
- Skill-Path: screener_ops
"""


def test_parse_learnings_extracts_metadata():
    entries = parse_learnings(SAMPLE)
    assert len(entries) == 1
    e = entries[0]
    assert e.lrn_id == "LRN-20260601-001"
    assert e.pattern_key == "sample_pattern"
    assert e.recurrence_count == 3
    assert e.skill_path == "screener_ops"
    assert e.status == "pending"


def test_build_report_finds_promotion_candidate():
    repo = Path(__file__).resolve().parent.parent
    report = build_report()
    assert report.lrn_total >= 10
    assert "memory.md" in report.tier_lines
    assert report.tier_lines["memory.md"]["lines"] <= 100
    # Real repo should have README after our add
    assert (repo / ".learnings" / "README.md").exists()


def test_build_report_json_roundtrip():
    report = build_report()
    payload = json.loads(json.dumps(report, default=lambda o: o.__dict__))
    assert "tier_lines" in payload
    assert "lrn_total" in payload
