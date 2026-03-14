"""Tests for common/massive_chain_analytics.py."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from common.massive_chain_analytics import (
    compute_atm_straddle,
    compute_chain_analytics,
    compute_oi_concentration,
    compute_put_call_skew,
    compute_rr_25d,
    compute_volume_by_expiry_bucket,
    find_25delta_contracts,
)


def _contract(
    expiry="2026-04-17",
    ctype="call",
    strike=100.0,
    iv=0.50,
    delta=0.50,
    oi=1000,
    day_close=5.0,
    day_volume=500,
):
    return {
        "expiration_date": expiry,
        "contract_type": ctype,
        "strike_price": strike,
        "implied_volatility": iv,
        "delta": delta,
        "open_interest": oi,
        "day_close": day_close,
        "day_volume": day_volume,
    }


class TestFind25DeltaContracts:
    def test_finds_correct_contracts(self):
        contracts = [
            _contract(ctype="put", delta=-0.50, strike=95),
            _contract(ctype="put", delta=-0.25, strike=90, iv=0.55),
            _contract(ctype="put", delta=-0.10, strike=85),
            _contract(ctype="call", delta=0.50, strike=100),
            _contract(ctype="call", delta=0.25, strike=110, iv=0.45),
            _contract(ctype="call", delta=0.10, strike=120),
        ]
        put, call = find_25delta_contracts(contracts, "2026-04-17")
        assert put is not None
        assert put["strike_price"] == 90
        assert call is not None
        assert call["strike_price"] == 110

    def test_rejects_far_delta(self):
        """If no contract within 0.15 of target, returns None."""
        contracts = [
            _contract(ctype="put", delta=-0.50),
            _contract(ctype="call", delta=0.50),
        ]
        put, call = find_25delta_contracts(contracts, "2026-04-17")
        assert put is None
        assert call is None

    def test_missing_delta(self):
        contracts = [_contract(ctype="put", delta=None)]
        put, call = find_25delta_contracts(contracts, "2026-04-17")
        assert put is None


class TestRR25d:
    def test_positive_rr(self):
        """Call IV > put IV → positive (bullish skew)."""
        put = _contract(ctype="put", iv=0.55)
        call = _contract(ctype="call", iv=0.60)
        assert abs(compute_rr_25d(put, call) - 0.05) < 1e-10

    def test_negative_rr(self):
        put = _contract(ctype="put", iv=0.65)
        call = _contract(ctype="call", iv=0.50)
        assert abs(compute_rr_25d(put, call) - (-0.15)) < 1e-10

    def test_none_input(self):
        assert compute_rr_25d(None, _contract()) is None


class TestPutCallSkew:
    def test_positive_skew(self):
        """Put IV > call IV → positive (bearish sentiment)."""
        put = _contract(iv=0.60)
        call = _contract(iv=0.40)
        result = compute_put_call_skew(put, call)
        assert result is not None
        assert result > 0

    def test_none_input(self):
        assert compute_put_call_skew(None, _contract()) is None


class TestATMStraddle:
    def test_basic(self):
        contracts = [
            _contract(ctype="call", strike=100, day_close=6.0),
            _contract(ctype="put", strike=100, day_close=5.0),
            _contract(ctype="call", strike=105, day_close=3.0),
        ]
        result = compute_atm_straddle(contracts, 100.0, "2026-04-17")
        assert result["straddle_price"] == 11.0
        assert abs(result["actual_implied_move"] - 0.11) < 0.001

    def test_no_contracts(self):
        result = compute_atm_straddle([], 100.0, "2026-04-17")
        assert result["straddle_price"] is None


class TestOIConcentration:
    def test_basic(self):
        contracts = [
            _contract(ctype="call", oi=500, strike=100),
            _contract(ctype="call", oi=200, strike=105),
            _contract(ctype="put", oi=300, strike=95),
        ]
        result = compute_oi_concentration(contracts)
        assert result["total_oi"] == 1000
        assert result["max_oi"] == 500
        assert result["oi_concentration"] == 0.5
        assert result["put_oi"] == 300
        assert result["call_oi"] == 700


class TestVolumeByExpiryBucket:
    def test_bucketing(self):
        contracts = [
            _contract(expiry="2026-03-25", day_volume=100),  # 11d → near
            _contract(expiry="2026-05-15", day_volume=200),  # 62d → mid
            _contract(expiry="2026-08-15", day_volume=300),  # 154d → far
            _contract(expiry="2027-03-14", day_volume=400),  # 365d → core
        ]
        result = compute_volume_by_expiry_bucket(contracts, "2026-03-14")
        assert result["near_0_30d"] == 100
        assert result["mid_31_90d"] == 200
        assert result["far_91_180d"] == 300
        assert result["core_180d_plus"] == 400


class TestComputeChainAnalytics:
    def test_full_chain(self):
        contracts = [
            _contract(ctype="put", delta=-0.25, strike=90, iv=0.55, oi=300, day_close=3.0, day_volume=100),
            _contract(ctype="put", delta=-0.50, strike=100, iv=0.50, oi=500, day_close=5.0, day_volume=200),
            _contract(ctype="call", delta=0.50, strike=100, iv=0.48, oi=600, day_close=6.0, day_volume=300),
            _contract(ctype="call", delta=0.25, strike=110, iv=0.45, oi=200, day_close=2.0, day_volume=150),
        ]
        result = compute_chain_analytics(contracts, 100.0, "2026-03-14")
        assert result["status"] == "ok"
        assert result["rr_25d"] is not None  # 0.45 - 0.55 = -0.10
        assert result["put_call_skew"] is not None
        assert result["straddle_price"] == 11.0
        assert result["total_oi"] > 0

    def test_empty_chain(self):
        result = compute_chain_analytics([], 100.0)
        assert result["status"] == "no_data"

    def test_zero_price(self):
        result = compute_chain_analytics([_contract()], 0.0)
        assert result["status"] == "no_data"
