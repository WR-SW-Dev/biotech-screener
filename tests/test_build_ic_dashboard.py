"""Tests for tools/build_ic_dashboard.py."""

from __future__ import annotations

import csv
import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.build_ic_dashboard import SCHEMA_VERSION, build_ic_dashboard, compute_ic, format_dashboard_md


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _write_rankings(snap_dir: Path, rows: list):
    snap_dir.mkdir(parents=True, exist_ok=True)
    path = snap_dir / "rankings.csv"
    fieldnames = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def _write_prices(path: Path, rows: list):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["ticker", "date", "close"])
        w.writeheader()
        w.writerows(rows)


def _make_snapshot(snap_dir: Path, tickers: list, signal_field: str, values: list):
    """Create a minimal snapshot with signal values."""
    rows = []
    for t, v in zip(tickers, values):
        rows.append(
            {
                "ticker": t,
                signal_field: str(v),
                "score_rank_pct": str(v),
                "clinical_optionality_pct_dev": str(v),
                "clinical_score_v2_z": str(v),
                "inst_delta_z": str(v),
            }
        )
    _write_rankings(snap_dir, rows)


# ---------------------------------------------------------------------------
# compute_ic
# ---------------------------------------------------------------------------
class TestComputeIc:
    def test_perfect_positive(self):
        sig = {"A": 1.0, "B": 2.0, "C": 3.0, "D": 4.0, "E": 5.0, "F": 6.0, "G": 7.0, "H": 8.0, "I": 9.0, "J": 10.0}
        ret = {
            "A": 0.01,
            "B": 0.02,
            "C": 0.03,
            "D": 0.04,
            "E": 0.05,
            "F": 0.06,
            "G": 0.07,
            "H": 0.08,
            "I": 0.09,
            "J": 0.10,
        }
        ic, n = compute_ic(sig, ret, higher_is_better=True)
        assert ic > 0.95
        assert n == 10

    def test_perfect_negative(self):
        sig = {"A": 10.0, "B": 9.0, "C": 8.0, "D": 7.0, "E": 6.0, "F": 5.0, "G": 4.0, "H": 3.0, "I": 2.0, "J": 1.0}
        ret = {
            "A": 0.01,
            "B": 0.02,
            "C": 0.03,
            "D": 0.04,
            "E": 0.05,
            "F": 0.06,
            "G": 0.07,
            "H": 0.08,
            "I": 0.09,
            "J": 0.10,
        }
        ic, n = compute_ic(sig, ret, higher_is_better=True)
        assert ic < -0.95

    def test_flip_direction(self):
        sig = {"A": 10.0, "B": 9.0, "C": 8.0, "D": 7.0, "E": 6.0, "F": 5.0, "G": 4.0, "H": 3.0, "I": 2.0, "J": 1.0}
        ret = {
            "A": 0.01,
            "B": 0.02,
            "C": 0.03,
            "D": 0.04,
            "E": 0.05,
            "F": 0.06,
            "G": 0.07,
            "H": 0.08,
            "I": 0.09,
            "J": 0.10,
        }
        ic, n = compute_ic(sig, ret, higher_is_better=False)
        assert ic > 0.95  # flipped, so now positive

    def test_too_few_obs(self):
        sig = {"A": 1.0, "B": 2.0}
        ret = {"A": 0.01, "B": 0.02}
        ic, n = compute_ic(sig, ret, higher_is_better=True)
        assert math.isnan(ic)
        assert n == 2

    def test_partial_overlap(self):
        sig = {"A": 1.0, "B": 2.0, "C": 3.0, "D": 4.0, "E": 5.0, "F": 6.0, "G": 7.0, "H": 8.0, "I": 9.0, "J": 10.0}
        ret = {
            "A": 0.01,
            "B": 0.02,
            "C": 0.03,
            "D": 0.04,
            "E": 0.05,
            "F": 0.06,
            "G": 0.07,
            "H": 0.08,
            "I": 0.09,
            "J": 0.10,
            "K": 0.11,
        }  # extra ticker
        ic, n = compute_ic(sig, ret, higher_is_better=True)
        assert n == 10


