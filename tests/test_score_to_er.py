"""
Dedicated unit tests for common/score_to_er.py

Covers: _norm_ppf, _safe_float, _rank_base, attach_rank_and_z,
        attach_expected_return, compute_expected_returns, validate_er_output.

Edge cases: empty input, single row, ties, clamping, degraded mode,
            monotonicity, deterministic ordering, z-score symmetry,
            score_breakdown preference, non-numeric scores.
"""

from __future__ import annotations

import copy
from decimal import Decimal

import pytest

from common.score_to_er import (
    _norm_ppf,
    _rank_base,
    _safe_float,
    attach_expected_return,
    attach_rank_and_z,
    compute_expected_returns,
    validate_er_output,
)

# =====================================================================
# Helpers
# =====================================================================


def _make_rows(n, scores=None, tickers=None):
    """Build minimal rows with composite_score and ticker."""
    rows = []
    for i in range(n):
        score = scores[i] if scores else float(n - i)
        ticker = tickers[i] if tickers else f"T{i:03d}"
        rows.append({"ticker": ticker, "composite_score": score})
    return rows


# =====================================================================
# _norm_ppf
# =====================================================================


class TestNormPpf:
    """Inverse normal CDF (Acklam approximation)."""

    def test_median(self):
        """ppf(0.5) == 0."""
        assert abs(_norm_ppf(0.5)) < 1e-8

    def test_symmetry(self):
        """ppf(p) == -ppf(1-p) for symmetric quantiles."""
        for p in [0.01, 0.05, 0.10, 0.25]:
            assert abs(_norm_ppf(p) + _norm_ppf(1.0 - p)) < 1e-6

    def test_known_quantiles(self):
        """Spot-check against well-known z values."""
        # z = 1.96 at p ~ 0.975
        assert abs(_norm_ppf(0.975) - 1.96) < 0.01
        # z = -1.645 at p ~ 0.05
        assert abs(_norm_ppf(0.05) - (-1.645)) < 0.01
        # z = 2.326 at p ~ 0.99
        assert abs(_norm_ppf(0.99) - 2.326) < 0.01

    def test_monotonic(self):
        """ppf is strictly increasing."""
        ps = [i / 100.0 for i in range(1, 100)]
        zs = [_norm_ppf(p) for p in ps]
        for i in range(len(zs) - 1):
            assert zs[i] < zs[i + 1], f"Not monotonic at p={ps[i]}"

    def test_edge_zero(self):
        """p=0 returns practical lower bound."""
        assert _norm_ppf(0.0) == -10.0

    def test_edge_one(self):
        """p=1 returns practical upper bound."""
        assert _norm_ppf(1.0) == 10.0

    def test_negative_p(self):
        """Negative p treated as p=0."""
        assert _norm_ppf(-0.5) == -10.0

    def test_p_above_one(self):
        """p > 1 treated as p=1."""
        assert _norm_ppf(1.5) == 10.0

    def test_tail_accuracy(self):
        """Lower and upper tail regions produce reasonable z values."""
        # p = 0.001 should give z ~ -3.09
        assert abs(_norm_ppf(0.001) - (-3.09)) < 0.02
        # p = 0.999 should give z ~ 3.09
        assert abs(_norm_ppf(0.999) - 3.09) < 0.02


# =====================================================================
# _safe_float
# =====================================================================


class TestSafeFloat:

    def test_numeric_string(self):
        assert _safe_float("3.14") == 3.14

    def test_int(self):
        assert _safe_float(42) == 42.0

    def test_none_default(self):
        assert _safe_float(None) == 0.0

    def test_none_custom_default(self):
        assert _safe_float(None, default=-1.0) == -1.0

    def test_non_numeric_string(self):
        assert _safe_float("abc") == 0.0

    def test_empty_string(self):
        assert _safe_float("") == 0.0

    def test_float_passthrough(self):
        assert _safe_float(2.718) == 2.718

    def test_negative(self):
        assert _safe_float("-5.5") == -5.5


# =====================================================================
# _rank_base
# =====================================================================


