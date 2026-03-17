"""Tests for Spec 025: Long Call Candidate Selector."""

import csv
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.research.build_long_call_candidates import (
    apply_candidate_filters,
    build_candidates,
    run_from_screen,
    select_contracts,
    write_csv,
    write_json,
    write_markdown,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_RANKING = {
    "ticker": "AAAA",
    "tier_any": "A",
    "actionable_rank": "5",
    "composite_score": "0.08",
    "is_hard_catalyst": "0",
    "catalyst_days": "60",
    "catalyst_family": "CLINICAL",
    "catalyst_event_type": "CT_PRIMARY_COMPLETION",
    "opt_rr_25d": "0.25",
    "opt_atm_iv": "0.8",
    "rr_trend_flag": "",
    "surface_move_extreme": "low",
    "actual_implied_move_pctile": "0.4",
    "iv_crush_breakeven_pct": "",
    "crush_adjusted_implied_move": "0.05",
    "archetype": "drug_developer",
    "opt_has_data": "1",
}

SAMPLE_CHAIN = [
    {
        "ticker": "O:AAAA260717C00010000",
        "contract_type": "call",
        "strike_price": 10.0,
        "expiration_date": "2026-07-17",
        "implied_volatility": 0.85,
        "open_interest": 200,
        "break_even_price": 12.5,
        "delta": 0.45,
        "gamma": 0.03,
        "theta": -0.02,
        "vega": 0.05,
        "day_open": 2.5,
        "day_high": 2.6,
        "day_low": 2.4,
        "day_close": 2.5,
        "day_volume": 50,
    },
    {
        "ticker": "O:AAAA260717C00015000",
        "contract_type": "call",
        "strike_price": 15.0,
        "expiration_date": "2026-07-17",
        "implied_volatility": 0.95,
        "open_interest": 150,
        "break_even_price": 16.0,
        "delta": 0.30,
        "gamma": 0.02,
        "theta": -0.01,
        "vega": 0.04,
        "day_open": 1.0,
        "day_high": 1.1,
        "day_low": 0.9,
        "day_close": 1.0,
        "day_volume": 30,
    },
    {
        "ticker": "O:AAAA260320C00005000",
        "contract_type": "call",
        "strike_price": 5.0,
        "expiration_date": "2026-03-20",
        "implied_volatility": 1.2,
        "open_interest": 500,
        "break_even_price": 7.0,
        "delta": 0.80,
        "gamma": 0.05,
        "theta": -0.05,
        "vega": 0.01,
        "day_open": 2.0,
        "day_high": 2.0,
        "day_low": 2.0,
        "day_close": 2.0,
        "day_volume": 100,
    },
]


def _make_ranking(**overrides):
    r = dict(SAMPLE_RANKING)
    r.update(overrides)
    return r


@pytest.fixture
def snapshot_dir(tmp_path):
    """Create a minimal snapshot dir with rankings and chain data."""
    sd = tmp_path / "2026-03-16"
    sd.mkdir()
    chains_dir = sd / "chains"
    chains_dir.mkdir()

    # Write rankings
    rankings = [
        _make_ranking(ticker="AAAA", tier_any="A", opt_rr_25d="0.25", catalyst_days="60"),
        _make_ranking(ticker="BBBB", tier_any="B", opt_rr_25d="-0.10", catalyst_days="45"),
        _make_ranking(ticker="CCCC", tier_any="C", opt_rr_25d="0.50", catalyst_days="90"),
        _make_ranking(ticker="DDDD", tier_any="D", opt_rr_25d="", catalyst_days="30"),
        _make_ranking(ticker="NOCAT", tier_any="A", opt_rr_25d="0.30", catalyst_days=""),
    ]
    fieldnames = list(rankings[0].keys())
    with open(sd / "rankings.csv", "w", encoding="utf-8", newline="\n") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        writer.writerows(rankings)

    # Write chain for AAAA
    with open(chains_dir / "AAAA.json", "w") as f:
        json.dump(SAMPLE_CHAIN, f)
    # Write chain for CCCC
    with open(chains_dir / "CCCC.json", "w") as f:
        json.dump(SAMPLE_CHAIN, f)

    return sd


@pytest.fixture
def data_dir(tmp_path):
    """Create a minimal price_history.csv."""
    dd = tmp_path / "production_data"
    dd.mkdir()
    with open(dd / "price_history.csv", "w", encoding="utf-8", newline="\n") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "ticker", "close", "open", "high", "low", "volume"])
        writer.writeheader()
        for ticker, price in [("AAAA", 10.0), ("BBBB", 20.0), ("CCCC", 12.0), ("DDDD", 5.0)]:
            writer.writerow(
                {
                    "date": "2026-03-16",
                    "ticker": ticker,
                    "close": price,
                    "open": price,
                    "high": price,
                    "low": price,
                    "volume": 100000,
                }
            )
    return dd


