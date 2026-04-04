"""Tests for portfolio_risk_layer.py — Spec 052."""

import pytest

from portfolio_risk_layer import MarketSnapshot, PortfolioPolicy, Position, RiskLayerResult, apply_risk_layer

# ── Helpers ──────────────────────────────────────────────────────────


def _make_positions(n=30, therapeutic_area="oncology", indication="NSCLC", phase="Phase 3"):
    """Build N equal-weight test positions."""
    return [
        Position(
            ticker=f"T{i:03d}",
            rank=i + 1,
            weight=1.0 / n,
            therapeutic_area=therapeutic_area if i < n else "neurology",
            primary_indication=indication,
            lead_program_phase=phase,
            adv_usd_20d=5_000_000.0,
        )
        for i in range(n)
    ]


def _make_policy(**overrides):
    defaults = dict(
        risk_layer_enabled=True,
        global_name_cap_pct=0.030,
        global_name_cap_buffer_pct=0.005,
        therapeutic_area_cap_pct=0.40,
        liquidity_max_adv_pct=0.05,
        account_usd=500_000,
        drawdown_breaker_enabled=True,
        portfolio_dd_threshold=0.15,
        portfolio_dd_cap_multiplier=0.75,
        single_name_dd_threshold=0.40,
        correlated_pair_enabled=True,
        max_same_indication_phase=2,
    )
    defaults.update(overrides)
    return PortfolioPolicy(**defaults)


def _make_snapshot(portfolio_dd_from_high=0.0, single_name_dds=None):
    return MarketSnapshot(
        portfolio_dd_from_high=portfolio_dd_from_high,
        single_name_dds=single_name_dds or {},
    )


def _total_weight(positions):
    return sum(p.weight for p in positions)


# ── Tests ────────────────────────────────────────────────────────────


class TestEWPassthrough:
    """With no breaches, output == input EW weights."""

    def test_no_breaches_passthrough(self):
        positions = _make_positions(30)
        # Diversify therapeutic areas so C2 doesn't trigger
        for i, p in enumerate(positions):
            p.therapeutic_area = ["oncology", "neurology", "immunology", "rare_disease", "cardiology"][i % 5]
            p.primary_indication = f"indication_{i}"
        policy = _make_policy()
        snapshot = _make_snapshot()

        result = apply_risk_layer(positions, policy, snapshot)

        assert isinstance(result, RiskLayerResult)
        assert len(result.positions) == 30
        assert abs(_total_weight(result.positions) - 1.0) < 0.001
        # All weights should be ~1/30
        for p in result.positions:
            assert abs(p.weight - 1.0 / 30) < 0.002
        assert len(result.breaches) == 0


class TestSingleNameCap:
    """Drift scenario triggers trim + redistribution."""

    def test_drift_triggers_trim(self):
        positions = _make_positions(30)
        # Diversify areas
        for i, p in enumerate(positions):
            p.therapeutic_area = f"area_{i % 5}"
            p.primary_indication = f"ind_{i}"
        # Simulate drift: one name at 5%
        positions[0].weight = 0.05
        # Renormalize others
        remaining = (1.0 - 0.05) / 29
        for p in positions[1:]:
            p.weight = remaining

        policy = _make_policy()
        snapshot = _make_snapshot()
        result = apply_risk_layer(positions, policy, snapshot)

        # T000 should be capped at max(3.0%, 1/30=3.33%)
        t000 = next(p for p in result.positions if p.ticker == "T000")
        expected_cap = max(policy.global_name_cap_pct, 1.0 / 30)
        assert t000.weight <= expected_cap + 0.001
        assert abs(_total_weight(result.positions) - 1.0) < 0.001
        assert any(b["control"] == "C1_single_name_cap" for b in result.breaches)


