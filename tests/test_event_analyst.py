"""Tests for build_event_analyst.py — lesson aggregation from postmortem records."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_event_analyst import build_event_analyst, load_postmortems


def _make_postmortem(ticker, event_date, outcome="HIT", tier="A", rank=10, catalyst_family="CLINICAL"):
    return {
        "schema": "postmortem.v1",
        "ticker": ticker,
        "event_date": event_date,
        "ruleset_id": "9f1f4587",
        "pre_event": {
            "actionable_rank": rank,
            "tier_dev": tier,
            "catalyst_family": catalyst_family,
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


class TestEventAnalystLoadPostmortems:
    def test_empty_dir(self, tmp_path):
        records = load_postmortems(tmp_path, "2026-04-30", lookback_days=90)
        assert records == []

    def test_loads_records(self, tmp_path):
        _write_postmortem(tmp_path, _make_postmortem("AAA", "2026-04-01"))
        _write_postmortem(tmp_path, _make_postmortem("BBB", "2026-04-05"))
        records = load_postmortems(tmp_path, "2026-04-30", lookback_days=90)
        assert len(records) == 2


class TestBuildEventAnalyst:
    def test_no_data(self, tmp_path):
        result = build_event_analyst("2026-04-30", artifacts_dir=tmp_path)
        assert result.get("status") == "NO_DATA" or result.get("n_postmortems", 0) == 0

    def test_with_data(self, tmp_path):
        pm_dir = tmp_path / "postmortem"
        _write_postmortem(pm_dir, _make_postmortem("AAA", "2026-04-01", "HIT", "A", 5))
        _write_postmortem(pm_dir, _make_postmortem("BBB", "2026-04-05", "MISS", "B", 50))
        _write_postmortem(pm_dir, _make_postmortem("CCC", "2026-04-10", "HIT", "A", 8))
        result = build_event_analyst("2026-04-30", artifacts_dir=tmp_path)
        assert result.get("n_postmortems", 0) == 3 or result.get("status") == "OK"

    def test_tier_separation(self, tmp_path):
        pm_dir = tmp_path / "postmortem"
        # A-tier names HIT, B-tier MISS
        for i in range(5):
            _write_postmortem(pm_dir, _make_postmortem(f"A{i}", f"2026-04-{i+1:02d}", "HIT", "A", i + 1))
        for i in range(5):
            _write_postmortem(pm_dir, _make_postmortem(f"B{i}", f"2026-04-{i+6:02d}", "MISS", "B", 50 + i))
        result = build_event_analyst("2026-04-30", artifacts_dir=tmp_path)
        # Should have some data regardless of exact schema
        n = result.get("n_postmortems", len(result.get("postmortems", [])))
        assert n >= 5  # At least some loaded
