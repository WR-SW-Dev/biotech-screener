"""Tests for common/regulatory_coverage_telemetry.py."""

from __future__ import annotations

import json
from typing import Dict

import pytest

from common.regulatory_coverage_telemetry import (
    TELEMETRY_SCHEMA,
    build_coverage_breakdown,
    build_telemetry,
    compute_delta,
    extract_regulatory_flags,
    write_telemetry,
)


def _make_row(
    ticker: str = "ACME",
    eligible: str = "1",
    has_reg: str = "0",
    reg_days: str = "",
    reg_type: str = "",
    reg_conf: str = "",
) -> Dict[str, str]:
    return {
        "ticker": ticker,
        "eligible": eligible,
        "has_regulatory_upcoming_180d": has_reg,
        "regulatory_days": reg_days,
        "regulatory_event_type": reg_type,
        "regulatory_confidence": reg_conf,
    }


class TestExtractRegulatoryFlags:
    def test_basic_extraction(self):
        rows = [
            _make_row("A", has_reg="1", reg_days="30", reg_type="PDUFA"),
            _make_row("B", has_reg="0"),
            _make_row("C", has_reg="1", reg_days="90", reg_type="FDA_ADCOM"),
        ]
        n_elig, n_flagged, details = extract_regulatory_flags(rows)
        assert n_elig == 3
        assert n_flagged == 2
        assert details[0]["ticker"] == "A"  # sorted by days
        assert details[1]["ticker"] == "C"

    def test_ineligible_excluded(self):
        rows = [
            _make_row("A", eligible="0", has_reg="1", reg_days="30"),
            _make_row("B", eligible="1", has_reg="1", reg_days="60"),
        ]
        n_elig, n_flagged, _ = extract_regulatory_flags(rows)
        assert n_elig == 1
        assert n_flagged == 1

    def test_empty_rows(self):
        n_elig, n_flagged, details = extract_regulatory_flags([])
        assert n_elig == 0
        assert n_flagged == 0
        assert details == []


class TestBuildCoverageBreakdown:
    def test_by_type_and_bucket(self):
        flagged = [
            {"ticker": "A", "regulatory_days": "10", "regulatory_event_type": "PDUFA", "regulatory_confidence": "HIGH"},
            {"ticker": "B", "regulatory_days": "50", "regulatory_event_type": "PDUFA", "regulatory_confidence": "HIGH"},
            {
                "ticker": "C",
                "regulatory_days": "120",
                "regulatory_event_type": "FDA_ADCOM",
                "regulatory_confidence": "MED",
            },
        ]
        result = build_coverage_breakdown(flagged)
        assert result["by_event_type"] == {"PDUFA": 2, "FDA_ADCOM": 1}
        assert result["by_proximity_bucket"]["0_30d"] == 1
        assert result["by_proximity_bucket"]["31_90d"] == 1
        assert result["by_proximity_bucket"]["91_180d"] == 1


class TestComputeDelta:
    def test_basic(self):
        d = compute_delta({"A", "B", "C"}, {"B", "D"}, 100, 100)
        assert d["delta_count"] == 1
        assert sorted(d["added"]) == ["A", "C"]
        assert d["dropped"] == ["D"]
        assert d["current_pct"] == 3.0
        assert d["prior_pct"] == 2.0

    def test_no_change(self):
        d = compute_delta({"A", "B"}, {"A", "B"}, 50, 50)
        assert d["delta_count"] == 0
        assert d["added"] == []
        assert d["dropped"] == []


class TestBuildTelemetry:
    def test_basic_telemetry(self):
        rows = [
            _make_row("A", has_reg="1", reg_days="30", reg_type="PDUFA", reg_conf="HIGH"),
            _make_row("B"),
            _make_row("C"),
        ]
        tel = build_telemetry(rows, "2026-03-11")
        assert tel["schema"] == TELEMETRY_SCHEMA
        assert tel["n_eligible"] == 3
        assert tel["n_flagged"] == 1
        assert tel["coverage_pct"] == pytest.approx(33.3, abs=0.1)
        assert "A" in tel["flagged_tickers"]

    def test_delta_with_prior(self, tmp_path):
        # Create prior snapshot with telemetry
        prior_dir = tmp_path / "2026-03-04"
        prior_dir.mkdir()
        prior_tel = {
            "schema": TELEMETRY_SCHEMA,
            "flagged_tickers": ["A", "D"],
            "n_eligible": 3,
        }
        (prior_dir / "regulatory_coverage.json").write_text(json.dumps(prior_tel))

        rows = [
            _make_row("A", has_reg="1", reg_days="30", reg_type="PDUFA"),
            _make_row("B", has_reg="1", reg_days="60", reg_type="FDA_ADCOM"),
            _make_row("C"),
        ]
        tel = build_telemetry(rows, "2026-03-11", snapshots_dir=tmp_path)
        assert "delta" in tel
        assert sorted(tel["delta"]["added"]) == ["B"]
        assert tel["delta"]["dropped"] == ["D"]
        assert tel["delta"]["prior_snapshot"] == "2026-03-04"


class TestWriteTelemetry:
    def test_writes_json(self, tmp_path):
        rows = [
            _make_row("A", has_reg="1", reg_days="30", reg_type="PDUFA"),
            _make_row("B"),
        ]
        result = write_telemetry(tmp_path, rows, "2026-03-11")
        assert result is not None
        data = json.loads((tmp_path / "regulatory_coverage.json").read_text())
        assert data["n_flagged"] == 1
        assert data["coverage_pct"] == 50.0
