"""Tests for backfill_shadow_history.py."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.backfill_shadow_history import backfill_shadow_history, dates_in_performance_csv, discover_snapshot_dates

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

RANKINGS_HEADER = [
    "ticker",
    "eligible",
    "actionable_rank",
    "tier_any",
    "size_band",
    "catalyst_days",
    "catalyst_mode",
    "mom_state",
    "de_beta_xbi_60d_source",
]


def _write_snapshot(snap_dir: Path, date: str, tickers: list[str]) -> None:
    """Create a minimal snapshot with rankings.csv + metadata.json."""
    d = snap_dir / date
    d.mkdir(parents=True, exist_ok=True)
    # rankings.csv
    with open(d / "rankings.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=RANKINGS_HEADER)
        w.writeheader()
        for i, t in enumerate(tickers):
            w.writerow(
                {
                    "ticker": t,
                    "eligible": "1",
                    "actionable_rank": str(i + 1),
                    "tier_any": "A",
                    "size_band": "M",
                    "catalyst_days": "100",
                    "catalyst_mode": "specific_days",
                    "mom_state": "tailwind",
                    "de_beta_xbi_60d_source": "hydrated",
                }
            )
    # metadata.json
    with open(d / "metadata.json", "w") as f:
        json.dump({"as_of_date": date, "ruleset_id": "test123"}, f)


def _write_price_csv(path: Path, dates: list[str], tickers: list[str]) -> None:
    """Write a minimal price_history.csv."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "ticker", "close"])
        w.writeheader()
        for d in dates:
            for t in tickers:
                w.writerow({"date": d, "ticker": t, "close": "100.0"})
            w.writerow({"date": d, "ticker": "XBI", "close": "80.0"})


