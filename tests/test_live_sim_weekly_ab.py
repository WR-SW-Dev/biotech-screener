"""Tests for scripts/research/live_sim_weekly_ab.py."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "research"))

from live_sim_weekly_ab import (
    aggregate,
    compute_period_return,
    compute_turnover,
    discover_dates,
    load_prices,
    run_arm,
    select_rebalance_dates,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MINIMAL_POLICY = {
    "schema": "portfolio_policy.v3",
    "rebalance_cadence": "weekly",
    "rebalance_day": "FRIDAY",
    "account_usd": 100_000,
    "bucket_targets": {
        "binary_0_30": 0.10,
        "binary_31_90": 0.25,
        "binary_91_180": 0.55,
        "less_binary": 0.10,
    },
    "bucket_top_k": {
        "binary_0_30": 5,
        "binary_31_90": 5,
        "binary_91_180": 5,
        "less_binary": 5,
    },
    "bucket_name_caps": {
        "binary_0_30": 5.0,
        "binary_31_90": 5.0,
        "binary_91_180": 15.0,
        "less_binary": 5.0,
    },
    "family_filter_mode": "primary",
    "gap_risk": {"high_days": 7, "high_cap_pct": 0.5},
    "regulatory_ladder_enabled": False,
    "regulatory_resolution_enabled": False,
}


def _make_ranking_row(ticker, rank, bucket_days, eligible="1"):
    """Create a minimal rankings CSV row."""
    # catalyst_bucket is set by classify_action_bucket based on catalyst_days
    return {
        "ticker": ticker,
        "company_name": f"{ticker} Inc",
        "actionable_rank": str(rank),
        "target_weight_pct": "1.0",
        "tier_any": "A",
        "tier_any_reason": "test",
        "tier_dev": "A",
        "tier_reason": "test",
        "tier_commercial": "",
        "eligible": eligible,
        "catalyst_days": str(bucket_days),
        "catalyst_in_window": "1",
        "catalyst_mode": "specific_days",
        "catalyst_bucket": "",
        "catalyst_family": "CLINICAL",
        "catalyst_reason_detail": "test",
        "mom_state": "neutral",
        "size_band": "M",
        "risk_flags": "",
        "de_beta_xbi_60d_source": "computed",
        "has_regulatory_upcoming_180d": "0",
        "regulatory_days": "",
        "regulatory_quality": "",
        "regulatory_event_type": "",
        "catalyst_decay": "1.0",
        "binary_quality_score": "0.5",
    }


def _write_snapshot(tmp_dir, date, rows):
    """Write a minimal snapshot with rankings.csv and metadata.json."""
    snap_dir = Path(tmp_dir) / date
    snap_dir.mkdir(parents=True, exist_ok=True)

    csv_path = snap_dir / "rankings.csv"
    if rows:
        fieldnames = list(rows[0].keys())
        with open(csv_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(rows)

    meta_path = snap_dir / "metadata.json"
    meta_path.write_text(json.dumps({"as_of_date": date, "ruleset_id": "test"}))


def _write_prices(tmp_dir, price_data):
    """Write price_history.csv from list of (ticker, date, close)."""
    csv_path = Path(tmp_dir) / "prices.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["ticker", "date", "open", "high", "low", "close", "volume"])
        w.writeheader()
        for ticker, date, close in price_data:
            w.writerow(
                {
                    "ticker": ticker,
                    "date": date,
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "volume": "1000000",
                }
            )
    return csv_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDiscoverDates:
    def test_discovers_date_dirs(self, tmp_path):
        rows = [_make_ranking_row("AAA", 1, 120)]
        _write_snapshot(tmp_path, "2025-01-03", rows)
        _write_snapshot(tmp_path, "2025-01-10", rows)

        dates = discover_dates(tmp_path)
        assert dates == ["2025-01-03", "2025-01-10"]

    def test_skips_dirs_without_rankings(self, tmp_path):
        (tmp_path / "2025-01-03").mkdir()
        rows = [_make_ranking_row("AAA", 1, 120)]
        _write_snapshot(tmp_path, "2025-01-10", rows)

        dates = discover_dates(tmp_path)
        assert dates == ["2025-01-10"]


class TestSelectRebalanceDates:
    def test_every_date(self):
        dates = ["2025-01-03", "2025-01-10", "2025-01-17", "2025-01-24"]
        assert select_rebalance_dates(dates, 1) == dates

    def test_every_other(self):
        dates = ["2025-01-03", "2025-01-10", "2025-01-17", "2025-01-24"]
        assert select_rebalance_dates(dates, 2) == ["2025-01-03", "2025-01-17"]


class TestComputeTurnover:
    def test_no_change(self):
        pos = [{"ticker": "A"}, {"ticker": "B"}]
        assert compute_turnover(pos, pos) == 0.0

    def test_full_turnover(self):
        prev = [{"ticker": "A"}, {"ticker": "B"}]
        curr = [{"ticker": "C"}, {"ticker": "D"}]
        assert compute_turnover(prev, curr) == 1.0

    def test_partial_turnover(self):
        prev = [{"ticker": "A"}, {"ticker": "B"}]
        curr = [{"ticker": "A"}, {"ticker": "C"}]
        assert compute_turnover(prev, curr) == 0.5


class TestComputePeriodReturn:
    def test_simple_return(self):
        positions = [
            {"ticker": "A", "weight_pct": 50.0, "bucket": "binary_91_180"},
            {"ticker": "B", "weight_pct": 50.0, "bucket": "binary_91_180"},
        ]
        prices = {
            "A": {"2025-01-03": 10.0, "2025-01-10": 11.0},
            "B": {"2025-01-03": 20.0, "2025-01-10": 22.0},
            "XBI": {"2025-01-03": 100.0, "2025-01-10": 105.0},
        }
        result = compute_period_return(positions, prices, "2025-01-03", "2025-01-10")

        # Both stocks +10%, XBI +5%, hedged = 10% - 5% = 5%
        assert abs(result["gross_return"] - 0.10) < 1e-6
        assert abs(result["xbi_return"] - 0.05) < 1e-6
        assert abs(result["hedged_return"] - 0.05) < 1e-6

    def test_cost_deduction(self):
        positions = [
            {"ticker": "A", "weight_pct": 100.0, "bucket": "binary_91_180"},
        ]
        prices = {
            "A": {"2025-01-03": 10.0, "2025-01-10": 11.0},
            "XBI": {"2025-01-03": 100.0, "2025-01-10": 100.0},
        }
        # 50% turnover at 30bps
        result = compute_period_return(
            positions,
            prices,
            "2025-01-03",
            "2025-01-10",
            cost_bps=30.0,
            turnover_frac=0.5,
        )
        # gross = 10%, cost = 0.5 * 0.003 = 0.0015, net = 0.0985
        assert abs(result["net_return"] - 0.0985) < 1e-6


class TestAggregate:
    def test_basic_aggregation(self):
        results = [
            {"hedged_return": 0.01, "net_return": 0.02, "gross_return": 0.025, "xbi_return": 0.015, "turnover": 0.10},
            {"hedged_return": 0.02, "net_return": 0.03, "gross_return": 0.035, "xbi_return": 0.015, "turnover": 0.05},
        ]
        agg = aggregate(results)
        assert agg["n_periods"] == 2
        assert abs(agg["mean_hedged"] - 0.015) < 1e-6
        # Cumulative: (1.01)(1.02) - 1 = 0.0302
        assert abs(agg["cum_hedged"] - 0.0302) < 1e-6


class TestRunArm:
    def test_end_to_end_tiny(self, tmp_path):
        """Run arm on 3 dates (2 periods) with 2 tickers."""
        snap_root = tmp_path / "snaps"
        price_csv = _write_prices(
            tmp_path,
            [
                ("AAA", "2025-01-03", "10.0"),
                ("AAA", "2025-01-10", "11.0"),
                ("AAA", "2025-01-17", "12.0"),
                ("BBB", "2025-01-03", "20.0"),
                ("BBB", "2025-01-10", "21.0"),
                ("BBB", "2025-01-17", "22.0"),
                ("XBI", "2025-01-03", "100.0"),
                ("XBI", "2025-01-10", "102.0"),
                ("XBI", "2025-01-17", "104.0"),
            ],
        )

        rows = [
            _make_ranking_row("AAA", 1, 120),
            _make_ranking_row("BBB", 2, 130),
        ]
        _write_snapshot(snap_root, "2025-01-03", rows)
        _write_snapshot(snap_root, "2025-01-10", rows)
        _write_snapshot(snap_root, "2025-01-17", rows)

        prices = load_prices(price_csv)
        results = run_arm(
            "test",
            snap_root,
            ["2025-01-03", "2025-01-10", "2025-01-17"],
            prices,
            MINIMAL_POLICY,
            cost_bps=0.0,
        )

        assert len(results) == 2
        assert results[0]["entry_date"] == "2025-01-03"
        assert results[0]["exit_date"] == "2025-01-10"
        # Both tickers have positive returns
        assert results[0]["gross_return"] > 0
        assert results[1]["gross_return"] > 0

    def test_deterministic(self, tmp_path):
        """Same inputs produce same outputs."""
        snap_root = tmp_path / "snaps"
        price_csv = _write_prices(
            tmp_path,
            [
                ("AAA", "2025-01-03", "10.0"),
                ("AAA", "2025-01-10", "11.0"),
                ("XBI", "2025-01-03", "100.0"),
                ("XBI", "2025-01-10", "102.0"),
            ],
        )
        rows = [_make_ranking_row("AAA", 1, 120)]
        _write_snapshot(snap_root, "2025-01-03", rows)
        _write_snapshot(snap_root, "2025-01-10", rows)

        prices = load_prices(price_csv)
        dates = ["2025-01-03", "2025-01-10"]

        r1 = run_arm("test", snap_root, dates, prices, MINIMAL_POLICY)
        r2 = run_arm("test", snap_root, dates, prices, MINIMAL_POLICY)

        assert r1[0]["gross_return"] == r2[0]["gross_return"]
        assert r1[0]["hedged_return"] == r2[0]["hedged_return"]
