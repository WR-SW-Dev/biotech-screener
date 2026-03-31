"""Tests for CRT Phase 3 — calibration rollup + governance triggers."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.catalyst_resolution_tracker import ResolutionRecord, compute_record_hash


def _write_resolution(
    resolutions_dir,
    ticker,
    catalyst_date,
    outcome,
    catalyst_type="PHASE_3_READOUT",
    dem_rank=None,
    price_t_minus_1=None,
    price_t_0=None,
):
    """Helper to write a resolution record to disk."""
    record = ResolutionRecord(
        ticker=ticker,
        catalyst_date=catalyst_date,
        catalyst_type=catalyst_type,
        resolution_date=catalyst_date,
        outcome=outcome,
        source_type="SEC_8K",
        source_id=f"test_{ticker}_{catalyst_date}",
        prediction_dem_rank=dem_rank,
        price_t_minus_1=price_t_minus_1,
        price_t_0=price_t_0,
        as_of_date=catalyst_date,
    )
    month_dir = resolutions_dir / catalyst_date[:7]
    month_dir.mkdir(parents=True, exist_ok=True)
    out_path = month_dir / f"{ticker}_{catalyst_date}.json"
    out_data = record.to_dict()
    out_data["record_hash"] = compute_record_hash(record)
    with open(out_path, "w") as f:
        json.dump(out_data, f, indent=2)
    return out_path


class TestCalibrationRollup:
    def test_empty_resolutions_dir(self, tmp_path):
        from tools.crt_calibration import build_calibration_summary

        result = build_calibration_summary(tmp_path, "2026-04")
        assert result["total_resolutions"] == 0
        assert result["period"] == "2026-04"

    def test_counts_outcomes_correctly(self, tmp_path):
        from tools.crt_calibration import build_calibration_summary

        _write_resolution(tmp_path, "AAA", "2026-04-01", "HIT")
        _write_resolution(tmp_path, "BBB", "2026-04-05", "HIT")
        _write_resolution(tmp_path, "CCC", "2026-04-10", "MISS")
        _write_resolution(tmp_path, "DDD", "2026-04-15", "DELAYED")
        result = build_calibration_summary(tmp_path, "2026-04")
        assert result["total_resolutions"] == 4
        assert result["outcome_distribution"]["HIT"] == 2
        assert result["outcome_distribution"]["MISS"] == 1
        assert result["outcome_distribution"]["DELAYED"] == 1

    def test_by_catalyst_type(self, tmp_path):
        from tools.crt_calibration import build_calibration_summary

        _write_resolution(tmp_path, "AAA", "2026-04-01", "HIT", catalyst_type="PDUFA_ACTION")
        _write_resolution(tmp_path, "BBB", "2026-04-05", "MISS", catalyst_type="PDUFA_ACTION")
        _write_resolution(tmp_path, "CCC", "2026-04-10", "HIT", catalyst_type="PHASE_3_READOUT")
        result = build_calibration_summary(tmp_path, "2026-04")
        pdufa = result["by_catalyst_type"]["PDUFA_ACTION"]
        assert pdufa["n"] == 2
        assert pdufa["hit"] == 1
        assert pdufa["miss"] == 1
        assert pdufa["hit_rate"] == 0.5

    def test_by_dem_decile(self, tmp_path):
        from tools.crt_calibration import build_calibration_summary

        _write_resolution(tmp_path, "TOP", "2026-04-01", "HIT", dem_rank=5)
        _write_resolution(tmp_path, "MID", "2026-04-05", "MISS", dem_rank=50)
        _write_resolution(tmp_path, "BOT", "2026-04-10", "MISS", dem_rank=150)
        result = build_calibration_summary(tmp_path, "2026-04")
        assert result["by_dem_decile"]["top_20"]["hit"] == 1
        assert result["by_dem_decile"]["bottom_50"]["miss"] >= 1

    def test_ignores_other_months(self, tmp_path):
        from tools.crt_calibration import build_calibration_summary

        _write_resolution(tmp_path, "AAA", "2026-04-01", "HIT")
        _write_resolution(tmp_path, "BBB", "2026-03-15", "MISS")  # March, not April
        result = build_calibration_summary(tmp_path, "2026-04")
        assert result["total_resolutions"] == 1


class TestGovernanceTriggers:
    def test_no_triggers_when_empty(self, tmp_path):
        from tools.crt_calibration import evaluate_governance_triggers

        triggers = evaluate_governance_triggers(tmp_path, "2026-04")
        assert all(t["status"] != "MET" for t in triggers)

    def test_catalyst_taxonomy_trigger(self, tmp_path):
        from tools.crt_calibration import evaluate_governance_triggers

        # Write 25 resolutions across 5 catalyst types
        types = ["PDUFA_ACTION", "PHASE_3_READOUT", "PHASE_2_READOUT", "NDA_BLA_FILING", "ADVISORY_COMMITTEE"]
        for i in range(25):
            ct = types[i % len(types)]
            _write_resolution(tmp_path, f"T{i:03d}", f"2026-04-{(i % 28) + 1:02d}", "HIT", catalyst_type=ct)
        triggers = evaluate_governance_triggers(tmp_path, "2026-04")
        taxonomy = next(t for t in triggers if t["trigger"] == "catalyst_taxonomy_empirical")
        assert taxonomy["status"] == "MET"

    def test_postmortem_coverage_trigger(self, tmp_path):
        from tools.crt_calibration import evaluate_governance_triggers

        for i in range(6):
            _write_resolution(tmp_path, f"T{i}", f"2026-04-{i+1:02d}", "HIT", price_t_minus_1=10.0, price_t_0=15.0)
        triggers = evaluate_governance_triggers(tmp_path, "2026-04")
        postmortem = next(t for t in triggers if t["trigger"] == "postmortem_coverage_threshold")
        assert postmortem["status"] == "MET"
