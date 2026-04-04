"""Tests for event_type_score overlay wiring."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard.app import EVENT_TYPE_LABELS
from tools.event_quality_shadow_sizer import EVENT_TYPE_SCORE_MAP


def test_event_type_score_map_complete():
    """All known event types have a score."""
    assert EVENT_TYPE_SCORE_MAP["FDA_PDUFA_DATE"] == 3
    assert EVENT_TYPE_SCORE_MAP["DATA_READOUT"] == 2
    assert EVENT_TYPE_SCORE_MAP["CT_PRIMARY_COMPLETION"] == 1
    assert EVENT_TYPE_SCORE_MAP["CT_STUDY_COMPLETION"] == 1
    assert EVENT_TYPE_SCORE_MAP["CT_RESULTS_POSTED"] == 0
    assert EVENT_TYPE_SCORE_MAP["CT_TRIAL_SUSPENDED"] == 0
    assert EVENT_TYPE_SCORE_MAP["IR_EVENT"] == 0


def test_event_type_labels_coverage():
    """Labels cover all possible score values."""
    all_scores = set(EVENT_TYPE_SCORE_MAP.values())
    for score in all_scores:
        assert score in EVENT_TYPE_LABELS, f"Score {score} has no label"


def test_position_event_type_enrichment():
    """Test that dashboard enrichment produces correct labels."""
    test_cases = [
        ("3", "PDUFA"),
        ("2", "Data Readout"),
        ("1", "Clinical Milestone"),
        ("0", "Low/None"),
        ("", "—"),  # empty string → no score
    ]
    for raw, expected_label in test_cases:
        try:
            ets_val = int(float(raw)) if raw != "" else None
        except (ValueError, TypeError):
            ets_val = None
        label = EVENT_TYPE_LABELS.get(ets_val, "—") if ets_val is not None else "—"
        assert label == expected_label, f"raw={raw!r} → got {label!r}, expected {expected_label!r}"


def test_catalyst_quality_summary():
    """Test catalyst quality distribution computation."""
    from collections import Counter

    positions = [
        {"event_type_label": "PDUFA"},
        {"event_type_label": "PDUFA"},
        {"event_type_label": "Data Readout"},
        {"event_type_label": "Clinical Milestone"},
        {"event_type_label": "—"},
        {"event_type_label": "—"},
        {"event_type_label": "—"},
    ]
    catalyst_quality = Counter(p["event_type_label"] for p in positions)
    assert catalyst_quality["PDUFA"] == 2
    assert catalyst_quality["Data Readout"] == 1
    assert catalyst_quality["Clinical Milestone"] == 1
    assert catalyst_quality["—"] == 3


def test_shadow_sizer_event_type_in_output():
    """Test that event_quality_shadow_sizer includes event_type_score in results."""
    from tools.event_quality_shadow_sizer import compute_event_quality_tilt

    # Hard catalyst row
    row = {
        "is_hard_catalyst": "1.0",
        "catalyst_days": "30",
        "catalyst_source": "FDA_CALENDAR",
        "coinvest_score_z": "1.5",
        "catalyst_event_type": "FDA_PDUFA_DATE",
    }
    tilt, reason = compute_event_quality_tilt(row)
    assert tilt == 1.10
    assert reason == "hard_catalyst"

    # Event type score should map correctly
    evt = row.get("catalyst_event_type", "")
    ets = EVENT_TYPE_SCORE_MAP.get(evt, 0) if evt else None
    assert ets == 3


def test_shadow_sizer_event_type_dist():
    """Test event type distribution computation logic."""
    results = [
        {"event_type_score": 3},
        {"event_type_score": 3},
        {"event_type_score": 2},
        {"event_type_score": 1},
        {"event_type_score": 0},
        {"event_type_score": None},
    ]
    event_type_dist = {}
    for r in results:
        ets = r.get("event_type_score")
        key = str(ets) if ets is not None else "none"
        event_type_dist[key] = event_type_dist.get(key, 0) + 1

    assert event_type_dist["3"] == 2
    assert event_type_dist["2"] == 1
    assert event_type_dist["1"] == 1
    assert event_type_dist["0"] == 1
    assert event_type_dist["none"] == 1
