"""Tests for classify_press_releases.py and fetch date extraction."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from tools.classify_press_releases import _classify_locally, _is_noise, _is_ticker_collision
from tools.fetch_company_press_releases import _extract_date_from_context

# ---------------------------------------------------------------------------
# Noise filter
# ---------------------------------------------------------------------------


class TestIsNoise:
    def test_law_firm_alert(self):
        assert _is_noise("INVESTOR ALERT: Pomerantz Law Firm Investigates Claims On Behalf of Investors")

    def test_class_action(self):
        assert _is_noise("Securities Class Action Filed Against XYZ Corp")

    def test_market_report(self):
        assert _is_noise("Lithium Metal Battery Materials Market Volume Worth 1,549,218 tons by 2035")

    def test_global_market_forecast(self):
        assert _is_noise("Global Market Research Report on Oncology Therapeutics 2025-2030")

    def test_joint_venture_analysis(self):
        assert _is_noise("Pharmaceuticals and Biotechnology Joint Venture Agreements Analysis Report 2025")

    def test_inducement_grant(self):
        assert _is_noise("4DMT Announces New Employment Inducement Grants")

    def test_hagens_berman(self):
        assert _is_noise("QURE ALERT: Hagens Berman Updates uniQure Investigation")

    def test_legitimate_clinical_not_noise(self):
        assert not _is_noise("Kodiak Sciences Announces Positive Topline Results in Phase 3 GLOW2 Trial")

    def test_legitimate_regulatory_not_noise(self):
        assert not _is_noise("FDA Approves New High Dose Regimen of SPINRAZA")

    def test_legitimate_corporate_not_noise(self):
        assert not _is_noise("Centessa Pharmaceuticals Reports Fourth Quarter Financial Results")

    def test_empty_headline(self):
        assert not _is_noise("")


# ---------------------------------------------------------------------------
# Clinical classification
# ---------------------------------------------------------------------------


class TestClassifyClinical:
    def test_phase_3_topline(self):
        r = _classify_locally("Kodiak Sciences Announces Positive Topline Results in Phase 3 GLOW2 Trial")
        assert r["event_category"] == "clinical"
        assert r["event_outcome_guess"] == "hit"
        assert r["thesis_change_flag"] is True

    def test_phase_2_data(self):
        r = _classify_locally("Maze Therapeutics Announces Positive Topline Data from Phase 2 HORIZON Trial")
        assert r["event_category"] == "clinical"

    def test_phase_1_data(self):
        r = _classify_locally("Oruka Therapeutics Announces Positive Interim Phase 1 Data for ORKA-002")
        assert r["event_category"] == "clinical"

    def test_did_not_meet_endpoint(self):
        r = _classify_locally("Theravance Biopharma Reports Phase 3 CYPRESS Study Did Not Meet Primary Endpoint")
        assert r["event_category"] == "clinical"
        assert r["event_outcome_guess"] == "miss"

    def test_pivotal_keyword(self):
        r = _classify_locally("Company Announces Pivotal Trial Results for Drug X")
        assert r["event_category"] == "clinical"

    def test_clinical_confidence(self):
        r = _classify_locally("Phase 3 data readout expected next week")
        assert r["confidence"] == 0.6


# ---------------------------------------------------------------------------
# Regulatory classification
# ---------------------------------------------------------------------------


class TestClassifyRegulatory:
    def test_fda_approval(self):
        r = _classify_locally("FDA Approves New High Dose Regimen of SPINRAZA")
        assert r["event_category"] == "regulatory"

    def test_nda_acceptance(self):
        r = _classify_locally("Celcuity Announces FDA Acceptance New Drug Application")
        assert r["event_category"] == "regulatory"

    def test_breakthrough_designation(self):
        r = _classify_locally("Cogent Biosciences Announces Breakthrough Therapy Designation")
        assert r["event_category"] == "regulatory"

    def test_complete_response_letter(self):
        r = _classify_locally("Company Receives Complete Response Letter from FDA")
        assert r["event_category"] == "regulatory"

    def test_pdufa_keyword(self):
        r = _classify_locally("PDUFA date set for May 24, 2026")
        assert r["event_category"] == "regulatory"


# ---------------------------------------------------------------------------
# M&A classification
# ---------------------------------------------------------------------------


class TestClassifyMNA:
    def test_acquisition(self):
        r = _classify_locally("Lilly to acquire Centessa Pharmaceuticals to advance treatments")
        assert r["event_category"] == "mna"
        assert r["mna_signal_flag"] is True
        assert r["exogenous_to_primary_catalyst"] is True
        assert r["severity"] == "critical"

    def test_merger(self):
        r = _classify_locally("Company X and Company Y Announce Definitive Merger Agreement")
        assert r["event_category"] == "mna"

    def test_definitive_agreement(self):
        r = _classify_locally("Company Enters Into Definitive Agreement to Be Acquired at $38 Per Share")
        assert r["event_category"] == "mna"

    def test_tender_offer(self):
        r = _classify_locally("Pfizer Commences Tender Offer for All Outstanding Shares")
        assert r["event_category"] == "mna"


# ---------------------------------------------------------------------------
# Financing classification
# ---------------------------------------------------------------------------


class TestClassifyFinancing:
    def test_public_offering(self):
        r = _classify_locally("Centessa Pharmaceuticals Announces Pricing of $250,000,000 Public Offering")
        assert r["event_category"] == "financing"
        assert r["financing_signal_flag"] is True
        assert r["price_direction_guess"] == "down"

    def test_private_placement(self):
        r = _classify_locally("Company Announces $50 Million Private Placement of Common Stock")
        assert r["event_category"] == "financing"

    def test_atm_offering(self):
        r = _classify_locally("Company Enters Into At-The-Market Offering Agreement")
        assert r["event_category"] == "financing"

    def test_registered_direct(self):
        r = _classify_locally("Company Announces Pricing of Registered Direct Offering")
        assert r["event_category"] == "financing"


# ---------------------------------------------------------------------------
# Safety classification
# ---------------------------------------------------------------------------


class TestClassifySafety:
    def test_clinical_hold(self):
        r = _classify_locally("FDA Places Partial Clinical Hold on Phase 2 Trial of Drug X")
        assert r["event_category"] == "safety"
        assert r["safety_signal_flag"] is True
        assert r["severity"] == "critical"

    def test_adverse_event(self):
        r = _classify_locally("Company Reports Serious Adverse Event in Phase 3 Trial")
        assert r["event_category"] == "safety"

    def test_voluntary_recall(self):
        r = _classify_locally("Company Announces Voluntary Recall of Product Due to Contamination")
        assert r["event_category"] == "safety"


# ---------------------------------------------------------------------------
# Default / other classification
# ---------------------------------------------------------------------------


class TestClassifyOther:
    def test_generic_corporate(self):
        r = _classify_locally("Company Provides Business Update for Q1 2026")
        assert r["event_category"] == "other"
        assert r["confidence"] == 0.3

    def test_informational_conference(self):
        r = _classify_locally("Company to Present at Upcoming Healthcare Conference in March")
        assert r["event_category"] == "other"
        assert r["informational_only"] is True
        assert r["confidence"] == 0.7

    def test_informational_financial_results(self):
        r = _classify_locally("Sionna Therapeutics Reports Fourth Quarter and Full Year 2025 Financial Results")
        assert r["event_category"] == "other"
        assert r["informational_only"] is True


# ---------------------------------------------------------------------------
# Priority order (clinical > regulatory > mna > financing > safety > other)
# ---------------------------------------------------------------------------


class TestClassificationPriority:
    def test_safety_beats_clinical(self):
        """Safety checked before clinical — 'clinical hold on Phase 2' is safety."""
        r = _classify_locally("FDA Places Clinical Hold on Phase 2 Trial")
        assert r["event_category"] == "safety"

    def test_clinical_beats_regulatory(self):
        """When headline matches both clinical and regulatory keywords, clinical wins
        because it's checked first (after safety)."""
        r = _classify_locally("FDA Accepts Phase 3 Topline Data Submission")
        assert r["event_category"] == "clinical"

    def test_informational_beats_clinical(self):
        """Informational filter runs before clinical keywords."""
        r = _classify_locally("Company to Present Phase 3 Data at Investor Conference")
        assert r["informational_only"] is True


