"""Tests for regulatory event resolution handling.

Verifies:
1. _is_regulatory_resolved() detection logic
2. Resolved names excluded from positions (0% target)
3. Resolved names tracked in summary
4. Weekly summary "Resolved Regulatory" section
5. Resolution disabled when policy flag is off
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.live_shadow_portfolio import _is_regulatory_resolved, build_positions, write_weekly_summary

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
) -> dict:
    return {
        "ticker": ticker,
        "actionable_rank": str(rank),
        "eligible": "1",
        "catalyst_family": catalyst_family,
        "catalyst_days": catalyst_days,
        "catalyst_mode": catalyst_mode,
        "catalyst_bucket": "binary_91_180",
        "has_regulatory_upcoming_180d": has_regulatory,
        "regulatory_days": regulatory_days,
        "regulatory_event_type": regulatory_event_type,
        "tier_any": "A",
        "size_band": "M",
        "mom_state": "neutral",
        "de_beta_xbi_60d_source": "computed",
    }


def _policy_with_resolution(enabled=True, account_usd=100_000):
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
        "family_targets": {},
        "family_filter_mode": "secondary",
        "gap_risk": {"high_days": 7, "high_cap_pct": 0.5},
        "regulatory_ladder_enabled": False,
        "regulatory_bucket_caps_pct": {},
        "regulatory_bucket_weights": {},
        "regulatory_resolution_enabled": enabled,
        "rebalance_buffer_ranks": 30,
        "bucket_hysteresis_days": 7,
    }


# ---------------------------------------------------------------------------
# Test _is_regulatory_resolved
# ---------------------------------------------------------------------------


class TestIsRegulatoryResolved:
    def test_negative_days_resolved(self):
        assert _is_regulatory_resolved({"regulatory_days": "-5"}) is True

    def test_zero_days_resolved(self):
        assert _is_regulatory_resolved({"regulatory_days": "0"}) is True

    def test_positive_days_not_resolved(self):
        assert _is_regulatory_resolved({"regulatory_days": "30"}) is False

    def test_empty_days_not_resolved(self):
        assert _is_regulatory_resolved({"regulatory_days": ""}) is False

    def test_missing_key_not_resolved(self):
        assert _is_regulatory_resolved({}) is False

    def test_non_numeric_not_resolved(self):
        assert _is_regulatory_resolved({"regulatory_days": "abc"}) is False

    def test_small_negative_resolved(self):
        assert _is_regulatory_resolved({"regulatory_days": "-0.5"}) is True


# ---------------------------------------------------------------------------
# Test resolution filtering in build_positions
# ---------------------------------------------------------------------------


class TestResolutionFiltering:
    def test_resolved_name_excluded_from_positions(self):
        """A REGULATORY name with days <= 0 should not appear in positions."""
        rankings = [
            _make_ranking("RESOLVED", 1, regulatory_days="-3"),
            _make_ranking("ACTIVE", 2, regulatory_days="60"),
        ]
        policy = _policy_with_resolution(enabled=True)
        result = build_positions(rankings, policy)
        tickers = [p["ticker"] for p in result["positions"]]
        assert "RESOLVED" not in tickers
        assert "ACTIVE" in tickers

    def test_resolved_name_in_summary(self):
        """Resolved names should be tracked in summary."""
        rankings = [
            _make_ranking("RESOLVED", 1, regulatory_days="0", regulatory_event_type="PDUFA"),
            _make_ranking("ACTIVE", 2, regulatory_days="60"),
        ]
        policy = _policy_with_resolution(enabled=True)
        result = build_positions(rankings, policy)
        resolved = result["summary"]["resolved_regulatory"]
        assert len(resolved) == 1
        assert resolved[0]["ticker"] == "RESOLVED"
        assert resolved[0]["regulatory_event_type"] == "PDUFA"

    def test_resolution_disabled_keeps_name(self):
        """When resolution is disabled, resolved names stay in positions."""
        rankings = [
            _make_ranking("RESOLVED", 1, regulatory_days="-3"),
        ]
        policy = _policy_with_resolution(enabled=False)
        result = build_positions(rankings, policy)
        tickers = [p["ticker"] for p in result["positions"]]
        assert "RESOLVED" in tickers
        assert result["summary"]["resolved_regulatory"] == []

    def test_clinical_not_affected_by_resolution(self):
        """CLINICAL names with negative regulatory_days should NOT be resolved."""
        rankings = [
            _make_ranking(
                "CLIN1",
                1,
                catalyst_family="CLINICAL",
                has_regulatory="0",
                regulatory_days="-5",
            ),
        ]
        policy = _policy_with_resolution(enabled=True)
        result = build_positions(rankings, policy)
        tickers = [p["ticker"] for p in result["positions"]]
        assert "CLIN1" in tickers

    def test_multiple_resolved_names(self):
        """Multiple resolved names all excluded and tracked."""
        rankings = [
            _make_ranking("R1", 1, regulatory_days="-10", regulatory_event_type="PDUFA"),
            _make_ranking("R2", 2, regulatory_days="0", regulatory_event_type="FDA_ADCOM"),
            _make_ranking("R3", 3, regulatory_days="60"),
        ]
        policy = _policy_with_resolution(enabled=True)
        result = build_positions(rankings, policy)
        tickers = [p["ticker"] for p in result["positions"]]
        assert "R1" not in tickers
        assert "R2" not in tickers
        assert "R3" in tickers
        assert len(result["summary"]["resolved_regulatory"]) == 2

    def test_budget_reflows_after_resolution(self):
        """Resolved names' share should not leave cash drag."""
        rankings = [
            _make_ranking("RESOLVED", 1, regulatory_days="-3"),
            _make_ranking("ACTIVE", 2, regulatory_days="60"),
        ]
        policy = _policy_with_resolution(enabled=True)
        result = build_positions(rankings, policy)
        # ACTIVE should get full bucket budget (50% of $100k = $50k)
        active = next(p for p in result["positions"] if p["ticker"] == "ACTIVE")
        assert active["target_dollars"] == pytest.approx(50_000, abs=100)

    def test_secondary_regulatory_resolved(self):
        """A secondary REGULATORY name (CLINICAL primary) with days <= 0
        should also be resolved."""
        rankings = [
            _make_ranking(
                "DUAL",
                1,
                catalyst_family="CLINICAL",
                has_regulatory="1",
                regulatory_days="-2",
                regulatory_event_type="PDUFA",
            ),
        ]
        policy = _policy_with_resolution(enabled=True)
        result = build_positions(rankings, policy)
        tickers = [p["ticker"] for p in result["positions"]]
        assert "DUAL" not in tickers
        assert len(result["summary"]["resolved_regulatory"]) == 1


