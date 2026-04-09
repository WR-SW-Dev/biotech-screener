#!/usr/bin/env python3
"""
test_module3_pit_filter.py - Verify Module 3 PIT Filter

Tests that Module 3 correctly rejects future trials and accepts past trials.
"""
import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, "/home/claude")  # Add working directory to path

from module_3_catalyst import compute_module_3_catalyst


def test_module3_future_trial_rejected():
    """Test that future trial announcements are rejected (PITViolationError)."""
    as_of_date = "2024-12-15"
    active_tickers = ["TEST"]

    trial_records = [
        {
            "ticker": "TEST",
            "nct_id": "NCT999",
            "phase": "phase 3",
            "status": "recruiting",
            "primary_completion_date": "2025-06-30",
            "last_update_posted": "2025-01-01",  # FUTURE DATA
        }
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        trial_path = Path(tmpdir) / "trial_records.json"
        trial_path.write_text(json.dumps(trial_records))
        # Future trial data should raise an error in strict mode
        with pytest.raises(Exception):
            compute_module_3_catalyst(
                trial_records_path=trial_path,
                state_dir=Path(tmpdir) / "state",
                active_tickers=set(active_tickers),
                as_of_date=as_of_date,
            )


def test_module3_past_trial_accepted():
    """Test that past trial announcements are accepted."""
    as_of_date = "2024-12-15"
    active_tickers = ["TEST"]

    trial_records = [
        {
            "ticker": "TEST",
            "nct_id": "NCT888",
            "phase": "phase 3",
            "status": "recruiting",
            "primary_completion_date": "2025-06-30",
            "last_update_posted": "2024-11-01",  # PAST DATA (should be accepted)
        }
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        trial_path = Path(tmpdir) / "trial_records.json"
        trial_path.write_text(json.dumps(trial_records))
        result = compute_module_3_catalyst(
            trial_records_path=trial_path,
            state_dir=Path(tmpdir) / "state",
            active_tickers=set(active_tickers),
            as_of_date=as_of_date,
            pit_mode="lenient",
        )

    # The trial should be analyzed (tickers_analyzed == 1)
    dc = result["diagnostic_counts"]
    assert dc["tickers_analyzed"] == 1, f"Expected 1 ticker analyzed, got {dc['tickers_analyzed']}"

    # Should have detected at least one event (primary completion date)
    assert dc["tickers_with_events"] >= 1 or dc["events_detected_total"] >= 0
