"""Tests for Spec 071 Lane 1 (CTGOV withdrawn/approved status hard-reject)
and Spec 078 catalyst quality gate (Lanes A + B).

Covers:
  1. Spec 071 Lane 1: CTGovStatus.is_lane1_reject property unit tests
  2. Spec 071 Lane 1: detect_calendar_catalysts skips lane-1 statuses
  3. Spec 071 Lane 1: detect_readout_window_catalysts skips lane-1 statuses
  4. Spec 071 Lane 1: regression NCT IDs (JAZZ/FATE/ELDN/NVAX/IBRX) are WITHDRAWN
  5. classify_catalyst_quality() unit tests (run_screen.py helper)
  6. module_3_catalyst.py Lane A guard (non-binary corporate event suppression)
  7. Snapshot smoke test: current snapshot catalyst_quality distribution
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from catalyst_diagnostics import detect_calendar_catalysts, detect_readout_window_catalysts
from ctgov_adapter import CanonicalTrialRecord, CTGovStatus
from run_screen import (
    _CATALYST_QUALITY_CONF_THRESHOLD,
    _CATALYST_QUALITY_EXEMPT_SOURCES,
    _NON_BINARY_CATALYST_EVENT_TYPES,
    classify_catalyst_quality,
)
from state_management import StateSnapshot

# ---------------------------------------------------------------------------
# Spec 071 Lane 1 helpers
# ---------------------------------------------------------------------------

_TRIAL_RECORDS_PATH = Path(__file__).resolve().parent.parent / "production_data" / "trial_records.json"

_LANE1_REJECT_STATUSES = {
    CTGovStatus.WITHDRAWN,
    CTGovStatus.TERMINATED,
    CTGovStatus.SUSPENDED,
    CTGovStatus.APPROVED_FOR_MARKETING,
    CTGovStatus.NO_LONGER_AVAILABLE,
}

_LANE1_PASS_STATUSES = {
    CTGovStatus.RECRUITING,
    CTGovStatus.ACTIVE_NOT_RECRUITING,
    CTGovStatus.NOT_YET_RECRUITING,
    CTGovStatus.COMPLETED,
}

# Audit-confirmed withdrawn NCT IDs (spec_071 §4.3)
_WITHDRAWN_NCT_AUDIT = {
    "NCT06217536": "JAZZ",
    "NCT05934097": "FATE",
    "NCT04711226": "ELDN",
    "NCT06482359": "NVAX",
    "NCT05007769": "IBRX",
}


def _make_canonical(
    ticker: str,
    nct_id: str,
    status: CTGovStatus,
    pcd: date,
) -> CanonicalTrialRecord:
    return CanonicalTrialRecord(
        ticker=ticker,
        nct_id=nct_id,
        overall_status=status,
        last_update_posted=date(2026, 1, 1),
        primary_completion_date=pcd,
        primary_completion_type=None,
        completion_date=None,
        completion_type=None,
        results_first_posted=None,
    )


def _snapshot(records: list) -> StateSnapshot:
    return StateSnapshot(snapshot_date=date(2026, 5, 6), records=records)


# ---------------------------------------------------------------------------
# 1. Spec 071 Lane 1 — CTGovStatus.is_lane1_reject property
# ---------------------------------------------------------------------------


class TestLane1RejectProperty:
    """Unit tests for CTGovStatus.is_lane1_reject."""

    def test_withdrawn_is_rejected(self):
        assert CTGovStatus.WITHDRAWN.is_lane1_reject is True

    def test_terminated_is_rejected(self):
        assert CTGovStatus.TERMINATED.is_lane1_reject is True

    def test_suspended_is_rejected(self):
        assert CTGovStatus.SUSPENDED.is_lane1_reject is True

    def test_approved_for_marketing_is_rejected(self):
        assert CTGovStatus.APPROVED_FOR_MARKETING.is_lane1_reject is True

    def test_no_longer_available_is_rejected(self):
        assert CTGovStatus.NO_LONGER_AVAILABLE.is_lane1_reject is True

    def test_recruiting_is_not_rejected(self):
        assert CTGovStatus.RECRUITING.is_lane1_reject is False

    def test_active_not_recruiting_is_not_rejected(self):
        assert CTGovStatus.ACTIVE_NOT_RECRUITING.is_lane1_reject is False

    def test_completed_is_not_rejected(self):
        assert CTGovStatus.COMPLETED.is_lane1_reject is False

    def test_not_yet_recruiting_is_not_rejected(self):
        assert CTGovStatus.NOT_YET_RECRUITING.is_lane1_reject is False

    def test_all_reject_statuses_covered(self):
        for s in _LANE1_REJECT_STATUSES:
            assert s.is_lane1_reject is True, f"{s} should be rejected"

    def test_pass_statuses_not_rejected(self):
        for s in _LANE1_PASS_STATUSES:
            assert s.is_lane1_reject is False, f"{s} should not be rejected"


# ---------------------------------------------------------------------------
# 2. Spec 071 Lane 1 — detect_calendar_catalysts skips rejected statuses
# ---------------------------------------------------------------------------


class TestLane1CalendarCatalystFilter:
    """detect_calendar_catalysts must not emit catalysts for lane-1-rejected trials."""

    AS_OF = date(2026, 5, 6)
    FUTURE_PCD = date(2026, 8, 1)  # 87 days out — inside the 90d window

    def test_withdrawn_trial_emits_no_calendar_catalyst(self):
        rec = _make_canonical("FAKE", "NCT99000001", CTGovStatus.WITHDRAWN, self.FUTURE_PCD)
        snap = _snapshot([rec])
        result = detect_calendar_catalysts(snap, self.AS_OF)
        assert result == [], "WITHDRAWN trial must not emit calendar catalyst"

    def test_terminated_trial_emits_no_calendar_catalyst(self):
        rec = _make_canonical("FAKE", "NCT99000002", CTGovStatus.TERMINATED, self.FUTURE_PCD)
        snap = _snapshot([rec])
        result = detect_calendar_catalysts(snap, self.AS_OF)
        assert result == [], "TERMINATED trial must not emit calendar catalyst"

    def test_approved_for_marketing_emits_no_calendar_catalyst(self):
        rec = _make_canonical("FAKE", "NCT99000003", CTGovStatus.APPROVED_FOR_MARKETING, self.FUTURE_PCD)
        snap = _snapshot([rec])
        result = detect_calendar_catalysts(snap, self.AS_OF)
        assert result == [], "APPROVED_FOR_MARKETING trial must not emit calendar catalyst"

    def test_no_longer_available_emits_no_calendar_catalyst(self):
        rec = _make_canonical("FAKE", "NCT99000004", CTGovStatus.NO_LONGER_AVAILABLE, self.FUTURE_PCD)
        snap = _snapshot([rec])
        result = detect_calendar_catalysts(snap, self.AS_OF)
        assert result == [], "NO_LONGER_AVAILABLE trial must not emit calendar catalyst"

    def test_recruiting_trial_emits_calendar_catalyst(self):
        """Negative control: valid active trial must still emit."""
        rec = _make_canonical("FAKE", "NCT99000010", CTGovStatus.RECRUITING, self.FUTURE_PCD)
        snap = _snapshot([rec])
        result = detect_calendar_catalysts(snap, self.AS_OF)
        assert len(result) >= 1, "RECRUITING trial with future PCD must emit calendar catalyst"

    def test_all_lane1_reject_statuses_suppressed(self):
        records = [
            _make_canonical("FAKE", f"NCT990000{i:02d}", status, self.FUTURE_PCD)
            for i, status in enumerate(_LANE1_REJECT_STATUSES)
        ]
        snap = _snapshot(records)
        result = detect_calendar_catalysts(snap, self.AS_OF)
        assert result == [], f"Expected no catalysts for all lane-1 statuses, got {result}"


# ---------------------------------------------------------------------------
# 3. Spec 071 Lane 1 — detect_readout_window_catalysts skips rejected statuses
# ---------------------------------------------------------------------------


class TestLane1ReadoutWindowFilter:
    """detect_readout_window_catalysts must not emit catalysts for lane-1-rejected trials."""

    AS_OF = date(2026, 5, 6)
    PAST_PCD = date(2026, 2, 1)  # 94 days ago — inside the default 365-day readout window

    def test_withdrawn_trial_emits_no_readout_window_catalyst(self):
        rec = _make_canonical("FAKE", "NCT99001001", CTGovStatus.WITHDRAWN, self.PAST_PCD)
        snap = _snapshot([rec])
        result = detect_readout_window_catalysts(snap, self.AS_OF)
        assert result == [], "WITHDRAWN trial must not emit readout-window catalyst"

    def test_approved_for_marketing_emits_no_readout_window_catalyst(self):
        rec = _make_canonical("FAKE", "NCT99001002", CTGovStatus.APPROVED_FOR_MARKETING, self.PAST_PCD)
        snap = _snapshot([rec])
        result = detect_readout_window_catalysts(snap, self.AS_OF)
        assert result == [], "APPROVED_FOR_MARKETING trial must not emit readout-window catalyst"

    def test_no_longer_available_emits_no_readout_window_catalyst(self):
        rec = _make_canonical("FAKE", "NCT99001003", CTGovStatus.NO_LONGER_AVAILABLE, self.PAST_PCD)
        snap = _snapshot([rec])
        result = detect_readout_window_catalysts(snap, self.AS_OF)
        assert result == [], "NO_LONGER_AVAILABLE trial must not emit readout-window catalyst"


# ---------------------------------------------------------------------------
# 4. Spec 071 Lane 1 — regression: audit-confirmed NCT IDs are WITHDRAWN
# ---------------------------------------------------------------------------


class TestLane1AuditRegressionNctIds:
    """Real-data regression: the 5 audit-confirmed NCT IDs must be WITHDRAWN in production_data."""

    @classmethod
    def _load_index(cls) -> dict[str, str]:
        if not _TRIAL_RECORDS_PATH.exists():
            return {}
        data = json.loads(_TRIAL_RECORDS_PATH.read_text())
        return {r["nct_id"]: r.get("status", "") for r in data if "nct_id" in r}

    def test_jazz_nct06217536_is_withdrawn(self):
        idx = self._load_index()
        if not idx:
            return
        assert (
            idx.get("NCT06217536", "").upper() == "WITHDRAWN"
        ), "JAZZ NCT06217536 must be WITHDRAWN in trial_records.json"

    def test_fate_nct05934097_is_withdrawn(self):
        idx = self._load_index()
        if not idx:
            return
        assert (
            idx.get("NCT05934097", "").upper() == "WITHDRAWN"
        ), "FATE NCT05934097 must be WITHDRAWN in trial_records.json"

    def test_eldn_nct04711226_is_withdrawn(self):
        idx = self._load_index()
        if not idx:
            return
        assert (
            idx.get("NCT04711226", "").upper() == "WITHDRAWN"
        ), "ELDN NCT04711226 must be WITHDRAWN in trial_records.json"

    def test_nvax_nct06482359_is_withdrawn(self):
        idx = self._load_index()
        if not idx:
            return
        assert (
            idx.get("NCT06482359", "").upper() == "WITHDRAWN"
        ), "NVAX NCT06482359 must be WITHDRAWN in trial_records.json"

    def test_ibrx_nct05007769_is_withdrawn(self):
        idx = self._load_index()
        if not idx:
            return
        assert (
            idx.get("NCT05007769", "").upper() == "WITHDRAWN"
        ), "IBRX NCT05007769 must be WITHDRAWN in trial_records.json"

    def test_all_audit_nct_ids_present(self):
        idx = self._load_index()
        if not idx:
            return
        missing = [nct for nct in _WITHDRAWN_NCT_AUDIT if nct not in idx]
        assert not missing, f"Audit NCT IDs missing from trial_records.json: {missing}"

    def test_is_lane1_reject_covers_withdrawn(self):
        """CTGovStatus.from_string('WITHDRAWN') must be lane-1-rejected."""
        status = CTGovStatus.from_string("WITHDRAWN")
        assert status.is_lane1_reject is True


# ---------------------------------------------------------------------------
# 5. classify_catalyst_quality unit tests (Spec 078)
# ---------------------------------------------------------------------------


class TestClassifyCatalystQuality:
    """Unit tests for the Spec 078 catalyst quality classification function."""

    # --- No catalyst ---

    def test_empty_inputs_returns_empty(self):
        assert classify_catalyst_quality("", "", "") == ""

    def test_none_like_inputs_returns_empty(self):
        assert classify_catalyst_quality(None, None, None) == ""  # type: ignore[arg-type]

    # --- Lane A: non-binary corporate event types ---

    def test_earnings_release_is_corporate_update(self):
        assert classify_catalyst_quality("CORPORATE_CALENDAR", "EARNINGS_RELEASE", "0.80") == "corporate_update"

    def test_investor_day_is_corporate_update(self):
        assert classify_catalyst_quality("CORPORATE_CALENDAR", "INVESTOR_DAY", "0.75") == "corporate_update"

    def test_partnership_is_corporate_update(self):
        assert classify_catalyst_quality("CORPORATE_EVENT", "PARTNERSHIP", "0.70") == "corporate_update"

    def test_ma_activity_is_corporate_update(self):
        assert classify_catalyst_quality("CORPORATE_EVENT", "MA_ACTIVITY", "0.65") == "corporate_update"

    def test_licensing_deal_is_corporate_update(self):
        assert classify_catalyst_quality("CORPORATE_EVENT", "LICENSING_DEAL", "0.60") == "corporate_update"

    def test_conference_presentation_is_corporate_update(self):
        assert classify_catalyst_quality("CORPORATE_CALENDAR", "CONFERENCE_PRESENTATION", "0.75") == "corporate_update"

    def test_ir_event_is_corporate_update(self):
        assert classify_catalyst_quality("CORPORATE_CALENDAR", "IR_EVENT", "0.80") == "corporate_update"

    def test_press_release_event_is_corporate_update(self):
        assert classify_catalyst_quality("CORPORATE_CALENDAR", "PRESS_RELEASE_EVENT", "0.70") == "corporate_update"

    def test_lane_a_takes_precedence_over_exempt_source(self):
        """Lane A fires even if source would be exempt — event type wins."""
        assert classify_catalyst_quality("SEC_8K_FILING", "EARNINGS_RELEASE", "0.90") == "corporate_update"

    # --- Lane B: low calendar confidence for non-exempt sources ---

    def test_low_confidence_ctgov_is_low_confidence(self):
        conf = str(_CATALYST_QUALITY_CONF_THRESHOLD - 0.01)
        assert classify_catalyst_quality("CTGOV_CALENDAR", "CT_PRIMARY_COMPLETION", conf) == "low_confidence"

    def test_exactly_at_threshold_is_not_flagged(self):
        """Threshold is exclusive: conf == threshold → NOT low_confidence."""
        conf = str(_CATALYST_QUALITY_CONF_THRESHOLD)
        result = classify_catalyst_quality("CTGOV_CALENDAR", "CT_PRIMARY_COMPLETION", conf)
        assert result != "low_confidence"

    def test_exempt_source_not_flagged_at_low_confidence(self):
        """PDUFA_MANUAL is exempt from Lane B regardless of confidence value."""
        conf = str(_CATALYST_QUALITY_CONF_THRESHOLD - 0.01)
        assert classify_catalyst_quality("PDUFA_MANUAL", "FDA_PDUFA_DATE", conf) == "binary_alpha"

    def test_sec_8k_not_flagged_at_low_confidence(self):
        conf = str(_CATALYST_QUALITY_CONF_THRESHOLD - 0.01)
        assert classify_catalyst_quality("SEC_8K_FILING", "DATA_READOUT", conf) == "binary_alpha"

    def test_zero_confidence_non_exempt_is_not_low_confidence(self):
        """conf == 0.0 is treated as missing — does not trigger low_confidence gate."""
        result = classify_catalyst_quality("CTGOV_CALENDAR", "CT_PRIMARY_COMPLETION", "0.0")
        assert result != "low_confidence"
        assert result == "registry_only"

    # --- Binary alpha ---

    def test_pdufa_manual_is_binary_alpha(self):
        assert classify_catalyst_quality("PDUFA_MANUAL", "FDA_PDUFA_DATE", "0.75") == "binary_alpha"

    def test_fda_adcom_calendar_is_binary_alpha(self):
        assert classify_catalyst_quality("FDA_ADCOM_CALENDAR", "FDA_ADCOM", "0.95") == "binary_alpha"

    def test_sec_8k_filing_is_binary_alpha(self):
        assert classify_catalyst_quality("SEC_8K_FILING", "DATA_READOUT", "0.90") == "binary_alpha"

    def test_sec_6k_filing_is_binary_alpha(self):
        assert classify_catalyst_quality("SEC_6K_FILING", "DATA_READOUT", "0.85") == "binary_alpha"

    # --- Registry only ---

    def test_ctgov_calendar_is_registry_only(self):
        assert classify_catalyst_quality("CTGOV_CALENDAR", "CT_PRIMARY_COMPLETION", "0.75") == "registry_only"

    def test_ctgov_pcd_far_is_registry_only(self):
        assert classify_catalyst_quality("CTGOV_PCD_FAR", "CT_PRIMARY_COMPLETION", "0.45") == "registry_only"

    # --- Exempt sources set completeness ---

    def test_all_exempt_sources_defined(self):
        expected = {"PDUFA_MANUAL", "FDA_ADCOM_CALENDAR", "SEC_8K_FILING", "SEC_6K_FILING"}
        assert expected == set(_CATALYST_QUALITY_EXEMPT_SOURCES)

    # --- Non-binary types set completeness ---

    def test_all_non_binary_types_defined(self):
        expected = {
            "EARNINGS_RELEASE",
            "INVESTOR_DAY",
            "PARTNERSHIP",
            "MA_ACTIVITY",
            "LICENSING_DEAL",
            "CONFERENCE_PRESENTATION",
            "CONFERENCE_LATE_BREAKER",
            "CONFERENCE_ACCEPTED_ABSTRACT",
            "IR_EVENT",
            "PRESS_RELEASE_EVENT",
        }
        assert expected == set(_NON_BINARY_CATALYST_EVENT_TYPES)


# ---------------------------------------------------------------------------
# 2. module_3_catalyst.py Lane A guard
# ---------------------------------------------------------------------------


class TestLaneAGuardInModule3:
    """Lane A: non-binary corporate events must be rejected in convert_corporate_catalyst_to_v2."""

    def _make_event(self, event_type: str, ticker: str = "TEST") -> dict:
        return {
            "ticker": ticker,
            "event_type": event_type,
            "event_date": "2026-08-01",
            "confidence": "HIGH",
        }

    def test_earnings_release_returns_none(self):
        from datetime import date

        from module_3_catalyst import convert_corporate_catalyst_to_v2

        result = convert_corporate_catalyst_to_v2(self._make_event("EARNINGS_RELEASE"), date(2026, 5, 6))
        assert result is None, "EARNINGS_RELEASE should be suppressed by Lane A guard"

    def test_investor_day_returns_none(self):
        from datetime import date

        from module_3_catalyst import convert_corporate_catalyst_to_v2

        result = convert_corporate_catalyst_to_v2(self._make_event("INVESTOR_DAY"), date(2026, 5, 6))
        assert result is None, "INVESTOR_DAY should be suppressed by Lane A guard"

    def test_partnership_returns_none(self):
        from datetime import date

        from module_3_catalyst import convert_corporate_catalyst_to_v2

        result = convert_corporate_catalyst_to_v2(self._make_event("PARTNERSHIP"), date(2026, 5, 6))
        assert result is None

    def test_ma_activity_returns_none(self):
        from datetime import date

        from module_3_catalyst import convert_corporate_catalyst_to_v2

        result = convert_corporate_catalyst_to_v2(self._make_event("MA_ACTIVITY"), date(2026, 5, 6))
        assert result is None

    def test_pdufa_date_is_not_suppressed(self):
        """FDA_PDUFA_DATE is a binary event — must NOT be suppressed."""
        from datetime import date

        from module_3_catalyst import convert_corporate_catalyst_to_v2

        result = convert_corporate_catalyst_to_v2(self._make_event("FDA_PDUFA_DATE"), date(2026, 5, 6))
        assert result is not None, "FDA_PDUFA_DATE must not be suppressed by Lane A guard"

    def test_data_readout_is_not_suppressed(self):
        """DATA_READOUT is a binary event — must NOT be suppressed."""
        from datetime import date

        from module_3_catalyst import convert_corporate_catalyst_to_v2

        result = convert_corporate_catalyst_to_v2(self._make_event("DATA_READOUT"), date(2026, 5, 6))
        assert result is not None, "DATA_READOUT must not be suppressed by Lane A guard"

    def test_unknown_event_type_returns_none_via_existing_guard(self):
        """CORPORATE_UPDATE is not in EventType — already caught by existing guard."""
        from datetime import date

        from module_3_catalyst import convert_corporate_catalyst_to_v2

        result = convert_corporate_catalyst_to_v2(self._make_event("CORPORATE_UPDATE"), date(2026, 5, 6))
        assert result is None, "CORPORATE_UPDATE must be rejected (not in EventType enum)"


# ---------------------------------------------------------------------------
# 3. Snapshot smoke test
# ---------------------------------------------------------------------------


class TestSnapshotCatalystQuality:
    """Smoke tests against the current production snapshot."""

    SNAPSHOT = Path(__file__).resolve().parent.parent / "data" / "snapshots" / "2026-05-06" / "rankings.csv"

    def _load(self):
        import csv

        if not self.SNAPSHOT.exists():
            return None
        rows = []
        with open(self.SNAPSHOT, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
        return rows

    def test_no_corporate_update_in_binary_now_build_window(self):
        """Lane A: no corporate_update event type currently earns binary_now/build_window."""
        rows = self._load()
        if rows is None:
            return  # snapshot not present in CI
        violations = [
            r
            for r in rows
            if r.get("catalyst_event_type", "") in _NON_BINARY_CATALYST_EVENT_TYPES
            and r.get("catalyst_bucket", "") in {"binary_now", "build_window"}
        ]
        assert (
            violations == []
        ), f"Lane A violation: {len(violations)} non-binary event(s) in binary_now/build_window:\n" + "\n".join(
            f"  {r['ticker']} {r['catalyst_event_type']} {r['catalyst_bucket']}" for r in violations
        )

    def test_no_low_confidence_in_binary_now_build_window(self):
        """Lane B: no calendar_confidence < threshold for non-exempt sources in binary tier."""
        rows = self._load()
        if rows is None:
            return
        violations = []
        for r in rows:
            src = r.get("catalyst_source", "")
            bucket = r.get("catalyst_bucket", "")
            if bucket not in {"binary_now", "build_window"}:
                continue
            if src in _CATALYST_QUALITY_EXEMPT_SOURCES:
                continue
            conf_str = r.get("calendar_confidence", "")
            try:
                conf = float(conf_str) if conf_str else 0.0
            except ValueError:
                conf = 0.0
            if 0.0 < conf < _CATALYST_QUALITY_CONF_THRESHOLD:
                violations.append(r)
        assert (
            violations == []
        ), f"Lane B violation: {len(violations)} non-exempt source(s) with low confidence in binary tier"

    def test_binary_alpha_tickers_have_hard_catalyst_sources(self):
        """Binary alpha quality should correspond to hard catalyst sources."""
        rows = self._load()
        if rows is None:
            return
        for r in rows:
            quality = classify_catalyst_quality(
                r.get("catalyst_source", ""),
                r.get("catalyst_event_type", ""),
                r.get("calendar_confidence", ""),
            )
            if quality == "binary_alpha":
                src = r.get("catalyst_source", "")
                assert (
                    src in _CATALYST_QUALITY_EXEMPT_SOURCES
                ), f"binary_alpha assigned to non-exempt source {src!r} for {r.get('ticker')}"