# ---------------------------------------------------------------------------
# Filter tests
# ---------------------------------------------------------------------------


class TestCandidateFilters:
    def test_default_filters_include_abc(self, snapshot_dir, data_dir):
        """Default tiers A+B+C all pass."""
        from scripts.research.build_long_call_candidates import load_rankings

        rankings = load_rankings(snapshot_dir)
        filtered = apply_candidate_filters(
            rankings,
            allowed_tiers={"A", "B", "C"},
            catalyst_window=(15, 180),
            require_hard_catalyst=False,
            require_positive_rr=False,
        )
        tickers = {r["ticker"] for r in filtered}
        assert "AAAA" in tickers
        assert "BBBB" in tickers
        assert "CCCC" in tickers
        assert "DDDD" not in tickers  # Tier D excluded
        assert "NOCAT" not in tickers  # No catalyst_days

    def test_hard_catalyst_filter(self, snapshot_dir, data_dir):
        """Hard catalyst requirement excludes all our fixtures."""
        from scripts.research.build_long_call_candidates import load_rankings

        rankings = load_rankings(snapshot_dir)
        filtered = apply_candidate_filters(
            rankings,
            allowed_tiers={"A", "B", "C"},
            catalyst_window=(15, 180),
            require_hard_catalyst=True,
            require_positive_rr=False,
        )
        assert len(filtered) == 0

    def test_positive_rr_filter(self, snapshot_dir, data_dir):
        """Positive RR requirement excludes BBBB (negative RR)."""
        from scripts.research.build_long_call_candidates import load_rankings

        rankings = load_rankings(snapshot_dir)
        filtered = apply_candidate_filters(
            rankings,
            allowed_tiers={"A", "B", "C"},
            catalyst_window=(15, 180),
            require_hard_catalyst=False,
            require_positive_rr=True,
        )
        tickers = {r["ticker"] for r in filtered}
        assert "AAAA" in tickers
        assert "CCCC" in tickers
        assert "BBBB" not in tickers  # Negative RR
        assert "DDDD" not in tickers  # Missing RR

    def test_catalyst_window_filter(self, snapshot_dir, data_dir):
        """Catalyst window excludes names outside range."""
        from scripts.research.build_long_call_candidates import load_rankings

        rankings = load_rankings(snapshot_dir)
        filtered = apply_candidate_filters(
            rankings,
            allowed_tiers={"A", "B", "C"},
            catalyst_window=(50, 70),
            require_hard_catalyst=False,
            require_positive_rr=False,
        )
        tickers = {r["ticker"] for r in filtered}
        assert "AAAA" in tickers  # 60d
        assert "BBBB" not in tickers  # 45d
        assert "CCCC" not in tickers  # 90d


# ---------------------------------------------------------------------------
# Contract selection tests
# ---------------------------------------------------------------------------


