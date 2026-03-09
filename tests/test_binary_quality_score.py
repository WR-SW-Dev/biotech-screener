"""Tests for common/binary_quality_score.py."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from common.binary_quality_score import (
    W_DESIGN,
    W_FAMILY,
    W_PHASE,
    W_SOURCE,
    compute_binary_quality_score,
    score_binary_positions,
)

# ---------------------------------------------------------------------------
# A) Weight sanity
# ---------------------------------------------------------------------------


class TestWeights:
    def test_weights_sum_to_one(self):
        assert abs(W_FAMILY + W_PHASE + W_SOURCE + W_DESIGN - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# B) Component scoring
# ---------------------------------------------------------------------------


class TestFamilyScore:
    def test_regulatory_family(self):
        row = {"catalyst_family": "REGULATORY", "catalyst_event_type": ""}
        score = compute_binary_quality_score(row)
        # REGULATORY family = 1.0, rest defaults → should be high
        assert score > 0.5

    def test_pdufa_event_type_override(self):
        row = {"catalyst_family": "", "catalyst_event_type": "PDUFA"}
        score = compute_binary_quality_score(row)
        # PDUFA override = 1.0 for family component
        assert score > 0.5

    def test_safety_family_scores_low(self):
        row = {"catalyst_family": "SAFETY", "catalyst_event_type": ""}
        score = compute_binary_quality_score(row)
        # SAFETY = 0.0 for family → lower score
        assert score < 0.5

    def test_unknown_family(self):
        row = {"catalyst_family": "UNKNOWN", "catalyst_event_type": ""}
        score = compute_binary_quality_score(row)
        # Unknown = 0.3 default
        assert 0.1 < score < 0.6

    def test_event_type_takes_precedence(self):
        """Granular event_type override takes precedence over family."""
        row_family = {"catalyst_family": "CLINICAL", "catalyst_event_type": ""}
        row_event = {
            "catalyst_family": "CLINICAL",
            "catalyst_event_type": "DATA_READOUT",
        }
        s_family = compute_binary_quality_score(row_family)
        s_event = compute_binary_quality_score(row_event)
        # DATA_READOUT (0.75) > CLINICAL family (0.6)
        assert s_event > s_family


class TestPhaseScore:
    def test_phase3_highest(self):
        base = {"catalyst_family": "CLINICAL", "catalyst_event_type": ""}
        row3 = {**base, "lead_program_phase": "3.0"}
        row1 = {**base, "lead_program_phase": "1.0"}
        assert compute_binary_quality_score(row3) > compute_binary_quality_score(row1)

    def test_missing_phase_neutral(self):
        row = {"catalyst_family": "CLINICAL", "catalyst_event_type": ""}
        score = compute_binary_quality_score(row)
        # Missing phase → 0.3 default
        assert score > 0.0

    def test_invalid_phase_neutral(self):
        row = {
            "catalyst_family": "CLINICAL",
            "catalyst_event_type": "",
            "lead_program_phase": "not_a_number",
        }
        score = compute_binary_quality_score(row)
        assert score > 0.0


class TestSourceScore:
    def test_sec_8k_highest(self):
        base = {"catalyst_family": "REGULATORY", "catalyst_event_type": ""}
        row_sec = {**base, "catalyst_source": "SEC_8K_FILING"}
        row_ctgov = {**base, "catalyst_source": "CTGOV_CALENDAR"}
        assert compute_binary_quality_score(row_sec) > compute_binary_quality_score(row_ctgov)

    def test_unknown_source(self):
        row = {
            "catalyst_family": "CLINICAL",
            "catalyst_event_type": "",
            "catalyst_source": "SOMETHING_NEW",
        }
        score = compute_binary_quality_score(row)
        assert score > 0.0


class TestDesignScore:
    def test_high_design_quality(self):
        base = {"catalyst_family": "CLINICAL", "catalyst_event_type": ""}
        row_high = {**base, "design_quality_score": "0.9"}
        row_low = {**base, "design_quality_score": "0.1"}
        assert compute_binary_quality_score(row_high) > compute_binary_quality_score(row_low)

    def test_design_clamped(self):
        row = {
            "catalyst_family": "CLINICAL",
            "catalyst_event_type": "",
            "design_quality_score": "5.0",
        }
        score = compute_binary_quality_score(row)
        assert score <= 1.0


# ---------------------------------------------------------------------------
# C) Full scoring
# ---------------------------------------------------------------------------


class TestComputeScore:
    def test_perfect_binary(self):
        """PDUFA + Phase 3 + SEC confirmed + high design → near 1.0."""
        row = {
            "catalyst_family": "REGULATORY",
            "catalyst_event_type": "PDUFA",
            "catalyst_source": "SEC_8K_FILING",
            "lead_program_phase": "3.0",
            "design_quality_score": "1.0",
        }
        score = compute_binary_quality_score(row)
        assert score >= 0.95

    def test_worst_binary(self):
        """SAFETY + Phase 0.5 + far CTgov + no design → near 0."""
        row = {
            "catalyst_family": "SAFETY",
            "catalyst_event_type": "",
            "catalyst_source": "CTGOV_PCD_FAR",
            "lead_program_phase": "0.5",
            "design_quality_score": "0.0",
        }
        score = compute_binary_quality_score(row)
        assert score < 0.15

    def test_empty_row(self):
        score = compute_binary_quality_score({})
        assert 0.0 <= score <= 1.0

    def test_score_range(self):
        row = {
            "catalyst_family": "CLINICAL",
            "catalyst_event_type": "CT_PRIMARY_COMPLETION",
            "catalyst_source": "CTGOV_CALENDAR",
            "lead_program_phase": "2.0",
            "design_quality_score": "0.5",
        }
        score = compute_binary_quality_score(row)
        assert 0.0 <= score <= 1.0

    def test_score_rounded(self):
        row = {"catalyst_family": "CLINICAL", "catalyst_event_type": "DATA_READOUT"}
        score = compute_binary_quality_score(row)
        # Should be rounded to 4 decimal places
        assert score == round(score, 4)


# ---------------------------------------------------------------------------
# D) Batch scorer
# ---------------------------------------------------------------------------


class TestScoreBinaryPositions:
    def test_only_binary_mode(self):
        rows = [
            {
                "catalyst_mode": "specific_days",
                "catalyst_family": "REGULATORY",
                "catalyst_event_type": "PDUFA",
            },
            {
                "catalyst_mode": "blended_window",
                "catalyst_family": "CLINICAL",
                "catalyst_event_type": "",
            },
            {
                "catalyst_mode": "no_upcoming",
                "catalyst_family": "",
                "catalyst_event_type": "",
            },
        ]
        result = score_binary_positions(rows, only_binary=True)
        assert result[0]["binary_quality_score"] > 0.0
        assert result[1]["binary_quality_score"] == 0.0
        assert result[2]["binary_quality_score"] == 0.0

    def test_all_mode(self):
        rows = [
            {
                "catalyst_mode": "blended_window",
                "catalyst_family": "CLINICAL",
                "catalyst_event_type": "DATA_READOUT",
            },
        ]
        result = score_binary_positions(rows, only_binary=False)
        assert result[0]["binary_quality_score"] > 0.0

    def test_mutates_in_place(self):
        rows = [
            {
                "catalyst_mode": "specific_days",
                "catalyst_family": "REGULATORY",
                "catalyst_event_type": "",
            },
        ]
        result = score_binary_positions(rows)
        assert result is rows
        assert "binary_quality_score" in rows[0]

    def test_empty_list(self):
        result = score_binary_positions([])
        assert result == []
