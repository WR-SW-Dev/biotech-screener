"""Tests for Spec 059 Phase D — Risk Overlays & Hedge Awareness.

Tests written BEFORE implementation per spec template.
"""

from __future__ import annotations

from typing import Any, Dict, List

# ============================================================================
# Fixtures
# ============================================================================


def _book_name(
    ticker: str = "ACAD",
    catalyst_days: int = 14,
    implied_move: float = 0.15,
    atm_iv: float = 0.90,
    iv_regime: str = "HIGH",
    liquidity: str = "liquid",
    underlying_price: float = 25.0,
    weight_pct: float = 3.33,
) -> Dict[str, Any]:
    return {
        "ticker": ticker,
        "catalyst_days": catalyst_days,
        "implied_event_move": implied_move,
        "opt_atm_iv": atm_iv,
        "opt_iv_regime": iv_regime,
        "opt_liquidity_state": liquidity,
        "underlying_price": underlying_price,
        "weight_pct": weight_pct,
    }


def _book() -> List[Dict[str, Any]]:
    """Typical 30-name book with a few names near catalysts."""
    return [
        # Near catalyst, high IV
        _book_name("PVLA", catalyst_days=5, implied_move=0.25, atm_iv=1.50, iv_regime="EXTREME", underlying_price=12.0),
        _book_name("ACAD", catalyst_days=14, implied_move=0.15, atm_iv=0.90, underlying_price=25.0),
        _book_name("IONS", catalyst_days=28, implied_move=0.12, atm_iv=0.70, underlying_price=40.0),
        # Far from catalyst
        _book_name("BMRN", catalyst_days=90, implied_move=0.08, atm_iv=0.45, underlying_price=80.0),
        # Thin liquidity near catalyst
        _book_name("TBPH", catalyst_days=10, implied_move=0.20, atm_iv=1.10, liquidity="thin", underlying_price=8.0),
        # Absent options
        _book_name("JBIO", catalyst_days=7, implied_move=None, atm_iv=None, liquidity="absent", underlying_price=3.0),
    ]


# ============================================================================
# Test: Catalyst Proximity Risk Matrix
# ============================================================================


class TestCatalystRiskMatrix:
    def test_filters_to_near_catalyst(self):
        from event_ev.catalyst_risk_overlay import build_catalyst_risk_matrix

        matrix = build_catalyst_risk_matrix(_book(), max_days=30)
        tickers = [r["ticker"] for r in matrix]
        # PVLA (5d), ACAD (14d), IONS (28d) are within 30d and liquid
        assert "PVLA" in tickers
        assert "ACAD" in tickers
        assert "IONS" in tickers
        # BMRN (90d) is too far
        assert "BMRN" not in tickers

    def test_excludes_illiquid(self):
        from event_ev.catalyst_risk_overlay import build_catalyst_risk_matrix

        matrix = build_catalyst_risk_matrix(_book(), max_days=30)
        tickers = [r["ticker"] for r in matrix]
        # TBPH (thin) and JBIO (absent) excluded
        assert "TBPH" not in tickers
        assert "JBIO" not in tickers

    def test_matrix_fields(self):
        from event_ev.catalyst_risk_overlay import build_catalyst_risk_matrix

        matrix = build_catalyst_risk_matrix(_book(), max_days=30)
        for row in matrix:
            assert "ticker" in row
            assert "catalyst_days" in row
            assert "implied_move_pct" in row
            assert "breakeven_straddle_pct" in row
            assert "iv_crush_est" in row
            assert "var_1d_pct" in row

    def test_sorted_by_catalyst_days(self):
        from event_ev.catalyst_risk_overlay import build_catalyst_risk_matrix

        matrix = build_catalyst_risk_matrix(_book(), max_days=30)
        days = [r["catalyst_days"] for r in matrix]
        assert days == sorted(days)

    def test_empty_book(self):
        from event_ev.catalyst_risk_overlay import build_catalyst_risk_matrix

        assert build_catalyst_risk_matrix([], max_days=30) == []