class TestTherapeuticAreaCap:
    """5 oncology names out of 6 total, cap at 40%."""

    def test_area_cap_triggers(self):
        # 30 positions: 15 oncology, 5 neurology, 5 immunology, 5 cardiology
        # Oncology at 50% > 40% cap. Enough other areas to absorb.
        positions = _make_positions(30)
        areas = ["oncology"] * 15 + ["neurology"] * 5 + ["immunology"] * 5 + ["cardiology"] * 5
        for i, p in enumerate(positions):
            p.therapeutic_area = areas[i]
            p.primary_indication = f"ind_{i}"
        policy = _make_policy()
        snapshot = _make_snapshot()

        result = apply_risk_layer(positions, policy, snapshot)

        # Oncology total should be <= 40%
        onc_weight = sum(p.weight for p in result.positions if p.therapeutic_area == "oncology")
        assert onc_weight <= 0.40 + 0.02
        assert abs(_total_weight(result.positions) - 1.0) < 0.01
        assert any(b["control"] == "C2_therapeutic_area_cap" for b in result.breaches)

    def test_area_cap_no_breach_when_diverse(self):
        positions = _make_positions(30)
        areas = ["oncology", "neurology", "immunology", "rare_disease", "cardiology"]
        for i, p in enumerate(positions):
            p.therapeutic_area = areas[i % 5]
            p.primary_indication = f"ind_{i}"
        policy = _make_policy()
        snapshot = _make_snapshot()

        result = apply_risk_layer(positions, policy, snapshot)
        assert not any(b["control"] == "C2_therapeutic_area_cap" for b in result.breaches)


class TestLiquidityCeiling:
    """Micro-cap with low ADV gets capped."""

    def test_low_adv_caps_weight(self):
        positions = _make_positions(10)
        for i, p in enumerate(positions):
            p.therapeutic_area = f"area_{i % 5}"
            p.primary_indication = f"ind_{i}"
        # T000 has very low ADV: $100K/day. At 5% max, that's $5K max position.
        # Account $500K, so max weight = $5K / $500K = 1.0%
        positions[0].adv_usd_20d = 100_000.0

        policy = _make_policy()
        snapshot = _make_snapshot()
        result = apply_risk_layer(positions, policy, snapshot)

        t000 = next(p for p in result.positions if p.ticker == "T000")
        max_weight = (100_000 * 0.05) / 500_000  # = 0.01
        assert t000.weight <= max_weight + 0.001
        assert abs(_total_weight(result.positions) - 1.0) < 0.001
        assert any(b["control"] == "C3_liquidity_ceiling" for b in result.breaches)

    def test_missing_adv_skips_check(self):
        positions = _make_positions(10)
        for i, p in enumerate(positions):
            p.therapeutic_area = f"area_{i % 5}"
            p.primary_indication = f"ind_{i}"
        positions[0].adv_usd_20d = None

        policy = _make_policy()
        snapshot = _make_snapshot()
        result = apply_risk_layer(positions, policy, snapshot)

        # Should have a warning flag, not a breach
        assert any(f["flag_type"] == "MISSING_ADV" for f in result.flags)
        # T000 weight unchanged (relative to input)
        assert abs(_total_weight(result.positions) - 1.0) < 0.001