class TestRankBase:

    def test_simple_composite_score(self):
        row = {"composite_score": 75.0}
        assert _rank_base(row) == 75.0

    def test_prefers_post_cap_score(self):
        """score_breakdown.final.post_cap_score takes priority."""
        row = {
            "composite_score": 50.0,
            "score_breakdown": {"final": {"post_cap_score": 80.0}},
        }
        assert _rank_base(row) == 80.0

    def test_falls_back_to_pre_penalty(self):
        """Falls back to pre_penalty_score when post_cap is missing."""
        row = {
            "composite_score": 50.0,
            "score_breakdown": {"final": {"pre_penalty_score": 70.0}},
        }
        assert _rank_base(row) == 70.0

    def test_no_breakdown(self):
        """Without score_breakdown, uses composite_score."""
        row = {"composite_score": "60.5"}
        assert _rank_base(row) == 60.5

    def test_empty_breakdown(self):
        """Empty breakdown falls through to composite_score."""
        row = {"composite_score": 40.0, "score_breakdown": {}}
        assert _rank_base(row) == 40.0

    def test_missing_score(self):
        """No score at all returns 0.0."""
        assert _rank_base({}) == 0.0

    def test_string_score_in_breakdown(self):
        row = {
            "composite_score": 10.0,
            "score_breakdown": {"final": {"post_cap_score": "99.9"}},
        }
        assert _rank_base(row) == 99.9


# =====================================================================
# attach_rank_and_z — core ranking
# =====================================================================


class TestAttachRankAndZ:

    def test_empty_input(self):
        """Empty list returns clean metadata, no crash."""
        rows = []
        result = attach_rank_and_z(rows)
        assert result["valid_count"] == 0
        assert result["invalid_count"] == 0
        assert result["degraded"] is False
        assert result["warnings"] == []

    def test_single_row(self):
        """Single row gets percentile 0.5, z ~ 0."""
        rows = _make_rows(1, scores=[50.0])
        result = attach_rank_and_z(rows)
        assert result["valid_count"] == 1
        assert result["degraded"] is False
        # p = (1 - 1 + 0.5) / 1 = 0.5
        assert rows[0]["score_rank_pct"] == pytest.approx(0.5, abs=0.01)
        assert abs(rows[0]["score_z"]) < 0.01

    def test_two_rows_ordering(self):
        """Higher score gets higher percentile and positive z."""
        rows = _make_rows(2, scores=[100.0, 20.0], tickers=["HI", "LO"])
        attach_rank_and_z(rows)
        hi = next(r for r in rows if r["ticker"] == "HI")
        lo = next(r for r in rows if r["ticker"] == "LO")
        assert hi["score_rank_pct"] > lo["score_rank_pct"]
        assert hi["score_z"] > lo["score_z"]

    def test_monotonicity_large(self):
        """Percentile and z are monotonically decreasing with rank."""
        n = 50
        rows = _make_rows(n)  # scores: 50, 49, ..., 1
        attach_rank_and_z(rows)
        ordered = sorted(rows, key=lambda r: -r["score_rank_pct"])
        for i in range(len(ordered) - 1):
            assert ordered[i]["score_rank_pct"] > ordered[i + 1]["score_rank_pct"]
            assert ordered[i]["score_z"] > ordered[i + 1]["score_z"]

    def test_z_symmetry(self):
        """Z-scores are roughly symmetric around 0 for uniform spread."""
        n = 20
        rows = _make_rows(n)
        attach_rank_and_z(rows)
        zs = [r["score_z"] for r in rows]
        z_mean = sum(zs) / len(zs)
        # Mean z should be near 0
        assert abs(z_mean) < 0.1

    def test_percentile_range(self):
        """All percentiles are in (0, 1)."""
        rows = _make_rows(30)
        attach_rank_and_z(rows)
        for r in rows:
            assert 0.0 < r["score_rank_pct"] < 1.0

    def test_percentile_clamping(self):
        """For large N, extreme ranks are clamped to [0.001, 0.999]."""
        n = 200
        rows = _make_rows(n)
        attach_rank_and_z(rows)
        pcts = [r["score_rank_pct"] for r in rows]
        assert min(pcts) >= 0.001
        assert max(pcts) <= 0.999

    def test_deterministic(self):
        """Same input produces identical output across runs."""
        rows_a = _make_rows(10)
        rows_b = _make_rows(10)
        attach_rank_and_z(rows_a)
        attach_rank_and_z(rows_b)
        for a, b in zip(rows_a, rows_b):
            assert a["score_rank_pct"] == b["score_rank_pct"]
            assert a["score_z"] == b["score_z"]

    def test_mutation_in_place(self):
        """Rows are mutated, not copied."""
        rows = _make_rows(3)
        original_ids = [id(r) for r in rows]
        attach_rank_and_z(rows)
        for r, oid in zip(rows, original_ids):
            assert id(r) == oid
            assert "score_rank_pct" in r
            assert "score_z" in r