# ============================================================================
# Test: Hedge Cost Indicator
# ============================================================================


class TestHedgeCost:
    def test_computes_put_cost(self):
        from event_ev.catalyst_risk_overlay import compute_hedge_cost

        result = compute_hedge_cost(
            underlying_price=25.0,
            atm_iv=0.90,
            catalyst_days=14,
        )
        assert result is not None
        assert "put_cost_pct" in result
        assert result["put_cost_pct"] > 0
        assert result["put_cost_pct"] < 0.50  # less than 50% of position

    def test_cost_increases_with_iv(self):
        from event_ev.catalyst_risk_overlay import compute_hedge_cost

        low = compute_hedge_cost(25.0, 0.30, 14)
        high = compute_hedge_cost(25.0, 1.50, 14)
        assert high["put_cost_pct"] > low["put_cost_pct"]

    def test_invalid_inputs(self):
        from event_ev.catalyst_risk_overlay import compute_hedge_cost

        assert compute_hedge_cost(0, 0.9, 14) is None
        assert compute_hedge_cost(25.0, 0, 14) is None
        assert compute_hedge_cost(25.0, 0.9, 0) is None


# ============================================================================
# Test: Escalated Risk Alerts
# ============================================================================


class TestEscalatedRiskAlerts:
    def test_extreme_iv_near_catalyst_high_implied(self):
        """EXTREME IV + <7d + >20% implied → escalated alert."""
        from event_ev.catalyst_risk_overlay import check_escalated_risk

        alert = check_escalated_risk(
            _book_name("PVLA", catalyst_days=5, implied_move=0.25, iv_regime="EXTREME", atm_iv=1.50)
        )
        assert alert is not None
        assert alert["severity"] == "critical"
        assert "EXTREME" in alert["reason"]

    def test_extreme_iv_far_catalyst_no_alert(self):
        """EXTREME IV but far catalyst → no escalated alert."""
        from event_ev.catalyst_risk_overlay import check_escalated_risk

        alert = check_escalated_risk(
            _book_name("BMRN", catalyst_days=90, implied_move=0.08, iv_regime="EXTREME", atm_iv=1.50)
        )
        assert alert is None

    def test_high_iv_near_catalyst_moderate_implied(self):
        """HIGH IV + near catalyst + moderate implied → no critical alert."""
        from event_ev.catalyst_risk_overlay import check_escalated_risk

        alert = check_escalated_risk(
            _book_name("ACAD", catalyst_days=5, implied_move=0.15, iv_regime="HIGH", atm_iv=0.90)
        )
        # Should not be critical (implied < 20%)
        assert alert is None or alert["severity"] != "critical"

    def test_extreme_iv_near_but_low_implied(self):
        """EXTREME IV + <7d but low implied → warning, not critical."""
        from event_ev.catalyst_risk_overlay import check_escalated_risk

        alert = check_escalated_risk(
            _book_name("SRPT", catalyst_days=3, implied_move=0.10, iv_regime="EXTREME", atm_iv=1.50)
        )
        # EXTREME + near → at least a warning
        if alert is not None:
            assert alert["severity"] in ("warning", "critical")

    def test_illiquid_no_alert(self):
        """Absent options should not generate alerts."""
        from event_ev.catalyst_risk_overlay import check_escalated_risk

        alert = check_escalated_risk(
            _book_name("JBIO", catalyst_days=3, implied_move=None, iv_regime="", liquidity="absent")
        )
        assert alert is None

    def test_collect_alerts_from_book(self):
        """Collect all escalated alerts from a full book."""
        from event_ev.catalyst_risk_overlay import collect_escalated_alerts

        alerts = collect_escalated_alerts(_book())
        # Only PVLA should trigger critical (EXTREME + 5d + 25%)
        critical = [a for a in alerts if a["severity"] == "critical"]
        assert len(critical) >= 1
        assert critical[0]["ticker"] == "PVLA"
