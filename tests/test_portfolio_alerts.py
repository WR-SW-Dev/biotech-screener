"""Tests for portfolio_alerts.py."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.portfolio_alerts import (
    check_concentration,
    check_drawdown,
    check_gap_risk,
    check_gate_fail,
    check_turnover,
    fire_webhook_if_needed,
    run_portfolio_alerts,
    write_alerts_json,
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


def _write_positions(path: Path, as_of_date: str, positions: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "schema": "live_shadow_positions.v1",
        "as_of_date": as_of_date,
        "positions": positions,
        "summary": {"total_positions": len(positions)},
    }
    with open(path, "w") as f:
        json.dump(doc, f)


def _pos(ticker: str, dollars: float, gap_risk: str = "") -> dict:
    return {
        "ticker": ticker,
        "target_dollars": dollars,
        "bucket": "binary_91_180",
        "gap_risk": gap_risk,
        "tier": "A",
        "weight_pct": 1.0,
    }


def _write_perf_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=PERF_COLUMNS)
        w.writeheader()
        w.writerows(rows)


def _perf_row(date: str, pnl_pct: float, turnover: float = 0.05) -> dict:
    return {
        "schema_version": "v1",
        "date": date,
        "prior_date": "",
        "total_pnl": "0",
        "pnl_pct": str(pnl_pct),
        "xbi_return_pct": "0",
        "excess_vs_xbi_pct": "0",
        "n_held": "60",
        "turnover": str(turnover),
        "gap_risk_high_count": "0",
        "n_missing_price": "0",
        "sleeve_binary_0_30_pnl": "0",
        "sleeve_binary_31_90_pnl": "0",
        "sleeve_binary_91_180_pnl": "0",
        "sleeve_less_binary_pnl": "0",
        "ruleset_id": "test",
    }


# ---------------------------------------------------------------------------
# Gap risk
# ---------------------------------------------------------------------------


class TestCheckGapRisk:
    def test_new_gap_risk_high(self, tmp_path):
        pos_dir = tmp_path / "positions"
        _write_positions(
            pos_dir / "2026-03-07.json",
            "2026-03-07",
            [
                _pos("AAPL", 5000),
                _pos("VERA", 2000),
            ],
        )
        _write_positions(
            pos_dir / "2026-03-08.json",
            "2026-03-08",
            [
                _pos("AAPL", 5000),
                _pos("VERA", 2000, gap_risk="HIGH"),
            ],
        )
        alerts = check_gap_risk(pos_dir / "2026-03-08.json", pos_dir)
        assert len(alerts) == 1
        assert alerts[0]["type"] == "NEW_GAP_RISK_HIGH"
        assert "VERA" in alerts[0]["tickers"]

    def test_no_new_gap_risk(self, tmp_path):
        pos_dir = tmp_path / "positions"
        _write_positions(
            pos_dir / "2026-03-07.json",
            "2026-03-07",
            [
                _pos("VERA", 2000, gap_risk="HIGH"),
            ],
        )
        _write_positions(
            pos_dir / "2026-03-08.json",
            "2026-03-08",
            [
                _pos("VERA", 2000, gap_risk="HIGH"),
            ],
        )
        alerts = check_gap_risk(pos_dir / "2026-03-08.json", pos_dir)
        assert len(alerts) == 0


# ---------------------------------------------------------------------------
# Gate fail
# ---------------------------------------------------------------------------


class TestCheckGateFail:
    def test_detects_fail(self, tmp_path):
        snap = tmp_path / "snap"
        snap.mkdir()
        with open(snap / "run_manifest.json", "w") as f:
            json.dump({"overall_status": "FAIL", "gates": [{"name": "audit", "status": "FAIL"}]}, f)
        alerts = check_gate_fail(snap)
        assert len(alerts) == 1
        assert alerts[0]["type"] == "HARD_GATE_FAIL"
        assert alerts[0]["severity"] == "FAIL"

    def test_no_fail(self, tmp_path):
        snap = tmp_path / "snap"
        snap.mkdir()
        with open(snap / "run_manifest.json", "w") as f:
            json.dump({"overall_status": "PASS", "gates": []}, f)
        assert check_gate_fail(snap) == []

    def test_no_manifest(self, tmp_path):
        assert check_gate_fail(tmp_path / "nope") == []


# ---------------------------------------------------------------------------
# Concentration
# ---------------------------------------------------------------------------


class TestCheckConcentration:
    def test_detects_concentrated(self, tmp_path):
        pos_path = tmp_path / "pos.json"
        _write_positions(
            pos_path,
            "2026-03-08",
            [
                _pos("BIG", 6000),  # 60% of 10k total
                _pos("SML", 4000),
            ],
        )
        alerts = check_concentration(pos_path, max_name_pct=5.0)
        assert len(alerts) == 1
        assert "BIG" in alerts[0]["tickers"]

    def test_no_concentration(self, tmp_path):
        pos_path = tmp_path / "pos.json"
        _write_positions(
            pos_path,
            "2026-03-08",
            [
                _pos("A", 2500),
                _pos("B", 2500),
                _pos("C", 2500),
                _pos("D", 2500),
            ],
        )
        assert check_concentration(pos_path, max_name_pct=30.0) == []


# ---------------------------------------------------------------------------
# Drawdown
# ---------------------------------------------------------------------------


class TestCheckDrawdown:
    def test_detects_drawdown(self, tmp_path):
        perf = tmp_path / "perf.csv"
        _write_perf_csv(perf, [_perf_row("2026-03-08", -4.0)])
        alerts = check_drawdown(perf, threshold_pct=-3.0)
        assert len(alerts) == 1
        assert alerts[0]["type"] == "LARGE_DRAWDOWN"

    def test_no_drawdown(self, tmp_path):
        perf = tmp_path / "perf.csv"
        _write_perf_csv(perf, [_perf_row("2026-03-08", -1.0)])
        assert check_drawdown(perf, threshold_pct=-3.0) == []


# ---------------------------------------------------------------------------
# Turnover
# ---------------------------------------------------------------------------


class TestCheckTurnover:
    def test_detects_high_turnover(self, tmp_path):
        perf = tmp_path / "perf.csv"
        _write_perf_csv(perf, [_perf_row("2026-03-08", 0.0, turnover=0.35)])
        alerts = check_turnover(perf, threshold_pct=30.0)
        assert len(alerts) == 1
        assert alerts[0]["type"] == "HIGH_TURNOVER"

    def test_no_high_turnover(self, tmp_path):
        perf = tmp_path / "perf.csv"
        _write_perf_csv(perf, [_perf_row("2026-03-08", 0.0, turnover=0.10)])
        assert check_turnover(perf, threshold_pct=30.0) == []


# ---------------------------------------------------------------------------
# Alerts JSON
# ---------------------------------------------------------------------------


class TestWriteAlertsJSON:
    def test_writes_valid_json(self, tmp_path):
        alerts = [{"type": "TEST", "severity": "WARN", "detail": "test", "tickers": []}]
        path = write_alerts_json(alerts, "2026-03-08", tmp_path / "alerts.json")
        with open(path) as f:
            doc = json.load(f)
        assert doc["schema"] == "portfolio_alerts.v1"
        assert doc["alert_count"] == 1

    def test_empty_alerts(self, tmp_path):
        path = write_alerts_json([], "2026-03-08", tmp_path / "alerts.json")
        with open(path) as f:
            doc = json.load(f)
        assert doc["alert_count"] == 0


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------


class TestWebhook:
    def test_dry_run(self, capsys):
        alerts = [{"type": "TEST", "severity": "WARN", "detail": "test", "tickers": []}]
        fire_webhook_if_needed(alerts, "2026-03-08", "https://example.com", dry_run=True)
        captured = capsys.readouterr()
        assert "DRY RUN" in captured.out

    def test_no_alerts_skips(self):
        # Should not raise or POST
        fire_webhook_if_needed([], "2026-03-08", "https://example.com")


# ---------------------------------------------------------------------------
# End-to-end
# ---------------------------------------------------------------------------


class TestRunAlerts:
    def test_full_run(self, tmp_path):
        shadow = tmp_path / "shadow"
        snap_root = tmp_path / "snapshots"

        pos_dir = shadow / "positions"
        _write_positions(pos_dir / "2026-03-07.json", "2026-03-07", [_pos("AAPL", 5000)])
        _write_positions(
            pos_dir / "2026-03-08.json",
            "2026-03-08",
            [
                _pos("AAPL", 5000),
                _pos("VERA", 2000, gap_risk="HIGH"),
            ],
        )

        result = run_portfolio_alerts(
            "2026-03-08",
            shadow_root=shadow,
            snapshots_root=snap_root,
        )
        assert result["alert_count"] >= 1
        alert_path = Path(result["alert_path"])
        assert alert_path.is_file()
        with open(alert_path) as f:
            doc = json.load(f)
        assert doc["schema"] == "portfolio_alerts.v1"

    def test_no_alerts_clean_portfolio(self, tmp_path):
        shadow = tmp_path / "shadow"
        snap_root = tmp_path / "snapshots"

        pos_dir = shadow / "positions"
        # 25 positions at 400 each = 10k total, each 4% < 5% cap
        positions = [_pos(f"T{i:02d}", 400) for i in range(25)]
        _write_positions(pos_dir / "2026-03-08.json", "2026-03-08", positions)

        result = run_portfolio_alerts(
            "2026-03-08",
            shadow_root=shadow,
            snapshots_root=snap_root,
        )
        assert result["alert_count"] == 0

    def test_idempotent(self, tmp_path):
        shadow = tmp_path / "shadow"
        snap_root = tmp_path / "snapshots"
        pos_dir = shadow / "positions"
        _write_positions(pos_dir / "2026-03-08.json", "2026-03-08", [_pos("A", 5000)])

        run_portfolio_alerts("2026-03-08", shadow_root=shadow, snapshots_root=snap_root)
        result = run_portfolio_alerts("2026-03-08", shadow_root=shadow, snapshots_root=snap_root)
        # JSON is overwritten, not appended
        with open(result["alert_path"]) as f:
            doc = json.load(f)
        assert isinstance(doc["alerts"], list)