# =====================================================================
# attach_rank_and_z — tie handling
# =====================================================================


class TestTies:

    def test_identical_scores_tiebreak_by_ticker(self):
        """Ties broken alphabetically by ticker — earlier ticker gets higher rank."""
        rows = _make_rows(4, scores=[50.0, 50.0, 50.0, 50.0], tickers=["ALPHA", "BETA", "GAMMA", "DELTA"])
        attach_rank_and_z(rows)
        alpha = next(r for r in rows if r["ticker"] == "ALPHA")
        beta = next(r for r in rows if r["ticker"] == "BETA")
        delta = next(r for r in rows if r["ticker"] == "DELTA")
        gamma = next(r for r in rows if r["ticker"] == "GAMMA")
        # Alphabetical: ALPHA < BETA < DELTA < GAMMA → ALPHA gets best rank
        assert alpha["score_rank_pct"] > beta["score_rank_pct"]
        assert beta["score_rank_pct"] > delta["score_rank_pct"]
        assert delta["score_rank_pct"] > gamma["score_rank_pct"]

    def test_partial_ties(self):
        """Mix of tied and distinct scores."""
        rows = _make_rows(5, scores=[90.0, 70.0, 70.0, 70.0, 30.0], tickers=["TOP", "MID_A", "MID_B", "MID_C", "BOT"])
        attach_rank_and_z(rows)
        top = next(r for r in rows if r["ticker"] == "TOP")
        bot = next(r for r in rows if r["ticker"] == "BOT")
        mids = [r for r in rows if r["ticker"].startswith("MID")]
        # TOP > all MIDs > BOT
        assert all(top["score_rank_pct"] > m["score_rank_pct"] for m in mids)
        assert all(m["score_rank_pct"] > bot["score_rank_pct"] for m in mids)

    def test_all_identical_scores(self):
        """All scores equal — still produces valid, distinct percentiles."""
        n = 10
        rows = _make_rows(n, scores=[42.0] * n)
        attach_rank_and_z(rows)
        pcts = sorted(r["score_rank_pct"] for r in rows)
        # All percentiles should be distinct
        assert len(set(pcts)) == n
        # Still in valid range
        assert all(0.0 < p < 1.0 for p in pcts)


# =====================================================================
# attach_rank_and_z — invalid / degraded
# =====================================================================


