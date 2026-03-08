"""Tests for weekly_go_nogo.py."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.weekly_go_nogo import (
    SCHEMA_VERSION,
    build_ic_memo,
    check_focus_bucket_health,
    check_gap_risk,
    check_price_coverage,
    check_snapshot_integrity,
    check_turnover,
    run_go_nogo,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

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

RANKINGS_HEADER = "ticker,actionable_rank,catalyst_days,catalyst_mode," "eligible,tier_any,size_band,target_weight_pct"


def _write_metadata(snap_dir, **overrides):
    snap_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "ruleset_id": "abc123",
        "ruleset_hash": "deadbeef",
        "engine_version": "v1.0",
        "git_sha": "1234567",
    }
    meta.update(overrides)
    with open(snap_dir / "metadata.json", "w") as f:
        json.dump(meta, f)


def _write_rankings(snap_dir, rows=None):
    snap_dir.mkdir(parents=True, exist_ok=True)
    path = snap_dir / "rankings.csv"
    if rows is None:
        rows = [
            "AAPL,1,90,specific_days,1,A,L,2.5",
            "GOOG,2,120,specific_days,1,B,M,2.5",
        ]
    with open(path, "w") as f:
        f.write(RANKINGS_HEADER + "\n")
        for r in rows:
            f.write(r + "\n")


def _write_manifest(snap_dir, overall_status="WARN"):
    snap_dir.mkdir(parents=True, exist_ok=True)
    with open(snap_dir / "run_manifest.json", "w") as f:
        json.dump({"overall_status": overall_status}, f)


def _write_positions(shadow_root, date, positions):
    pos_dir = shadow_root / "positions"
    pos_dir.mkdir(parents=True, exist_ok=True)
    with open(pos_dir / f"{date}.json", "w") as f:
        json.dump(
            {"schema": "live_shadow_positions.v1", "as_of_date": date, "positions": positions},
            f,
        )


def _write_perf_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=PERF_COLUMNS)
        w.writeheader()
        w.writerows(rows)


def _perf_row(date, turnover=0.05, pnl_pct=1.0, xbi=0.5, sleeve_91_180=500):
    return {
        "schema_version": "live_shadow_perf.v1",
        "date": date,
        "prior_date": "",
        "total_pnl": "1000",
        "pnl_pct": str(pnl_pct),
        "xbi_return_pct": str(xbi),
        "excess_vs_xbi_pct": str(pnl_pct - xbi),
        "n_held": "60",
        "turnover": str(turnover),
        "gap_risk_high_count": "0",
        "n_missing_price": "0",
        "sleeve_binary_0_30_pnl": "100",
        "sleeve_binary_31_90_pnl": "200",
        "sleeve_binary_91_180_pnl": str(sleeve_91_180),
        "sleeve_less_binary_pnl": "50",
        "ruleset_id": "test",
    }


def _make_positions(n=20, bucket="binary_91_180", gap_risk=""):
    return [
        {
            "ticker": f"T{i:03d}",
            "bucket": bucket,
            "target_dollars": 5000,
            "gap_risk": gap_risk,
            "price_coverage": "OK",
            "actionable_rank": i,
        }
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# A) Snapshot integrity
# ---------------------------------------------------------------------------


class TestSnapshotIntegrity:
    def test_missing_metadata_fails(self, tmp_path):
        snap = tmp_path / "snap"
        snap.mkdir()
        results = check_snapshot_integrity(snap)
        assert any(c["status"] == "FAIL" and c["check"] == "snapshot_metadata" for c in results)

    def test_missing_provenance_field_fails(self, tmp_path):
        snap = tmp_path / "snap"
        _write_metadata(snap, ruleset_id="", engine_version="v1")
        _write_rankings(snap)
        results = check_snapshot_integrity(snap)
        assert any(c["status"] == "FAIL" and c["check"] == "snapshot_provenance" for c in results)

    def test_valid_provenance_passes(self, tmp_path):
        snap = tmp_path / "snap"
        _write_metadata(snap)
        _write_rankings(snap)
        results = check_snapshot_integrity(snap)
        prov = [c for c in results if c["check"] == "snapshot_provenance"]
        assert prov[0]["status"] == "PASS"

    def test_manifest_fail_status(self, tmp_path):
        snap = tmp_path / "snap"
        _write_metadata(snap)
        _write_rankings(snap)
        _write_manifest(snap, "FAIL")
        results = check_snapshot_integrity(snap)
        pf = [c for c in results if c["check"] == "preflight_status"]
        assert pf[0]["status"] == "FAIL"

    def test_missing_rankings_cols(self, tmp_path):
        snap = tmp_path / "snap"
        _write_metadata(snap)
        # Write rankings with missing columns
        with open(snap / "rankings.csv", "w") as f:
            f.write("ticker,foo\nAAPL,1\n")
        results = check_snapshot_integrity(snap)
        rc = [c for c in results if c["check"] == "rankings_columns"]
        assert rc[0]["status"] == "FAIL"


# ---------------------------------------------------------------------------
# B) Price coverage
# ---------------------------------------------------------------------------


class TestPriceCoverage:
    def test_all_priced_passes(self):
        prices = {"AAPL": 150.0, "GOOG": 200.0}
        positions = [
            {"ticker": "AAPL", "price_coverage": "OK"},
            {"ticker": "GOOG", "price_coverage": "OK"},
        ]
        results = check_price_coverage(["AAPL", "GOOG"], prices, positions)
        assert results[0]["status"] == "PASS"

    def test_missing_price_fails(self):
        prices = {"AAPL": 150.0}
        positions = [
            {"ticker": "AAPL", "price_coverage": "OK"},
            {"ticker": "GOOG", "price_coverage": "OK"},
        ]
        results = check_price_coverage(["AAPL", "GOOG"], prices, positions)
        assert results[0]["status"] == "FAIL"
        assert results[0]["hard"]

    def test_missing_price_relaxed_warns(self):
        prices = {"AAPL": 150.0}
        positions = [
            {"ticker": "AAPL", "price_coverage": "OK"},
            {"ticker": "GOOG", "price_coverage": "OK"},
        ]
        results = check_price_coverage(["AAPL", "GOOG"], prices, positions, relaxed=True)
        assert results[0]["status"] == "WARN"

    def test_coverage_flag_missing_fails(self):
        prices = {"AAPL": 150.0, "GOOG": 200.0}
        positions = [
            {"ticker": "AAPL", "price_coverage": "OK"},
            {"ticker": "GOOG", "price_coverage": "MISSING"},
        ]
        results = check_price_coverage(["AAPL", "GOOG"], prices, positions)
        assert results[0]["status"] == "FAIL"


# ---------------------------------------------------------------------------
# C) Gap-risk
# ---------------------------------------------------------------------------


class TestGapRisk:
    def test_under_threshold_passes(self):
        positions = _make_positions(3, gap_risk="HIGH")
        results = check_gap_risk(positions, [], max_high_gap=5)
        assert results[0]["status"] == "PASS"

    def test_over_threshold_warns(self):
        positions = _make_positions(6, gap_risk="HIGH")
        results = check_gap_risk(positions, [], max_high_gap=5)
        assert results[0]["status"] == "WARN"

    def test_far_over_threshold_fails(self):
        positions = _make_positions(8, gap_risk="HIGH")
        results = check_gap_risk(positions, [], max_high_gap=5)
        assert results[0]["status"] == "FAIL"


# ---------------------------------------------------------------------------
# D) Turnover
# ---------------------------------------------------------------------------


class TestTurnover:
    def test_normal_turnover_passes(self, tmp_path):
        perf = tmp_path / "perf.csv"
        _write_perf_csv(
            perf,
            [
                _perf_row("2026-03-01", turnover=0.04),
                _perf_row("2026-03-02", turnover=0.05),
                _perf_row("2026-03-03", turnover=0.03),
                _perf_row("2026-03-04", turnover=0.04),
            ],
        )
        results = check_turnover(0.06, perf, "2026-03-08")
        assert results[0]["status"] == "PASS"

    def test_spike_warns(self, tmp_path):
        perf = tmp_path / "perf.csv"
        _write_perf_csv(
            perf,
            [
                _perf_row("2026-03-01", turnover=0.04),
                _perf_row("2026-03-02", turnover=0.04),
                _perf_row("2026-03-03", turnover=0.04),
                _perf_row("2026-03-04", turnover=0.04),
            ],
        )
        # 0.15 > 2.5 * 0.04 = 0.10 and > 0.05
        results = check_turnover(0.15, perf, "2026-03-08")
        assert results[0]["status"] == "WARN"

    def test_big_spike_fails(self, tmp_path):
        perf = tmp_path / "perf.csv"
        _write_perf_csv(
            perf,
            [
                _perf_row("2026-03-01", turnover=0.04),
                _perf_row("2026-03-02", turnover=0.04),
            ],
        )
        # 0.25 > 4 * 0.04 = 0.16 and > 0.10
        results = check_turnover(0.25, perf, "2026-03-08")
        assert results[0]["status"] == "FAIL"

    def test_no_trailing_data_passes(self, tmp_path):
        perf = tmp_path / "perf.csv"
        results = check_turnover(0.10, perf, "2026-03-08")
        assert results[0]["status"] == "PASS"


# ---------------------------------------------------------------------------
# E) Focus bucket health
# ---------------------------------------------------------------------------


class TestFocusBucketHealth:
    def test_enough_names_passes(self, tmp_path):
        positions = _make_positions(20, bucket="binary_91_180")
        perf = tmp_path / "perf.csv"
        results = check_focus_bucket_health(positions, perf, "2026-03-08", min_names=15)
        names_check = [c for c in results if c["check"] == "focus_bucket_names"]
        assert names_check[0]["status"] == "PASS"

    def test_too_few_names_warns(self, tmp_path):
        positions = _make_positions(10, bucket="binary_91_180")
        perf = tmp_path / "perf.csv"
        results = check_focus_bucket_health(positions, perf, "2026-03-08", min_names=15)
        names_check = [c for c in results if c["check"] == "focus_bucket_names"]
        assert names_check[0]["status"] == "WARN"

    def test_negative_streak_warns(self, tmp_path):
        perf = tmp_path / "perf.csv"
        _write_perf_csv(
            perf,
            [
                _perf_row("2026-03-01", sleeve_91_180=-100, xbi=0.5),
                _perf_row("2026-03-02", sleeve_91_180=-50, xbi=0.5),
                _perf_row("2026-03-03", sleeve_91_180=-200, xbi=0.5),
            ],
        )
        positions = _make_positions(20)
        results = check_focus_bucket_health(positions, perf, "2026-03-08", warn_streak=3, fail_streak=6)
        streak_check = [c for c in results if c["check"] == "focus_bucket_streak"]
        assert streak_check[0]["status"] == "WARN"

    def test_long_negative_streak_fails(self, tmp_path):
        perf = tmp_path / "perf.csv"
        rows = [_perf_row(f"2026-03-0{i}", sleeve_91_180=-100, xbi=0.5) for i in range(1, 8)]
        _write_perf_csv(perf, rows)
        positions = _make_positions(20)
        results = check_focus_bucket_health(positions, perf, "2026-03-08", warn_streak=3, fail_streak=6)
        streak_check = [c for c in results if c["check"] == "focus_bucket_streak"]
        assert streak_check[0]["status"] == "FAIL"


# ---------------------------------------------------------------------------
# Orchestrator + relaxed/confirm logic
# ---------------------------------------------------------------------------


class TestRunGoNogo:
    def _setup_clean(self, tmp_path, date="2026-03-08"):
        snap_root = tmp_path / "snapshots"
        shadow_root = tmp_path / "shadow"
        snap = snap_root / date
        _write_metadata(snap)
        _write_rankings(snap)

        # Write positions with enough focus bucket names
        positions = _make_positions(20, bucket="binary_91_180")
        _write_positions(shadow_root, date, positions)

        # Write price history CSV
        price_path = tmp_path / "prices.csv"
        with open(price_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["date", "ticker", "close"])
            w.writeheader()
            for p in positions:
                w.writerow({"date": date, "ticker": p["ticker"], "close": "100.0"})

        return snap_root, shadow_root, price_path

    def test_go_with_confirm(self, tmp_path):
        snap_root, shadow_root, price_path = self._setup_clean(tmp_path)
        result = run_go_nogo(
            "2026-03-08",
            snapshot_root=snap_root,
            shadow_root=shadow_root,
            price_path=price_path,
            confirm=True,
            out_dir=tmp_path / "out",
        )
        assert result["verdict"] == "GO"
        assert result["n_fail"] == 0

    def test_nogo_without_confirm(self, tmp_path):
        snap_root, shadow_root, price_path = self._setup_clean(tmp_path)
        result = run_go_nogo(
            "2026-03-08",
            snapshot_root=snap_root,
            shadow_root=shadow_root,
            price_path=price_path,
            confirm=False,
            out_dir=tmp_path / "out",
        )
        assert result["verdict"] == "NOGO"
        assert "confirm" in result["nogo_reason"].lower()

    def test_relaxed_always_nogo(self, tmp_path):
        snap_root, shadow_root, price_path = self._setup_clean(tmp_path)
        result = run_go_nogo(
            "2026-03-08",
            snapshot_root=snap_root,
            shadow_root=shadow_root,
            price_path=price_path,
            confirm=True,
            relaxed=True,
            out_dir=tmp_path / "out",
        )
        assert result["verdict"] == "NOGO"
        assert "RELAXED" in result["nogo_reason"]
        # Check scarlet banner in MD
        md = (tmp_path / "out" / "GO_NOGO.md").read_text()
        assert "RELAXED" in md
        assert "DO NOT TRADE" in md

    def test_hard_fail_produces_nogo(self, tmp_path):
        snap_root = tmp_path / "snapshots"
        shadow_root = tmp_path / "shadow"
        snap = snap_root / "2026-03-08"
        # Missing provenance → FAIL
        _write_metadata(snap, ruleset_id="", ruleset_hash="", engine_version="")
        _write_rankings(snap)
        _write_positions(shadow_root, "2026-03-08", _make_positions(20))

        result = run_go_nogo(
            "2026-03-08",
            snapshot_root=snap_root,
            shadow_root=shadow_root,
            confirm=True,
            out_dir=tmp_path / "out",
        )
        assert result["verdict"] == "NOGO"
        assert result["n_fail"] >= 1

    def test_json_schema_stable(self, tmp_path):
        snap_root, shadow_root, price_path = self._setup_clean(tmp_path)
        run_go_nogo(
            "2026-03-08",
            snapshot_root=snap_root,
            shadow_root=shadow_root,
            price_path=price_path,
            confirm=True,
            out_dir=tmp_path / "out",
        )
        json_path = tmp_path / "out" / "GO_NOGO.json"
        assert json_path.is_file()
        with open(json_path) as f:
            doc = json.load(f)
        assert doc["schema"] == SCHEMA_VERSION
        assert "verdict" in doc
        assert "checks" in doc
        assert isinstance(doc["checks"], list)
        for c in doc["checks"]:
            assert "check" in c
            assert "status" in c
            assert c["status"] in ("PASS", "WARN", "FAIL")

    def test_outputs_both_files(self, tmp_path):
        snap_root, shadow_root, price_path = self._setup_clean(tmp_path)
        run_go_nogo(
            "2026-03-08",
            snapshot_root=snap_root,
            shadow_root=shadow_root,
            price_path=price_path,
            out_dir=tmp_path / "out",
        )
        assert (tmp_path / "out" / "GO_NOGO.json").is_file()
        assert (tmp_path / "out" / "GO_NOGO.md").is_file()


# ---------------------------------------------------------------------------
# IC memo
# ---------------------------------------------------------------------------


class TestICMemo:
    def test_no_data_memo(self, tmp_path):
        perf = tmp_path / "perf.csv"
        lines = build_ic_memo(perf, "2026-03-08")
        text = "\n".join(lines)
        assert "No performance data" in text

    def test_with_data(self, tmp_path):
        perf = tmp_path / "perf.csv"
        _write_perf_csv(
            perf,
            [
                _perf_row("2026-03-04", pnl_pct=1.5, xbi=0.5),
                _perf_row("2026-03-08", pnl_pct=-0.5, xbi=-0.3),
            ],
        )
        lines = build_ic_memo(perf, "2026-03-08")
        text = "\n".join(lines)
        assert "Latest period" in text
        assert "2026-03-08" in text
        assert "Trailing Bucket" in text

    def test_with_contributors(self, tmp_path):
        perf = tmp_path / "perf.csv"
        _write_perf_csv(perf, [_perf_row("2026-03-08")])
        contribs = [
            {
                "ticker": f"T{i}",
                "bucket": "binary_91_180",
                "pnl": 100 - i * 30,
                "return_pct": 2.0 - i * 0.5,
                "dollars": 5000,
            }
            for i in range(10)
        ]
        lines = build_ic_memo(perf, "2026-03-08", contribs)
        text = "\n".join(lines)
        assert "Top Contributors" in text
        assert "Bottom Contributors" in text