def _write_policy(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(
            {
                "schema": "portfolio_policy.v1",
                "account_usd": 100000,
                "rebalance_day": "FRIDAY",
                "bucket_targets": {"binary_91_180": 1.0, "binary_31_90": 0, "binary_0_30": 0, "less_binary": 0},
                "bucket_top_k": {"binary_91_180": 5, "binary_31_90": 0, "binary_0_30": 0, "less_binary": 0},
                "bucket_name_caps": {"binary_91_180": 25.0},
                "gap_risk": {"high_days": 7, "high_cap_pct": 0.5},
            },
            f,
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDiscoverDates:
    def test_finds_dates_in_range(self, tmp_path):
        snap_root = tmp_path / "snapshots"
        _write_snapshot(snap_root, "2026-03-01", ["AAPL"])
        _write_snapshot(snap_root, "2026-03-03", ["AAPL"])
        _write_snapshot(snap_root, "2026-03-05", ["AAPL"])
        result = discover_snapshot_dates(snap_root, "2026-03-01", "2026-03-04")
        assert result == ["2026-03-01", "2026-03-03"]

    def test_excludes_dirs_without_rankings(self, tmp_path):
        snap_root = tmp_path / "snapshots"
        (snap_root / "2026-03-01").mkdir(parents=True)
        _write_snapshot(snap_root, "2026-03-02", ["AAPL"])
        result = discover_snapshot_dates(snap_root, "2026-03-01", "2026-03-05")
        assert result == ["2026-03-02"]

    def test_empty_when_no_snapshots(self, tmp_path):
        assert discover_snapshot_dates(tmp_path / "nope", "2026-03-01", "2026-03-05") == []


class TestDatesInPerfCSV:
    def test_reads_existing_dates(self, tmp_path):
        perf = tmp_path / "performance.csv"
        with open(perf, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["date", "pnl_pct"])
            w.writeheader()
            w.writerow({"date": "2026-03-01", "pnl_pct": "0.5"})
            w.writerow({"date": "2026-03-02", "pnl_pct": "-0.3"})
        assert dates_in_performance_csv(perf) == {"2026-03-01", "2026-03-02"}

    def test_empty_when_no_file(self, tmp_path):
        assert dates_in_performance_csv(tmp_path / "nope.csv") == set()


class TestBackfillChronological:
    def test_builds_positions_in_order(self, tmp_path):
        snap_root = tmp_path / "snapshots"
        shadow_root = tmp_path / "shadow"
        price_path = tmp_path / "prices.csv"
        policy_path = tmp_path / "policy.json"
        tickers = ["AAA", "BBB", "CCC"]
        dates = ["2026-03-03", "2026-03-04", "2026-03-05"]
        for d in dates:
            _write_snapshot(snap_root, d, tickers)
        _write_price_csv(price_path, dates, tickers)
        _write_policy(policy_path)

        result = backfill_shadow_history(
            "2026-03-03",
            "2026-03-05",
            snapshots_root=snap_root,
            shadow_root=shadow_root,
            price_path=price_path,
            policy_path=policy_path,
        )
        assert result["n_dates_processed"] == 3
        assert result["n_skipped"] == 0
        assert result["errors"] == []

        pos_dir = shadow_root / "positions"
        for d in dates:
            assert (pos_dir / f"{d}.json").is_file()

        # Performance CSV should have entries for 2nd and 3rd dates (first has no prior)
        perf_csv = shadow_root / "performance.csv"
        assert perf_csv.is_file()
        perf_dates = dates_in_performance_csv(perf_csv)
        assert "2026-03-03" not in perf_dates  # first date, no prior
        assert "2026-03-04" in perf_dates
        assert "2026-03-05" in perf_dates


class TestBackfillIdempotency:
    def test_no_duplicate_rows(self, tmp_path):
        snap_root = tmp_path / "snapshots"
        shadow_root = tmp_path / "shadow"
        price_path = tmp_path / "prices.csv"
        policy_path = tmp_path / "policy.json"
        tickers = ["AAA"]
        dates = ["2026-03-03", "2026-03-04"]
        for d in dates:
            _write_snapshot(snap_root, d, tickers)
        _write_price_csv(price_path, dates, tickers)
        _write_policy(policy_path)

        kwargs = dict(
            snapshots_root=snap_root,
            shadow_root=shadow_root,
            price_path=price_path,
            policy_path=policy_path,
        )
        backfill_shadow_history("2026-03-03", "2026-03-04", **kwargs)
        # Run again without force — should skip
        result = backfill_shadow_history("2026-03-03", "2026-03-04", **kwargs)
        assert result["n_skipped"] == 2
        assert result["n_dates_processed"] == 0

        # Verify no duplicate rows in performance.csv
        perf_csv = shadow_root / "performance.csv"
        with open(perf_csv) as f:
            rows = list(csv.DictReader(f))
        date_counts = {}
        for r in rows:
            d = r["date"]
            date_counts[d] = date_counts.get(d, 0) + 1
        for d, count in date_counts.items():
            assert count == 1, f"Duplicate perf row for {d}"


class TestBackfillForce:
    def test_force_overwrites(self, tmp_path):
        snap_root = tmp_path / "snapshots"
        shadow_root = tmp_path / "shadow"
        price_path = tmp_path / "prices.csv"
        policy_path = tmp_path / "policy.json"
        tickers = ["AAA"]
        dates = ["2026-03-03", "2026-03-04"]
        for d in dates:
            _write_snapshot(snap_root, d, tickers)
        _write_price_csv(price_path, dates, tickers)
        _write_policy(policy_path)

        kwargs = dict(
            snapshots_root=snap_root,
            shadow_root=shadow_root,
            price_path=price_path,
            policy_path=policy_path,
        )
        backfill_shadow_history("2026-03-03", "2026-03-04", **kwargs)
        result = backfill_shadow_history("2026-03-03", "2026-03-04", force=True, **kwargs)
        assert result["n_dates_processed"] == 2
        assert result["n_skipped"] == 0


class TestBackfillTradesOnFriday:
    def test_trade_packet_on_friday(self, tmp_path):
        snap_root = tmp_path / "snapshots"
        shadow_root = tmp_path / "shadow"
        price_path = tmp_path / "prices.csv"
        policy_path = tmp_path / "policy.json"
        tickers = ["AAA", "BBB"]
        # 2026-03-06 is a Friday
        dates = ["2026-03-05", "2026-03-06"]
        for d in dates:
            _write_snapshot(snap_root, d, tickers)
        _write_price_csv(price_path, dates, tickers)
        _write_policy(policy_path)

        result = backfill_shadow_history(
            "2026-03-05",
            "2026-03-06",
            snapshots_root=snap_root,
            shadow_root=shadow_root,
            price_path=price_path,
            policy_path=policy_path,
        )
        assert result["n_trade_days"] == 1


class TestBackfillGaps:
    def test_handles_missing_dates(self, tmp_path):
        snap_root = tmp_path / "snapshots"
        shadow_root = tmp_path / "shadow"
        price_path = tmp_path / "prices.csv"
        policy_path = tmp_path / "policy.json"
        tickers = ["AAA"]
        # Only 03-01 and 03-03 exist (gap on 03-02)
        for d in ["2026-03-01", "2026-03-03"]:
            _write_snapshot(snap_root, d, tickers)
        _write_price_csv(price_path, ["2026-03-01", "2026-03-02", "2026-03-03"], tickers)
        _write_policy(policy_path)

        result = backfill_shadow_history(
            "2026-03-01",
            "2026-03-03",
            snapshots_root=snap_root,
            shadow_root=shadow_root,
            price_path=price_path,
            policy_path=policy_path,
        )
        assert result["n_dates_processed"] == 2
        assert result["errors"] == []
