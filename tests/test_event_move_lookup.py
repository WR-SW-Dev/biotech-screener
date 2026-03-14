"""Tests for common/event_move_lookup.py and common/straddle_mispricing.py."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from common.event_move_lookup import (
    build_table,
    compute_percentiles,
    indication_bucket,
    lookup_event_move,
    phase_bucket,
)
from common.straddle_mispricing import compute_cheap_vol_score


class TestPhaseBucket:
    def test_phase3(self):
        assert phase_bucket("3.0") == "phase3"

    def test_phase2(self):
        assert phase_bucket("2.0") == "phase2"

    def test_early(self):
        assert phase_bucket("1.0") == "early"

    def test_unknown(self):
        assert phase_bucket("") == "unknown"


class TestIndicationBucket:
    def test_oncology(self):
        assert indication_bucket("oncology") == "oncology"

    def test_rare(self):
        assert indication_bucket("rare_disease") == "rare"

    def test_other(self):
        assert indication_bucket("cns") == "other"

    def test_empty(self):
        assert indication_bucket("") == "other"


class TestComputePercentiles:
    def test_basic(self):
        result = compute_percentiles([0.1, 0.2, 0.3, 0.4, 0.5])
        assert result["n"] == 5
        assert result["p50"] is not None
        assert result["confidence"] == "low_confidence"

    def test_ok_confidence(self):
        result = compute_percentiles(list(range(15)))
        assert result["confidence"] == "ok"

    def test_empty(self):
        result = compute_percentiles([])
        assert result["n"] == 0


class TestBuildTable:
    def test_builds_with_fallbacks(self):
        rows = [
            {
                "abs_gap": 0.05,
                "catalyst_family": "CLINICAL",
                "lead_program_phase": "3.0",
                "therapeutic_area": "oncology",
            },
            {
                "abs_gap": 0.10,
                "catalyst_family": "CLINICAL",
                "lead_program_phase": "3.0",
                "therapeutic_area": "oncology",
            },
            {"abs_gap": 0.15, "catalyst_family": "CLINICAL", "lead_program_phase": "3.0", "therapeutic_area": "cns"},
        ]
        table = build_table(rows)
        # Should have specific cells + fallbacks
        assert "CLINICAL|phase3|oncology" in table
        assert "CLINICAL|phase3|any" in table
        assert "CLINICAL|any|any" in table
        assert "any|any|any" in table

    def test_empty_input(self):
        table = build_table([])
        assert table == {}


class TestLookupEventMove:
    def _make_table(self):
        return {
            "CLINICAL|phase3|oncology": {"n": 50, "p25": 0.01, "p50": 0.02, "p75": 0.04, "confidence": "ok"},
            "CLINICAL|phase3|any": {"n": 80, "p25": 0.01, "p50": 0.018, "p75": 0.03, "confidence": "ok"},
            "CLINICAL|any|any": {"n": 100, "p25": 0.01, "p50": 0.017, "p75": 0.03, "confidence": "ok"},
            "any|any|any": {"n": 111, "p25": 0.01, "p50": 0.018, "p75": 0.03, "confidence": "ok"},
        }

    def test_exact_match(self):
        table = self._make_table()
        result = lookup_event_move("CLINICAL", "phase3", "oncology", table)
        assert result["lookup_key"] == "CLINICAL|phase3|oncology"
        assert not result["fallback"]

    def test_fallback_to_any_indication(self):
        table = self._make_table()
        result = lookup_event_move("CLINICAL", "phase3", "rare", table)
        assert result["lookup_key"] == "CLINICAL|phase3|any"
        assert result["fallback"]

    def test_fallback_to_any_phase(self):
        table = self._make_table()
        result = lookup_event_move("CLINICAL", "phase2", "oncology", table)
        assert result["lookup_key"] == "CLINICAL|any|any"

    def test_global_fallback(self):
        table = self._make_table()
        result = lookup_event_move("REGULATORY", "pdufa", "any", table)
        assert result["lookup_key"] == "any|any|any"

    def test_min_n_gate(self):
        table = {"CLINICAL|phase3|oncology": {"n": 3, "p50": 0.05, "confidence": "insufficient"}}
        table["any|any|any"] = {"n": 50, "p50": 0.02, "confidence": "ok"}
        result = lookup_event_move("CLINICAL", "phase3", "oncology", table, min_n=10)
        assert result["lookup_key"] == "any|any|any"


class TestComputeCheapVolScore:
    def _make_table(self):
        return {
            "CLINICAL|phase3|oncology": {"n": 50, "p25": 0.08, "p50": 0.18, "p75": 0.35, "confidence": "ok"},
            "any|any|any": {"n": 111, "p25": 0.01, "p50": 0.018, "p75": 0.03, "confidence": "ok"},
        }

    def test_cheap_straddle(self):
        """Low IV relative to historical p50 → CHEAP."""
        table = self._make_table()
        result = compute_cheap_vol_score(
            opt_atm_iv=0.3,
            catalyst_days=30,
            catalyst_family="CLINICAL",
            lead_program_phase="3.0",
            therapeutic_area="oncology",
            event_move_table=table,
        )
        # implied_move = 0.3 * sqrt(30/365) ≈ 0.086
        # cheap_vol_score = 0.18 / 0.086 ≈ 2.1 → CHEAP
        assert result["vol_classification"] == "CHEAP"
        assert result["cheap_vol_score"] > 1.4

    def test_rich_straddle(self):
        """High IV relative to historical p50 → RICH."""
        table = self._make_table()
        result = compute_cheap_vol_score(
            opt_atm_iv=3.0,
            catalyst_days=30,
            catalyst_family="CLINICAL",
            lead_program_phase="3.0",
            therapeutic_area="oncology",
            event_move_table=table,
        )
        # implied_move = 3.0 * sqrt(30/365) ≈ 0.86
        # cheap_vol_score = 0.18 / 0.86 ≈ 0.21 → RICH
        assert result["vol_classification"] == "RICH"
        assert result["cheap_vol_score"] < 0.65

    def test_fair_straddle(self):
        table = self._make_table()
        result = compute_cheap_vol_score(
            opt_atm_iv=0.6,
            catalyst_days=30,
            catalyst_family="CLINICAL",
            lead_program_phase="3.0",
            therapeutic_area="oncology",
            event_move_table=table,
        )
        # implied_move ≈ 0.172, cheap_vol ≈ 0.18/0.172 ≈ 1.05 → FAIR
        assert result["vol_classification"] == "FAIR"

    def test_low_confidence_suppresses_cheap(self):
        """Low-confidence cell caps at SLIGHTLY_CHEAP, never CHEAP."""
        # Use n=10 so lookup succeeds, but set confidence to low_confidence
        table = {
            "CLINICAL|phase3|oncology": {
                "n": 10,
                "p25": 0.08,
                "p50": 0.18,
                "p75": 0.35,
                "confidence": "low_confidence",
            },
            "any|any|any": {"n": 10, "p25": 0.01, "p50": 0.018, "p75": 0.03, "confidence": "low_confidence"},
        }
        result = compute_cheap_vol_score(
            opt_atm_iv=0.3,
            catalyst_days=30,
            catalyst_family="CLINICAL",
            lead_program_phase="3.0",
            therapeutic_area="oncology",
            event_move_table=table,
        )
        # cheap_vol_score ≈ 0.18/0.086 ≈ 2.1 — would be CHEAP but capped
        assert result["vol_classification"] == "SLIGHTLY_CHEAP"
        assert result["vol_classification"] != "CHEAP"

    def test_missing_iv(self):
        table = self._make_table()
        result = compute_cheap_vol_score(
            opt_atm_iv=float("nan"),
            catalyst_days=30,
            catalyst_family="CLINICAL",
            lead_program_phase="3.0",
            therapeutic_area="oncology",
            event_move_table=table,
        )
        assert result["cheap_vol_score"] is None

    def test_zero_catalyst_days(self):
        table = self._make_table()
        result = compute_cheap_vol_score(
            opt_atm_iv=0.5,
            catalyst_days=0,
            catalyst_family="CLINICAL",
            lead_program_phase="3.0",
            therapeutic_area="oncology",
            event_move_table=table,
        )
        assert result["cheap_vol_score"] is None
