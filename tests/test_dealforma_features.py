"""Tests for DealForma deal comp features — Spec 046."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.dealforma_features import (
    _cutoff_date,
    _recency_weight,
    compute_shadow_features,
    compute_universe_shadow_features,
    get_deal_comps,
)


def _sample_comps():
    """Build a sample comps dataset for testing."""
    return {
        "schema": "dealforma_comps.v1",
        "as_of_date": "2026-04-01",
        "deals": [
            {
                "deal_id": "d001",
                "deal_type": "M&A",
                "announcement_date": "2025-09-15",
                "acquirer": "Pfizer",
                "target": "TargetCo A",
                "target_ticker": "TGTA",
                "therapeutic_area": "Oncology",
                "stage": "phase_2",
                "modality": "antibody",
                "biological_target": "HER2",
                "upfront_value_mm": 500.0,
                "total_value_mm": 1200.0,
                "has_cvr": True,
                "has_earnout": False,
                "revenue_multiple": None,
            },
            {
                "deal_id": "d002",
                "deal_type": "licensing",
                "announcement_date": "2025-11-01",
                "acquirer": "AstraZeneca",
                "target": "TargetCo B",
                "target_ticker": "TGTB",
                "therapeutic_area": "Oncology",
                "stage": "phase_2",
                "modality": "small_molecule",
                "biological_target": "KRAS",
                "upfront_value_mm": 200.0,
                "total_value_mm": 800.0,
                "has_cvr": False,
                "has_earnout": True,
                "revenue_multiple": None,
            },
            {
                "deal_id": "d003",
                "deal_type": "M&A",
                "announcement_date": "2026-01-10",
                "acquirer": "Lilly",
                "target": "TargetCo C",
                "target_ticker": "TGTC",
                "therapeutic_area": "Oncology",
                "stage": "phase_3",
                "modality": "antibody",
                "biological_target": "PD-L1",
                "upfront_value_mm": 2000.0,
                "total_value_mm": 3500.0,
                "has_cvr": True,
                "has_earnout": True,
                "revenue_multiple": None,
            },
            {
                "deal_id": "d004",
                "deal_type": "licensing",
                "announcement_date": "2026-02-20",
                "acquirer": "Novartis",
                "target": "TargetCo D",
                "target_ticker": "TGTD",
                "therapeutic_area": "Rare Disease",
                "stage": "phase_2",
                "modality": "gene_therapy",
                "biological_target": "SMN1",
                "upfront_value_mm": 150.0,
                "total_value_mm": 600.0,
                "has_cvr": False,
                "has_earnout": False,
                "revenue_multiple": None,
            },
            {
                "deal_id": "d005",
                "deal_type": "M&A",
                "announcement_date": "2024-06-01",
                "acquirer": "Merck",
                "target": "OldCo",
                "target_ticker": "OLDC",
                "therapeutic_area": "Oncology",
                "stage": "approved",
                "modality": "small_molecule",
                "biological_target": None,
                "upfront_value_mm": 5000.0,
                "total_value_mm": 5000.0,
                "has_cvr": False,
                "has_earnout": False,
                "revenue_multiple": 8.5,
            },
            {
                "deal_id": "d006",
                "deal_type": "licensing",
                "announcement_date": "2026-03-01",
                "acquirer": "Roche",
                "target": "TargetCo E",
                "target_ticker": "TGTE",
                "therapeutic_area": "Oncology",
                "stage": "phase_2",
                "modality": "antibody",
                "biological_target": "HER2",
                "upfront_value_mm": 300.0,
                "total_value_mm": 900.0,
                "has_cvr": False,
                "has_earnout": False,
                "revenue_multiple": None,
            },
            # Future deal — should be excluded by PIT filter
            {
                "deal_id": "d007",
                "deal_type": "M&A",
                "announcement_date": "2026-05-01",
                "acquirer": "Pfizer",
                "target": "FutureCo",
                "target_ticker": "FUTC",
                "therapeutic_area": "Oncology",
                "stage": "phase_2",
                "upfront_value_mm": 9999.0,
                "total_value_mm": 9999.0,
                "has_cvr": False,
                "has_earnout": False,
            },
        ],
    }


class TestDealCompBucketMatching:
    def test_strict_ta_stage_match(self):
        comps = _sample_comps()
        result = get_deal_comps("TEST", "Oncology", "phase_2", as_of_date="2026-04-01", comps_data=comps)
        # Should match d001, d002, d006 (all Oncology + phase_2)
        assert result["n_comps"] >= 3
        assert "Oncology" in result["bucket"]

    def test_fallback_to_ta_only_when_sparse(self):
        comps = _sample_comps()
        result = get_deal_comps("TEST", "Rare Disease", "phase_3", as_of_date="2026-04-01", comps_data=comps)
        # phase_3 in Rare Disease has 0 deals, should fallback to TA-only
        assert result["n_comps"] >= 1
        assert "all stages" in result["bucket"]

    def test_empty_bucket_neutral(self):
        comps = _sample_comps()
        result = get_deal_comps("TEST", "Dermatology", "phase_1", as_of_date="2026-04-01", comps_data=comps)
        assert result["n_comps"] == 0

    def test_no_ta_returns_empty(self):
        comps = _sample_comps()
        result = get_deal_comps("TEST", None, None, as_of_date="2026-04-01", comps_data=comps)
        assert result["n_comps"] == 0


class TestDealCompPITSafety:
    def test_future_deals_excluded(self):
        comps = _sample_comps()
        result = get_deal_comps("TEST", "Oncology", "phase_2", as_of_date="2026-04-01", comps_data=comps)
        tickers = [d.get("target") for d in result["recent_deals"]]
        assert "FutureCo" not in tickers

    def test_self_excluded(self):
        comps = _sample_comps()
        result = get_deal_comps("TGTA", "Oncology", "phase_2", as_of_date="2026-04-01", comps_data=comps)
        tickers = [d.get("target") for d in result["recent_deals"]]
        assert "TargetCo A" not in tickers


class TestDealCompMedianCalculation:
    def test_median_upfront(self):
        comps = _sample_comps()
        result = get_deal_comps("TEST", "Oncology", "phase_2", as_of_date="2026-04-01", comps_data=comps)
        # Strict Oncology+phase_2 matches d001(500), d002(200), d006(300) = 3 deals
        # But < 5 deals triggers fallback to TA-only, adding d003(2000), d005(5000)
        # So median depends on fallback bucket width
        assert result["median_upfront_mm"] is not None
        assert result["median_upfront_mm"] > 0

    def test_median_with_no_values(self):
        comps = {
            "deals": [
                {
                    "deal_id": "x",
                    "deal_type": "M&A",
                    "announcement_date": "2026-01-01",
                    "therapeutic_area": "Neuro",
                    "stage": "phase_1",
                    "upfront_value_mm": None,
                    "total_value_mm": None,
                },
            ],
            "as_of_date": "2026-04-01",
        }
        result = get_deal_comps("TEST", "Neuro", "phase_1", as_of_date="2026-04-01", comps_data=comps)
        assert result["median_upfront_mm"] is None


class TestDealCompDashboardEndpointSchema:
    def test_required_fields_present(self):
        comps = _sample_comps()
        result = get_deal_comps("TEST", "Oncology", "phase_2", as_of_date="2026-04-01", comps_data=comps)
        assert "ticker" in result
        assert "bucket" in result
        assert "n_comps" in result
        assert "recent_deals" in result
        assert "median_upfront_mm" in result
        assert "median_total_mm" in result
        assert "top_acquirers" in result
        assert "deal_type_split" in result
        assert "cvr_prevalence" in result

    def test_deal_type_split(self):
        comps = _sample_comps()
        result = get_deal_comps("TEST", "Oncology", "phase_2", as_of_date="2026-04-01", comps_data=comps)
        split = result["deal_type_split"]
        assert "M&A" in split
        assert "licensing" in split
        assert split["M&A"] >= 1
        assert split["licensing"] >= 1


class TestShadowFeatures:
    def test_deal_activity_score_recency_weighting(self):
        comps = _sample_comps()
        features = compute_shadow_features("TEST", "Oncology", "phase_2", as_of_date="2026-04-01", comps_data=comps)
        # Recent deals should have higher weight than old ones
        assert features["deal_activity_score_24m"] > 0

    def test_mna_count_filter_type(self):
        comps = _sample_comps()
        features = compute_shadow_features("TEST", "Oncology", "phase_2", as_of_date="2026-04-01", comps_data=comps)
        # Only d001 is M&A + Oncology + phase_2
        assert features["mna_count_same_ta_stage_24m"] >= 1

    def test_licensing_heat_target_match(self):
        comps = _sample_comps()
        features = compute_shadow_features(
            "TEST",
            "Oncology",
            "phase_2",
            biological_target="HER2",
            as_of_date="2026-04-01",
            comps_data=comps,
        )
        # d001 and d006 both involve HER2 licensing/M&A — but licensing_heat only counts licensing
        # d006 is licensing with HER2, d001 is M&A with HER2
        assert features["licensing_heat_same_target_12m"] >= 1

    def test_big_pharma_flag_top20(self):
        comps = _sample_comps()
        features = compute_shadow_features("TEST", "Oncology", "phase_2", as_of_date="2026-04-01", comps_data=comps)
        # Pfizer, AstraZeneca, Roche are all big pharma + Oncology in 12m
        assert features["big_pharma_interest_flag"] == 1

    def test_no_big_pharma_in_bucket(self):
        comps = {
            "deals": [
                {
                    "deal_id": "x",
                    "deal_type": "M&A",
                    "announcement_date": "2026-01-01",
                    "acquirer": "TinyBiotech Inc",
                    "therapeutic_area": "Neuro",
                    "stage": "phase_1",
                },
            ],
            "as_of_date": "2026-04-01",
        }
        features = compute_shadow_features("TEST", "Neuro", "phase_1", as_of_date="2026-04-01", comps_data=comps)
        assert features["big_pharma_interest_flag"] == 0

    def test_empty_bucket_neutral(self):
        comps = _sample_comps()
        features = compute_shadow_features("TEST", "Dermatology", "phase_1", as_of_date="2026-04-01", comps_data=comps)
        assert features["deal_activity_score_24m"] == 0
        assert features["mna_count_same_ta_stage_24m"] == 0
        assert features["n_comps_in_bucket"] == 0


class TestDealabilityZScore:
    def test_zscore_clipped(self):
        rows = [{"ticker": f"T{i}", "therapeutic_area": "Oncology", "lead_program_phase": "phase_2"} for i in range(20)]
        comps = _sample_comps()
        results = compute_universe_shadow_features(rows, comps_data=comps, as_of_date="2026-04-01")
        for r in results:
            assert -3.0 <= r["dealability_prior_score"] <= 3.0

    def test_single_ticker_gets_zero(self):
        rows = [{"ticker": "SOLO", "therapeutic_area": "Oncology", "lead_program_phase": "phase_2"}]
        comps = _sample_comps()
        results = compute_universe_shadow_features(rows, comps_data=comps, as_of_date="2026-04-01")
        assert results[0]["dealability_prior_score"] == 0.0

    def test_deterministic(self):
        rows = [
            {"ticker": "A", "therapeutic_area": "Oncology", "lead_program_phase": "phase_2"},
            {"ticker": "B", "therapeutic_area": "Rare Disease", "lead_program_phase": "phase_2"},
            {"ticker": "C", "therapeutic_area": "Dermatology", "lead_program_phase": "phase_1"},
        ]
        comps = _sample_comps()
        r1 = compute_universe_shadow_features(rows, comps_data=comps, as_of_date="2026-04-01")
        r2 = compute_universe_shadow_features(rows, comps_data=comps, as_of_date="2026-04-01")
        for a, b in zip(r1, r2):
            assert a == b


class TestHelpers:
    def test_cutoff_date_24m(self):
        assert _cutoff_date("2026-04-01", 24) == "2024-04-01"

    def test_cutoff_date_12m(self):
        assert _cutoff_date("2026-04-01", 12) == "2025-04-01"

    def test_cutoff_date_wraps_year(self):
        assert _cutoff_date("2026-02-15", 6) == "2025-08-15"

    def test_recency_weight_today(self):
        w = _recency_weight("2026-04-01", "2026-04-01")
        assert abs(w - 1.0) < 0.001

    def test_recency_weight_half_life(self):
        w = _recency_weight("2025-10-03", "2026-04-01", half_life_days=180)
        assert 0.4 < w < 0.6  # ~half-life away
