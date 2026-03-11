"""Tests for the regulatory calendar maintenance packet builder.

Covers:
  1. build_suggested_edits — past-dated, missing disclosed, duplicates, downgrade_conf
  2. find_slip_leaders — imminent + large slip detection
  3. find_chronic_slip_sources — repeated large slip source×confidence
  4. build_maintenance_packet — end-to-end with a temp calendar + optional slips
  5. write_maintenance_packet — output files exist and contain expected sections
  6. load_slip_artifacts — artifact loading + lookback
"""

from __future__ import annotations

import csv as csv_mod
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.research.build_regulatory_calendar_maintenance_packet import (
    VALID_ACTIONS,
    build_maintenance_packet,
    build_suggested_edits,
    find_chronic_slip_sources,
    find_slip_leaders,
    load_slip_artifacts,
    write_maintenance_packet,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_calendar(tmp_path: Path, entries: list) -> Path:
    cal_path = tmp_path / "pdufa_dates.json"
    cal_path.write_text(json.dumps(entries))
    return cal_path


def _slip_row(
    ticker="ACME",
    family="REGULATORY",
    slip_days="20",
    imminent="1",
    large_slip="1",
    current_source="ANALYST_ESTIMATE",
    current_confidence="MED",
    prior_days="30",
    current_days="10",
    **kwargs,
):
    row = {
        "ticker": ticker,
        "family": family,
        "prior_days": prior_days,
        "current_days": current_days,
        "delta_days": "",
        "expected_days": "",
        "slip_days": slip_days,
        "prior_event_type": "",
        "current_event_type": "",
        "prior_source": "",
        "current_source": current_source,
        "prior_confidence": "",
        "current_confidence": current_confidence,
        "prior_mode": "",
        "current_mode": "",
        "prior_snapshot_date": "",
        "current_snapshot_date": "",
        "new_flag": "0",
        "dropped_flag": "0",
        "large_slip": large_slip,
        "imminent": imminent,
    }
    row.update(kwargs)
    return row


# ---------------------------------------------------------------------------
# 1. build_suggested_edits
# ---------------------------------------------------------------------------


class TestBuildSuggestedEdits:
    def test_past_dated_suggests_remove(self):
        audit = {
            "as_of_date": "2026-03-10",
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
            "as_of_date": "2026-03-10",
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
            "as_of_date": "2026-03-10",
            "past_dated": [],
            "missing_disclosed_at": [],
            "duplicates": ["duplicate: ABC 2026-04-01 appears 2x"],
            "freshness": {"age_days": 5},
        }
        edits = build_suggested_edits(audit)
        assert len(edits) == 1
        assert edits[0]["action"] == "DEDUP"

    def test_fresh_calendar_no_edits(self):
        audit = {
            "as_of_date": "2026-03-10",
            "past_dated": [],
            "missing_disclosed_at": [],
            "duplicates": [],
            "freshness": {"age_days": 10},
        }
        edits = build_suggested_edits(audit)
        assert edits == []

    def test_multiple_issues(self):
        audit = {
            "as_of_date": "2026-03-10",
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

    def test_deterministic_ordering(self):
        """Edits ordered: REMOVE > ADD_DISCLOSED_AT > DEDUP > DOWNGRADE_CONF."""
        audit = {
            "as_of_date": "2026-03-10",
            "past_dated": [{"ticker": "OLD", "pdufa_date": "2026-01-01"}],
            "missing_disclosed_at": [{"ticker": "MISS", "pdufa_date": "2026-04-01", "days": 22}],
            "duplicates": ["duplicate: ('DUP', '2026-05-01', 'PDUFA')"],
        }
        slip_data = {
            "slip_leaders": [],
            "chronic_slip_sources": [
                {
                    "source": "ANALYST_ESTIMATE",
                    "confidence": "MED",
                    "total_slips": 5,
                    "large_slips": 3,
                    "mean_abs_slip": 22.0,
                    "tickers": ["CHRON"],
                }
            ],
        }
        edits = build_suggested_edits(audit, slip_data)
        actions = [e["action"] for e in edits]
        assert actions == ["REMOVE", "ADD_DISCLOSED_AT", "DEDUP", "DOWNGRADE_CONF"]

    def test_all_actions_valid(self):
        audit = {
            "as_of_date": "2026-03-10",
            "past_dated": [{"ticker": "X", "pdufa_date": "2026-01-01"}],
            "missing_disclosed_at": [],
            "duplicates": [],
        }
        edits = build_suggested_edits(audit)
        for e in edits:
            assert e["action"] in VALID_ACTIONS

    def test_edit_has_required_fields(self):
        audit = {
            "as_of_date": "2026-03-10",
            "past_dated": [{"ticker": "X", "pdufa_date": "2026-01-01"}],
            "missing_disclosed_at": [],
            "duplicates": [],
        }
        edits = build_suggested_edits(audit)
        for e in edits:
            assert "ticker" in e
            assert "pdufa_date" in e
            assert "action" in e
            assert "reason" in e
            assert "old_fields" in e
            assert "proposed_fields" in e
            assert "evidence" in e

    def test_slip_leader_low_conf_removed(self):
        audit = {
            "as_of_date": "2026-03-10",
            "past_dated": [],
            "missing_disclosed_at": [],
            "duplicates": [],
        }
        slip_data = {
            "slip_leaders": [
                {
                    "ticker": "LOWQ",
                    "current_confidence": "LOW",
                    "slip_days": "25",
                    "current_days": "5",
                    "prior_days": "30",
                    "current_source": "ANALYST_ESTIMATE",
                }
            ],
            "chronic_slip_sources": [],
        }
        edits = build_suggested_edits(audit, slip_data)
        assert len(edits) == 1
        assert edits[0]["action"] == "REMOVE"
        assert edits[0]["ticker"] == "LOWQ"

    def test_downgrade_conf_includes_evidence(self):
        audit = {
            "as_of_date": "2026-03-10",
            "past_dated": [],
            "missing_disclosed_at": [],
            "duplicates": [],
        }
        slip_data = {
            "slip_leaders": [],
            "chronic_slip_sources": [
                {
                    "source": "ANALYST_ESTIMATE",
                    "confidence": "MED",
                    "total_slips": 4,
                    "large_slips": 3,
                    "mean_abs_slip": 18.5,
                    "tickers": ["ABCD"],
                }
            ],
        }
        edits = build_suggested_edits(audit, slip_data)
        downgrade = [e for e in edits if e["action"] == "DOWNGRADE_CONF"]
        assert len(downgrade) == 1
        assert downgrade[0]["evidence"]["large_slips"] == 3
        assert downgrade[0]["proposed_fields"]["confidence"] == "LOW"


# ---------------------------------------------------------------------------
# 2. find_slip_leaders
# ---------------------------------------------------------------------------


class TestFindSlipLeaders:
    def test_detects_imminent_large_slip(self):
        slips = [
            _slip_row(ticker="AAA", imminent="1", large_slip="1"),
            _slip_row(ticker="BBB", imminent="1", large_slip="0"),
            _slip_row(ticker="CCC", imminent="0", large_slip="1"),
        ]
        leaders = find_slip_leaders(slips)
        assert len(leaders) == 1
        assert leaders[0]["ticker"] == "AAA"

    def test_empty_slips(self):
        assert find_slip_leaders([]) == []

    def test_sorted_by_abs_slip(self):
        slips = [
            _slip_row(ticker="A", slip_days="10", imminent="1", large_slip="1"),
            _slip_row(ticker="B", slip_days="-25", imminent="1", large_slip="1"),
            _slip_row(ticker="C", slip_days="15", imminent="1", large_slip="1"),
        ]
        leaders = find_slip_leaders(slips)
        tickers = [ld["ticker"] for ld in leaders]
        assert tickers == ["B", "C", "A"]


# ---------------------------------------------------------------------------
# 3. find_chronic_slip_sources
# ---------------------------------------------------------------------------


class TestFindChronicSlipSources:
    def test_detects_chronic_source(self):
        slips = [
            _slip_row(ticker="A", slip_days="20", large_slip="1"),
            _slip_row(ticker="B", slip_days="18", large_slip="1"),
        ]
        chronic = find_chronic_slip_sources(slips)
        assert len(chronic) == 1
        assert chronic[0]["source"] == "ANALYST_ESTIMATE"
        assert chronic[0]["large_slips"] == 2

    def test_ignores_non_chronic(self):
        slips = [
            _slip_row(ticker="A", slip_days="20", large_slip="1"),
        ]
        chronic = find_chronic_slip_sources(slips)
        assert chronic == []

    def test_empty_slips(self):
        assert find_chronic_slip_sources([]) == []

    def test_tickers_collected(self):
        slips = [
            _slip_row(ticker="X", slip_days="20", large_slip="1"),
            _slip_row(ticker="Y", slip_days="30", large_slip="1"),
            _slip_row(
                ticker="Z", slip_days="5", large_slip="0", current_source="COMPANY_GUIDANCE", current_confidence="HIGH"
            ),
        ]
        chronic = find_chronic_slip_sources(slips)
        assert len(chronic) == 1
        assert sorted(chronic[0]["tickers"]) == ["X", "Y"]


# ---------------------------------------------------------------------------
# 4. load_slip_artifacts
# ---------------------------------------------------------------------------


class TestLoadSlipArtifacts:
    def test_loads_from_exact_date(self, tmp_path):
        slip_dir = tmp_path / "2026-03-10"
        slip_dir.mkdir()
        (slip_dir / "slips.csv").write_text("ticker,slip_days\nACME,5\n")
        (slip_dir / "slip_summary.json").write_text('{"total_tracked": 1}')

        result = load_slip_artifacts(tmp_path, "2026-03-10")
        assert result["slip_date"] == "2026-03-10"
        assert len(result["slips"]) == 1
        assert result["summary"]["total_tracked"] == 1

    def test_lookback_finds_earlier_date(self, tmp_path):
        slip_dir = tmp_path / "2026-03-08"
        slip_dir.mkdir()
        (slip_dir / "slips.csv").write_text("ticker,slip_days\nFOO,3\n")

        result = load_slip_artifacts(tmp_path, "2026-03-10", lookback_days=7)
        assert result["slip_date"] == "2026-03-08"

    def test_returns_empty_if_nothing_found(self, tmp_path):
        result = load_slip_artifacts(tmp_path, "2026-03-10")
        assert result == {}


# ---------------------------------------------------------------------------
# 5. build_maintenance_packet — integration with temp calendar
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

    def test_with_slip_data(self, tmp_path):
        cal_path = _write_calendar(
            tmp_path,
            [
                {
                    "ticker": "ACME",
                    "pdufa_date": "2026-06-15",
                    "event_type": "PDUFA",
                    "source": "COMPANY_GUIDANCE",
                    "confidence": "HIGH",
                    "as_of_disclosed_at": "2026-03-01",
                }
            ],
        )

        # Write slip artifacts
        slip_dir = tmp_path / "slips" / "2026-03-10"
        slip_dir.mkdir(parents=True)
        csv_path = slip_dir / "slips.csv"
        with open(csv_path, "w", newline="") as f:
            w = csv_mod.DictWriter(f, fieldnames=_slip_row().keys())
            w.writeheader()
            w.writerow(_slip_row(ticker="SLP1"))
            w.writerow(_slip_row(ticker="SLP2"))

        packet = build_maintenance_packet(
            "2026-03-10",
            calendar_path=cal_path,
            slips_root=tmp_path / "slips",
        )
        assert "slip_data" in packet
        assert len(packet["slip_data"]["slip_leaders"]) == 2


# ---------------------------------------------------------------------------
# 6. write_maintenance_packet — output format
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
                    "old_fields": {},
                    "proposed_fields": {},
                    "evidence": {},
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

    def test_slip_leaders_in_md(self, tmp_path):
        packet = {
            "as_of_date": "2026-03-10",
            "raw_count": 2,
            "pit_eligible": 2,
            "all_normalized": 2,
            "freshness": {},
            "proximity": {},
            "past_dated": [],
            "missing_disclosed_at": [],
            "duplicates": [],
            "suggested_edits": [],
            "n_suggested_edits": 0,
            "slip_data": {
                "slip_date": "2026-03-10",
                "slip_leaders": [
                    {
                        "ticker": "SLIP",
                        "family": "REGULATORY",
                        "current_days": "5",
                        "slip_days": "20",
                        "prior_days": "30",
                        "current_source": "ANALYST_ESTIMATE",
                        "current_confidence": "MED",
                    }
                ],
                "chronic_slip_sources": [],
            },
        }
        out_dir = tmp_path / "out"
        md_path = write_maintenance_packet(packet, out_dir)
        md = md_path.read_text()
        assert "Slip Leaders" in md
        assert "SLIP" in md

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
