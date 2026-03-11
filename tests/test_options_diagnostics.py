"""Tests for options-implied vol/skew diagnostics.

Uses mocks/fixtures for tastytrade responses — does not hit live APIs.
"""

from datetime import date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from common.options_diagnostics import (
    OPTIONS_DIAGNOSTIC_COLUMNS,
    _has_credentials,
    classify_event_premium,
    classify_iv_regime,
    classify_liquidity_ok,
    classify_use_for_judgment,
    compute_operator_flags,
    compute_put_call_skew,
    compute_term_slope,
    empty_diagnostics,
    fetch_options_diagnostics,
    select_atm_strike,
    select_catalyst_tickers,
    select_front_back_expiries,
)

# ---------------------------------------------------------------------------
# 1. Pure helpers
# ---------------------------------------------------------------------------


class TestEmptyDiagnostics:
    def test_default_reason(self):
        d = empty_diagnostics()
        assert d["opt_has_data"] == "0"
        assert d["opt_diagnostic_basis"] == ""
        assert set(d.keys()) == set(OPTIONS_DIAGNOSTIC_COLUMNS)

    def test_with_reason(self):
        d = empty_diagnostics("no_credentials")
        assert d["opt_diagnostic_basis"] == "no_credentials"
        assert d["opt_has_data"] == "0"

    def test_output_schema_stable(self):
        d = empty_diagnostics()
        assert list(d.keys()) == OPTIONS_DIAGNOSTIC_COLUMNS


class TestSelectFrontBackExpiries:
    def test_two_expiries(self):
        ivs = [
            {"expiration_date": date(2026, 4, 17), "implied_volatility": 0.85},
            {"expiration_date": date(2026, 5, 15), "implied_volatility": 0.72},
        ]
        front, back = select_front_back_expiries(ivs, date(2026, 3, 11))
        assert front["expiration_date"] == date(2026, 4, 17)
        assert back["expiration_date"] == date(2026, 5, 15)
        assert front["dte"] == 37
        assert back["dte"] == 65

    def test_skips_near_term_weeklies(self):
        ivs = [
            {"expiration_date": date(2026, 3, 14), "implied_volatility": 0.90},  # 3 DTE
            {"expiration_date": date(2026, 4, 17), "implied_volatility": 0.80},
        ]
        front, back = select_front_back_expiries(ivs, date(2026, 3, 11))
        assert front["expiration_date"] == date(2026, 4, 17)
        assert back is None

    def test_no_iv_data(self):
        ivs = [
            {"expiration_date": date(2026, 4, 17), "implied_volatility": None},
        ]
        front, back = select_front_back_expiries(ivs, date(2026, 3, 11))
        assert front is None
        assert back is None

    def test_empty_list(self):
        front, back = select_front_back_expiries([], date(2026, 3, 11))
        assert front is None
        assert back is None

    def test_string_dates_parsed(self):
        ivs = [
            {"expiration_date": "2026-04-17", "implied_volatility": 0.80},
        ]
        front, back = select_front_back_expiries(ivs, date(2026, 3, 11))
        assert front["expiration_date"] == date(2026, 4, 17)

    def test_deterministic_ordering(self):
        """Front is always the nearest future expiry."""
        ivs = [
            {"expiration_date": date(2026, 6, 19), "implied_volatility": 0.70},
            {"expiration_date": date(2026, 4, 17), "implied_volatility": 0.85},
            {"expiration_date": date(2026, 5, 15), "implied_volatility": 0.78},
        ]
        front, back = select_front_back_expiries(ivs, date(2026, 3, 11))
        assert front["expiration_date"] == date(2026, 4, 17)
        assert back["expiration_date"] == date(2026, 5, 15)


class TestComputeTermSlope:
    def test_contango(self):
        # back > front = positive (normal)
        slope = compute_term_slope(0.80, 0.90)
        assert slope == 0.125

    def test_backwardation(self):
        # front > back = negative (event premium)
        slope = compute_term_slope(0.90, 0.80)
        assert slope is not None
        assert slope < 0

    def test_zero_front(self):
        assert compute_term_slope(0.0, 0.50) is None

    def test_none_front(self):
        assert compute_term_slope(None, 0.50) is None


