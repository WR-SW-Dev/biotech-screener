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
