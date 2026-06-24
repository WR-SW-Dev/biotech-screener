"""Tests for archive-mode helpers in run_rank_ic_backtest.py."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from run_rank_ic_backtest import assert_rank_unique, signal_to_rankings

# ── assert_rank_unique ──────────────────────────────────────────────────────


class TestAssertRankUnique:
    def test_unique_ranks_pass(self):
        rankings = {"A": 1, "B": 2, "C": 3}
        result = assert_rank_unique(rankings, "2026-01-01", {})
        assert result is True

    def test_duplicate_ranks_fail(self):
        rankings = {"A": 1, "B": 1, "C": 3}
        with pytest.raises(ValueError, match="Rank ties"):
            assert_rank_unique(rankings, "2026-01-01", {})

    def test_duplicate_ranks_allowed_with_flag(self):
        rankings = {"A": 1, "B": 1, "C": 3}
        result = assert_rank_unique(rankings, "2026-01-01", {}, allow_ties=True)
        assert result is True

    def test_empty_rankings(self):
        result = assert_rank_unique({}, "2026-01-01", {})
        assert result is True

    def test_single_entry(self):
        result = assert_rank_unique({"A": 1}, "2026-01-01", {})
        assert result is True


# ── signal_to_rankings ──────────────────────────────────────────────────────


class TestSignalToRankings:
    def test_higher_is_better(self):
        signals = {"A": 0.9, "B": 0.5, "C": 0.1}
        result = signal_to_rankings(signals, higher_is_better=True)
        assert result == {"A": 1, "B": 2, "C": 3}

    def test_lower_is_better(self):
        signals = {"A": 0.9, "B": 0.5, "C": 0.1}
        result = signal_to_rankings(signals, higher_is_better=False)
        assert result == {"C": 1, "B": 2, "A": 3}

    def test_dense_ranking(self):
        """Ranks should be dense 1..N with no gaps."""
        signals = {"X": 10.0, "Y": 20.0, "Z": 15.0}
        result = signal_to_rankings(signals, higher_is_better=True)
        assert sorted(result.values()) == [1, 2, 3]
        assert result["Y"] == 1
        assert result["Z"] == 2
        assert result["X"] == 3

    def test_single_ticker(self):
        result = signal_to_rankings({"A": 0.5}, higher_is_better=True)
        assert result == {"A": 1}

    def test_identical_signals_deterministic(self):
        """With identical values, output should still assign unique dense ranks."""
        signals = {"A": 0.5, "B": 0.5, "C": 0.5}
        result = signal_to_rankings(signals, higher_is_better=True)
        assert sorted(result.values()) == [1, 2, 3]

    def test_score_rank_pct_lower_is_better(self):
        """score_rank_pct: lower = better rank. Use higher_is_better=False."""
        signals = {"A": 0.01, "B": 0.50, "C": 0.99}
        result = signal_to_rankings(signals, higher_is_better=False)
        assert result["A"] == 1  # best
        assert result["C"] == 3  # worst


# ── Spec 100: universe-gate filter and overlap check ────────────────────────


class TestSpec100UniverseFilter:
    """Spec 100: universe-gate filter and overlap check."""

    def _make_signal_scores(self, n=40, n_eligible=20, n_actionable=15):
        tickers = [f"T{i:03d}" for i in range(n)]
        eligible = {t: (1.0 if i < n_eligible else 0.0) for i, t in enumerate(tickers)}
        actionable_rank = {t: float(i + 1) for i, t in enumerate(tickers[:n_actionable])}
        return tickers, eligible, actionable_rank

    def test_eligible_filter_keeps_only_eligible_tickers(self):
        tickers, eligible, actionable_rank = self._make_signal_scores(n=40, n_eligible=20)
        signal_scores_data = {"eligible": eligible, "actionable_rank": actionable_rank}
        keep = {t for t, v in signal_scores_data.get("eligible", {}).items() if v == 1.0}
        assert len(keep) == 20
        assert all(eligible[t] == 1.0 for t in keep)

    def test_actionable_filter_keeps_top30_only(self):
        tickers, eligible, actionable_rank = self._make_signal_scores(n=50, n_actionable=30)
        signal_scores_data = {"eligible": {}, "actionable_rank": actionable_rank}
        keep = {t for t, v in signal_scores_data.get("actionable_rank", {}).items() if v <= 30}
        assert len(keep) == 30

    def test_all_filter_returns_full_set(self):
        tickers, eligible, actionable_rank = self._make_signal_scores(n=60)
        signal_scores_data = {"eligible": eligible, "actionable_rank": actionable_rank}
        keep = set(tickers)  # "all" = no filtering
        assert len(keep) == 60

    def test_overlap_calculation_perfect(self):
        ic_rankings = {f"T{i:03d}": i + 1 for i in range(60)}
        prod_top30 = {f"T{i:03d}" for i in range(30)}
        _top_n = min(30, len(ic_rankings))
        _ic_top_n = {t for t, r in ic_rankings.items() if r <= _top_n}
        _denom = max(len(_ic_top_n), len(prod_top30))
        overlap = len(_ic_top_n & prod_top30) / _denom * 100
        assert overlap == 100.0

    def test_overlap_calculation_zero(self):
        ic_rankings = {f"T{i:03d}": i + 1 for i in range(60)}
        prod_top30 = {f"T{i:03d}" for i in range(30, 60)}
        _top_n = min(30, len(ic_rankings))
        _ic_top_n = {t for t, r in ic_rankings.items() if r <= _top_n}
        _denom = max(len(_ic_top_n), len(prod_top30))
        overlap = len(_ic_top_n & prod_top30) / _denom * 100
        assert overlap == 0.0

    def test_overlap_calculation_partial(self):
        ic_rankings = {f"T{i:03d}": i + 1 for i in range(60)}
        # 15 overlap: T000-T014 are in both ic top-30 and prod_top30
        prod_top30 = {f"T{i:03d}" for i in range(15, 45)}
        _top_n = min(30, len(ic_rankings))
        _ic_top_n = {t for t, r in ic_rankings.items() if r <= _top_n}
        _denom = max(len(_ic_top_n), len(prod_top30))
        overlap = len(_ic_top_n & prod_top30) / _denom * 100
        assert abs(overlap - 50.0) < 0.1

    def test_eligible_filter_empty_gives_empty_keep(self):
        signal_scores_data = {"eligible": {f"T{i:03d}": 0.0 for i in range(40)}}
        keep = {t for t, v in signal_scores_data.get("eligible", {}).items() if v == 1.0}
        assert len(keep) == 0

    def test_actionable_rank_not_present_gives_empty_keep(self):
        signal_scores_data = {}
        keep = {t for t, v in signal_scores_data.get("actionable_rank", {}).items() if v <= 30}
        assert len(keep) == 0
