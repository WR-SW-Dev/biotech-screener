"""Tests for regulatory quality tilt inside the ladder.

Verifies:
1. _quality_weights() normalization and clipping
2. Higher quality → more dollars within sub-bucket
3. Cap interaction: capped name's overflow reflows to others
4. Determinism
5. Quality tilt disabled → equal weight
6. Weekly summary shows quality column
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.live_shadow_portfolio import _quality_weights, build_positions, write_weekly_summary

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ranking(
    ticker: str,
    rank: int = 1,
    regulatory_days: str = "60",
    regulatory_quality: str = "0.50",
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
        "tier_any": "A",
        "size_band": "M",
        "mom_state": "neutral",
        "de_beta_xbi_60d_source": "computed",
    }


def _policy_with_quality(
    quality_enabled=True,
    clip_lo=0.30,
    clip_hi=1.00,
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
        "regulatory_quality_clip_lo": clip_lo,
        "regulatory_quality_clip_hi": clip_hi,
        "regulatory_resolution_enabled": False,
        "rebalance_buffer_ranks": 30,
        "bucket_hysteresis_days": 7,
    }


# ---------------------------------------------------------------------------
# Test _quality_weights
# ---------------------------------------------------------------------------


class TestQualityWeights:
    def test_basic_normalization(self):
        rows = [
            {"regulatory_quality": "0.80"},
            {"regulatory_quality": "0.40"},
        ]
        w = _quality_weights(rows, 0.30, 1.00)
        assert len(w) == 2
        assert sum(w) == pytest.approx(1.0)
        # 0.80 should get more weight than 0.40
        assert w[0] > w[1]

    def test_clipping_low(self):
        """Quality below q_lo should be clipped up."""
        rows = [
            {"regulatory_quality": "0.10"},
            {"regulatory_quality": "0.80"},
        ]
        w = _quality_weights(rows, 0.30, 1.00)
        # First row clipped to 0.30, second stays 0.80
        # ratio should be 0.30:0.80
        assert w[0] == pytest.approx(0.30 / 1.10, abs=0.01)
        assert w[1] == pytest.approx(0.80 / 1.10, abs=0.01)

    def test_clipping_high(self):
        """Quality above q_hi should be clipped down."""
        rows = [
            {"regulatory_quality": "1.50"},
            {"regulatory_quality": "0.50"},
        ]
        w = _quality_weights(rows, 0.30, 1.00)
        # First clipped to 1.00, second stays 0.50
        assert w[0] == pytest.approx(1.00 / 1.50, abs=0.01)
        assert w[1] == pytest.approx(0.50 / 1.50, abs=0.01)

    def test_all_zero_quality_equal_weight(self):
        """When all qualities are 0, fallback to equal weight."""
        rows = [
            {"regulatory_quality": "0"},
            {"regulatory_quality": "0"},
        ]
        w = _quality_weights(rows, 0.30, 1.00)
        # Clipped to 0.30 each → equal
        assert w[0] == pytest.approx(0.50)
        assert w[1] == pytest.approx(0.50)

    def test_missing_quality_uses_floor(self):
        rows = [
            {"regulatory_quality": ""},
            {"regulatory_quality": "0.80"},
        ]
        w = _quality_weights(rows, 0.30, 1.00)
        assert w[0] < w[1]

    def test_single_row(self):
        w = _quality_weights([{"regulatory_quality": "0.50"}], 0.30, 1.00)
        assert w == [1.0]


# ---------------------------------------------------------------------------
# Test quality tilt in allocation
# ---------------------------------------------------------------------------


class TestQualityTiltAllocation:
    def test_higher_quality_gets_more_dollars(self):
        """Within same sub-bucket, higher quality → more dollars."""
        rankings = [
            _make_ranking("HIGH", 1, regulatory_days="60", regulatory_quality="0.90"),
            _make_ranking("LOW", 2, regulatory_days="65", regulatory_quality="0.30"),
        ]
        policy = _policy_with_quality(quality_enabled=True)
        result = build_positions(rankings, policy)
        positions = result["positions"]
        high = next(p for p in positions if p["ticker"] == "HIGH")
        low = next(p for p in positions if p["ticker"] == "LOW")
        assert high["target_dollars"] > low["target_dollars"]
        # With 0.90 vs 0.30, high should get 3x more
        assert high["target_dollars"] > low["target_dollars"] * 2.5

    def test_disabled_gives_equal_weight(self):
        """With quality tilt disabled, same sub-bucket → equal dollars."""
        rankings = [
            _make_ranking("HIGH", 1, regulatory_days="60", regulatory_quality="0.90"),
            _make_ranking("LOW", 2, regulatory_days="65", regulatory_quality="0.30"),
        ]
        policy = _policy_with_quality(quality_enabled=False)
        result = build_positions(rankings, policy)
        positions = result["positions"]
        high = next(p for p in positions if p["ticker"] == "HIGH")
        low = next(p for p in positions if p["ticker"] == "LOW")
        assert high["target_dollars"] == pytest.approx(low["target_dollars"], abs=1)

    def test_cap_overflow_reflows(self):
        """When high-quality name hits cap, overflow goes to next-best."""
        rankings = [
            _make_ranking("HIGH", 1, regulatory_days="60", regulatory_quality="0.95"),
            _make_ranking("MED", 2, regulatory_days="65", regulatory_quality="0.50"),
            _make_ranking("LOW", 3, regulatory_days="70", regulatory_quality="0.30"),
        ]
        # Cap at 40% so HIGH (quality 0.95) is capped but MED/LOW aren't
        policy = _policy_with_quality(
            quality_enabled=True,
            ladder_caps={"reg_46_90": 40.0},
        )
        result = build_positions(rankings, policy)
        positions = result["positions"]
        high = next(p for p in positions if p["ticker"] == "HIGH")
        med = next(p for p in positions if p["ticker"] == "MED")
        low = next(p for p in positions if p["ticker"] == "LOW")

        # HIGH should be capped at 40%
        assert high["weight_pct"] <= 40.0 + 0.01
        # Without cap, HIGH would get ~54% (0.95/1.75). Capped at 40%.
        # MED should get more than LOW from overflow redistribution
        assert med["target_dollars"] > low["target_dollars"]
        # Total should still be ~$100k (full bucket budget)
        total = sum(p["target_dollars"] for p in positions)
        assert total == pytest.approx(100_000, abs=500)

    def test_deterministic(self):
        rankings = [
            _make_ranking("A", 1, regulatory_days="60", regulatory_quality="0.80"),
            _make_ranking("B", 2, regulatory_days="65", regulatory_quality="0.50"),
            _make_ranking("C", 3, regulatory_days="70", regulatory_quality="0.30"),
        ]
        policy = _policy_with_quality()
        r1 = build_positions(rankings, policy)
        r2 = build_positions(rankings, policy)
        d1 = [(p["ticker"], p["target_dollars"]) for p in r1["positions"]]
        d2 = [(p["ticker"], p["target_dollars"]) for p in r2["positions"]]
        assert d1 == d2

    def test_quality_across_sub_buckets_independent(self):
        """Quality tilt in one sub-bucket doesn't affect another."""
        rankings = [
            _make_ranking("NEAR_HI", 1, regulatory_days="30", regulatory_quality="0.90"),
            _make_ranking("NEAR_LO", 2, regulatory_days="35", regulatory_quality="0.30"),
            _make_ranking("FAR_HI", 3, regulatory_days="100", regulatory_quality="0.90"),
            _make_ranking("FAR_LO", 4, regulatory_days="110", regulatory_quality="0.30"),
        ]
        policy = _policy_with_quality()
        result = build_positions(rankings, policy)
        positions = result["positions"]

        near_hi = next(p for p in positions if p["ticker"] == "NEAR_HI")
        near_lo = next(p for p in positions if p["ticker"] == "NEAR_LO")
        far_hi = next(p for p in positions if p["ticker"] == "FAR_HI")
        far_lo = next(p for p in positions if p["ticker"] == "FAR_LO")

        # Within each sub-bucket, high > low
        assert near_hi["target_dollars"] > near_lo["target_dollars"]
        assert far_hi["target_dollars"] > far_lo["target_dollars"]

    def test_all_same_quality_equal_weight(self):
        """If all names have identical quality, allocation is equal."""
        rankings = [
            _make_ranking("A", 1, regulatory_days="60", regulatory_quality="0.70"),
            _make_ranking("B", 2, regulatory_days="65", regulatory_quality="0.70"),
        ]
        policy = _policy_with_quality()
        result = build_positions(rankings, policy)
        positions = result["positions"]
        assert positions[0]["target_dollars"] == pytest.approx(positions[1]["target_dollars"], abs=1)


