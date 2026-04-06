"""Tests for compute_timing_hazard — execution warning logic.

Covers the _compute_execution_warning function with realistic kwargs to
verify that warnings fire correctly after the bug fix (kwargs were not
passed at the call site, causing FAMILY_MISSING and LOW_CONFIDENCE_DATE
to fire on every catalyst).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.compute_timing_hazard import (
    _compute_calibration_curve,
    _compute_execution_warning,
    classify_family_bucket,
    classify_hardness,
    classify_horizon_bucket,
)

# ---------------------------------------------------------------------------
# _compute_execution_warning tests
# ---------------------------------------------------------------------------


class TestExecutionWarningKwargs:
    """Verify that warnings fire correctly when kwargs are provided."""

    def _call(self, **overrides):
        """Call _compute_execution_warning with sane defaults + overrides."""
        defaults = dict(
            on_time_prob=0.70,
            last_update_age=30,
            aact_delta=None,
            is_hard=True,
            logistic_prob=0.65,
            catalyst_family="REGULATORY",
            catalyst_days=45,
            precision="DAY",
            date_confidence=0.85,
            source="FDA_CALENDAR",
            n_revisions=0,
            last_revision_pushout=False,
            source_action="ALLOW",
        )
        defaults.update(overrides)
        # Separate positional from keyword args
        positional = [
            defaults.pop("on_time_prob"),
            defaults.pop("last_update_age"),
            defaults.pop("aact_delta"),
            defaults.pop("is_hard"),
        ]
        return _compute_execution_warning(*positional, **defaults)

    def test_clean_regulatory_no_warnings(self):
        """A healthy regulatory catalyst should produce zero warnings."""
        has_warn, reasons = self._call()
        assert not has_warn
        assert reasons == []

    def test_family_missing_not_fired_when_family_present(self):
        """FAMILY_MISSING should NOT fire when catalyst_family is provided."""
        has_warn, reasons = self._call(catalyst_family="CLINICAL")
        labels = [w["label"] for w in reasons]
        assert "FAMILY_MISSING" not in labels

    def test_family_missing_fires_when_empty(self):
        """FAMILY_MISSING should fire when catalyst_family is empty."""
        has_warn, reasons = self._call(catalyst_family="")
        labels = [w["label"] for w in reasons]
        assert "FAMILY_MISSING" in labels

    def test_family_missing_fires_when_no_catalyst(self):
        """FAMILY_MISSING should fire when catalyst_family is NO_CATALYST."""
        has_warn, reasons = self._call(catalyst_family="NO_CATALYST")
        labels = [w["label"] for w in reasons]
        assert "FAMILY_MISSING" in labels

    def test_low_confidence_not_fired_with_day_precision(self):
        """LOW_CONFIDENCE_DATE should NOT fire when precision is DAY."""
        has_warn, reasons = self._call(precision="DAY", date_confidence=0.85, logistic_prob=0.70)
        labels = [w["label"] for w in reasons]
        assert "LOW_CONFIDENCE_DATE" not in labels

    def test_low_confidence_fires_with_quarter_precision(self):
        """LOW_CONFIDENCE_DATE fires with QUARTER precision."""
        has_warn, reasons = self._call(precision="QUARTER")
        labels = [w["label"] for w in reasons]
        assert "LOW_CONFIDENCE_DATE" in labels

    def test_low_confidence_fires_with_low_model_prob(self):
        """LOW_CONFIDENCE_DATE fires when logistic_prob < 0.50."""
        has_warn, reasons = self._call(logistic_prob=0.35, precision="DAY")
        labels = [w["label"] for w in reasons]
        assert "LOW_CONFIDENCE_DATE" in labels

    def test_low_confidence_fires_with_low_date_confidence(self):
        """LOW_CONFIDENCE_DATE fires when date_confidence < 0.50."""
        has_warn, reasons = self._call(date_confidence=0.30, precision="DAY")
        labels = [w["label"] for w in reasons]
        assert "LOW_CONFIDENCE_DATE" in labels

    def test_short_dated_revision_risk(self):
        """SHORT_DATED_REVISION_RISK fires for near-term + pushout."""
        # Use CLINICAL+SOFT to avoid REGULATORY_DETERMINISTIC suppression
        has_warn, reasons = self._call(
            catalyst_days=15, last_revision_pushout=True, catalyst_family="CLINICAL", is_hard=False
        )
        labels = [w["label"] for w in reasons]
        assert "SHORT_DATED_REVISION_RISK" in labels

    def test_short_dated_no_fire_without_pushout(self):
        """SHORT_DATED_REVISION_RISK should NOT fire without pushout."""
        has_warn, reasons = self._call(
            catalyst_days=15, last_revision_pushout=False, catalyst_family="CLINICAL", is_hard=False
        )
        labels = [w["label"] for w in reasons]
        assert "SHORT_DATED_REVISION_RISK" not in labels

    def test_short_dated_no_fire_for_far_catalyst(self):
        """SHORT_DATED_REVISION_RISK should NOT fire for far catalysts."""
        has_warn, reasons = self._call(catalyst_days=90, last_revision_pushout=True)
        labels = [w["label"] for w in reasons]
        assert "SHORT_DATED_REVISION_RISK" not in labels

    def test_stale_event_record(self):
        """STALE_EVENT_RECORD fires when last_update_age > 120."""
        has_warn, reasons = self._call(last_update_age=150)
        labels = [w["label"] for w in reasons]
        assert "STALE_EVENT_RECORD" in labels

    def test_stale_not_fired_when_fresh(self):
        """STALE_EVENT_RECORD should NOT fire for fresh records."""
        has_warn, reasons = self._call(last_update_age=30)
        labels = [w["label"] for w in reasons]
        assert "STALE_EVENT_RECORD" not in labels

    def test_source_unreliable_demote(self):
        """SOURCE_UNRELIABLE fires for DEMOTE action."""
        has_warn, reasons = self._call(source_action="DEMOTE")
        labels = [w["label"] for w in reasons]
        assert "SOURCE_UNRELIABLE" in labels

    def test_source_unreliable_suppress(self):
        """SOURCE_UNRELIABLE fires for SUPPRESS action."""
        has_warn, reasons = self._call(source_action="SUPPRESS")
        labels = [w["label"] for w in reasons]
        assert "SOURCE_UNRELIABLE" in labels

    def test_source_allow_no_warning(self):
        """SOURCE_UNRELIABLE should NOT fire for ALLOW action."""
        has_warn, reasons = self._call(source_action="ALLOW")
        labels = [w["label"] for w in reasons]
        assert "SOURCE_UNRELIABLE" not in labels

    def test_pcd_delayed(self):
        """PCD_DELAYED fires when AACT delta has delayed trials."""
        has_warn, reasons = self._call(aact_delta={"n_pcd_delayed": 2, "n_status_downgrades": 0})
        labels = [w["label"] for w in reasons]
        assert "PCD_DELAYED" in labels

    def test_status_downgrade(self):
        """STATUS_DOWNGRADE fires from AACT delta."""
        has_warn, reasons = self._call(aact_delta={"n_pcd_delayed": 0, "n_status_downgrades": 1})
        labels = [w["label"] for w in reasons]
        assert "STATUS_DOWNGRADE" in labels

    def test_multiple_warnings_combine(self):
        """Multiple warnings can fire simultaneously."""
        has_warn, reasons = self._call(
            catalyst_family="",
            precision="YEAR",
            source_action="DEMOTE",
            last_update_age=200,
        )
        labels = [w["label"] for w in reasons]
        assert "FAMILY_MISSING" in labels
        assert "LOW_CONFIDENCE_DATE" in labels
        assert "SOURCE_UNRELIABLE" in labels
        assert "STALE_EVENT_RECORD" in labels
        assert len(labels) == 4

    def test_warning_reasons_have_required_keys(self):
        """Each warning dict has label, reason, and drivers."""
        _, reasons = self._call(catalyst_family="", precision="QUARTER")
        for w in reasons:
            assert "label" in w
            assert "reason" in w
            assert "drivers" in w
            assert isinstance(w["drivers"], list)


# ---------------------------------------------------------------------------
# Bucket classification tests
# ---------------------------------------------------------------------------


class TestBucketClassification:
    def test_horizon_near(self):
        assert classify_horizon_bucket(15) == "NEAR"

    def test_horizon_medium(self):
        assert classify_horizon_bucket(60) == "MEDIUM"

    def test_horizon_far(self):
        assert classify_horizon_bucket(120) == "FAR"

    def test_horizon_boundary_near(self):
        assert classify_horizon_bucket(30) == "NEAR"

    def test_horizon_boundary_medium(self):
        assert classify_horizon_bucket(90) == "MEDIUM"

    def test_hardness_hard_flag(self):
        assert classify_hardness(True, "CTGOV_CALENDAR") == "HARD"

    def test_hardness_hard_source(self):
        assert classify_hardness(False, "SEC_8K_FILING") == "HARD"

    def test_hardness_soft(self):
        assert classify_hardness(False, "CTGOV_CALENDAR") == "SOFT"

    def test_family_bucket_known(self):
        assert classify_family_bucket("REGULATORY") == "REGULATORY"
        assert classify_family_bucket("CLINICAL") == "CLINICAL"
        assert classify_family_bucket("SAFETY") == "SAFETY"

    def test_family_bucket_unknown(self):
        assert classify_family_bucket("") == "UNKNOWN"
        assert classify_family_bucket("OTHER") == "UNKNOWN"
        assert classify_family_bucket("NO_CATALYST") == "UNKNOWN"


# ---------------------------------------------------------------------------
# Calibration curve tests
# ---------------------------------------------------------------------------


class TestCalibrationCurve:
    def test_empty_records(self):
        assert _compute_calibration_curve([]) == []

    def test_single_bin(self):
        records = [(0.75, 1), (0.72, 0), (0.78, 1)]
        curve = _compute_calibration_curve(records, n_bins=10)
        assert len(curve) == 1
        assert curve[0]["n"] == 3
        assert curve[0]["bin_lower"] == 0.7
        assert curve[0]["bin_upper"] == 0.8

    def test_multiple_bins(self):
        records = [(0.1, 0), (0.2, 0), (0.8, 1), (0.9, 1)]
        curve = _compute_calibration_curve(records, n_bins=10)
        assert len(curve) >= 2
        # Low bin should have low actual rate
        low = [c for c in curve if c["bin_lower"] <= 0.2]
        high = [c for c in curve if c["bin_lower"] >= 0.7]
        assert low and high
        assert low[0]["actual_rate"] <= high[0]["actual_rate"]

    def test_perfect_calibration(self):
        records = [(0.5, 1), (0.5, 0)]
        curve = _compute_calibration_curve(records, n_bins=10)
        assert len(curve) == 1
        assert curve[0]["actual_rate"] == 0.5
