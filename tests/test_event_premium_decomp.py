"""Tests for event premium decomposition — within-top-30 ranking features."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.event_premium_decomp import compute_event_premium_decomp, compute_universe_decomp


def _base_row(**overrides):
    row = {
        "ticker": "TEST",
        "opt_front_iv": "0.80",
        "opt_back_iv": "0.60",
        "opt_atm_iv": "0.75",
        "opt_rr_25d": "0.05",
        "opt_term_slope": "-0.25",
        "implied_event_move": "0.30",
        "atm_iv_change_5d": "0.08",
        "catalyst_days": "20",
        "catalyst_event_type": "FDA_PDUFA_DATE",
        "lead_program_phase": "3",
        "opt_has_data": "1",
    }
    row.update(overrides)
    return row


class TestEventPremiumRatio:
    def test_backwardation(self):
        r = compute_event_premium_decomp(_base_row())
        assert r["epd_event_premium_ratio"] is not None
        assert r["epd_event_premium_ratio"] > 1.0  # front > back = backwardation

    def test_contango(self):
        r = compute_event_premium_decomp(_base_row(opt_front_iv="0.40", opt_back_iv="0.60"))
        assert r["epd_event_premium_ratio"] < 1.0

    def test_missing_back_iv(self):
        r = compute_event_premium_decomp(_base_row(opt_back_iv=""))
        assert r["epd_event_premium_ratio"] is None


class TestTermSlopeZ:
    def test_with_history(self):
        hist = [
            {"date": f"2026-01-{i:02d}", "atm_iv": 0.5, "front_iv": 0.5, "back_iv": 0.50 + 0.02 * (i % 5)}
            for i in range(1, 21)
        ]
        r = compute_event_premium_decomp(_base_row(), iv_history=hist)
        # Current slope is -0.25, historical slopes are small positive → z should be negative
        assert r["epd_term_slope_z"] is not None
        assert r["epd_term_slope_z"] < 0

    def test_insufficient_history(self):
        hist = [{"date": "2026-01-01", "atm_iv": 0.5}]
        r = compute_event_premium_decomp(_base_row(), iv_history=hist)
        assert r["epd_term_slope_z"] is None

    def test_bounded(self):
        hist = [{"date": f"2026-01-{i:02d}", "atm_iv": 0.5, "front_iv": 0.5, "back_iv": 0.50001} for i in range(1, 21)]
        r = compute_event_premium_decomp(
            _base_row(opt_term_slope="-5.0"),
            iv_history=hist,
        )
        assert r["epd_term_slope_z"] is not None
        assert -3.0 <= r["epd_term_slope_z"] <= 3.0


class TestSkewRichness:
    def test_with_rr_history(self):
        rr_hist = [0.02, 0.03, 0.01, 0.02, 0.03, 0.02, 0.01, 0.03]
        r = compute_event_premium_decomp(_base_row(opt_rr_25d="0.15"), rr_history=rr_hist)
        assert r["epd_skew_richness_z"] is not None
        assert r["epd_skew_richness_z"] > 1.0  # 0.15 is way above history of ~0.02

    def test_no_history(self):
        r = compute_event_premium_decomp(_base_row())
        assert r["epd_skew_richness_z"] is None

    def test_bounded(self):
        rr_hist = [0.02] * 10
        r = compute_event_premium_decomp(_base_row(opt_rr_25d="99.0"), rr_history=rr_hist)
        if r["epd_skew_richness_z"] is not None:
            assert -3.0 <= r["epd_skew_richness_z"] <= 3.0


class TestImpliedVsRealized:
    def test_overpriced(self):
        table = {"FDA_PDUFA_DATE": {"phase3": {"p50": 0.15, "n": 20}}}
        r = compute_event_premium_decomp(_base_row(), event_move_table=table)
        # implied=0.30 vs historical p50=0.15 → ratio 2.0 → overpriced
        assert r["epd_implied_vs_realized_ratio"] is not None
        assert r["epd_implied_vs_realized_ratio"] > 1.3
        assert r["epd_mispricing_direction"] == "overpriced"

    def test_underpriced(self):
        table = {"FDA_PDUFA_DATE": {"phase3": {"p50": 0.50, "n": 20}}}
        r = compute_event_premium_decomp(_base_row(), event_move_table=table)
        # implied=0.30 vs p50=0.50 → ratio 0.6 → underpriced
        assert r["epd_mispricing_direction"] == "underpriced"

    def test_no_table(self):
        r = compute_event_premium_decomp(_base_row())
        assert r["epd_implied_vs_realized_ratio"] is None


class TestIVMomentum:
    def test_ramping(self):
        r = compute_event_premium_decomp(_base_row(atm_iv_change_5d="0.08"))
        assert r["epd_iv_ramping"] is True
        assert r["epd_iv_crushing"] is False

    def test_crushing(self):
        r = compute_event_premium_decomp(_base_row(atm_iv_change_5d="-0.10"))
        assert r["epd_iv_crushing"] is True
        assert r["epd_iv_ramping"] is False

    def test_flat(self):
        r = compute_event_premium_decomp(_base_row(atm_iv_change_5d="0.01"))
        assert r["epd_iv_ramping"] is False
        assert r["epd_iv_crushing"] is False


class TestCatalystProximity:
    def test_imminent(self):
        r = compute_event_premium_decomp(_base_row(catalyst_days="7"))
        assert r["epd_catalyst_proximity_bucket"] == "imminent"

    def test_near(self):
        r = compute_event_premium_decomp(_base_row(catalyst_days="30"))
        assert r["epd_catalyst_proximity_bucket"] == "near"

    def test_far(self):
        r = compute_event_premium_decomp(_base_row(catalyst_days="120"))
        assert r["epd_catalyst_proximity_bucket"] == "far"

    def test_iv_per_day(self):
        r = compute_event_premium_decomp(_base_row(opt_atm_iv="0.80", catalyst_days="20"))
        assert r["epd_iv_per_catalyst_day"] is not None
        assert r["epd_iv_per_catalyst_day"] > 0


class TestSurfaceRegime:
    def test_event_loaded(self):
        r = compute_event_premium_decomp(_base_row())
        # front/back = 0.80/0.60 = 1.33 > 1.15 → event_loaded
        assert "event_loaded" in r["epd_surface_regime"]

    def test_ramping(self):
        r = compute_event_premium_decomp(_base_row(atm_iv_change_5d="0.10"))
        assert "iv_ramping" in r["epd_surface_regime"]

    def test_flat(self):
        r = compute_event_premium_decomp(_base_row(opt_front_iv="0.50", opt_back_iv="0.50", atm_iv_change_5d="0.01"))
        assert r["epd_surface_regime"] == "flat"


class TestQuality:
    def test_full_quality(self):
        r = compute_event_premium_decomp(_base_row())
        assert r["epd_quality"] in ("full", "partial")

    def test_sparse_quality(self):
        r = compute_event_premium_decomp({"ticker": "EMPTY"})
        assert r["epd_quality"] == "sparse"


class TestUniverseDecomp:
    def test_zscore_across_universe(self):
        rows = [
            _base_row(ticker="A", opt_front_iv="1.00", opt_back_iv="0.50"),  # big premium
            _base_row(ticker="B", opt_front_iv="0.55", opt_back_iv="0.50"),  # small premium
            _base_row(ticker="C", opt_front_iv="0.50", opt_back_iv="0.60"),  # contango
        ]
        results = compute_universe_decomp(rows)
        assert len(results) == 3
        # A should have highest z, C lowest
        by_ticker = {r["ticker"]: r for r in results}
        assert by_ticker["A"]["epd_event_premium_ratio_z"] > by_ticker["C"]["epd_event_premium_ratio_z"]

    def test_deterministic(self):
        rows = [_base_row(ticker="X"), _base_row(ticker="Y")]
        r1 = compute_universe_decomp(rows)
        r2 = compute_universe_decomp(rows)
        assert r1 == r2