# ---------------------------------------------------------------------------
# Date extraction from HTML context
# ---------------------------------------------------------------------------


class TestExtractDateFromContext:
    def test_time_datetime_tag(self):
        html = '<div><time datetime="2026-03-15T08:00:00Z">March 15, 2026</time> <a href="/news">Link</a></div>'
        assert _extract_date_from_context(html, html.index("href")) == "2026-03-15"

    def test_data_date_attribute(self):
        html = '<div data-publish-date="2026-04-01"><a href="/press">Press Release</a></div>'
        assert _extract_date_from_context(html, html.index("href")) == "2026-04-01"

    def test_iso_date_in_text(self):
        html = '<span>Published: 2026-03-20</span> <a href="/news">Headline</a>'
        assert _extract_date_from_context(html, html.index("href")) == "2026-03-20"

    def test_us_date_format(self):
        html = '<span>March 15, 2026</span> <a href="/news">Headline text here</a>'
        assert _extract_date_from_context(html, html.index("href")) == "2026-03-15"

    def test_us_date_no_comma(self):
        html = '<span>January 8 2026</span> <a href="/news">Headline</a>'
        assert _extract_date_from_context(html, html.index("href")) == "2026-01-08"

    def test_abbreviated_month(self):
        html = '<span>Feb 3, 2026</span> <a href="/news">Headline</a>'
        assert _extract_date_from_context(html, html.index("href")) == "2026-02-03"

    def test_no_date_returns_empty(self):
        html = '<div><a href="/news">Just a headline with no date anywhere</a></div>'
        assert _extract_date_from_context(html, html.index("href")) == ""

    def test_old_year_ignored(self):
        """Dates from old years should be ignored (not recent)."""
        html = '<span>2018-05-15</span> <a href="/news">Old news</a>'
        assert _extract_date_from_context(html, html.index("href")) == ""

    def test_priority_datetime_over_text(self):
        """datetime attribute should win over text dates."""
        html = '<time datetime="2026-03-20">March 25, 2026</time> <a href="/news">Link</a>'
        # datetime attr (2026-03-20) should beat text date (March 25)
        assert _extract_date_from_context(html, html.index("href")) == "2026-03-20"


