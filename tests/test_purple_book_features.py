"""Tests for Purple Book biologics competition features — Spec 047."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.purple_book_features import (
    compute_shadow_features,
    compute_universe_shadow_features,
    get_biologic_competition,
)


def _sample_pb_data():
    """Build sample Purple Book dataset."""
    return {
        "schema": "purple_book.v1",
        "as_of_date": "2026-04-01",
        "products": [
            # Reference product: HUMIRA (AbbVie)
            {
                "bla_number": "125057",
                "product_name_proprietary": "HUMIRA",
                "product_name_nonproprietary": "adalimumab",
                "applicant": "AbbVie Inc.",
                "applicant_normalized": "AbbVie",
                "resolved_ticker": "ABBV",
                "licensing_date": "2002-12-31",
                "product_category": "Therapeutic biologics",
                "is_biosimilar": False,
                "is_interchangeable": False,
                "reference_product_bla": None,
                "exclusivity_expiry_date": "2023-01-31",
                "marketing_status": "Active",
            },
            # Biosimilar to HUMIRA: HADLIMA (Organon)
            {
                "bla_number": "761059",
                "product_name_proprietary": "HADLIMA",
                "product_name_nonproprietary": "adalimumab-bwwd",
                "applicant": "Organon LLC",
                "applicant_normalized": "Organon",
                "resolved_ticker": "OGN",
                "licensing_date": "2019-07-23",
                "is_biosimilar": True,
                "is_interchangeable": False,
                "reference_product_bla": "125057",
                "reference_product_name": "HUMIRA",
            },
            # Interchangeable to HUMIRA: CYLTEZO (Boehringer)
            {
                "bla_number": "761058",
                "product_name_proprietary": "CYLTEZO",
                "product_name_nonproprietary": "adalimumab-adbm",
                "applicant": "Boehringer Ingelheim",
                "applicant_normalized": "Boehringer Ingelheim",
                "resolved_ticker": None,
                "licensing_date": "2017-08-25",
                "is_biosimilar": True,
                "is_interchangeable": True,
                "reference_product_bla": "125057",
                "reference_product_name": "HUMIRA",
            },
            # Another biosimilar to HUMIRA: HYRIMOZ (Sandoz)
            {
                "bla_number": "761024",
                "product_name_proprietary": "HYRIMOZ",
                "product_name_nonproprietary": "adalimumab-adaz",
                "applicant": "Sandoz Inc",
                "applicant_normalized": "Sandoz",
                "resolved_ticker": None,
                "licensing_date": "2018-10-30",
                "is_biosimilar": True,
                "is_interchangeable": False,
                "reference_product_bla": "125057",
                "reference_product_name": "HUMIRA",
            },
            # Reference product: no competition (Regeneron EYLEA)
            {
                "bla_number": "125387",
                "product_name_proprietary": "EYLEA",
                "product_name_nonproprietary": "aflibercept",
                "applicant": "Regeneron Pharmaceuticals",
                "applicant_normalized": "Regeneron Pharmaceuticals",
                "resolved_ticker": "REGN",
                "licensing_date": "2011-11-18",
                "is_biosimilar": False,
                "is_interchangeable": False,
                "reference_product_bla": None,
                "exclusivity_expiry_date": "2027-05-01",
                "marketing_status": "Active",
            },
            # Small biotech with a licensed biologic, no competition
            {
                "bla_number": "999001",
                "product_name_proprietary": "TESTMAB",
                "product_name_nonproprietary": "testmab",
                "applicant": "TestBio Inc",
                "applicant_normalized": "TestBio",
                "resolved_ticker": "TSTB",
                "licensing_date": "2024-06-15",
                "is_biosimilar": False,
                "is_interchangeable": False,
                "reference_product_bla": None,
                "exclusivity_expiry_date": "2036-06-15",
                "marketing_status": "Active",
            },
            # Future product — should be PIT-excluded
            {
                "bla_number": "999099",
                "product_name_proprietary": "FUTUREMAB",
                "product_name_nonproprietary": "futuremab",
                "applicant": "TestBio Inc",
                "applicant_normalized": "TestBio",
                "resolved_ticker": "TSTB",
                "licensing_date": "2027-01-01",
                "is_biosimilar": False,
                "is_interchangeable": False,
                "reference_product_bla": None,
            },
        ],
        "reference_product_map": {
            "125057": {
                "bla_number": "125057",
                "product_name": "HUMIRA",
                "applicant": "AbbVie Inc.",
                "resolved_ticker": "ABBV",
                "licensing_date": "2002-12-31",
                "exclusivity_expiry_date": "2023-01-31",
                "biosimilars": [
                    {
                        "bla_number": "761059",
                        "product_name": "HADLIMA",
                        "applicant": "Organon LLC",
                        "licensing_date": "2019-07-23",
                    },
                    {
                        "bla_number": "761024",
                        "product_name": "HYRIMOZ",
                        "applicant": "Sandoz Inc",
                        "licensing_date": "2018-10-30",
                    },
                ],
                "interchangeables": [
                    {
                        "bla_number": "761058",
                        "product_name": "CYLTEZO",
                        "applicant": "Boehringer Ingelheim",
                        "licensing_date": "2017-08-25",
                    },
                ],
            },
            "125387": {
                "bla_number": "125387",
                "product_name": "EYLEA",
                "applicant": "Regeneron Pharmaceuticals",
                "resolved_ticker": "REGN",
                "licensing_date": "2011-11-18",
                "exclusivity_expiry_date": "2027-05-01",
                "biosimilars": [],
                "interchangeables": [],
            },
            "999001": {
                "bla_number": "999001",
                "product_name": "TESTMAB",
                "applicant": "TestBio Inc",
                "resolved_ticker": "TSTB",
                "licensing_date": "2024-06-15",
                "exclusivity_expiry_date": "2036-06-15",
                "biosimilars": [],
                "interchangeables": [],
            },
        },
    }


class TestBiosimilarCount:
    def test_abbv_has_biosimilar_competition(self):
        data = _sample_pb_data()
        result = get_biologic_competition("ABBV", "2026-04-01", data)
        assert result["is_biologic_company"] is True
        assert result["total_biosimilar_count"] == 2
        assert result["total_interchangeable_count"] == 1

    def test_regn_no_competition(self):
        data = _sample_pb_data()
        result = get_biologic_competition("REGN", "2026-04-01", data)
        assert result["is_biologic_company"] is True
        assert result["total_biosimilar_count"] == 0
        assert result["total_interchangeable_count"] == 0


class TestInterchangeableCount:
    def test_interchangeable_counted_separately(self):
        data = _sample_pb_data()
        result = get_biologic_competition("ABBV", "2026-04-01", data)
        assert result["total_interchangeable_count"] == 1
        exposure = result["biosimilar_exposure"]
        assert len(exposure) == 1
        assert exposure[0]["interchangeable_count"] == 1
        assert exposure[0]["biosimilar_count"] == 2


class TestExclusivityPITSafe:
    def test_exclusivity_expired(self):
        data = _sample_pb_data()
        result = get_biologic_competition("ABBV", "2026-04-01", data)
        assert len(result["exclusivity_status"]) == 1
        assert result["exclusivity_status"][0]["expired"] is True

    def test_exclusivity_active(self):
        data = _sample_pb_data()
        result = get_biologic_competition("REGN", "2026-04-01", data)
        assert len(result["exclusivity_status"]) == 1
        assert result["exclusivity_status"][0]["expired"] is False


class TestTickerMapping:
    def test_resolved_ticker_match(self):
        data = _sample_pb_data()
        result = get_biologic_competition("TSTB", "2026-04-01", data)
        assert result["is_biologic_company"] is True
        assert result["n_products"] >= 1


class TestEmptyMatchNeutral:
    def test_unknown_ticker(self):
        data = _sample_pb_data()
        result = get_biologic_competition("XYZZ", "2026-04-01", data)
        assert result["is_biologic_company"] is False
        assert result["n_products"] == 0
        assert result["total_biosimilar_count"] == 0

    def test_empty_data(self):
        data = {"products": [], "reference_product_map": {}}
        result = get_biologic_competition("ABBV", "2026-04-01", data)
        assert result["is_biologic_company"] is False


class TestDashboardSchema:
    def test_required_fields(self):
        data = _sample_pb_data()
        result = get_biologic_competition("ABBV", "2026-04-01", data)
        assert "ticker" in result
        assert "is_biologic_company" in result
        assert "n_products" in result
        assert "products" in result
        assert "biosimilar_exposure" in result
        assert "total_biosimilar_count" in result
        assert "total_interchangeable_count" in result
        assert "exclusivity_status" in result


class TestShadowFeatures:
    def test_abbv_features(self):
        data = _sample_pb_data()
        f = compute_shadow_features("ABBV", "2026-04-01", data)
        assert f["is_fda_licensed_biologic"] == 1
        assert f["is_reference_product"] == 1
        assert f["has_biosimilar_competition"] == 1
        assert f["has_interchangeable_competition"] == 1
        assert f["reference_product_exclusivity_expired"] == 1
        assert f["biosimilar_count"] == 2

    def test_regn_features(self):
        data = _sample_pb_data()
        f = compute_shadow_features("REGN", "2026-04-01", data)
        assert f["is_fda_licensed_biologic"] == 1
        assert f["has_biosimilar_competition"] == 0
        assert f["reference_product_exclusivity_expired"] == 0

    def test_unknown_ticker_neutral(self):
        data = _sample_pb_data()
        f = compute_shadow_features("XYZZ", "2026-04-01", data)
        assert f["is_fda_licensed_biologic"] == 0
        assert f["biosimilar_count"] == 0


class TestDeterministic:
    def test_same_inputs_same_output(self):
        data = _sample_pb_data()
        r1 = get_biologic_competition("ABBV", "2026-04-01", data)
        r2 = get_biologic_competition("ABBV", "2026-04-01", data)
        assert r1 == r2


class TestCompetitionPressureScore:
    def test_zscore_bounded(self):
        tickers = ["ABBV", "REGN", "TSTB", "XYZZ"]
        data = _sample_pb_data()
        results = compute_universe_shadow_features(tickers, "2026-04-01", data)
        for r in results:
            assert -3.0 <= r["biologic_competition_pressure_score"] <= 3.0

    def test_abbv_highest_pressure(self):
        tickers = ["ABBV", "REGN", "TSTB", "XYZZ"]
        data = _sample_pb_data()
        results = compute_universe_shadow_features(tickers, "2026-04-01", data)
        by_ticker = {r["ticker"]: r for r in results}
        # ABBV has most competition + expired exclusivity
        assert (
            by_ticker["ABBV"]["biologic_competition_pressure_score"]
            > by_ticker["REGN"]["biologic_competition_pressure_score"]
        )
        assert (
            by_ticker["ABBV"]["biologic_competition_pressure_score"]
            > by_ticker["XYZZ"]["biologic_competition_pressure_score"]
        )

    def test_single_ticker(self):
        data = _sample_pb_data()
        results = compute_universe_shadow_features(["ABBV"], "2026-04-01", data)
        assert results[0]["biologic_competition_pressure_score"] == 0.0
