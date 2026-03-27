"""Tests for tools/build_shadow_monitor.py."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.build_shadow_monitor import (
    SCHEMA_VERSION,
    THRESHOLDS,
    build_shadow_monitor,
    classify_alerts,
    compute_cumulative,
    compute_drawdown_streak,
    format_monitor_md,
    load_performance,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
PERF_FIELDS = [
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


def _perf_row(
    date="2026-03-27",
    prior_date="2026-03-26",
    pnl="1000",
    pnl_pct="0.5",
    xbi_return="0.3",
    excess="0.2",
    n_held="50",
    sleeve_0_30="100",
    sleeve_31_90="200",
    sleeve_91_180="500",
    sleeve_lb="200",
):
    return {
        "schema_version": "live_shadow_perf.v1",
        "date": date,
        "prior_date": prior_date,
        "total_pnl": pnl,
        "pnl_pct": pnl_pct,
        "xbi_return_pct": xbi_return,
        "excess_vs_xbi_pct": excess,
        "n_held": n_held,
        "turnover": "5",
        "gap_risk_high_count": "1",
        "n_missing_price": "0",
        "sleeve_binary_0_30_pnl": sleeve_0_30,
        "sleeve_binary_31_90_pnl": sleeve_31_90,
        "sleeve_binary_91_180_pnl": sleeve_91_180,
        "sleeve_less_binary_pnl": sleeve_lb,
        "ruleset_id": "9f1f4587",
    }


def _write_perf(path: Path, rows: list):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=PERF_FIELDS)
        w.writeheader()
        w.writerows(rows)


def _write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


# ---------------------------------------------------------------------------
# load_performance
# ---------------------------------------------------------------------------
class TestLoadPerformance:
    def test_basic(self, tmp_path):
        path = tmp_path / "performance.csv"
        _write_perf(path, [_perf_row()])
        rows = load_performance(path)
        assert len(rows) == 1
        assert rows[0]["pnl_pct"] == 0.5

    def test_missing_file(self, tmp_path):
        rows = load_performance(tmp_path / "nope.csv")
        assert rows == []


# ---------------------------------------------------------------------------
# compute_drawdown_streak
# ---------------------------------------------------------------------------
class TestDrawdownStreak:
    def test_no_streak(self):
        rows = [{"pnl_pct": 1.0}, {"pnl_pct": 0.5}, {"pnl_pct": 0.2}]
        assert compute_drawdown_streak(rows) == 0

    def test_three_day_streak(self):
        rows = [{"pnl_pct": 1.0}, {"pnl_pct": -0.5}, {"pnl_pct": -0.3}, {"pnl_pct": -0.1}]
        assert compute_drawdown_streak(rows) == 3

    def test_broken_streak(self):
        rows = [{"pnl_pct": -1.0}, {"pnl_pct": 0.5}, {"pnl_pct": -0.3}]
        assert compute_drawdown_streak(rows) == 1

    def test_empty(self):
        assert compute_drawdown_streak([]) == 0


# ---------------------------------------------------------------------------
# compute_cumulative
# ---------------------------------------------------------------------------
class TestComputeCumulative:
    def test_basic(self):
        rows = [
            {
                "pnl_pct": 1.0,
                "excess_pct": 0.5,
                "sleeve_0_30": 100,
                "sleeve_31_90": 200,
                "sleeve_91_180": 300,
                "sleeve_less_binary": 400,
            },
            {
                "pnl_pct": -0.5,
                "excess_pct": -0.3,
                "sleeve_0_30": -50,
                "sleeve_31_90": -100,
                "sleeve_91_180": -200,
                "sleeve_less_binary": -150,
            },
        ]
        cum = compute_cumulative(rows)
        assert cum["total_pnl_pct"] == 0.5
        assert cum["total_excess_pct"] == 0.2
        assert cum["n_periods"] == 2
        assert cum["win_rate"] == 0.5

    def test_max_drawdown(self):
        rows = [
            {
                "pnl_pct": 2.0,
                "excess_pct": 0,
                "sleeve_0_30": 0,
                "sleeve_31_90": 0,
                "sleeve_91_180": 0,
                "sleeve_less_binary": 0,
            },
            {
                "pnl_pct": -3.0,
                "excess_pct": 0,
                "sleeve_0_30": 0,
                "sleeve_31_90": 0,
                "sleeve_91_180": 0,
                "sleeve_less_binary": 0,
            },
            {
                "pnl_pct": -1.0,
                "excess_pct": 0,
                "sleeve_0_30": 0,
                "sleeve_31_90": 0,
                "sleeve_91_180": 0,
                "sleeve_less_binary": 0,
            },
        ]
        cum = compute_cumulative(rows)
        assert cum["max_drawdown_pct"] == 4.0  # peak at +2, trough at -2


# ---------------------------------------------------------------------------
# classify_alerts
# ---------------------------------------------------------------------------
class TestClassifyAlerts:
    def test_drawdown_streak_warn(self):
        rows = [{"pnl_pct": -0.5}] * 3
        cum = compute_cumulative(
            [
                {
                    "pnl_pct": -0.5,
                    "excess_pct": 0,
                    "sleeve_0_30": 0,
                    "sleeve_31_90": 0,
                    "sleeve_91_180": 0,
                    "sleeve_less_binary": 0,
                }
            ]
            * 3
        )
        alerts = classify_alerts(rows, cum, None)
        codes = [a["code"] for a in alerts]
        assert "DRAWDOWN_STREAK" in codes

    def test_single_day_loss_alert(self):
        rows = [{"pnl_pct": -5.0}]
        cum = compute_cumulative(
            [
                {
                    "pnl_pct": -5.0,
                    "excess_pct": -5.0,
                    "sleeve_0_30": 0,
                    "sleeve_31_90": 0,
                    "sleeve_91_180": 0,
                    "sleeve_less_binary": 0,
                }
            ]
        )
        alerts = classify_alerts(rows, cum, None)
        levels = {a["code"]: a["level"] for a in alerts}
        assert levels.get("SINGLE_DAY_LOSS") == "ALERT"

    def test_excess_deterioration(self):
        rows = [{"pnl_pct": -1.0}]
        cum = {
            "total_pnl_pct": -4.0,
            "total_excess_pct": -4.0,
            "max_drawdown_pct": 4.0,
            "win_rate": 0,
            "n_periods": 4,
            "sleeve_totals": {},
        }
        alerts = classify_alerts(rows, cum, None)
        codes = [a["code"] for a in alerts]
        assert "EXCESS_DETERIORATION" in codes

    def test_sleeve_concentration(self):
        rows = [{"pnl_pct": -1.0}]
        cum = {
            "total_pnl_pct": -5.0,
            "total_excess_pct": -2.0,
            "max_drawdown_pct": 5.0,
            "win_rate": 0,
            "n_periods": 5,
            "sleeve_totals": {"0_30": -100, "31_90": -10, "91_180": -5000, "less_binary": -10},
        }
        alerts = classify_alerts(rows, cum, None)
        sleeve_alerts = [a for a in alerts if a["code"] == "SLEEVE_CONCENTRATION"]
        assert len(sleeve_alerts) >= 1
        assert "91_180" in sleeve_alerts[0]["detail"]

    def test_scorecard_fail(self):
        rows = [{"pnl_pct": 1.0}]
        cum = {
            "total_pnl_pct": 1.0,
            "total_excess_pct": 1.0,
            "max_drawdown_pct": 0,
            "win_rate": 1.0,
            "n_periods": 1,
            "sleeve_totals": {},
        }
        scorecard = {"checks": [{"name": "health_gate", "status": "FAIL", "detail": "phase2_health=FAIL"}]}
        alerts = classify_alerts(rows, cum, scorecard)
        codes = [a["code"] for a in alerts]
        assert "SCORECARD_FAIL" in codes

    def test_no_alerts_healthy(self):
        rows = [{"pnl_pct": 1.0}]
        cum = {
            "total_pnl_pct": 1.0,
            "total_excess_pct": 1.0,
            "max_drawdown_pct": 0.5,
            "win_rate": 1.0,
            "n_periods": 1,
            "sleeve_totals": {},
        }
        alerts = classify_alerts(rows, cum, None)
        assert len(alerts) == 0


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------
class TestBuildShadowMonitor:
    def test_basic(self, tmp_path):
        artifacts = tmp_path / "artifacts"
        perf_rows = [
            _perf_row(date="2026-03-25", pnl_pct="1.5", excess="0.8"),
            _perf_row(date="2026-03-26", pnl_pct="-2.5", excess="-1.0"),
            _perf_row(date="2026-03-27", pnl_pct="2.0", excess="1.2"),
        ]
        _write_perf(artifacts / "live_shadow" / "performance.csv", perf_rows)

        result = build_shadow_monitor(
            "2026-03-27",
            artifacts_dir=artifacts,
            snapshots_dir=tmp_path / "snapshots",
            price_csv=tmp_path / "prices.csv",
        )

        assert result["schema"] == SCHEMA_VERSION
        assert "error" not in result
        assert result["attention"] in ("LOW", "MEDIUM", "HIGH")
        assert result["cumulative"]["n_periods"] == 3

    def test_missing_perf(self, tmp_path):
        result = build_shadow_monitor(
            "2026-03-27",
            artifacts_dir=tmp_path / "artifacts",
        )
        assert "error" in result

    def test_writes_artifacts(self, tmp_path):
        artifacts = tmp_path / "artifacts"
        _write_perf(artifacts / "live_shadow" / "performance.csv", [_perf_row()])

        build_shadow_monitor("2026-03-27", artifacts_dir=artifacts, price_csv=tmp_path / "p.csv")

        assert (artifacts / "shadow_monitor" / "2026-03-27_monitor.json").exists()
        assert (artifacts / "shadow_monitor" / "2026-03-27_monitor.md").exists()


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------
class TestFormatMd:
    def test_basic(self):
        d = {
            "as_of_date": "2026-03-27",
            "attention": "MEDIUM",
            "generated_at": "2026-03-27T00:00:00Z",
            "latest": {"date": "2026-03-27", "pnl_pct": 2.0, "excess_pct": 1.0, "n_held": 50},
            "cumulative": {
                "total_pnl_pct": -4.76,
                "total_excess_pct": -3.64,
                "max_drawdown_pct": 7.14,
                "win_rate": 0.23,
                "n_periods": 22,
                "sleeve_totals": {"0_30": -1688, "31_90": 909, "91_180": -22422, "less_binary": -232},
            },
            "drawdown_streak": 0,
            "alerts": [{"level": "WARN", "code": "EXCESS_DETERIORATION", "detail": "-3.64% vs XBI"}],
            "noteworthy_positions": [],
            "recent_trend": [{"date": "2026-03-27", "pnl_pct": 2.0, "excess_pct": 1.0}],
            "scorecard_verdict": "HOLD",
            "thresholds": THRESHOLDS,
        }
        md = format_monitor_md(d)
        assert "Shadow Monitor" in md
        assert "MEDIUM" in md
        assert "EXCESS_DETERIORATION" in md
