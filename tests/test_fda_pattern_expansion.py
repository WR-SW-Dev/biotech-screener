#!/usr/bin/env python3
"""
Unit tests for expanded FDA patterns in SEC 8-K catalyst collector.

Tests _extract_timing_events and _extract_downside_events directly against
new FDA-specific regex patterns added for PDUFA/ADCOM capture uplift.
"""

from datetime import date

from wake_robin_data_pipeline.collectors.sec_8k_catalyst_collector import (
    PATTERN_VERSION,
    _extract_downside_events,
    _extract_timing_events,
)

# Common test fixtures
AS_OF = date(2026, 2, 13)
FILING_DATE = "2026-01-15"


class TestFDATimingPatterns:
    """Tests for new FDA timing patterns in TIMING_PATTERNS."""

    def test_fda_action_date_day(self):
        """'FDA action date of March 15, 2026' → FDA_PDUFA_DATE, DAY."""
        text = "The Company announced that the FDA action date of March 15, 2026 has been confirmed."
        events = _extract_timing_events(text, "AAAA", FILING_DATE, AS_OF)
        fda = [e for e in events if e["event_type"] == "FDA_PDUFA_DATE"]
        assert len(fda) >= 1
        assert fda[0]["date_precision"] == "DAY"
        assert fda[0]["event_date"] == "2026-03-15"
        assert fda[0]["confidence"] == "HIGH"

    def test_fda_target_action_date(self):
        """'FDA target action date set for June 30, 2026' → FDA_PDUFA_DATE, DAY."""
        text = "The FDA target action date set for June 30, 2026 under the PDUFA."
        events = _extract_timing_events(text, "BBBB", FILING_DATE, AS_OF)
        fda = [e for e in events if e["event_type"] == "FDA_PDUFA_DATE"]
        assert len(fda) >= 1
        assert fda[0]["event_date"] == "2026-06-30"

    def test_nda_accepted_pdufa(self):
        """'NDA accepted...PDUFA date of April 3, 2026' → FDA_PDUFA_DATE, DAY."""
        text = "The NDA was accepted for review with a PDUFA date of April 3, 2026."
        events = _extract_timing_events(text, "CCCC", FILING_DATE, AS_OF)
        fda = [e for e in events if e["event_type"] == "FDA_PDUFA_DATE"]
        assert len(fda) >= 1
        assert fda[0]["date_precision"] == "DAY"
        assert fda[0]["event_date"] == "2026-04-03"

    def test_bla_pdufa_date(self):
        """'BLA...PDUFA date is August 22, 2026' → FDA_PDUFA_DATE, DAY."""
        text = "Following BLA acceptance, the PDUFA date is August 22, 2026."
        events = _extract_timing_events(text, "DDDD", FILING_DATE, AS_OF)
        fda = [e for e in events if e["event_type"] == "FDA_PDUFA_DATE"]
        assert len(fda) >= 1
        assert fda[0]["event_date"] == "2026-08-22"

    def test_pdufa_full_name(self):
        """'Prescription Drug User Fee Act date of March 15, 2026' → FDA_PDUFA_DATE, DAY."""
        text = "The Prescription Drug User Fee Act date of March 15, 2026 is the target."
        events = _extract_timing_events(text, "EEEE", FILING_DATE, AS_OF)
        fda = [e for e in events if e["event_type"] == "FDA_PDUFA_DATE"]
        assert len(fda) >= 1
        assert fda[0]["date_precision"] == "DAY"
        assert fda[0]["event_date"] == "2026-03-15"

    def test_regulatory_decision_quarter(self):
        """'regulatory decision expected in Q2 2026' → FDA_PDUFA_DATE, QUARTER."""
        text = "A regulatory decision is expected in Q2 2026 for the lead compound."
        events = _extract_timing_events(text, "FFFF", FILING_DATE, AS_OF)
        fda = [e for e in events if e["event_type"] == "FDA_PDUFA_DATE"]
        assert len(fda) >= 1
        assert fda[0]["date_precision"] == "QUARTER"
        assert fda[0]["event_date"] == "2026-04-01"
        assert fda[0]["event_date_end"] == "2026-06-30"

    def test_fda_approval_quarter(self):
        """'FDA approval expected in Q2 2026' → FDA_PDUFA_DATE, QUARTER."""
        text = "FDA approval is expected in Q2 2026 based on the review timeline."
        events = _extract_timing_events(text, "GGGG", FILING_DATE, AS_OF)
        fda = [e for e in events if e["event_type"] == "FDA_PDUFA_DATE"]
        assert len(fda) >= 1
        assert fda[0]["date_precision"] == "QUARTER"
        assert fda[0]["confidence"] == "MED"

    def test_fda_approval_half_year(self):
        """'approval anticipated second half of 2026' → FDA_PDUFA_DATE, HALF_YEAR."""
        text = "FDA approval is anticipated in the second half of 2026."
        events = _extract_timing_events(text, "HHHH", FILING_DATE, AS_OF)
        fda = [e for e in events if e["event_type"] == "FDA_PDUFA_DATE"]
        assert len(fda) >= 1
        assert fda[0]["date_precision"] == "HALF_YEAR"
        assert fda[0]["event_date"] == "2026-07-01"
        assert fda[0]["event_date_end"] == "2026-12-31"
        assert fda[0]["confidence"] == "LOW"

    def test_advisory_committee_day(self):
        """'Advisory Committee meeting on July 17, 2026' → FDA_ADCOM, DAY."""
        text = "The FDA Advisory Committee meeting on July 17, 2026 will review the application."
        events = _extract_timing_events(text, "IIII", FILING_DATE, AS_OF)
        adcom = [e for e in events if e["event_type"] == "FDA_ADCOM"]
        assert len(adcom) >= 1
        assert adcom[0]["date_precision"] == "DAY"
        assert adcom[0]["event_date"] == "2026-07-17"

    def test_adcom_quarter(self):
        """'ADCOM meeting expected in Q3 2026' → FDA_ADCOM, QUARTER."""
        text = "An ADCOM meeting is expected in Q3 2026 to discuss the filing."
        events = _extract_timing_events(text, "JJJJ", FILING_DATE, AS_OF)
        adcom = [e for e in events if e["event_type"] == "FDA_ADCOM"]
        assert len(adcom) >= 1
        assert adcom[0]["date_precision"] == "QUARTER"
        assert adcom[0]["event_date"] == "2026-07-01"
        assert adcom[0]["event_date_end"] == "2026-09-30"

    def test_no_false_positive_boilerplate(self):
        """FDA mentions in forward-looking disclaimers NOT matched."""
        text = (
            "Some preamble text about the company. "
            "Forward-looking statements: This press release contains forward-looking "
            "statements. There can be no assurance that FDA approval will be obtained. "
            "FDA action date risks include regulatory decision expected in Q1 2027."
        )
        # _extract_timing_events does not strip boilerplate (that's done in the
        # calling code flow); the test below confirms the _strip_boilerplate path
        # eliminates false positives from forward-looking disclaimers.
        from wake_robin_data_pipeline.collectors.sec_8k_catalyst_collector import _strip_boilerplate

        clean = _strip_boilerplate(text)
        events_clean = _extract_timing_events(clean, "KKKK", FILING_DATE, AS_OF)
        fda = [e for e in events_clean if e["event_type"] in ("FDA_PDUFA_DATE", "FDA_ADCOM")]
        assert len(fda) == 0, f"Should not match FDA patterns in boilerplate, got: {fda}"

    def test_existing_pdufa_pattern_still_works(self):
        """Regression: original PDUFA pattern 'PDUFA date of ...' still matches."""
        text = "The PDUFA date of September 10, 2026 has been assigned."
        events = _extract_timing_events(text, "LLLL", FILING_DATE, AS_OF)
        fda = [e for e in events if e["event_type"] == "FDA_PDUFA_DATE"]
        assert len(fda) >= 1
        assert fda[0]["date_precision"] == "DAY"
        assert fda[0]["event_date"] == "2026-09-10"


