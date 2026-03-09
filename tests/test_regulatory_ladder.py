"""Tests for regulatory time-ladder sizing rails.

Verifies:
1. _reg_sub_bucket() boundary classification
2. Per-sub-bucket cap enforcement
3. Budget reflow when a ladder bucket has 0 names
4. Deterministic output
5. Weekly summary Regulatory Ladder section
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.live_shadow_portfolio import _reg_sub_bucket, build_positions, write_weekly_summary

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ranking(
    ticker: str,
    rank: int = 1,
    catalyst_family: str = "REGULATORY",
    catalyst_days: str = "100",
    catalyst_mode: str = "specific_days",
    has_regulatory: str = "1",
    regulatory_days: str = "60",
    regulatory_event_type: str = "PDUFA",
    bucket_override: str = "",
) -> dict:
    return {
        "ticker": ticker,
        "actionable_rank": str(rank),
        "eligible": "1",
        "catalyst_family": catalyst_family,
        "catalyst_days": catalyst_days,
        "catalyst_mode": catalyst_mode,
        "catalyst_bucket": bucket_override or "binary_91_180",
        "has_regulatory_upcoming_180d": has_regulatory,
        "regulatory_days": regulatory_days,
        "regulatory_event_type": regulatory_event_type,
        "tier_any": "A",
        "size_band": "M",
        "mom_state": "neutral",
        "de_beta_xbi_60d_source": "computed",
    }


def _policy_with_ladder(
    ladder_enabled=True,
    ladder_caps=None,
    ladder_weights=None,
    family_targets=None,
    account_usd=100_000,
):
    return {
        "account_usd": account_usd,
        "bucket_targets": {
            "binary_91_180": 0.50,
            "binary_31_90": 0.30,
            "binary_0_30": 0.10,
            "less_binary": 0.10,
        },
        "bucket_top_k": {
            "binary_91_180": 20,
            "binary_31_90": 15,
            "binary_0_30": 10,
            "less_binary": 15,
        },
        "bucket_name_caps": {
            "binary_91_180": 50.0,
            "binary_31_90": 50.0,
            "binary_0_30": 50.0,
            "less_binary": 50.0,
        },
        "family_overrides": {},
        "family_targets": family_targets
        or {
            "binary_91_180": {"REGULATORY": 1.0},
        },
        "family_filter_mode": "secondary",
        "gap_risk": {"high_days": 7, "high_cap_pct": 0.5},
        "regulatory_ladder_enabled": ladder_enabled,
        "regulatory_bucket_caps_pct": ladder_caps or {},
        "regulatory_bucket_weights": ladder_weights or {},
        "rebalance_buffer_ranks": 30,
        "bucket_hysteresis_days": 7,
    }


# ---------------------------------------------------------------------------
# Test _reg_sub_bucket classification
# ---------------------------------------------------------------------------


class TestRegSubBucket:
    def test_boundary_0(self):
        assert _reg_sub_bucket("0") == ""

    def test_boundary_1(self):
        assert _reg_sub_bucket("1") == "reg_0_14"

    def test_boundary_14(self):
        assert _reg_sub_bucket("14") == "reg_0_14"

    def test_boundary_15(self):
        assert _reg_sub_bucket("15") == "reg_15_45"

    def test_boundary_45(self):
        assert _reg_sub_bucket("45") == "reg_15_45"

    def test_boundary_46(self):
        assert _reg_sub_bucket("46") == "reg_46_90"

    def test_boundary_90(self):
        assert _reg_sub_bucket("90") == "reg_46_90"

    def test_boundary_91(self):
        assert _reg_sub_bucket("91") == "reg_91_180"

    def test_boundary_180(self):
        assert _reg_sub_bucket("180") == "reg_91_180"

    def test_boundary_181(self):
        assert _reg_sub_bucket("181") == ""

    def test_empty_string(self):
        assert _reg_sub_bucket("") == ""

    def test_non_numeric(self):
        assert _reg_sub_bucket("abc") == ""

    def test_negative(self):
        assert _reg_sub_bucket("-5") == ""

    def test_float_value(self):
        assert _reg_sub_bucket("14.5") == "reg_15_45"


# ---------------------------------------------------------------------------
# Test ladder allocation
# ---------------------------------------------------------------------------


class TestLadderAllocation:
    def test_basic_ladder_split(self):
        """Names in different sub-buckets get different allocations."""
        rankings = [
            _make_ranking("R1", 1, regulatory_days="10"),  # reg_0_14
            _make_ranking("R2", 2, regulatory_days="30"),  # reg_15_45
            _make_ranking("R3", 3, regulatory_days="70"),  # reg_46_90
            _make_ranking("R4", 4, regulatory_days="120"),  # reg_91_180
        ]
        policy = _policy_with_ladder()
        result = build_positions(rankings, policy)
        positions = result["positions"]

        assert len(positions) == 4
        subs = {p["ticker"]: p["reg_sub_bucket"] for p in positions}
        assert subs["R1"] == "reg_0_14"
        assert subs["R2"] == "reg_15_45"
        assert subs["R3"] == "reg_46_90"
        assert subs["R4"] == "reg_91_180"

    def test_ladder_caps_enforced(self):
        """Per-sub-bucket caps limit individual position weight."""
        rankings = [
            _make_ranking("R1", 1, regulatory_days="10"),  # reg_0_14
        ]
        policy = _policy_with_ladder(
            ladder_caps={"reg_0_14": 0.35},
        )
        result = build_positions(rankings, policy)
        pos = result["positions"][0]
        # Cap is 0.35% → max $350 on $100k
        assert pos["weight_pct"] <= 0.35
        assert pos["target_dollars"] <= 350 + 1

    def test_ladder_reflow_empty_sub_bucket(self):
        """If a sub-bucket has 0 names, its budget flows to the next priority."""
        # Only reg_15_45 names, nothing in other sub-buckets
        rankings = [
            _make_ranking("R1", 1, regulatory_days="20"),
            _make_ranking("R2", 2, regulatory_days="30"),
        ]
        policy = _policy_with_ladder(
            ladder_weights={
                "binary_91_180": {
                    "reg_0_14": 0.25,
                    "reg_15_45": 0.25,
                    "reg_46_90": 0.25,
                    "reg_91_180": 0.25,
                }
            },
        )
        result = build_positions(rankings, policy)
        positions = result["positions"]
        # All budget should flow to reg_15_45 (the only active sub-bucket)
        total = sum(p["target_dollars"] for p in positions)
        # Full REGULATORY budget = 100% of 50% of $100k = $50k
        assert total == pytest.approx(50_000, abs=100)

    def test_ladder_with_custom_weights(self):
        """Custom weights tilt budget toward specific sub-buckets."""
        rankings = [
            _make_ranking("R1", 1, regulatory_days="30"),  # reg_15_45
            _make_ranking("R2", 2, regulatory_days="70"),  # reg_46_90
        ]
        policy = _policy_with_ladder(
            ladder_weights={
                "binary_91_180": {
                    "reg_0_14": 0.0,
                    "reg_15_45": 0.80,
                    "reg_46_90": 0.20,
                    "reg_91_180": 0.0,
                }
            },
        )
        result = build_positions(rankings, policy)
        positions = result["positions"]
        r1 = next(p for p in positions if p["ticker"] == "R1")
        r2 = next(p for p in positions if p["ticker"] == "R2")
        # R1 should get ~80% of budget, R2 ~20%
        assert r1["target_dollars"] > r2["target_dollars"] * 3

    def test_ladder_disabled_no_sub_buckets(self):
        """When ladder_enabled=False, no reg_sub_bucket assigned."""
        rankings = [
            _make_ranking("R1", 1, regulatory_days="30"),
        ]
        policy = _policy_with_ladder(ladder_enabled=False)
        result = build_positions(rankings, policy)
        pos = result["positions"][0]
        assert pos["reg_sub_bucket"] == ""

    def test_deterministic(self):
        """Ladder output is deterministic."""
        rankings = [
            _make_ranking("R1", 1, regulatory_days="10"),
            _make_ranking("R2", 2, regulatory_days="30"),
            _make_ranking("R3", 3, regulatory_days="70"),
        ]
        policy = _policy_with_ladder()
        r1 = build_positions(rankings, policy)
        r2 = build_positions(rankings, policy)
        t1 = [(p["ticker"], p["target_dollars"], p["reg_sub_bucket"]) for p in r1["positions"]]
        t2 = [(p["ticker"], p["target_dollars"], p["reg_sub_bucket"]) for p in r2["positions"]]
        assert t1 == t2

    def test_multiple_names_per_sub_bucket(self):
        """Multiple names in one sub-bucket share that sub-bucket's allocation."""
        rankings = [
            _make_ranking("R1", 1, regulatory_days="20"),
            _make_ranking("R2", 2, regulatory_days="25"),
            _make_ranking("R3", 3, regulatory_days="35"),
        ]
        policy = _policy_with_ladder()
        result = build_positions(rankings, policy)
        positions = result["positions"]
        # All three in reg_15_45
        assert all(p["reg_sub_bucket"] == "reg_15_45" for p in positions)
        # Equal weight within sub-bucket
        dollars = [p["target_dollars"] for p in positions]
        assert dollars[0] == pytest.approx(dollars[1], abs=1)
        assert dollars[1] == pytest.approx(dollars[2], abs=1)


