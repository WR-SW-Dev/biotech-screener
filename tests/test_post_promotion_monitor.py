"""Tests for post-promotion monitor."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.post_promotion_monitor import PROMOTION_DATE, compute_monitor


def _write_positions(tmp_path: Path, as_of_date: str, positions: list) -> None:
    pos_dir = tmp_path / "positions"
    pos_dir.mkdir(parents=True, exist_ok=True)
    with open(pos_dir / f"{as_of_date}.json", "w") as f:
        json.dump({"positions": positions}, f)


def _write_perf_csv(tmp_path: Path, rows: list[dict]) -> None:
    perf_path = tmp_path / "performance.csv"
    with open(perf_path, "w") as f:
        for r in rows:
            # Format: schema,date,prior,pnl,$,pnl%,xbi%,excess%,n_held,turnover,...
            f.write(
                f"live_shadow_perf.v1,{r['date']},,"
                f"{r.get('pnl', 0)},{r.get('pnl_pct', 0)},{r.get('xbi_pct', 0)},"
                f"{r.get('excess', 0)},{r.get('n_held', 30)},{r.get('turnover', 0)},,\n"
            )


class TestComputeMonitor:
    def test_day_zero(self, tmp_path, monkeypatch):
        monkeypatch.setattr("tools.post_promotion_monitor.SHADOW_POSITIONS_DIR", tmp_path / "positions")
        monkeypatch.setattr("tools.post_promotion_monitor.SHADOW_PERF_CSV", tmp_path / "performance.csv")

        _write_positions(tmp_path, PROMOTION_DATE, [{"ticker": f"T{i}", "size_band": "EW"} for i in range(30)])
        _write_perf_csv(tmp_path, [])

        result = compute_monitor(PROMOTION_DATE)
        assert result["days_since_promotion"] == 0
        assert result["in_monitor_window"] is True
        assert result["n_positions"] == 30

    def test_regime_classification_bear(self, tmp_path, monkeypatch):
        monkeypatch.setattr("tools.post_promotion_monitor.SHADOW_POSITIONS_DIR", tmp_path / "positions")
        monkeypatch.setattr("tools.post_promotion_monitor.SHADOW_PERF_CSV", tmp_path / "performance.csv")

        _write_positions(tmp_path, "2026-04-15", [{"ticker": "A", "size_band": "EW"}])
        _write_perf_csv(
            tmp_path,
            [
                {"date": "2026-04-08", "pnl_pct": -1.0, "xbi_pct": -3.0, "excess": 2.0, "n_held": 30, "turnover": 0.1},
            ],
        )

        result = compute_monitor("2026-04-15")
        assert result["regime"] == "bear"

    def test_regime_classification_bull(self, tmp_path, monkeypatch):
        monkeypatch.setattr("tools.post_promotion_monitor.SHADOW_POSITIONS_DIR", tmp_path / "positions")
        monkeypatch.setattr("tools.post_promotion_monitor.SHADOW_PERF_CSV", tmp_path / "performance.csv")

        _write_positions(tmp_path, "2026-04-15", [{"ticker": "A", "size_band": "EW"}])
        _write_perf_csv(
            tmp_path,
            [
                {"date": "2026-04-08", "pnl_pct": 3.0, "xbi_pct": 5.0, "excess": -2.0, "n_held": 30, "turnover": 0.05},
            ],
        )

        result = compute_monitor("2026-04-15")
        assert result["regime"] == "bull"

    def test_excess_drawdown_alert(self, tmp_path, monkeypatch):
        monkeypatch.setattr("tools.post_promotion_monitor.SHADOW_POSITIONS_DIR", tmp_path / "positions")
        monkeypatch.setattr("tools.post_promotion_monitor.SHADOW_PERF_CSV", tmp_path / "performance.csv")

        _write_positions(tmp_path, "2026-04-15", [{"ticker": "A", "size_band": "EW"}])
        _write_perf_csv(
            tmp_path,
            [
                {"date": "2026-04-08", "pnl_pct": -4.0, "xbi_pct": 1.0, "excess": -6.0, "n_held": 30, "turnover": 0.1},
            ],
        )

        result = compute_monitor("2026-04-15")
        assert any("EXCESS_DRAWDOWN" in a for a in result["alerts"])

    def test_low_positions_alert(self, tmp_path, monkeypatch):
        monkeypatch.setattr("tools.post_promotion_monitor.SHADOW_POSITIONS_DIR", tmp_path / "positions")
        monkeypatch.setattr("tools.post_promotion_monitor.SHADOW_PERF_CSV", tmp_path / "performance.csv")

        _write_positions(tmp_path, "2026-04-15", [{"ticker": f"T{i}", "size_band": "EW"} for i in range(10)])
        _write_perf_csv(tmp_path, [])

        result = compute_monitor("2026-04-15")
        assert any("LOW_POSITIONS" in a for a in result["alerts"])

    def test_outside_monitor_window(self, tmp_path, monkeypatch):
        monkeypatch.setattr("tools.post_promotion_monitor.SHADOW_POSITIONS_DIR", tmp_path / "positions")
        monkeypatch.setattr("tools.post_promotion_monitor.SHADOW_PERF_CSV", tmp_path / "performance.csv")

        _write_positions(tmp_path, "2026-05-15", [{"ticker": "A", "size_band": "EW"}])
        _write_perf_csv(tmp_path, [])

        result = compute_monitor("2026-05-15")
        assert result["in_monitor_window"] is False
        assert result["days_since_promotion"] == 44

    def test_no_positions_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr("tools.post_promotion_monitor.SHADOW_POSITIONS_DIR", tmp_path / "positions")
        monkeypatch.setattr("tools.post_promotion_monitor.SHADOW_PERF_CSV", tmp_path / "performance.csv")

        result = compute_monitor("2026-04-15")
        assert result["n_positions"] == 0

    def test_cost_drag_computation(self, tmp_path, monkeypatch):
        monkeypatch.setattr("tools.post_promotion_monitor.SHADOW_POSITIONS_DIR", tmp_path / "positions")
        monkeypatch.setattr("tools.post_promotion_monitor.SHADOW_PERF_CSV", tmp_path / "performance.csv")

        _write_positions(tmp_path, "2026-04-15", [{"ticker": "A", "size_band": "EW"}])
        _write_perf_csv(
            tmp_path,
            [
                {"date": "2026-04-08", "pnl_pct": 1.0, "xbi_pct": 0.5, "excess": 0.5, "n_held": 30, "turnover": 0.15},
                {"date": "2026-04-15", "pnl_pct": 0.5, "xbi_pct": 0.3, "excess": 0.2, "n_held": 30, "turnover": 0.10},
            ],
        )

        result = compute_monitor("2026-04-15")
        perf = result["performance_since_promotion"]
        assert perf["total_turnover"] == 0.25
        assert perf["realized_cost_drag_bps"] > 0
