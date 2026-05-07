#!/usr/bin/env python3
"""Tests for biotech_hedge_report.py."""
from __future__ import annotations

import csv
import math
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

scipy = pytest.importorskip("scipy", reason="scipy not installed")

from tools.biotech_hedge_report import (
    _simulate_structure_pnl,
    bucket_expiries_by_dte,
    compute_beta_stats,
    compute_concentration_metrics,
    compute_hedge_contracts,
    compute_log_returns,
    compute_realized_vol,
    compute_regime_analysis,
    compute_structure_greeks,
    evaluate_structures,
    load_portfolio_weights,
    rank_best_dte_candidates,
    resolve_portfolio_csv,
    score_structures,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_price_series(
    start_price: float = 100.0,
    n_days: int = 80,
    daily_return: float = 0.001,
    noise: float = 0.0,
) -> dict:
    """Generate synthetic daily prices keyed by date string."""
    from datetime import date, timedelta

    prices = {}
    p = start_price
    base = date(2025, 1, 1)
    for i in range(n_days):
        dt = base + timedelta(days=i)
        # Skip weekends
        if dt.weekday() >= 5:
            continue
        prices[dt.isoformat()] = round(p, 4)
        p *= 1 + daily_return + noise * ((-1) ** i)
    return prices


def _make_correlated_prices(
    base_prices: dict,
    beta: float = 1.0,
    noise: float = 0.0,
) -> dict:
    """Generate prices correlated to base with given beta."""
    dates = sorted(base_prices.keys())
    prices = {}
    p = 100.0
    prices[dates[0]] = p
    for i in range(1, len(dates)):
        base_ret = math.log(base_prices[dates[i]] / base_prices[dates[i - 1]])
        port_ret = beta * base_ret + noise * ((-1) ** i)
        p *= math.exp(port_ret)
        prices[dates[i]] = round(p, 4)
    return prices


@pytest.fixture
def synthetic_prices():
    """XBI-like price series and correlated portfolio."""
    xbi = _make_price_series(100.0, 120, 0.0005, 0.005)
    ibb = _make_price_series(150.0, 120, 0.0003, 0.004)
    # Stock perfectly correlated with XBI at beta=1.0
    stock_a = _make_correlated_prices(xbi, beta=1.0, noise=0.0)
    # Stock uncorrelated
    stock_b = _make_price_series(50.0, 120, 0.002, 0.01)
    return {
        "XBI": xbi,
        "IBB": ibb,
        "STOCKA": stock_a,
        "STOCKB": stock_b,
    }


@pytest.fixture
def tmp_output(tmp_path):
    return tmp_path / "hedge_output"


@pytest.fixture
def tmp_rankings(tmp_path):
    """Create a minimal rankings.csv."""
    path = tmp_path / "rankings.csv"
    rows = []
    for i in range(80):
        rows.append(
            {
                "ticker": f"TK{i:03d}",
                "actionable_rank": str(i + 1),
                "eligible": "True",
                "catalyst_days": str(30 + i),
                "catalyst_family": "CLINICAL" if i % 3 == 0 else "REGULATORY" if i % 3 == 1 else "",
                "archetype": "Phase 2" if i % 2 == 0 else "Phase 3",
            }
        )
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return path


@pytest.fixture
def tmp_portfolio(tmp_path):
    """Create a minimal portfolio CSV."""
    path = tmp_path / "portfolio.csv"
    rows = [
        {"ticker": "STOCKA", "weight": "0.6"},
        {"ticker": "STOCKB", "weight": "0.4"},
    ]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["ticker", "weight"])
        writer.writeheader()
        writer.writerows(rows)
    return path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBetaRegression:
    """Test portfolio beta computation."""

    def test_beta_perfectly_correlated(self, synthetic_prices):
        """Portfolio perfectly correlated with XBI should have beta ~1.0."""
        weights = {"STOCKA": 1.0}
        as_of = sorted(synthetic_prices["XBI"].keys())[-1]
        result = compute_beta_stats(weights, synthetic_prices, "XBI", as_of)
        assert result["beta"] is not None
        assert abs(result["beta"] - 1.0) < 0.15, f"beta={result['beta']}, expected ~1.0"
        assert result["r_squared"] is not None
        assert result["r_squared"] > 0.85, f"R²={result['r_squared']}, expected high"

    def test_beta_near_zero_uncorrelated(self, synthetic_prices):
        """Uncorrelated portfolio should have low R-squared."""
        # Build a price series with returns opposite to XBI's pattern
        xbi = synthetic_prices["XBI"]
        xbi_dates = sorted(xbi.keys())
        opposite: dict = {xbi_dates[0]: 50.0}
        p = 50.0
        for i in range(1, len(xbi_dates)):
            # Reverse XBI return and add offset so it's uncorrelated
            xbi_ret = math.log(xbi[xbi_dates[i]] / xbi[xbi_dates[i - 1]])
            # Use hash-based pseudo-random sign to break correlation
            sign = 1 if hash(xbi_dates[i]) % 3 == 0 else -1
            p *= math.exp(sign * abs(xbi_ret) * 0.3 + 0.001)
            opposite[xbi_dates[i]] = round(p, 4)
        synthetic_prices["STOCKB_UNCORR"] = opposite

        weights = {"STOCKB_UNCORR": 1.0}
        as_of = xbi_dates[-1]
        result = compute_beta_stats(weights, synthetic_prices, "XBI", as_of)
        assert result["r_squared"] is not None
        assert result["r_squared"] < 0.5, f"R²={result['r_squared']}, expected low"