class TestSelectAtmStrike:
    def test_exact_match(self):
        strikes = [
            {"strike_price": 50.0, "call": "C50", "put": "P50"},
            {"strike_price": 55.0, "call": "C55", "put": "P55"},
            {"strike_price": 60.0, "call": "C60", "put": "P60"},
        ]
        atm = select_atm_strike(strikes, 55.0)
        assert atm["strike_price"] == 55.0

    def test_between_strikes(self):
        strikes = [
            {"strike_price": 50.0, "call": "C50", "put": "P50"},
            {"strike_price": 55.0, "call": "C55", "put": "P55"},
        ]
        atm = select_atm_strike(strikes, 52.0)
        assert atm["strike_price"] == 50.0  # nearest

    def test_empty_strikes(self):
        assert select_atm_strike([], 50.0) is None

    def test_zero_spot(self):
        strikes = [{"strike_price": 50.0, "call": "C", "put": "P"}]
        assert select_atm_strike(strikes, 0.0) is None


class TestComputePutCallSkew:
    def test_puts_more_expensive(self):
        skew = compute_put_call_skew(0.90, 0.80)
        assert skew is not None
        assert skew > 0  # put premium

    def test_symmetric(self):
        skew = compute_put_call_skew(0.80, 0.80)
        assert skew == 0.0

    def test_calls_more_expensive(self):
        skew = compute_put_call_skew(0.70, 0.80)
        assert skew is not None
        assert skew < 0

    def test_missing_iv(self):
        assert compute_put_call_skew(None, 0.80) is None
        assert compute_put_call_skew(0.80, None) is None


# ---------------------------------------------------------------------------
# 2. Credentials check
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 1b. Operator flags
# ---------------------------------------------------------------------------


class TestClassifyIvRegime:
    def test_normal(self):
        assert classify_iv_regime(0.35) == "NORMAL"
        assert classify_iv_regime(0.59) == "NORMAL"

    def test_elevated(self):
        assert classify_iv_regime(0.60) == "ELEVATED"
        assert classify_iv_regime(1.20) == "ELEVATED"

    def test_extreme(self):
        assert classify_iv_regime(2.00) == "EXTREME"
        assert classify_iv_regime(15.0) == "EXTREME"

    def test_none(self):
        assert classify_iv_regime(None) == ""


class TestClassifyEventPremium:
    def test_backwardation(self):
        assert classify_event_premium(-0.15) == "YES"
        assert classify_event_premium(-0.50) == "YES"

    def test_flat_or_contango(self):
        assert classify_event_premium(-0.05) == "NO"
        assert classify_event_premium(0.0) == "NO"
        assert classify_event_premium(0.10) == "NO"

    def test_boundary(self):
        assert classify_event_premium(-0.10) == "NO"  # not strictly below
        assert classify_event_premium(-0.1001) == "YES"

    def test_none(self):
        assert classify_event_premium(None) == ""


class TestClassifyLiquidityOk:
    def test_good_liquidity(self):
        assert classify_liquidity_ok(3) == "1"
        assert classify_liquidity_ok(4) == "1"
        assert classify_liquidity_ok(5) == "1"

    def test_poor_liquidity(self):
        assert classify_liquidity_ok(1) == "0"
        assert classify_liquidity_ok(2) == "0"

    def test_none(self):
        assert classify_liquidity_ok(None) == "0"


class TestClassifyUseForJudgment:
    def test_good_data(self):
        assert classify_use_for_judgment(True, True, 0.50) == "YES"

    def test_no_data(self):
        assert classify_use_for_judgment(False, True, 0.50) == "NO"

    def test_illiquid(self):
        assert classify_use_for_judgment(True, False, 0.50) == "NO"

    def test_junk_iv(self):
        assert classify_use_for_judgment(True, True, 5.00) == "NO"
        assert classify_use_for_judgment(True, True, 15.0) == "NO"

    def test_high_but_not_junk(self):
        assert classify_use_for_judgment(True, True, 1.80) == "YES"

    def test_none_iv_ok(self):
        assert classify_use_for_judgment(True, True, None) == "YES"


