"""Tests for tools/build_options_chartbook.py."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.build_options_chartbook import SCHEMA_VERSION, _derive_flags, _svg_hbar, _svg_scatter, build_watchlist

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ranking_row(
    ticker="TEST",
    opt_has_data="1",
    opt_use_for_judgment="YES",
    opt_liquidity_ok="1",
    opt_atm_iv="0.50",
    opt_term_slope="0.05",
    opt_put_call_skew="0.02",
    opt_rr_25d="0.03",
    opt_iv_regime="NORMAL",
    opt_event_premium="NO",
    is_hard_catalyst="1",
    catalyst_days="15",
    catalyst_bucket="build_window",
    catalyst_family="CLINICAL",
    tier_dev="A",
    actionable_rank="10",
    implied_event_move="0.25",
):
    return {
        "ticker": ticker,
        "opt_has_data": opt_has_data,
        "opt_use_for_judgment": opt_use_for_judgment,
        "opt_liquidity_ok": opt_liquidity_ok,
        "opt_atm_iv": opt_atm_iv,
        "opt_front_iv": opt_atm_iv,
        "opt_back_iv": str(float(opt_atm_iv) * 0.9) if opt_atm_iv else "",
        "opt_term_slope": opt_term_slope,
        "opt_put_call_skew": opt_put_call_skew,
        "opt_rr_25d": opt_rr_25d,
        "opt_iv_regime": opt_iv_regime,
        "opt_event_premium": opt_event_premium,
        "is_hard_catalyst": is_hard_catalyst,
        "catalyst_days": catalyst_days,
        "catalyst_bucket": catalyst_bucket,
        "catalyst_family": catalyst_family,
        "tier_dev": tier_dev,
        "actionable_rank": actionable_rank,
        "implied_event_move": implied_event_move,
    }


# ---------------------------------------------------------------------------
# _derive_flags
# ---------------------------------------------------------------------------


class TestDeriveFlags:
    def test_event_premium(self):
        row = {"opt_event_premium": "YES"}
        assert "EVENT_PREMIUM" in _derive_flags(row)

    def test_extreme_skew(self):
        row = {"opt_rr_25d": 0.20}
        assert "EXTREME_SKEW" in _derive_flags(row)

    def test_deep_backwardation(self):
        row = {"opt_term_slope": -0.25}
        assert "DEEP_BACKWARDATION" in _derive_flags(row)

    def test_no_flags_normal(self):
        row = {
            "opt_event_premium": "NO",
            "opt_term_slope": 0.05,
            "opt_rr_25d": 0.03,
            "opt_put_call_skew": 0.01,
        }
        assert _derive_flags(row) == []

    def test_nan_handling(self):
        row = {"opt_rr_25d": float("nan"), "opt_term_slope": ""}
        assert _derive_flags(row) == []


# ---------------------------------------------------------------------------
# build_watchlist
# ---------------------------------------------------------------------------


class TestBuildWatchlist:
    def test_hard_catalyst_included(self):
        rankings = [_ranking_row(ticker="PVLA", is_hard_catalyst="1")]
        eligible, suppressed = build_watchlist(rankings, None, set(), set(), set())
        assert len(eligible) == 1
        assert eligible[0]["ticker"] == "PVLA"

    def test_no_data_suppressed(self):
        rankings = [_ranking_row(ticker="PVLA", opt_has_data="0")]
        eligible, suppressed = build_watchlist(rankings, None, set(), set(), set())
        assert len(eligible) == 0
        assert len(suppressed) == 1
        assert suppressed[0]["reason"] == "no_options_data"

    def test_illiquid_suppressed(self):
        rankings = [
            _ranking_row(
                ticker="PVLA",
                opt_use_for_judgment="NO",
                opt_liquidity_ok="0",
            )
        ]
        eligible, suppressed = build_watchlist(rankings, None, set(), set(), set())
        assert len(eligible) == 0
        assert len(suppressed) == 1
        assert "illiquid" in suppressed[0]["reason"]

    def test_trade_plan_ticker_included(self):
        rankings = [
            _ranking_row(
                ticker="AAPL",
                is_hard_catalyst="0",
                tier_dev="C",
                actionable_rank="200",
            )
        ]
        eligible, _ = build_watchlist(rankings, None, {"AAPL"}, set(), set())
        assert len(eligible) == 1

    def test_shadow_ticker_included(self):
        rankings = [
            _ranking_row(
                ticker="AAPL",
                is_hard_catalyst="0",
                tier_dev="C",
                actionable_rank="200",
            )
        ]
        eligible, _ = build_watchlist(rankings, None, set(), {"AAPL"}, set())
        assert len(eligible) == 1
        assert eligible[0]["in_shadow"]

    def test_options_watch_drives_universe(self):
        """When options_watch exists, it drives the universe."""
        rankings = [
            _ranking_row(ticker="PVLA"),
            _ranking_row(ticker="BIIB"),
        ]
        watch = {
            "rows": [{"ticker": "PVLA", "flags": ["EVENT_PREMIUM"], "priority_score": 2, "why": "test"}],
            "suppressed": [],
        }
        eligible, _ = build_watchlist(rankings, watch, set(), set(), set())
        tickers = [r["ticker"] for r in eligible]
        assert "PVLA" in tickers
        assert "BIIB" not in tickers

    def test_enriched_row_fields(self):
        rankings = [_ranking_row(ticker="PVLA")]
        eligible, _ = build_watchlist(rankings, None, {"PVLA"}, {"PVLA"}, set())
        r = eligible[0]
        assert r["in_trade_plan"]
        assert r["in_shadow"]
        assert not r["in_review_queue"]
        assert r["opt_atm_iv"] == 0.50
        assert r["is_hard_catalyst"]

    def test_sort_order(self):
        """Higher priority score + hard catalyst comes first."""
        rankings = [
            _ranking_row(ticker="LOW", is_hard_catalyst="0", opt_event_premium="NO", actionable_rank="50"),
            _ranking_row(
                ticker="HIGH",
                is_hard_catalyst="1",
                opt_event_premium="YES",
                opt_rr_25d="0.30",
                opt_term_slope="-0.25",
                actionable_rank="5",
            ),
        ]
        eligible, _ = build_watchlist(rankings, None, set(), set(), set())
        assert eligible[0]["ticker"] == "HIGH"


# ---------------------------------------------------------------------------
# SVG generators
# ---------------------------------------------------------------------------


class TestSvgCharts:
    def test_hbar_basic(self):
        data = [("PVLA", 0.5), ("BIIB", -0.3)]
        svg = _svg_hbar(data, "Test Chart")
        assert "<svg" in svg
        assert "PVLA" in svg
        assert "BIIB" in svg
        assert "<rect" in svg

    def test_hbar_empty(self):
        result = _svg_hbar([], "Empty Chart")
        assert "No data" in result

    def test_scatter_basic(self):
        data = [("PVLA", 10.0, 0.8, 2, True), ("BIIB", 30.0, 0.5, 1, False)]
        svg = _svg_scatter(data, "Test Scatter", "X", "Y")
        assert "<svg" in svg
        assert "<circle" in svg

    def test_scatter_empty(self):
        result = _svg_scatter([], "Empty Scatter", "X", "Y")
        assert "No data" in result


# ---------------------------------------------------------------------------
# Integration: build_chartbook with temp data
# ---------------------------------------------------------------------------


class TestBuildChartbook:
    def _write_rankings(self, snap_dir: Path, rows: list):
        snap_dir.mkdir(parents=True, exist_ok=True)
        csv_path = snap_dir / "rankings.csv"
        if not rows:
            return
        fieldnames = list(rows[0].keys())
        with open(csv_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(rows)

    def test_full_build(self, tmp_path, monkeypatch):
        from tools import build_options_chartbook as mod

        monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(mod, "SNAPSHOT_DIR", tmp_path / "data" / "snapshots")
        monkeypatch.setattr(mod, "OUT_DIR", tmp_path / "artifacts" / "options_chartbook")

        snap_dir = tmp_path / "data" / "snapshots" / "2026-03-26"
        self._write_rankings(
            snap_dir,
            [
                _ranking_row(ticker="PVLA", opt_event_premium="YES", opt_rr_25d="0.25", opt_term_slope="-0.15"),
                _ranking_row(ticker="BIIB", catalyst_days="30", opt_atm_iv="0.45"),
                _ranking_row(ticker="NODATA", opt_has_data="0"),
            ],
        )

        # Write minimal diagnostics summary
        diag_summary = {
            "schema": "options_diagnostics_summary.v2",
            "coverage": {"n_universe": 3, "n_with_options_data": 2, "coverage_pct": 66.7, "has_credentials": True},
            "flag_distributions": {"iv_regime": {"NORMAL": 2}},
        }
        with open(snap_dir / "options_diagnostics_summary.json", "w") as f:
            json.dump(diag_summary, f)

        result = mod.build_chartbook("2026-03-26", snapshots_dir=tmp_path / "data" / "snapshots")

        assert "error" not in result
        assert result["schema"] == SCHEMA_VERSION
        assert result["scoreboard"]["watchlist_size"] == 2
        assert result["scoreboard"]["n_suppressed"] >= 1  # NODATA

        # Check HTML written
        html_path = Path(result["_html_path"])
        assert html_path.exists()
        html = html_path.read_text()
        assert "PVLA" in html
        assert "BIIB" in html
        assert "Cover / Scoreboard" in html
        assert "Suppressed / Excluded" in html

        # Check JSON written
        json_path = Path(result["_json_path"])
        assert json_path.exists()

    def test_missing_snapshot(self, tmp_path, monkeypatch):
        from tools import build_options_chartbook as mod

        monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(mod, "SNAPSHOT_DIR", tmp_path / "data" / "snapshots")

        result = mod.build_chartbook("2099-01-01", snapshots_dir=tmp_path / "data" / "snapshots")
        assert "error" in result

    def test_no_rankings(self, tmp_path, monkeypatch):
        from tools import build_options_chartbook as mod

        monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(mod, "SNAPSHOT_DIR", tmp_path / "data" / "snapshots")

        snap_dir = tmp_path / "data" / "snapshots" / "2026-03-26"
        snap_dir.mkdir(parents=True)

        result = mod.build_chartbook("2026-03-26", snapshots_dir=tmp_path / "data" / "snapshots")
        assert "error" in result
