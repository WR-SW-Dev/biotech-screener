"""Tests for timing hazard review loop."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.research.timing_hazard_review import feature_attribution, find_failure_cases, score_calibration

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_prediction(
    ticker="ACME",
    prediction_date="2026-03-01",
    on_time_prob=0.80,
    catalyst_days=60,
    catalyst_family="CLINICAL",
    is_hard=False,
    confidence="HIGH",
    warning=False,
):
    return {
        "prediction_date": prediction_date,
        "ticker": ticker,
        "rank": 5,
        "catalyst_days": catalyst_days,
        "catalyst_event_type": "CT_PRIMARY_COMPLETION",
        "catalyst_family": catalyst_family,
        "is_hard_catalyst": is_hard,
        "on_time_prob": on_time_prob,
        "slip_prob_30d": (1 - on_time_prob) * 0.55,
        "slip_prob_60d_plus": (1 - on_time_prob) * 0.45,
        "timing_confidence_bucket": confidence,
        "execution_warning_flag": warning,
        "warning_reasons": ["low_on_time_prob"] if warning else [],
        "top_driver_1": {"feature": "is_clinical", "magnitude": 0.3, "direction": "up_slip"},
        "last_update_age": 30,
    }


def _make_matched(outcome="ON_TIME", on_time_prob=0.80, **kwargs):
    pred = _make_prediction(on_time_prob=on_time_prob, **kwargs)
    pred["outcome"] = outcome
    pred["actual_on_time"] = 1 if outcome == "ON_TIME" else 0
    pred["revision_drift_days"] = 0 if outcome == "ON_TIME" else 45.0
    pred["revision_date"] = None if outcome == "ON_TIME" else "2026-04-01"
    return pred


# ---------------------------------------------------------------------------
# score_calibration
# ---------------------------------------------------------------------------


def test_score_calibration_basic():
    """Test calibration scoring with known data."""
    matched = []
    # 80 on-time, 20 slips
    for i in range(80):
        matched.append(_make_matched("ON_TIME", on_time_prob=0.85, ticker=f"T{i}"))
    for i in range(20):
        matched.append(_make_matched("SLIP", on_time_prob=0.60, ticker=f"S{i}"))

    result = score_calibration(matched)
    assert "error" not in result
    assert result["n_scoreable"] == 100
    assert 0 < result["brier_score"] < 0.5
    assert result["base_rate"] == 0.80  # 80/100
    assert result["verdict"]  # some verdict string


def test_score_calibration_excludes_rollovers():
    matched = [
        _make_matched("ON_TIME"),
        _make_matched("SLIP"),
        {**_make_matched("ROLLOVER"), "outcome": "ROLLOVER"},
    ]
    result = score_calibration(matched)
    assert result["n_scoreable"] == 2


def test_score_calibration_breakdowns():
    matched = []
    for i in range(30):
        matched.append(_make_matched("ON_TIME", on_time_prob=0.90, confidence="HIGH", ticker=f"H{i}"))
    for i in range(10):
        matched.append(_make_matched("SLIP", on_time_prob=0.50, confidence="LOW", ticker=f"L{i}"))

    result = score_calibration(matched)
    bkd = result["breakdowns"]
    assert bkd["by_confidence_bucket"]["HIGH"]["n"] == 30
    assert bkd["by_confidence_bucket"]["LOW"]["n"] == 10


def test_score_calibration_empty():
    result = score_calibration([])
    assert "error" in result


# ---------------------------------------------------------------------------
# feature_attribution
# ---------------------------------------------------------------------------


def test_feature_attribution_basic():
    matched = []
    for i in range(20):
        matched.append(_make_matched("ON_TIME", catalyst_days=30, ticker=f"OT{i}"))
    for i in range(10):
        matched.append(_make_matched("SLIP", catalyst_days=120, ticker=f"SL{i}"))

    result = feature_attribution(matched)
    comps = result["feature_comparisons"]
    assert "catalyst_days" in comps
    # Slips should have higher catalyst_days on average
    assert comps["catalyst_days"]["slip_mean"] > comps["catalyst_days"]["on_time_mean"]


def test_feature_attribution_empty():
    result = feature_attribution([_make_matched("ON_TIME")])
    assert "error" in result  # no slips


# ---------------------------------------------------------------------------
# find_failure_cases
# ---------------------------------------------------------------------------


def test_failure_cases_confident_slips():
    matched = [
        _make_matched("SLIP", on_time_prob=0.95, ticker="WORST"),
        _make_matched("SLIP", on_time_prob=0.70, ticker="BAD"),
        _make_matched("ON_TIME", on_time_prob=0.90, ticker="GOOD"),
    ]
    result = find_failure_cases(matched)
    slips = result["confident_slips"]
    assert len(slips) == 2
    assert slips[0]["ticker"] == "WORST"  # sorted by highest P(on_time)


def test_failure_cases_pessimistic_hits():
    matched = [
        _make_matched("ON_TIME", on_time_prob=0.30, ticker="SURPRISE"),
        _make_matched("ON_TIME", on_time_prob=0.90, ticker="EXPECTED"),
    ]
    result = find_failure_cases(matched)
    hits = result["pessimistic_hits"]
    assert len(hits) == 2
    assert hits[0]["ticker"] == "SURPRISE"  # sorted by lowest P(on_time)


# ---------------------------------------------------------------------------
# Warning flag accuracy
# ---------------------------------------------------------------------------


def test_warning_flag_precision():
    matched = [
        _make_matched("SLIP", on_time_prob=0.35, warning=True, ticker="W1"),
        _make_matched("ON_TIME", on_time_prob=0.38, warning=True, ticker="W2"),
        _make_matched("ON_TIME", on_time_prob=0.90, warning=False, ticker="OK"),
    ]
    result = score_calibration(matched)
    wf = result["breakdowns"]["warning_flag"]
    assert wf["n_warned"] == 2
    assert wf["slip_rate_of_warned"] == 0.5  # 1/2 warned actually slipped


# ---------------------------------------------------------------------------
# Overconfidence detection
# ---------------------------------------------------------------------------


def test_overconfidence_detection():
    """Model predicting higher on-time rate than reality → positive overconfidence."""
    matched = []
    # Model says 90% on-time but only 50% actually are
    for i in range(50):
        matched.append(_make_matched("ON_TIME", on_time_prob=0.90, ticker=f"OT{i}"))
    for i in range(50):
        matched.append(_make_matched("SLIP", on_time_prob=0.90, ticker=f"SL{i}"))

    result = score_calibration(matched)
    # mean_predicted ≈ 0.90, base_rate = 0.50
    assert result["overconfidence"] > 0.3  # significantly overconfident
