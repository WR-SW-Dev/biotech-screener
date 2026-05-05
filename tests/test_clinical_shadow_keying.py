"""Tests for the clinical-transmission-shadow row keying.

The legacy join key was ``f"{ticker}_{event_type}"`` which collided when the
same ticker had multiple events of the same type at different dates. The new
``shadow_row_key`` uses CatalystNode.node_id with a ticker+event_type+date
fallback for legacy rows.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.clinical_transmission_shadow import shadow_row_key  # noqa: E402


def test_uses_catalyst_id_when_present():
    row = {
        "ticker": "ABCD",
        "event_type": "PDUFA",
        "expected_date": "2026-06-15",
        "catalyst_id": "abc123def456",
    }
    assert shadow_row_key(row) == "abc123def456"


def test_falls_back_to_composite_when_catalyst_id_missing():
    row = {"ticker": "ABCD", "event_type": "PDUFA", "expected_date": "2026-06-15"}
    assert shadow_row_key(row) == "ABCD|PDUFA|2026-06-15"


def test_falls_back_to_composite_when_catalyst_id_blank():
    row = {
        "ticker": "ABCD",
        "event_type": "PDUFA",
        "expected_date": "2026-06-15",
        "catalyst_id": "",
    }
    assert shadow_row_key(row) == "ABCD|PDUFA|2026-06-15"


def test_legacy_collision_is_avoided():
    # Two events: same ticker, same event_type, DIFFERENT expected dates.
    # Under the old f"{ticker}_{event_type}" key, both rows mapped to one
    # bucket and the second silently overwrote the first.
    r1 = {"ticker": "ABCD", "event_type": "DATA_READOUT", "expected_date": "2026-06-15"}
    r2 = {"ticker": "ABCD", "event_type": "DATA_READOUT", "expected_date": "2026-09-01"}
    assert shadow_row_key(r1) != shadow_row_key(r2)


def test_same_event_same_run_collapses():
    # Same catalyst — shadow_row_key must return the same value across calls
    # so default-variant and tx-variant rows for the same node match up.
    r_default = {
        "ticker": "ABCD",
        "event_type": "PDUFA",
        "expected_date": "2026-06-15",
        "catalyst_id": "node_x",
        "rank": 12,
    }
    r_tx = {
        "ticker": "ABCD",
        "event_type": "PDUFA",
        "expected_date": "2026-06-15",
        "catalyst_id": "node_x",
        "rank": 7,
    }
    assert shadow_row_key(r_default) == shadow_row_key(r_tx)


def test_missing_expected_date_in_fallback_is_stable():
    # Two rows with no expected_date AND no catalyst_id but different tickers
    # must still produce different keys.
    r1 = {"ticker": "ABCD", "event_type": "PDUFA", "expected_date": None}
    r2 = {"ticker": "EFGH", "event_type": "PDUFA", "expected_date": None}
    assert shadow_row_key(r1) == "ABCD|PDUFA|"
    assert shadow_row_key(r2) == "EFGH|PDUFA|"