class TestInvalidScores:

    def test_missing_score_counted(self):
        """Row with missing composite_score is counted as invalid."""
        rows = [
            {"ticker": "A", "composite_score": 50.0},
            {"ticker": "B", "composite_score": 40.0},
            {"ticker": "C", "composite_score": 30.0},
            {"ticker": "D", "composite_score": 20.0},
            {"ticker": "E", "composite_score": 10.0},
            {"ticker": "F", "composite_score": 5.0},
            {"ticker": "G", "composite_score": 3.0},
            {"ticker": "H", "composite_score": 2.0},
            {"ticker": "I", "composite_score": 1.0},
            {"ticker": "J"},  # no score — 1/10 = 10%, at threshold
        ]
        result = attach_rank_and_z(rows)
        assert result["valid_count"] == 9
        assert result["invalid_count"] == 1
        assert not result["degraded"]

    def test_non_numeric_score_counted(self):
        """Row with non-numeric score is counted as invalid."""
        rows = [
            {"ticker": "A", "composite_score": 50.0},
            {"ticker": "B", "composite_score": "N/A"},
        ]
        result = attach_rank_and_z(rows)
        assert result["invalid_count"] == 1
        assert len(result["warnings"]) == 1
        assert "non-numeric" in result["warnings"][0]

    def test_degraded_mode_above_threshold(self):
        """When > 10% invalid, enters degraded mode: all z=0, pct=0.5."""
        rows = [
            {"ticker": "A", "composite_score": 50.0},
            {"ticker": "B"},
            {"ticker": "C"},
        ]
        # 2/3 = 66% invalid, well above 10%
        result = attach_rank_and_z(rows)
        assert result["degraded"] is True
        for r in rows:
            assert r["score_rank_pct"] == 0.5
            assert r["score_z"] == 0.0

    def test_degraded_mode_custom_threshold(self):
        """Custom max_invalid_pct is respected."""
        rows = [
            {"ticker": "A", "composite_score": 50.0},
            {"ticker": "B"},
        ]
        # 50% invalid — with threshold 0.60, not degraded
        result = attach_rank_and_z(rows, max_invalid_pct=0.60)
        assert result["degraded"] is False
        # with threshold 0.40, degraded
        rows2 = copy.deepcopy(rows)
        result2 = attach_rank_and_z(rows2, max_invalid_pct=0.40)
        assert result2["degraded"] is True

    def test_none_score_treated_as_zero(self):
        """None score rows still get ranked (score=0) when below threshold."""
        rows = _make_rows(10)
        rows[0]["composite_score"] = None  # 1/10 = 10%, at threshold
        result = attach_rank_and_z(rows, max_invalid_pct=0.10)
        # Exactly at threshold → not degraded (> threshold triggers)
        assert result["degraded"] is False
        # The None-score row should still have z/pct (ranked as 0.0)
        assert "score_rank_pct" in rows[0]
        assert "score_z" in rows[0]

    def test_all_invalid(self):
        """All rows invalid → degraded."""
        rows = [{"ticker": "A"}, {"ticker": "B"}, {"ticker": "C"}]
        result = attach_rank_and_z(rows)
        assert result["degraded"] is True
        assert result["valid_count"] == 0
        assert result["invalid_count"] == 3

    def test_string_scores_work(self):
        """String-encoded numeric scores are accepted."""
        rows = _make_rows(3, scores=["80", "50", "20"], tickers=["A", "B", "C"])
        result = attach_rank_and_z(rows)
        assert result["valid_count"] == 3
        assert result["invalid_count"] == 0


# =====================================================================
# attach_rank_and_z — score_breakdown preference
# =====================================================================


class TestScoreBreakdownPreference:

    def test_post_cap_score_overrides_composite(self):
        """Ranking uses post_cap_score from breakdown, not composite_score."""
        rows = [
            {
                "ticker": "HAS_BREAKDOWN",
                "composite_score": 10.0,
                "score_breakdown": {"final": {"post_cap_score": 90.0}},
            },
            {
                "ticker": "NO_BREAKDOWN",
                "composite_score": 50.0,
            },
        ]
        attach_rank_and_z(rows)
        has = next(r for r in rows if r["ticker"] == "HAS_BREAKDOWN")
        no = next(r for r in rows if r["ticker"] == "NO_BREAKDOWN")
        # HAS_BREAKDOWN should rank higher (90 > 50) despite lower composite_score
        assert has["score_rank_pct"] > no["score_rank_pct"]

    def test_pre_penalty_fallback(self):
        """Uses pre_penalty_score when post_cap is absent."""
        rows = [
            {
                "ticker": "A",
                "composite_score": 10.0,
                "score_breakdown": {"final": {"pre_penalty_score": 80.0}},
            },
            {"ticker": "B", "composite_score": 40.0},
        ]
        attach_rank_and_z(rows)
        a = next(r for r in rows if r["ticker"] == "A")
        b = next(r for r in rows if r["ticker"] == "B")
        assert a["score_rank_pct"] > b["score_rank_pct"]


# =====================================================================
# attach_expected_return
# =====================================================================