class TestContractSelection:
    def test_selects_post_catalyst_expiry(self):
        """Never selects expiry before catalyst."""
        result = select_contracts(
            SAMPLE_CHAIN,
            catalyst_days=60,
            as_of_date="2026-03-16",
            stock_price=10.0,
            tier="A",
            iv_level=0.8,
        )
        assert not result["no_trade"]
        assert result["primary"] is not None
        # Mar 20 expiry is before catalyst (day 60 = May 15), so should not be selected
        assert result["primary"]["expiry"] != "2026-03-20"

    def test_rejects_low_oi(self):
        """Contracts with OI < 50 are rejected."""
        thin_chain = [
            {**SAMPLE_CHAIN[0], "open_interest": 5, "day_volume": 1},
        ]
        result = select_contracts(
            thin_chain,
            catalyst_days=60,
            as_of_date="2026-03-16",
            stock_price=10.0,
            tier="A",
            iv_level=0.8,
        )
        assert result["no_trade"]

    def test_rejects_absurd_dte(self):
        """Contracts with DTE > 180 are rejected."""
        far_chain = [
            {**SAMPLE_CHAIN[0], "expiration_date": "2028-01-21", "open_interest": 500},
        ]
        result = select_contracts(
            far_chain,
            catalyst_days=30,
            as_of_date="2026-03-16",
            stock_price=10.0,
            tier="A",
            iv_level=0.8,
        )
        assert result["no_trade"]
        assert "no_near_term_chain_insufficient" in (result.get("no_trade_reason") or "")

    def test_no_chain_returns_no_trade(self):
        """Empty chain returns no_trade."""
        result = select_contracts(
            [],
            catalyst_days=60,
            as_of_date="2026-03-16",
            stock_price=10.0,
            tier="A",
            iv_level=0.8,
        )
        assert result["no_trade"]
        assert result["no_trade_reason"] == "no_call_contracts_in_chain"

    def test_primary_and_backup_differ(self):
        """Primary and backup contracts are different."""
        result = select_contracts(
            SAMPLE_CHAIN,
            catalyst_days=60,
            as_of_date="2026-03-16",
            stock_price=10.0,
            tier="A",
            iv_level=0.8,
        )
        if result["primary"] and result["backup"]:
            assert (
                result["primary"]["strike"] != result["backup"]["strike"]
                or result["primary"]["expiry"] != result["backup"]["expiry"]
            )


# ---------------------------------------------------------------------------
# Full pipeline tests
# ---------------------------------------------------------------------------


class TestBuildCandidates:
    def test_produces_candidates(self, snapshot_dir, data_dir):
        """Full pipeline produces candidates for fixture data."""
        from scripts.research.build_long_call_candidates import load_rankings

        rankings = load_rankings(snapshot_dir)
        candidates = build_candidates(rankings, snapshot_dir, data_dir, "2026-03-16")
        assert len(candidates) > 0
        # AAAA should be present (Tier A, catalyst 60d, has chain)
        tickers = [c["ticker"] for c in candidates]
        assert "AAAA" in tickers

    def test_category_assignment(self, snapshot_dir, data_dir):
        """Categories are correctly assigned based on RR."""
        from scripts.research.build_long_call_candidates import load_rankings

        rankings = load_rankings(snapshot_dir)
        candidates = build_candidates(rankings, snapshot_dir, data_dir, "2026-03-16")
        by_ticker = {c["ticker"]: c for c in candidates}
        if "AAAA" in by_ticker:
            assert by_ticker["AAAA"]["category"] == "strongest_directional"
        if "BBBB" in by_ticker:
            assert by_ticker["BBBB"]["category"] == "bearish_rr_caution"

    def test_no_chain_produces_no_trade(self, snapshot_dir, data_dir):
        """Tickers without chain data get NO_TRADE."""
        from scripts.research.build_long_call_candidates import load_rankings

        rankings = load_rankings(snapshot_dir)
        candidates = build_candidates(rankings, snapshot_dir, data_dir, "2026-03-16")
        by_ticker = {c["ticker"]: c for c in candidates}
        if "BBBB" in by_ticker:
            assert by_ticker["BBBB"]["no_trade"]
            assert "no_chain_data" in (by_ticker["BBBB"].get("no_trade_reason") or "")


