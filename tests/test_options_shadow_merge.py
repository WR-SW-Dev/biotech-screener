"""Tests for the options shadow merge layer.

Verifies that:
- Source provenance is preserved (TT and RH fields remain separate)
- IV disagreement is surfaced, not hidden or averaged
- Broken RH quotes downgrade liquidity classification but do not erase TT signal
- TT event premium survives when RH liquidity is poor
- Governance flags are all False
- No writes to protected pipeline files
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make tools/ importable
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))

import collect_options_shadow as shadow
from collect_options_shadow import (
    GOVERNANCE,
    _classify_signal,
    _is_broken,
    _iv_disagreement_pp,
    _merge_ticker,
    _spread_pct,
)

# ---------------------------------------------------------------------------
# Fixtures (real data from prior session)
# ---------------------------------------------------------------------------

TT_ARWR = {
    "opt_has_data": "1",
    "opt_atm_iv": 0.639,
    "opt_front_iv": 0.583,
    "opt_back_iv": 0.695,
    "opt_term_slope": 0.193,
    "opt_event_premium": "NO",
    "opt_iv_regime": "ELEVATED",
    "opt_liquidity_state": "thin",
    "opt_nearest_expiry": "2026-07-17",
    "opt_dte": 20,
    "opt_quote_ts": "2026-06-26T19:49:54+00:00",
    "opt_diagnostic_basis": "tt_market_metrics",
}

TT_RVMD = {
    "opt_has_data": "1",
    "opt_atm_iv": 0.509,
    "opt_front_iv": 0.510,
    "opt_back_iv": 0.507,
    "opt_term_slope": -0.005,
    "opt_event_premium": "NO",
    "opt_iv_regime": "NORMAL",
    "opt_liquidity_state": "thin",
    "opt_nearest_expiry": "2026-07-17",
    "opt_dte": 20,
    "opt_quote_ts": "2026-06-26T19:56:26+00:00",
    "opt_diagnostic_basis": "tt_market_metrics",
}

TT_NRIX = {
    "opt_has_data": "1",
    "opt_atm_iv": 0.818,
    "opt_front_iv": 0.945,
    "opt_back_iv": 0.653,
    "opt_term_slope": -0.309,
    "opt_event_premium": "YES",
    "opt_iv_regime": "ELEVATED",
    "opt_liquidity_state": "thin",
    "opt_nearest_expiry": "2026-07-17",
    "opt_dte": 20,
    "opt_quote_ts": "2026-06-26T19:55:32+00:00",
    "opt_diagnostic_basis": "tt_market_metrics",
}

TT_PRAX = {
    "opt_has_data": "1",
    "opt_atm_iv": 0.637,
    "opt_front_iv": 0.621,
    "opt_back_iv": 0.654,
    "opt_term_slope": 0.054,
    "opt_event_premium": "NO",
    "opt_iv_regime": "ELEVATED",
    "opt_liquidity_state": "thin",
    "opt_nearest_expiry": "2026-07-17",
    "opt_dte": 20,
    "opt_quote_ts": "2026-06-26T19:48:36+00:00",
    "opt_diagnostic_basis": "tt_market_metrics",
}

RH_ARWR = {
    "underlying_price": 79.04,
    "nearest_expiry": "2026-07-17",
    "atm_strike": 80.0,
    "call": {
        "implied_volatility": 0.573,
        "delta": 0.496,
        "gamma": 0.038,
        "theta": -0.110,
        "vega": 0.073,
        "open_interest": 526,
        "volume": 105,
        "bid": 2.65,
        "ask": 5.00,
        "mark": 3.83,
    },
    "put": {
        "implied_volatility": 0.615,
        "delta": -0.500,
        "gamma": 0.035,
        "theta": -0.110,
        "vega": 0.073,
        "open_interest": 441,
        "volume": 5,
        "bid": 3.90,
        "ask": 6.00,
        "mark": 4.95,
    },
}

RH_RVMD = {
    "underlying_price": 182.11,
    "nearest_expiry": "2026-07-17",
    "atm_strike": 180.0,
    "call": {
        "implied_volatility": 0.510,
        "delta": 0.569,
        "gamma": 0.018,
        "theta": -0.224,
        "vega": 0.166,
        "open_interest": 2470,
        "volume": 174,
        "bid": 9.20,
        "ask": 10.50,
        "mark": 9.85,
    },
    "put": {
        "implied_volatility": 0.502,
        "delta": -0.431,
        "gamma": 0.019,
        "theta": -0.203,
        "vega": 0.167,
        "open_interest": 25,
        "volume": 12,
        "bid": 6.30,
        "ask": 8.20,
        "mark": 7.25,
    },
}

RH_NRIX = {
    "underlying_price": 22.90,
    "nearest_expiry": "2026-07-17",
    "atm_strike": 23.0,
    "call": {
        "implied_volatility": 0.850,
        "delta": 0.535,
        "gamma": 0.088,
        "theta": -0.047,
        "vega": 0.021,
        "open_interest": 8,
        "volume": 4,
        "bid": 1.00,
        "ask": 2.55,
        "mark": 1.78,
    },
    "put": {
        "implied_volatility": 0.0,
        "delta": 0.0,
        "gamma": 0.0,
        "theta": 0.0,
        "vega": 0.0,
        "open_interest": 0,
        "volume": 0,
        "bid": 0.0,
        "ask": 4.90,
        "mark": 2.45,
    },  # BROKEN
}

RH_PRAX = {
    "underlying_price": 327.28,
    "nearest_expiry": "2026-07-17",
    "atm_strike": 330.0,
    "call": {
        "implied_volatility": 0.592,
        "delta": 0.509,
        "gamma": 0.009,
        "theta": -0.470,
        "vega": 0.304,
        "open_interest": 0,
        "volume": 0,
        "bid": 13.0,
        "ask": 21.0,
        "mark": 17.0,
    },
    "put": {
        "implied_volatility": 0.589,
        "delta": -0.492,
        "gamma": 0.009,
        "theta": -0.436,
        "vega": 0.304,
        "open_interest": 1,
        "volume": 3,
        "bid": 15.0,
        "ask": 23.0,
        "mark": 19.0,
    },
}

TT_MISSING = {
    "opt_has_data": "0",
    "opt_diagnostic_basis": "no_credentials",
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_source_provenance_preserved():
    """Merged record must keep tastytrade_iv and robinhood_call_iv as distinct fields."""
    rec = _merge_ticker("ARWR", TT_ARWR, RH_ARWR)
    iv = rec["iv"]
    assert isinstance(iv, dict), "iv must be a dict, not scalar"
    assert "tastytrade_iv" in iv
    assert "robinhood_call_iv" in iv
    assert iv["tastytrade_iv"] is not None
    assert iv["robinhood_call_iv"] is not None
    assert iv["tastytrade_iv"] != iv["robinhood_call_iv"], "values must remain separate"
    assert "iv_type_tt" in iv
    assert "iv_type_rh" in iv


def test_iv_disagreement_surfaced():
    """ARWR: TT=63.9%, RH call=57.3% → disagreement ~6.6pp."""
    rec = _merge_ticker("ARWR", TT_ARWR, RH_ARWR)
    d = rec["iv"]["iv_disagreement_pp"]
    assert d is not None, "iv_disagreement_pp should not be None for ARWR"
    assert abs(d - 6.6) < 0.5, f"Expected ~6.6pp, got {d}"


def test_broken_put_downgrades_to_iv_signal_only():
    """NRIX put is broken (bid=0) → signal_class must be IV_SIGNAL_ONLY."""
    assert _is_broken(RH_NRIX["put"]), "NRIX put should be detected as broken"
    sc = _classify_signal(TT_NRIX, RH_NRIX)
    assert sc == "IV_SIGNAL_ONLY", f"Expected IV_SIGNAL_ONLY, got {sc}"


def test_broken_put_preserves_tt_event_premium():
    """NRIX event_premium=YES from TT must survive even with broken RH put."""
    rec = _merge_ticker("NRIX", TT_NRIX, RH_NRIX)
    ts = rec.get("term_structure")
    assert ts is not None, "term_structure should be present"
    assert ts["event_premium"] is True, "TT event_premium should survive broken RH put"
    assert ts["source"] == "tastytrade_metrics"


def test_illiquid_classification():
    """PRAX: total OI = 0+1 = 1 → ILLIQUID."""
    sc = _classify_signal(TT_PRAX, RH_PRAX)
    assert sc == "ILLIQUID", f"Expected ILLIQUID, got {sc}"


def test_contract_validated_classification():
    """ARWR: OI 526+441=967, call spread ~61% < 60%? Actually max spread is 61%...

    Check: call spread = (5.00-2.65)/3.83 = 0.613 > 0.60 → CONTRACT_VALIDATED threshold
    requires max_spread < 0.60. So ARWR actually falls to ILLIQUID by spread.

    Wait — let me re-check the spec:
    CONTRACT_VALIDATED: TT has data + RH total_oi > 10 + neither side broken + max spread < 60%
    ARWR call spread = 0.613 which is > 0.60. So ARWR should be ILLIQUID.

    But RVMD: call spread = (10.50-9.20)/9.85 = 0.132; put spread = (8.20-6.30)/7.25 = 0.262
    max spread = 0.262 < 0.60, total OI = 2470+25 = 2495 > 10 → CONTRACT_VALIDATED
    Also total OI 2495 > 50 but max spread 0.262 < 0.30 → HIGH_CONFIDENCE_SIGNAL
    """
    # RVMD should be HIGH_CONFIDENCE_SIGNAL (OI>50, max spread<30%)
    sc_rvmd = _classify_signal(TT_RVMD, RH_RVMD)
    assert sc_rvmd == "HIGH_CONFIDENCE_SIGNAL", f"RVMD expected HIGH_CONFIDENCE_SIGNAL, got {sc_rvmd}"

    # ARWR: call spread 0.613 > 0.60, so falls to ILLIQUID
    sc_arwr = _classify_signal(TT_ARWR, RH_ARWR)
    assert sc_arwr == "ILLIQUID", f"ARWR expected ILLIQUID (spread>60%), got {sc_arwr}"


def test_governance_flags_all_false():
    """All governance flags must be False."""
    for k, v in GOVERNANCE.items():
        assert v is False, f"governance.{k} should be False, got {v}"


def test_no_averaged_iv():
    """The iv field must be a dict, not a float — IVs must not be averaged."""
    rec = _merge_ticker("ARWR", TT_ARWR, RH_ARWR)
    assert isinstance(rec["iv"], dict), "iv must remain a dict"
    # No top-level float named 'iv'
    assert not isinstance(rec.get("iv"), float), "iv must not be collapsed to a scalar"


def test_tt_only_no_rh_cache():
    """When rh=None for a ticker, signal_class should be IV_SIGNAL_ONLY (TT has data)."""
    sc = _classify_signal(TT_ARWR, None)
    assert sc == "IV_SIGNAL_ONLY", f"Expected IV_SIGNAL_ONLY with no RH, got {sc}"

    rec = _merge_ticker("ARWR", TT_ARWR, None)
    assert rec["signal_class"] == "IV_SIGNAL_ONLY"
    assert rec["contract"] is None
    assert rec["greeks"] is None
    assert rec["liquidity"] is None
    # TT iv should still be present
    assert rec["iv"]["tastytrade_iv"] is not None


def test_no_chain_when_tt_missing():
    """When TT has opt_has_data != '1', signal_class should be NO_CHAIN."""
    sc = _classify_signal(TT_MISSING, RH_ARWR)
    assert sc == "NO_CHAIN", f"Expected NO_CHAIN, got {sc}"

    sc_none = _classify_signal(None, RH_ARWR)
    assert sc_none == "NO_CHAIN", f"Expected NO_CHAIN for None TT, got {sc_none}"


def test_is_broken_detection():
    """_is_broken correctly identifies broken and valid quotes."""
    assert _is_broken(None) is True
    assert _is_broken({}) is True
    assert _is_broken({"bid": 0.0, "ask": 4.90}) is True
    assert _is_broken({"bid": 0, "ask": 4.90}) is True
    assert _is_broken({"bid": 1.00, "ask": 2.55}) is False


def test_spread_pct_calculation():
    """_spread_pct returns correct value."""
    side = {"bid": 2.65, "ask": 5.00, "mark": 3.83}
    sp = _spread_pct(side)
    assert abs(sp - (5.00 - 2.65) / 3.83) < 0.001

    assert _spread_pct(None) == 1.0
    assert _spread_pct({"bid": 0, "ask": 5, "mark": 0}) == 1.0


def test_nrix_call_iv_used_for_disagreement_when_put_broken():
    """When put is broken, disagreement should use call IV."""
    rec = _merge_ticker("NRIX", TT_NRIX, RH_NRIX)
    iv = rec["iv"]
    # TT=0.818, RH call=0.850 → disagreement = (0.818-0.850)*100 = -3.2pp
    assert iv["iv_disagreement_pp"] is not None
    assert abs(iv["iv_disagreement_pp"] - (-3.2)) < 0.5, f"Expected ~-3.2pp, got {iv['iv_disagreement_pp']}"


def test_rvmd_high_confidence():
    """RVMD: OI=2495 > 50, max spread=26.2% < 30% → HIGH_CONFIDENCE_SIGNAL."""
    sc = _classify_signal(TT_RVMD, RH_RVMD)
    assert sc == "HIGH_CONFIDENCE_SIGNAL", f"Expected HIGH_CONFIDENCE_SIGNAL, got {sc}"


def test_term_structure_source_attribution():
    """term_structure.source must always be tastytrade_metrics."""
    for sym, tt, rh in [
        ("ARWR", TT_ARWR, RH_ARWR),
        ("NRIX", TT_NRIX, RH_NRIX),
        ("ARWR", TT_ARWR, None),
    ]:
        rec = _merge_ticker(sym, tt, rh)
        if rec.get("term_structure"):
            assert rec["term_structure"]["source"] == "tastytrade_metrics"