class TestAttachExpectedReturn:

    def test_basic_er(self):
        """z > 0 → positive ER, z < 0 → negative ER."""
        rows = [
            {"ticker": "POS", "score_z": 1.5},
            {"ticker": "NEG", "score_z": -1.5},
            {"ticker": "ZERO", "score_z": 0.0},
        ]
        attach_expected_return(rows)
        pos = next(r for r in rows if r["ticker"] == "POS")
        neg = next(r for r in rows if r["ticker"] == "NEG")
        zero = next(r for r in rows if r["ticker"] == "ZERO")
        assert pos["expected_excess_return_annual"] > 0
        assert neg["expected_excess_return_annual"] < 0
        assert zero["expected_excess_return_annual"] == 0.0

    def test_er_proportional_to_z(self):
        """ER is linear in z (ER = z * lambda)."""
        rows = [
            {"ticker": "A", "score_z": 1.0},
            {"ticker": "B", "score_z": 2.0},
        ]
        attach_expected_return(rows)
        a = next(r for r in rows if r["ticker"] == "A")
        b = next(r for r in rows if r["ticker"] == "B")
        assert b["expected_excess_return_annual"] == pytest.approx(2.0 * a["expected_excess_return_annual"], abs=0.001)

    def test_default_lambda(self):
        """Default lambda = 0.08 → z=1 gives ER=0.08."""
        rows = [{"ticker": "X", "score_z": 1.0}]
        attach_expected_return(rows)
        assert rows[0]["expected_excess_return_annual"] == pytest.approx(0.08, abs=0.001)

    def test_custom_lambda(self):
        """Custom lambda is respected."""
        rows = [{"ticker": "X", "score_z": 1.0}]
        attach_expected_return(rows, lambda_annual=Decimal("0.12"))
        assert rows[0]["expected_excess_return_annual"] == pytest.approx(0.12, abs=0.001)

    def test_daily_er_computed(self):
        """Daily ER = annual / 252."""
        rows = [{"ticker": "X", "score_z": 1.0}]
        attach_expected_return(rows, include_daily=True)
        annual = rows[0]["expected_excess_return_annual"]
        daily = rows[0]["expected_excess_return_daily"]
        assert daily == pytest.approx(annual / 252.0, abs=1e-6)

    def test_daily_er_skipped(self):
        """include_daily=False omits the daily field."""
        rows = [{"ticker": "X", "score_z": 1.0}]
        attach_expected_return(rows, include_daily=False)
        assert "expected_excess_return_daily" not in rows[0]

    def test_missing_z_skipped(self):
        """Row without score_z is skipped, not crashed."""
        rows = [{"ticker": "X"}]
        attach_expected_return(rows)
        assert "expected_excess_return_annual" not in rows[0]

    def test_er_symmetry(self):
        """ER(z) = -ER(-z)."""
        rows = [
            {"ticker": "A", "score_z": 1.5},
            {"ticker": "B", "score_z": -1.5},
        ]
        attach_expected_return(rows)
        a = next(r for r in rows if r["ticker"] == "A")
        b = next(r for r in rows if r["ticker"] == "B")
        assert a["expected_excess_return_annual"] == pytest.approx(-b["expected_excess_return_annual"], abs=0.001)


# =====================================================================
# compute_expected_returns (full pipeline)
# =====================================================================


class TestComputeExpectedReturns:

    def test_full_pipeline(self):
        """End-to-end: scores → rank_pct, z, ER_annual, ER_daily."""
        rows = _make_rows(5)
        prov = compute_expected_returns(rows)
        for r in rows:
            assert "score_rank_pct" in r
            assert "score_z" in r
            assert "expected_excess_return_annual" in r
            assert "expected_excess_return_daily" in r
        # Provenance
        assert prov["er_model"] == "zscore_linear_lambda"
        assert prov["validation"]["valid_count"] == 5
        assert prov["validation"]["degraded"] is False

    def test_degraded_pipeline(self):
        """Degraded mode sets ER=0 for all rows."""
        rows = [{"ticker": "A"}, {"ticker": "B"}]  # all invalid
        prov = compute_expected_returns(rows)
        assert prov["validation"]["degraded"] is True
        for r in rows:
            assert r["expected_excess_return_annual"] == 0.0
            assert r["expected_excess_return_daily"] == 0.0

    def test_provenance_includes_warnings(self):
        """Warnings propagated to provenance."""
        rows = _make_rows(10)
        rows[0]["composite_score"] = None  # 1 invalid
        prov = compute_expected_returns(rows)
        assert "warnings" in prov
        assert len(prov["warnings"]) >= 1

    def test_empty_input_provenance(self):
        """Empty input returns clean provenance."""
        prov = compute_expected_returns([])
        assert prov["validation"]["valid_count"] == 0
        assert prov["validation"]["degraded"] is False

    def test_best_row_gets_positive_er(self):
        """Highest-scored row gets positive annual ER."""
        rows = _make_rows(10)
        compute_expected_returns(rows)
        best = max(rows, key=lambda r: float(r["composite_score"]))
        assert best["expected_excess_return_annual"] > 0

    def test_worst_row_gets_negative_er(self):
        """Lowest-scored row gets negative annual ER."""
        rows = _make_rows(10)
        compute_expected_returns(rows)
        worst = min(rows, key=lambda r: float(r["composite_score"]))
        assert worst["expected_excess_return_annual"] < 0


