"""Tests for scripts/research/backfill_catalyst_event_type.py and ranking_utils catalyst_event_type heuristic."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "research"))

from backfill_catalyst_event_type import (
    _parse_date,
    backfill_snapshot,
    infer_event_type,
    load_ctgov_cache,
    load_pdufa_dates,
)


# ---------------------------------------------------------------------------
# _parse_date
# ---------------------------------------------------------------------------
class TestParseDate:
    def test_valid(self):
        dt = _parse_date("2025-06-15")
        assert dt is not None
        assert dt.year == 2025 and dt.month == 6 and dt.day == 15

    def test_empty(self):
        assert _parse_date("") is None
        assert _parse_date(None) is None

    def test_short(self):
        assert _parse_date("2025") is None


# ---------------------------------------------------------------------------
# infer_event_type
# ---------------------------------------------------------------------------
class TestInferEventType:
    def test_pdufa_match(self):
        pdufa = {"ACAD": [{"pdufa_date": "2026-04-03"}]}
        # Snapshot 2026-03-01, catalyst_days=33 → implied 2026-04-03
        et, src, conf = infer_event_type("ACAD", "2026-03-01", 33, {}, pdufa)
        assert et == "FDA_DECISION"
        assert src == "PDUFA_MANUAL"
        assert conf == "HIGH"

    def test_pdufa_no_match_too_far(self):
        pdufa = {"ACAD": [{"pdufa_date": "2026-04-03"}]}
        # Snapshot 2025-01-01, catalyst_days=30 → implied 2025-01-31 (far from 2026-04-03)
        et, src, conf = infer_event_type("ACAD", "2025-01-01", 30, {}, pdufa)
        assert et != "FDA_DECISION"

    def test_ctgov_match(self):
        ctgov = {
            "NUVB": [
                {
                    "nct_id": "NCT123",
                    "primary_completion_date": "2025-11-15",
                    "first_posted": "2024-01-01",
                    "study_type": "INTERVENTIONAL",
                }
            ]
        }
        # Snapshot 2025-06-01, catalyst_days=167 → implied ~2025-11-15
        et, src, conf = infer_event_type("NUVB", "2025-06-01", 167, ctgov, {})
        assert et == "CT_PRIMARY_COMPLETION"
        assert src == "CTGOV_CALENDAR"

    def test_ctgov_pit_safe(self):
        """Trial posted after snapshot should not match."""
        ctgov = {
            "NUVB": [
                {
                    "nct_id": "NCT123",
                    "primary_completion_date": "2025-11-15",
                    "first_posted": "2025-07-01",  # After snapshot
                    "study_type": "INTERVENTIONAL",
                }
            ]
        }
        et, src, conf = infer_event_type("NUVB", "2025-06-01", 167, ctgov, {})
        # Should fall through to generic fallback
        assert et == "DATA_READOUT"
        assert src == "INFERRED"

    def test_fallback_generic(self):
        et, src, conf = infer_event_type("UNKNOWN", "2025-06-01", 100, {}, {})
        assert et == "DATA_READOUT"
        assert src == "INFERRED"
        assert conf == "LOW"

    def test_pdufa_priority_over_ctgov(self):
        """PDUFA should be checked first."""
        pdufa = {"ACAD": [{"pdufa_date": "2025-07-15"}]}
        ctgov = {
            "ACAD": [
                {
                    "nct_id": "NCT456",
                    "primary_completion_date": "2025-07-15",
                    "first_posted": "2024-01-01",
                }
            ]
        }
        et, src, _ = infer_event_type("ACAD", "2025-06-01", 44, ctgov, pdufa)
        assert et == "FDA_DECISION"
        assert src == "PDUFA_MANUAL"


# ---------------------------------------------------------------------------
# backfill_snapshot
# ---------------------------------------------------------------------------
class TestBackfillSnapshot:
    def test_backfills_specific_days(self):
        rows = [
            {"ticker": "AAA", "catalyst_mode": "specific_days", "catalyst_days": "100"},
            {"ticker": "BBB", "catalyst_mode": "no_upcoming", "catalyst_days": ""},
        ]
        n = backfill_snapshot(rows, "2025-06-01", {}, {})
        assert n == 1  # Only AAA updated
        assert rows[0]["catalyst_event_type"] == "DATA_READOUT"  # Fallback
        assert rows[0]["catalyst_family"] == "CLINICAL"
        assert rows[1]["catalyst_event_type"] == ""
        assert rows[1]["catalyst_family"] == ""

    def test_skips_existing_event_type(self):
        rows = [
            {
                "ticker": "AAA",
                "catalyst_mode": "specific_days",
                "catalyst_days": "100",
                "catalyst_event_type": "FDA_DECISION",
            },
        ]
        n = backfill_snapshot(rows, "2025-06-01", {}, {})
        assert n == 0
        assert rows[0]["catalyst_event_type"] == "FDA_DECISION"

    def test_ctgov_match_in_backfill(self):
        ctgov = {
            "AAA": [
                {
                    "nct_id": "NCT789",
                    "primary_completion_date": "2025-09-10",
                    "first_posted": "2024-01-01",
                }
            ]
        }
        rows = [
            {"ticker": "AAA", "catalyst_mode": "specific_days", "catalyst_days": "100"},
        ]
        n = backfill_snapshot(rows, "2025-06-01", ctgov, {})
        assert n == 1
        assert rows[0]["catalyst_event_type"] == "CT_PRIMARY_COMPLETION"
        assert rows[0]["catalyst_source"] == "CTGOV_CALENDAR"

    def test_assigns_catalyst_family_to_all(self):
        rows = [
            {"ticker": "AAA", "catalyst_mode": "specific_days", "catalyst_days": "100"},
            {"ticker": "BBB", "catalyst_mode": "no_upcoming", "catalyst_days": ""},
        ]
        backfill_snapshot(rows, "2025-06-01", {}, {})
        for r in rows:
            assert "catalyst_family" in r


# ---------------------------------------------------------------------------
# load_pdufa_dates
# ---------------------------------------------------------------------------
class TestLoadPdufaDates:
    def test_loads_correctly(self, tmp_path):
        p = tmp_path / "pdufa.json"
        p.write_text(
            json.dumps(
                [
                    {"ticker": "ACAD", "pdufa_date": "2026-04-03"},
                    {"ticker": "CYTK", "pdufa_date": "2026-03-28"},
                ]
            )
        )
        result = load_pdufa_dates(p)
        assert "ACAD" in result
        assert len(result["ACAD"]) == 1
        assert result["ACAD"][0]["pdufa_date"] == "2026-04-03"

    def test_missing_file(self, tmp_path):
        result = load_pdufa_dates(tmp_path / "nope.json")
        assert result == {}


# ---------------------------------------------------------------------------
# load_ctgov_cache
# ---------------------------------------------------------------------------
class TestLoadCtgovCache:
    def test_loads_nearest_pit_safe(self, tmp_path):
        # Create two cache files
        data1 = [
            {"ticker": "AAA", "nct_id": "NCT1", "primary_completion_date": "2025-06-01", "study_type": "INTERVENTIONAL"}
        ]
        data2 = [
            {"ticker": "BBB", "nct_id": "NCT2", "primary_completion_date": "2025-09-01", "study_type": "INTERVENTIONAL"}
        ]
        (tmp_path / "trial_records_2025-01-31.json").write_text(json.dumps(data1))
        (tmp_path / "trial_records_2025-06-30.json").write_text(json.dumps(data2))

        # Request for 2025-05-15 → should load 2025-01-31 (PIT-safe)
        result = load_ctgov_cache(tmp_path, "2025-05-15")
        assert "AAA" in result
        assert "BBB" not in result

    def test_empty_dir(self, tmp_path):
        result = load_ctgov_cache(tmp_path, "2025-06-01")
        assert result == {}

    def test_filters_non_interventional(self, tmp_path):
        data = [
            {
                "ticker": "AAA",
                "nct_id": "NCT1",
                "primary_completion_date": "2025-06-01",
                "study_type": "INTERVENTIONAL",
            },
            {"ticker": "BBB", "nct_id": "NCT2", "primary_completion_date": "2025-06-01", "study_type": "OBSERVATIONAL"},
        ]
        (tmp_path / "trial_records_2025-01-31.json").write_text(json.dumps(data))
        result = load_ctgov_cache(tmp_path, "2025-06-01")
        assert "AAA" in result
        assert "BBB" not in result


# ---------------------------------------------------------------------------
# ranking_utils backfill_columns heuristic
# ---------------------------------------------------------------------------
class TestBackfillColumnsHeuristic:
    """Test the catalyst_event_type inference in backfill_columns."""

    def _make_rows(self, overrides=None):
        """Create rows with enough columns to pass min_cols check."""
        base = {
            "ticker": "TEST",
            "catalyst_mode": "specific_days",
            "catalyst_days": "100",
            "catalyst_source": "",
            "catalyst_event_type": "",
        }
        if overrides:
            base.update(overrides)
        # Pad to 55 columns
        for i in range(55):
            base.setdefault(f"col_{i}", "")
        return [base]

    def test_ctgov_source_maps_to_ct_primary(self):
        from common.ranking_utils import backfill_columns

        rows = self._make_rows({"catalyst_source": "CTGOV_CALENDAR"})
        backfill_columns(rows)
        assert rows[0]["catalyst_event_type"] == "CT_PRIMARY_COMPLETION"
        assert rows[0]["catalyst_family"] == "CLINICAL"

    def test_pdufa_source_maps_to_fda_decision(self):
        from common.ranking_utils import backfill_columns

        rows = self._make_rows({"catalyst_source": "PDUFA_MANUAL"})
        backfill_columns(rows)
        assert rows[0]["catalyst_event_type"] == "FDA_DECISION"
        assert rows[0]["catalyst_family"] == "REGULATORY"

    def test_sec_8k_maps_to_data_readout(self):
        from common.ranking_utils import backfill_columns

        rows = self._make_rows({"catalyst_source": "SEC_8K_FILING"})
        backfill_columns(rows)
        assert rows[0]["catalyst_event_type"] == "DATA_READOUT"
        assert rows[0]["catalyst_family"] == "CLINICAL"

    def test_no_source_defaults_to_clinical(self):
        from common.ranking_utils import backfill_columns

        rows = self._make_rows({"catalyst_source": ""})
        backfill_columns(rows)
        assert rows[0]["catalyst_event_type"] == "CT_PRIMARY_COMPLETION"
        assert rows[0]["catalyst_family"] == "CLINICAL"

    def test_no_upcoming_gets_empty(self):
        from common.ranking_utils import backfill_columns

        rows = self._make_rows({"catalyst_mode": "no_upcoming", "catalyst_source": ""})
        backfill_columns(rows)
        assert rows[0]["catalyst_event_type"] == ""

    def test_preserves_existing_event_type(self):
        from common.ranking_utils import backfill_columns

        rows = self._make_rows({"catalyst_event_type": "FDA_ADCOM"})
        backfill_columns(rows)
        assert rows[0]["catalyst_event_type"] == "FDA_ADCOM"