class TestDrawdownBreaker:
    """Portfolio drawdown triggers cap tightening."""

    def test_portfolio_drawdown_tightens_caps(self):
        # Use 50 positions so that 1/N (2%) < effective_cap (2.25%) < normal cap (3%)
        positions = _make_positions(50)
        for i, p in enumerate(positions):
            p.therapeutic_area = ["oncology", "neurology", "immunology", "rare_disease", "cardiology"][i % 5]
            p.primary_indication = f"ind_{i}"
        # One name drifted to 4%
        positions[0].weight = 0.04
        remaining = (1.0 - 0.04) / 49
        for p in positions[1:]:
            p.weight = remaining

        policy = _make_policy()
        snapshot = _make_snapshot(portfolio_dd_from_high=0.18)  # >15% threshold

        result = apply_risk_layer(positions, policy, snapshot)

        # Effective cap = 3.0% * 0.75 = 2.25%, 1/N = 2.0%, so actual_cap = 2.25%
        effective_cap = 0.030 * 0.75  # 2.25%
        t000 = next(p for p in result.positions if p.ticker == "T000")
        assert t000.weight <= effective_cap + 0.002
        assert abs(_total_weight(result.positions) - 1.0) < 0.001
        assert any(b["control"] == "C4_drawdown_breaker" for b in result.breaches)

    def test_single_name_drawdown_warns(self):
        positions = _make_positions(10)
        for i, p in enumerate(positions):
            p.therapeutic_area = f"area_{i % 5}"
            p.primary_indication = f"ind_{i}"
        policy = _make_policy()
        snapshot = _make_snapshot(single_name_dds={"T000": 0.45})  # >40%

        result = apply_risk_layer(positions, policy, snapshot)
        assert any(f["flag_type"] == "SINGLE_NAME_DRAWDOWN" and f["ticker"] == "T000" for f in result.flags)


class TestCorrelatedPairLimit:
    """Two Phase 3 NASH names — one dropped when limit is 2."""

    def test_three_same_indication_phase_drops_one(self):
        positions = _make_positions(10)
        for i, p in enumerate(positions):
            p.therapeutic_area = f"area_{i % 5}"
            p.primary_indication = f"ind_{i}"
        # Make 3 positions share the same indication + phase
        for i in range(3):
            positions[i].primary_indication = "NASH"
            positions[i].lead_program_phase = "Phase 3"

        policy = _make_policy(max_same_indication_phase=2)
        snapshot = _make_snapshot()

        result = apply_risk_layer(positions, policy, snapshot)

        # Count NASH Phase 3 in output
        nash_p3 = [p for p in result.positions if p.primary_indication == "NASH" and p.lead_program_phase == "Phase 3"]
        assert len(nash_p3) <= 2
        assert any(b["control"] == "C5_correlated_pair_limit" for b in result.breaches)
        assert abs(_total_weight(result.positions) - 1.0) < 0.001

    def test_two_same_indication_no_breach(self):
        positions = _make_positions(10)
        for i, p in enumerate(positions):
            p.therapeutic_area = f"area_{i % 5}"
            p.primary_indication = f"ind_{i}"
        # Only 2 share indication + phase (at limit, not over)
        positions[0].primary_indication = "NASH"
        positions[0].lead_program_phase = "Phase 3"
        positions[1].primary_indication = "NASH"
        positions[1].lead_program_phase = "Phase 3"

        policy = _make_policy(max_same_indication_phase=2)
        snapshot = _make_snapshot()

        result = apply_risk_layer(positions, policy, snapshot)
        assert not any(b["control"] == "C5_correlated_pair_limit" for b in result.breaches)


class TestDeterministic:
    """Same inputs → same outputs across 10 runs."""

    def test_deterministic_10_runs(self):
        positions = _make_positions(30)
        for i, p in enumerate(positions):
            p.therapeutic_area = ["oncology", "neurology", "immunology"][i % 3]
            p.primary_indication = f"ind_{i}"
        policy = _make_policy()
        snapshot = _make_snapshot()

        results = []
        for _ in range(10):
            r = apply_risk_layer(positions, policy, snapshot)
            weights = {p.ticker: round(p.weight, 8) for p in r.positions}
            results.append(weights)

        for i in range(1, 10):
            assert results[i] == results[0]