class TestHedgeRatioCalculation:
    """Test hedge contract computation."""

    def test_hedge_ratio_basic(self):
        """Given beta=1.2 and notional=$1M, contracts = 1.2M / (price * 100)."""
        contracts = compute_hedge_contracts(1_000_000, 1.2, 100.0)
        expected = round(1_000_000 * 1.2 / (100 * 100))
        assert contracts == expected

    def test_hedge_ratio_with_high_beta(self):
        contracts = compute_hedge_contracts(1_000_000, 1.5, 150.0)
        expected = round(1_000_000 * 1.5 / (150 * 100))
        assert contracts == expected

    def test_hedge_ratio_zero_price(self):
        assert compute_hedge_contracts(1_000_000, 1.0, 0.0) == 0


class TestStructureEvaluation:
    """Test hedge structure evaluation and scoring."""

    def test_put_spread_cheaper_than_put(self):
        """Put spread net premium must be less than straight put."""
        structures = evaluate_structures(
            "XBI",
            100.0,
            0.30,
            45,
            "2026-05-01",
            1.0,
            1_000_000,
            [],
        )
        straight_5otm = next(
            (s for s in structures if s["type"] == "straight_put" and "5% OTM" in s["structure"]),
            None,
        )
        spread_5_15 = next(
            (s for s in structures if s["type"] == "put_spread" and "5/15" in s["structure"]),
            None,
        )
        assert straight_5otm is not None
        assert spread_5_15 is not None
        assert spread_5_15["premium_per_contract"] < straight_5otm["premium_per_contract"]

    def test_collar_near_zero_cost(self):
        """Collar net premium should be near zero."""
        structures = evaluate_structures(
            "XBI",
            100.0,
            0.30,
            45,
            "2026-05-01",
            1.0,
            1_000_000,
            [],
        )
        collars = [s for s in structures if s["type"] == "collar"]
        assert len(collars) >= 1
        for c in collars:
            # Premium should be modest relative to ETF price
            assert abs(c["premium_per_contract"]) < 5.0, f"Collar premium {c['premium_per_contract']} too large"

    def test_minimum_structures_generated(self):
        """Should generate at least 4 structures per ETF."""
        structures = evaluate_structures(
            "XBI",
            100.0,
            0.30,
            45,
            "2026-05-01",
            1.0,
            1_000_000,
            [],
        )
        assert len(structures) >= 4, f"Only {len(structures)} structures"

    def test_put_ratio_only_when_safe(self):
        """Put ratio should only appear if danger zone >30% below."""
        structures = evaluate_structures(
            "XBI",
            100.0,
            0.30,
            45,
            "2026-05-01",
            1.0,
            1_000_000,
            [],
        )
        ratios = [s for s in structures if s["type"] == "put_ratio"]
        for r in ratios:
            assert r.get("danger_zone_pct", 0) < -30, "Ratio spread danger zone not deep enough"