# =====================================================================
# validate_er_output
# =====================================================================


class TestValidateErOutput:

    def test_valid_output(self):
        """Well-formed output produces no warnings."""
        rows = _make_rows(20)
        compute_expected_returns(rows)
        warnings = validate_er_output(rows)
        assert warnings == []

    def test_empty_rows(self):
        warnings = validate_er_output([])
        assert any("No rows" in w for w in warnings)

    def test_missing_z(self):
        rows = [{"ticker": "A"}]
        warnings = validate_er_output(rows)
        assert any("missing score_z" in w for w in warnings)

    def test_missing_er(self):
        rows = [{"ticker": "A", "score_z": 0.5}]
        warnings = validate_er_output(rows)
        assert any("missing expected_excess_return_annual" in w for w in warnings)

    def test_asymmetry_warning(self):
        """Large z-score asymmetry triggers warning."""
        rows = [
            {"ticker": "A", "score_z": 3.0, "expected_excess_return_annual": 0.24},
            {"ticker": "B", "score_z": 2.5, "expected_excess_return_annual": 0.20},
            {"ticker": "C", "score_z": 0.5, "expected_excess_return_annual": 0.04},
        ]
        warnings = validate_er_output(rows)
        assert any("not symmetric" in w for w in warnings)

    def test_narrow_range_warning(self):
        """Very narrow z-score range triggers warning."""
        rows = [
            {"ticker": "A", "score_z": 0.01, "expected_excess_return_annual": 0.001},
            {"ticker": "B", "score_z": 0.00, "expected_excess_return_annual": 0.000},
            {"ticker": "C", "score_z": -0.01, "expected_excess_return_annual": -0.001},
        ]
        warnings = validate_er_output(rows)
        assert any("too narrow" in w for w in warnings)


# =====================================================================
# Regression / integration
# =====================================================================


class TestRegression:

    def test_large_universe(self):
        """353-ticker universe (production size) completes without error."""
        rows = _make_rows(353)
        prov = compute_expected_returns(rows)
        assert prov["validation"]["valid_count"] == 353
        assert prov["validation"]["degraded"] is False
        # Check all rows got ER
        assert all("expected_excess_return_annual" in r for r in rows)

    def test_negative_scores(self):
        """Negative composite scores are handled correctly."""
        rows = _make_rows(5, scores=[-10.0, -5.0, 0.0, 5.0, 10.0], tickers=["A", "B", "C", "D", "E"])
        attach_rank_and_z(rows)
        a = next(r for r in rows if r["ticker"] == "A")
        e = next(r for r in rows if r["ticker"] == "E")
        # E (score=10) should rank above A (score=-10)
        assert e["score_rank_pct"] > a["score_rank_pct"]

    def test_very_close_scores(self):
        """Scores differing by epsilon still produce distinct percentiles."""
        base = 50.0
        rows = _make_rows(5, scores=[base + i * 1e-8 for i in range(5)], tickers=["A", "B", "C", "D", "E"])
        attach_rank_and_z(rows)
        pcts = [r["score_rank_pct"] for r in rows]
        # Should have 5 distinct percentiles (tiebreaker by ticker)
        assert len(set(pcts)) == 5

    def test_score_key_override(self):
        """Custom score_key is respected."""
        rows = [
            {"ticker": "A", "custom": 100.0},
            {"ticker": "B", "custom": 50.0},
        ]
        result = attach_rank_and_z(rows, score_key="custom")
        assert result["valid_count"] == 2
        a = next(r for r in rows if r["ticker"] == "A")
        b = next(r for r in rows if r["ticker"] == "B")
        assert a["score_rank_pct"] > b["score_rank_pct"]

    def test_idempotent(self):
        """Running attach_rank_and_z twice produces same result as once."""
        rows = _make_rows(10)
        attach_rank_and_z(rows)
        first_pass = [(r["score_rank_pct"], r["score_z"]) for r in rows]
        attach_rank_and_z(rows)
        second_pass = [(r["score_rank_pct"], r["score_z"]) for r in rows]
        assert first_pass == second_pass
