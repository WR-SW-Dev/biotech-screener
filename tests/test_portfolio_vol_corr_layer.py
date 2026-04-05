"""Tests for portfolio_vol_corr_layer.py."""

import math
from pathlib import Path

from portfolio_vol_corr_layer import (
    VolCorrSnapshot,
    _ticker_vol,
    build_vol_corr_snapshot,
    compute_portfolio_vol,
    load_returns_from_csv,
)

# ── Helpers ──────────────────────────────────────────────────────────


def _write_price_csv(path: Path, rows):
    """Write a minimal price_history.csv.

    rows: list of (date, ticker, close) tuples.
    """
    with open(path, "w") as f:
        f.write("date,ticker,close,open,high,low,volume\n")
        for dt, tk, cl in rows:
            f.write(f"{dt},{tk},{cl},{cl},{cl},{cl},100000\n")


def _make_daily_returns(n=60, daily_ret=0.001, ticker="AAA"):
    """Generate synthetic price rows with constant daily return.

    Annualized vol ≈ daily_std * sqrt(252). For constant return, vol=0.
    """
    prices = [10.0]
    for _ in range(n):
        prices.append(prices[-1] * math.exp(daily_ret))

    rows = []
    base_year = 2026
    for i, p in enumerate(prices):
        day = i + 1
        month = (day - 1) // 28 + 1
        d = (day - 1) % 28 + 1
        if month > 12:
            month = 12
            d = 28
        rows.append((f"{base_year}-{month:02d}-{d:02d}", ticker, round(p, 4)))
    return rows


def _make_volatile_prices(n=60, ticker="BBB", daily_std=0.03):
    """Generate prices with alternating +/- moves for known vol."""
    import random

    rng = random.Random(42)
    prices = [10.0]
    for _ in range(n):
        ret = rng.gauss(0, daily_std)
        prices.append(prices[-1] * math.exp(ret))

    rows = []
    base_year = 2026
    for i, p in enumerate(prices):
        day = i + 1
        month = (day - 1) // 28 + 1
        d = (day - 1) % 28 + 1
        if month > 12:
            month = 12
            d = 28
        rows.append((f"{base_year}-{month:02d}-{d:02d}", ticker, round(p, 4)))
    return rows


# ── Tests: Return loading ────────────────────────────────────────────


class TestLoadReturns:
    def test_basic_loading(self, tmp_path):
        csv_path = tmp_path / "prices.csv"
        rows = [
            ("2026-01-02", "AAA", 10.0),
            ("2026-01-03", "AAA", 10.5),
            ("2026-01-04", "AAA", 10.2),
        ]
        _write_price_csv(csv_path, rows)
        rets, dates = load_returns_from_csv(csv_path, ["AAA"], lookback_days=60, as_of_date="2026-01-04")
        assert len(dates) == 2
        assert len(rets["AAA"]) == 2
        # First return: log(10.5/10.0) ≈ 0.0488
        assert abs(rets["AAA"][0] - math.log(10.5 / 10.0)) < 1e-6

    def test_missing_ticker_returns_none(self, tmp_path):
        csv_path = tmp_path / "prices.csv"
        rows = [
            ("2026-01-02", "AAA", 10.0),
            ("2026-01-03", "AAA", 10.5),
        ]
        _write_price_csv(csv_path, rows)
        rets, dates = load_returns_from_csv(csv_path, ["AAA", "BBB"], lookback_days=60, as_of_date="2026-01-03")
        assert rets["BBB"] == [None]

    def test_empty_csv(self, tmp_path):
        csv_path = tmp_path / "prices.csv"
        _write_price_csv(csv_path, [])
        rets, dates = load_returns_from_csv(csv_path, ["AAA"], lookback_days=60)
        assert rets["AAA"] == []


# ── Tests: Ticker vol ────────────────────────────────────────────────


class TestTickerVol:
    def test_constant_returns_zero_vol(self):
        rets = [0.01] * 60
        vol = _ticker_vol(rets)
        # Constant returns → var=0 → _ticker_vol returns None (degenerate)
        assert vol is None

    def test_insufficient_data_returns_none(self):
        rets = [0.01] * 5
        assert _ticker_vol(rets, min_obs=10) is None

    def test_known_vol(self):
        # daily_std=0.03 -> annualized ≈ 0.03 * sqrt(252) ≈ 0.476
        import random

        rng = random.Random(42)
        rets = [rng.gauss(0, 0.03) for _ in range(252)]
        vol = _ticker_vol(rets)
        assert vol is not None
        assert 0.30 < vol < 0.65  # Wide band for sample noise

    def test_none_values_filtered(self):
        rets = [0.01, None, 0.02, None, 0.01] * 12
        vol = _ticker_vol(rets, min_obs=10)
        # Should use only 36 non-None values
        assert vol is not None


# ── Tests: Portfolio vol ─────────────────────────────────────────────