class TestStructureScoring:
    """Test scoring framework."""

    def test_scoring_deterministic(self):
        """Same inputs produce same hedge_score."""
        structures = evaluate_structures(
            "XBI",
            100.0,
            0.30,
            45,
            "2026-05-01",
            1.0,
            1_000_000,
            [],
        )
        scored1 = score_structures(list(structures))
        scored2 = score_structures(list(structures))
        for s1, s2 in zip(scored1, scored2):
            assert s1["hedge_score"] == s2["hedge_score"]
            assert s1["rank"] == s2["rank"]

    def test_scoring_all_fields_present(self):
        structures = evaluate_structures(
            "IBB",
            150.0,
            0.25,
            60,
            "2026-05-15",
            0.9,
            500_000,
            [],
        )
        scored = score_structures(structures)
        for s in scored:
            assert "cost_score" in s
            assert "protection_score" in s
            assert "simplicity_score" in s
            assert "tail_score" in s
            assert "hedge_score" in s
            assert "rank" in s


class TestPortfolioWeightsLoading:
    """Spec 087 B1a — load_portfolio_weights fail-closed paths.

    The legacy rankings.csv equal-weight-top-60 fallback is removed; the
    function now requires a guaranteed-existing portfolio CSV from the
    caller (use ``resolve_portfolio_csv``) and SystemExits on unusable input.
    """

    def test_portfolio_csv_with_weight(self, tmp_portfolio):
        weights, source = load_portfolio_weights(tmp_portfolio)
        assert len(weights) == 2
        assert abs(weights["STOCKA"] - 0.6) < 0.01
        assert "portfolio file" in source

    def test_unknown_columns_fail_closed(self, tmp_path):
        """Portfolio CSV missing all of weight / market_value / target_weight_pct
        must SystemExit and name the expected columns."""
        bad = tmp_path / "no_weights.csv"
        with open(bad, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["ticker", "company_name"])
            writer.writeheader()
            writer.writerow({"ticker": "FOO", "company_name": "Foo Inc"})
        with pytest.raises(SystemExit) as exc_info:
            load_portfolio_weights(bad)
        msg = str(exc_info.value)
        assert "no usable weight column" in msg
        assert "weight" in msg
        assert "market_value" in msg
        assert "target_weight_pct" in msg

    def test_realized_vol_fallback(self, synthetic_prices):
        """When no chain data, surface uses realized vol. (Orthogonal to
        portfolio loading; kept here as a regression check.)"""
        from tools.biotech_hedge_report import analyze_options_surface

        rv = compute_realized_vol(synthetic_prices["XBI"], "2025-03-15", window=30)
        result = analyze_options_surface(
            "XBI",
            [],
            100.0,
            "2025-03-15",
            rv,
            synthetic_prices,
        )
        assert result["data_source"] == "realized_vol_proxy"
        assert result["atm_iv_near"] == rv


