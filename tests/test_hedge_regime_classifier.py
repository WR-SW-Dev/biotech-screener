#!/usr/bin/env python3
"""Tests for hedge_regime_classifier.py."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from common.hedge_regime_classifier import classify_hedge_regime


class TestRegimeClassifier:
    """Test regime preference classification."""

    def test_high_vrp_prefers_collar(self):
        """High VRP + expensive regime → collar preferred."""
        result = classify_hedge_regime(
            vrp=0.08,
            vrp_percentile=0.85,
            cost_regime="expensive",
            r_squared=0.85,
        )
        assert result["regime_preference"] == "collar_preferred"
        assert result["collar_score"] > result["put_score"]

    def test_low_vrp_prefers_put(self):
        """Low VRP + cheap regime → OTM put preferred."""
        result = classify_hedge_regime(
            vrp=0.01,
            vrp_percentile=0.20,
            cost_regime="cheap",
            r_squared=0.85,
        )
        assert result["regime_preference"] == "otm_put_preferred"
        assert result["put_score"] > result["collar_score"]

    def test_neutral_is_ambiguous(self):
        """Neutral VRP + fair regime → ambiguous."""
        result = classify_hedge_regime(
            vrp=0.03,
            vrp_percentile=0.50,
            cost_regime="fair",
            r_squared=0.85,
        )
        assert result["regime_preference"] == "ambiguous"

    def test_weak_r_squared_downgrades_confidence(self):
        """Low R² should downgrade confidence."""
        strong = classify_hedge_regime(
            vrp=0.08,
            vrp_percentile=0.85,
            cost_regime="expensive",
            r_squared=0.85,
        )
        weak = classify_hedge_regime(
            vrp=0.08,
            vrp_percentile=0.85,
            cost_regime="expensive",
            r_squared=0.30,
        )
        # Same preference but weaker confidence
        assert strong["regime_preference"] == weak["regime_preference"]
        conf_order = {"high": 3, "medium": 2, "low": 1}
        assert conf_order[weak["regime_confidence"]] < conf_order[strong["regime_confidence"]]

    def test_elevated_skew_adds_collar_point(self):
        """Elevated put skew should push toward collar."""
        without_skew = classify_hedge_regime(vrp=0.03, cost_regime="fair")
        with_skew = classify_hedge_regime(
            vrp=0.03,
            cost_regime="fair",
            skew_25d=-0.08,
        )
        assert with_skew["collar_score"] > without_skew["collar_score"]

    def test_none_inputs_produce_ambiguous(self):
        """All None inputs → ambiguous with low confidence."""
        result = classify_hedge_regime()
        assert result["regime_preference"] == "ambiguous"
        assert result["regime_confidence"] == "low"

    def test_reasons_populated(self):
        """Every non-None input should produce a reason."""
        result = classify_hedge_regime(
            vrp=0.06,
            vrp_percentile=0.80,
            cost_regime="expensive",
            r_squared=0.85,
            skew_25d=-0.07,
        )
        assert len(result["regime_reasons"]) >= 4

    def test_inputs_preserved(self):
        """Input values should be recorded in the output."""
        result = classify_hedge_regime(vrp=0.05, r_squared=0.80)
        assert result["regime_inputs"]["vrp"] == 0.05
        assert result["regime_inputs"]["r_squared"] == 0.80
