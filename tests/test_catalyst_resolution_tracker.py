"""Tests for Catalyst Resolution Tracker (Spec 042) — Phase 1 schemas + detection."""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.catalyst_resolution_tracker import ResolutionRecord, build_watchlist, classify_outcome, compute_record_hash

# --- Schema tests ---


class TestResolutionRecordSchema:
    def test_valid_record_roundtrips(self):
        r = ResolutionRecord(
            ticker="PVLA",
            catalyst_date="2026-04-15",
            catalyst_type="PHASE_3_READOUT",
            catalyst_description="Phase 3 topline readout",
            resolution_date="2026-04-15",
            outcome="HIT",
            outcome_detail="Primary endpoint met",
            source_type="SEC_8K",
            source_id="8K_2026-04-15_PVLA",
            prediction_snapshot_date="2026-04-01",
            prediction_dem_rank=14,
            price_t_minus_1=12.50,
            price_t_0=18.75,
            price_t_plus_5=None,
            days_from_expected=0,
            as_of_date="2026-04-16",
        )
        d = r.to_dict()
        assert d["ticker"] == "PVLA"
        assert d["outcome"] == "HIT"
        assert d["schema_version"] == "1.0.0"

    def test_invalid_outcome_raises(self):
        try:
            ResolutionRecord(
                ticker="TEST",
                catalyst_date="2026-04-01",
                catalyst_type="PDUFA_ACTION",
                resolution_date="2026-04-01",
                outcome="INVALID",
                source_type="SEC_8K",
                source_id="test",
                as_of_date="2026-04-02",
            )
            assert False, "Should have raised ValueError"
        except ValueError:
            pass

    def test_invalid_catalyst_type_raises(self):
        try:
            ResolutionRecord(
                ticker="TEST",
                catalyst_date="2026-04-01",
                catalyst_type="MADE_UP_TYPE",
                resolution_date="2026-04-01",
                outcome="HIT",
                source_type="SEC_8K",
                source_id="test",
                as_of_date="2026-04-02",
            )
            assert False, "Should have raised ValueError"
        except ValueError:
            pass

    def test_invalid_source_type_raises(self):
        try:
            ResolutionRecord(
                ticker="TEST",
                catalyst_date="2026-04-01",
                catalyst_type="PDUFA_ACTION",
                resolution_date="2026-04-01",
                outcome="HIT",
                source_type="TWITTER",
                source_id="test",
                as_of_date="2026-04-02",
            )
            assert False, "Should have raised ValueError"
        except ValueError:
            pass


class TestRecordHash:
    def test_hash_is_deterministic(self):
        r = ResolutionRecord(
            ticker="BIIB",
            catalyst_date="2026-05-24",
            catalyst_type="PDUFA_ACTION",
            resolution_date="2026-05-24",
            outcome="HIT",
            source_type="FDA_ACTION",
            source_id="fda_2026-05-24_BIIB",
            as_of_date="2026-05-25",
        )
        h1 = compute_record_hash(r)
        h2 = compute_record_hash(r)
        assert h1 == h2
        assert len(h1) == 64  # SHA256 hex

    def test_different_outcomes_different_hash(self):
        base = dict(
            ticker="TEST",
            catalyst_date="2026-04-01",
            catalyst_type="PDUFA_ACTION",
            resolution_date="2026-04-01",
            source_type="SEC_8K",
            source_id="test",
            as_of_date="2026-04-02",
        )
        r1 = ResolutionRecord(outcome="HIT", **base)
        r2 = ResolutionRecord(outcome="MISS", **base)
        assert compute_record_hash(r1) != compute_record_hash(r2)


# --- Watchlist tests ---


