"""Integration tests: CRT resolution records → postmortem / calibration_evidence.

Verifies that CRT output schema is compatible with downstream consumers."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.catalyst_resolution_tracker import ResolutionRecord, compute_record_hash


def _make_crt_record(**overrides):
    """Build a realistic CRT resolution record."""
    defaults = dict(
        ticker="PVLA",
        catalyst_date="2026-04-15",
        catalyst_type="PHASE_3_READOUT",
        catalyst_description="Phase 3 SELVA topline readout",
        resolution_date="2026-04-15",
        outcome="HIT",
        outcome_detail="Primary endpoint met with statistical significance",
        source_type="SEC_8K",
        source_id="8K_2026-04-15_PVLA",
        prediction_snapshot_date="2026-04-01",
        prediction_dem_rank=18,
        prediction_composite_score=72.3,
        price_t_minus_1=110.66,
        price_t_0=145.00,
        price_t_plus_5=138.50,
        days_from_expected=0,
        as_of_date="2026-04-16",
    )
    defaults.update(overrides)
    return ResolutionRecord(**defaults)


class TestCRTRecordPostmortemCompatibility:
    """CRT records must have the fields the postmortem agent expects."""

    def test_has_ticker(self):
        r = _make_crt_record()
        d = r.to_dict()
        assert d["ticker"] == "PVLA"

    def test_has_event_date(self):
        r = _make_crt_record()
        d = r.to_dict()
        assert d["catalyst_date"] == "2026-04-15"

    def test_has_outcome(self):
        r = _make_crt_record()
        d = r.to_dict()
        assert d["outcome"] in ("HIT", "MISS", "MIXED", "DELAYED", "WITHDRAWN", "NEEDS_REVIEW")

    def test_has_pre_event_rank(self):
        r = _make_crt_record()
        d = r.to_dict()
        assert d["prediction_dem_rank"] == 18

    def test_has_pre_event_snapshot_date(self):
        r = _make_crt_record()
        d = r.to_dict()
        assert d["prediction_snapshot_date"] == "2026-04-01"

    def test_has_price_reaction(self):
        r = _make_crt_record()
        d = r.to_dict()
        assert d["price_t_minus_1"] == 110.66
        assert d["price_t_0"] == 145.00
        assert d["price_t_plus_5"] == 138.50

    def test_can_compute_return(self):
        r = _make_crt_record()
        d = r.to_dict()
        t0_return = (d["price_t_0"] - d["price_t_minus_1"]) / d["price_t_minus_1"]
        assert abs(t0_return - 0.3104) < 0.01  # ~31% move

    def test_has_catalyst_type(self):
        r = _make_crt_record()
        d = r.to_dict()
        assert d["catalyst_type"] == "PHASE_3_READOUT"

    def test_has_source(self):
        r = _make_crt_record()
        d = r.to_dict()
        assert d["source_type"] in ("SEC_8K", "PRESS_RELEASE", "CTGOV_STATUS", "FDA_ACTION", "MANUAL")


class TestCRTRecordCalibrationEvidenceCompatibility:
    """CRT records must support calibration_evidence aggregation."""

    def test_can_group_by_catalyst_type(self):
        records = [
            _make_crt_record(ticker="A", catalyst_type="PDUFA_ACTION", outcome="HIT"),
            _make_crt_record(ticker="B", catalyst_type="PDUFA_ACTION", outcome="MISS"),
            _make_crt_record(ticker="C", catalyst_type="PHASE_3_READOUT", outcome="HIT"),
        ]
        by_type = {}
        for r in records:
            d = r.to_dict()
            ct = d["catalyst_type"]
            by_type.setdefault(ct, []).append(d["outcome"])
        assert by_type["PDUFA_ACTION"] == ["HIT", "MISS"]
        assert by_type["PHASE_3_READOUT"] == ["HIT"]

    def test_can_group_by_dem_decile(self):
        records = [
            _make_crt_record(ticker="TOP", prediction_dem_rank=5, outcome="HIT"),
            _make_crt_record(ticker="MID", prediction_dem_rank=50, outcome="MISS"),
            _make_crt_record(ticker="BOT", prediction_dem_rank=150, outcome="MISS"),
        ]
        top20 = [r for r in records if r.prediction_dem_rank is not None and r.prediction_dem_rank <= 20]
        assert len(top20) == 1
        assert top20[0].outcome == "HIT"

    def test_null_fields_handled(self):
        """Records with missing optional fields should not break aggregation."""
        r = _make_crt_record(
            prediction_dem_rank=None,
            prediction_composite_score=None,
            price_t_minus_1=None,
            price_t_0=None,
            price_t_plus_5=None,
        )
        d = r.to_dict()
        assert d["prediction_dem_rank"] is None
        assert d["price_t_0"] is None
        # Should still be groupable by catalyst_type
        assert d["catalyst_type"] == "PHASE_3_READOUT"


class TestCRTRecordDiskRoundTrip:
    """CRT records survive write-to-disk and read-back."""

    def test_json_round_trip(self, tmp_path):
        r = _make_crt_record()
        record_hash = compute_record_hash(r)
        out_data = r.to_dict()
        out_data["record_hash"] = record_hash

        path = tmp_path / "PVLA_2026-04-15.json"
        with open(path, "w") as f:
            json.dump(out_data, f, indent=2, default=str)

        with open(path) as f:
            loaded = json.load(f)

        assert loaded["ticker"] == "PVLA"
        assert loaded["outcome"] == "HIT"
        assert loaded["record_hash"] == record_hash

    def test_hash_stability(self):
        """Same record produces same hash across calls."""
        r1 = _make_crt_record()
        r2 = _make_crt_record()
        assert compute_record_hash(r1) == compute_record_hash(r2)

    def test_different_outcome_different_hash(self):
        r1 = _make_crt_record(outcome="HIT")
        r2 = _make_crt_record(outcome="MISS")
        assert compute_record_hash(r1) != compute_record_hash(r2)


class TestCRTRecordEdgeCases:
    """Edge cases that could break downstream consumers."""

    def test_delayed_no_prices(self):
        r = _make_crt_record(
            outcome="DELAYED",
            price_t_minus_1=None,
            price_t_0=None,
            price_t_plus_5=None,
            days_from_expected=None,
        )
        d = r.to_dict()
        assert d["outcome"] == "DELAYED"
        assert d["price_t_0"] is None

    def test_needs_review(self):
        r = _make_crt_record(outcome="NEEDS_REVIEW", outcome_detail="ambiguous headline")
        d = r.to_dict()
        assert d["outcome"] == "NEEDS_REVIEW"

    def test_withdrawn(self):
        r = _make_crt_record(outcome="WITHDRAWN", outcome_detail="trial terminated")
        d = r.to_dict()
        assert d["outcome"] == "WITHDRAWN"

    def test_mixed_outcome(self):
        r = _make_crt_record(outcome="MIXED", outcome_detail="met primary, missed key secondary")
        d = r.to_dict()
        assert d["outcome"] == "MIXED"

    def test_manual_override_source(self):
        r = _make_crt_record(source_type="MANUAL", source_id="manual_override")
        d = r.to_dict()
        assert d["source_type"] == "MANUAL"


class TestPredictionFieldPropagation:
    """prediction_composite_score must flow from CRT record into postmortem artifact."""

    def _make_pre_row(self, ticker="PVLA", composite_score="0.07"):
        return {
            "ticker": ticker,
            "actionable_rank": "18",
            "composite_score": composite_score,
            "tier_dev": "A",
            "size_band": "S",
            "target_weight_pct": "",
            "catalyst_days": "1",
            "catalyst_mode": "specific_days",
            "catalyst_family": "CLINICAL",
            "catalyst_event_type": "PHASE_3_READOUT",
            "catalyst_source": "CTGOV_CALENDAR",
            "is_hard_catalyst": "1",
            "confidence_overall": "0.9",
            "mom_state": "neutral",
            "eligible": "1",
            "ineligible_reasons": "",
            "decision_engine_ruleset_id": "2a3e79eb",
            "next_catalyst_date": "2026-04-15",
        }

    def _call_write_postmortem(self, tmp_path, ticker, event_date, resolution_rec):
        """Invoke write_postmortem with a minimal snapshot environment."""
        import agents.postmortem.scripts.run_postmortem as pm_mod

        orig_pm = pm_mod.PM_DIR
        orig_repo = pm_mod.REPO
        pm_mod.PM_DIR = str(tmp_path / "postmortem")
        pm_mod.REPO = str(tmp_path)

        outcome = {
            "pre_close_date": event_date,
            "pre_close": 110.0,
            "return_t1": 0.05,
            "t1_date": "2026-04-16",
            "excess_vs_xbi_t1": 0.03,
            "return_t3": 0.04,
            "t3_date": "2026-04-18",
            "excess_vs_xbi_t3": 0.02,
            "return_t5": 0.03,
            "excess_vs_xbi_t5": 0.01,
        }
        pre_row = self._make_pre_row(ticker=ticker)
        try:
            record = pm_mod.write_postmortem(ticker, event_date, "2026-04-14", pre_row, outcome, resolution_rec)
        finally:
            pm_mod.PM_DIR = orig_pm
            pm_mod.REPO = orig_repo
        return record

    def test_prediction_score_in_resolution_source(self, tmp_path):
        crt = _make_crt_record(
            prediction_composite_score=72.3,
            prediction_snapshot_date="2026-04-01",
            prediction_dem_rank=18,
        ).to_dict()
        record = self._call_write_postmortem(tmp_path, "PVLA", "2026-04-15", crt)
        rs = record.get("resolution_source", {})
        assert rs.get("prediction_composite_score") == 72.3

    def test_prediction_snapshot_date_in_resolution_source(self, tmp_path):
        crt = _make_crt_record(prediction_snapshot_date="2026-04-01").to_dict()
        record = self._call_write_postmortem(tmp_path, "PVLA", "2026-04-15", crt)
        rs = record.get("resolution_source", {})
        assert rs.get("prediction_snapshot_date") == "2026-04-01"

    def test_prediction_dem_rank_in_resolution_source(self, tmp_path):
        crt = _make_crt_record(prediction_dem_rank=18).to_dict()
        record = self._call_write_postmortem(tmp_path, "PVLA", "2026-04-15", crt)
        rs = record.get("resolution_source", {})
        assert rs.get("prediction_dem_rank") == 18

    def test_composite_score_in_pre_event(self, tmp_path):
        crt = _make_crt_record().to_dict()
        record = self._call_write_postmortem(tmp_path, "PVLA", "2026-04-15", crt)
        assert record["pre_event"].get("composite_score") == pytest.approx(0.07, abs=1e-6)

    def test_null_prediction_score_propagated(self, tmp_path):
        crt = _make_crt_record(prediction_composite_score=None).to_dict()
        record = self._call_write_postmortem(tmp_path, "PVLA", "2026-04-15", crt)
        rs = record.get("resolution_source", {})
        assert "prediction_composite_score" in rs
        assert rs["prediction_composite_score"] is None

    def test_no_resolution_rec_no_resolution_source(self, tmp_path):
        record = self._call_write_postmortem(tmp_path, "PVLA", "2026-04-15", None)
        assert "resolution_source" not in record

    def test_live_artifacts_have_prediction_field(self):
        """All existing postmortem artifacts must carry prediction_composite_score."""
        artifacts_dir = Path(__file__).resolve().parents[1] / "artifacts" / "postmortem"
        if not artifacts_dir.exists():
            return
        missing = []
        for f in artifacts_dir.glob("**/*.json"):
            d = json.loads(f.read_text())
            if "pre_event" not in d:
                continue
            rs = d.get("resolution_source", {})
            if "prediction_composite_score" not in rs:
                missing.append(str(f.relative_to(artifacts_dir)))
        assert missing == [], f"Artifacts missing prediction_composite_score: {missing}"