# ---------------------------------------------------------------------------
# Ticker collision detection
# ---------------------------------------------------------------------------


class TestIsTickerCollision:
    NAMES = {
        "SION": ["sionna"],
        "ACAD": ["acadia"],
        "PHVS": ["pharvaris"],
        "KURA": ["kura", "oncology"],
        "FDMT": ["molecular"],  # "4D Molecular Therapeutics"
        "BIIB": ["biogen"],
        "BBIO": ["bridgebio"],
    }

    def test_company_name_match(self):
        assert not _is_ticker_collision("Sionna Therapeutics Reports Q4 Results", "SION", self.NAMES)

    def test_ticker_in_headline(self):
        assert not _is_ticker_collision("BIIB Reports Strong Earnings", "BIIB", self.NAMES)

    def test_true_collision_market_report(self):
        assert _is_ticker_collision(
            "Lithium Metal Battery Materials Market Volume Worth 1,549,218 tons by 2035",
            "SION",
            self.NAMES,
        )

    def test_true_collision_unrelated_company(self):
        assert _is_ticker_collision(
            "Eclipse Group showcases new electric vehicles at auto show 2026",
            "KURA",
            self.NAMES,
        )

    def test_brand_name_not_flagged(self):
        """4DMT is FDMT's brand — headline starts with brand, should not be flagged."""
        assert not _is_ticker_collision(
            "4DMT Completes Enrollment for 4FRONT-1 Phase 3 Clinical Trial",
            "FDMT",
            self.NAMES,
        )

    def test_no_company_registered(self):
        """Unknown ticker — assume not a collision."""
        assert not _is_ticker_collision("Something about UNKNOWN ticker", "ZZZZ", self.NAMES)

    def test_drug_name_headline(self):
        """BridgeBio's drug BBP-418 — company name not in headline but biotech content."""
        assert not _is_ticker_collision(
            "BBP-418 Demonstrates Consistent Efficacy and Favorable Safety Profile in Phase 3",
            "BBIO",
            self.NAMES,
        )

    def test_techbob_collision(self):
        assert _is_ticker_collision(
            "Techbob Academy Launches Tech Elite Incubation Program",
            "ACAD",
            self.NAMES,
        )
