"""Tests for live shadow portfolio tracker.

Validates:
  1. Policy loading (file + defaults)
  2. Position construction (top-K, caps, gap-risk, overage trim)
  3. Performance computation (P&L, excess vs XBI, sleeve attribution, turnover)
  4. Persistence (positions JSON, performance CSV append-only)
  5. Weekly summary markdown
  6. Deterministic output
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.live_shadow_portfolio import (
    PERF_COLUMNS,
    SCHEMA_VERSION,
    append_performance,
    build_positions,
    compute_performance,
    load_policy,
    load_prior_positions,
    load_rankings,
    run_shadow_portfolio,
    save_positions,
    write_weekly_summary,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

POLICY = {
    "schema": "portfolio_policy.v1",
    "account_usd": 100_000,
    "bucket_targets": {
        "binary_91_180": 0.50,
        "binary_31_90": 0.25,
        "binary_0_30": 0.15,
        "less_binary": 0.10,
    },
    "bucket_top_k": {
        "binary_91_180": 3,
        "binary_31_90": 3,
        "binary_0_30": 3,
        "less_binary": 3,
    },
    "bucket_name_caps": {
        "binary_91_180": 5.0,
        "binary_31_90": 3.0,
        "binary_0_30": 2.0,
        "less_binary": 3.0,
    },
    "gap_risk": {"high_days": 7, "high_cap_pct": 0.5},
    "rebalance_buffer_ranks": 30,
    "bucket_hysteresis_days": 7,
}

RANKINGS_HEADER = [
    "ticker",
    "actionable_rank",
    "eligible",
    "catalyst_days",
    "catalyst_mode",
    "tier_any",
    "size_band",
    "target_weight_pct",
    "mom_state",
    "archetype",
    "alpha_cohort_key",
    "industry_group",
    "catalyst_bucket",
    "catalyst_strength",
    "de_beta_xbi_60d_source",
]


def _make_ranking_row(
    ticker: str,
    rank: int,
    catalyst_days: str = "",
    catalyst_mode: str = "missing",
    eligible: str = "1",
    size_band: str = "M",
    de_beta_xbi_60d_source: str = "price_history",
) -> Dict[str, str]:
    return {
        "ticker": ticker,
        "actionable_rank": str(rank),
        "eligible": eligible,
        "catalyst_days": catalyst_days,
        "catalyst_mode": catalyst_mode,
        "tier_any": "A",
        "size_band": size_band,
        "target_weight_pct": "1.0",
        "mom_state": "tailwind",
        "archetype": "drug_developer",
        "alpha_cohort_key": "",
        "industry_group": "",
        "catalyst_bucket": "",
        "catalyst_strength": "",
        "de_beta_xbi_60d_source": de_beta_xbi_60d_source,
    }


def _write_rankings(snap_dir: Path, rows: List[Dict[str, str]]) -> None:
    snap_dir.mkdir(parents=True, exist_ok=True)
    csv_path = snap_dir / "rankings.csv"
    if rows:
        fieldnames = list(rows[0].keys())
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)


def _write_metadata(snap_dir: Path, as_of_date: str = "2026-03-08") -> None:
    meta = {
        "as_of_date": as_of_date,
        "version": "v1.3.0",
        "ruleset_id": "test_rs",
        "ruleset_hash": "abc123",
    }
    with open(snap_dir / "metadata.json", "w") as f:
        json.dump(meta, f)


def _write_price_history(path: Path, data: List[Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["date", "ticker", "close", "open", "high", "low", "volume"]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in data:
            writer.writerow(row)


def _make_snapshot(tmp_path: Path, name: str = "2026-03-08") -> Path:
    """Create a snapshot with diverse bucket coverage."""
    snap_dir = tmp_path / "snaps" / name
    rows = [
        # Binary 0-30 (3 names, one with gap risk HIGH)
        _make_ranking_row("BIN1", 1, "5", "specific_days"),
        _make_ranking_row("BIN2", 2, "15", "specific_days"),
        _make_ranking_row("BIN3", 3, "25", "specific_days"),
        # Binary 31-90 (3 names)
        _make_ranking_row("MID1", 4, "45", "specific_days"),
        _make_ranking_row("MID2", 5, "60", "specific_days"),
        _make_ranking_row("MID3", 6, "85", "specific_days"),
        # Binary 91-180 (4 names, top-K=3 so 1 excluded)
        _make_ranking_row("FAR1", 7, "100", "specific_days"),
        _make_ranking_row("FAR2", 8, "130", "specific_days"),
        _make_ranking_row("FAR3", 9, "160", "specific_days"),
        _make_ranking_row("FAR4", 10, "175", "specific_days"),
        # Less binary (2 names, 1 missing price)
        _make_ranking_row("CORE1", 11),
        _make_ranking_row("CORE2", 12, de_beta_xbi_60d_source=""),
    ]
    _write_rankings(snap_dir, rows)
    _write_metadata(snap_dir, name)
    return snap_dir


# ---------------------------------------------------------------------------
# A) Policy loading
# ---------------------------------------------------------------------------


class TestPolicyLoading:

    def test_load_from_file(self, tmp_path):
        p = tmp_path / "policy.json"
        with open(p, "w") as f:
            json.dump(POLICY, f)
        loaded = load_policy(p)
        assert loaded["account_usd"] == 100_000
        assert loaded["bucket_targets"]["binary_91_180"] == 0.50

    def test_load_defaults_when_missing(self, tmp_path):
        loaded = load_policy(tmp_path / "nonexistent.json")
        assert loaded["account_usd"] == 500_000
        assert "bucket_targets" in loaded

    def test_default_has_all_buckets(self, tmp_path):
        loaded = load_policy(tmp_path / "nonexistent.json")
        for b in ["binary_0_30", "binary_31_90", "binary_91_180", "less_binary"]:
            assert b in loaded["bucket_targets"]


# ---------------------------------------------------------------------------
# B) Position construction
# ---------------------------------------------------------------------------


class TestBuildPositions:

    def test_top_k_selection(self, tmp_path):
        snap = _make_snapshot(tmp_path)
        rankings = load_rankings(snap)
        result = build_positions(rankings, POLICY, 100_000)
        positions = result["positions"]
        # 3+3+3+2 = 11 (FAR4 excluded by top-K=3, only 2 less-binary)
        assert len(positions) == 11

    def test_bucket_assignment(self, tmp_path):
        snap = _make_snapshot(tmp_path)
        rankings = load_rankings(snap)
        result = build_positions(rankings, POLICY, 100_000)
        buckets = {}
        for p in result["positions"]:
            buckets.setdefault(p["bucket"], []).append(p["ticker"])
        assert "BIN1" in buckets["binary_0_30"]
        assert "MID1" in buckets["binary_31_90"]
        assert "FAR1" in buckets["binary_91_180"]
        assert "CORE1" in buckets["less_binary"]

    def test_gap_risk_high_capped(self, tmp_path):
        snap = _make_snapshot(tmp_path)
        rankings = load_rankings(snap)
        result = build_positions(rankings, POLICY, 100_000)
        bin1 = [p for p in result["positions"] if p["ticker"] == "BIN1"][0]
        assert bin1["gap_risk"] == "HIGH"
        assert bin1["weight_pct"] <= POLICY["gap_risk"]["high_cap_pct"]

    def test_per_bucket_cap_enforced(self, tmp_path):
        snap = _make_snapshot(tmp_path)
        rankings = load_rankings(snap)
        result = build_positions(rankings, POLICY, 100_000)
        for p in result["positions"]:
            bucket_cap = POLICY["bucket_name_caps"].get(p["bucket"], 5.0)
            assert p["weight_pct"] <= bucket_cap + 0.01

    def test_total_never_exceeds_account(self, tmp_path):
        snap = _make_snapshot(tmp_path)
        rankings = load_rankings(snap)
        result = build_positions(rankings, POLICY, 100_000)
        total = sum(p["target_dollars"] for p in result["positions"])
        assert total <= 100_000 + 0.01

    def test_missing_price_flagged(self, tmp_path):
        snap = _make_snapshot(tmp_path)
        rankings = load_rankings(snap)
        result = build_positions(rankings, POLICY, 100_000)
        core2 = [p for p in result["positions"] if p["ticker"] == "CORE2"][0]
        assert core2["price_coverage"] == "MISSING"
        assert "CORE2" in result["summary"]["missing_price"]

    def test_summary_has_required_keys(self, tmp_path):
        snap = _make_snapshot(tmp_path)
        rankings = load_rankings(snap)
        result = build_positions(rankings, POLICY, 100_000)
        s = result["summary"]
        assert "total_positions" in s
        assert "total_allocated" in s
        assert "residual_cash" in s
        assert "per_bucket" in s
        assert "gap_risk_high" in s


# ---------------------------------------------------------------------------
# C) Performance computation
# ---------------------------------------------------------------------------


class TestPerformance:

    def _make_positions(self, tickers_dollars):
        return [{"ticker": t, "target_dollars": d, "bucket": "binary_91_180"} for t, d in tickers_dollars]

    def test_basic_pnl(self, tmp_path):
        price_path = tmp_path / "prices.csv"
        _write_price_history(
            price_path,
            [
                {"date": "2026-03-01", "ticker": "A", "close": "100"},
                {"date": "2026-03-01", "ticker": "XBI", "close": "100"},
                {"date": "2026-03-08", "ticker": "A", "close": "110"},
                {"date": "2026-03-08", "ticker": "XBI", "close": "102"},
            ],
        )
        prior = self._make_positions([("A", 10_000)])
        current = self._make_positions([("A", 10_000)])
        perf = compute_performance(prior, current, "2026-03-01", "2026-03-08", price_path)
        assert perf["total_pnl"] == 1000.0  # 10% of $10k
        assert abs(perf["pnl_pct"] - 10.0) < 0.01
        assert abs(perf["xbi_return_pct"] - 2.0) < 0.01
        assert abs(perf["excess_vs_xbi_pct"] - 8.0) < 0.01

    def test_turnover_computation(self, tmp_path):
        price_path = tmp_path / "prices.csv"
        _write_price_history(price_path, [])
        prior = self._make_positions([("A", 5_000), ("B", 5_000)])
        current = self._make_positions([("A", 5_000), ("C", 5_000)])
        perf = compute_performance(prior, current, "2026-03-01", "2026-03-08", price_path)
        # 1 of 2 prior names dropped
        assert abs(perf["turnover"] - 0.5) < 0.01

    def test_sleeve_attribution(self, tmp_path):
        price_path = tmp_path / "prices.csv"
        _write_price_history(
            price_path,
            [
                {"date": "2026-03-01", "ticker": "A", "close": "100"},
                {"date": "2026-03-01", "ticker": "B", "close": "50"},
                {"date": "2026-03-01", "ticker": "XBI", "close": "100"},
                {"date": "2026-03-08", "ticker": "A", "close": "120"},
                {"date": "2026-03-08", "ticker": "B", "close": "45"},
                {"date": "2026-03-08", "ticker": "XBI", "close": "102"},
            ],
        )
        prior = [
            {"ticker": "A", "target_dollars": 5000, "bucket": "binary_91_180"},
            {"ticker": "B", "target_dollars": 5000, "bucket": "binary_0_30"},
        ]
        perf = compute_performance(prior, prior, "2026-03-01", "2026-03-08", price_path)
        sleeve = perf["sleeve_attribution"]
        assert sleeve["binary_91_180"]["pnl"] == 1000.0  # A: +20%
        assert sleeve["binary_0_30"]["pnl"] == -500.0  # B: -10%
        # Excess vs XBI fields present when XBI is priced
        assert "excess_vs_xbi_pct" in sleeve["binary_91_180"]
        assert "excess_pnl" in sleeve["binary_91_180"]
        # A: 20% return, XBI: 2% → excess ~18%
        assert abs(sleeve["binary_91_180"]["excess_vs_xbi_pct"] - 18.0) < 0.1
        # B: -10% return, XBI: 2% → excess ~-12%
        assert abs(sleeve["binary_0_30"]["excess_vs_xbi_pct"] - (-12.0)) < 0.1

    def test_contributors_emitted(self, tmp_path):
        price_path = tmp_path / "prices.csv"
        _write_price_history(
            price_path,
            [
                {"date": "2026-03-01", "ticker": "A", "close": "100"},
                {"date": "2026-03-01", "ticker": "B", "close": "50"},
                {"date": "2026-03-01", "ticker": "XBI", "close": "100"},
                {"date": "2026-03-08", "ticker": "A", "close": "120"},
                {"date": "2026-03-08", "ticker": "B", "close": "45"},
                {"date": "2026-03-08", "ticker": "XBI", "close": "102"},
            ],
        )
        prior = [
            {"ticker": "A", "target_dollars": 5000, "bucket": "binary_91_180"},
            {"ticker": "B", "target_dollars": 5000, "bucket": "binary_0_30"},
        ]
        perf = compute_performance(prior, prior, "2026-03-01", "2026-03-08", price_path)
        contribs = perf["contributors"]
        assert len(contribs) == 2
        # Sorted by pnl descending — A (+$1000) first
        assert contribs[0]["ticker"] == "A"
        assert contribs[0]["pnl"] == 1000.0
        assert contribs[1]["ticker"] == "B"
        assert contribs[1]["pnl"] == -500.0
        # Excess fields present
        assert "excess_vs_xbi_pct" in contribs[0]
        assert "excess_pnl" in contribs[0]
        assert "bucket" in contribs[0]

    def test_missing_prices_counted(self, tmp_path):
        price_path = tmp_path / "prices.csv"
        _write_price_history(price_path, [])
        prior = self._make_positions([("A", 5_000)])
        perf = compute_performance(prior, prior, "2026-03-01", "2026-03-08", price_path)
        assert perf["n_missing_price"] == 1
        assert perf["n_priced"] == 0


# ---------------------------------------------------------------------------
# D) Persistence
# ---------------------------------------------------------------------------


class TestPersistence:

    def test_save_and_load_positions(self, tmp_path):
        pos_data = {
            "positions": [
                {"ticker": "A", "bucket": "binary_91_180", "target_dollars": 5000},
            ],
            "summary": {"total_positions": 1},
        }
        pos_dir = tmp_path / "positions"
        save_positions("2026-03-08", pos_data, {"ruleset_id": "test"}, pos_dir)

        path = pos_dir / "2026-03-08.json"
        assert path.is_file()
        doc = json.loads(path.read_text())
        assert doc["schema"] == SCHEMA_VERSION
        assert doc["as_of_date"] == "2026-03-08"
        assert len(doc["positions"]) == 1

    def test_load_prior_positions(self, tmp_path):
        pos_dir = tmp_path / "positions"
        # Save two dates
        for date in ["2026-03-06", "2026-03-08"]:
            save_positions(
                date,
                {"positions": [{"ticker": "A"}], "summary": {}},
                {},
                pos_dir,
            )
        result = load_prior_positions("2026-03-08", pos_dir)
        assert result is not None
        prior_date, positions = result
        assert prior_date == "2026-03-06"

    def test_no_prior_returns_none(self, tmp_path):
        pos_dir = tmp_path / "positions"
        pos_dir.mkdir(parents=True)
        result = load_prior_positions("2026-03-08", pos_dir)
        assert result is None

    def test_append_performance_csv(self, tmp_path):
        perf_csv = tmp_path / "performance.csv"
        perf = {
            "prior_date": "2026-03-06",
            "total_pnl": 500.0,
            "pnl_pct": 1.5,
            "xbi_return_pct": 0.5,
            "excess_vs_xbi_pct": 1.0,
            "n_prior": 20,
            "turnover": 0.1,
            "gap_risk_high_count": 2,
            "n_missing_price": 1,
            "sleeve_attribution": {
                "binary_0_30": {"pnl": 100},
                "binary_31_90": {"pnl": 150},
                "binary_91_180": {"pnl": 200},
                "less_binary": {"pnl": 50},
            },
        }
        append_performance("2026-03-08", perf, "test_rs", perf_csv)
        append_performance("2026-03-09", perf, "test_rs", perf_csv)

        with open(perf_csv) as f:
            reader = list(csv.DictReader(f))
        assert len(reader) == 2
        assert reader[0]["date"] == "2026-03-08"
        assert reader[1]["date"] == "2026-03-09"
        assert set(reader[0].keys()) == set(PERF_COLUMNS)

    def test_append_performance_dedup(self, tmp_path):
        """Re-appending same (date, prior_date, ruleset_id) is a no-op."""
        perf_csv = tmp_path / "performance.csv"
        perf = {
            "prior_date": "2026-03-06",
            "total_pnl": 500.0,
            "pnl_pct": 1.5,
            "xbi_return_pct": 0.5,
            "excess_vs_xbi_pct": 1.0,
            "n_prior": 20,
            "turnover": 0.1,
            "gap_risk_high_count": 0,
            "n_missing_price": 0,
            "sleeve_attribution": {
                "binary_0_30": {"pnl": 100},
                "binary_31_90": {"pnl": 150},
                "binary_91_180": {"pnl": 200},
                "less_binary": {"pnl": 50},
            },
        }
        append_performance("2026-03-08", perf, "test_rs", perf_csv)
        append_performance("2026-03-08", perf, "test_rs", perf_csv)  # duplicate

        with open(perf_csv) as f:
            reader = list(csv.DictReader(f))
        assert len(reader) == 1, f"Expected 1 row, got {len(reader)} (dedup failed)"

    def test_append_performance_different_ruleset_not_deduped(self, tmp_path):
        """Different ruleset_id on same date is NOT a duplicate."""
        perf_csv = tmp_path / "performance.csv"
        perf = {
            "prior_date": "2026-03-06",
            "total_pnl": 500.0,
            "pnl_pct": 1.5,
            "xbi_return_pct": 0.5,
            "excess_vs_xbi_pct": 1.0,
            "n_prior": 20,
            "turnover": 0.1,
            "gap_risk_high_count": 0,
            "n_missing_price": 0,
            "sleeve_attribution": {},
        }
        append_performance("2026-03-08", perf, "rs_a", perf_csv)
        append_performance("2026-03-08", perf, "rs_b", perf_csv)

        with open(perf_csv) as f:
            reader = list(csv.DictReader(f))
        assert len(reader) == 2


# ---------------------------------------------------------------------------
# E) Weekly summary
# ---------------------------------------------------------------------------


class TestWeeklySummary:

    def test_summary_created(self, tmp_path):
        pos_data = {
            "positions": [
                {
                    "ticker": "A",
                    "bucket": "binary_91_180",
                    "target_dollars": 50000,
                    "weight_pct": 5.0,
                    "actionable_rank": 1,
                    "gap_risk": "",
                },
            ],
            "summary": {
                "total_positions": 1,
                "total_allocated": 50000,
                "residual_cash": 50000,
                "per_bucket": {
                    "binary_91_180": {
                        "count": 1,
                        "total_dollars": 50000,
                        "weight_pct": 5.0,
                    }
                },
                "gap_risk_high": [],
                "missing_price": [],
            },
        }
        out_path = tmp_path / "summary.md"
        write_weekly_summary("2026-03-08", pos_data, None, POLICY, {"ruleset_id": "test"}, out_path)
        text = out_path.read_text()
        assert "Weekly Shadow Portfolio Summary" in text
        assert "Policy vs Actual" in text
        assert "$100,000" in text

    def test_summary_with_performance(self, tmp_path):
        pos_data = {
            "positions": [
                {
                    "ticker": "A",
                    "bucket": "binary_91_180",
                    "target_dollars": 50000,
                    "weight_pct": 5.0,
                    "actionable_rank": 1,
                    "gap_risk": "",
                },
            ],
            "summary": {
                "total_positions": 1,
                "total_allocated": 50000,
                "residual_cash": 50000,
                "per_bucket": {},
                "gap_risk_high": [],
                "missing_price": [],
            },
        }
        perf = {
            "prior_date": "2026-03-01",
            "total_pnl": 1500.0,
            "pnl_pct": 3.0,
            "xbi_return_pct": 1.0,
            "excess_vs_xbi_pct": 2.0,
            "turnover": 0.15,
            "sleeve_attribution": {
                "binary_0_30": {
                    "pnl": 100,
                    "return_pct": 1.0,
                    "weight": 10000,
                    "excess_vs_xbi_pct": 0.0,
                    "excess_pnl": 0,
                },
                "binary_31_90": {
                    "pnl": 200,
                    "return_pct": 1.5,
                    "weight": 15000,
                    "excess_vs_xbi_pct": 0.5,
                    "excess_pnl": 50,
                },
                "binary_91_180": {
                    "pnl": 1000,
                    "return_pct": 3.5,
                    "weight": 50000,
                    "excess_vs_xbi_pct": 2.5,
                    "excess_pnl": 750,
                },
                "less_binary": {
                    "pnl": 200,
                    "return_pct": 2.0,
                    "weight": 10000,
                    "excess_vs_xbi_pct": 1.0,
                    "excess_pnl": 100,
                },
            },
            "contributors": [
                {
                    "ticker": "TOP1",
                    "bucket": "binary_91_180",
                    "dollars": 25000,
                    "return_pct": 5.0,
                    "pnl": 1250.0,
                    "excess_vs_xbi_pct": 4.0,
                    "excess_pnl": 1000,
                },
                {
                    "ticker": "TOP2",
                    "bucket": "binary_31_90",
                    "dollars": 15000,
                    "return_pct": 2.0,
                    "pnl": 300.0,
                    "excess_vs_xbi_pct": 1.0,
                    "excess_pnl": 150,
                },
                {
                    "ticker": "BOT1",
                    "bucket": "binary_0_30",
                    "dollars": 10000,
                    "return_pct": -1.0,
                    "pnl": -100.0,
                    "excess_vs_xbi_pct": -2.0,
                    "excess_pnl": -200,
                },
            ],
        }
        out_path = tmp_path / "summary.md"
        write_weekly_summary("2026-03-08", pos_data, perf, POLICY, {"ruleset_id": "test"}, out_path)
        text = out_path.read_text()
        assert "Performance vs Prior" in text
        assert "$1,500.00" in text
        assert "Excess vs XBI" in text
        assert "Sleeve Attribution" in text
        assert "Excess %" in text
        assert "What Drove the Week" in text
        assert "TOP1" in text
        assert "Rollup" in text
        assert "Binary (all)" in text


# ---------------------------------------------------------------------------
# F) Deterministic output
# ---------------------------------------------------------------------------


class TestDeterministic:

    def test_positions_stable_across_runs(self, tmp_path):
        snap = _make_snapshot(tmp_path)
        rankings = load_rankings(snap)
        r1 = build_positions(rankings, POLICY, 100_000)
        r2 = build_positions(rankings, POLICY, 100_000)
        t1 = [(p["ticker"], p["target_dollars"]) for p in r1["positions"]]
        t2 = [(p["ticker"], p["target_dollars"]) for p in r2["positions"]]
        assert t1 == t2


# ---------------------------------------------------------------------------
# G) End-to-end
# ---------------------------------------------------------------------------


class TestEndToEnd:

    def test_run_shadow_portfolio(self, tmp_path):
        snap = _make_snapshot(tmp_path)
        shadow_root = tmp_path / "shadow"
        result = run_shadow_portfolio(
            snap,
            account_usd=100_000,
            price_path=tmp_path / "empty_prices.csv",
            shadow_root=shadow_root,
        )
        assert result["summary"]["total_positions"] > 0
        pos_path = Path(result["positions_path"])
        assert pos_path.is_file()
        assert (shadow_root / "weekly_summary.md").is_file()

    def test_two_snapshots_with_performance(self, tmp_path):
        """Two sequential snapshots produce performance comparison."""
        snap1_dir = tmp_path / "snaps" / "2026-03-06"
        snap2_dir = tmp_path / "snaps" / "2026-03-08"

        # Same rankings for both
        rows = [
            _make_ranking_row("A", 1, "100", "specific_days"),
            _make_ranking_row("B", 2, "120", "specific_days"),
        ]
        _write_rankings(snap1_dir, rows)
        _write_metadata(snap1_dir, "2026-03-06")
        _write_rankings(snap2_dir, rows)
        _write_metadata(snap2_dir, "2026-03-08")

        # Price data
        price_path = tmp_path / "prices.csv"
        _write_price_history(
            price_path,
            [
                {"date": "2026-03-06", "ticker": "A", "close": "100"},
                {"date": "2026-03-06", "ticker": "B", "close": "50"},
                {"date": "2026-03-08", "ticker": "A", "close": "105"},
                {"date": "2026-03-08", "ticker": "B", "close": "52"},
            ],
        )

        shadow_root = tmp_path / "shadow"

        # Run first snapshot
        r1 = run_shadow_portfolio(
            snap1_dir,
            account_usd=100_000,
            price_path=price_path,
            shadow_root=shadow_root,
        )
        assert r1["performance"] is None  # no prior

        # Run second snapshot
        r2 = run_shadow_portfolio(
            snap2_dir,
            account_usd=100_000,
            price_path=price_path,
            shadow_root=shadow_root,
        )
        assert r2["performance"] is not None
        assert r2["performance"]["total_pnl"] > 0  # both stocks went up
        assert (shadow_root / "performance.csv").is_file()


# ---------------------------------------------------------------------------
# AST-based isolation enforcement
# ---------------------------------------------------------------------------


class TestIsolationEnforcement:
    """AST-scan to ensure all calls to guarded functions in this test file
    pass explicit path kwargs (no production defaults).
    """

    REQUIRED_KWARGS = {
        "compute_performance": {"price_path"},
        "save_positions": {"out_dir"},
        "load_prior_positions": {"positions_dir"},
        "append_performance": {"perf_csv"},
        "write_weekly_summary": {"out_path"},
        "run_shadow_portfolio": {"price_path", "shadow_root"},
    }

    # Tests that intentionally omit kwargs (e.g., guard verification)
    ALLOWED_MISSING: set = set()

    def _scan_test_file(self, filepath):
        import ast

        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(filepath))
        violations = []

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func_name = None
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                func_name = node.func.attr
            if func_name not in self.REQUIRED_KWARGS:
                continue

            enclosing = self._find_enclosing_function(tree, node.lineno)
            if enclosing in self.ALLOWED_MISSING:
                continue

            call_kwargs = {kw.arg for kw in node.keywords if kw.arg is not None}
            # Also count positional args (some functions take path as positional)
            n_positional = len(node.args)
            required = self.REQUIRED_KWARGS[func_name]

            # For functions where the guarded param can be positional,
            # check if enough positional args cover it
            missing = set()
            for kw_name in required:
                if kw_name not in call_kwargs:
                    # Check if it could be a positional arg
                    if not self._is_covered_by_positional(func_name, kw_name, n_positional):
                        missing.add(kw_name)

            if missing:
                violations.append(
                    f"{filepath.name}:{node.lineno} — {func_name}() "
                    f"missing {sorted(missing)} (in {enclosing or '<module>'})"
                )
        return violations

    @staticmethod
    def _is_covered_by_positional(func_name, kw_name, n_positional):
        """Check if a keyword arg is covered by a positional argument."""
        # Map function → param index for guarded params that can be positional
        # Index is 0-based: if param is at index N, n_positional must be > N
        positional_indices = {
            ("save_positions", "out_dir"): 3,
            ("load_prior_positions", "positions_dir"): 1,
            ("append_performance", "perf_csv"): 3,
            ("write_weekly_summary", "out_path"): 5,
            ("compute_performance", "price_path"): 4,
        }
        idx = positional_indices.get((func_name, kw_name))
        return idx is not None and n_positional > idx

    @staticmethod
    def _find_enclosing_function(tree, lineno):
        import ast

        enclosing = ""
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                end = getattr(node, "end_lineno", node.lineno + 1000)
                if node.lineno <= lineno <= end:
                    enclosing = node.name
        return enclosing

    def test_all_calls_pass_isolation_kwargs(self):
        """Every call to guarded live_shadow functions must include explicit
        path kwargs. If this fails, a new test omitted isolation kwargs."""
        test_file = Path(__file__)
        violations = self._scan_test_file(test_file)
        assert not violations, "Found test calls missing required isolation kwargs:\n" + "\n".join(
            f"  {v}" for v in violations
        )


# ---------------------------------------------------------------------------
# End-to-end integration test: synthetic action loop
# ---------------------------------------------------------------------------


class TestEndToEndActionLoop:
    """Integration test that runs the full chain on synthetic fixtures and
    asserts required artifacts + weekly summary sections.

    Given: synthetic snapshot + policy + minimal price history
    Assert: positions produced, pre_trade_check PASS, trade_plan generated,
            weekly_summary contains required sections.
    """

    def _make_snapshot(self, snap_dir, as_of_date, rankings):
        """Write a minimal snapshot directory (rankings.csv + metadata.json)."""
        snap_dir.mkdir(parents=True, exist_ok=True)
        # Write rankings.csv
        if rankings:
            fieldnames = list(rankings[0].keys())
            with open(snap_dir / "rankings.csv", "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=fieldnames)
                w.writeheader()
                w.writerows(rankings)
        # Write metadata.json
        meta = {
            "as_of_date": as_of_date,
            "ruleset_id": "test_e2e",
            "version": "v_test",
        }
        with open(snap_dir / "metadata.json", "w") as f:
            json.dump(meta, f)

    def _make_price_csv(self, price_path, tickers, dates, base_price=10.0):
        """Write a minimal price_history.csv with prices for tickers x dates."""
        price_path.parent.mkdir(parents=True, exist_ok=True)
        with open(price_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["ticker", "date", "open", "high", "low", "close", "volume"])
            w.writeheader()
            for ticker in tickers:
                for i, date in enumerate(dates):
                    p = base_price + i * 0.5
                    w.writerow(
                        {
                            "ticker": ticker,
                            "date": date,
                            "open": str(p),
                            "high": str(p + 0.1),
                            "low": str(p - 0.1),
                            "close": str(p),
                            "volume": "100000",
                        }
                    )
            # Add XBI for benchmark
            for i, date in enumerate(dates):
                p = 80.0 + i * 0.3
                w.writerow(
                    {
                        "ticker": "XBI",
                        "date": date,
                        "open": str(p),
                        "high": str(p + 0.1),
                        "low": str(p - 0.1),
                        "close": str(p),
                        "volume": "500000",
                    }
                )

    def _make_rankings(self, n=25):
        """Generate N synthetic ranking rows."""
        rows = []
        for i in range(n):
            ticker = f"BIO{i:03d}"
            rows.append(
                {
                    "ticker": ticker,
                    "actionable_rank": i + 1,
                    "tier_dev": "A" if i < 8 else "B",
                    "tier_commercial": "",
                    "tier_any": "A" if i < 8 else "B",
                    "eligible": "1",
                    "composite_score": str(90 - i),
                    "composite_rank": str(i + 1),
                    "optionality_pct": f"{0.95 - i * 0.02:.2f}",
                    "catalyst_days": str(120 - i * 3),
                    "gap_risk": "",
                    "price_coverage": "OK",
                    "archetype": "drug_developer",
                    "has_regulatory_upcoming_180d": "0",
                    "regulatory_days": "",
                    "regulatory_quality": "",
                    "regulatory_event_type": "",
                }
            )
        return rows

    def test_full_action_loop(self, tmp_path):
        """End-to-end: snapshot → positions → performance → pre-trade → trade plan → summary."""
        tickers = [f"BIO{i:03d}" for i in range(25)]
        dates = ["2026-03-01", "2026-03-08"]

        # 1. Create synthetic fixtures
        snap1 = tmp_path / "snapshots" / "2026-03-01"
        snap2 = tmp_path / "snapshots" / "2026-03-08"
        self._make_snapshot(snap1, "2026-03-01", self._make_rankings())
        self._make_snapshot(snap2, "2026-03-08", self._make_rankings())

        price_path = tmp_path / "prices" / "price_history.csv"
        self._make_price_csv(price_path, tickers, dates)

        shadow_root = tmp_path / "shadow"
        positions_dir = shadow_root / "positions"

        # 2. Run shadow portfolio for week 1
        r1 = run_shadow_portfolio(
            snap1,
            account_usd=100_000,
            price_path=price_path,
            shadow_root=shadow_root,
        )
        assert "positions_path" in r1
        assert Path(r1["positions_path"]).is_file()

        # 3. Run shadow portfolio for week 2 (will compute performance)
        r2 = run_shadow_portfolio(
            snap2,
            account_usd=100_000,
            price_path=price_path,
            shadow_root=shadow_root,
        )
        assert r2["performance"] is not None

        # 4. Pre-trade check PASS
        from tools.pre_trade_check import run_pre_trade_check

        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "rulesets": [{"id": "test_e2e", "file": "test.json", "status": "active"}],
                }
            )
        )

        ptc = run_pre_trade_check(
            "2026-03-08",
            positions_dir=positions_dir,
            snap_dir=snap2,
            manifest_path=manifest_path,
            deviation_max_pct=100,  # synthetic data won't match targets exactly
            max_missing_prices=25,  # synthetic tickers won't have real prices
        )
        assert ptc.overall in ("PASS", "WARN"), f"Pre-trade check failed: {ptc.checks}"

        # 5. Weekly summary has required sections
        summary_path = shadow_root / "weekly_summary.md"
        assert summary_path.is_file(), "Weekly summary not generated"
        summary_text = summary_path.read_text()
        assert "# Weekly Shadow Portfolio Summary" in summary_text
        assert "## Policy vs Actual" in summary_text
        assert "## Performance vs Prior" in summary_text
        assert "## Top 10 Holdings" in summary_text

        # 6. Performance CSV exists
        perf_csv = shadow_root / "performance.csv"
        assert perf_csv.is_file(), "Performance CSV not generated"


# ---------------------------------------------------------------------------
# H) Edge cases — coverage gaps
# ---------------------------------------------------------------------------


class TestEdgeCasesCoverageGap:
    """Targeted edge-case tests for under-covered paths:
    - Family sleeve reflow when regulatory_days <= 0 (auto-demote)
    - Time-ladder sub-bucket concentration
    - Quality-proportional weighting with zero-quality entries
    - Options overlay ImportError fallback
    """

    # -- helpers --

    def _make_row(
        self,
        ticker: str,
        rank: int,
        catalyst_days: str = "100",
        catalyst_mode: str = "specific_days",
        catalyst_family: str = "CLINICAL",
        regulatory_days: str = "",
        regulatory_quality: str = "0",
        has_regulatory_upcoming_180d: str = "0",
        regulatory_event_type: str = "",
        regulatory_confidence: str = "HIGH",
    ) -> Dict[str, str]:
        return {
            "ticker": ticker,
            "actionable_rank": str(rank),
            "eligible": "1",
            "catalyst_days": catalyst_days,
            "catalyst_mode": catalyst_mode,
            "tier_any": "A",
            "size_band": "M",
            "target_weight_pct": "1.0",
            "mom_state": "tailwind",
            "archetype": "drug_developer",
            "alpha_cohort_key": "",
            "industry_group": "",
            "catalyst_bucket": "",
            "catalyst_strength": "",
            "de_beta_xbi_60d_source": "price_history",
            "catalyst_family": catalyst_family,
            "has_regulatory_upcoming_180d": has_regulatory_upcoming_180d,
            "regulatory_days": regulatory_days,
            "regulatory_quality": regulatory_quality,
            "regulatory_event_type": regulatory_event_type,
            "regulatory_confidence": regulatory_confidence,
        }

    def _policy_with_family_targets(self, **overrides):
        """Minimal policy with family targets and ladder enabled."""
        base = {
            "schema": "portfolio_policy.v1",
            "account_usd": 100_000,
            "bucket_targets": {
                "binary_91_180": 0.60,
                "binary_31_90": 0.20,
                "binary_0_30": 0.10,
                "less_binary": 0.10,
            },
            "bucket_top_k": {
                "binary_91_180": 10,
                "binary_31_90": 10,
                "binary_0_30": 10,
                "less_binary": 10,
            },
            "bucket_name_caps": {
                "binary_91_180": 5.0,
                "binary_31_90": 5.0,
                "binary_0_30": 5.0,
                "less_binary": 5.0,
            },
            "gap_risk": {"high_days": 7, "high_cap_pct": 0.5},
            "family_targets": {
                "binary_91_180": {"REGULATORY": 0.70, "CLINICAL": 0.30},
            },
            "family_overrides": {},
            "family_filter_mode": "primary",
            "regulatory_ladder_enabled": False,
            "regulatory_quality_tilt_enabled": False,
            "regulatory_resolution_enabled": False,
            "rebalance_buffer_ranks": 30,
            "bucket_hysteresis_days": 7,
        }
        base.update(overrides)
        return base

    # -----------------------------------------------------------------------
    # 1. Regulatory resolution: auto-demote when regulatory_days <= 0
    # -----------------------------------------------------------------------

    def test_resolved_regulatory_auto_demoted(self):
        """A REGULATORY name with regulatory_days <= 0 is excluded when
        resolution is enabled."""
        rows = [
            self._make_row("RESOLVED", 1, "100", catalyst_family="REGULATORY", regulatory_days="-2"),
            self._make_row("ACTIVE", 2, "120", catalyst_family="REGULATORY", regulatory_days="45"),
            self._make_row("CLIN1", 3, "130", catalyst_family="CLINICAL"),
        ]
        policy = self._policy_with_family_targets(
            regulatory_resolution_enabled=True,
        )
        result = build_positions(rows, policy, 100_000)
        tickers = {p["ticker"] for p in result["positions"]}
        assert "RESOLVED" not in tickers, "Resolved regulatory name should be excluded"
        assert "ACTIVE" in tickers
        assert "CLIN1" in tickers

    def test_resolved_regulatory_zero_days_excluded(self):
        """regulatory_days == 0 is also considered resolved (event is today)."""
        rows = [
            self._make_row("TODAY", 1, "100", catalyst_family="REGULATORY", regulatory_days="0"),
            self._make_row("FUTURE", 2, "120", catalyst_family="REGULATORY", regulatory_days="30"),
        ]
        policy = self._policy_with_family_targets(
            regulatory_resolution_enabled=True,
        )
        result = build_positions(rows, policy, 100_000)
        tickers = {p["ticker"] for p in result["positions"]}
        assert "TODAY" not in tickers, "regulatory_days=0 should be resolved"
        assert "FUTURE" in tickers

    def test_resolved_not_excluded_when_resolution_disabled(self):
        """With resolution_enabled=False, regulatory_days <= 0 names stay."""
        rows = [
            self._make_row("RESOLVED", 1, "100", catalyst_family="REGULATORY", regulatory_days="-5"),
            self._make_row("CLIN1", 2, "120", catalyst_family="CLINICAL"),
        ]
        policy = self._policy_with_family_targets(
            regulatory_resolution_enabled=False,
        )
        result = build_positions(rows, policy, 100_000)
        tickers = {p["ticker"] for p in result["positions"]}
        assert "RESOLVED" in tickers, "Resolution disabled — name should remain"

    # -----------------------------------------------------------------------
    # 2. Family reflow: unused REGULATORY budget reflows to CLINICAL
    # -----------------------------------------------------------------------

    def test_family_reflow_when_no_regulatory_names(self):
        """When family_targets says 70% REGULATORY but there are zero
        REGULATORY names, the entire budget reflows to CLINICAL.
        Each name is capped at bucket_name_caps (5%), so 2 names get 5% each."""
        rows = [
            self._make_row("CLIN1", 1, "100", catalyst_family="CLINICAL"),
            self._make_row("CLIN2", 2, "130", catalyst_family="CLINICAL"),
        ]
        policy = self._policy_with_family_targets()
        result = build_positions(rows, policy, 100_000)
        b91_pos = [p for p in result["positions"] if p["bucket"] == "binary_91_180"]
        assert len(b91_pos) == 2, "Both CLINICAL names should be allocated"
        # With reflow, CLINICAL's effective share becomes 1.0 (all of bucket).
        # fam_frac = 0.60 * 1.0 = 0.60, equal_wt = 60.0 / 2 = 30% each,
        # but capped to 5% each → $5k each = $10k total.
        for p in b91_pos:
            assert p["weight_pct"] <= 5.0 + 0.01
            assert p["target_dollars"] > 0

    def test_family_reflow_partial(self):
        """One REGULATORY + two CLINICAL: REG gets its 70% slice, CLIN gets 30%.
        Both are subject to per-name caps."""
        rows = [
            self._make_row("REG1", 1, "100", catalyst_family="REGULATORY", regulatory_days="60"),
            self._make_row("CLIN1", 2, "120", catalyst_family="CLINICAL"),
            self._make_row("CLIN2", 3, "150", catalyst_family="CLINICAL"),
        ]
        # Use generous caps so allocation isn't cap-limited
        policy = self._policy_with_family_targets(
            bucket_name_caps={
                "binary_91_180": 50.0,
                "binary_31_90": 50.0,
                "binary_0_30": 50.0,
                "less_binary": 50.0,
            },
        )
        result = build_positions(rows, policy, 100_000)
        reg_pos = [
            p for p in result["positions"] if p["bucket"] == "binary_91_180" and p["catalyst_family"] == "REGULATORY"
        ]
        clin_pos = [
            p for p in result["positions"] if p["bucket"] == "binary_91_180" and p["catalyst_family"] == "CLINICAL"
        ]
        reg_dollars = sum(p["target_dollars"] for p in reg_pos)
        clin_dollars = sum(p["target_dollars"] for p in clin_pos)
        # REG: 60% * 70% * 100k = $42k (1 name), CLIN: 60% * 30% * 100k = $18k (2 names)
        assert reg_dollars > clin_dollars, f"REG (${reg_dollars:.0f}) should exceed CLIN (${clin_dollars:.0f})"

    # -----------------------------------------------------------------------
    # 3. Time-ladder: all positions in one sub-bucket
    # -----------------------------------------------------------------------

    def test_ladder_all_names_one_sub_bucket(self):
        """When all REGULATORY names fall in the same sub-bucket,
        the full REGULATORY budget concentrates there via reflow."""
        rows = [
            self._make_row(
                "REG1", 1, "100", catalyst_family="REGULATORY", regulatory_days="20", regulatory_quality="0.8"
            ),
            self._make_row(
                "REG2", 2, "120", catalyst_family="REGULATORY", regulatory_days="30", regulatory_quality="0.6"
            ),
            self._make_row(
                "REG3", 3, "140", catalyst_family="REGULATORY", regulatory_days="40", regulatory_quality="0.4"
            ),
        ]
        policy = self._policy_with_family_targets(
            regulatory_ladder_enabled=True,
            # Generous caps so allocation isn't cap-limited
            bucket_name_caps={
                "binary_91_180": 50.0,
                "binary_31_90": 50.0,
                "binary_0_30": 50.0,
                "less_binary": 50.0,
            },
        )
        result = build_positions(rows, policy, 100_000)
        reg_pos = [
            p for p in result["positions"] if p["bucket"] == "binary_91_180" and p["catalyst_family"] == "REGULATORY"
        ]
        # All three should be allocated (all in reg_15_45)
        assert len(reg_pos) == 3
        subs = {p["reg_sub_bucket"] for p in reg_pos}
        assert subs == {"reg_15_45"}, f"Expected all in reg_15_45, got {subs}"
        # Total should be close to the full REGULATORY slice
        # 60% * 70% * 100k = $42k
        reg_dollars = sum(p["target_dollars"] for p in reg_pos)
        assert (
            reg_dollars > 40_000
        ), f"Full REGULATORY budget should reflow to single sub-bucket, got ${reg_dollars:.0f}"

    def test_ladder_unclassified_reg_names_get_residual(self):
        """REGULATORY names with no regulatory_days get flat allocation from
        residual budget after ladder names are placed."""
        rows = [
            self._make_row(
                "REG_LADDER", 1, "100", catalyst_family="REGULATORY", regulatory_days="50", regulatory_quality="0.8"
            ),
            self._make_row(
                "REG_NO_DAYS", 2, "130", catalyst_family="REGULATORY", regulatory_days="", regulatory_quality="0.5"
            ),
        ]
        policy = self._policy_with_family_targets(
            regulatory_ladder_enabled=True,
        )
        result = build_positions(rows, policy, 100_000)
        reg_pos = {p["ticker"]: p for p in result["positions"] if p["bucket"] == "binary_91_180"}
        assert "REG_LADDER" in reg_pos
        assert "REG_NO_DAYS" in reg_pos
        # Unclassified name gets no sub-bucket
        assert reg_pos["REG_NO_DAYS"]["reg_sub_bucket"] == ""
        # Both should have non-zero allocation
        assert reg_pos["REG_LADDER"]["target_dollars"] > 0
        assert reg_pos["REG_NO_DAYS"]["target_dollars"] > 0

    # -----------------------------------------------------------------------
    # 4. Quality-proportional weighting edge cases
    # -----------------------------------------------------------------------

    def test_quality_weights_all_zero_falls_back_to_equal(self):
        """When all regulatory_quality values are 0, quality_weights
        should fall back to equal-weight allocation."""
        from tools.live_shadow_portfolio import _quality_weights

        rows = [
            {"regulatory_quality": "0"},
            {"regulatory_quality": "0"},
            {"regulatory_quality": ""},
        ]
        weights = _quality_weights(rows)
        # With q_lo=0.30 default, zero quality gets clipped to 0.30
        # so all three get equal weight
        assert len(weights) == 3
        for w in weights:
            assert abs(w - 1.0 / 3.0) < 0.001

    def test_quality_tilt_differentiates_high_low(self):
        """With ladder + quality tilt, higher quality names get more dollars."""
        rows = [
            self._make_row(
                "REG_HI", 1, "100", catalyst_family="REGULATORY", regulatory_days="50", regulatory_quality="0.95"
            ),
            self._make_row(
                "REG_LO", 2, "120", catalyst_family="REGULATORY", regulatory_days="60", regulatory_quality="0.35"
            ),
        ]
        policy = self._policy_with_family_targets(
            regulatory_ladder_enabled=True,
            regulatory_quality_tilt_enabled=True,
            # Generous caps so quality tilt isn't masked by cap clipping
            bucket_name_caps={
                "binary_91_180": 50.0,
                "binary_31_90": 50.0,
                "binary_0_30": 50.0,
                "less_binary": 50.0,
            },
        )
        result = build_positions(rows, policy, 100_000)
        pos_map = {p["ticker"]: p for p in result["positions"] if p["bucket"] == "binary_91_180"}
        assert (
            pos_map["REG_HI"]["target_dollars"] > pos_map["REG_LO"]["target_dollars"]
        ), "Higher quality name should get more dollars under quality tilt"

    def test_confidence_tilt_with_low_confidence(self):
        """LOW confidence should receive smaller allocation than HIGH."""
        from tools.live_shadow_portfolio import _combined_weights

        rows = [
            {"regulatory_quality": "0.8", "regulatory_confidence": "HIGH"},
            {"regulatory_quality": "0.8", "regulatory_confidence": "LOW"},
        ]
        weights = _combined_weights(
            rows,
            quality_tilt=True,
            q_lo=0.30,
            q_hi=1.00,
            confidence_tilt=True,
            conf_weights={"HIGH": 1.0, "MED": 0.6, "LOW": 0.3},
            conf_clip_lo=0.30,
            conf_clip_hi=1.00,
        )
        assert len(weights) == 2
        # HIGH confidence should get more weight
        assert (
            weights[0] > weights[1]
        ), f"HIGH confidence weight ({weights[0]:.3f}) should exceed LOW ({weights[1]:.3f})"

    def test_combined_weights_empty_rows(self):
        """Empty row list should return empty weights."""
        from tools.live_shadow_portfolio import _combined_weights

        weights = _combined_weights(
            [],
            quality_tilt=True,
            q_lo=0.30,
            q_hi=1.00,
            confidence_tilt=False,
            conf_weights={"HIGH": 1.0},
            conf_clip_lo=0.30,
            conf_clip_hi=1.00,
        )
        assert weights == []

    # -----------------------------------------------------------------------
    # 5. Sub-bucket cap overflow reflow
    # -----------------------------------------------------------------------

    def test_sub_bucket_cap_overflow_reflows(self):
        """When a high-quality name hits the cap, overflow reflows to
        uncapped names within the same sub-bucket."""
        from tools.live_shadow_portfolio import _allocate_sub_bucket_quality

        def _row(ticker, quality):
            return {
                "regulatory_quality": quality,
                "catalyst_days": "50",
                "catalyst_mode": "specific_days",
                "de_beta_xbi_60d_source": "price_history",
                "ticker": ticker,
                "actionable_rank": "1",
                "tier_any": "A",
                "size_band": "M",
                "mom_state": "tailwind",
                "regulatory_days": "50",
                "regulatory_event_type": "",
                "has_regulatory_upcoming_180d": "1",
                "catalyst_family": "REGULATORY",
                "regulatory_confidence": "HIGH",
            }

        rows = [_row("A", "0.95"), _row("B", "0.35"), _row("C", "0.35")]
        # sb_frac=0.10 → budget_pct=10.0, cap=4.0
        # Without cap: A gets ~10*0.95/1.65=5.76%, B/C get ~2.12% each
        # With cap=4.0: A capped at 4%, overflow 1.76% reflows to B/C
        positions = _allocate_sub_bucket_quality(
            rows,
            sb_frac=0.10,
            cap=4.0,
            bucket_name="binary_91_180",
            gap_high_days=7,
            gap_high_cap=0.5,
            acct=100_000,
            sb="reg_46_90",
            quality_tilt=True,
            q_lo=0.30,
            q_hi=1.00,
        )
        assert len(positions) == 3
        pos_a = [p for p in positions if p["ticker"] == "A"][0]
        pos_b = [p for p in positions if p["ticker"] == "B"][0]
        # A should be at the cap
        assert abs(pos_a["weight_pct"] - 4.0) < 0.01
        # B should have received some overflow (more than its original share)
        # Original B share ~ 10 * 0.35/1.65 = 2.12%, with overflow > 2.5%
        assert pos_b["weight_pct"] > 2.5, f"B should get overflow from A, got {pos_b['weight_pct']:.2f}%"
        # Total should be close to the full budget
        total_wt = sum(p["weight_pct"] for p in positions)
        assert total_wt > 9.5, f"Expected ~10% total allocation, got {total_wt:.2f}%"

    # -----------------------------------------------------------------------
    # 6. Options overlay ImportError fallback
    # -----------------------------------------------------------------------

    def test_options_overlay_import_error_uses_1x_multiplier(self):
        """When options overlay modules are unavailable, the ImportError
        fallback should apply a 1.0x multiplier (no weight change)."""
        # The sub-bucket allocator catches ImportError and logs a warning.
        # If the modules aren't installed in this test environment, this
        # exercises the fallback path. If they are installed, we verify
        # the overlay field is present.
        from tools.live_shadow_portfolio import _allocate_sub_bucket_quality

        rows = [
            {
                "regulatory_quality": "0.8",
                "catalyst_days": "50",
                "catalyst_mode": "specific_days",
                "de_beta_xbi_60d_source": "price_history",
                "ticker": "OPT1",
                "actionable_rank": "1",
                "tier_any": "A",
                "size_band": "M",
                "mom_state": "tailwind",
                "regulatory_days": "50",
                "regulatory_event_type": "",
                "has_regulatory_upcoming_180d": "0",
                "catalyst_family": "REGULATORY",
                "regulatory_confidence": "HIGH",
                "_options_fresh": False,
                "_crowding_panel_populated": False,
            },
        ]
        positions = _allocate_sub_bucket_quality(
            rows,
            sb_frac=0.10,
            cap=5.0,
            bucket_name="binary_31_90",
            gap_high_days=7,
            gap_high_cap=0.5,
            acct=100_000,
            sb="reg_15_45",
            quality_tilt=False,
            q_lo=0.30,
            q_hi=1.00,
        )
        assert len(positions) == 1
        # Regardless of whether the import succeeded or failed,
        # the position should have a valid weight
        assert positions[0]["weight_pct"] > 0
        assert positions[0]["target_dollars"] > 0

    def test_options_overlay_fallback_in_build_positions(self):
        """Exercise the options overlay code path through build_positions.
        With options_overlay enabled but modules possibly missing, positions
        should still be produced with valid weights."""
        rows = [
            self._make_row("OV1", 1, "50", catalyst_family="CLINICAL"),
            self._make_row("OV2", 2, "70", catalyst_family="CLINICAL"),
        ]
        policy = self._policy_with_family_targets(
            options_overlay={"enabled": True, "options_fresh": False, "crowding_panel_populated": False},
        )
        result = build_positions(rows, policy, 100_000)
        # Should not crash; positions should exist
        assert len(result["positions"]) >= 2
        for p in result["positions"]:
            assert p["target_dollars"] >= 0

    # -----------------------------------------------------------------------
    # 7. _reg_sub_bucket edge cases
    # -----------------------------------------------------------------------

    def test_reg_sub_bucket_boundary_values(self):
        """Verify exact boundary classification for regulatory sub-buckets."""
        from tools.live_shadow_portfolio import _reg_sub_bucket

        assert _reg_sub_bucket("0") == "", "0 days → resolved, no sub-bucket"
        assert _reg_sub_bucket("-1") == "", "Negative → no sub-bucket"
        assert _reg_sub_bucket("1") == "reg_0_14"
        assert _reg_sub_bucket("14") == "reg_0_14"
        assert _reg_sub_bucket("15") == "reg_15_45"
        assert _reg_sub_bucket("45") == "reg_15_45"
        assert _reg_sub_bucket("46") == "reg_46_90"
        assert _reg_sub_bucket("90") == "reg_46_90"
        assert _reg_sub_bucket("91") == "reg_91_180"
        assert _reg_sub_bucket("180") == "reg_91_180"
        assert _reg_sub_bucket("181") == "", ">180 → no sub-bucket"
        assert _reg_sub_bucket("") == "", "empty → no sub-bucket"
        assert _reg_sub_bucket("abc") == "", "non-numeric → no sub-bucket"

    # -----------------------------------------------------------------------
    # 8. _is_regulatory_resolved edge cases
    # -----------------------------------------------------------------------

    def test_is_regulatory_resolved_edge_values(self):
        from tools.live_shadow_portfolio import _is_regulatory_resolved

        assert _is_regulatory_resolved({"regulatory_days": "0"}) is True
        assert _is_regulatory_resolved({"regulatory_days": "-10"}) is True
        assert _is_regulatory_resolved({"regulatory_days": "1"}) is False
        assert _is_regulatory_resolved({"regulatory_days": ""}) is False
        assert _is_regulatory_resolved({}) is False
        assert _is_regulatory_resolved({"regulatory_days": "abc"}) is False

    # -----------------------------------------------------------------------
    # 9. _effective_family in secondary mode
    # -----------------------------------------------------------------------

    def test_effective_family_secondary_mode(self):
        from tools.live_shadow_portfolio import _effective_family

        # Secondary mode: has_regulatory_upcoming_180d=1 → REGULATORY
        row = {"catalyst_family": "CLINICAL", "has_regulatory_upcoming_180d": "1"}
        assert _effective_family(row, mode="secondary") == "REGULATORY"
        # Primary mode: same row → CLINICAL
        assert _effective_family(row, mode="primary") == "CLINICAL"
        # Missing catalyst_family → OTHER
        assert _effective_family({}, mode="primary") == "OTHER"
        assert _effective_family({"catalyst_family": ""}, mode="primary") == "OTHER"

    # -----------------------------------------------------------------------
    # 10. Overage trim with concentrated single-bucket portfolio
    # -----------------------------------------------------------------------

    def test_overage_trim_when_caps_exceed_account(self):
        """When bucket caps are generous and many names land in one bucket,
        total can exceed account. Overage trim must bring it back."""
        # All names in b91 with 5% cap each → 10 names × 5% × 60% bucket
        # This shouldn't exceed account, but let's create a scenario that does
        rows = []
        for i in range(20):
            rows.append(self._make_row(f"T{i:02d}", i + 1, str(100 + i)))
        policy = self._policy_with_family_targets(
            bucket_top_k={"binary_91_180": 20, "binary_31_90": 20, "binary_0_30": 20, "less_binary": 20},
            # Remove family targets to use flat allocation
            family_targets={},
        )
        result = build_positions(rows, policy, 100_000)
        total = sum(p["target_dollars"] for p in result["positions"])
        assert total <= 100_000 + 0.01, f"Overage trim failed: total ${total:.0f} exceeds $100,000"

    # -----------------------------------------------------------------------
    # 11. Ladder reflow priority order
    # -----------------------------------------------------------------------

    def test_ladder_reflow_priority_order(self):
        """When multiple sub-buckets are empty, reflow should go to the
        first active sub-bucket in priority order:
        reg_15_45 → reg_46_90 → reg_91_180 → reg_0_14.

        NOTE: This test uses the legacy sleeve construction path."""
        # Only reg_46_90 has names; reg_0_14, reg_15_45, reg_91_180 are empty
        rows = [
            self._make_row(
                "REG1", 1, "100", catalyst_family="REGULATORY", regulatory_days="60", regulatory_quality="0.7"
            ),
            self._make_row(
                "REG2", 2, "120", catalyst_family="REGULATORY", regulatory_days="75", regulatory_quality="0.5"
            ),
        ]
        policy = self._policy_with_family_targets(
            regulatory_ladder_enabled=True,
            regulatory_bucket_weights={
                "binary_91_180": {
                    "reg_0_14": 0.25,
                    "reg_15_45": 0.25,
                    "reg_46_90": 0.25,
                    "reg_91_180": 0.25,
                },
            },
            # Generous caps so reflow isn't masked by cap clipping
            bucket_name_caps={
                "binary_91_180": 50.0,
                "binary_31_90": 50.0,
                "binary_0_30": 50.0,
                "less_binary": 50.0,
            },
        )
        result = build_positions(rows, policy, 100_000)
        reg_pos = [
            p for p in result["positions"] if p["bucket"] == "binary_91_180" and p["catalyst_family"] == "REGULATORY"
        ]
        # All budget should reflow to reg_46_90
        assert len(reg_pos) == 2
        assert all(p["reg_sub_bucket"] == "reg_46_90" for p in reg_pos)
        # Should have close to the full REGULATORY allocation
        # 60% * 70% * 100k = $42k
        reg_dollars = sum(p["target_dollars"] for p in reg_pos)
        assert reg_dollars > 40_000, f"Expected full REGULATORY reflow to reg_46_90, got ${reg_dollars:.0f}"


# ---------------------------------------------------------------------------
# EW Top-30 construction mode
# ---------------------------------------------------------------------------


class TestEWTopN:
    """Tests for the promoted EW Top-N construction path (_build_ew_top_n)."""

    EW_POLICY = {
        "schema": "portfolio_policy.v4",
        "construction_mode": "ew_top_n",
        "ew_top_n": 5,
        "account_usd": 100_000,
    }

    def _make_rows(self, n: int = 10) -> List[Dict[str, str]]:
        return [_make_ranking_row(f"T{i:02d}", rank=i, catalyst_days=str(30 + i * 10)) for i in range(1, n + 1)]

    def test_selects_top_n(self):
        rows = self._make_rows(10)
        result = build_positions(rows, self.EW_POLICY, 100_000)
        assert len(result["positions"]) == 5
        tickers = [p["ticker"] for p in result["positions"]]
        assert tickers == ["T01", "T02", "T03", "T04", "T05"]

    def test_equal_weights(self):
        rows = self._make_rows(10)
        result = build_positions(rows, self.EW_POLICY, 100_000)
        for p in result["positions"]:
            assert abs(p["weight_pct"] - 20.0) < 0.01  # 100% / 5

    def test_total_weight_100(self):
        rows = self._make_rows(10)
        result = build_positions(rows, self.EW_POLICY, 100_000)
        total = sum(p["weight_pct"] for p in result["positions"])
        assert abs(total - 100.0) < 0.01

    def test_total_dollars_matches_account(self):
        rows = self._make_rows(10)
        result = build_positions(rows, self.EW_POLICY, 100_000)
        total = sum(p["target_dollars"] for p in result["positions"])
        assert abs(total - 100_000) < 1.0

    def test_fewer_names_than_n(self):
        """When universe has fewer names than ew_top_n, use all available."""
        rows = self._make_rows(3)
        result = build_positions(rows, self.EW_POLICY, 100_000)
        assert len(result["positions"]) == 3
        for p in result["positions"]:
            assert abs(p["weight_pct"] - 100.0 / 3) < 0.01

    def test_empty_rankings(self):
        result = build_positions([], self.EW_POLICY, 100_000)
        assert len(result["positions"]) == 0
        assert result["summary"]["residual_cash"] == 100_000

    def test_summary_has_construction_mode(self):
        rows = self._make_rows(10)
        result = build_positions(rows, self.EW_POLICY, 100_000)
        assert result["summary"]["construction_mode"] == "ew_top_n"
        assert result["summary"]["ew_n"] == 5

    def test_positions_have_required_fields(self):
        rows = self._make_rows(10)
        result = build_positions(rows, self.EW_POLICY, 100_000)
        required = {
            "ticker",
            "weight_pct",
            "target_dollars",
            "bucket",
            "tier",
            "actionable_rank",
            "catalyst_days",
            "size_band",
            "opt_liquidity_state",
        }
        for p in result["positions"]:
            for field in required:
                assert field in p, f"Missing field {field} in position {p['ticker']}"

    def test_size_band_is_ew(self):
        rows = self._make_rows(5)
        result = build_positions(rows, self.EW_POLICY, 100_000)
        for p in result["positions"]:
            assert p["size_band"] == "EW"

    def test_default_mode_is_sleeve(self):
        """Policy without construction_mode should use sleeve (backward compat)."""
        result = build_positions(self._make_rows(5), POLICY, 100_000)
        # Should NOT have construction_mode in summary (sleeve path)
        assert result["summary"].get("construction_mode") != "ew_top_n"

    def test_account_override(self):
        rows = self._make_rows(5)
        result = build_positions(rows, self.EW_POLICY, 200_000)
        total = sum(p["target_dollars"] for p in result["positions"])
        assert abs(total - 200_000) < 1.0