class TestPortfolioCsvResolution:
    """Spec 087 B1a — resolve_portfolio_csv fail-closed paths."""

    def test_explicit_existing_path_resolves(self, tmp_portfolio, tmp_path):
        """An explicit existing --portfolio-csv is returned as-is. The
        snapshots_root is irrelevant when the explicit arg points at a real file."""
        snapshots_root = tmp_path / "absent_snapshots_root"  # never touched
        result = resolve_portfolio_csv(tmp_portfolio, snapshots_root=snapshots_root)
        assert result == tmp_portfolio

    def test_explicit_missing_path_fails_closed(self, tmp_path):
        """An explicit --portfolio-csv that does not exist must SystemExit;
        the resolver does NOT silently auto-discover when an explicit arg was
        passed but is missing."""
        missing = tmp_path / "does_not_exist.csv"
        with pytest.raises(SystemExit) as exc_info:
            resolve_portfolio_csv(missing, snapshots_root=tmp_path / "snapshots")
        msg = str(exc_info.value)
        assert "does not exist" in msg
        assert str(missing) in msg

    def test_omitted_discovers_latest_snapshot(self, tmp_path):
        """No --portfolio-csv → auto-discover the latest snapshot's portfolio CSV."""
        snapshots = tmp_path / "snapshots"
        for date in ("2026-05-04", "2026-05-05", "2026-05-06"):
            d = snapshots / date
            d.mkdir(parents=True)
            (d / "portfolio_positions.csv").write_text("ticker,weight\nFOO,1.0\n", encoding="utf-8")
        result = resolve_portfolio_csv(None, snapshots_root=snapshots)
        assert result.parent.name == "2026-05-06"
        assert result.name == "portfolio_positions.csv"

    def test_omitted_no_snapshots_fails_closed(self, tmp_path):
        """No --portfolio-csv and an empty snapshots root must SystemExit."""
        snapshots = tmp_path / "snapshots"
        snapshots.mkdir()
        with pytest.raises(SystemExit) as exc_info:
            resolve_portfolio_csv(None, snapshots_root=snapshots)
        assert "no portfolio_positions.csv found" in str(exc_info.value)

    def test_omitted_no_snapshots_root_fails_closed(self, tmp_path):
        """No --portfolio-csv and a non-existent snapshots root must SystemExit."""
        snapshots = tmp_path / "does_not_exist_at_all"
        with pytest.raises(SystemExit) as exc_info:
            resolve_portfolio_csv(None, snapshots_root=snapshots)
        msg = str(exc_info.value)
        assert "snapshots root" in msg
        assert "does not exist" in msg

    def test_never_falls_back_to_rankings_stub(self, tmp_path):
        """Even when rankings.csv files are present alongside or at repo root,
        the resolver only ever considers portfolio_positions.csv."""
        snapshots = tmp_path / "snapshots"
        d = snapshots / "2026-05-06"
        d.mkdir(parents=True)
        # rankings.csv exists in the dated snapshot dir but no portfolio_positions.csv
        (d / "rankings.csv").write_text("ticker,actionable_rank,eligible\nSTUB,1,True\n", encoding="utf-8")
        # Repo-root-style rankings.csv stub adjacent
        (tmp_path / "rankings.csv").write_text("ticker,actionable_rank,eligible\nSTUB,1,True\n", encoding="utf-8")
        with pytest.raises(SystemExit) as exc_info:
            resolve_portfolio_csv(None, snapshots_root=snapshots)
        assert "no portfolio_positions.csv found" in str(exc_info.value)

    def test_explicit_same_date_missing_fails_closed_even_with_prior(self, tmp_path):
        """Cron regression: an explicit --portfolio-csv for today must fail
        closed when today's file is missing, even if a prior day's file
        exists. Friday cron must NOT silently fall through to Thursday."""
        snapshots = tmp_path / "snapshots"
        prior = snapshots / "2026-05-06"
        today = snapshots / "2026-05-07"
        prior.mkdir(parents=True)
        today.mkdir(parents=True)
        (prior / "portfolio_positions.csv").write_text("ticker,weight\nFOO,1.0\n", encoding="utf-8")
        # 2026-05-07/portfolio_positions.csv intentionally absent
        explicit = today / "portfolio_positions.csv"
        with pytest.raises(SystemExit) as exc_info:
            resolve_portfolio_csv(explicit, snapshots_root=snapshots)
        msg = str(exc_info.value)
        assert "does not exist" in msg
        assert "2026-05-07" in msg
        # Resolver must not have looked at the prior day at all
        assert "2026-05-06" not in msg