# ---------------------------------------------------------------------------
# Output writer tests
# ---------------------------------------------------------------------------


class TestOutputWriters:
    def test_write_csv(self, tmp_path):
        candidates = [{"ticker": "AAAA", "tier": "A", "no_trade": False}]
        path = tmp_path / "test.csv"
        write_csv(candidates, path)
        assert path.exists()
        with open(path) as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 1
        assert rows[0]["ticker"] == "AAAA"

    def test_write_json(self, tmp_path):
        candidates = [{"ticker": "AAAA", "no_trade": False}]
        path = tmp_path / "test.json"
        write_json(candidates, path, "2026-03-16")
        with open(path) as f:
            d = json.load(f)
        assert d["schema_version"].startswith("long_call_candidates")
        assert d["n_candidates"] == 1

    def test_write_markdown(self, tmp_path):
        candidates = [
            {
                "ticker": "AAAA",
                "tier": "A",
                "actionable_rank": "5",
                "catalyst": "CLINICAL:PCD",
                "catalyst_days": 60,
                "stock_price": 10.0,
                "opt_rr_25d": 0.25,
                "surface_move_extreme": "low",
                "crush_adjusted_implied_move": "0.05",
                "thesis_summary": "test",
                "category": "strongest_directional",
                "no_trade": False,
                "no_trade_reason": None,
                "primary_expiry": "2026-07-17",
                "primary_dte": 123,
                "primary_strike": 10,
                "primary_delta": 0.45,
                "primary_premium_or_mid": 2.5,
                "primary_spread_or_liquidity_proxy": "OI=200,vol=50",
                "primary_breakeven_move_pct": 25.0,
                "primary_why_this_contract": "test",
                "backup_expiry": None,
            }
        ]
        path = tmp_path / "test.md"
        write_markdown(candidates, path, "2026-03-16")
        text = path.read_text()
        assert "AAAA" in text
        assert "Strongest" in text

    def test_empty_candidates(self, tmp_path):
        """Empty candidate list writes placeholder files without error."""
        write_csv([], tmp_path / "empty.csv")
        write_json([], tmp_path / "empty.json", "2026-03-16")
        write_markdown([], tmp_path / "empty.md", "2026-03-16")
        assert (tmp_path / "empty.csv").exists()
        assert (tmp_path / "empty.json").exists()
        assert (tmp_path / "empty.md").exists()


# ---------------------------------------------------------------------------
# run_from_screen integration tests
# ---------------------------------------------------------------------------


class TestRunFromScreen:
    def test_produces_artifacts(self, snapshot_dir, data_dir):
        """run_from_screen writes all three artifact files."""
        result = run_from_screen(snapshot_dir, data_dir, "2026-03-16")
        assert result is not None
        assert result > 0
        assert (snapshot_dir / "long_call_candidates.csv").exists()
        assert (snapshot_dir / "long_call_candidates.json").exists()
        assert (snapshot_dir / "long_call_candidates.md").exists()

    def test_missing_rankings_returns_none(self, tmp_path):
        """Missing rankings.csv returns None gracefully."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        result = run_from_screen(empty_dir, tmp_path, "2026-03-16")
        assert result is None

    def test_missing_chains_produces_no_trade(self, snapshot_dir, data_dir):
        """Tickers without chain files get NO_TRADE entries."""
        result = run_from_screen(snapshot_dir, data_dir, "2026-03-16")
        assert result is not None
        with open(snapshot_dir / "long_call_candidates.json") as f:
            d = json.load(f)
        no_trade_tickers = [c["ticker"] for c in d["candidates"] if c.get("no_trade")]
        # BBBB has no chain file
        assert "BBBB" in no_trade_tickers

    def test_opt_out_does_not_crash(self, snapshot_dir, data_dir):
        """Verifies the function returns cleanly — opt-out is tested at run_screen level."""
        result = run_from_screen(snapshot_dir, data_dir, "2026-03-16")
        assert isinstance(result, int)