class TestPortfolioVol:
    def test_single_name_vol_equals_portfolio_vol(self):
        """1-name portfolio vol = that name's vol."""
        import random

        rng = random.Random(42)
        rets_a = [rng.gauss(0, 0.03) for _ in range(60)]
        returns = {"AAA": rets_a}
        weights = {"AAA": 1.0}
        port_vol, n_imp = compute_portfolio_vol(returns, weights)
        name_vol = _ticker_vol(rets_a)
        assert abs(port_vol - name_vol) < 0.01

    def test_uncorrelated_reduces_vol(self):
        """N uncorrelated names -> vol < individual vol."""
        import random

        rng = random.Random(42)
        n_names = 10
        returns = {}
        weights = {}
        for i in range(n_names):
            tk = f"T{i:03d}"
            returns[tk] = [rng.gauss(0, 0.03) for _ in range(60)]
            weights[tk] = 1.0 / n_names

        port_vol, _ = compute_portfolio_vol(returns, weights)
        avg_name_vol = sum(_ticker_vol(r) for r in returns.values()) / n_names

        # Portfolio vol should be meaningfully below average name vol
        assert port_vol < avg_name_vol * 0.8

    def test_empty_portfolio(self):
        port_vol, n_imp = compute_portfolio_vol({}, {})
        assert port_vol == 0.0

    def test_imputed_tickers_counted(self):
        """Tickers with no data get imputed vol and correlation."""
        import random

        rng = random.Random(42)
        returns = {
            "AAA": [rng.gauss(0, 0.03) for _ in range(60)],
            "BBB": [],  # No data
        }
        weights = {"AAA": 0.5, "BBB": 0.5}
        port_vol, n_imp = compute_portfolio_vol(returns, weights)
        assert n_imp == 1
        assert port_vol > 0


# ── Tests: Build snapshot ────────────────────────────────────────────


class TestBuildSnapshot:
    def test_basic_snapshot(self, tmp_path):
        csv_path = tmp_path / "prices.csv"
        # Generate 61 days of prices for 2 tickers
        rows = _make_volatile_prices(60, "AAA", 0.03) + _make_volatile_prices(60, "BBB", 0.03)
        _write_price_csv(csv_path, rows)

        tickers = ["AAA", "BBB"]
        weights = {"AAA": 0.5, "BBB": 0.5}
        snap = build_vol_corr_snapshot(
            csv_path,
            tickers,
            weights,
            vol_target=0.50,
            as_of_date="2026-03-01",
        )
        assert isinstance(snap, VolCorrSnapshot)
        assert snap.portfolio_vol_annualized > 0
        assert snap.gross_exposure_scalar <= 1.0
        assert snap.n_tickers_with_data <= 2

    def test_vol_breach_detection(self, tmp_path):
        csv_path = tmp_path / "prices.csv"
        # Very volatile prices
        rows = _make_volatile_prices(60, "AAA", 0.08)
        _write_price_csv(csv_path, rows)

        snap = build_vol_corr_snapshot(
            csv_path,
            ["AAA"],
            {"AAA": 1.0},
            vol_target=0.30,
            as_of_date="2026-03-01",
        )
        # Single very volatile name should breach 30% target
        assert snap.vol_breach is True
        assert snap.gross_exposure_scalar < 1.0

    def test_no_breach_below_target(self, tmp_path):
        csv_path = tmp_path / "prices.csv"
        # Low-vol prices
        rows = _make_volatile_prices(60, "AAA", 0.01)
        _write_price_csv(csv_path, rows)

        snap = build_vol_corr_snapshot(
            csv_path,
            ["AAA"],
            {"AAA": 1.0},
            vol_target=0.80,
            as_of_date="2026-03-01",
        )
        assert snap.vol_breach is False
        assert snap.gross_exposure_scalar == 1.0

    def test_correlation_clusters_formed(self, tmp_path):
        csv_path = tmp_path / "prices.csv"
        # Two tickers with identical prices (corr=1.0) + one independent
        import random

        rng = random.Random(42)
        base_prices = [10.0]
        for _ in range(60):
            base_prices.append(base_prices[-1] * math.exp(rng.gauss(0, 0.03)))

        indep_prices = [10.0]
        for _ in range(60):
            indep_prices.append(indep_prices[-1] * math.exp(rng.gauss(0, 0.03)))

        rows = []
        for i, p in enumerate(base_prices):
            day = i + 1
            month = (day - 1) // 28 + 1
            d = (day - 1) % 28 + 1
            if month > 12:
                month, d = 12, 28
            dt = f"2026-{month:02d}-{d:02d}"
            rows.append((dt, "AAA", round(p, 4)))
            rows.append((dt, "BBB", round(p * 1.1, 4)))  # Same returns, different level
            rows.append((dt, "CCC", round(indep_prices[i], 4)))  # Independent

        _write_price_csv(csv_path, rows)

        tickers = ["AAA", "BBB", "CCC"]
        weights = {"AAA": 0.33, "BBB": 0.34, "CCC": 0.33}
        snap = build_vol_corr_snapshot(
            csv_path,
            tickers,
            weights,
            corr_threshold=0.70,
            as_of_date="2026-03-01",
        )
        # AAA and BBB should be in the same cluster
        assert snap.correlation_clusters.get("AAA") == snap.correlation_clusters.get("BBB")
        # CCC should be in a different cluster
        assert snap.correlation_clusters.get("CCC") != snap.correlation_clusters.get("AAA")

    def test_deterministic(self, tmp_path):
        csv_path = tmp_path / "prices.csv"
        rows = _make_volatile_prices(60, "AAA", 0.03) + _make_volatile_prices(60, "BBB", 0.03)
        _write_price_csv(csv_path, rows)

        tickers = ["AAA", "BBB"]
        weights = {"AAA": 0.5, "BBB": 0.5}
        results = []
        for _ in range(5):
            snap = build_vol_corr_snapshot(
                csv_path,
                tickers,
                weights,
                as_of_date="2026-03-01",
            )
            results.append(snap.portfolio_vol_annualized)
        assert len(set(results)) == 1, "Not deterministic"
