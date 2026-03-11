"""Tests for family-targeted sleeve allocation in build_positions().

Verifies:
1. Secondary mode classifies tickers correctly via _effective_family()
2. Family-targeted allocation respects 70/30 split
3. Reflow works when a family has 0 eligible names
4. Deterministic output (sorted by rank, then ticker)
5. Weekly summary contains Regulatory Sleeve section
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.live_shadow_portfolio import _effective_family, build_positions, write_weekly_summary

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ranking(
    ticker: str,
    rank: int = 1,
    catalyst_family: str = "CLINICAL",
    catalyst_days: str = "100",
    catalyst_mode: str = "specific_days",
    has_regulatory: str = "0",
    regulatory_days: str = "",
    regulatory_event_type: str = "",
    tier_any: str = "A",
    bucket_override: str = "",
) -> dict:
    """Build a minimal rankings row that classify_action_bucket will bucket."""
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
        "tier_any": tier_any,
        "size_band": "M",
        "mom_state": "neutral",
        "de_beta_xbi_60d_source": "computed",
    }


def _policy_with_family_targets(
    family_targets=None,
    family_filter_mode="secondary",
    account_usd=100_000,
    bucket_targets=None,
    bucket_top_k=None,
):
    """Build a policy dict with family targets."""
    return {
        "account_usd": account_usd,
        "bucket_targets": bucket_targets
        or {
            "binary_91_180": 0.50,
            "binary_31_90": 0.30,
            "binary_0_30": 0.10,
            "less_binary": 0.10,
        },
        "bucket_top_k": bucket_top_k
        or {
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
        "family_targets": family_targets or {},
        "family_filter_mode": family_filter_mode,
        "gap_risk": {"high_days": 7, "high_cap_pct": 0.5},
        "rebalance_buffer_ranks": 30,
        "bucket_hysteresis_days": 7,
    }


# ---------------------------------------------------------------------------
# Test _effective_family
# ---------------------------------------------------------------------------


class TestEffectiveFamilyPortfolio:
    """Tests for _effective_family() in live_shadow_portfolio."""

    def test_primary_mode_uses_catalyst_family(self):
        row = {"catalyst_family": "CLINICAL", "has_regulatory_upcoming_180d": "1"}
        assert _effective_family(row, "primary") == "CLINICAL"

    def test_secondary_promotes_regulatory(self):
        row = {"catalyst_family": "CLINICAL", "has_regulatory_upcoming_180d": "1"}
        assert _effective_family(row, "secondary") == "REGULATORY"

    def test_secondary_no_flag_keeps_primary(self):
        row = {"catalyst_family": "CLINICAL", "has_regulatory_upcoming_180d": "0"}
        assert _effective_family(row, "secondary") == "CLINICAL"

    def test_secondary_missing_flag_keeps_primary(self):
        row = {"catalyst_family": "CLINICAL"}
        assert _effective_family(row, "secondary") == "CLINICAL"

    def test_primary_regulatory_stays_regulatory(self):
        row = {"catalyst_family": "REGULATORY", "has_regulatory_upcoming_180d": "1"}
        assert _effective_family(row, "secondary") == "REGULATORY"


# ---------------------------------------------------------------------------
# Test family-targeted allocation
# ---------------------------------------------------------------------------


class TestFamilyTargetedAllocation:
    """Tests for build_positions() with family_targets."""

    def test_70_30_split_regulatory_clinical(self):
        """binary_91_180 with 70% REGULATORY / 30% CLINICAL."""
        rankings = [
            _make_ranking(
                "REG1", 1, "REGULATORY", has_regulatory="1", regulatory_days="60", regulatory_event_type="PDUFA"
            ),
            _make_ranking(
                "REG2", 2, "REGULATORY", has_regulatory="1", regulatory_days="90", regulatory_event_type="FDA_ADCOM"
            ),
            _make_ranking("CLIN1", 3, "CLINICAL"),
            _make_ranking("CLIN2", 4, "CLINICAL"),
        ]
        policy = _policy_with_family_targets(
            family_targets={"binary_91_180": {"REGULATORY": 0.70, "CLINICAL": 0.30}},
            account_usd=100_000,
        )
        result = build_positions(rankings, policy)
        positions = result["positions"]
        assert len(positions) == 4

        reg_pos = [p for p in positions if p["effective_family"] == "REGULATORY"]
        clin_pos = [p for p in positions if p["effective_family"] == "CLINICAL"]
        reg_dollars = sum(p["target_dollars"] for p in reg_pos)
        clin_dollars = sum(p["target_dollars"] for p in clin_pos)
        total = reg_dollars + clin_dollars

        # 70% of 50% of $100k = $35k for REGULATORY
        assert reg_dollars == pytest.approx(35_000, abs=100)
        # 30% of 50% of $100k = $15k for CLINICAL
        assert clin_dollars == pytest.approx(15_000, abs=100)
        # Total bucket = 50% of $100k
        assert total == pytest.approx(50_000, abs=100)

    def test_secondary_mode_clinical_primary_promoted(self):
        """A ticker with catalyst_family=CLINICAL but has_regulatory=1
        should be allocated as REGULATORY in secondary mode."""
        rankings = [
            # Primary CLINICAL, but secondary REGULATORY
            _make_ranking(
                "DUAL1", 1, "CLINICAL", has_regulatory="1", regulatory_days="45", regulatory_event_type="PDUFA"
            ),
            _make_ranking("CLIN1", 2, "CLINICAL"),
        ]
        policy = _policy_with_family_targets(
            family_targets={"binary_91_180": {"REGULATORY": 0.70, "CLINICAL": 0.30}},
            family_filter_mode="secondary",
        )
        result = build_positions(rankings, policy)
        positions = result["positions"]

        dual = next(p for p in positions if p["ticker"] == "DUAL1")
        assert dual["effective_family"] == "REGULATORY"
        assert dual["regulatory_is_secondary"] is True

        clin = next(p for p in positions if p["ticker"] == "CLIN1")
        assert clin["effective_family"] == "CLINICAL"
        assert clin["regulatory_is_secondary"] is False

    def test_reflow_when_regulatory_empty(self):
        """If no REGULATORY names, their 70% share reflows to CLINICAL."""
        rankings = [
            _make_ranking("CLIN1", 1, "CLINICAL"),
            _make_ranking("CLIN2", 2, "CLINICAL"),
        ]
        policy = _policy_with_family_targets(
            family_targets={"binary_91_180": {"REGULATORY": 0.70, "CLINICAL": 0.30}},
        )
        result = build_positions(rankings, policy)
        positions = result["positions"]
        assert len(positions) == 2

        # All dollars should go to CLINICAL (full reflow)
        total = sum(p["target_dollars"] for p in positions)
        # 50% of $100k = $50k total for bucket
        assert total == pytest.approx(50_000, abs=100)
        # All positions should be CLINICAL
        assert all(p["effective_family"] == "CLINICAL" for p in positions)

    def test_reflow_when_clinical_empty(self):
        """If no CLINICAL names, their 30% share reflows to REGULATORY."""
        rankings = [
            _make_ranking("REG1", 1, "REGULATORY", has_regulatory="1", regulatory_days="60"),
            _make_ranking("REG2", 2, "REGULATORY", has_regulatory="1", regulatory_days="90"),
        ]
        policy = _policy_with_family_targets(
            family_targets={"binary_91_180": {"REGULATORY": 0.70, "CLINICAL": 0.30}},
        )
        result = build_positions(rankings, policy)
        positions = result["positions"]
        total = sum(p["target_dollars"] for p in positions)
        assert total == pytest.approx(50_000, abs=100)
        assert all(p["effective_family"] == "REGULATORY" for p in positions)

    def test_no_family_targets_flat_allocation(self):
        """Without family_targets, allocation is flat (equal weight)."""
        rankings = [
            _make_ranking("REG1", 1, "REGULATORY"),
            _make_ranking("CLIN1", 2, "CLINICAL"),
        ]
        policy = _policy_with_family_targets(family_targets={})
        result = build_positions(rankings, policy)
        positions = result["positions"]
        # Each gets equal share of bucket allocation
        dollars = [p["target_dollars"] for p in positions]
        assert dollars[0] == pytest.approx(dollars[1], abs=1)

    def test_deterministic_output(self):
        """Positions should be deterministic (sorted by rank, then ticker)."""
        rankings = [
            _make_ranking("CLIN2", 4, "CLINICAL"),
            _make_ranking("CLIN1", 3, "CLINICAL"),
            _make_ranking("REG2", 2, "REGULATORY", has_regulatory="1"),
            _make_ranking("REG1", 1, "REGULATORY", has_regulatory="1"),
        ]
        policy = _policy_with_family_targets(
            family_targets={"binary_91_180": {"REGULATORY": 0.70, "CLINICAL": 0.30}},
        )
        result1 = build_positions(rankings, policy)
        result2 = build_positions(rankings, policy)
        tickers1 = [p["ticker"] for p in result1["positions"]]
        tickers2 = [p["ticker"] for p in result2["positions"]]
        assert tickers1 == tickers2

    def test_per_bucket_family_summary(self):
        """Summary should include per_bucket_family breakdown."""
        rankings = [
            _make_ranking("REG1", 1, "REGULATORY", has_regulatory="1"),
            _make_ranking("CLIN1", 2, "CLINICAL"),
        ]
        policy = _policy_with_family_targets(
            family_targets={"binary_91_180": {"REGULATORY": 0.70, "CLINICAL": 0.30}},
        )
        result = build_positions(rankings, policy)
        pbf = result["summary"]["per_bucket_family"]
        assert "binary_91_180__REGULATORY" in pbf
        assert "binary_91_180__CLINICAL" in pbf
        assert pbf["binary_91_180__REGULATORY"]["count"] == 1
        assert pbf["binary_91_180__CLINICAL"]["count"] == 1

    def test_family_targets_only_affects_targeted_buckets(self):
        """Buckets without family_targets should use flat allocation."""
        # binary_31_90 rows
        rankings = [
            _make_ranking(
                "REG1", 1, "REGULATORY", catalyst_days="60", has_regulatory="1", bucket_override="binary_31_90"
            ),
            _make_ranking("CLIN1", 2, "CLINICAL", catalyst_days="60", bucket_override="binary_31_90"),
        ]
        policy = _policy_with_family_targets(
            # Only binary_91_180 has targets, not binary_31_90
            family_targets={"binary_91_180": {"REGULATORY": 0.70, "CLINICAL": 0.30}},
        )
        result = build_positions(rankings, policy)
        positions = result["positions"]
        # Should be equal weight (flat allocation for binary_31_90)
        dollars = [p["target_dollars"] for p in positions]
        assert dollars[0] == pytest.approx(dollars[1], abs=1)

    def test_family_overrides_cap_applied_within_family(self):
        """Per-family name_cap_pct from family_overrides should be respected."""
        rankings = [
            _make_ranking("REG1", 1, "REGULATORY", has_regulatory="1"),
        ]
        policy = _policy_with_family_targets(
            family_targets={"binary_91_180": {"REGULATORY": 0.70, "CLINICAL": 0.30}},
        )
        # Add a family override with a tight cap
        policy["family_overrides"] = {
            "binary_91_180": {
                "REGULATORY": {"max_k": 5, "name_cap_pct": 1.0},
            }
        }
        result = build_positions(rankings, policy)
        positions = result["positions"]
        # With cap at 1.0%, max target = $1,000 on $100k
        assert positions[0]["weight_pct"] <= 1.0
        assert positions[0]["target_dollars"] <= 1_000 + 1  # float tolerance


# ---------------------------------------------------------------------------
# Test weekly summary Regulatory Sleeve section
# ---------------------------------------------------------------------------


class TestWeeklySummaryRegulatorySleeve:

    def _make_pos(
        self,
        ticker,
        bucket="binary_91_180",
        eff_family="CLINICAL",
        reg_days="",
        reg_event="",
        has_reg="0",
        is_secondary=False,
    ):
        return {
            "ticker": ticker,
            "bucket": bucket,
            "catalyst_family": "CLINICAL" if eff_family != "REGULATORY" else "REGULATORY",
            "effective_family": eff_family,
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
            "has_regulatory_upcoming_180d": has_reg,
            "regulatory_is_secondary": is_secondary,
        }

    def _render(self, positions, tmp_path, policy=None):
        positions_data = {
            "positions": positions,
            "summary": {"per_bucket": {}, "per_bucket_family": {}},
        }
        pol = policy or {
            "account_usd": 100_000,
            "bucket_targets": {},
            "family_filter_mode": "secondary",
            "family_targets": {
                "binary_91_180": {"REGULATORY": 0.70, "CLINICAL": 0.30},
            },
        }
        out = tmp_path / "weekly.md"
        write_weekly_summary("2026-03-08", positions_data, None, pol, {}, out)
        return out.read_text()

    def test_sleeve_table_present(self, tmp_path):
        positions = [
            self._make_pos("REG1", eff_family="REGULATORY", reg_days="30", reg_event="PDUFA", has_reg="1"),
            self._make_pos("CLIN1"),
        ]
        md = self._render(positions, tmp_path)
        assert "### Regulatory Sleeve by Bucket" in md
        assert "Reg Names" in md
        assert "Reg Target" in md

    def test_sleeve_shows_secondary_flag(self, tmp_path):
        positions = [
            self._make_pos(
                "DUAL1", eff_family="REGULATORY", reg_days="30", reg_event="PDUFA", has_reg="1", is_secondary=True
            ),
        ]
        md = self._render(positions, tmp_path)
        assert "Secondary?" in md
        assert "| yes |" in md

    def test_sleeve_avg_regulatory_days(self, tmp_path):
        positions = [
            self._make_pos("REG1", eff_family="REGULATORY", reg_days="30", reg_event="PDUFA", has_reg="1"),
            self._make_pos("REG2", eff_family="REGULATORY", reg_days="90", reg_event="FDA_ADCOM", has_reg="1"),
        ]
        md = self._render(positions, tmp_path)
        assert "Avg regulatory days (held)" in md
        assert "60d" in md  # (30+90)/2 = 60

    def test_no_sleeve_section_in_primary_mode(self, tmp_path):
        """When family_filter_mode=primary and no family_targets, no sleeve table."""
        positions = [self._make_pos("CLIN1")]
        policy = {
            "account_usd": 100_000,
            "bucket_targets": {},
            "family_filter_mode": "primary",
            "family_targets": {},
        }
        md = self._render(positions, tmp_path, policy=policy)
        assert "### Regulatory Sleeve by Bucket" not in md

    def test_coverage_section_still_present(self, tmp_path):
        """The coverage header should still be there regardless of mode."""
        positions = [self._make_pos("CLIN1")]
        md = self._render(positions, tmp_path)
        assert "## Secondary Regulatory Coverage" in md


# ---------------------------------------------------------------------------
# Max_k reflow: when one family is empty, its max_k slots go to others
# ---------------------------------------------------------------------------


class TestMaxKReflow:
    """Test that family max_k reflows when a configured family has 0 names."""

    def _make_row(self, ticker, rank, family="CLINICAL", cat_days="100"):
        return _make_ranking(
            ticker=ticker,
            rank=rank,
            catalyst_family=family,
            catalyst_days=cat_days,
            has_regulatory="1" if family == "REGULATORY" else "0",
            regulatory_days=cat_days if family == "REGULATORY" else "",
        )

    def _policy(self, max_k_reg=8, max_k_clin=12, top_k=20):
        return {
            "account_usd": 100_000,
            "bucket_targets": {
                "binary_91_180": 1.0,
                "binary_31_90": 0.0,
                "binary_0_30": 0.0,
                "less_binary": 0.0,
            },
            "bucket_top_k": {"binary_91_180": top_k},
            "bucket_name_caps": {"binary_91_180": 50.0},
            "family_overrides": {
                "binary_91_180": {
                    "REGULATORY": {"max_k": max_k_reg, "name_cap_pct": 50.0},
                    "CLINICAL": {"max_k": max_k_clin, "name_cap_pct": 50.0},
                },
            },
            "family_targets": {},
            "family_filter_mode": "secondary",
            "gap_risk": {"high_days": 7, "high_cap_pct": 0.5},
            "rebalance_buffer_ranks": 30,
            "bucket_hysteresis_days": 7,
        }

    def test_both_families_present_no_reflow(self):
        """When both families have names, max_k caps each family independently."""
        # 20 CLIN names at ranks 1-20, 20 REG at ranks 21-40 → top_k=40
        rankings = [
            *[self._make_row(f"C{i}", i, "CLINICAL") for i in range(1, 21)],
            *[self._make_row(f"R{i}", i + 20, "REGULATORY") for i in range(1, 21)],
        ]
        result = build_positions(rankings, self._policy(max_k_reg=8, max_k_clin=12, top_k=40))
        positions = result["positions"]
        fams = {}
        for p in positions:
            fams.setdefault(p["effective_family"], 0)
            fams[p["effective_family"]] += 1
        assert fams.get("REGULATORY", 0) == 8
        assert fams.get("CLINICAL", 0) == 12

    def test_zero_regulatory_reflows_to_clinical(self):
        """When REGULATORY has 0 names, CLINICAL gets REGULATORY's max_k slots."""
        rankings = [self._make_row(f"C{i}", i, "CLINICAL") for i in range(1, 25)]
        # max_k_reg=8, max_k_clin=12 → with reflow, CLINICAL gets 20 (=12+8)
        result = build_positions(rankings, self._policy(max_k_reg=8, max_k_clin=12, top_k=20))
        positions = result["positions"]
        assert len(positions) == 20  # full top_k

    def test_zero_clinical_reflows_to_regulatory(self):
        """When CLINICAL has 0 names, REGULATORY gets CLINICAL's max_k slots."""
        rankings = [self._make_row(f"R{i}", i, "REGULATORY") for i in range(1, 25)]
        result = build_positions(rankings, self._policy(max_k_reg=8, max_k_clin=12, top_k=20))
        positions = result["positions"]
        assert len(positions) == 20

    def test_reflow_respects_top_k(self):
        """Reflowed max_k should not exceed bucket top_k."""
        rankings = [self._make_row(f"C{i}", i, "CLINICAL") for i in range(1, 30)]
        # max_k_reg=15, max_k_clin=15 → 30 total but top_k=20
        result = build_positions(rankings, self._policy(max_k_reg=15, max_k_clin=15, top_k=20))
        positions = result["positions"]
        assert len(positions) <= 20

    def test_partial_reflow(self):
        """When one family has fewer names than max_k, excess slots DON'T reflow
        (reflow only happens when family has 0 names)."""
        rankings = [
            *[self._make_row(f"R{i}", i, "REGULATORY") for i in range(1, 4)],  # 3 REG
            *[self._make_row(f"C{i}", i + 10, "CLINICAL") for i in range(1, 20)],  # 19 CLIN
        ]
        result = build_positions(rankings, self._policy(max_k_reg=8, max_k_clin=12))
        positions = result["positions"]
        fams = {}
        for p in positions:
            fams.setdefault(p["effective_family"], 0)
            fams[p["effective_family"]] += 1
        # REG has 3 (< max_k=8), CLIN capped at 12 — no reflow because REG is present
        assert fams.get("REGULATORY", 0) == 3
        assert fams.get("CLINICAL", 0) == 12