class TestComputeOperatorFlags:
    def test_healthy_ticker(self):
        diag = {"opt_has_data": "1", "opt_atm_iv": 0.45, "opt_term_slope": -0.15}
        flags = compute_operator_flags(diag, liquidity_rating=4)
        assert flags["opt_iv_regime"] == "NORMAL"
        assert flags["opt_event_premium"] == "YES"
        assert flags["opt_liquidity_ok"] == "1"
        assert flags["opt_use_for_judgment"] == "YES"

    def test_extreme_illiquid(self):
        diag = {"opt_has_data": "1", "opt_atm_iv": 8.0, "opt_term_slope": -0.90}
        flags = compute_operator_flags(diag, liquidity_rating=1)
        assert flags["opt_iv_regime"] == "EXTREME"
        assert flags["opt_event_premium"] == "YES"
        assert flags["opt_liquidity_ok"] == "0"
        assert flags["opt_use_for_judgment"] == "NO"

    def test_no_data(self):
        diag = {"opt_has_data": "0", "opt_atm_iv": "", "opt_term_slope": ""}
        flags = compute_operator_flags(diag, liquidity_rating=None)
        assert flags["opt_iv_regime"] == ""
        assert flags["opt_event_premium"] == ""
        assert flags["opt_liquidity_ok"] == "0"
        assert flags["opt_use_for_judgment"] == "NO"

    def test_elevated_contango_liquid(self):
        diag = {"opt_has_data": "1", "opt_atm_iv": 0.80, "opt_term_slope": 0.05}
        flags = compute_operator_flags(diag, liquidity_rating=3)
        assert flags["opt_iv_regime"] == "ELEVATED"
        assert flags["opt_event_premium"] == "NO"
        assert flags["opt_use_for_judgment"] == "YES"


# ---------------------------------------------------------------------------
# 2. Credentials check
# ---------------------------------------------------------------------------


class TestHasCredentials:
    def test_missing_credentials(self, monkeypatch):
        monkeypatch.delenv("TT_SECRET", raising=False)
        monkeypatch.delenv("TT_REFRESH", raising=False)
        assert _has_credentials() is False

    def test_partial_credentials(self, monkeypatch):
        monkeypatch.setenv("TT_SECRET", "xxx")
        monkeypatch.delenv("TT_REFRESH", raising=False)
        assert _has_credentials() is False

    def test_full_credentials(self, monkeypatch):
        monkeypatch.setenv("TT_SECRET", "xxx")
        monkeypatch.setenv("TT_REFRESH", "yyy")
        assert _has_credentials() is True


# ---------------------------------------------------------------------------
# 3. Graceful degradation
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    def test_no_credentials_returns_empty(self, monkeypatch):
        monkeypatch.delenv("TT_SECRET", raising=False)
        monkeypatch.delenv("TT_REFRESH", raising=False)
        result = fetch_options_diagnostics(["ACME"], "2026-03-11")
        assert result["ACME"]["opt_has_data"] == "0"
        assert result["ACME"]["opt_diagnostic_basis"] == "no_credentials"

    def test_empty_symbols(self):
        result = fetch_options_diagnostics([], "2026-03-11")
        assert result == {}


# ---------------------------------------------------------------------------
# 4. Mock-based fetch tests
# ---------------------------------------------------------------------------


def _mock_market_metric(
    symbol: str,
    iv_index: float = 0.85,
    expiry_ivs=None,
    liquidity_rating: int = 3,
):
    """Build a mock MarketMetricInfo object."""
    m = MagicMock()
    m.symbol = symbol
    m.implied_volatility_index = Decimal(str(iv_index))
    m.liquidity_rating = liquidity_rating
    m.implied_volatility_updated_at = datetime(2026, 3, 11, 15, 30, 0)
    m.updated_at = datetime(2026, 3, 11, 15, 30, 0)

    if expiry_ivs is None:
        expiry_ivs = [
            {"expiration_date": date(2026, 4, 17), "iv": 0.82},
            {"expiration_date": date(2026, 5, 15), "iv": 0.78},
        ]

    oivs = []
    for eiv in expiry_ivs:
        oiv = MagicMock()
        oiv.expiration_date = eiv["expiration_date"]
        oiv.implied_volatility = Decimal(str(eiv["iv"])) if eiv["iv"] is not None else None
        oivs.append(oiv)

    m.option_expiration_implied_volatilities = oivs
    return m