# ---------------------------------------------------------------------------
# Test weekly summary quality column
# ---------------------------------------------------------------------------


class TestWeeklySummaryQuality:
    def _make_pos(self, ticker, reg_days="60", quality="0.50", reg_sub="reg_46_90"):
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
            "reg_sub_bucket": reg_sub,
        }

    def _render(self, positions, tmp_path):
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
        }
        out = tmp_path / "weekly.md"
        write_weekly_summary("2026-03-08", positions_data, None, policy, {}, out)
        return out.read_text()

    def test_quality_column_in_ladder_table(self, tmp_path):
        positions = [self._make_pos("R1", quality="0.80")]
        md = self._render(positions, tmp_path)
        assert "Avg Quality" in md
        assert "0.80" in md

    def test_quality_in_top_holdings(self, tmp_path):
        positions = [self._make_pos("R1", quality="0.75")]
        md = self._render(positions, tmp_path)
        assert "Quality" in md
        assert "0.75" in md

    def test_min_max_quality_in_ladder_table(self, tmp_path):
        positions = [
            self._make_pos("R1", quality="0.30"),
            self._make_pos("R2", quality="0.90"),
        ]
        md = self._render(positions, tmp_path)
        assert "Min Q" in md
        assert "Max Q" in md
        assert "0.30" in md
        assert "0.90" in md


