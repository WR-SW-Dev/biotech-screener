"""Tests for common/wake_robin_context.py."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from common.wake_robin_context import clear_cache, enrich_alert, enrich_ticker, format_context_line


def _write_rankings(snap_dir: Path, rows: list):
    snap_dir.mkdir(parents=True, exist_ok=True)
    with open(snap_dir / "rankings.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def _write_positions(path: Path, tickers: list):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"positions": [{"ticker": t, "bucket": "binary_91_180", "weight_pct": 3.0} for t in tickers]}, f)


class TestEnrichTicker:
    def test_basic(self, tmp_path):
        clear_cache()
        snaps = tmp_path / "snapshots"
        arts = tmp_path / "artifacts"
        _write_rankings(
            snaps / "2026-03-27",
            [
                {
                    "ticker": "TEST",
                    "tier_dev": "A",
                    "actionable_rank": "5",
                    "catalyst_days": "10",
                    "catalyst_family": "CLINICAL",
                    "is_hard_catalyst": "1",
                    "opt_iv_regime": "NORMAL",
                    "opt_rr_25d": "-0.05",
                    "actual_implied_move_pctile": "0.75",
                },
            ],
        )
        _write_positions(arts / "live_shadow" / "positions" / "2026-03-27.json", ["TEST"])

        ctx = enrich_ticker("TEST", "2026-03-27", snapshots_dir=snaps, artifacts_dir=arts)
        assert ctx["ticker"] == "TEST"
        assert ctx["screening"]["tier_dev"] == "A"
        assert ctx["portfolio"]["in_shadow"] is True
        assert ctx["portfolio"]["bucket"] == "binary_91_180"

    def test_not_in_portfolio(self, tmp_path):
        clear_cache()
        snaps = tmp_path / "snapshots"
        arts = tmp_path / "artifacts"
        _write_rankings(
            snaps / "2026-03-27",
            [
                {"ticker": "OUT", "tier_dev": "C", "actionable_rank": "80"},
            ],
        )

        ctx = enrich_ticker("OUT", "2026-03-27", snapshots_dir=snaps, artifacts_dir=arts)
        assert ctx["portfolio"]["in_shadow"] is False

    def test_unknown_ticker(self, tmp_path):
        clear_cache()
        snaps = tmp_path / "snapshots"
        arts = tmp_path / "artifacts"
        _write_rankings(snaps / "2026-03-27", [{"ticker": "AAA"}])

        ctx = enrich_ticker("ZZZ", "2026-03-27", snapshots_dir=snaps, artifacts_dir=arts)
        assert ctx["screening"]["ticker"] == ""  # not found


class TestFormatContextLine:
    def test_full_context(self):
        ctx = {
            "ticker": "PVLA",
            "screening": {
                "tier_dev": "A",
                "actionable_rank": "18",
                "catalyst_days": "4",
                "catalyst_family": "CLINICAL",
                "is_hard_catalyst": "1",
                "opt_iv_regime": "ELEVATED",
                "opt_rr_25d": "-0.21",
                "actual_implied_move_pctile": "0.84",
            },
            "portfolio": {
                "in_shadow": True,
                "in_trade_plan": False,
                "bucket": "binary_0_30",
                "weight_pct": 0.5,
                "effective_family": "CLINICAL",
            },
        }
        line = format_context_line(ctx)
        assert "PVLA" in line
        assert "A" in line
        assert "Rank 18" in line
        assert "4d CLINICAL (hard)" in line
        assert "shadow:YES" in line


class TestEnrichAlert:
    def test_adds_context(self, tmp_path):
        clear_cache()
        snaps = tmp_path / "snapshots"
        arts = tmp_path / "artifacts"
        _write_rankings(
            snaps / "2026-03-27",
            [
                {"ticker": "ALT", "tier_dev": "B", "actionable_rank": "30"},
            ],
        )

        alert = {"ticker": "ALT", "code": "STOCK_MOVE_UP", "return_1d_pct": 8.5}
        enriched = enrich_alert(alert, "2026-03-27", snapshots_dir=snaps, artifacts_dir=arts)
        assert "context" in enriched
        assert "context_line" in enriched
        assert "ALT" in enriched["context_line"]