class TestRealizedVol:
    """Test realized volatility computation."""

    def test_realized_vol_positive(self, synthetic_prices):
        as_of = sorted(synthetic_prices["XBI"].keys())[-1]
        rv = compute_realized_vol(synthetic_prices["XBI"], as_of, window=30)
        assert rv is not None
        assert rv > 0

    def test_realized_vol_insufficient_data(self):
        """Should return None with too few data points."""
        rv = compute_realized_vol({"2025-01-01": 100, "2025-01-02": 101}, "2025-01-02", window=30)
        assert rv is None


class TestRegimeSplit:
    """Test regime analysis."""

    def test_regime_split_exhaustive(self):
        """Up + flat + down months = total months."""
        months = [
            {
                "start_date": "2025-01-01",
                "end_date": "2025-02-01",
                "portfolio_return": 0.05,
                "etf_return": 0.05,
                "hedge_pnl": -500,
            },
            {
                "start_date": "2025-02-01",
                "end_date": "2025-03-01",
                "portfolio_return": -0.04,
                "etf_return": -0.04,
                "hedge_pnl": 3000,
            },
            {
                "start_date": "2025-03-01",
                "end_date": "2025-04-01",
                "portfolio_return": 0.01,
                "etf_return": 0.01,
                "hedge_pnl": -200,
            },
            {
                "start_date": "2025-04-01",
                "end_date": "2025-05-01",
                "portfolio_return": -0.06,
                "etf_return": -0.06,
                "hedge_pnl": 5000,
            },
            {
                "start_date": "2025-05-01",
                "end_date": "2025-06-01",
                "portfolio_return": 0.08,
                "etf_return": 0.08,
                "hedge_pnl": -800,
            },
        ]
        regimes = compute_regime_analysis(months, {})
        total = sum(r["months"] for r in regimes)
        assert total == len(months), f"Regime split {total} != {len(months)}"

    def test_regime_all_up(self):
        months = [
            {
                "start_date": "2025-01-01",
                "end_date": "2025-02-01",
                "portfolio_return": 0.05,
                "etf_return": 0.05,
                "hedge_pnl": -500,
            },
        ]
        regimes = compute_regime_analysis(months, {})
        up = next(r for r in regimes if r["regime"] == "Up (>3%)")
        assert up["months"] == 1


class TestConcentration:
    """Test concentration metrics."""

    def test_herfindahl_equal_weight(self):
        weights = {f"TK{i}": 0.01 for i in range(100)}
        metrics = compute_concentration_metrics(weights, None)
        assert abs(metrics["herfindahl"] - 0.01) < 0.001

    def test_herfindahl_concentrated(self):
        weights = {"A": 0.90, "B": 0.10}
        metrics = compute_concentration_metrics(weights, None)
        assert metrics["herfindahl"] > 0.8


class TestLogReturns:
    """Test log return computation."""

    def test_basic_returns(self):
        prices = {"2025-01-01": 100, "2025-01-02": 110, "2025-01-03": 105}
        dates = ["2025-01-01", "2025-01-02", "2025-01-03"]
        rets = compute_log_returns(prices, dates)
        assert len(rets) == 2
        assert abs(rets[0] - math.log(110 / 100)) < 1e-10
        assert abs(rets[1] - math.log(105 / 110)) < 1e-10

    def test_missing_prices(self):
        prices = {"2025-01-01": 100, "2025-01-03": 105}
        dates = ["2025-01-01", "2025-01-02", "2025-01-03"]
        rets = compute_log_returns(prices, dates)
        assert rets[0] is None  # missing 01-02
        assert rets[1] is None  # missing 01-02


