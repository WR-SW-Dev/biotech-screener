"""Tests for build_portfolio_report.py."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.build_portfolio_report import (
    build_portfolio_report,
    compute_portfolio_metrics,
    load_fill_quality,
    load_performance_history,
)

PERF_COLUMNS = [
    "schema_version",
    "date",
    "prior_date",
    "total_pnl",
    "pnl_pct",
    "xbi_return_pct",
    "excess_vs_xbi_pct",
    "n_held",
    "turnover",
    "gap_risk_high_count",
    "n_missing_price",
    "sleeve_binary_0_30_pnl",
    "sleeve_binary_31_90_pnl",
    "sleeve_binary_91_180_pnl",
    "sleeve_less_binary_pnl",
    "ruleset_id",
]


def _write_perf_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=PERF_COLUMNS)
        w.writeheader()
        w.writerows(rows)


def _perf_row(date: str, pnl_pct: float, xbi_pct: float = 0.0, total_pnl: float = 0.0, turnover: float = 0.05) -> dict:
    return {
        "schema_version": "live_shadow_perf.v1",
        "date": date,
        "prior_date": "",
        "total_pnl": str(total_pnl),
        "pnl_pct": str(pnl_pct),
        "xbi_return_pct": str(xbi_pct),
        "excess_vs_xbi_pct": str(pnl_pct - xbi_pct),
        "n_held": "60",
        "turnover": str(turnover),
        "gap_risk_high_count": "0",
        "n_missing_price": "0",
        "sleeve_binary_0_30_pnl": "0",
        "sleeve_binary_31_90_pnl": "0",
        "sleeve_binary_91_180_pnl": str(total_pnl),
        "sleeve_less_binary_pnl": "0",
        "ruleset_id": "test",
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLoadPerformance:
    def test_loads_rows(self, tmp_path):
        perf = tmp_path / "performance.csv"
        _write_perf_csv(perf, [_perf_row("2026-03-04", 1.5, 0.5, 750)])
        rows = load_performance_history(perf)
        assert len(rows) == 1
        assert rows[0]["pnl_pct"] == 1.5
        assert rows[0]["date"] == "2026-03-04"

    def test_empty_when_no_file(self, tmp_path):
        assert load_performance_history(tmp_path / "nope.csv") == []


class TestComputeMetrics:
    def test_cumulative_return(self):
        rows = [
            {
                "date": "d1",
                "pnl_pct": 2.0,
                "xbi_return_pct": 1.0,
                "total_pnl": 1000,
                "turnover": 0.05,
                "excess_vs_xbi_pct": 1.0,
                "sleeve_binary_0_30_pnl": 0,
                "sleeve_binary_31_90_pnl": 0,
                "sleeve_binary_91_180_pnl": 1000,
                "sleeve_less_binary_pnl": 0,
            },
            {
                "date": "d2",
                "pnl_pct": -1.0,
                "xbi_return_pct": -0.5,
                "total_pnl": -500,
                "turnover": 0.03,
                "excess_vs_xbi_pct": -0.5,
                "sleeve_binary_0_30_pnl": 0,
                "sleeve_binary_31_90_pnl": 0,
                "sleeve_binary_91_180_pnl": -500,
                "sleeve_less_binary_pnl": 0,
            },
        ]
        m = compute_portfolio_metrics(rows)
        # (1.02 * 0.99 - 1) * 100 = 0.98%
        assert abs(m["cumulative_return_pct"] - 0.98) < 0.01
        assert m["n_periods"] == 2
        assert m["win_rate"] == 0.5
        assert m["total_pnl_usd"] == 500.0

    def test_zero_periods(self):
        m = compute_portfolio_metrics([])
        assert m["n_periods"] == 0
        assert m["cumulative_return_pct"] == 0.0
        assert m["sharpe_ratio"] == 0.0

    def test_sharpe_no_variance(self):
        rows = [
            {
                "date": "d1",
                "pnl_pct": 0.0,
                "xbi_return_pct": 0.0,
                "total_pnl": 0,
                "turnover": 0,
                "excess_vs_xbi_pct": 0.0,
                "sleeve_binary_0_30_pnl": 0,
                "sleeve_binary_31_90_pnl": 0,
                "sleeve_binary_91_180_pnl": 0,
                "sleeve_less_binary_pnl": 0,
            },
            {
                "date": "d2",
                "pnl_pct": 0.0,
                "xbi_return_pct": 0.0,
                "total_pnl": 0,
                "turnover": 0,
                "excess_vs_xbi_pct": 0.0,
                "sleeve_binary_0_30_pnl": 0,
                "sleeve_binary_31_90_pnl": 0,
                "sleeve_binary_91_180_pnl": 0,
                "sleeve_less_binary_pnl": 0,
            },
        ]
        m = compute_portfolio_metrics(rows)
        assert m["sharpe_ratio"] == 0.0

    def test_max_drawdown(self):
        # Up 5%, then down 3% from peak
        rows = [
            {
                "date": "d1",
                "pnl_pct": 5.0,
                "xbi_return_pct": 0,
                "total_pnl": 2500,
                "turnover": 0,
                "excess_vs_xbi_pct": 5.0,
                "sleeve_binary_0_30_pnl": 0,
                "sleeve_binary_31_90_pnl": 0,
                "sleeve_binary_91_180_pnl": 2500,
                "sleeve_less_binary_pnl": 0,
            },
            {
                "date": "d2",
                "pnl_pct": -3.0,
                "xbi_return_pct": 0,
                "total_pnl": -1500,
                "turnover": 0,
                "excess_vs_xbi_pct": -3.0,
                "sleeve_binary_0_30_pnl": 0,
                "sleeve_binary_31_90_pnl": 0,
                "sleeve_binary_91_180_pnl": -1500,
                "sleeve_less_binary_pnl": 0,
            },
        ]
        m = compute_portfolio_metrics(rows)
        # Peak = 1.05, trough = 1.05 * 0.97 = 1.0185
        # DD = (1.05 - 1.0185) / 1.05 = 3.0%
        assert abs(m["max_drawdown_pct"] - 3.0) < 0.1

    def test_sleeve_attribution(self):
        rows = [
            {
                "date": "d1",
                "pnl_pct": 1,
                "xbi_return_pct": 0,
                "total_pnl": 500,
                "turnover": 0,
                "excess_vs_xbi_pct": 1,
                "sleeve_binary_0_30_pnl": 100,
                "sleeve_binary_31_90_pnl": 150,
                "sleeve_binary_91_180_pnl": 200,
                "sleeve_less_binary_pnl": 50,
            },
        ]
        m = compute_portfolio_metrics(rows)
        assert m["sleeve_attribution"]["binary_0_30"] == 100.0
        assert m["sleeve_attribution"]["binary_91_180"] == 200.0


class TestFillQuality:
    def test_loads_fill_quality(self, tmp_path):
        trades = tmp_path / "trades"
        fills_dir = trades / "2026-03-06"
        fills_dir.mkdir(parents=True)
        with open(fills_dir / "fills.csv", "w", newline="") as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    "ticker",
                    "action",
                    "target_usd",
                    "fill_price",
                    "fill_shares",
                    "fill_usd",
                    "slippage_bps",
                    "fill_date",
                    "status",
                ],
            )
            w.writeheader()
            w.writerow(
                {
                    "ticker": "AAPL",
                    "action": "BUY",
                    "target_usd": "5000",
                    "fill_price": "150",
                    "fill_shares": "33",
                    "fill_usd": "4950",
                    "slippage_bps": "-100",
                    "fill_date": "2026-03-06",
                    "status": "FILLED",
                }
            )

        q = load_fill_quality(trades)
        assert q is not None
        assert q["total_fills"] == 1
        assert q["fill_rate"] == 1.0

    def test_no_fills(self, tmp_path):
        assert load_fill_quality(tmp_path / "nope") is None


class TestReportOutput:
    def test_writes_markdown_and_json(self, tmp_path):
        shadow = tmp_path / "shadow"
        perf = shadow / "performance.csv"
        _write_perf_csv(
            perf,
            [
                _perf_row("2026-03-04", 1.5, 0.5, 750),
                _perf_row("2026-03-05", -0.5, -0.3, -250),
            ],
        )

        build_portfolio_report(shadow)
        assert (shadow / "portfolio_report.md").is_file()
        assert (shadow / "portfolio_metrics.json").is_file()

        text = (shadow / "portfolio_report.md").read_text()
        assert "Shadow Portfolio Report" in text
        assert "Cumulative" in text

        with open(shadow / "portfolio_metrics.json") as f:
            doc = json.load(f)
        assert doc["schema"] == "portfolio_metrics.v1"
        assert doc["n_periods"] == 2

    def test_empty_report(self, tmp_path):
        shadow = tmp_path / "shadow"
        shadow.mkdir(parents=True)
        build_portfolio_report(shadow)
        text = (shadow / "portfolio_report.md").read_text()
        assert "Insufficient data" in text
