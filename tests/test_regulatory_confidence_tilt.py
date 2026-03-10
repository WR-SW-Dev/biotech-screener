"""Tests for regulatory confidence-weighted tilt inside the REGULATORY sleeve.

Covers:
  1. _confidence_factor — mapping defaults + missing fallback
  2. _combined_weights — quality*confidence composition + clipping
  3. Allocation: HIGH gets more dollars than MED (same quality)
  4. Caps respected + overflow reflow converges
  5. Determinism (same inputs → same outputs)
  6. Budget conservation
  7. Weekly summary: confidence table shown when enabled, absent when disabled
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.live_shadow_portfolio import (
    _DEFAULT_CONFIDENCE_WEIGHTS,
    _combined_weights,
    _confidence_factor,
    build_positions,
    write_weekly_summary,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ranking(
    ticker: str,
    rank: int = 1,
    regulatory_days: str = "60",
    regulatory_quality: str = "0.50",
    regulatory_confidence: str = "HIGH",
    regulatory_event_type: str = "PDUFA",
) -> dict:
    return {
        "ticker": ticker,
        "actionable_rank": str(rank),
        "eligible": "1",
        "catalyst_family": "REGULATORY",
        "catalyst_days": "100",
        "catalyst_mode": "specific_days",
        "catalyst_bucket": "binary_91_180",
        "has_regulatory_upcoming_180d": "1",
        "regulatory_days": regulatory_days,
        "regulatory_event_type": regulatory_event_type,
        "regulatory_quality": regulatory_quality,
        "regulatory_confidence": regulatory_confidence,
        "tier_any": "A",
        "size_band": "M",
        "mom_state": "neutral",
        "de_beta_xbi_60d_source": "computed",
    }


def _policy_with_confidence(
    quality_enabled=True,
    confidence_enabled=True,
    conf_weights=None,
    conf_clip_lo=0.30,
    conf_clip_hi=1.00,
    ladder_caps=None,
    account_usd=100_000,
):
    return {
        "account_usd": account_usd,
        "bucket_targets": {
            "binary_91_180": 1.0,
            "binary_31_90": 0.0,
            "binary_0_30": 0.0,
            "less_binary": 0.0,
        },
        "bucket_top_k": {"binary_91_180": 20},
        "bucket_name_caps": {"binary_91_180": 100.0},
        "family_overrides": {},
        "family_targets": {"binary_91_180": {"REGULATORY": 1.0}},
        "family_filter_mode": "secondary",
        "gap_risk": {"high_days": 7, "high_cap_pct": 0.5},
        "regulatory_ladder_enabled": True,
        "regulatory_bucket_caps_pct": ladder_caps or {},
        "regulatory_bucket_weights": {},
        "regulatory_quality_tilt_enabled": quality_enabled,
        "regulatory_quality_clip_lo": 0.30,
        "regulatory_quality_clip_hi": 1.00,
        "regulatory_confidence_tilt_enabled": confidence_enabled,
        "regulatory_confidence_weights": conf_weights or {"HIGH": 1.0, "MED": 0.6, "LOW": 0.3},
        "regulatory_confidence_clip_lo": conf_clip_lo,
        "regulatory_confidence_clip_hi": conf_clip_hi,
        "regulatory_resolution_enabled": False,
        "rebalance_buffer_ranks": 30,
        "bucket_hysteresis_days": 7,
    }


# ---------------------------------------------------------------------------
# 1. _confidence_factor unit tests
# ---------------------------------------------------------------------------


class TestConfidenceFactor:
    def test_high(self):
        row = {"regulatory_confidence": "HIGH"}
        assert _confidence_factor(row, _DEFAULT_CONFIDENCE_WEIGHTS) == 1.0

    def test_med(self):
        row = {"regulatory_confidence": "MED"}
        assert _confidence_factor(row, _DEFAULT_CONFIDENCE_WEIGHTS) == 0.6

    def test_low(self):
        row = {"regulatory_confidence": "LOW"}
        assert _confidence_factor(row, _DEFAULT_CONFIDENCE_WEIGHTS) == 0.3

    def test_missing_defaults_to_high(self):
        row = {}
        assert _confidence_factor(row, _DEFAULT_CONFIDENCE_WEIGHTS) == 1.0

    def test_empty_string_defaults_to_high(self):
        row = {"regulatory_confidence": ""}
        assert _confidence_factor(row, _DEFAULT_CONFIDENCE_WEIGHTS) == 1.0

    def test_custom_weights(self):
        row = {"regulatory_confidence": "MED"}
        custom = {"HIGH": 1.0, "MED": 0.8, "LOW": 0.5}
        assert _confidence_factor(row, custom) == 0.8


# ---------------------------------------------------------------------------
# 2. _combined_weights tests
# ---------------------------------------------------------------------------


class TestCombinedWeights:
    def test_quality_only(self):
        """When confidence_tilt=False, behaves like quality-only."""
        rows = [
            {"regulatory_quality": "0.80", "regulatory_confidence": "HIGH"},
            {"regulatory_quality": "0.40", "regulatory_confidence": "HIGH"},
        ]
        w = _combined_weights(rows, True, 0.30, 1.00, False, {}, 0.30, 1.00)
        assert sum(w) == pytest.approx(1.0)
        assert w[0] > w[1]

    def test_confidence_only(self):
        """When quality_tilt=False, weights come from confidence factor only."""
        rows = [
            {"regulatory_quality": "0.50", "regulatory_confidence": "HIGH"},
            {"regulatory_quality": "0.50", "regulatory_confidence": "MED"},
        ]
        w = _combined_weights(rows, False, 0.30, 1.00, True, _DEFAULT_CONFIDENCE_WEIGHTS, 0.30, 1.00)
        assert sum(w) == pytest.approx(1.0)
        # HIGH (1.0) vs MED (0.6): HIGH gets more
        assert w[0] > w[1]

    def test_combined_multiplicative(self):
        """Quality * confidence, then clip."""
        rows = [
            {"regulatory_quality": "0.80", "regulatory_confidence": "HIGH"},  # 0.80 * 1.0 = 0.80
            {"regulatory_quality": "0.80", "regulatory_confidence": "MED"},  # 0.80 * 0.6 = 0.48
        ]
        w = _combined_weights(rows, True, 0.30, 1.00, True, _DEFAULT_CONFIDENCE_WEIGHTS, 0.30, 1.00)
        assert sum(w) == pytest.approx(1.0)
        # 0.80 vs 0.48 → first gets more
        assert w[0] > w[1]

    def test_both_disabled_equal(self):
        """Neither quality nor confidence → equal weights."""
        rows = [
            {"regulatory_quality": "0.90", "regulatory_confidence": "HIGH"},
            {"regulatory_quality": "0.30", "regulatory_confidence": "LOW"},
        ]
        w = _combined_weights(rows, False, 0.30, 1.00, False, _DEFAULT_CONFIDENCE_WEIGHTS, 0.30, 1.00)
        assert w[0] == pytest.approx(0.5)
        assert w[1] == pytest.approx(0.5)

    def test_clipping_after_multiply(self):
        """Combined value below conf_clip_lo gets clipped up."""
        rows = [
            {"regulatory_quality": "0.30", "regulatory_confidence": "LOW"},  # 0.30 * 0.3 = 0.09 → clip to 0.30
            {"regulatory_quality": "0.80", "regulatory_confidence": "HIGH"},  # 0.80 * 1.0 = 0.80
        ]
        w = _combined_weights(rows, True, 0.30, 1.00, True, _DEFAULT_CONFIDENCE_WEIGHTS, 0.30, 1.00)
        # 0.30 vs 0.80 after clipping
        assert w[0] == pytest.approx(0.30 / 1.10, abs=0.01)
        assert w[1] == pytest.approx(0.80 / 1.10, abs=0.01)

    def test_empty_rows(self):
        assert _combined_weights([], True, 0.30, 1.00, True, {}, 0.30, 1.00) == []


# ---------------------------------------------------------------------------
# 3. Allocation: HIGH confidence gets more dollars
# ---------------------------------------------------------------------------


class TestConfidenceTiltAllocation:
    def test_high_gets_more_than_med(self):
        """Same quality, different confidence → HIGH gets more."""
        rankings = [
            _make_ranking("HI", 1, regulatory_days="60", regulatory_quality="0.70", regulatory_confidence="HIGH"),
            _make_ranking("MD", 2, regulatory_days="65", regulatory_quality="0.70", regulatory_confidence="MED"),
        ]
        policy = _policy_with_confidence(quality_enabled=False, confidence_enabled=True)
        result = build_positions(rankings, policy)
        dollars = {p["ticker"]: p["target_dollars"] for p in result["positions"]}
        assert dollars["HI"] > dollars["MD"]

    def test_disabled_gives_equal(self):
        """Confidence tilt disabled → equal dollars (quality also disabled)."""
        rankings = [
            _make_ranking("HI", 1, regulatory_days="60", regulatory_confidence="HIGH"),
            _make_ranking("MD", 2, regulatory_days="65", regulatory_confidence="MED"),
        ]
        policy = _policy_with_confidence(quality_enabled=False, confidence_enabled=False)
        result = build_positions(rankings, policy)
        dollars = {p["ticker"]: p["target_dollars"] for p in result["positions"]}
        assert dollars["HI"] == pytest.approx(dollars["MD"], abs=1)

    def test_combined_with_quality(self):
        """Both quality and confidence tilt: HIGH+good quality > MED+good quality."""
        rankings = [
            _make_ranking("HI", 1, regulatory_days="60", regulatory_quality="0.80", regulatory_confidence="HIGH"),
            _make_ranking("MD", 2, regulatory_days="65", regulatory_quality="0.80", regulatory_confidence="MED"),
        ]
        policy = _policy_with_confidence(quality_enabled=True, confidence_enabled=True)
        result = build_positions(rankings, policy)
        dollars = {p["ticker"]: p["target_dollars"] for p in result["positions"]}
        assert dollars["HI"] > dollars["MD"]


# ---------------------------------------------------------------------------
# 4. Caps respected + overflow reflow
# ---------------------------------------------------------------------------


class TestCapsAndReflow:
    def test_cap_respected(self):
        rankings = [
            _make_ranking("HI", 1, regulatory_days="60", regulatory_confidence="HIGH"),
            _make_ranking("MD", 2, regulatory_days="65", regulatory_confidence="MED"),
        ]
        policy = _policy_with_confidence(ladder_caps={"reg_46_90": 30.0})
        result = build_positions(rankings, policy)
        for p in result["positions"]:
            assert p["weight_pct"] <= 30.0 + 0.01

    def test_overflow_reflows(self):
        """Capped HIGH position's overflow goes to MED position."""
        rankings = [
            _make_ranking("HI", 1, regulatory_days="60", regulatory_confidence="HIGH"),
            _make_ranking("MD", 2, regulatory_days="65", regulatory_confidence="MED"),
            _make_ranking("LO", 3, regulatory_days="70", regulatory_confidence="LOW"),
        ]
        policy = _policy_with_confidence(ladder_caps={"reg_46_90": 40.0})
        result = build_positions(rankings, policy)
        total = sum(p["target_dollars"] for p in result["positions"])
        assert total == pytest.approx(100_000, abs=500)


