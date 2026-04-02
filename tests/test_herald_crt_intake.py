"""Tests for herald_crt_intake.py — shadow intake filter."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.herald_crt_intake import _map_catalyst_type, _map_outcome, build_intake_candidates

# ---------------------------------------------------------------------------
# Catalyst type mapping
# ---------------------------------------------------------------------------


class TestMapCatalystType:
    def test_clinical_phase3(self):
        r = {"event_subtype": "clinical_data", "headline": "Phase 3 topline results", "event_category": "clinical"}
        assert _map_catalyst_type(r) == "PHASE_3_READOUT"

    def test_clinical_phase2(self):
        r = {"event_subtype": "clinical_data", "headline": "Phase 2 data from trial", "event_category": "clinical"}
        assert _map_catalyst_type(r) == "PHASE_2_READOUT"

    def test_clinical_phase1(self):
        r = {"event_subtype": "clinical_data", "headline": "Phase 1 interim results", "event_category": "clinical"}
        assert _map_catalyst_type(r) == "PHASE_1_DATA"

    def test_regulatory_nda(self):
        r = {
            "event_subtype": "regulatory_update",
            "headline": "FDA accepts NDA submission",
            "event_category": "regulatory",
        }
        assert _map_catalyst_type(r) == "NDA_BLA_FILING"

    def test_regulatory_breakthrough(self):
        r = {
            "event_subtype": "regulatory_update",
            "headline": "Breakthrough therapy designation granted",
            "event_category": "regulatory",
        }
        assert _map_catalyst_type(r) == "REGULATORY_DESIGNATION"

    def test_regulatory_adcom(self):
        r = {
            "event_subtype": "regulatory_update",
            "headline": "Advisory committee meeting scheduled",
            "event_category": "regulatory",
        }
        assert _map_catalyst_type(r) == "ADVISORY_COMMITTEE"

    def test_safety_signal(self):
        r = {"event_subtype": "safety_signal", "headline": "Clinical hold placed", "event_category": "safety"}
        assert _map_catalyst_type(r) == "CORPORATE_UPDATE"

    def test_unknown_subtype(self):
        r = {"event_subtype": "unknown", "headline": "Something happened", "event_category": "other"}
        assert _map_catalyst_type(r) == "CORPORATE_UPDATE"


# ---------------------------------------------------------------------------
# Outcome mapping
# ---------------------------------------------------------------------------


class TestMapOutcome:
    def test_hit(self):
        assert _map_outcome({"event_outcome_guess": "hit"}) == "HIT"

    def test_miss(self):
        assert _map_outcome({"event_outcome_guess": "miss"}) == "MISS"

    def test_mixed(self):
        assert _map_outcome({"event_outcome_guess": "mixed"}) == "MIXED"

    def test_unclear(self):
        assert _map_outcome({"event_outcome_guess": "unclear"}) == "NEEDS_REVIEW"

    def test_missing(self):
        assert _map_outcome({}) == "NEEDS_REVIEW"


# ---------------------------------------------------------------------------
# Intake filter
# ---------------------------------------------------------------------------


class TestIntakeFilter:
    def _write_classified(self, tmp_path: Path, date: str, records: list) -> None:
        cdir = tmp_path / "classified"
        cdir.mkdir(parents=True, exist_ok=True)
        path = cdir / f"classified_{date}.jsonl"
        with open(path, "w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

    def _write_rankings(self, tmp_path: Path, date: str, rows: list) -> None:
        snap = tmp_path / "snapshots" / date
        snap.mkdir(parents=True, exist_ok=True)
        import csv

        if rows:
            with open(snap / "rankings.csv", "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                w.writeheader()
                w.writerows(rows)

    def test_clinical_event_passes(self, tmp_path, monkeypatch):
        monkeypatch.setattr("tools.herald_crt_intake.CLASSIFIED_DIR", tmp_path / "classified")
        monkeypatch.setattr("tools.herald_crt_intake.SNAPSHOT_DIR", tmp_path / "snapshots")
        monkeypatch.setattr("tools.herald_crt_intake.RESOLUTION_DIR", tmp_path / "resolutions")

        self._write_classified(
            tmp_path,
            "2026-04-01",
            [
                {
                    "ticker": "TEST",
                    "headline": "Phase 3 Positive Topline Results",
                    "event_category": "clinical",
                    "event_subtype": "clinical_data",
                    "confidence": 0.6,
                    "informational_only": False,
                    "event_outcome_guess": "hit",
                    "source_url": "https://example.com",
                    "source_type": "company_ir",
                    "thesis_change_flag": True,
                    "safety_signal_flag": False,
                    "mna_signal_flag": False,
                    "financing_signal_flag": False,
                }
            ],
        )
        self._write_rankings(
            tmp_path,
            "2026-04-01",
            [
                {
                    "ticker": "TEST",
                    "actionable_rank": "5",
                    "catalyst_days": "10",
                    "catalyst_event_type": "data_readout",
                    "is_hard_catalyst": "1",
                },
            ],
        )

        result = build_intake_candidates("2026-04-01")
        assert result["n_candidates"] == 1
        assert result["candidates"][0]["ticker"] == "TEST"
        assert result["candidates"][0]["mapped_outcome"] == "HIT"

    def test_informational_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setattr("tools.herald_crt_intake.CLASSIFIED_DIR", tmp_path / "classified")
        monkeypatch.setattr("tools.herald_crt_intake.SNAPSHOT_DIR", tmp_path / "snapshots")
        monkeypatch.setattr("tools.herald_crt_intake.RESOLUTION_DIR", tmp_path / "resolutions")

        self._write_classified(
            tmp_path,
            "2026-04-01",
            [
                {
                    "ticker": "TEST",
                    "headline": "Q4 Results",
                    "event_category": "other",
                    "informational_only": True,
                    "confidence": 0.7,
                },
            ],
        )
        self._write_rankings(
            tmp_path,
            "2026-04-01",
            [
                {
                    "ticker": "TEST",
                    "actionable_rank": "5",
                    "catalyst_days": "10",
                    "catalyst_event_type": "",
                    "is_hard_catalyst": "0",
                },
            ],
        )

        result = build_intake_candidates("2026-04-01")
        assert result["n_candidates"] == 0
        assert result["rejection_reasons"]["informational"] == 1

    def test_low_confidence_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setattr("tools.herald_crt_intake.CLASSIFIED_DIR", tmp_path / "classified")
        monkeypatch.setattr("tools.herald_crt_intake.SNAPSHOT_DIR", tmp_path / "snapshots")
        monkeypatch.setattr("tools.herald_crt_intake.RESOLUTION_DIR", tmp_path / "resolutions")

        self._write_classified(
            tmp_path,
            "2026-04-01",
            [
                {
                    "ticker": "TEST",
                    "headline": "Phase 3 data",
                    "event_category": "clinical",
                    "informational_only": False,
                    "confidence": 0.3,
                },
            ],
        )
        self._write_rankings(
            tmp_path,
            "2026-04-01",
            [
                {
                    "ticker": "TEST",
                    "actionable_rank": "5",
                    "catalyst_days": "10",
                    "catalyst_event_type": "",
                    "is_hard_catalyst": "0",
                },
            ],
        )

        result = build_intake_candidates("2026-04-01")
        assert result["n_candidates"] == 0
        assert result["rejection_reasons"]["low_confidence"] == 1

    def test_no_dem_match_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setattr("tools.herald_crt_intake.CLASSIFIED_DIR", tmp_path / "classified")
        monkeypatch.setattr("tools.herald_crt_intake.SNAPSHOT_DIR", tmp_path / "snapshots")
        monkeypatch.setattr("tools.herald_crt_intake.RESOLUTION_DIR", tmp_path / "resolutions")

        self._write_classified(
            tmp_path,
            "2026-04-01",
            [
                {
                    "ticker": "UNKNOWN",
                    "headline": "Phase 3 positive",
                    "event_category": "clinical",
                    "informational_only": False,
                    "confidence": 0.6,
                },
            ],
        )
        self._write_rankings(
            tmp_path,
            "2026-04-01",
            [
                {
                    "ticker": "OTHER",
                    "actionable_rank": "5",
                    "catalyst_days": "10",
                    "catalyst_event_type": "",
                    "is_hard_catalyst": "0",
                },
            ],
        )

        result = build_intake_candidates("2026-04-01")
        assert result["n_candidates"] == 0
        assert result["rejection_reasons"]["no_dem_match"] == 1

    def test_deduplicates_by_ticker_type(self, tmp_path, monkeypatch):
        monkeypatch.setattr("tools.herald_crt_intake.CLASSIFIED_DIR", tmp_path / "classified")
        monkeypatch.setattr("tools.herald_crt_intake.SNAPSHOT_DIR", tmp_path / "snapshots")
        monkeypatch.setattr("tools.herald_crt_intake.RESOLUTION_DIR", tmp_path / "resolutions")

        self._write_classified(
            tmp_path,
            "2026-04-01",
            [
                {
                    "ticker": "TEST",
                    "headline": "Phase 3 first headline",
                    "event_category": "clinical",
                    "event_subtype": "clinical_data",
                    "informational_only": False,
                    "confidence": 0.5,
                    "event_outcome_guess": "unclear",
                    "source_url": "",
                    "source_type": "company_ir",
                    "thesis_change_flag": False,
                    "safety_signal_flag": False,
                    "mna_signal_flag": False,
                    "financing_signal_flag": False,
                },
                {
                    "ticker": "TEST",
                    "headline": "Phase 3 second headline higher conf",
                    "event_category": "clinical",
                    "event_subtype": "clinical_data",
                    "informational_only": False,
                    "confidence": 0.6,
                    "event_outcome_guess": "hit",
                    "source_url": "",
                    "source_type": "company_ir",
                    "thesis_change_flag": True,
                    "safety_signal_flag": False,
                    "mna_signal_flag": False,
                    "financing_signal_flag": False,
                },
            ],
        )
        self._write_rankings(
            tmp_path,
            "2026-04-01",
            [
                {
                    "ticker": "TEST",
                    "actionable_rank": "5",
                    "catalyst_days": "10",
                    "catalyst_event_type": "",
                    "is_hard_catalyst": "0",
                },
            ],
        )

        result = build_intake_candidates("2026-04-01")
        assert result["n_candidates"] == 1
        # Should keep the higher confidence one
        assert result["candidates"][0]["herald_confidence"] == 0.6

    def test_empty_classified(self, tmp_path, monkeypatch):
        monkeypatch.setattr("tools.herald_crt_intake.CLASSIFIED_DIR", tmp_path / "classified")
        monkeypatch.setattr("tools.herald_crt_intake.SNAPSHOT_DIR", tmp_path / "snapshots")
        monkeypatch.setattr("tools.herald_crt_intake.RESOLUTION_DIR", tmp_path / "resolutions")

        result = build_intake_candidates("2026-04-01")
        assert result["n_candidates"] == 0
        assert result["n_classified"] == 0
