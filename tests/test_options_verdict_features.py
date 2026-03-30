"""Tests for common/options_verdict_features.py — research feature extraction."""

from decimal import Decimal

import pytest

from common.options_verdict_features import compute_verdict_features, enrich_csv_rows_with_verdict


class TestComputeVerdictFeatures:
    def test_none_returns_empty(self):
        result = compute_verdict_features(None)
        assert result["ovf_composite"] == ""
        assert result["ovf_agreement_count"] == ""

    def test_resolved_returns_empty(self):
        result = compute_verdict_features({"severity": "RESOLVED", "flags": [], "lenses": []})
        assert result["ovf_composite"] == ""

    def test_high_2_lenses(self):
        row = {
            "severity": "HIGH",
            "n_lenses": 2,
            "lenses": ["options_watch_post", "surface_delta"],
            "flags": ["IV_RAMP_HIGH", "iv_jump_up"],
            "near_catalyst": True,
            "catalyst_days": 5,
        }
        result = compute_verdict_features(row)
        assert result["ovf_agreement_count"] == "2"
        assert result["ovf_severity_score"] == "2"
        assert result["ovf_near_catalyst"] == "1"
        assert result["ovf_has_iv_ramp"] == "1"
        assert result["ovf_surface_confirmed"] == "1"
        composite = Decimal(result["ovf_composite"])
        assert composite > Decimal("0.4")  # agreement + flags + near + confirmed
        assert composite <= Decimal("1")

    def test_medium_1_lens(self):
        row = {
            "severity": "MEDIUM",
            "n_lenses": 1,
            "lenses": ["price_action"],
            "flags": ["QUIET_BEFORE_CATALYST"],
            "near_catalyst": True,
            "catalyst_days": 10,
        }
        result = compute_verdict_features(row)
        assert result["ovf_agreement_count"] == "1"
        assert result["ovf_severity_score"] == "1"
        assert result["ovf_has_quiet_before"] == "1"
        assert result["ovf_surface_confirmed"] == "0"

    def test_penalty_flags_reduce_composite(self):
        base = {
            "severity": "MEDIUM",
            "n_lenses": 1,
            "lenses": ["price_action"],
            "flags": ["IV_RAMP_HIGH"],
            "near_catalyst": False,
        }
        no_penalty = compute_verdict_features(base)

        with_penalty = dict(base)
        with_penalty["flags"] = ["IV_RAMP_HIGH", "IV_CRUSH", "REACTION_MISMATCH"]
        penalized = compute_verdict_features(with_penalty)

        assert Decimal(no_penalty["ovf_composite"]) > Decimal(penalized["ovf_composite"])

    def test_composite_bounded_0_1(self):
        # Max everything
        row = {
            "severity": "HIGH",
            "n_lenses": 4,
            "lenses": ["options_watch_post", "options_watch_pre", "surface_delta", "price_action"],
            "flags": list({"EVENT_PREMIUM", "IV_RAMP_HIGH", "SURFACE_MOVE_HIGH", "EXTREME_SKEW", "iv_jump_up"}),
            "near_catalyst": True,
        }
        result = compute_verdict_features(row)
        assert Decimal(result["ovf_composite"]) <= Decimal("1")
        assert Decimal(result["ovf_composite"]) >= Decimal("0")

    def test_all_features_present(self):
        row = {
            "severity": "HIGH",
            "n_lenses": 1,
            "lenses": ["options_watch_post"],
            "flags": [],
            "near_catalyst": False,
        }
        result = compute_verdict_features(row)
        expected_keys = {
            "ovf_agreement_count",
            "ovf_severity_score",
            "ovf_near_catalyst",
            "ovf_has_event_premium",
            "ovf_has_iv_ramp",
            "ovf_has_quiet_before",
            "ovf_surface_confirmed",
            "ovf_composite",
        }
        assert set(result.keys()) == expected_keys


class TestEnrichCsvRows:
    def test_enriches_matching_tickers(self):
        rows = [{"ticker": "PVLA"}, {"ticker": "CELC"}, {"ticker": "OTHER"}]
        verdict_data = {
            "verdicts": [
                {
                    "ticker": "PVLA",
                    "severity": "HIGH",
                    "n_lenses": 2,
                    "lenses": ["options_watch_post", "surface_delta"],
                    "flags": ["IV_RAMP_HIGH"],
                    "near_catalyst": True,
                },
            ],
        }
        n = enrich_csv_rows_with_verdict(rows, verdict_data)
        assert n == 1
        assert rows[0]["ovf_agreement_count"] == "2"
        assert rows[1]["ovf_composite"] == ""  # CELC not in verdict
        assert rows[2]["ovf_composite"] == ""  # OTHER not in verdict

    def test_none_verdict_fills_empty(self):
        rows = [{"ticker": "PVLA"}]
        n = enrich_csv_rows_with_verdict(rows, None)
        assert n == 0
        assert rows[0]["ovf_composite"] == ""