# ---------------------------------------------------------------------------
# 5. Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_deterministic(self):
        rankings = [
            _make_ranking("A", 1, regulatory_days="60", regulatory_confidence="HIGH"),
            _make_ranking("B", 2, regulatory_days="65", regulatory_confidence="MED"),
            _make_ranking("C", 3, regulatory_days="70", regulatory_confidence="LOW"),
        ]
        policy = _policy_with_confidence()
        r1 = build_positions(rankings, policy)
        r2 = build_positions(rankings, policy)
        d1 = [(p["ticker"], p["target_dollars"]) for p in r1["positions"]]
        d2 = [(p["ticker"], p["target_dollars"]) for p in r2["positions"]]
        assert d1 == d2


# ---------------------------------------------------------------------------
# 6. Budget conservation
# ---------------------------------------------------------------------------


class TestBudgetConservation:
    def test_budget_conserved(self):
        rankings = [
            _make_ranking("A", 1, regulatory_days="60", regulatory_confidence="HIGH"),
            _make_ranking("B", 2, regulatory_days="65", regulatory_confidence="MED"),
        ]
        policy = _policy_with_confidence(account_usd=500_000)
        result = build_positions(rankings, policy)
        total = sum(p["target_dollars"] for p in result["positions"])
        assert total == pytest.approx(500_000, abs=100)

    def test_budget_conserved_with_cap(self):
        rankings = [
            _make_ranking("HI", 1, regulatory_days="60", regulatory_confidence="HIGH"),
            _make_ranking("MD", 2, regulatory_days="65", regulatory_confidence="MED"),
            _make_ranking("LO", 3, regulatory_days="70", regulatory_confidence="LOW"),
        ]
        policy = _policy_with_confidence(ladder_caps={"reg_46_90": 40.0})
        result = build_positions(rankings, policy)
        total = sum(p["target_dollars"] for p in result["positions"])
        assert total == pytest.approx(100_000, abs=500)


