"""Tests for FDA AdCom voting-pattern pilot features."""

from common.adcom_vote_features import (
    ADCOM_VOTE_COLUMNS,
    COMMITTEE_BASE_RATES,
    DEFAULT_BASE_RATE,
    build_adcom_vote_lookup,
    classify_signal,
    compute_adcom_vote_features,
    score_committee,
)


def _adcom_event(
    ticker="ACME",
    event_date="2026-06-15",
    committee="Oncologic Drugs Advisory Committee",
    disclosed_at="2026-01-01",
):
    return {
        "ticker": ticker,
        "event_date": event_date,
        "committee": committee,
        "disclosed_at": disclosed_at,
        "event_type": "FDA_ADCOM",
        "source": "FEDERAL_REGISTER",
    }


# ---------------------------------------------------------------------------
# 1. score_committee
# ---------------------------------------------------------------------------


class TestScoreCommittee:
    def test_known_committee(self):
        assert score_committee("Oncologic Drugs Advisory Committee") == 0.63

    def test_vaccines_committee(self):
        assert score_committee("Vaccines and Related Biological Products Advisory Committee") == 0.80

    def test_unknown_committee_gets_default(self):
        assert score_committee("Brand New Committee") == DEFAULT_BASE_RATE

    def test_empty_string_gets_default(self):
        assert score_committee("") == DEFAULT_BASE_RATE

    def test_all_rates_between_0_and_1(self):
        for name, rate in COMMITTEE_BASE_RATES.items():
            assert 0.0 < rate < 1.0, f"{name} rate {rate} out of range"


# ---------------------------------------------------------------------------
# 2. classify_signal
# ---------------------------------------------------------------------------


class TestClassifySignal:
    def test_high(self):
        assert classify_signal(0.80) == "HIGH"
        assert classify_signal(0.75) == "HIGH"

    def test_med(self):
        assert classify_signal(0.70) == "MED"
        assert classify_signal(0.60) == "MED"

    def test_low(self):
        assert classify_signal(0.58) == "LOW"
        assert classify_signal(0.50) == "LOW"


# ---------------------------------------------------------------------------
# 3. compute_adcom_vote_features
# ---------------------------------------------------------------------------


class TestComputeAdcomVoteFeatures:
    def test_basic_oncology(self):
        events = [_adcom_event()]
        result = compute_adcom_vote_features("ACME", events, "2026-03-01")
        assert result["adcom_vote_score"] == 0.63
        assert result["adcom_vote_signal"] == "MED"
        assert result["adcom_vote_n"] == 0
        assert result["adcom_vote_recency_days"] == 106  # 2026-03-01 → 2026-06-15
        assert result["adcom_vote_basis"] == "committee_prior"

    def test_vaccines_high_signal(self):
        events = [
            _adcom_event(
                committee="Vaccines and Related Biological Products Advisory Committee",
                event_date="2026-04-01",
            )
        ]
        result = compute_adcom_vote_features("ACME", events, "2026-03-01")
        assert result["adcom_vote_score"] == 0.80
        assert result["adcom_vote_signal"] == "HIGH"

    def test_no_events_returns_empty(self):
        result = compute_adcom_vote_features("ACME", [], "2026-03-01")
        assert all(result[col] == "" for col in ADCOM_VOTE_COLUMNS)

    def test_wrong_ticker_returns_empty(self):
        events = [_adcom_event(ticker="OTHER")]
        result = compute_adcom_vote_features("ACME", events, "2026-03-01")
        assert result["adcom_vote_score"] == ""

    def test_past_event_ignored(self):
        events = [_adcom_event(event_date="2026-02-01")]  # before as_of
        result = compute_adcom_vote_features("ACME", events, "2026-03-01")
        assert result["adcom_vote_score"] == ""

    def test_pit_safety_future_disclosure_excluded(self):
        events = [_adcom_event(disclosed_at="2026-04-01")]  # disclosed after as_of
        result = compute_adcom_vote_features("ACME", events, "2026-03-01")
        assert result["adcom_vote_score"] == ""

    def test_event_today_included(self):
        events = [_adcom_event(event_date="2026-03-01")]
        result = compute_adcom_vote_features("ACME", events, "2026-03-01")
        assert result["adcom_vote_recency_days"] == 0
        assert result["adcom_vote_score"] == 0.63

    def test_nearest_event_chosen(self):
        events = [
            _adcom_event(event_date="2026-08-01"),  # farther
            _adcom_event(event_date="2026-04-01"),  # nearer
        ]
        result = compute_adcom_vote_features("ACME", events, "2026-03-01")
        assert result["adcom_vote_recency_days"] == 31  # to 2026-04-01

    def test_beyond_relevance_window_excluded(self):
        # 181 days out
        events = [_adcom_event(event_date="2026-09-15")]
        result = compute_adcom_vote_features("ACME", events, "2026-03-18")
        # 2026-03-18 to 2026-09-15 = 181 days > 180
        assert result["adcom_vote_score"] == ""

    def test_at_relevance_boundary_included(self):
        # Exactly 180 days
        events = [_adcom_event(event_date="2026-09-14")]
        result = compute_adcom_vote_features("ACME", events, "2026-03-18")
        # 2026-03-18 to 2026-09-14 = 180 days
        assert result["adcom_vote_score"] == 0.63

    def test_case_insensitive_ticker(self):
        events = [_adcom_event(ticker="acme")]
        result = compute_adcom_vote_features("ACME", events, "2026-03-01")
        assert result["adcom_vote_score"] == 0.63

    def test_bad_date_returns_empty(self):
        events = [_adcom_event()]
        result = compute_adcom_vote_features("ACME", events, "not-a-date")
        assert result["adcom_vote_score"] == ""

    def test_output_columns_match_spec(self):
        events = [_adcom_event()]
        result = compute_adcom_vote_features("ACME", events, "2026-03-01")
        assert set(result.keys()) == set(ADCOM_VOTE_COLUMNS)


# ---------------------------------------------------------------------------
# 4. build_adcom_vote_lookup
# ---------------------------------------------------------------------------


class TestBuildAdcomVoteLookup:
    def test_multiple_tickers(self):
        events = [
            _adcom_event(ticker="AAA", event_date="2026-04-01"),
            _adcom_event(ticker="BBB", event_date="2026-05-01"),
        ]
        lookup = build_adcom_vote_lookup(events, "2026-03-01")
        assert "AAA" in lookup
        assert "BBB" in lookup
        assert lookup["AAA"]["adcom_vote_recency_days"] == 31
        assert lookup["BBB"]["adcom_vote_recency_days"] == 61

    def test_empty_events(self):
        assert build_adcom_vote_lookup([], "2026-03-01") == {}

    def test_no_as_of_date(self):
        events = [_adcom_event()]
        assert build_adcom_vote_lookup(events, "") == {}

    def test_ticker_without_upcoming_excluded(self):
        events = [_adcom_event(event_date="2026-02-01")]  # past
        lookup = build_adcom_vote_lookup(events, "2026-03-01")
        assert lookup == {}

    def test_lookup_keys_are_uppercase(self):
        events = [_adcom_event(ticker="acme", event_date="2026-04-01")]
        lookup = build_adcom_vote_lookup(events, "2026-03-01")
        assert "ACME" in lookup
