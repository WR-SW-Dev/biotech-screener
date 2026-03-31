"""Tests for Spec 041 — deadline-constrained milestone optionality."""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.milestone_optionality import (
    MilestoneInput,
    MilestoneResult,
    _estimate_completion_months,
    _normalize_phase,
    compute_milestone_features,
    z_score_overlay,
)


def _dummy_pos_fn(phase: str, endpoint: str = "other"):
    lookup = {"phase1": 0.05, "phase2": 0.25, "phase3": 0.53, "nda": 0.85, "unknown": 0.10}
    p = _normalize_phase(phase)
    return {"pos_prior": lookup.get(p, 0.10)}


class TestDeadlineMissingNeutral:
    def test_no_milestones_returns_zero(self):
        r = compute_milestone_features("TEST", [], date(2026, 3, 31))
        assert r.milestone_deadline_ev_pct == 0.0
        assert r.milestone_count_active == 0
        assert r.milestone_deadline_mode == "none"

    def test_past_deadline_returns_zero(self):
        m = MilestoneInput("phase3_data", deadline_date=date(2025, 1, 1), phase="phase3")
        r = compute_milestone_features("TEST", [m], date(2026, 3, 31))
        assert r.milestone_count_active == 0
        assert r.milestone_deadline_ev_pct == 0.0


class TestFixedDeadlineBeforeBaseCasePenalized:
    def test_tight_timeline_lower_than_ample(self):
        tight = MilestoneInput("phase3_data", deadline_date=date(2027, 1, 1), phase="phase3")
        ample = MilestoneInput("phase3_data", deadline_date=date(2032, 1, 1), phase="phase3")
        r_tight = compute_milestone_features("T1", [tight], date(2026, 3, 31), pos_prior_fn=_dummy_pos_fn)
        r_ample = compute_milestone_features("T2", [ample], date(2026, 3, 31), pos_prior_fn=_dummy_pos_fn)
        assert r_tight.milestone_deadline_ev_pct < r_ample.milestone_deadline_ev_pct


class TestMoreSlackMonotonic:
    def test_slack_increases_score(self):
        scores = []
        for extra_years in [0, 1, 2, 3]:
            dl = date(2027, 3, 31) + __import__("datetime").timedelta(days=extra_years * 365)
            m = MilestoneInput("phase3_data", deadline_date=dl, phase="phase3")
            r = compute_milestone_features("T", [m], date(2026, 3, 31), pos_prior_fn=_dummy_pos_fn)
            scores.append(r.milestone_deadline_ev_pct)
        for i in range(len(scores) - 1):
            assert scores[i] <= scores[i + 1] + 1e-9, f"Not monotonic: {scores}"


class TestCorrPenaltyMonotonic:
    def test_more_milestones_lower_per_milestone_credit(self):
        base_m = MilestoneInput("phase3_data", deadline_date=date(2030, 1, 1), phase="phase3")
        r1 = compute_milestone_features("T", [base_m], date(2026, 3, 31), pos_prior_fn=_dummy_pos_fn)
        r3 = compute_milestone_features("T", [base_m, base_m, base_m], date(2026, 3, 31), pos_prior_fn=_dummy_pos_fn)
        # 3 identical milestones should NOT give 3x the EV (correlation penalty)
        assert r3.milestone_deadline_ev_pct < r1.milestone_deadline_ev_pct * 3


class TestContractualPayoutWeightApplied:
    def test_higher_payout_higher_ev(self):
        m_low = MilestoneInput("approval", deadline_date=date(2030, 1, 1), phase="nda", payout_value=2.0)
        m_high = MilestoneInput("approval", deadline_date=date(2030, 1, 1), phase="nda", payout_value=8.0)
        r_low = compute_milestone_features("T", [m_low], date(2026, 3, 31), pos_prior_fn=_dummy_pos_fn)
        r_high = compute_milestone_features("T", [m_high], date(2026, 3, 31), pos_prior_fn=_dummy_pos_fn)
        assert r_high.milestone_deadline_ev_pct > r_low.milestone_deadline_ev_pct


class TestNonContractProxyWeightApplied:
    def test_approval_worth_more_than_phase1(self):
        m_appr = MilestoneInput("approval", deadline_date=date(2030, 1, 1), phase="nda")
        m_p1 = MilestoneInput("phase1_data", deadline_date=date(2030, 1, 1), phase="phase1")
        r_appr = compute_milestone_features("T", [m_appr], date(2026, 3, 31), pos_prior_fn=_dummy_pos_fn)
        r_p1 = compute_milestone_features("T", [m_p1], date(2026, 3, 31), pos_prior_fn=_dummy_pos_fn)
        assert r_appr.milestone_deadline_ev_pct > r_p1.milestone_deadline_ev_pct