# ---------------------------------------------------------------------------
# Extended edge-case tests
# ---------------------------------------------------------------------------


class TestQualityTiltEdgeCases:
    def test_monotonicity_ordering(self):
        """Strictly higher quality → strictly more dollars (no caps binding)."""
        rankings = [
            _make_ranking("A", 1, regulatory_days="60", regulatory_quality="0.90"),
            _make_ranking("B", 2, regulatory_days="65", regulatory_quality="0.70"),
            _make_ranking("C", 3, regulatory_days="70", regulatory_quality="0.50"),
            _make_ranking("D", 4, regulatory_days="75", regulatory_quality="0.30"),
        ]
        policy = _policy_with_quality()
        result = build_positions(rankings, policy)
        dollars = {p["ticker"]: p["target_dollars"] for p in result["positions"]}
        assert dollars["A"] > dollars["B"]
        assert dollars["B"] > dollars["C"]
        assert dollars["C"] > dollars["D"]

    def test_budget_conservation(self):
        """Total dollars must equal bucket budget within rounding tolerance."""
        rankings = [
            _make_ranking("A", 1, regulatory_days="60", regulatory_quality="0.95"),
            _make_ranking("B", 2, regulatory_days="65", regulatory_quality="0.60"),
            _make_ranking("C", 3, regulatory_days="70", regulatory_quality="0.35"),
        ]
        policy = _policy_with_quality(account_usd=500_000)
        result = build_positions(rankings, policy)
        total = sum(p["target_dollars"] for p in result["positions"])
        # 100% of $500k to binary_91_180, 100% to REGULATORY
        assert total == pytest.approx(500_000, abs=100)

    def test_budget_conservation_with_cap(self):
        """Cap-overflow reflows correctly: HI capped, excess goes to LO."""
        rankings = [
            _make_ranking("HI", 1, regulatory_days="60", regulatory_quality="0.95"),
            _make_ranking("MED", 2, regulatory_days="65", regulatory_quality="0.60"),
            _make_ranking("LO", 3, regulatory_days="70", regulatory_quality="0.30"),
        ]
        # Cap at 40% → HI gets capped, overflow redistributed to MED+LO
        policy = _policy_with_quality(ladder_caps={"reg_46_90": 40.0})
        result = build_positions(rankings, policy)
        dollars = {p["ticker"]: p["target_dollars"] for p in result["positions"]}
        # HI should be capped at 40% of $100k = $40k
        assert dollars["HI"] <= 40_000 + 100
        # Total should equal full budget (3 names can absorb overflow)
        total = sum(dollars.values())
        assert total == pytest.approx(100_000, abs=100)

    def test_missing_quality_treated_as_floor(self):
        """Missing regulatory_quality → clipped to q_lo, not zero."""
        rankings = [
            _make_ranking("GOOD", 1, regulatory_days="60", regulatory_quality="0.80"),
            _make_ranking("MISSING", 2, regulatory_days="65", regulatory_quality=""),
        ]
        policy = _policy_with_quality()
        result = build_positions(rankings, policy)
        dollars = {p["ticker"]: p["target_dollars"] for p in result["positions"]}
        # MISSING gets floor=0.30, GOOD gets 0.80 → GOOD should get more
        assert dollars["GOOD"] > dollars["MISSING"]
        # But MISSING should still get something (not zero)
        assert dollars["MISSING"] > 0

    def test_nan_quality_treated_as_floor(self):
        """Non-numeric quality → treated as floor."""
        rankings = [
            _make_ranking("A", 1, regulatory_days="60", regulatory_quality="nan_value"),
            _make_ranking("B", 2, regulatory_days="65", regulatory_quality="0.80"),
        ]
        policy = _policy_with_quality()
        result = build_positions(rankings, policy)
        dollars = {p["ticker"]: p["target_dollars"] for p in result["positions"]}
        assert dollars["B"] > dollars["A"]
        assert dollars["A"] > 0

    def test_all_caps_respected(self):
        """No position exceeds the sub-bucket cap."""
        rankings = [
            _make_ranking("A", 1, regulatory_days="60", regulatory_quality="1.00"),
            _make_ranking("B", 2, regulatory_days="65", regulatory_quality="0.30"),
        ]
        policy = _policy_with_quality(ladder_caps={"reg_46_90": 30.0})
        result = build_positions(rankings, policy)
        for p in result["positions"]:
            assert p["weight_pct"] <= 30.0 + 0.01

    def test_single_name_gets_full_budget(self):
        """One name in sub-bucket → gets full sub-bucket budget (up to cap)."""
        rankings = [
            _make_ranking("SOLO", 1, regulatory_days="60", regulatory_quality="0.50"),
        ]
        policy = _policy_with_quality()
        result = build_positions(rankings, policy)
        assert len(result["positions"]) == 1
        assert result["positions"][0]["target_dollars"] == pytest.approx(100_000, abs=100)