# ---------------------------------------------------------------------------
# Test weekly summary Regulatory Ladder section
# ---------------------------------------------------------------------------


class TestWeeklySummaryLadder:
    def _make_pos(self, ticker, reg_days="60", reg_event="PDUFA", reg_sub="reg_46_90"):
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
            "regulatory_event_type": reg_event,
            "has_regulatory_upcoming_180d": "1",
            "regulatory_is_secondary": False,
            "reg_sub_bucket": reg_sub,
        }

    def _render(self, positions, tmp_path, ladder_enabled=True):
        positions_data = {
            "positions": positions,
            "summary": {"per_bucket": {}, "per_bucket_family": {}},
        }
        policy = {
            "account_usd": 100_000,
            "bucket_targets": {},
            "family_filter_mode": "secondary",
            "family_targets": {},
            "regulatory_ladder_enabled": ladder_enabled,
            "regulatory_bucket_caps_pct": {
                "reg_0_14": 0.35,
                "reg_15_45": 1.25,
            },
        }
        out = tmp_path / "weekly.md"
        write_weekly_summary("2026-03-08", positions_data, None, policy, {}, out)
        return out.read_text()

    def test_ladder_section_present(self, tmp_path):
        positions = [
            self._make_pos("R1", "10", "PDUFA", "reg_0_14"),
            self._make_pos("R2", "30", "FDA_ADCOM", "reg_15_45"),
        ]
        md = self._render(positions, tmp_path)
        assert "### Regulatory Ladder" in md
        assert "Reg 0-14d" in md
        assert "Reg 15-45d" in md

    def test_ladder_section_absent_when_disabled(self, tmp_path):
        positions = [self._make_pos("R1", "30", "PDUFA", "reg_15_45")]
        md = self._render(positions, tmp_path, ladder_enabled=False)
        assert "### Regulatory Ladder" not in md

    def test_ladder_top_holdings(self, tmp_path):
        positions = [
            self._make_pos("R1", "30", "PDUFA", "reg_15_45"),
        ]
        md = self._render(positions, tmp_path)
        assert "Reg 15-45d — top 1:" in md
        assert "R1" in md

    def test_ladder_shows_cap(self, tmp_path):
        positions = [
            self._make_pos("R1", "10", "PDUFA", "reg_0_14"),
        ]
        md = self._render(positions, tmp_path)
        assert "0.35%" in md
