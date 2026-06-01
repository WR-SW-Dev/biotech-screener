"""
Regression test for Module 5 weakest-link aggregation bug.

The bug occurs when composite scores collapse to near-zero despite normal component scores.
This happens because the weakest-link logic attempts to reconstruct raw component scores from
transformed contribution space via division:
    underlying = contributions[c] / effective_weights[c]

This fails because contributions[c] includes non-linear transforms (asymmetric transform,
confidence weighting) that division cannot undo. When contributions become negative, min_critical
becomes deeply negative and collapses the entire composite via:
    composite = 0.85 * weighted_sum + 0.15 * min_critical

The fix: use raw/effective component scores (from component_scores) directly instead of
reconstructing from transformed contributions.
"""

from datetime import datetime
from decimal import Decimal

import pytest

from module_5_scoring_v3 import NormalizationMethod, ScoringMode, _score_single_ticker_v3


def test_weakest_link_with_normal_components():
    """
    Verify that weakest-link logic produces reasonable composites when both
    financial and clinical components are normal [0,100].
    """
    # Simulate a realistic ticker with:
    # - financial_score = 35.0 (normal, not transformed)
    # - clinical_score = 45.0 (normal, not transformed)
    # - catalyst_score = 65.0 (normal)
    # - momentum = 55.0 (normal)
    # Expected composite: ~50-60 range (not 0.06-0.10)

    ticker = "TEST_TICKER"
    normalized_scores = {
        "clinical": Decimal("45"),  # Normal [0,100]
        "financial": Decimal("35"),  # Normal [0,100]
        "catalyst": Decimal("65"),  # Normal [0,100]
        "pos": None,
    }

    base_weights = {
        "clinical": Decimal("0.25"),
        "financial": Decimal("0.25"),
        "catalyst": Decimal("0.30"),
        "momentum": Decimal("0.15"),
        "valuation": Decimal("0.05"),
    }

    # Minimal data structures (metadata-only)
    fin_data = {
        "ticker": ticker,
        "financial_score": 35.0,
        "market_cap_mm": 500,
        "severity": "none",
        "runway_months": 24,
        "dilution_bucket": "LOW",
        "has_revenue": False,
    }
    cat_data = {
        "ticker": ticker,
        "catalyst_score_net": 65.0,
        "nearest_catalyst_type": "FDA_PDUFA_DATE",
        "catalyst_window_days": 20,
        "flags": {},
        "scores": {},
    }
    clin_data = {
        "ticker": ticker,
        "clinical_score": 45.0,
        "lead_phase": "phase_2",
        "trial_count": 3,
        "severity": "none",
        "lead_program_phase": "phase_2",
    }

    # Run the scoring function
    result = _score_single_ticker_v3(
        ticker=ticker,
        fin_data=fin_data,
        cat_data=cat_data,
        clin_data=clin_data,
        pos_data=None,
        si_data=None,
        market_data=None,
        coinvest_data={
            "coinvest_overlap_count": 0,
            "coinvest_holders": [],
            "coinvest_usable": False,
            "position_changes": {},
        },
        base_weights=base_weights,
        regime="DEFAULT",
        mode=ScoringMode.DEFAULT,
        normalized_scores=normalized_scores,
        cohort_key="phase_2",
        normalization_method=NormalizationMethod.COHORT,
        peer_valuations=[],
    )

    composite_score = Decimal(str(result["composite_score"]))

    # ASSERTIONS:
    # Weighted avg = 0.25*45 + 0.25*35 + 0.30*65 + 0.15*0 + 0.05*0 = ~39.5
    # The fix should push composite closer to 35-50 range

    # 1. Composite should NOT collapse to near-zero (0.06-0.10 bug)
    assert composite_score > Decimal("5"), (
        f"REGRESSION DETECTED: composite_score={composite_score} is catastrophically low. "
        f"Expected 30-50 range. Weakest-link logic is collapsing the score."
    )

    # 2. Composite should be reasonable given inputs
    assert composite_score <= Decimal("100"), f"Composite score {composite_score} is invalid (should be 0-100)"

    # 3. For now, just verify it's not near-catastrophic collapse
    # After fix, this should be much higher
    print(f"DEBUG: composite_score={composite_score} (before fix, expected 30-50 after fix)")

    print(f"✓ weakest_link test PASSED: composite_score={composite_score}")
    return result


def test_weakest_link_with_negative_financial():
    """
    Test edge case: financial_score is legitimately negative from contradiction penalties.

    Even if financial_score becomes negative during aggregation (e.g., due to contradictions),
    the min_critical should NOT be used to collapse the entire composite. Instead, min_critical
    should be computed from the raw/effective financial score [0,100], not from the
    transformed contribution space.
    """
    ticker = "TEST_CONTRADICTION"

    # High momentum + poor financial = contradiction penalty applies
    normalized_scores = {
        "clinical": Decimal("35"),  # OK
        "financial": Decimal("25"),  # Weak (triggers momentum_fundamental_divergence)
        "catalyst": Decimal("50"),
        "pos": None,
    }

    base_weights = {
        "clinical": Decimal("0.25"),
        "financial": Decimal("0.25"),
        "catalyst": Decimal("0.30"),
        "momentum": Decimal("0.15"),
        "valuation": Decimal("0.05"),
    }

    fin_data = {
        "ticker": ticker,
        "financial_score": 25.0,  # Low, will trigger contradiction if momentum high
        "market_cap_mm": 500,
        "severity": "none",
        "runway_months": 24,
        "dilution_bucket": "LOW",
        "has_revenue": False,
    }
    cat_data = {
        "ticker": ticker,
        "catalyst_score_net": 50.0,
        "nearest_catalyst_type": "DEFAULT",
        "catalyst_window_days": 0,
        "flags": {},
        "scores": {},
    }
    clin_data = {
        "ticker": ticker,
        "clinical_score": 35.0,
        "lead_phase": "phase_2",
        "trial_count": 2,
        "severity": "none",
        "lead_program_phase": "phase_2",
    }

    result = _score_single_ticker_v3(
        ticker=ticker,
        fin_data=fin_data,
        cat_data=cat_data,
        clin_data=clin_data,
        pos_data=None,
        si_data=None,
        market_data={
            "volatility_252d": 0.45,
            "return_60d": Decimal("0.15"),  # Strong momentum
            "xbi_return_60d": Decimal("0.05"),
        },
        coinvest_data={
            "coinvest_overlap_count": 0,
            "coinvest_holders": [],
            "coinvest_usable": False,
            "position_changes": {},
        },
        base_weights=base_weights,
        regime="DEFAULT",
        mode=ScoringMode.PARTIAL,
        normalized_scores=normalized_scores,
        cohort_key="phase_2",
        normalization_method=NormalizationMethod.COHORT,
        peer_valuations=[],
    )

    composite_score = Decimal(str(result["composite_score"]))

    # Even with contradiction penalties, composite should NOT collapse to near-zero
    assert composite_score > Decimal("10"), (
        f"REGRESSION: composite_score={composite_score} collapsed despite normal inputs. "
        f"Contradiction penalty was applied correctly, but min_critical logic is broken."
    )

    print(f"✓ weakest_link_contradiction test PASSED: composite_score={composite_score}")
    return result


if __name__ == "__main__":
    # Run tests standalone
    print("Running Module 5 weakest-link regression tests...")
    try:
        test_weakest_link_with_normal_components()
        test_weakest_link_with_negative_financial()
        print("\n✓ All regression tests PASSED")
    except AssertionError as e:
        print(f"\n✗ REGRESSION DETECTED:\n{e}")
        exit(1)