class TestFDADownsidePatterns:
    """Tests for new FDA downside patterns in DOWNSIDE_PATTERNS."""

    def test_refuse_to_file_downside(self):
        """'refused to file' → FDA_RTF, HIGH confidence."""
        text = "The FDA refused to file the Company's NDA submission for drug X."
        events = _extract_downside_events(text, "MMMM", FILING_DATE)
        rtf = [e for e in events if e["event_type"] == "FDA_RTF"]
        assert len(rtf) == 1
        assert rtf[0]["confidence"] == "HIGH"
        assert "sec_8k" in rtf[0]["tags"]
        assert "downside" in rtf[0]["tags"]

    def test_refuse_to_file_capitalized(self):
        """'Refuse to File' (capitalized) → FDA_RTF."""
        text = "The Company received a Refuse to File letter from the FDA."
        events = _extract_downside_events(text, "NNNN", FILING_DATE)
        rtf = [e for e in events if e["event_type"] == "FDA_RTF"]
        assert len(rtf) == 1

    def test_fda_warning_letter(self):
        """'FDA warning letter' → FDA_WARNING_LETTER, MED confidence."""
        text = "The Company disclosed receiving an FDA warning letter regarding manufacturing."
        events = _extract_downside_events(text, "OOOO", FILING_DATE)
        wl = [e for e in events if e["event_type"] == "FDA_WARNING_LETTER"]
        assert len(wl) == 1
        assert wl[0]["confidence"] == "MED"

    def test_warning_letter_in_boilerplate_filtered(self):
        """FDA warning letter after boilerplate marker is stripped."""
        text = (
            "Some real content here. "
            "Forward-looking statements: risks include FDA warning letter "
            "and other regulatory actions."
        )
        from wake_robin_data_pipeline.collectors.sec_8k_catalyst_collector import _strip_boilerplate

        clean = _strip_boilerplate(text)
        events = _extract_downside_events(clean, "PPPP", FILING_DATE)
        wl = [e for e in events if e["event_type"] == "FDA_WARNING_LETTER"]
        assert len(wl) == 0