class TestFetchWithMock:
    @patch("common.options_diagnostics._has_credentials", return_value=True)
    @patch("common.options_diagnostics._create_session")
    @patch("common.options_diagnostics._fetch_metrics_batch")
    def test_basic_fetch(self, mock_batch, mock_session, mock_creds):
        mock_sess = AsyncMock()
        mock_sess.__aenter__ = AsyncMock(return_value=mock_sess)
        mock_sess.__aexit__ = AsyncMock(return_value=None)
        mock_session.return_value = mock_sess

        mock_batch.return_value = {
            "ACME": _mock_market_metric("ACME", iv_index=0.85),
        }

        result = fetch_options_diagnostics(["ACME"], "2026-03-11")
        assert result["ACME"]["opt_has_data"] == "1"
        assert result["ACME"]["opt_atm_iv"] == 0.85
        assert result["ACME"]["opt_front_iv"] == 0.82
        assert result["ACME"]["opt_back_iv"] == 0.78
        assert result["ACME"]["opt_nearest_expiry"] == "2026-04-17"
        assert result["ACME"]["opt_dte"] == 37
        assert result["ACME"]["opt_diagnostic_basis"] == "tt_market_metrics"
        # Operator flags present
        assert result["ACME"]["opt_iv_regime"] == "ELEVATED"  # 0.85 > 0.60
        assert result["ACME"]["opt_liquidity_ok"] == "1"  # liq=3
        assert result["ACME"]["opt_use_for_judgment"] == "YES"

    @patch("common.options_diagnostics._has_credentials", return_value=True)
    @patch("common.options_diagnostics._create_session")
    @patch("common.options_diagnostics._fetch_metrics_batch")
    def test_no_metrics_for_symbol(self, mock_batch, mock_session, mock_creds):
        mock_sess = AsyncMock()
        mock_sess.__aenter__ = AsyncMock(return_value=mock_sess)
        mock_sess.__aexit__ = AsyncMock(return_value=None)
        mock_session.return_value = mock_sess
        mock_batch.return_value = {}

        result = fetch_options_diagnostics(["ACME"], "2026-03-11")
        assert result["ACME"]["opt_has_data"] == "0"
        assert result["ACME"]["opt_diagnostic_basis"] == "no_metrics"

    @patch("common.options_diagnostics._has_credentials", return_value=True)
    @patch("common.options_diagnostics._create_session")
    @patch("common.options_diagnostics._fetch_metrics_batch")
    def test_sparse_chain_null_iv(self, mock_batch, mock_session, mock_creds):
        mock_sess = AsyncMock()
        mock_sess.__aenter__ = AsyncMock(return_value=mock_sess)
        mock_sess.__aexit__ = AsyncMock(return_value=None)
        mock_session.return_value = mock_sess

        mock_batch.return_value = {
            "ACME": _mock_market_metric(
                "ACME",
                expiry_ivs=[{"expiration_date": date(2026, 4, 17), "iv": None}],
            ),
        }

        result = fetch_options_diagnostics(["ACME"], "2026-03-11")
        assert result["ACME"]["opt_has_data"] == "0"
        assert "no_liquid_expiry" in result["ACME"]["opt_diagnostic_basis"]

    @patch("common.options_diagnostics._has_credentials", return_value=True)
    @patch("common.options_diagnostics._create_session")
    @patch("common.options_diagnostics._fetch_metrics_batch")
    def test_term_slope_computed(self, mock_batch, mock_session, mock_creds):
        mock_sess = AsyncMock()
        mock_sess.__aenter__ = AsyncMock(return_value=mock_sess)
        mock_sess.__aexit__ = AsyncMock(return_value=None)
        mock_session.return_value = mock_sess

        mock_batch.return_value = {
            "ACME": _mock_market_metric(
                "ACME",
                expiry_ivs=[
                    {"expiration_date": date(2026, 4, 17), "iv": 0.80},
                    {"expiration_date": date(2026, 5, 15), "iv": 0.90},
                ],
            ),
        }

        result = fetch_options_diagnostics(["ACME"], "2026-03-11")
        assert result["ACME"]["opt_term_slope"] == 0.125  # (0.90-0.80)/0.80

    @patch("common.options_diagnostics._has_credentials", return_value=True)
    @patch("common.options_diagnostics._create_session")
    @patch("common.options_diagnostics._fetch_metrics_batch")
    def test_single_expiry_no_back(self, mock_batch, mock_session, mock_creds):
        mock_sess = AsyncMock()
        mock_sess.__aenter__ = AsyncMock(return_value=mock_sess)
        mock_sess.__aexit__ = AsyncMock(return_value=None)
        mock_session.return_value = mock_sess

        mock_batch.return_value = {
            "ACME": _mock_market_metric(
                "ACME",
                expiry_ivs=[{"expiration_date": date(2026, 4, 17), "iv": 0.80}],
            ),
        }

        result = fetch_options_diagnostics(["ACME"], "2026-03-11")
        assert result["ACME"]["opt_has_data"] == "1"
        assert result["ACME"]["opt_back_iv"] == ""
        assert result["ACME"]["opt_term_slope"] == ""

    @patch("common.options_diagnostics._has_credentials", return_value=True)
    @patch("common.options_diagnostics._create_session", return_value=None)
    def test_session_failure(self, mock_session, mock_creds):
        result = fetch_options_diagnostics(["ACME"], "2026-03-11")
        assert result["ACME"]["opt_has_data"] == "0"
        assert result["ACME"]["opt_diagnostic_basis"] == "no_session"


