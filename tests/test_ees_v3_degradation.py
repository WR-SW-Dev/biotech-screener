"""Tests for EES v3 silent-degradation flagging.

When the upstream EES v2 or conditional_model enrichment fails, the
conditional_misprice_score column is absent from csv_rows. EES v3 used to
silently zero out that factor; it now emits `ees_v3_misprice_available=0`
per row so the schema/QA layer can detect the degradation.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from event_ev.ees_v3 import enrich_csv_rows  # noqa: E402


def test_misprice_available_flag_set_when_inputs_present():
    rows = [
        {"ticker": "AAA", "conditional_misprice_score": 0.1, "conditional_expected_move": 22.0},
        {"ticker": "BBB", "conditional_misprice_score": -0.3, "conditional_expected_move": 28.0},
        {"ticker": "CCC", "conditional_misprice_score": 0.2, "conditional_expected_move": 15.0},
    ]
    enrich_csv_rows(rows, as_of_date="2026-04-15")

    for row in rows:
        assert "ees_v3_misprice_available" in row
        assert row["ees_v3_misprice_available"] == "1"
        assert "ees_v3_score" in row


def test_misprice_available_flag_zero_when_ees_v2_failed_upstream():
    """Simulates EES v2 enrichment failure: conditional_misprice_score absent.

    Before the fix, v3 silently zeroed misprice_z for every row and no
    column made that visible. The flag column now makes the degradation
    discoverable by the schema gate.
    """
    rows = [
        # conditional_misprice_score deliberately absent — simulates v2 failure
        {"ticker": "AAA", "conditional_expected_move": 22.0},
        {"ticker": "BBB", "conditional_expected_move": 28.0},
        {"ticker": "CCC", "conditional_expected_move": 15.0},
    ]
    enrich_csv_rows(rows, as_of_date="2026-04-15")

    for row in rows:
        assert row["ees_v3_misprice_available"] == "0", row


def test_misprice_available_mixed_rows():
    """Per-row granularity: rows with misprice should be flagged 1, others 0."""
    rows = [
        {"ticker": "AAA", "conditional_misprice_score": 0.1, "conditional_expected_move": 22.0},
        {"ticker": "BBB", "conditional_expected_move": 28.0},  # missing misprice
        {"ticker": "CCC", "conditional_misprice_score": 0.2, "conditional_expected_move": 15.0},
    ]
    enrich_csv_rows(rows, as_of_date="2026-04-15")

    by_ticker = {r["ticker"]: r for r in rows}
    assert by_ticker["AAA"]["ees_v3_misprice_available"] == "1"
    assert by_ticker["BBB"]["ees_v3_misprice_available"] == "0"
    assert by_ticker["CCC"]["ees_v3_misprice_available"] == "1"


def test_column_listed_in_exported_constant():
    """Schema constant must expose the new column so downstream writers pick it up."""
    from event_ev.ees_v3 import EES_V3_CSV_COLUMNS

    assert "ees_v3_misprice_available" in EES_V3_CSV_COLUMNS


def test_snapshot_columns_includes_flag():
    """run_screen_columns.SNAPSHOT_COLUMNS must include the flag for CSV emission."""
    from run_screen_columns import SNAPSHOT_COLUMNS

    assert "ees_v3_misprice_available" in SNAPSHOT_COLUMNS
