"""Tests for build_calibration_evidence.py — evidence builder from postmortem records."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_calibration_evidence import build_calibration_evidence, load_postmortems, load_snapshot_row


def _make_postmortem(ticker, event_date, outcome="HIT", tier="A", rank=10):
    return {
        "schema": "postmortem.v1",
        "ticker": ticker,
        "event_date": event_date,
        "ruleset_id": "9f1f4587",
        "pre_event": {
            "actionable_rank": rank,
            "tier_dev": tier,
            "catalyst_family": "CLINICAL",
            "catalyst_days": 5,
            "snapshot_date": event_date,
        },
        "outcome": {
            "outcome": outcome,
            "return_t1": 0.10 if outcome == "HIT" else -0.15,
            "return_t3": 0.08 if outcome == "HIT" else -0.20,
            "excess_return_t1": 0.09 if outcome == "HIT" else -0.16,
            "abs_gap": 0.12 if outcome == "HIT" else 0.18,
        },
    }


def _write_postmortem(base_dir, pm):
    date_dir = base_dir / pm["event_date"]
    date_dir.mkdir(parents=True, exist_ok=True)
    path = date_dir / f"{pm['ticker']}_{pm['event_date']}.json"
    with open(path, "w") as f:
        json.dump(pm, f, indent=2)
    return path


class TestLoadPostmortems:
    def test_empty_dir(self, tmp_path):
        records = load_postmortems(tmp_path, "2026-04-30")
        assert records == []

    def test_loads_valid_records(self, tmp_path):
        pm = _make_postmortem("TEST", "2026-04-01")
        _write_postmortem(tmp_path, pm)
        records = load_postmortems(tmp_path, "2026-04-30")
        assert len(records) == 1
        assert records[0]["ticker"] == "TEST"

    def test_respects_as_of_date(self, tmp_path):
        pm1 = _make_postmortem("EARLY", "2026-03-01")
        pm2 = _make_postmortem("LATE", "2026-05-01")
        _write_postmortem(tmp_path, pm1)
        _write_postmortem(tmp_path, pm2)
        records = load_postmortems(tmp_path, "2026-04-15")
        assert len(records) == 1
        assert records[0]["ticker"] == "EARLY"

    def test_ignores_wrong_schema(self, tmp_path):
        pm = _make_postmortem("TEST", "2026-04-01")
        pm["schema"] = "wrong_schema.v1"
        _write_postmortem(tmp_path, pm)
        records = load_postmortems(tmp_path, "2026-04-30")
        assert len(records) == 0

    def test_handles_corrupt_json(self, tmp_path):
        date_dir = tmp_path / "2026-04-01"
        date_dir.mkdir()
        (date_dir / "bad.json").write_text("{invalid json")
        records = load_postmortems(tmp_path, "2026-04-30")
        assert len(records) == 0


class TestBuildCalibrationEvidence:
    def test_no_data_returns_status(self, tmp_path):
        result = build_calibration_evidence(
            "2026-04-30",
            artifacts_dir=tmp_path,
            snapshots_dir=tmp_path / "snapshots",
        )
        assert result["status"] == "NO_DATA"
        assert result["n_postmortems"] == 0

    def test_with_data_returns_ok(self, tmp_path):
        pm_dir = tmp_path / "postmortem"
        for i in range(3):
            pm = _make_postmortem(f"T{i}", f"2026-04-{i+1:02d}")
            _write_postmortem(pm_dir, pm)
        snap_dir = tmp_path / "snapshots"
        snap_dir.mkdir()
        result = build_calibration_evidence(
            "2026-04-30",
            artifacts_dir=tmp_path,
            snapshots_dir=snap_dir,
        )
        assert result["status"] == "OK"
        assert result["n_postmortems"] == 3
        assert "signal_tracker" in result
        assert "threshold_audit" in result
        assert "calibration_curve" in result


class TestLoadSnapshotRow:
    def test_missing_snapshot(self, tmp_path):
        row = load_snapshot_row(tmp_path, "2026-04-01", "TEST")
        assert row == {}

    def test_loads_ticker_row(self, tmp_path):
        snap_dir = tmp_path / "2026-04-01"
        snap_dir.mkdir()
        (snap_dir / "rankings.csv").write_text("ticker,actionable_rank,tier_any\nTEST,5,A\nOTHER,10,B\n")
        row = load_snapshot_row(tmp_path, "2026-04-01", "TEST")
        assert row["ticker"] == "TEST"
        assert row["actionable_rank"] == "5"

    def test_missing_ticker(self, tmp_path):
        snap_dir = tmp_path / "2026-04-01"
        snap_dir.mkdir()
        (snap_dir / "rankings.csv").write_text("ticker,actionable_rank\nOTHER,10\n")
        row = load_snapshot_row(tmp_path, "2026-04-01", "MISSING")
        assert row == {}