# ---------------------------------------------------------------------------
# 7. Weekly summary confidence table
# ---------------------------------------------------------------------------


class TestWeeklySummaryConfidence:
    def _make_pos(self, ticker, reg_days="60", quality="0.50", confidence="HIGH", reg_sub="reg_46_90"):
        return {
            "ticker": ticker,
            "bucket": "binary_91_180",
            "catalyst_family": "REGULATORY",
            "effective_family": "REGULATORY",
            "actionable_rank": 1,
            "tier": "A",
            "size_band": "M",
            "catalyst_days": "100",
            "catalyst_mode": "specific_days",
            "mom_state": "neutral",
            "weight_pct": 2.0,
            "target_dollars": 10000,
            "gap_risk": "",
            "price_coverage": "OK",
            "regulatory_days": reg_days,
            "regulatory_event_type": "PDUFA",
            "has_regulatory_upcoming_180d": "1",
            "regulatory_is_secondary": False,
            "regulatory_quality": quality,
            "regulatory_confidence": confidence,
            "reg_sub_bucket": reg_sub,
        }

    def _render(self, positions, tmp_path, confidence_enabled=True):
        positions_data = {
            "positions": positions,
            "summary": {"per_bucket": {}, "per_bucket_family": {}},
        }
        policy = {
            "account_usd": 100_000,
            "bucket_targets": {},
            "family_filter_mode": "secondary",
            "family_targets": {},
            "regulatory_ladder_enabled": True,
            "regulatory_bucket_caps_pct": {},
            "regulatory_confidence_tilt_enabled": confidence_enabled,
            "regulatory_confidence_weights": {"HIGH": 1.0, "MED": 0.6, "LOW": 0.3},
        }
        out = tmp_path / "weekly.md"
        write_weekly_summary("2026-03-08", positions_data, None, policy, {}, out)
        return out.read_text()

    def test_confidence_table_present_when_enabled(self, tmp_path):
        positions = [
            self._make_pos("R1", confidence="HIGH"),
            self._make_pos("R2", confidence="MED"),
        ]
        md = self._render(positions, tmp_path, confidence_enabled=True)
        assert "### Regulatory Confidence Breakdown" in md
        assert "HIGH" in md

    def test_confidence_table_absent_when_disabled(self, tmp_path):
        positions = [self._make_pos("R1", confidence="HIGH")]
        md = self._render(positions, tmp_path, confidence_enabled=False)
        assert "### Regulatory Confidence Breakdown" not in md
