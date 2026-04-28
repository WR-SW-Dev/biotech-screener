"""Tests for 6-K coverage in collect_8k_timing_events extractors.

Phase 2 step 2: the producer was 8-K-only and silently excluded foreign
private issuers (TEVA, AZN, BNTX, ARGX, ASND, …) which file on 6-K. The
extractor now accepts a `form` kwarg that drives event_name prefix and
source label via FORM_TO_SOURCE.
"""

from __future__ import annotations

from datetime import date

from wake_robin_data_pipeline.collectors.sec_8k_catalyst_collector import (
    FORM_TO_SOURCE,
    _extract_downside_events,
    _extract_timing_events,
    collect_8k_timing_events,
    reset_extraction_diagnostics,
)

AS_OF = date(2026, 4, 28)
FILING = "2026-04-15"


class TestTimingExtractorFormParam:
    def setup_method(self):
        reset_extraction_diagnostics()

    def test_8k_default_unchanged(self):
        text = "The FDA has assigned a PDUFA date of May 15, 2026 for " "the Company's NDA submission."
        events = _extract_timing_events(text, "ACME", FILING, AS_OF)
        assert events
        ev = events[0]
        assert ev["source"] == "SEC_8K_FILING"
        assert ev["event_name"].startswith("8-K:")

    def test_6k_form_emits_sec_6k_filing(self):
        text = "The Company expects topline results in Q3 2026 from its " "pivotal Phase 2 trial in solid tumors."
        events = _extract_timing_events(text, "TEVA", FILING, AS_OF, form="6-K")
        assert events
        ev = events[0]
        assert ev["source"] == "SEC_6K_FILING"
        assert ev["event_name"].startswith("6-K:")
        # Schema fields unchanged otherwise
        assert ev["event_type"] == "DATA_READOUT"
        assert ev["disclosed_at"] == FILING
        assert "sec_8k" in ev["tags"]  # universal tag preserved across forms

    def test_unknown_form_falls_back_to_8k_source(self):
        text = "PDUFA date of June 1, 2026 has been assigned."
        events = _extract_timing_events(text, "ACME", FILING, AS_OF, form="20-F")
        assert events
        # Unknown form: source falls back to SEC_8K_FILING per FORM_TO_SOURCE.get default
        assert events[0]["source"] == "SEC_8K_FILING"
        # event_name still uses the literal form passed in (not falsified to 8-K)
        assert events[0]["event_name"].startswith("20-F:")


class TestDownsideExtractorFormParam:
    def test_8k_default_unchanged(self):
        text = "The Company received a Complete Response Letter (CRL) from the FDA."
        events = _extract_downside_events(text, "ACME", FILING)
        assert events
        ev = events[0]
        assert ev["source"] == "SEC_8K_FILING"
        assert ev["event_name"].startswith("8-K:")
        assert "downside" in ev["tags"]

    def test_6k_downside_emits_sec_6k_filing(self):
        text = (
            "The FDA has placed the Company's Phase 3 trial of BNT-123 "
            "on clinical hold pending review of safety data."
        )
        events = _extract_downside_events(text, "BNTX", FILING, form="6-K")
        assert events
        ev = events[0]
        assert ev["source"] == "SEC_6K_FILING"
        assert ev["event_name"].startswith("6-K:")
        assert ev["event_type"] == "CLINICAL_HOLD"


class TestFormToSourceMapping:
    def test_6k_and_amended_share_source_label(self):
        assert FORM_TO_SOURCE["6-K"] == "SEC_6K_FILING"
        assert FORM_TO_SOURCE["6-K/A"] == "SEC_6K_FILING"

    def test_8k_unchanged(self):
        assert FORM_TO_SOURCE["8-K"] == "SEC_8K_FILING"


class TestCollectFormsSignature:
    def test_default_forms_includes_6k(self):
        import inspect

        sig = inspect.signature(collect_8k_timing_events)
        forms_default = sig.parameters["forms"].default
        assert "8-K" in forms_default
        assert "6-K" in forms_default

    def test_8k_first_in_iteration_order(self):
        """8-K must precede 6-K so domestic filings win on accession dedupe."""
        import inspect

        sig = inspect.signature(collect_8k_timing_events)
        forms_default = list(sig.parameters["forms"].default)
        assert forms_default.index("8-K") < forms_default.index("6-K")
