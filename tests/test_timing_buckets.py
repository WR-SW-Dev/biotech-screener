"""Tests for Spec 058 timing bucket classification and calibration slicing."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.compute_timing_hazard import (
    classify_family_bucket,
    classify_hardness,
    classify_horizon_bucket,
    compute_calibration_by_slice,
)

# ---------------------------------------------------------------------------
# Horizon bucket
# ---------------------------------------------------------------------------


def test_horizon_near():
    assert classify_horizon_bucket(0) == "NEAR"
    assert classify_horizon_bucket(15) == "NEAR"
    assert classify_horizon_bucket(30) == "NEAR"


def test_horizon_medium():
    assert classify_horizon_bucket(31) == "MEDIUM"
    assert classify_horizon_bucket(60) == "MEDIUM"
    assert classify_horizon_bucket(90) == "MEDIUM"


def test_horizon_far():
    assert classify_horizon_bucket(91) == "FAR"
    assert classify_horizon_bucket(180) == "FAR"
    assert classify_horizon_bucket(365) == "FAR"


# ---------------------------------------------------------------------------
# Hardness
# ---------------------------------------------------------------------------


def test_hardness_from_flag():
    assert classify_hardness(True, "CTGOV_CALENDAR") == "HARD"
    assert classify_hardness(True, "") == "HARD"


def test_hardness_from_source():
    assert classify_hardness(False, "SEC_8K_FILING") == "HARD"
    assert classify_hardness(False, "FDA_CALENDAR") == "HARD"
    assert classify_hardness(False, "PDUFA_MANUAL") == "HARD"


def test_hardness_soft():
    assert classify_hardness(False, "CTGOV_CALENDAR") == "SOFT"
    assert classify_hardness(False, "CTGOV_PCD_FAR") == "SOFT"
    assert classify_hardness(False, "") == "SOFT"


# ---------------------------------------------------------------------------
# Family bucket
# ---------------------------------------------------------------------------


def test_family_known():
    assert classify_family_bucket("REGULATORY") == "REGULATORY"
    assert classify_family_bucket("CLINICAL") == "CLINICAL"
    assert classify_family_bucket("SAFETY") == "SAFETY"


def test_family_unknown():
    assert classify_family_bucket("") == "UNKNOWN"
    assert classify_family_bucket("OTHER") == "UNKNOWN"


# ---------------------------------------------------------------------------
# All 9 cells (3 families x 3 horizons) are reachable
# ---------------------------------------------------------------------------


def test_all_nine_cells():
    families = ["REGULATORY", "CLINICAL", "SAFETY"]
    horizons = [10, 50, 120]  # NEAR, MEDIUM, FAR
    expected_horizons = ["NEAR", "MEDIUM", "FAR"]
    cells = set()
    for fam in families:
        for days, exp_h in zip(horizons, expected_horizons):
            fb = classify_family_bucket(fam)
            hb = classify_horizon_bucket(days)
            assert fb == fam
            assert hb == exp_h
            cells.add((fb, hb))
    assert len(cells) == 9


# ---------------------------------------------------------------------------
# Calibration by slice
# ---------------------------------------------------------------------------


def test_calibration_by_slice_empty(tmp_path, monkeypatch):
    """No ledger → empty result."""
    monkeypatch.setattr(
        "tools.compute_timing_hazard.CALIBRATION_LEDGER",
        tmp_path / "nonexistent.jsonl",
    )
    result = compute_calibration_by_slice("2026-04-05")
    assert result["n_resolved"] == 0
    assert result["slices"] == []


def test_calibration_by_slice_groups(tmp_path, monkeypatch):
    """Resolved entries are grouped correctly by bucket."""
    ledger = tmp_path / "ledger.jsonl"
    entries = [
        {
            "prediction_date": "2026-03-15",
            "ticker": "ACME",
            "catalyst_family": "REGULATORY",
            "horizon_bucket": "NEAR",
            "hardness": "HARD",
            "on_time_prob": 0.95,
            "actual_outcome": "ON_TIME",
        },
        {
            "prediction_date": "2026-03-20",
            "ticker": "BETA",
            "catalyst_family": "CLINICAL",
            "horizon_bucket": "MEDIUM",
            "hardness": "SOFT",
            "on_time_prob": 0.60,
            "actual_outcome": "SLIP_30D",
        },
        {
            "prediction_date": "2026-03-25",
            "ticker": "GAMMA",
            "catalyst_family": "REGULATORY",
            "horizon_bucket": "NEAR",
            "hardness": "HARD",
            "on_time_prob": 0.90,
            "actual_outcome": "ON_TIME",
        },
    ]
    with open(ledger, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")

    monkeypatch.setattr("tools.compute_timing_hazard.CALIBRATION_LEDGER", ledger)
    result = compute_calibration_by_slice("2026-04-05", trailing_days=30)
    assert result["n_resolved"] == 3
    assert len(result["slices"]) == 2  # REGULATORY/NEAR/HARD and CLINICAL/MEDIUM/SOFT

    reg_slice = [s for s in result["slices"] if s["family"] == "REGULATORY"][0]
    assert reg_slice["n"] == 2
    assert reg_slice["actual_on_time_rate"] == 1.0

    clin_slice = [s for s in result["slices"] if s["family"] == "CLINICAL"][0]
    assert clin_slice["n"] == 1
    assert clin_slice["actual_on_time_rate"] == 0.0


def test_calibration_by_slice_trailing_window(tmp_path, monkeypatch):
    """Old entries outside trailing window are excluded."""
    ledger = tmp_path / "ledger.jsonl"
    entries = [
        {
            "prediction_date": "2026-01-01",  # too old
            "ticker": "OLD",
            "catalyst_family": "CLINICAL",
            "horizon_bucket": "FAR",
            "hardness": "SOFT",
            "on_time_prob": 0.50,
            "actual_outcome": "ON_TIME",
        },
        {
            "prediction_date": "2026-03-20",  # within window
            "ticker": "NEW",
            "catalyst_family": "CLINICAL",
            "horizon_bucket": "FAR",
            "hardness": "SOFT",
            "on_time_prob": 0.50,
            "actual_outcome": "SLIP_30D",
        },
    ]
    with open(ledger, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")

    monkeypatch.setattr("tools.compute_timing_hazard.CALIBRATION_LEDGER", ledger)
    result = compute_calibration_by_slice("2026-04-05", trailing_days=30)
    assert result["n_resolved"] == 1  # only the recent one