class TestReviewWindowPatterns:
    """Tests for review-window-change patterns (extended / Class 2 resubmission)."""

    def test_lantheus_three_month_extension_day(self):
        """Lantheus-style: 'three-month extension ... June 29, 2026' → extended/DAY."""
        text = (
            "Lantheus today announced that the FDA has extended the PDUFA target action date "
            "by three months, resulting in a three-month extension of the review period to "
            "June 29, 2026."
        )
        events = _extract_timing_events(text, "LNTH", FILING_DATE, AS_OF)
        ext = [e for e in events if e.get("event_status") == "extended"]
        assert len(ext) >= 1
        assert ext[0]["event_date"] == "2026-06-29"
        assert ext[0]["date_precision"] == "DAY"
        assert ext[0]["confidence"] == "HIGH"
        assert "review_window_change" in ext[0]["tags"]
        assert ext[0]["source"] == "SEC_8K_FILING"

    def test_review_period_extended_phrasing(self):
        """'review period has been extended ... new action date of August 22, 2026'."""
        text = (
            "Capricor announced that the FDA review period has been extended, with a new "
            "action date of August 22, 2026, following submission of additional CMC data."
        )
        events = _extract_timing_events(text, "CAPR", FILING_DATE, AS_OF)
        ext = [e for e in events if e.get("event_status") == "extended"]
        assert len(ext) >= 1
        assert ext[0]["event_date"] == "2026-08-22"

    def test_new_pdufa_date_phrase(self):
        """'new PDUFA date of June 29, 2026' → extended."""
        text = "Following the major amendment, the new PDUFA date of June 29, 2026 has been assigned."
        events = _extract_timing_events(text, "TICK", FILING_DATE, AS_OF)
        ext = [e for e in events if e.get("event_status") == "extended"]
        assert len(ext) >= 1
        assert ext[0]["event_date"] == "2026-06-29"

    def test_revised_pdufa_date_phrase(self):
        """'revised PDUFA date is September 10, 2026' → extended."""
        text = "The revised PDUFA date is September 10, 2026 per FDA notice."
        events = _extract_timing_events(text, "TICK", FILING_DATE, AS_OF)
        ext = [e for e in events if e.get("event_status") == "extended"]
        assert len(ext) >= 1
        assert ext[0]["event_date"] == "2026-09-10"

    def test_class_2_resubmission_phrase(self):
        """'Class 2 resubmission ... PDUFA date of June 5, 2026' → resubmission_accepted."""
        text = (
            "The FDA accepted the NDA as a Class 2 resubmission with a six-month review "
            "period and a PDUFA date of June 5, 2026."
        )
        events = _extract_timing_events(text, "ARVN", FILING_DATE, AS_OF)
        resub = [e for e in events if e.get("event_status") == "resubmission_accepted"]
        assert len(resub) >= 1
        assert any(e["event_date"] == "2026-06-05" for e in resub)
        assert any("class_2_resubmission" in e["tags"] or "six_month_review" in e["tags"] for e in resub)

    def test_pdufa_goal_date_phrase(self):
        """'PDUFA goal date of November 1, 2026' → upcoming, DAY."""
        text = "The PDUFA goal date of November 1, 2026 has been confirmed by the agency."
        events = _extract_timing_events(text, "TICK", FILING_DATE, AS_OF)
        fda = [e for e in events if e["event_type"] == "FDA_PDUFA_DATE" and e["event_date"] == "2026-11-01"]
        assert len(fda) >= 1
        assert fda[0]["date_precision"] == "DAY"
        assert fda[0]["confidence"] == "HIGH"

    def test_target_action_date_phrase(self):
        """'target action date of September 27, 2026' → upcoming, DAY."""
        text = "Praxis announced FDA acceptance with a target action date of September 27, 2026."
        events = _extract_timing_events(text, "PRAX", FILING_DATE, AS_OF)
        fda = [e for e in events if e["event_type"] == "FDA_PDUFA_DATE" and e["event_date"] == "2026-09-27"]
        assert len(fda) >= 1

    def test_prior_date_extracted_from_explicit_phrasing(self):
        """When 'from {old} to {new}' is present, prior_date is captured for extended events."""
        text = (
            "The FDA extended the PDUFA target action date from March 29, 2026 to "
            "June 29, 2026 following a major amendment to the application."
        )
        events = _extract_timing_events(text, "LNTH", FILING_DATE, AS_OF)
        ext = [e for e in events if e.get("event_status") == "extended" and e["event_date"] == "2026-06-29"]
        assert len(ext) >= 1
        # at least one of the extended-tagged events should carry the prior date
        assert any(
            e.get("prior_date") == "2026-03-29" for e in ext
        ), f"Expected prior_date=2026-03-29 in at least one extended event; got: {ext}"

    def test_extended_priority_in_tags(self):
        """An 'extended' event includes review_window_change tag."""
        text = "FDA extended the review period to August 1, 2026 per agency notice."
        events = _extract_timing_events(text, "TICK", FILING_DATE, AS_OF)
        ext = [e for e in events if e.get("event_status") == "extended"]
        assert len(ext) >= 1
        assert "review_window_change" in ext[0]["tags"]

    def test_fresh_pdufa_marked_upcoming(self):
        """A plain 'PDUFA date of ...' (no extension wording) is event_status='upcoming'."""
        text = "The FDA has assigned a PDUFA date of October 15, 2026."
        events = _extract_timing_events(text, "TICK", FILING_DATE, AS_OF)
        fresh = [e for e in events if e["event_type"] == "FDA_PDUFA_DATE" and e["event_date"] == "2026-10-15"]
        assert len(fresh) >= 1
        # at least one match has event_status="upcoming"
        assert any(e.get("event_status") == "upcoming" for e in fresh)