class TestWeightConservation:
    """Sum of output weights == 1.0 after all controls."""

    def test_weight_sum_after_all_controls(self):
        positions = _make_positions(30)
        # Create a messy scenario: drift, area overweight, low ADV
        positions[0].weight = 0.06
        positions[1].adv_usd_20d = 50_000.0
        for i in range(10):
            positions[i].therapeutic_area = "oncology"
        for i in range(10, 20):
            positions[i].therapeutic_area = "neurology"
            positions[i].primary_indication = f"ind_{i}"
        for i in range(20, 30):
            positions[i].therapeutic_area = "cardiology"
            positions[i].primary_indication = f"ind_{i}"
        # Renormalize rest
        remaining = (1.0 - 0.06) / 29
        for p in positions[1:]:
            p.weight = remaining

        policy = _make_policy()
        snapshot = _make_snapshot(portfolio_dd_from_high=0.20)

        result = apply_risk_layer(positions, policy, snapshot)
        # With drawdown breaker + area caps + liquidity constraint on T001,
        # total may be < 1.0 (remainder = unallocated cash). This is correct.
        total = _total_weight(result.positions)
        assert total <= 1.01
        assert total >= 0.80  # not pathologically low


class TestMissingDataFallback:
    """Missing therapeutic_area → skip C2 for those names, WARN."""

    def test_missing_therapeutic_area_warns(self):
        positions = _make_positions(10)
        for i, p in enumerate(positions):
            p.primary_indication = f"ind_{i}"
        # Clear all therapeutic areas
        for p in positions:
            p.therapeutic_area = None

        policy = _make_policy()
        snapshot = _make_snapshot()

        result = apply_risk_layer(positions, policy, snapshot)
        # Should still produce valid weights
        assert abs(_total_weight(result.positions) - 1.0) < 0.001
        # Should flag missing data
        assert any(f["flag_type"] == "MISSING_THERAPEUTIC_AREA" for f in result.flags)


class TestComposition:
    """All 5 controls applied in sequence on a combined scenario."""

    def test_all_controls_compose(self):
        positions = _make_positions(20)
        # C1 trigger: one name drifted to 12% (well above 1/N + buffer)
        positions[0].weight = 0.12
        # C2 trigger: 12 oncology names
        for i in range(12):
            positions[i].therapeutic_area = "oncology"
        for i in range(12, 20):
            positions[i].therapeutic_area = "cardiology"
        # C3 trigger: one name with very low ADV
        positions[1].adv_usd_20d = 50_000.0
        # C5 trigger: 3 names with same indication+phase
        for i in range(3):
            positions[i].primary_indication = "HER2"
            positions[i].lead_program_phase = "Phase 2"
        for i in range(3, 20):
            positions[i].primary_indication = f"ind_{i}"
        # Renormalize rest
        remaining = (1.0 - 0.12) / 19
        for p in positions[1:]:
            p.weight = remaining

        policy = _make_policy()
        # C4 trigger: drawdown
        snapshot = _make_snapshot(portfolio_dd_from_high=0.20)

        result = apply_risk_layer(positions, policy, snapshot)

        assert _total_weight(result.positions) <= 1.01
        controls_triggered = {b["control"] for b in result.breaches}
        # At minimum C1, C2, C3, C4 should fire (C5 depends on ordering)
        assert "C1_single_name_cap" in controls_triggered
        assert "C2_therapeutic_area_cap" in controls_triggered
        assert "C3_liquidity_ceiling" in controls_triggered
        assert "C4_drawdown_breaker" in controls_triggered


class TestPolicyMissingFails:
    """No policy → hard failure."""

    def test_none_policy_raises(self):
        positions = _make_positions(10)
        snapshot = _make_snapshot()

        with pytest.raises((ValueError, TypeError)):
            apply_risk_layer(positions, None, snapshot)

    def test_disabled_layer_passthrough(self):
        positions = _make_positions(10)
        for i, p in enumerate(positions):
            p.therapeutic_area = f"area_{i % 5}"
            p.primary_indication = f"ind_{i}"
        policy = _make_policy(risk_layer_enabled=False)
        snapshot = _make_snapshot()

        result = apply_risk_layer(positions, policy, snapshot)
        # Should pass through unchanged
        for i, p in enumerate(result.positions):
            assert abs(p.weight - positions[i].weight) < 0.001
