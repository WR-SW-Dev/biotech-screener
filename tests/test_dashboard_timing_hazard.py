"""Tests for timing hazard dashboard integration."""

from __future__ import annotations

import json

# Import the loader under test
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard.app import _load_timing_hazard

SAMPLE_TIMING_HAZARD = {
    "schema": "timing_hazard_overlay.v1",
    "snapshot_date": "2026-04-03",
    "generated_at": "2026-04-03T20:00:00+00:00",
    "n_catalysts": 5,
    "n_warnings": 2,
    "confidence_dist": {"HIGH": 2, "MEDIUM": 1, "LOW": 1, "STALE": 1},
    "mean_on_time_prob": 0.612,
    "catalysts": [
        {
            "ticker": "ACME",
            "rank": 3,
            "catalyst_days": 45,
            "catalyst_event_type": "FDA_PDUFA_DATE",
            "catalyst_family": "REGULATORY",
            "catalyst_source": "FDA_CALENDAR",
            "is_hard_catalyst": True,
            "on_time_prob": 0.82,
            "slip_prob_30d": 0.05,
            "slip_prob_60d_plus": 0.04,
            "expected_delay_days": 4.1,
            "timing_confidence_bucket": "HIGH",
            "top_driver_1": {"feature": "is_regulatory", "magnitude": 0.8, "direction": "up_on_time"},
            "top_driver_2": None,
            "top_driver_3": None,
            "last_update_age": 10,
            "execution_warning_flag": False,
            "warning_reasons": [],
            "hazard_rate": 0.018,
            "median_arrival_days": 49,
        },
        {
            "ticker": "SLIP",
            "rank": 12,
            "catalyst_days": 90,
            "catalyst_event_type": "CT_PRIMARY_COMPLETION",
            "catalyst_family": "CLINICAL",
            "catalyst_source": "CTGOV",
            "is_hard_catalyst": False,
            "on_time_prob": 0.35,
            "slip_prob_30d": 0.20,
            "slip_prob_60d_plus": 0.16,
            "expected_delay_days": 16.2,
            "timing_confidence_bucket": "LOW",
            "top_driver_1": {"feature": "precision_month_or_worse", "magnitude": 0.5, "direction": "up_slip"},
            "top_driver_2": None,
            "top_driver_3": None,
            "last_update_age": 150,
            "execution_warning_flag": True,
            "warning_reasons": ["low_on_time_prob", "stale_update"],
            "hazard_rate": 0.004,
            "median_arrival_days": 106,
        },
        {
            "ticker": "LATE",
            "rank": 25,
            "catalyst_days": 60,
            "catalyst_event_type": "CT_PRIMARY_COMPLETION",
            "catalyst_family": "CLINICAL",
            "catalyst_source": "CTGOV_PCD_FAR",
            "is_hard_catalyst": False,
            "on_time_prob": 0.38,
            "slip_prob_30d": 0.18,
            "slip_prob_60d_plus": 0.15,
            "expected_delay_days": 14.9,
            "timing_confidence_bucket": "LOW",
            "top_driver_1": {"feature": "is_clinical", "magnitude": 0.3, "direction": "up_slip"},
            "top_driver_2": None,
            "top_driver_3": None,
            "last_update_age": 200,
            "execution_warning_flag": True,
            "warning_reasons": ["low_on_time_prob", "stale_update"],
            "hazard_rate": 0.006,
            "median_arrival_days": 75,
        },
    ],
}


def test_load_timing_hazard_found(tmp_path):
    """Test loading timing hazard JSON when file exists."""
    th_dir = tmp_path / "artifacts" / "timing_hazard"
    th_dir.mkdir(parents=True)
    th_path = th_dir / "timing_hazard_2026-04-03.json"
    th_path.write_text(json.dumps(SAMPLE_TIMING_HAZARD))

    with patch("dashboard.app.REPO_ROOT", tmp_path):
        result = _load_timing_hazard("2026-04-03")

    assert result is not None
    assert result["n_catalysts"] == 5
    assert result["n_warnings"] == 2
    assert len(result["catalysts"]) == 3


def test_load_timing_hazard_missing(tmp_path):
    """Test loading timing hazard when file doesn't exist."""
    with patch("dashboard.app.REPO_ROOT", tmp_path):
        result = _load_timing_hazard("2026-04-03")
    assert result is None


def test_timing_warnings_filtering():
    """Test that execution warnings are correctly filtered."""
    catalysts = SAMPLE_TIMING_HAZARD["catalysts"]
    warnings = [c for c in catalysts if c.get("execution_warning_flag")]
    assert len(warnings) == 2
    assert {w["ticker"] for w in warnings} == {"SLIP", "LATE"}


def test_timing_alerts_generation():
    """Test that timing warnings generate correct alerts."""
    catalysts = SAMPLE_TIMING_HAZARD["catalysts"]
    warnings = [c for c in catalysts if c.get("execution_warning_flag")]

    alerts = []
    if warnings:
        alerts.append(
            {
                "source": "timing",
                "level": "LOW" if len(warnings) < 3 else "MEDIUM",
                "text": f"{len(warnings)} catalyst(s) with execution warnings",
            }
        )
        for tw in warnings:
            reasons = ", ".join(tw.get("warning_reasons", []))
            alerts.append(
                {
                    "source": "timing",
                    "level": "LOW",
                    "text": f"{tw['ticker']} P(on_time)={tw['on_time_prob']:.0%} [{reasons}]",
                }
            )

    assert len(alerts) == 3  # 1 summary + 2 per-ticker
    assert alerts[0]["source"] == "timing"
    assert alerts[0]["level"] == "LOW"  # 2 < 3 threshold
    assert "SLIP" in alerts[1]["text"]
    assert "low_on_time_prob" in alerts[1]["text"]


def test_timing_summary_structure():
    """Test timing summary computation from raw data."""
    th = SAMPLE_TIMING_HAZARD
    summary = {
        "n_catalysts": th.get("n_catalysts", 0),
        "n_warnings": th.get("n_warnings", 0),
        "mean_on_time": th.get("mean_on_time_prob"),
        "confidence_dist": th.get("confidence_dist", {}),
    }
    assert summary["n_catalysts"] == 5
    assert summary["n_warnings"] == 2
    assert summary["mean_on_time"] == 0.612
    assert summary["confidence_dist"]["HIGH"] == 2
    assert summary["confidence_dist"]["STALE"] == 1


def test_position_timing_enrichment():
    """Test that positions get timing confidence from overlay."""
    timing_by_ticker = {c["ticker"]: c for c in SAMPLE_TIMING_HAZARD["catalysts"]}

    positions = [
        {"ticker": "ACME", "weight": 3.3},
        {"ticker": "SLIP", "weight": 3.3},
        {"ticker": "NOCAT", "weight": 3.3},
    ]

    for p in positions:
        th = timing_by_ticker.get(p["ticker"], {})
        p["timing_confidence"] = th.get("timing_confidence_bucket", "")
        p["on_time_prob"] = th.get("on_time_prob")

    assert positions[0]["timing_confidence"] == "HIGH"
    assert positions[0]["on_time_prob"] == 0.82
    assert positions[1]["timing_confidence"] == "LOW"
    assert positions[1]["on_time_prob"] == 0.35
    assert positions[2]["timing_confidence"] == ""
    assert positions[2]["on_time_prob"] is None