class TestBuildWatchlist:
    def _make_event(self, ticker, catalyst_date_str, catalyst_type="PHASE_3_READOUT"):
        return {
            "ticker": ticker,
            "catalyst_date": catalyst_date_str,
            "catalyst_type": catalyst_type,
        }

    def test_includes_events_in_window(self):
        events = [
            self._make_event("PVLA", "2026-04-10"),  # 5 days ago from as_of
            self._make_event("BIIB", "2026-04-20"),  # 5 days in future
        ]
        wl = build_watchlist(events, date(2026, 4, 15), existing_resolutions=set())
        tickers = {w["ticker"] for w in wl}
        assert "PVLA" in tickers
        assert "BIIB" in tickers

    def test_excludes_events_outside_window(self):
        events = [
            self._make_event("OLD", "2025-01-01"),  # way too old
            self._make_event("FAR", "2027-01-01"),  # way too far
        ]
        wl = build_watchlist(events, date(2026, 4, 15), existing_resolutions=set())
        assert len(wl) == 0

    def test_excludes_already_resolved(self):
        events = [self._make_event("PVLA", "2026-04-10")]
        resolved = {("PVLA", "2026-04-10")}
        wl = build_watchlist(events, date(2026, 4, 15), existing_resolutions=resolved)
        assert len(wl) == 0

    def test_window_boundaries(self):
        # T-30 (just inside), T-31 (just outside), T+7 (just inside), T+8 (just outside)
        as_of = date(2026, 4, 15)
        events = [
            self._make_event("A", "2026-03-16"),  # -30d, inside
            self._make_event("B", "2026-03-15"),  # -31d, outside
            self._make_event("C", "2026-04-22"),  # +7d, inside
            self._make_event("D", "2026-04-23"),  # +8d, outside
        ]
        wl = build_watchlist(events, as_of, existing_resolutions=set())
        tickers = {w["ticker"] for w in wl}
        assert "A" in tickers
        assert "B" not in tickers
        assert "C" in tickers
        assert "D" not in tickers


# --- Outcome classification tests ---


class TestClassifyOutcome:
    def test_pdufa_approved(self):
        assert classify_outcome("PDUFA_ACTION", fda_action="APPROVED") == "HIT"

    def test_pdufa_crl(self):
        assert classify_outcome("PDUFA_ACTION", fda_action="CRL") == "MISS"

    def test_pdufa_unknown_action(self):
        assert classify_outcome("PDUFA_ACTION", fda_action=None) == "NEEDS_REVIEW"

    def test_phase3_positive_headline(self):
        assert (
            classify_outcome(
                "PHASE_3_READOUT",
                headline="Company announces positive topline results from Phase 3 trial",
            )
            == "HIT"
        )

    def test_phase3_met_endpoint(self):
        assert (
            classify_outcome(
                "PHASE_3_READOUT",
                headline="Trial met primary endpoint with statistical significance",
            )
            == "HIT"
        )

    def test_phase3_failed(self):
        assert (
            classify_outcome(
                "PHASE_3_READOUT",
                headline="Phase 3 trial did not meet primary endpoint",
            )
            == "MISS"
        )

    def test_phase3_discontinued(self):
        assert (
            classify_outcome(
                "PHASE_2_READOUT",
                headline="Company announces discontinuation of Phase 2 program",
            )
            == "MISS"
        )

    def test_ambiguous_headline(self):
        assert (
            classify_outcome(
                "PHASE_3_READOUT",
                headline="Company provides business update and financial results",
            )
            == "NEEDS_REVIEW"
        )

    def test_ctgov_completed(self):
        assert (
            classify_outcome(
                "PHASE_3_READOUT",
                ctgov_status_from="ACTIVE_NOT_RECRUITING",
                ctgov_status_to="COMPLETED",
            )
            == "NEEDS_REVIEW"
        )
        # CT.gov completion alone doesn't tell us HIT/MISS — need headline

    def test_ctgov_terminated(self):
        assert (
            classify_outcome(
                "PHASE_3_READOUT",
                ctgov_status_from="RECRUITING",
                ctgov_status_to="TERMINATED",
            )
            == "MISS"
        )

    def test_ctgov_withdrawn(self):
        assert (
            classify_outcome(
                "PHASE_2_READOUT",
                ctgov_status_from="NOT_YET_RECRUITING",
                ctgov_status_to="WITHDRAWN",
            )
            == "MISS"
        )