# ---------------------------------------------------------------------------
# 5. Catalyst ticker selection
# ---------------------------------------------------------------------------


class TestSelectCatalystTickers:
    def test_actionable_names_first(self):
        rows = [
            {"ticker": "A", "actionable_rank": "1", "catalyst_days": "90"},
            {"ticker": "B", "actionable_rank": "", "catalyst_days": "30"},
            {"ticker": "C", "actionable_rank": "2", "catalyst_days": "60"},
        ]
        result = select_catalyst_tickers(rows, max_tickers=10)
        assert "A" in result
        assert "B" in result
        assert "C" in result

    def test_skips_no_catalyst(self):
        rows = [
            {"ticker": "A", "actionable_rank": "", "catalyst_days": "300"},
        ]
        result = select_catalyst_tickers(rows, max_tickers=10)
        assert result == []

    def test_respects_max_tickers(self):
        rows = [{"ticker": f"T{i}", "actionable_rank": str(i), "catalyst_days": "90"} for i in range(20)]
        result = select_catalyst_tickers(rows, max_tickers=5)
        assert len(result) == 5

    def test_empty_rankings(self):
        assert select_catalyst_tickers([]) == []

    def test_uppercase_output(self):
        rows = [{"ticker": "abc", "actionable_rank": "1", "catalyst_days": "30"}]
        result = select_catalyst_tickers(rows)
        assert result == ["ABC"]


# ---------------------------------------------------------------------------
# 6. No effect on rankings / execution
# ---------------------------------------------------------------------------


class TestNoRankingEffect:
    def test_columns_are_all_opt_prefixed(self):
        """All diagnostic columns start with opt_ to prevent name collisions."""
        for col in OPTIONS_DIAGNOSTIC_COLUMNS:
            assert col.startswith("opt_"), f"{col} missing opt_ prefix"

    def test_empty_diagnostics_are_neutral(self):
        """Empty diagnostics should not affect any numeric computation."""
        d = empty_diagnostics("test")
        for col in OPTIONS_DIAGNOSTIC_COLUMNS:
            if col == "opt_has_data":
                assert d[col] == "0"
            elif col == "opt_diagnostic_basis":
                assert d[col] == "test"
            elif col == "opt_liquidity_ok":
                assert d[col] == "0"  # explicit zero, not empty
            else:
                assert d[col] == "", f"{col} should be empty string, got {d[col]}"

    def test_operator_flag_columns_present(self):
        """Operator flags are included in the column schema."""
        flag_cols = ["opt_iv_regime", "opt_event_premium", "opt_liquidity_ok", "opt_use_for_judgment"]
        for col in flag_cols:
            assert col in OPTIONS_DIAGNOSTIC_COLUMNS, f"{col} missing from schema"