class TestOptionsSourceSelection:
    """Test options source selection logic."""

    def test_auto_no_credentials(self, monkeypatch):
        """Auto mode with no credentials returns realized_vol."""
        from tools.biotech_hedge_report import select_options_source

        monkeypatch.delenv("TT_SECRET", raising=False)
        monkeypatch.delenv("TT_REFRESH", raising=False)
        monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
        source, reason = select_options_source("auto")
        assert source == "realized_vol"
        assert "no options API" in reason

    def test_tasty_override_without_creds(self, monkeypatch):
        """Requesting tasty without credentials falls back."""
        from tools.biotech_hedge_report import select_options_source

        monkeypatch.delenv("TT_SECRET", raising=False)
        monkeypatch.delenv("TT_REFRESH", raising=False)
        monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
        source, reason = select_options_source("tasty")
        assert source == "realized_vol"
        assert "fell back" in reason

    def test_tasty_surface_uses_diagnostics(self, synthetic_prices):
        """When tasty_diag is provided, surface uses it."""
        from tools.biotech_hedge_report import analyze_options_surface

        diag = {
            "opt_has_data": "1",
            "opt_atm_iv": "0.35",
            "opt_front_iv": "0.33",
            "opt_back_iv": "0.37",
            "opt_term_slope": "0.12",
            "opt_put_call_skew": "0.05",
            "opt_rr_25d": "-0.03",
            "opt_nearest_expiry": "2025-04-17",
            "opt_dte": "33",
            "opt_iv_regime": "NORMAL",
            "opt_event_premium": "NO",
            "opt_liquidity_ok": "1",
        }
        result = analyze_options_surface(
            "XBI",
            [],
            100.0,
            "2025-03-15",
            0.30,
            synthetic_prices,
            tasty_diag=diag,
        )
        assert result["data_source"] == "tastytrade"
        assert result["atm_iv_near"] == 0.35
        assert result["skew_25d"] == 0.05
        assert result["rr_25d"] == -0.03
        assert result["pricing_field_used"] == "tasty_mark_iv"

    def test_tasty_no_data_falls_back_to_chain(self, synthetic_prices):
        """If tasty returns opt_has_data=0, falls back to chain/rv."""
        from tools.biotech_hedge_report import analyze_options_surface

        diag = {"opt_has_data": "0", "opt_diagnostic_basis": "no_credentials"}
        result = analyze_options_surface(
            "XBI",
            [],
            100.0,
            "2025-03-15",
            0.30,
            synthetic_prices,
            tasty_diag=diag,
        )
        assert result["data_source"] == "realized_vol_proxy"


class TestHistoricalBacktest:
    """Test historical contract matching."""

    def test_find_best_contract_exact_strike(self):
        from common.historical_hedge_backtest import find_best_contract

        records = [
            {"underlying_ticker": "XBI", "option_ticker": "O:XBI260417P00120000", "close": 3.50, "volume": 100},
            {"underlying_ticker": "XBI", "option_ticker": "O:XBI260417P00115000", "close": 2.10, "volume": 50},
            {"underlying_ticker": "XBI", "option_ticker": "O:XBI260417C00130000", "close": 4.00, "volume": 200},
        ]
        match = find_best_contract(records, "XBI", 120.0, "put", "2026-04-01", "2026-05-01")
        assert match is not None
        assert match["strike"] == 120.0
        assert match["close"] == 3.50

    def test_find_best_contract_nearest_strike(self):
        from common.historical_hedge_backtest import find_best_contract

        records = [
            {"underlying_ticker": "XBI", "option_ticker": "O:XBI260417P00118000", "close": 2.80, "volume": 100},
            {"underlying_ticker": "XBI", "option_ticker": "O:XBI260417P00122000", "close": 3.90, "volume": 50},
        ]
        match = find_best_contract(records, "XBI", 120.0, "put", "2026-04-01", "2026-05-01")
        assert match is not None
        assert match["strike"] == 118.0  # closer to 120 than 122

    def test_find_best_contract_no_match(self):
        from common.historical_hedge_backtest import find_best_contract

        records = [
            {"underlying_ticker": "IBB", "option_ticker": "O:IBB260417P00150000", "close": 2.00, "volume": 10},
        ]
        # Looking for XBI, not IBB
        match = find_best_contract(records, "XBI", 120.0, "put", "2026-04-01", "2026-05-01")
        assert match is None

    def test_price_structure_historical_straight_put(self):
        from common.historical_hedge_backtest import price_structure_historical

        entry = [
            {"underlying_ticker": "XBI", "option_ticker": "O:XBI260417P00114000", "close": 2.50, "volume": 100},
        ]
        exit_recs = [
            {"underlying_ticker": "XBI", "option_ticker": "O:XBI260417P00114000", "close": 8.00, "volume": 80},
        ]
        result = price_structure_historical(
            "straight_put",
            {"put": -0.05},
            120.0,
            "XBI",
            entry,
            exit_recs,
            "2026-04-01",
            "2026-05-01",
            10,
        )
        assert result["pricing_source"] == "historical"
        # PnL = (8.00 - 2.50) * 10 * 100 = 5500
        assert result["pnl"] == 5500

    def test_price_structure_missing_data(self):
        from common.historical_hedge_backtest import price_structure_historical

        result = price_structure_historical(
            "straight_put",
            {"put": -0.05},
            120.0,
            "XBI",
            [],
            [],
            "2026-04-01",
            "2026-05-01",
            10,
        )
        assert result["pricing_source"] == "missing"


