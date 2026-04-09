"""Tests for tools/build_ev_validation.py."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from build_ev_validation import (
    _normalize_event_type,
    _record_hash,
    compute_summary,
    get_price,
    get_price_forward,
    match_predictions_to_resolutions,
)


class TestNormalizeEventType:
    def test_pdufa(self):
        assert _normalize_event_type("PDUFA_ACTION") == "PDUFA"

    def test_phase3_readout(self):
        assert _normalize_event_type("PHASE_3_READOUT") == "DATA_READOUT"

    def test_passthrough(self):
        assert _normalize_event_type("UNKNOWN_TYPE") == "UNKNOWN_TYPE"


class TestRecordHash:
    def test_deterministic(self):
        h1 = _record_hash("ACME", "2026-04-01", "2026-03-28")
        h2 = _record_hash("ACME", "2026-04-01", "2026-03-28")
        assert h1 == h2

    def test_different_inputs(self):
        h1 = _record_hash("ACME", "2026-04-01", "2026-03-28")
        h2 = _record_hash("ACME", "2026-04-02", "2026-03-28")
        assert h1 != h2


class TestGetPrice:
    def test_exact_date(self):
        prices = {"ACME": {"2026-04-01": 100.0, "2026-04-02": 105.0}}
        assert get_price(prices, "ACME", "2026-04-01") == 100.0

    def test_lookback(self):
        prices = {"ACME": {"2026-03-28": 99.0}}
        assert get_price(prices, "ACME", "2026-04-01", max_lookback=5) == 99.0

    def test_missing(self):
        prices = {"ACME": {"2026-01-01": 50.0}}
        assert get_price(prices, "ACME", "2026-04-01", max_lookback=2) is None


class TestGetPriceForward:
    def test_5_days(self):
        prices = {"ACME": {f"2026-04-0{i}": float(100 + i) for i in range(1, 9)}}
        result = get_price_forward(prices, "ACME", "2026-04-01", 5)
        assert result == 106.0  # 5th date after 2026-04-01


class TestMatchPredictions:
    def test_basic_match(self):
        predictions = {
            "2026-03-25": [
                {
                    "ticker": "ACME",
                    "event_type": "PDUFA",
                    "p_hit": 0.75,
                    "p_miss": 0.25,
                    "scenario_ev": 3.5,
                    "ds_adj_ev": 2.0,
                    "implied_p_hit": 0.6,
                    "mispricing": 0.15,
                    "upside_hit": 20.0,
                    "downside_miss": -30.0,
                    "event_family": "REGULATORY",
                    "phase": "3",
                    "analog_conf": "ok",
                    "days_to_event": 10,
                },
            ],
        }
        resolutions = [
            {
                "ticker": "ACME",
                "catalyst_date": "2026-04-04",
                "catalyst_type": "PDUFA_ACTION",
                "outcome": "HIT",
                "resolution_date": "2026-04-04",
                "outcome_detail": "Approved",
            },
        ]
        prices = {"ACME": {"2026-04-03": 50.0, "2026-04-04": 55.0, "2026-04-05": 56.0}}

        matched = match_predictions_to_resolutions(predictions, resolutions, prices, set())
        assert len(matched) == 1
        rec = matched[0]
        assert rec["ticker"] == "ACME"
        assert rec["outcome"] == "HIT"
        assert rec["predicted_p_hit"] == 0.75
        assert rec["brier_component"] == (0.75 - 1.0) ** 2

    def test_no_prediction_before_event(self):
        predictions = {
            "2026-04-10": [  # After catalyst_date
                {"ticker": "ACME", "event_type": "PDUFA", "p_hit": 0.75},
            ],
        }
        resolutions = [
            {"ticker": "ACME", "catalyst_date": "2026-04-04", "catalyst_type": "PDUFA_ACTION", "outcome": "HIT"},
        ]
        matched = match_predictions_to_resolutions(predictions, resolutions, {}, set())
        assert len(matched) == 0

    def test_dedup(self):
        predictions = {
            "2026-03-25": [{"ticker": "ACME", "event_type": "PDUFA", "p_hit": 0.75}],
        }
        resolutions = [
            {"ticker": "ACME", "catalyst_date": "2026-04-04", "catalyst_type": "PDUFA_ACTION", "outcome": "HIT"},
        ]
        existing = set()
        m1 = match_predictions_to_resolutions(predictions, resolutions, {}, existing)
        m2 = match_predictions_to_resolutions(predictions, resolutions, {}, existing)
        assert len(m1) == 1
        assert len(m2) == 0  # Already in existing_hashes


class TestComputeSummary:
    def test_empty(self):
        s = compute_summary([])
        assert s["n_matched"] == 0
        assert s["status"] == "insufficient_data"

    def test_basic(self):
        records = [
            {
                "predicted_p_hit": 0.8,
                "outcome_binary": 1.0,
                "brier_component": 0.04,
                "ev_error": 0.02,
                "outcome": "HIT",
                "event_family": "REGULATORY",
                "prediction_date": "2026-03-25",
                "resolution_date": "2026-04-04",
                "realized_1d_return": 0.10,
            },
            {
                "predicted_p_hit": 0.3,
                "outcome_binary": 0.0,
                "brier_component": 0.09,
                "ev_error": -0.05,
                "outcome": "MISS",
                "event_family": "CLINICAL",
                "prediction_date": "2026-03-20",
                "resolution_date": "2026-04-01",
                "realized_1d_return": -0.15,
            },
        ]
        s = compute_summary(records)
        assert s["n_matched"] == 2
        assert s["brier_score"] == (0.04 + 0.09) / 2
        assert s["outcome_distribution"]["HIT"] == 1
        assert s["outcome_distribution"]["MISS"] == 1
        assert s["n_with_prices"] == 2