# ---------------------------------------------------------------------------
# build_ic_dashboard
# ---------------------------------------------------------------------------
class TestBuildIcDashboard:
    def test_basic(self, tmp_path):
        snaps = tmp_path / "snapshots"
        artifacts = tmp_path / "artifacts"
        tickers = [f"T{i:02d}" for i in range(20)]

        # Create 5 prior snapshots with increasing signal values
        dates = ["2026-03-20", "2026-03-21", "2026-03-23", "2026-03-24", "2026-03-25"]
        for d in dates:
            values = [float(i) + hash(d) % 10 for i in range(20)]
            _make_snapshot(snaps / d, tickers, "inst_delta_z", values)

        # Create prices with forward returns
        price_rows = []
        for t in tickers:
            base = 10.0 + hash(t) % 20
            for i, d in enumerate(
                [
                    "2026-03-20",
                    "2026-03-21",
                    "2026-03-23",
                    "2026-03-24",
                    "2026-03-25",
                    "2026-03-26",
                    "2026-03-27",
                    "2026-03-28",
                    "2026-03-31",
                    "2026-04-01",
                    "2026-04-02",
                    "2026-04-03",
                    "2026-04-04",
                    "2026-04-07",
                    "2026-04-08",
                    "2026-04-09",
                    "2026-04-10",
                    "2026-04-11",
                    "2026-04-14",
                    "2026-04-15",
                    "2026-04-16",
                    "2026-04-17",
                    "2026-04-18",
                    "2026-04-21",
                    "2026-04-22",
                ]
            ):
                price_rows.append({"ticker": t, "date": d, "close": str(base + i * 0.1)})

        price_csv = tmp_path / "prices.csv"
        _write_prices(price_csv, price_rows)

        result = build_ic_dashboard(
            "2026-03-27",
            snapshots_dir=snaps,
            price_csv=price_csv,
            artifacts_dir=artifacts,
            lookback=5,
            horizon=20,
        )

        assert result["schema"] == SCHEMA_VERSION
        assert "error" not in result
        assert "signals" in result
        assert "inst_delta_z" in result["signals"]

    def test_missing_snapshots(self, tmp_path):
        result = build_ic_dashboard(
            "2026-03-27",
            snapshots_dir=tmp_path / "snapshots",
            price_csv=tmp_path / "p.csv",
            artifacts_dir=tmp_path / "artifacts",
        )
        assert "error" in result

    def test_writes_artifacts(self, tmp_path):
        snaps = tmp_path / "snapshots"
        artifacts = tmp_path / "artifacts"
        tickers = [f"T{i:02d}" for i in range(15)]

        dates = ["2026-03-22", "2026-03-23", "2026-03-24"]
        for d in dates:
            _make_snapshot(snaps / d, tickers, "score_rank_pct", [float(i) for i in range(15)])

        price_rows = []
        for t in tickers:
            for i, d in enumerate(
                [
                    "2026-03-22",
                    "2026-03-23",
                    "2026-03-24",
                    "2026-03-25",
                    "2026-03-26",
                    "2026-03-27",
                    "2026-03-28",
                    "2026-03-31",
                    "2026-04-01",
                    "2026-04-02",
                    "2026-04-03",
                    "2026-04-04",
                    "2026-04-07",
                    "2026-04-08",
                    "2026-04-09",
                    "2026-04-10",
                    "2026-04-11",
                    "2026-04-14",
                    "2026-04-15",
                    "2026-04-16",
                    "2026-04-17",
                    "2026-04-18",
                    "2026-04-21",
                    "2026-04-22",
                ]
            ):
                price_rows.append({"ticker": t, "date": d, "close": str(10.0 + i)})

        _write_prices(tmp_path / "p.csv", price_rows)

        build_ic_dashboard(
            "2026-03-27",
            snapshots_dir=snaps,
            price_csv=tmp_path / "p.csv",
            artifacts_dir=artifacts,
            lookback=5,
            horizon=20,
        )

        assert (artifacts / "ic_dashboard" / "2026-03-27_dashboard.json").exists()
        assert (artifacts / "ic_dashboard" / "2026-03-27_dashboard.md").exists()
        assert (artifacts / "ic_dashboard" / "history.jsonl").exists()


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------
class TestFormatMd:
    def test_basic(self):
        d = {
            "as_of_date": "2026-03-27",
            "attention": "MEDIUM",
            "lookback": 12,
            "horizon": 20,
            "date_range": ["2026-01-01", "2026-03-26"],
            "generated_at": "2026-03-27T00:00:00Z",
            "signals": {
                "inst_delta_z": {
                    "mean_ic": 0.045,
                    "hit_rate": 0.67,
                    "n_dates": 12,
                    "health": "HEALTHY",
                    "latest_ic": 0.052,
                    "per_date": [{"date": "2026-03-26", "ic": 0.052, "n_obs": 150}],
                },
                "clinical_score_v2_z": {
                    "mean_ic": -0.001,
                    "hit_rate": 0.50,
                    "n_dates": 12,
                    "health": "WARN",
                    "latest_ic": -0.02,
                    "per_date": [{"date": "2026-03-26", "ic": -0.02, "n_obs": 150}],
                },
            },
        }
        md = format_dashboard_md(d)
        assert "MEDIUM" in md
        assert "inst_delta_z" in md
        assert "HEALTHY" in md
        assert "WARN" in md