# ---------------------------------------------------------------------------
# Test weekly summary Resolved section
# ---------------------------------------------------------------------------


class TestWeeklySummaryResolved:
    def _render(self, positions, summary, tmp_path, policy=None):
        positions_data = {
            "positions": positions,
            "summary": summary or {"per_bucket": {}, "per_bucket_family": {}},
        }
        pol = policy or {
            "account_usd": 100_000,
            "bucket_targets": {},
            "family_filter_mode": "secondary",
            "family_targets": {},
            "regulatory_ladder_enabled": False,
            "regulatory_resolution_enabled": True,
        }
        out = tmp_path / "weekly.md"
        write_weekly_summary("2026-03-08", positions_data, None, pol, {}, out)
        return out.read_text()

    def test_resolved_section_present(self, tmp_path):
        summary = {
            "per_bucket": {},
            "per_bucket_family": {},
            "resolved_regulatory": [
                {"ticker": "ACME", "regulatory_event_type": "PDUFA", "regulatory_days": "-3"},
            ],
        }
        md = self._render([], summary, tmp_path)
        assert "## Resolved Regulatory (Demoted to 0%)" in md
        assert "1 name(s)" in md
        assert "ACME" in md
        assert "PDUFA" in md

    def test_no_resolved_section_when_empty(self, tmp_path):
        summary = {
            "per_bucket": {},
            "per_bucket_family": {},
            "resolved_regulatory": [],
        }
        md = self._render([], summary, tmp_path)
        assert "Resolved Regulatory" not in md

    def test_multiple_resolved_names_listed(self, tmp_path):
        summary = {
            "per_bucket": {},
            "per_bucket_family": {},
            "resolved_regulatory": [
                {"ticker": "R1", "regulatory_event_type": "PDUFA", "regulatory_days": "-3"},
                {"ticker": "R2", "regulatory_event_type": "FDA_ADCOM", "regulatory_days": "0"},
            ],
        }
        md = self._render([], summary, tmp_path)
        assert "2 name(s)" in md
        assert "R1" in md
        assert "R2" in md