class TestSimulatePnl:
    """Test structure PnL simulation."""

    def test_put_pnl_in_the_money(self):
        """Put should have positive PnL when ETF drops."""
        pnl = _simulate_structure_pnl(
            "straight_put",
            {"put": -0.05},
            etf_start=100.0,
            etf_end=85.0,  # 15% drop
            T=45 / 365,
            sigma=0.30,
            hedge_notional=1_000_000,
            contracts=10,
        )
        assert pnl > 0, f"Put PnL should be positive on 15% drop, got {pnl}"

    def test_put_pnl_out_of_money(self):
        """Put should lose premium when ETF rises."""
        pnl = _simulate_structure_pnl(
            "straight_put",
            {"put": -0.05},
            etf_start=100.0,
            etf_end=110.0,  # 10% rise
            T=45 / 365,
            sigma=0.30,
            hedge_notional=1_000_000,
            contracts=10,
        )
        assert pnl < 0, f"Put PnL should be negative on 10% rise, got {pnl}"


# ---------------------------------------------------------------------------
# Spec 029: DTE bucketing + Greeks
# ---------------------------------------------------------------------------


class TestDTEBucketing:
    """Test DTE bucket assignment and ranking."""

    def test_bucket_assignment_short(self):
        """Expiry with DTE 30 goes to short bucket."""
        chain = [{"expiration_date": "2026-04-17"}]  # 30d from 2026-03-18
        buckets = bucket_expiries_by_dte(chain, "2026-03-18")
        assert len(buckets["short"]) == 1
        assert buckets["short"][0]["dte"] == 30

    def test_bucket_assignment_medium(self):
        """Expiry with DTE 75 goes to medium bucket."""
        chain = [{"expiration_date": "2026-06-01"}]  # 75d from 2026-03-18
        buckets = bucket_expiries_by_dte(chain, "2026-03-18")
        assert len(buckets["medium"]) == 1

    def test_bucket_assignment_out_of_range(self):
        """Expiry with DTE 150 goes to no bucket."""
        chain = [{"expiration_date": "2026-08-15"}]  # 150d from 2026-03-18
        buckets = bucket_expiries_by_dte(chain, "2026-03-18")
        assert all(len(v) == 0 for v in buckets.values())

    def test_bucket_winner_selection_deterministic(self):
        """Same inputs produce same bucket winners."""
        structs = evaluate_structures("XBI", 100.0, 0.30, 45, "2026-05-01", 1.0, 1_000_000, [])
        for s in structs:
            s["dte_bucket"] = "medium_short"
        scored = score_structures(structs)
        r1 = rank_best_dte_candidates(scored)
        r2 = rank_best_dte_candidates(scored)
        assert r1["best_overall"].get("hedge_score") == r2["best_overall"].get("hedge_score")


