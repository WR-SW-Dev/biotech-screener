"""Tests for CQ conviction tilt in portfolio_sizing.py — Spec 057."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from event_ev.portfolio_sizing import _zscore_within, compute_weights

# 30 tickers — wide enough that top names don't all hit the 10% cap
TICKERS = [f"T{i:02d}" for i in range(30)]
B6_SCORES = {f"T{i:02d}": 0.03 + i * 0.032 for i in range(30)}  # 0.03 → 0.96
TRAP_SCORES = {t: 0.5 for t in TICKERS}  # uniform trap (no trap effect)
# Top names: T28=0.926, T29=0.958 — pre-cap weights ~5-6% each with 30 names


def _make_cq(low_tickers: list, high_tickers: list) -> dict:
    """Build CQ map: low_tickers get -0.8, high_tickers get +0.8, rest 0."""
    cq = {t: 0.0 for t in TICKERS}
    for t in low_tickers:
        cq[t] = -0.8
    for t in high_tickers:
        cq[t] = 0.8
    return cq


class TestCQTiltDisabled:
    def test_no_effect_when_strength_zero(self):
        """Default cq_tilt_strength=0 means CQ has zero impact."""
        w_base = compute_weights(TICKERS, B6_SCORES, TRAP_SCORES)
        cq = {t: -1.0 for t in TICKERS}  # extreme CQ
        w_cq = compute_weights(TICKERS, B6_SCORES, TRAP_SCORES, cq_scores=cq, cq_tilt_strength=0.0)
        for t in TICKERS:
            assert abs(w_base.get(t, 0) - w_cq.get(t, 0)) < 1e-10

    def test_no_effect_when_cq_none(self):
        """No CQ scores → identical to baseline."""
        w_base = compute_weights(TICKERS, B6_SCORES, TRAP_SCORES)
        w_cq = compute_weights(TICKERS, B6_SCORES, TRAP_SCORES, cq_scores=None, cq_tilt_strength=0.15)
        for t in TICKERS:
            assert abs(w_base.get(t, 0) - w_cq.get(t, 0)) < 1e-10

    def test_no_effect_when_cq_empty(self):
        w_base = compute_weights(TICKERS, B6_SCORES, TRAP_SCORES)
        w_cq = compute_weights(TICKERS, B6_SCORES, TRAP_SCORES, cq_scores={}, cq_tilt_strength=0.15)
        for t in TICKERS:
            assert abs(w_base.get(t, 0) - w_cq.get(t, 0)) < 1e-10


class TestCQTiltDirection:
    def test_low_cq_upweighted_vs_high_cq(self):
        """Low CQ names should get more weight than high CQ names (inverse tilt)."""
        # T25, T26 = high B6 (above gate), won't hit 10% cap in 30-name universe
        cq = _make_cq(low_tickers=["T25"], high_tickers=["T26"])
        w = compute_weights(TICKERS, B6_SCORES, TRAP_SCORES, cq_scores=cq, cq_tilt_strength=0.15)
        w_base = compute_weights(TICKERS, B6_SCORES, TRAP_SCORES)

        # T25 (low CQ) should be upweighted relative to baseline
        # T26 (high CQ) should be downweighted relative to baseline
        ratio_25 = w.get("T25", 0) / max(w_base.get("T25", 0), 1e-10)
        ratio_26 = w.get("T26", 0) / max(w_base.get("T26", 0), 1e-10)
        assert ratio_25 > ratio_26, f"Low CQ should be upweighted: T25 ratio={ratio_25:.4f}, T26 ratio={ratio_26:.4f}"

    def test_symmetric_tilt(self):
        """Swapping CQ assignments should reverse the relative weight change."""
        cq_a = _make_cq(low_tickers=["T26"], high_tickers=["T25"])
        cq_b = _make_cq(low_tickers=["T25"], high_tickers=["T26"])
        w_a = compute_weights(TICKERS, B6_SCORES, TRAP_SCORES, cq_scores=cq_a, cq_tilt_strength=0.15)
        w_b = compute_weights(TICKERS, B6_SCORES, TRAP_SCORES, cq_scores=cq_b, cq_tilt_strength=0.15)
        # In arm_a, T26 has low CQ (boosted) → T26 weight increases
        # In arm_b, T26 has high CQ (penalized) → T26 weight decreases
        assert w_a.get("T26", 0) > w_b.get("T26", 0)


class TestCQTiltBounds:
    def test_weights_sum_to_one(self):
        """Weights must still sum to 1.0 regardless of tilt."""
        cq = {t: -1.0 if i % 2 == 0 else 1.0 for i, t in enumerate(TICKERS)}
        w = compute_weights(TICKERS, B6_SCORES, TRAP_SCORES, cq_scores=cq, cq_tilt_strength=0.15)
        total = sum(w.values())
        assert abs(total - 1.0) < 1e-6, f"Weights sum to {total}, expected 1.0"

    def test_no_negative_weights(self):
        """Even with extreme tilt, weights must stay non-negative."""
        cq = {t: 1.0 for t in TICKERS}  # all high CQ → all get penalized
        w = compute_weights(TICKERS, B6_SCORES, TRAP_SCORES, cq_scores=cq, cq_tilt_strength=0.15)
        for t, wt in w.items():
            assert wt >= 0, f"{t} has negative weight {wt}"

    def test_tilt_capped(self):
        """Extreme CQ values should be capped at ±cq_tilt_cap."""
        # With extreme CQ and high tilt strength, the modifier should still be bounded
        cq = {t: -5.0 for t in TICKERS}  # extreme negative (would want huge boost)
        w_extreme = compute_weights(
            TICKERS, B6_SCORES, TRAP_SCORES, cq_scores=cq, cq_tilt_strength=0.50, cq_tilt_cap=0.20
        )
        w_base = compute_weights(TICKERS, B6_SCORES, TRAP_SCORES)
        # No single weight should deviate by more than cap from baseline
        # (modulo renormalization effects)
        for t in TICKERS:
            if w_base.get(t, 0) > 0.01:
                ratio = w_extreme.get(t, 0) / w_base[t]
                # After renormalization, ratios compress, but pre-norm tilt is ±20%
                assert 0.5 < ratio < 2.0, f"{t}: weight ratio {ratio} too extreme"

    def test_strength_scales_effect(self):
        """Higher tilt strength should produce larger weight changes."""
        cq = _make_cq(low_tickers=["T26"], high_tickers=["T25"])
        w_base = compute_weights(TICKERS, B6_SCORES, TRAP_SCORES)
        w_low = compute_weights(TICKERS, B6_SCORES, TRAP_SCORES, cq_scores=cq, cq_tilt_strength=0.05)
        w_high = compute_weights(TICKERS, B6_SCORES, TRAP_SCORES, cq_scores=cq, cq_tilt_strength=0.20)

        # T26 deviation from base should be larger at higher strength
        dev_low = abs(w_low.get("T26", 0) - w_base.get("T26", 0))
        dev_high = abs(w_high.get("T26", 0) - w_base.get("T26", 0))
        assert dev_high > dev_low


class TestCQCoinvestGate:
    def test_low_b6_names_not_tilted(self):
        """Names below coinvest gate should not be affected by CQ tilt."""
        cq = {t: -1.0 for t in TICKERS}
        w_base = compute_weights(TICKERS, B6_SCORES, TRAP_SCORES)
        w_cq = compute_weights(
            TICKERS, B6_SCORES, TRAP_SCORES, cq_scores=cq, cq_tilt_strength=0.15, cq_coinvest_gate=0.50
        )

        # T05, T06 have B6 ~0.19/0.22 (well below gate), should keep constant ratio
        if w_base.get("T05", 0) > 0 and w_base.get("T06", 0) > 0:
            ratio_base = w_base["T05"] / w_base["T06"]
            ratio_cq = w_cq.get("T05", 0) / max(w_cq.get("T06", 0), 1e-10)
            assert abs(ratio_base - ratio_cq) < 0.01, f"Ungated names changed ratio: {ratio_base:.4f} → {ratio_cq:.4f}"

    def test_custom_gate(self):
        """With a high gate, low-B6 name ratios are preserved (not directly tilted)."""
        cq = {f"T{i:02d}": -0.8 + i * 0.055 for i in range(30)}
        # Gate at 0.80: only T24-T29 (B6 >= 0.80) should be directly tilted
        w_cq = compute_weights(
            TICKERS, B6_SCORES, TRAP_SCORES, cq_scores=cq, cq_tilt_strength=0.15, cq_coinvest_gate=0.80
        )
        w_base = compute_weights(TICKERS, B6_SCORES, TRAP_SCORES)

        # T05 and T06 (B6 ~0.19/0.22, far below gate) should keep their ratio
        if w_base.get("T05", 0) > 0 and w_base.get("T06", 0) > 0:
            ratio_base = w_base["T05"] / w_base["T06"]
            ratio_cq = w_cq.get("T05", 0) / max(w_cq.get("T06", 0), 1e-10)
            assert abs(ratio_base - ratio_cq) < 0.01


class TestZScoreWithin:
    def test_basic(self):
        vals = {"A": 1.0, "B": 2.0, "C": 3.0}
        z = _zscore_within(vals)
        assert z["A"] < 0
        assert abs(z["B"]) < 0.01  # middle value ≈ 0
        assert z["C"] > 0

    def test_single_value(self):
        z = _zscore_within({"A": 5.0})
        assert z["A"] == 0.0

    def test_uniform(self):
        vals = {"A": 3.0, "B": 3.0, "C": 3.0}
        z = _zscore_within(vals)
        for v in z.values():
            assert v == 0.0


class TestCQTiltIntegration:
    def test_recommended_settings(self):
        """Test with recommended production settings: strength=0.15, cap=0.20."""
        cq = {f"T{i:02d}": -0.5 + i * 0.033 for i in range(30)}  # spread from -0.5 to +0.46
        w = compute_weights(TICKERS, B6_SCORES, TRAP_SCORES, cq_scores=cq, cq_tilt_strength=0.15, cq_tilt_cap=0.20)
        assert abs(sum(w.values()) - 1.0) < 1e-6
        assert all(v >= 0 for v in w.values())
        assert len(w) >= 5  # not too many positions dropped

    def test_empty_tickers(self):
        w = compute_weights([], {}, {}, cq_scores={"A": 0.5}, cq_tilt_strength=0.15)
        assert w == {}

    def test_too_few_cq_scores_skips_tilt(self):
        """Need >=5 CQ scores in cohort to apply tilt."""
        cq = {"T29": -0.8}  # only 1 score
        w_cq = compute_weights(TICKERS, B6_SCORES, TRAP_SCORES, cq_scores=cq, cq_tilt_strength=0.15)
        w_base = compute_weights(TICKERS, B6_SCORES, TRAP_SCORES)
        for t in TICKERS:
            assert abs(w_cq.get(t, 0) - w_base.get(t, 0)) < 1e-10
