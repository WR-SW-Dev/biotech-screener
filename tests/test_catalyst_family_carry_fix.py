"""Test that hard_catalyst_carry populates catalyst_family after overriding event_type."""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.hard_catalyst_carry import forward_carry_hard_catalysts
from event_ledger import CATALYST_FAMILY_MAP, classify_catalyst_family


def test_classify_known_event_types():
    """All mapped event types return a non-empty family."""
    for evt, family in CATALYST_FAMILY_MAP.items():
        assert classify_catalyst_family(evt) == family
        assert family in ("REGULATORY", "CLINICAL", "SAFETY")


def test_classify_empty_returns_empty():
    assert classify_catalyst_family("") == ""


def test_classify_unknown_returns_empty():
    assert classify_catalyst_family("UNKNOWN_TYPE") == ""
    assert classify_catalyst_family("IR_EVENT") == ""


def test_carry_populates_family(tmp_path):
    """forward_carry_hard_catalysts should set catalyst_family after overriding event_type."""

    # Create a carry state with a hard catalyst for ACME
    state = {
        "ACME": {
            "catalyst_source": "SEC_8K_FILING",
            "catalyst_event_type": "FDA_PDUFA_DATE",
            "estimated_event_date": "2026-06-01",
            "first_seen": "2026-03-01",
        }
    }
    state_path = tmp_path / "hard_catalyst_carry.json"
    state_path.write_text(json.dumps(state))

    # Row with a soft source and empty family (the bug scenario)
    rows = [
        {
            "ticker": "ACME",
            "catalyst_source": "CTGOV_CALENDAR",  # soft source
            "catalyst_event_type": "CT_PRIMARY_COMPLETION",
            "catalyst_family": "",  # empty — the bug
            "is_hard_catalyst": "0",
            "catalyst_days": "60",
        }
    ]

    n = forward_carry_hard_catalysts(rows, date(2026, 4, 5), state_path)
    assert n == 1

    # After carry: event_type should be overridden AND family should be populated
    assert rows[0]["catalyst_event_type"] == "FDA_PDUFA_DATE"
    assert rows[0]["catalyst_family"] == "REGULATORY"  # This was the fix
    assert rows[0]["is_hard_catalyst"] == "1"


def test_carry_does_not_override_hard_source(tmp_path):
    """Rows with existing hard sources should not be overridden."""
    state = {
        "ACME": {
            "catalyst_source": "SEC_8K_FILING",
            "catalyst_event_type": "FDA_PDUFA_DATE",
            "estimated_event_date": "2026-06-01",
            "first_seen": "2026-03-01",
        }
    }
    state_path = tmp_path / "hard_catalyst_carry.json"
    state_path.write_text(json.dumps(state))

    rows = [
        {
            "ticker": "ACME",
            "catalyst_source": "FDA_CALENDAR",  # already hard
            "catalyst_event_type": "FDA_PDUFA_DATE",
            "catalyst_family": "REGULATORY",
            "is_hard_catalyst": "1",
            "catalyst_days": "60",
        }
    ]

    n = forward_carry_hard_catalysts(rows, date(2026, 4, 5), state_path)
    assert n == 0  # no override needed
    assert rows[0]["catalyst_family"] == "REGULATORY"  # unchanged


def test_review_backfills_family():
    """The review script should backfill family from event_type when missing."""
    family = classify_catalyst_family("CT_PRIMARY_COMPLETION")
    assert family == "CLINICAL"

    family = classify_catalyst_family("DATA_READOUT")
    assert family == "CLINICAL"

    family = classify_catalyst_family("FDA_PDUFA_DATE")
    assert family == "REGULATORY"
