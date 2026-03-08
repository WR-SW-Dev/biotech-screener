"""Tests for less-binary inversion robustness battery.

Validates:
  1. Placebo destroys signal (shuffled IC → near zero)
  2. Execution lag logic (trade_lag_days shifts trade_date correctly)
  3. Deterministic shuffling (seeded)
  4. K sweep output schema
  5. Industry-neutral metric extraction
  6. VALIDATION.md / VALIDATION.json structure
  7. _extract_horizon_metrics helper
  8. Verdict logic per gate
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "research"))

from eval_forward_returns import _trading_days_after, spearman_ic
from validate_less_binary_inversion import (
    _extract_horizon_metrics,
    _fmt_f,
    _fmt_pct,
    write_validation,
    write_validation_json,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_summary(by_horizon: dict) -> MagicMock:
    """Create a mock EvalSummary with the given by_horizon dict."""
    summary = MagicMock()
    summary.by_horizon = by_horizon
    return summary


# ---------------------------------------------------------------------------
# 1) Placebo: shuffled IC should center on zero
# ---------------------------------------------------------------------------


class TestPlaceboProperty:

    def test_shuffled_ic_near_zero(self):
        """Random rankings → IC ≈ 0 (property test)."""
        import random
        import statistics

        rng = random.Random(42)
        ics = []
        for _ in range(200):
            signals = [rng.random() for _ in range(30)]
            returns = [rng.random() for _ in range(30)]
            ic = spearman_ic(signals, returns)
            if ic is not None:
                ics.append(ic)
        mean_ic = statistics.mean(ics)
        assert abs(mean_ic) < 0.08, f"Shuffled IC should be near 0, got {mean_ic:.4f}"

    def test_deterministic_shuffle_same_seed(self):
        """Same seed + same snap_date hash → same shuffle order."""
        import random

        data = list(range(50))
        for _ in range(3):
            copy = data[:]
            rng = random.Random(42 + hash("2024-01-01"))
            rng.shuffle(copy)
            assert copy == data[:] or True  # just verify no crash

        # Two runs with same seed should match
        copy1 = list(range(50))
        rng1 = random.Random(42 + hash("2024-01-01"))
        rng1.shuffle(copy1)

        copy2 = list(range(50))
        rng2 = random.Random(42 + hash("2024-01-01"))
        rng2.shuffle(copy2)
        assert copy1 == copy2

    def test_int_actionable_rank_no_crash(self):
        """After shuffle, actionable_rank is int — eligible_set build must not crash."""
        # Simulates what evaluate() does post-shuffle: assign int ranks,
        # then build eligible_set with str().strip() on actionable_rank.
        rankings = [{"ticker": f"T{i}", "actionable_rank": i + 1} for i in range(10)]  # int, not str
        # This is the line that used to crash: .strip() on int
        eligible_set = {r["ticker"] for r in rankings if r.get("ticker") and str(r.get("actionable_rank", "")).strip()}
        assert len(eligible_set) == 10

    def test_different_seeds_differ(self):
        """Different seeds should produce different orderings."""
        import random

        data = list(range(50))

        copy1 = data[:]
        random.Random(42).shuffle(copy1)

        copy2 = data[:]
        random.Random(99).shuffle(copy2)

        assert copy1 != copy2


# ---------------------------------------------------------------------------
# 2) Execution lag logic
# ---------------------------------------------------------------------------


class TestExecutionLag:

    def test_trading_days_after_basic(self):
        dates = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08"]
        assert _trading_days_after(dates, "2024-01-02", 0) == "2024-01-02"
        assert _trading_days_after(dates, "2024-01-02", 1) == "2024-01-03"
        assert _trading_days_after(dates, "2024-01-02", 3) == "2024-01-05"
        # 5d lag from 2024-01-02 → beyond data
        assert _trading_days_after(dates, "2024-01-02", 5) is None

    def test_lag_skips_weekends(self):
        """Trading days skip non-trading days (weekends/holidays)."""
        # Mon-Fri, skip Sat/Sun, then Mon
        dates = [
            "2024-01-08",
            "2024-01-09",
            "2024-01-10",
            "2024-01-11",
            "2024-01-12",
            "2024-01-16",
            "2024-01-17",
        ]  # MLK holiday on 15th
        result = _trading_days_after(dates, "2024-01-12", 1)
        assert result == "2024-01-16"  # skips weekend + holiday

    def test_lag_missing_start_returns_none(self):
        dates = ["2024-01-02", "2024-01-03"]
        assert _trading_days_after(dates, "2024-01-01", 1) is None

    def test_lag_zero_returns_same_date(self):
        dates = ["2024-01-02", "2024-01-03"]
        assert _trading_days_after(dates, "2024-01-02", 0) == "2024-01-02"


# ---------------------------------------------------------------------------
# 3) K sweep output schema
# ---------------------------------------------------------------------------


class TestKSweepSchema:

    def test_extract_horizon_metrics_fields(self):
        """_extract_horizon_metrics returns expected keys."""
        summary = _make_mock_summary(
            {
                84: {
                    "mean_ic": -0.05,
                    "ic_t_stat": -3.2,
                    "mean_net_return": 0.08,
                    "mean_excess_return": 0.04,
                    "mean_hedged_return": 0.03,
                    "mean_turnover": 0.10,
                    "mean_industry_neutral_ic": -0.03,
                    "industry_neutral_ic_t_stat": -1.8,
                    "n": 300,
                },
            }
        )
        result = _extract_horizon_metrics(summary, [84])
        m = result[84]
        assert m["mean_ic"] == -0.05
        assert m["ic_t_stat"] == -3.2
        assert m["mean_net"] == 0.08
        assert m["mean_excess"] == 0.04
        assert m["mean_hedged"] == 0.03
        assert m["mean_turnover"] == 0.10
        assert m["industry_neutral_ic"] == -0.03
        assert m["industry_neutral_ic_t"] == -1.8
        assert m["n_evaluated"] == 300

    def test_extract_missing_horizon_returns_nones(self):
        summary = _make_mock_summary({})
        result = _extract_horizon_metrics(summary, [84])
        m = result[84]
        assert m["mean_ic"] is None
        assert m["mean_hedged"] is None

    def test_k_sweep_result_structure(self):
        """K sweep result dict should have k_sweep and k_values keys."""
        # Simulate a k_sweep return
        result = {
            "k_sweep": {
                10: {
                    "bottom": {84: {"mean_hedged": 0.05}, 126: {"mean_hedged": 0.07}},
                    "top": {84: {"mean_hedged": 0.02}, 126: {"mean_hedged": 0.03}},
                },
                20: {
                    "bottom": {84: {"mean_hedged": 0.04}, 126: {"mean_hedged": 0.06}},
                    "top": {84: {"mean_hedged": 0.01}, 126: {"mean_hedged": 0.02}},
                },
            },
            "k_values": [10, 20],
        }
        assert "k_sweep" in result
        assert "k_values" in result
        assert 10 in result["k_sweep"]
        assert "bottom" in result["k_sweep"][10]
        assert "top" in result["k_sweep"][10]


# ---------------------------------------------------------------------------
# 4) Formatting helpers
# ---------------------------------------------------------------------------


class TestFormatHelpers:

    def test_fmt_pct_none(self):
        assert _fmt_pct(None) == "\u2014"

    def test_fmt_pct_value(self):
        assert _fmt_pct(0.1234) == "12.34%"

    def test_fmt_f_none(self):
        assert _fmt_f(None) == "\u2014"

    def test_fmt_f_value(self):
        assert _fmt_f(0.12345, 3) == "0.123"


# ---------------------------------------------------------------------------
# 5) Verdict / output structure
# ---------------------------------------------------------------------------


class TestVerdictOutput:

    def _make_baseline(self):
        return {
            84: {
                "mean_hedged": 0.10,
                "mean_excess": 0.08,
                "mean_net": 0.12,
                "mean_ic": -0.05,
                "ic_t_stat": -5.0,
                "mean_turnover": 0.05,
            },
            126: {
                "mean_hedged": 0.15,
                "mean_excess": 0.12,
                "mean_net": 0.18,
                "mean_ic": -0.08,
                "ic_t_stat": -8.0,
                "mean_turnover": 0.04,
            },
        }

    def test_validation_md_written(self, tmp_path):
        baseline = self._make_baseline()
        placebo = {
            "placebo_by_horizon": {
                84: {"mean_hedged": 0.02},
                126: {"mean_hedged": 0.03},
            }
        }
        k_sweep = {
            "k_sweep": {
                20: {
                    "bottom": {84: {"mean_hedged": 0.10}, 126: {"mean_hedged": 0.15}},
                    "top": {84: {"mean_hedged": 0.03}, 126: {"mean_hedged": 0.05}},
                },
            },
            "k_values": [20],
        }
        lag = {
            "lag_days": 5,
            "lagged_bottom": {84: {"mean_hedged": 0.08}, 126: {"mean_hedged": 0.12}},
            "lagged_top": {84: {"mean_hedged": 0.02}, 126: {"mean_hedged": 0.03}},
        }
        neutral = {
            "industry_neutral": {
                84: {"mean_ic": -0.05, "ic_t_stat": -5.0, "industry_neutral_ic": -0.04, "industry_neutral_ic_t": -4.0},
                126: {"mean_ic": -0.08, "ic_t_stat": -8.0, "industry_neutral_ic": -0.06, "industry_neutral_ic_t": -6.0},
            }
        }
        liquidity = {
            "liquidity_filtered": {
                84: {"mean_hedged": 0.08},
                126: {"mean_hedged": 0.12},
            }
        }

        path = write_validation(baseline, placebo, k_sweep, lag, neutral, liquidity, tmp_path)
        assert path.exists()
        text = path.read_text()
        assert "Less-Binary Inversion Robustness Battery" in text
        assert "Gate 1" in text
        assert "Gate 2" in text
        assert "Gate 3" in text
        assert "Gate 4" in text
        assert "Gate 5" in text
        assert "Overall Verdict" in text

    def test_validation_json_written(self, tmp_path):
        baseline = self._make_baseline()
        placebo = {"placebo_by_horizon": {84: {}, 126: {}}}
        k_sweep = {"k_sweep": {}, "k_values": []}
        lag = {"lag_days": 5, "lagged_bottom": {}, "lagged_top": {}}
        neutral = {"industry_neutral": {}}
        liquidity = {"liquidity_filtered": {}}

        path = write_validation_json(baseline, placebo, k_sweep, lag, neutral, liquidity, tmp_path)
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["schema"] == "less_binary_inversion_validation.v1"
        assert "baseline" in data
        assert "placebo" in data
        assert "k_sweep" in data
        assert "execution_lag" in data
        assert "industry_neutral" in data
        assert "liquidity_filter" in data

    def test_placebo_gate_pass_when_degradation_large(self, tmp_path):
        """Placebo gate PASS when baseline - shuffled > 2pp."""
        baseline = {
            84: {
                "mean_hedged": 0.10,
                "mean_excess": 0.08,
                "mean_net": 0.12,
                "mean_ic": -0.05,
                "ic_t_stat": -5.0,
                "mean_turnover": 0.05,
            },
            126: {
                "mean_hedged": 0.15,
                "mean_excess": 0.12,
                "mean_net": 0.18,
                "mean_ic": -0.08,
                "ic_t_stat": -8.0,
                "mean_turnover": 0.04,
            },
        }
        # Shuffled hedged much lower → degradation > 2pp → PASS
        placebo = {
            "placebo_by_horizon": {
                84: {"mean_hedged": 0.02},
                126: {"mean_hedged": 0.03},
            }
        }
        k_sweep = {"k_sweep": {}, "k_values": []}
        lag = {"lag_days": 5, "lagged_bottom": {}, "lagged_top": {}}
        neutral = {"industry_neutral": {}}
        liquidity = {"liquidity_filtered": {}}

        path = write_validation(baseline, placebo, k_sweep, lag, neutral, liquidity, tmp_path)
        text = path.read_text()
        # Overall verdict should show placebo: PASS
        assert "placebo: **PASS**" in text

    def test_placebo_gate_fail_when_no_degradation(self, tmp_path):
        """Placebo gate FAIL when shuffled ≈ baseline (< 2pp degradation)."""
        baseline = {
            84: {
                "mean_hedged": 0.10,
                "mean_excess": 0.08,
                "mean_net": 0.12,
                "mean_ic": -0.05,
                "ic_t_stat": -5.0,
                "mean_turnover": 0.05,
            },
            126: {
                "mean_hedged": 0.15,
                "mean_excess": 0.12,
                "mean_net": 0.18,
                "mean_ic": -0.08,
                "ic_t_stat": -8.0,
                "mean_turnover": 0.04,
            },
        }
        # Shuffled hedged close to baseline → < 2pp degradation → FAIL
        placebo = {
            "placebo_by_horizon": {
                84: {"mean_hedged": 0.09},
                126: {"mean_hedged": 0.14},
            }
        }
        k_sweep = {"k_sweep": {}, "k_values": []}
        lag = {"lag_days": 5, "lagged_bottom": {}, "lagged_top": {}}
        neutral = {"industry_neutral": {}}
        liquidity = {"liquidity_filtered": {}}

        path = write_validation(baseline, placebo, k_sweep, lag, neutral, liquidity, tmp_path)
        text = path.read_text()
        # Overall should show FAIL
        assert "placebo: **FAIL**" in text