class TestStructureGreeks:
    """Test Greek computation at leg, structure, and position level."""

    def test_straight_put_greeks_present(self):
        """Straight put should have all Greek fields."""
        struct = {
            "type": "straight_put",
            "strike_1": 95.0,
            "dte": 45,
            "contracts": 10,
        }
        g = compute_structure_greeks(struct, 100.0, 0.30)
        assert "per_leg_greeks" in g
        assert len(g["per_leg_greeks"]) == 1
        leg = g["per_leg_greeks"][0]
        assert leg["delta"] is not None
        assert leg["delta"] < 0  # put delta is negative
        assert g["per_contract_net_greeks"]["delta"] < 0

    def test_put_spread_net_greeks(self):
        """Put spread net Greeks = signed sum of legs."""
        struct = {
            "type": "put_spread",
            "strike_1": 95.0,
            "strike_2": 85.0,
            "dte": 45,
            "contracts": 10,
        }
        g = compute_structure_greeks(struct, 100.0, 0.30)
        legs = g["per_leg_greeks"]
        assert len(legs) == 2
        # Net delta = buy_put_delta * 1 + sell_put_delta * (-1)
        expected_delta = legs[0]["delta"] * 1 + legs[1]["delta"] * (-1)
        assert abs(g["per_contract_net_greeks"]["delta"] - expected_delta) < 1e-5

    def test_collar_net_greeks(self):
        """Collar net Greeks reflect short-call subtraction."""
        struct = {
            "type": "collar",
            "strike_1": 95.0,
            "strike_2": 105.0,
            "dte": 45,
            "contracts": 10,
        }
        g = compute_structure_greeks(struct, 100.0, 0.30)
        legs = g["per_leg_greeks"]
        assert legs[0]["option_type"] == "put"
        assert legs[1]["option_type"] == "call"
        assert legs[1]["quantity_sign"] == -1

    def test_ratio_spread_quantity_scaling(self):
        """1x2 ratio spread has quantity_sign=-2 on the short leg."""
        struct = {
            "type": "put_ratio",
            "strike_1": 90.0,
            "strike_2": 75.0,
            "dte": 45,
            "contracts": 10,
        }
        g = compute_structure_greeks(struct, 100.0, 0.30)
        legs = g["per_leg_greeks"]
        assert legs[1]["quantity_sign"] == -2

    def test_position_greeks_scale_by_contracts(self):
        """Hedge-position Greeks = net * contracts * 100."""
        struct = {
            "type": "straight_put",
            "strike_1": 95.0,
            "dte": 45,
            "contracts": 10,
        }
        g = compute_structure_greeks(struct, 100.0, 0.30)
        net_delta = g["per_contract_net_greeks"]["delta"]
        pos_delta = g["hedge_position_greeks"]["position_delta"]
        assert abs(pos_delta - net_delta * 10 * 100) < 0.01

    def test_theta_dollar_scaling(self):
        """Theta/day in dollars = net theta * contracts * 100."""
        struct = {
            "type": "straight_put",
            "strike_1": 95.0,
            "dte": 45,
            "contracts": 10,
        }
        g = compute_structure_greeks(struct, 100.0, 0.30)
        net_theta = g["per_contract_net_greeks"]["theta"]
        theta_dollars = g["hedge_position_greeks"]["theta_per_day_dollars"]
        assert abs(theta_dollars - net_theta * 10 * 100) < 0.01

    def test_vega_dollar_scaling(self):
        """Vega P&L per +1 vol point = net vega * contracts * 100."""
        struct = {
            "type": "straight_put",
            "strike_1": 95.0,
            "dte": 45,
            "contracts": 10,
        }
        g = compute_structure_greeks(struct, 100.0, 0.30)
        net_vega = g["per_contract_net_greeks"]["vega"]
        vega_dollars = g["hedge_position_greeks"]["vega_pnl_per_1vol_point_dollars"]
        assert abs(vega_dollars - net_vega * 10 * 100) < 0.01
