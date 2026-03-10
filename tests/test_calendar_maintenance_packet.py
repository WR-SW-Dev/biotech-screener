"""Tests for the regulatory calendar maintenance packet builder.

Covers:
  1. build_suggested_edits — past-dated, missing disclosed, duplicates, freshness
  2. build_maintenance_packet — end-to-end with a temp calendar
  3. write_maintenance_packet — output files exist and contain expected sections
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.research.build_regulatory_calendar_maintenance_packet import (
    build_maintenance_packet,
    build_suggested_edits,
    write_maintenance_packet,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_calendar(tmp_path: Path, entries: list) -> Path:
    cal_path = tmp_path / "pdufa_dates.json"
    cal_path.write_text(json.dumps(entries))
    return cal_path


# ---------------------------------------------------------------------------
# 1. build_suggested_edits
# ---------------------------------------------------------------------------


class TestBuildSuggestedEdits:
    def test_past_dated_suggests_remove(self):
        audit = {
            "past_dated": [{"ticker": "XYZ", "pdufa_date": "2025-01-01"}],
            "missing_disclosed_at": [],
            "duplicates": [],
            "freshness": {"age_days": 5},
        }
        edits = build_suggested_edits(audit)
        assert len(edits) == 1
        assert edits[0]["action"] == "REMOVE"
        assert edits[0]["ticker"] == "XYZ"

    def test_missing_disclosed_suggests_add(self):
        audit = {
            "past_dated": [],
            "missing_disclosed_at": [{"ticker": "ABC", "pdufa_date": "2026-04-01", "days": 22}],
            "duplicates": [],
            "freshness": {"age_days": 5},
        }
        edits = build_suggested_edits(audit)
        assert len(edits) == 1
        assert edits[0]["action"] == "ADD_DISCLOSED_AT"

    def test_duplicates_suggest_dedup(self):
        audit = {
            "past_dated": [],
            "missing_disclosed_at": [],
            "duplicates": ["duplicate: ABC 2026-04-01 appears 2x"],
            "freshness": {"age_days": 5},
        }
        edits = build_suggested_edits(audit)
        assert len(edits) == 1
        assert edits[0]["action"] == "DEDUP"

    def test_stale_freshness_suggests_refresh(self):
        audit = {
            "past_dated": [],
            "missing_disclosed_at": [],
            "duplicates": [],
            "freshness": {"age_days": 45},
        }
        edits = build_suggested_edits(audit)
        assert len(edits) == 1
        assert edits[0]["action"] == "REFRESH"
        assert "45d" in edits[0]["reason"]

    def test_fresh_calendar_no_edits(self):
        audit = {
            "past_dated": [],
            "missing_disclosed_at": [],
            "duplicates": [],
            "freshness": {"age_days": 10},
        }
        edits = build_suggested_edits(audit)
        assert edits == []

    def test_multiple_issues(self):
        audit = {
            "past_dated": [{"ticker": "OLD", "pdufa_date": "2025-01-01"}],
            "missing_disclosed_at": [{"ticker": "NEW", "pdufa_date": "2026-04-01", "days": 22}],
            "duplicates": ["duplicate: DUP 2026-05-01 appears 2x"],
            "freshness": {"age_days": 60},
        }
        edits = build_suggested_edits(audit)
        actions = [e["action"] for e in edits]
        assert "REMOVE" in actions
        assert "ADD_DISCLOSED_AT" in actions
        assert "DEDUP" in actions
        assert "REFRESH" in actions


# ---------------------------------------------------------------------------
# 2. build_maintenance_packet — integration with temp calendar
# ---------------------------------------------------------------------------


class TestBuildMaintenancePacket:
    def test_healthy_calendar(self, tmp_path):
        entries = [
            {
                "ticker": "ACME",
                "pdufa_date": "2026-06-15",
                "event_type": "PDUFA",
                "source": "COMPANY_GUIDANCE",
                "confidence": "HIGH",
                "as_of_disclosed_at": "2026-03-01",
            }
        ]
        cal_path = _write_calendar(tmp_path, entries)
        packet = build_maintenance_packet("2026-03-10", cal_path)

        assert packet["raw_count"] == 1
        assert packet["n_suggested_edits"] == 0

    def test_past_dated_flagged(self, tmp_path):
        entries = [
            {
                "ticker": "OLD",
                "pdufa_date": "2025-12-01",
                "event_type": "PDUFA",
                "source": "COMPANY_GUIDANCE",
                "confidence": "HIGH",
                "as_of_disclosed_at": "2025-11-01",
            }
        ]
        cal_path = _write_calendar(tmp_path, entries)
        packet = build_maintenance_packet("2026-03-10", cal_path)

        assert len(packet["past_dated"]) == 1
        assert packet["n_suggested_edits"] >= 1
        actions = [e["action"] for e in packet["suggested_edits"]]
        assert "REMOVE" in actions


# ---------------------------------------------------------------------------
# 3. write_maintenance_packet — output format
# ---------------------------------------------------------------------------


class TestWriteMaintenancePacket:
    def test_output_files_created(self, tmp_path):
        packet = {
            "as_of_date": "2026-03-10",
            "raw_count": 5,
            "pit_eligible": 4,
            "all_normalized": 5,
            "freshness": {
                "newest_disclosed_at": "2026-03-01",
                "age_days": 9,
                "n_with_disclosed": 5,
                "n_total": 5,
            },
            "proximity": {"imminent": [], "near": [], "mid": [], "far": []},
            "past_dated": [],
            "missing_disclosed_at": [],
            "duplicates": [],
            "suggested_edits": [],
            "n_suggested_edits": 0,
        }
        out_dir = tmp_path / "out"
        md_path = write_maintenance_packet(packet, out_dir)

        assert md_path.exists()
        assert (out_dir / "MAINTENANCE_PACKET.json").exists()

    def test_md_contains_sections(self, tmp_path):
        packet = {
            "as_of_date": "2026-03-10",
            "raw_count": 2,
            "pit_eligible": 1,
            "all_normalized": 2,
            "freshness": {"newest_disclosed_at": "2026-03-01", "age_days": 9, "n_with_disclosed": 2, "n_total": 2},
            "proximity": {
                "imminent": [],
                "near": [
                    {
                        "ticker": "TST",
                        "pdufa_date": "2026-04-01",
                        "event_type": "PDUFA",
                        "days": 22,
                        "confidence": "HIGH",
                        "disclosed_at": "2026-03-01",
                    }
                ],
                "mid": [],
                "far": [],
            },
            "past_dated": [{"ticker": "OLD", "pdufa_date": "2025-01-01"}],
            "missing_disclosed_at": [],
            "duplicates": [],
            "suggested_edits": [
                {
                    "ticker": "OLD",
                    "pdufa_date": "2025-01-01",
                    "action": "REMOVE",
                    "reason": "pdufa_date is in the past",
                }
            ],
            "n_suggested_edits": 1,
        }
        out_dir = tmp_path / "out"
        md_path = write_maintenance_packet(packet, out_dir)
        md = md_path.read_text()

        assert "# Regulatory Calendar Maintenance Packet" in md
        assert "## Proximity Bands" in md
        assert "## Past-Dated Entries" in md
        assert "## Suggested Edits" in md
        assert "## Summary" in md
        assert "NEEDS_ATTENTION" in md

    def test_json_roundtrip(self, tmp_path):
        packet = {
            "as_of_date": "2026-03-10",
            "raw_count": 1,
            "pit_eligible": 1,
            "all_normalized": 1,
            "freshness": {},
            "proximity": {"imminent": [], "near": [], "mid": [], "far": []},
            "past_dated": [],
            "missing_disclosed_at": [],
            "duplicates": [],
            "suggested_edits": [],
            "n_suggested_edits": 0,
        }
        out_dir = tmp_path / "out"
        write_maintenance_packet(packet, out_dir)
        loaded = json.loads((out_dir / "MAINTENANCE_PACKET.json").read_text())
        assert loaded["as_of_date"] == "2026-03-10"
        assert loaded["raw_count"] == 1
