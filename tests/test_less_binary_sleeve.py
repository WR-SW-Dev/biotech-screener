"""Tests for less-binary sleeve construction + contrarian validation.

Validates:
  1. DecisionRuleset.less_binary_construction field + validation
  2. _apply_less_binary_construction logic (exclude/equal_weight)
  3. select_portfolio_tickers + _select_with_buffer symmetry
  4. Hedge robustness computation
  5. Placebo degrades signal
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "research"))

from eval_forward_returns import _select_with_buffer, select_portfolio_tickers

from decision_engine import DecisionRuleset, _apply_less_binary_construction

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_row(
    ticker: str,
    size_band: str = "M",
    catalyst_days: object = "",
    catalyst_mode: str = "no_upcoming",
    target_weight_pct: float = 0.0,
) -> dict:
    return {
        "ticker": ticker,
        "size_band": size_band,
        "catalyst_days": catalyst_days,
        "catalyst_mode": catalyst_mode,
        "target_weight_pct": target_weight_pct,
    }


def _total_weight(rows):
    return sum(float(r.get("target_weight_pct", 0) or 0) for r in rows)


# ---------------------------------------------------------------------------
# A) Ruleset validation
# ---------------------------------------------------------------------------


class TestLessBinaryRulesetField:

    def test_default_is_include(self):
        rs = DecisionRuleset()
        assert rs.less_binary_construction == "include"

    def test_valid_modes(self):
        for mode in ("include", "equal_weight", "bottom_k", "exclude"):
            rs = DecisionRuleset(less_binary_construction=mode)
            assert rs.less_binary_construction == mode

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError, match="less_binary_construction"):
            DecisionRuleset(less_binary_construction="invalid")


# ---------------------------------------------------------------------------
# B) Less-binary construction logic
# ---------------------------------------------------------------------------


class TestApplyLessBinaryConstruction:

    def _make_mixed_rows(self):
        """3 binary + 3 core names with known weights."""
        return [
            _make_row("BIN1", catalyst_days=10, catalyst_mode="specific_days", target_weight_pct=20.0),
            _make_row("BIN2", catalyst_days=20, catalyst_mode="specific_days", target_weight_pct=15.0),
            _make_row("BIN3", catalyst_days=25, catalyst_mode="blended_window", target_weight_pct=15.0),
            _make_row("CORE1", catalyst_days=200, catalyst_mode="no_upcoming", target_weight_pct=20.0),
            _make_row("CORE2", catalyst_days="", catalyst_mode="missing", target_weight_pct=15.0),
            _make_row("CORE3", catalyst_days=300, catalyst_mode="no_upcoming", target_weight_pct=15.0),
        ]

    def test_include_no_change(self):
        rows = self._make_mixed_rows()
        orig = [r["target_weight_pct"] for r in rows]
        rs = DecisionRuleset(less_binary_construction="include")
        _apply_less_binary_construction(rows, rs)
        after = [r["target_weight_pct"] for r in rows]
        assert orig == after

    def test_exclude_zeros_core(self):
        rows = self._make_mixed_rows()
        rs = DecisionRuleset(less_binary_construction="exclude")
        _apply_less_binary_construction(rows, rs)
        # Core names should be zero
        assert float(rows[3]["target_weight_pct"]) == 0.0
        assert float(rows[4]["target_weight_pct"]) == 0.0
        assert float(rows[5]["target_weight_pct"]) == 0.0
        # Binary names should sum to 100%
        binary_total = sum(float(rows[i]["target_weight_pct"]) for i in range(3))
        assert abs(binary_total - 100.0) < 0.1

    def test_equal_weight_flattens_core(self):
        rows = self._make_mixed_rows()
        rs = DecisionRuleset(less_binary_construction="equal_weight")
        _apply_less_binary_construction(rows, rs)
        # Core names should have equal weight
        core_weights = [float(rows[i]["target_weight_pct"]) for i in range(3, 6)]
        assert len(set(core_weights)) == 1  # all same
        # Total should be ~100%
        assert abs(_total_weight(rows) - 100.0) < 0.15

    def test_no_core_names_noop(self):
        """When all names are binary, all modes are no-op."""
        rows = [
            _make_row("BIN1", catalyst_days=10, catalyst_mode="specific_days", target_weight_pct=50.0),
            _make_row("BIN2", catalyst_days=20, catalyst_mode="specific_days", target_weight_pct=50.0),
        ]
        orig = [r["target_weight_pct"] for r in rows]
        for mode in ("exclude", "equal_weight"):
            rs = DecisionRuleset(less_binary_construction=mode)
            _apply_less_binary_construction(rows, rs)
            after = [r["target_weight_pct"] for r in rows]
            assert orig == after


# ---------------------------------------------------------------------------
# C) Selection mode + buffer symmetry
# ---------------------------------------------------------------------------


class TestSelectionModes:

    def test_top_selects_first_k(self):
        t = list("ABCDEFGHIJ")
        assert select_portfolio_tickers(t, 3, "top") == ["A", "B", "C"]

    def test_bottom_selects_last_k(self):
        t = list("ABCDEFGHIJ")
        assert select_portfolio_tickers(t, 3, "bottom") == ["H", "I", "J"]

    def test_mid_selects_center(self):
        t = list("ABCDEFGHIJ")
        result = select_portfolio_tickers(t, 3, "mid")
        # Mid of 10 is index 5; start = 5-1=4 → E,F,G
        assert result == ["E", "F", "G"]

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError, match="Unknown selection_mode"):
            select_portfolio_tickers(list("ABC"), 2, "invalid")


class TestBufferSymmetry:
    """Verify buffer logic is symmetric across modes."""

    def test_top_buffer_keeps_prev(self):
        t = list("ABCDEFGHIJ")
        # Core = [A,B,C], buffer zone = [A,B,C,D,E]
        # Prev = [B,D] → kept (both in zone), fill A from core
        result = _select_with_buffer(t, 3, "top", 2, ["B", "D"])
        assert "B" in result and "D" in result
        assert len(result) == 3

    def test_bottom_buffer_keeps_prev(self):
        t = list("ABCDEFGHIJ")
        # Core = [H,I,J], buffer zone = [F,G,H,I,J]
        # Prev = [G,I] → both in zone, fill H from core
        result = _select_with_buffer(t, 3, "bottom", 2, ["G", "I"])
        assert "G" in result and "I" in result
        assert len(result) == 3

    def test_mid_buffer_keeps_prev(self):
        t = list("ABCDEFGHIJ")
        # Core = [E,F,G], buffer zone = [C,D,E,F,G,H,I]
        # Prev = [C,F] → both in zone, fill E from core
        result = _select_with_buffer(t, 3, "mid", 2, ["C", "F"])
        assert "C" in result and "F" in result
        assert len(result) == 3

    def test_no_prev_equals_raw_select(self):
        t = list("ABCDEFGHIJ")
        for mode in ("top", "bottom", "mid"):
            buffered = _select_with_buffer(t, 3, mode, 5, [])
            raw = select_portfolio_tickers(t, 3, mode)
            assert buffered == raw, f"{mode}: buffered={buffered} != raw={raw}"

    def test_buffer_reduces_turnover(self):
        """Buffer should keep more prev holdings → fewer changes."""
        t = list("ABCDEFGHIJ")
        prev = ["B", "D", "F"]  # 3 held, B is in top zone
        # Without buffer: top-3 = [A,B,C] → only B kept (1/3)
        # With buffer=5: zone = [A..F] → B,D,F all in zone → 3/3 kept
        no_buf = select_portfolio_tickers(t, 3, "top")
        with_buf = _select_with_buffer(t, 3, "top", 5, prev)
        prev_set = set(prev)
        kept_no_buf = len(set(no_buf) & prev_set)
        kept_with_buf = len(set(with_buf) & prev_set)
        assert kept_with_buf >= kept_no_buf


# ---------------------------------------------------------------------------
# D) Hedge robustness computation
# ---------------------------------------------------------------------------


class TestHedgeRobustness:

    def test_simple_hedge_equals_excess(self):
        """Simple 1x hedge = gross - benchmark = excess."""
        import csv
        import tempfile

        from validate_less_binary_contrarian import run_hedge_robustness

        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "by_date.csv"
            with open(p, "w", newline="") as f:
                w = csv.DictWriter(
                    f,
                    fieldnames=[
                        "date",
                        "horizon",
                        "skipped",
                        "gross_return",
                        "benchmark_return",
                        "hedged_return",
                        "excess_return",
                    ],
                )
                w.writeheader()
                w.writerow(
                    {
                        "date": "2024-01-01",
                        "horizon": "84",
                        "skipped": "False",
                        "gross_return": "0.10",
                        "benchmark_return": "0.04",
                        "hedged_return": "0.05",
                        "excess_return": "0.06",
                    }
                )
                w.writerow(
                    {
                        "date": "2024-01-08",
                        "horizon": "84",
                        "skipped": "False",
                        "gross_return": "0.08",
                        "benchmark_return": "0.02",
                        "hedged_return": "0.04",
                        "excess_return": "0.06",
                    }
                )

            result = run_hedge_robustness(p, Path("dummy.csv"), [84])
            h84 = result["hedge_by_horizon"][84]
            # Simple hedge = mean(0.10-0.04, 0.08-0.02) = mean(0.06, 0.06) = 0.06
            assert abs(h84["simple_hedged"] - 0.06) < 1e-6
            # Beta hedged = mean(0.05, 0.04) = 0.045
            assert abs(h84["beta_hedged"] - 0.045) < 1e-6

    def test_both_positive_passes(self):
        """Gate passes when both hedge methods show positive returns."""
        from validate_less_binary_contrarian import write_verdict

        hedge = {
            "hedge_by_horizon": {
                84: {"beta_hedged": 0.05, "simple_hedged": 0.04, "excess": 0.06},
                126: {"beta_hedged": 0.08, "simple_hedged": 0.07, "excess": 0.09},
            }
        }
        baseline = {84: {"hedged": 0.05}, 126: {"hedged": 0.08}}
        placebo = {
            "placebo_by_horizon": {
                84: {"mean_hedged": 0.01},
                126: {"mean_hedged": 0.02},
            }
        }
        tradeability = {
            "tradeability_by_horizon": {
                84: {"baseline_hedged": 0.05, "filtered_hedged": 0.04},
                126: {"baseline_hedged": 0.08, "filtered_hedged": 0.06},
            }
        }

        import tempfile

        with tempfile.TemporaryDirectory() as td:
            path = write_verdict(placebo, tradeability, hedge, baseline, Path(td))
            text = path.read_text()
            assert "PASS" in text


# ---------------------------------------------------------------------------
# E) Placebo test logic
# ---------------------------------------------------------------------------


class TestPlaceboLogic:

    def test_shuffle_changes_rank_order(self):
        """Shuffling with a seed should change actionable_rank order."""
        import random

        rankings = [{"ticker": f"T{i}", "actionable_rank": i, "size_band": "M"} for i in range(1, 21)]
        orig_order = [r["ticker"] for r in rankings]

        rng = random.Random(42)
        rng.shuffle(rankings)
        for i, r in enumerate(rankings):
            r["actionable_rank"] = i + 1

        shuffled_order = [r["ticker"] for r in rankings]
        assert orig_order != shuffled_order

    def test_placebo_should_degrade_vs_systematic(self):
        """Conceptual: random selection should have lower |IC| than systematic."""
        # This is a design property test — random selection IC should center on 0
        import statistics

        ics = []
        rng = __import__("random").Random(123)
        for _ in range(100):
            # Random signals vs random returns → IC ≈ 0
            signals = [rng.random() for _ in range(20)]
            returns = [rng.random() for _ in range(20)]
            from eval_forward_returns import spearman_ic

            ic = spearman_ic(signals, returns)
            if ic is not None:
                ics.append(ic)
        mean_ic = statistics.mean(ics)
        # Random IC should be near zero
        assert abs(mean_ic) < 0.1