class TestSafetyFlagBounded:
    def test_haircut_capped(self):
        m = MilestoneInput("phase3_data", deadline_date=date(2030, 1, 1), phase="phase3")
        r = compute_milestone_features(
            "T", [m], date(2026, 3, 31), pos_prior_fn=_dummy_pos_fn, safety_haircut=0.50, execution_haircut=0.50
        )
        # Should be capped at 0.25 + 0.20 = 0.45, so w_risk = 0.55
        assert r.milestone_deadline_ev_pct > 0  # not zeroed out


class TestShrinkageRespectsSupport:
    def test_no_pos_fn_uses_fallback(self):
        m = MilestoneInput("phase3_data", deadline_date=date(2030, 1, 1), phase="phase3")
        r = compute_milestone_features("T", [m], date(2026, 3, 31), pos_prior_fn=None)
        # Falls back to p_base=0.10
        assert r.milestone_pos_by_deadline_raw == 0.10


class TestSchemaVersionStamped:
    def test_version_present(self):
        r = compute_milestone_features("T", [], date(2026, 3, 31))
        assert r.schema_version == "milestone_optionality.v1"


class TestAsOfOnlyNoFutureDeadlines:
    def test_past_milestones_excluded(self):
        past = MilestoneInput("approval", deadline_date=date(2025, 6, 1), phase="nda")
        future = MilestoneInput("phase3_data", deadline_date=date(2028, 1, 1), phase="phase3")
        r = compute_milestone_features("T", [past, future], date(2026, 3, 31), pos_prior_fn=_dummy_pos_fn)
        assert r.milestone_count_active == 1


class TestSnapshotRebuildIdentical:
    def test_deterministic(self):
        m = MilestoneInput("phase3_data", deadline_date=date(2029, 6, 1), phase="phase3")
        r1 = compute_milestone_features("T", [m], date(2026, 3, 31), pos_prior_fn=_dummy_pos_fn)
        r2 = compute_milestone_features("T", [m], date(2026, 3, 31), pos_prior_fn=_dummy_pos_fn)
        assert r1.to_dict() == r2.to_dict()


class TestUnknownMilestoneTypeNeutral:
    def test_unknown_type_uses_default_weight(self):
        m = MilestoneInput("mystery_event", deadline_date=date(2030, 1, 1), phase="unknown")
        r = compute_milestone_features("T", [m], date(2026, 3, 31), pos_prior_fn=_dummy_pos_fn)
        assert r.milestone_value_weight == 0.25  # default


class TestZScoreOverlay:
    def test_z_scores_center_on_zero(self):
        results = {}
        for i, ev in enumerate([5.0, 10.0, 15.0, 20.0, 25.0]):
            r = MilestoneResult(ticker=f"T{i}", milestone_count_active=1, milestone_deadline_ev_pct=ev)
            results[f"T{i}"] = r
        z_score_overlay(results)
        z_vals = [r.milestone_deadline_overlay_z for r in results.values()]
        assert abs(sum(z_vals)) < 0.01

    def test_inactive_tickers_unchanged(self):
        results = {
            "ACTIVE": MilestoneResult(ticker="ACTIVE", milestone_count_active=2, milestone_deadline_ev_pct=10.0),
            "INACTIVE": MilestoneResult(ticker="INACTIVE", milestone_count_active=0, milestone_deadline_ev_pct=0.0),
        }
        z_score_overlay(results)
        assert results["INACTIVE"].milestone_deadline_overlay_z == 0.0


class TestDesignationAcceleration:
    def test_btd_reduces_completion_time(self):
        months_no_btd = _estimate_completion_months("phase3")
        months_btd = _estimate_completion_months("phase3", has_btd=True)
        assert months_btd < months_no_btd

    def test_btd_increases_ev(self):
        m = MilestoneInput("phase3_data", deadline_date=date(2030, 1, 1), phase="phase3")
        r_no = compute_milestone_features("T", [m], date(2026, 3, 31), pos_prior_fn=_dummy_pos_fn, designations=[])
        r_btd = compute_milestone_features(
            "T", [m], date(2026, 3, 31), pos_prior_fn=_dummy_pos_fn, designations=["BTD"]
        )
        assert r_btd.milestone_deadline_ev_pct >= r_no.milestone_deadline_ev_pct


class TestHardDeadlineMode:
    def test_hard_sets_fixed_deadline_mode(self):
        m = MilestoneInput("approval", deadline_date=date(2027, 6, 1), phase="nda", is_hard_deadline=True)
        r = compute_milestone_features("T", [m], date(2026, 3, 31))
        assert r.milestone_deadline_mode == "fixed_deadline"

    def test_soft_sets_dated_event_mode(self):
        m = MilestoneInput("phase3_data", deadline_date=date(2028, 1, 1), phase="phase3", is_hard_deadline=False)
        r = compute_milestone_features("T", [m], date(2026, 3, 31))
        assert r.milestone_deadline_mode == "dated_event"
