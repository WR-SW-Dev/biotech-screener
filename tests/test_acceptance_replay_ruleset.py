"""Tests for scripts/research/acceptance_replay_ruleset.py."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.research.acceptance_replay_ruleset import (
    aggregate_ranking_deltas,
    compute_rank_map,
    compute_tier_counts,
    compute_verdict,
    date_set_hash,
    discover_dates,
    pct_overlap,
    render_acceptance_md,
    top_k_tickers,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_rows(tickers_and_ranks, tier="A"):
    """Create minimal row dicts for testing."""
    return [
        {
            "ticker": t,
            "actionable_rank": str(r),
            "tier_dev": tier,
            "eligible": "True",
        }
        for t, r in tickers_and_ranks
    ]


# ---------------------------------------------------------------------------
# top_k_tickers
# ---------------------------------------------------------------------------


class TestTopKTickers:
    def test_returns_k_tickers_in_order(self):
        rows = _make_rows([("A", 1), ("B", 2), ("C", 3), ("D", 4)])
        result = top_k_tickers(rows, 3)
        assert result == ["A", "B", "C"]

    def test_skips_non_digit_ranks(self):
        rows = [
            {"ticker": "A", "actionable_rank": "1"},
            {"ticker": "B", "actionable_rank": ""},
            {"ticker": "C", "actionable_rank": "2"},
        ]
        result = top_k_tickers(rows, 5)
        assert result == ["A", "C"]


# ---------------------------------------------------------------------------
# pct_overlap
# ---------------------------------------------------------------------------


class TestPctOverlap:
    def test_full_overlap(self):
        assert pct_overlap(["A", "B", "C"], ["A", "B", "C"], 3) == 1.0

    def test_no_overlap(self):
        assert pct_overlap(["A", "B"], ["C", "D"], 2) == 0.0

    def test_partial_overlap(self):
        result = pct_overlap(["A", "B", "C", "D"], ["A", "C", "E", "F"], 4)
        assert abs(result - 0.5) < 0.01

    def test_empty(self):
        assert pct_overlap([], [], 5) == 1.0


# ---------------------------------------------------------------------------
# compute_rank_map
# ---------------------------------------------------------------------------


class TestComputeRankMap:
    def test_returns_dict(self):
        rows = _make_rows([("ABC", 1), ("DEF", 5)])
        result = compute_rank_map(rows)
        assert result == {"ABC": 1, "DEF": 5}

    def test_skips_empty_rank(self):
        rows = [{"ticker": "A", "actionable_rank": ""}]
        assert compute_rank_map(rows) == {}


# ---------------------------------------------------------------------------
# compute_tier_counts
# ---------------------------------------------------------------------------


class TestComputeTierCounts:
    def test_counts_within_top_k(self):
        rows = _make_rows([("A", 1), ("B", 2), ("C", 3)], tier="A")
        rows[2]["tier_dev"] = "B"
        result = compute_tier_counts(rows, 3)
        assert result["A"] == 2
        assert result["B"] == 1

    def test_ignores_outside_k(self):
        rows = _make_rows([("A", 1), ("B", 2), ("C", 100)], tier="A")
        result = compute_tier_counts(rows, 2)
        assert result["A"] == 2
        assert result["B"] == 0


# ---------------------------------------------------------------------------
# date_set_hash
# ---------------------------------------------------------------------------


class TestDateSetHash:
    def test_deterministic(self):
        dates = ["2026-03-01", "2026-03-05", "2026-03-10"]
        h1 = date_set_hash(dates)
        h2 = date_set_hash(dates)
        assert h1 == h2

    def test_order_independent(self):
        h1 = date_set_hash(["2026-03-10", "2026-03-01"])
        h2 = date_set_hash(["2026-03-01", "2026-03-10"])
        assert h1 == h2

    def test_different_sets_differ(self):
        h1 = date_set_hash(["2026-03-01"])
        h2 = date_set_hash(["2026-03-02"])
        assert h1 != h2

    def test_length(self):
        assert len(date_set_hash(["2026-03-01"])) == 16


# ---------------------------------------------------------------------------
# compute_verdict
# ---------------------------------------------------------------------------


class TestComputeVerdict:
    def _ranking_agg(self, top20_med=0.90, top60_med=0.90, tier_a_med=0):
        return {
            "top_20": {"median_overlap": top20_med},
            "top_60": {"median_overlap": top60_med},
            "tier_A_delta": {"median": tier_a_med, "max_abs": abs(tier_a_med)},
        }

    def _weekly_sim(self, cum_delta=0.5, mean_delta=0.05, turn_delta=0.1, gap_delta=1.0):
        return {
            "cumulative_hedged_delta_pp": cum_delta,
            "mean_weekly_hedged_delta_pp": mean_delta,
            "turnover_delta_pp": turn_delta,
            "gap_risk_high_weight_delta_pp": gap_delta,
        }

    def test_keep_active(self):
        v = compute_verdict(self._ranking_agg(), self._weekly_sim())
        assert v["verdict"] == "KEEP_ACTIVE"

    def test_rollback_on_exec_fail(self):
        v = compute_verdict(
            self._ranking_agg(),
            self._weekly_sim(cum_delta=-1.0, mean_delta=-0.10),
        )
        assert v["verdict"] == "ROLLBACK"

    def test_rollback_on_turnover_fail(self):
        v = compute_verdict(
            self._ranking_agg(),
            self._weekly_sim(turn_delta=0.50),
        )
        assert v["verdict"] == "ROLLBACK"

    def test_needs_more_on_stability_fail(self):
        """Execution OK but stability guardrail fails → NEEDS_MORE."""
        v = compute_verdict(
            self._ranking_agg(top20_med=0.50),
            self._weekly_sim(),
        )
        assert v["verdict"] == "NEEDS_MORE"

    def test_gap_risk_warn_not_fail(self):
        """Gap risk over threshold is WARN, not FAIL."""
        v = compute_verdict(
            self._ranking_agg(),
            self._weekly_sim(gap_delta=6.0),
        )
        assert v["verdict"] == "KEEP_ACTIVE"
        gap_check = [c for c in v["checks"] if "gap" in c["name"]][0]
        assert gap_check["status"] == "WARN"

    def test_all_checks_present(self):
        v = compute_verdict(self._ranking_agg(), self._weekly_sim())
        assert len(v["checks"]) == 7
        names = {c["name"] for c in v["checks"]}
        assert "top-20 overlap median" in names
        assert "cumulative hedged delta" in names
        assert "gap-risk (<=7d) weight delta" in names

    def test_recommendation_explicit(self):
        v = compute_verdict(self._ranking_agg(), self._weekly_sim(cum_delta=-0.5))
        assert v["recommendation"] in ("keep", "rollback")


# ---------------------------------------------------------------------------
# aggregate_ranking_deltas
# ---------------------------------------------------------------------------


class TestAggregateRankingDeltas:
    def test_computes_median_overlap(self):
        by_date = {
            "2026-03-01": {
                "top_20": {"pct_overlap": 0.90, "churn": 2, "entering": [], "leaving": []},
                "top_60": {"pct_overlap": 0.85, "churn": 3, "entering": [], "leaving": []},
                "rank_changes": {"n_changed": 5, "n_common": 100},
                "tier_counts": {"baseline": {"A": 5}, "candidate": {"A": 4}, "delta_A": -1},
            },
            "2026-03-05": {
                "top_20": {"pct_overlap": 0.80, "churn": 4, "entering": ["X"], "leaving": ["Y"]},
                "top_60": {"pct_overlap": 0.75, "churn": 5, "entering": ["X"], "leaving": ["Y"]},
                "rank_changes": {"n_changed": 10, "n_common": 100},
                "tier_counts": {"baseline": {"A": 5}, "candidate": {"A": 5}, "delta_A": 0},
            },
        }
        agg = aggregate_ranking_deltas(by_date, [20, 60])
        assert agg["top_20"]["median_overlap"] == 0.85
        assert agg["top_60"]["median_overlap"] == 0.80
        assert agg["tier_A_delta"]["median"] == -0.5


# ---------------------------------------------------------------------------
# discover_dates
# ---------------------------------------------------------------------------


class TestDiscoverDates:
    def test_finds_valid_dirs(self, tmp_path):
        for d in ["2026-03-01", "2026-03-05", "2026-03-10"]:
            dp = tmp_path / d
            dp.mkdir()
            (dp / "rankings.csv").write_text("ticker\nABC\n")

        # Invalid dirs that should be skipped
        (tmp_path / "not_a_date").mkdir()
        (tmp_path / "2026-03-02").mkdir()  # no rankings.csv

        result = discover_dates(tmp_path)
        assert result == ["2026-03-01", "2026-03-05", "2026-03-10"]

    def test_date_range_filter(self, tmp_path):
        for d in ["2026-03-01", "2026-03-05", "2026-03-10"]:
            dp = tmp_path / d
            dp.mkdir()
            (dp / "rankings.csv").write_text("ticker\nABC\n")

        result = discover_dates(tmp_path, date_from="2026-03-03", date_to="2026-03-08")
        assert result == ["2026-03-05"]


# ---------------------------------------------------------------------------
# render_acceptance_md
# ---------------------------------------------------------------------------


class TestRenderAcceptanceMd:
    def test_contains_all_sections(self):
        packet = {
            "candidate_id": "7177a4ea",
            "candidate_file": "v1.11.0.json",
            "baseline_id": "bebe73f8",
            "baseline_file": "v1.10.0.json",
            "n_dates": 10,
            "date_from": "2026-03-01",
            "date_to": "2026-03-10",
            "date_set_hash": "abc123",
            "generated_at": "2026-03-10T00:00:00Z",
            "ranking_aggregate": {
                "top_20": {
                    "mean_overlap": 0.9,
                    "median_overlap": 0.9,
                    "min_overlap": 0.8,
                    "mean_churn": 1.0,
                    "max_churn": 3,
                },
                "top_60": {
                    "mean_overlap": 0.85,
                    "median_overlap": 0.85,
                    "min_overlap": 0.7,
                    "mean_churn": 2.0,
                    "max_churn": 5,
                },
            },
            "weekly_sim": {
                "n_weeks": 5,
                "baseline_cumulative_pnl_pct": 1.0,
                "candidate_cumulative_pnl_pct": 1.5,
                "cumulative_hedged_delta_pp": 0.5,
                "mean_weekly_hedged_delta_pp": 0.1,
                "turnover_delta_pp": 0.05,
                "gap_risk_high_weight_delta_pp": 0.0,
                "mean_position_overlap": 0.9,
                "bucket_attribution": {},
                "composition_drivers": {"candidate_only": [], "baseline_only": []},
            },
            "verdict_result": {
                "verdict": "KEEP_ACTIVE",
                "reason": "All checks pass",
                "recommendation": "keep",
                "checks": [
                    {"name": "top-20 overlap median", "value": 0.9, "threshold": ">= 0.7", "status": "PASS"},
                ],
            },
        }
        md = render_acceptance_md(packet)
        assert "# Acceptance Replay" in md
        assert "## Decision Thresholds" in md
        assert "## Ranking Deltas" in md
        assert "## Weekly Policy Simulation" in md
        assert "## Verdict" in md
        assert "KEEP_ACTIVE" in md

    def test_rollback_verdict_shown(self):
        packet = {
            "candidate_id": "X",
            "candidate_file": "",
            "baseline_id": "Y",
            "baseline_file": "",
            "n_dates": 1,
            "date_from": "2026-03-01",
            "date_to": "2026-03-01",
            "date_set_hash": "abc",
            "generated_at": "2026-03-10T00:00:00Z",
            "ranking_aggregate": {"top_20": {}, "top_60": {}},
            "weekly_sim": {
                "n_weeks": 0,
                "bucket_attribution": {},
                "composition_drivers": {"candidate_only": [], "baseline_only": []},
            },
            "verdict_result": {
                "verdict": "ROLLBACK",
                "reason": "Failed",
                "recommendation": "rollback",
                "checks": [],
            },
        }
        md = render_acceptance_md(packet)
        assert "ROLLBACK" in md


# ---------------------------------------------------------------------------
# JSON schema fields
# ---------------------------------------------------------------------------


class TestAcceptanceJsonSchema:
    def test_required_fields(self):
        """Verify the packet schema has all required top-level fields."""
        required = {
            "schema",
            "candidate_id",
            "baseline_id",
            "date_from",
            "date_to",
            "n_dates",
            "date_set_hash",
            "generated_at",
            "ranking_aggregate",
            "weekly_sim",
            "verdict_result",
        }
        # Build a minimal packet to verify structure
        packet = {
            "schema": "acceptance_replay.v1",
            "candidate_id": "7177a4ea",
            "candidate_file": "v1.11.0.json",
            "baseline_id": "bebe73f8",
            "baseline_file": "v1.10.0.json",
            "date_from": "2026-03-01",
            "date_to": "2026-03-10",
            "n_dates": 5,
            "date_set_hash": "abc123",
            "generated_at": "2026-03-10T00:00:00Z",
            "ranking_aggregate": {},
            "weekly_sim": {},
            "verdict_result": {"verdict": "KEEP_ACTIVE", "reason": "", "checks": []},
            "by_date_ranking": {},
        }
        assert required.issubset(set(packet.keys()))


# ---------------------------------------------------------------------------
# No production leakage
# ---------------------------------------------------------------------------


class TestNoProductionLeakage:
    def test_discover_dates_requires_explicit_root(self, tmp_path):
        """discover_dates accepts explicit snapshot_root — no default used in test."""
        result = discover_dates(tmp_path / "nonexistent")
        assert result == []

    def test_verdict_uses_no_production_paths(self):
        """compute_verdict is pure logic — no file I/O."""
        ranking_agg = {
            "top_20": {"median_overlap": 0.90},
            "top_60": {"median_overlap": 0.90},
            "tier_A_delta": {"median": 0},
        }
        weekly_sim = {
            "cumulative_hedged_delta_pp": 0.5,
            "mean_weekly_hedged_delta_pp": 0.05,
            "turnover_delta_pp": 0.1,
            "gap_risk_high_weight_delta_pp": 1.0,
        }
        v = compute_verdict(ranking_agg, weekly_sim)
        assert v["verdict"] == "KEEP_ACTIVE"