class TestPatternVersion:
    """Verify PATTERN_VERSION changed from pre-expansion value."""

    def test_pattern_version_changes(self):
        """PATTERN_VERSION differs from prior cached value (b2bdaf75)."""
        # b2bdaf75 was the live cache version before the review-window expansion.
        OLD_PATTERN_VERSION = "b2bdaf75"
        assert PATTERN_VERSION != OLD_PATTERN_VERSION, (
            f"PATTERN_VERSION should have changed after adding new patterns, " f"still {PATTERN_VERSION}"
        )

    def test_pattern_version_is_hex_string(self):
        """PATTERN_VERSION is an 8-char hex string."""
        assert len(PATTERN_VERSION) == 8
        int(PATTERN_VERSION, 16)  # Should not raise


class TestCacheFallback:
    """Tests for cache discoverability: primary dir → fallback dir."""

    def test_8k_cache_found_in_primary(self, tmp_path):
        """8-K collection uses primary cache dir when file exists there."""
        import json

        from wake_robin_data_pipeline.collectors.sec_8k_catalyst_collector import (
            _versioned_cache_path,
            collect_8k_timing_events,
        )

        cache_dir = tmp_path / "primary"
        cache_dir.mkdir()

        as_of = date(2026, 2, 7)
        cached = [{"ticker": "TEST", "event_type": "DATA_READOUT", "event_date": "2026-06-01"}]
        cache_path = _versioned_cache_path(cache_dir, as_of)
        with open(cache_path, "w") as f:
            json.dump(cached, f)

        result = collect_8k_timing_events(
            universe=[{"ticker": "TEST"}],
            as_of_date=as_of,
            cache_dir=cache_dir,
        )
        assert len(result) == 1
        assert result[0]["ticker"] == "TEST"

    def test_multi_form_cache_found_in_primary(self, tmp_path):
        """Multi-form collection uses primary cache dir when file exists there."""
        import json

        from wake_robin_data_pipeline.collectors.sec_8k_catalyst_collector import (
            _multi_form_cache_path,
            collect_sec_filing_events,
        )

        cache_dir = tmp_path / "primary"
        cache_dir.mkdir()

        as_of = date(2026, 2, 7)
        cached = [
            {
                "ticker": "FOLD",
                "event_type": "FDA_PDUFA_DATE",
                "event_date": "2026-09-01",
                "filing_form": "10-Q",
                "source": "SEC_10Q_FILING",
            }
        ]
        cache_path = _multi_form_cache_path(cache_dir, as_of)
        with open(cache_path, "w") as f:
            json.dump(cached, f)

        result = collect_sec_filing_events(
            universe=[{"ticker": "FOLD"}],
            as_of_date=as_of,
            cache_dir=cache_dir,
        )
        assert len(result) == 1
        assert result[0]["ticker"] == "FOLD"
        assert result[0]["filing_form"] == "10-Q"
