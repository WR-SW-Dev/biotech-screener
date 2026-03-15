"""Tests for common/hard_catalyst_carry.py (Spec 011)."""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from common.hard_catalyst_carry import forward_carry_hard_catalysts, load_carry_state


def _row(ticker, source="CTGOV_CALENDAR", event_type="CT_PRIMARY_COMPLETION", cat_days="60"):
    return {
        "ticker": ticker,
        "catalyst_source": source,
        "catalyst_event_type": event_type,
        "catalyst_days": cat_days,
        "is_hard_catalyst": "0",
    }


class TestCarryFiresOnSoftSource:
    def test_carry_overrides_ctgov(self, tmp_path):
        state_path = tmp_path / "carry.json"
        state_path.write_text(
            json.dumps(
                {
                    "BIIB": {
                        "catalyst_event_type": "FDA_PDUFA_DATE",
                        "catalyst_source": "SEC_8K_FILING",
                        "catalyst_days_at_first_seen": "22",
                        "first_seen_date": "2026-03-12",
                        "estimated_event_date": "2026-04-03",
                    }
                }
            )
        )

        rows = [_row("BIIB")]
        count = forward_carry_hard_catalysts(rows, date(2026, 3, 15), state_path)
        assert count == 1
        assert rows[0]["catalyst_source"] == "SEC_8K_FILING"
        assert rows[0]["catalyst_event_type"] == "FDA_PDUFA_DATE"
        assert rows[0]["is_hard_catalyst"] == "1"

    def test_carry_overrides_empty_source(self, tmp_path):
        state_path = tmp_path / "carry.json"
        state_path.write_text(
            json.dumps(
                {
                    "CELC": {
                        "catalyst_event_type": "DATA_READOUT",
                        "catalyst_source": "SEC_8K_FILING",
                        "catalyst_days_at_first_seen": "17",
                        "first_seen_date": "2026-03-14",
                        "estimated_event_date": "2026-03-31",
                    }
                }
            )
        )

        rows = [_row("CELC", source="", event_type="")]
        count = forward_carry_hard_catalysts(rows, date(2026, 3, 15), state_path)
        assert count == 1
        assert rows[0]["catalyst_source"] == "SEC_8K_FILING"

    def test_carry_overrides_ctgov_pcd_far(self, tmp_path):
        state_path = tmp_path / "carry.json"
        state_path.write_text(
            json.dumps(
                {
                    "PVLA": {
                        "catalyst_event_type": "DATA_READOUT",
                        "catalyst_source": "SEC_8K_FILING",
                        "catalyst_days_at_first_seen": "17",
                        "first_seen_date": "2026-03-14",
                        "estimated_event_date": "2026-03-31",
                    }
                }
            )
        )

        rows = [_row("PVLA", source="CTGOV_PCD_FAR", event_type="CT_PRIMARY_COMPLETION")]
        count = forward_carry_hard_catalysts(rows, date(2026, 3, 15), state_path)
        assert count == 1
        assert rows[0]["catalyst_source"] == "SEC_8K_FILING"


class TestCarryDoesNotOverrideHard:
    def test_todays_hard_source_wins(self, tmp_path):
        state_path = tmp_path / "carry.json"
        state_path.write_text(
            json.dumps(
                {
                    "BIIB": {
                        "catalyst_event_type": "FDA_PDUFA_DATE",
                        "catalyst_source": "SEC_8K_FILING",
                        "catalyst_days_at_first_seen": "22",
                        "first_seen_date": "2026-03-12",
                        "estimated_event_date": "2026-04-03",
                    }
                }
            )
        )

        rows = [_row("BIIB", source="FDA_PDUFA_DATE", event_type="FDA_PDUFA_DATE")]
        count = forward_carry_hard_catalysts(rows, date(2026, 3, 15), state_path)
        assert count == 0
        assert rows[0]["catalyst_source"] == "FDA_PDUFA_DATE"


class TestStateExpiration:
    def test_expired_entry_removed(self, tmp_path):
        state_path = tmp_path / "carry.json"
        state_path.write_text(
            json.dumps(
                {
                    "OLD": {
                        "catalyst_event_type": "DATA_READOUT",
                        "catalyst_source": "SEC_8K_FILING",
                        "catalyst_days_at_first_seen": "10",
                        "first_seen_date": "2026-01-01",
                        "estimated_event_date": "2026-01-11",
                    }
                }
            )
        )

        rows = [_row("OLD")]
        count = forward_carry_hard_catalysts(rows, date(2026, 3, 15), state_path)
        assert count == 0

        state = load_carry_state(state_path)
        assert "OLD" not in state


class TestLearnNewHardSources:
    def test_new_hard_source_added_to_state(self, tmp_path):
        state_path = tmp_path / "carry.json"

        rows = [_row("PVLA", source="SEC_8K_FILING", event_type="DATA_READOUT", cat_days="17")]
        forward_carry_hard_catalysts(rows, date(2026, 3, 15), state_path)

        state = load_carry_state(state_path)
        assert "PVLA" in state
        assert state["PVLA"]["catalyst_source"] == "SEC_8K_FILING"
        assert state["PVLA"]["first_seen_date"] == "2026-03-15"
        assert state["PVLA"]["estimated_event_date"] == "2026-04-01"


class TestMultipleTickersIndependent:
    def test_independent_carry(self, tmp_path):
        state_path = tmp_path / "carry.json"
        state_path.write_text(
            json.dumps(
                {
                    "BIIB": {
                        "catalyst_event_type": "FDA_PDUFA_DATE",
                        "catalyst_source": "SEC_8K_FILING",
                        "catalyst_days_at_first_seen": "22",
                        "first_seen_date": "2026-03-12",
                        "estimated_event_date": "2026-04-03",
                    },
                    "CELC": {
                        "catalyst_event_type": "DATA_READOUT",
                        "catalyst_source": "SEC_8K_FILING",
                        "catalyst_days_at_first_seen": "17",
                        "first_seen_date": "2026-03-14",
                        "estimated_event_date": "2026-03-31",
                    },
                }
            )
        )

        rows = [
            _row("BIIB"),  # soft — should carry
            _row("CELC", source="SEC_8K_FILING", event_type="DATA_READOUT"),  # hard today
            _row("AAAA"),  # no state entry
        ]
        count = forward_carry_hard_catalysts(rows, date(2026, 3, 15), state_path)
        assert count == 1
        assert rows[0]["catalyst_source"] == "SEC_8K_FILING"
        assert rows[1]["catalyst_source"] == "SEC_8K_FILING"
        assert rows[2]["catalyst_source"] == "CTGOV_CALENDAR"


class TestEmptyState:
    def test_missing_state_file(self, tmp_path):
        state_path = tmp_path / "nonexistent.json"
        rows = [_row("BIIB")]
        count = forward_carry_hard_catalysts(rows, date(2026, 3, 15), state_path)
        assert count == 0

    def test_empty_rows(self, tmp_path):
        state_path = tmp_path / "carry.json"
        count = forward_carry_hard_catalysts([], date(2026, 3, 15), state_path)
        assert count == 0
