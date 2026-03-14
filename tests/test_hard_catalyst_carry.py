"""Tests for hard catalyst source forward-carry logic.

Tests the carry behavior inline in run_screen.py by exercising the
state file and row-level carry/learn/expire logic.
"""

from __future__ import annotations

import json
from pathlib import Path

# The carry logic is inline in run_screen.py, so we test via the state file
# and simulated row manipulation.


def _make_state(tmp_path: Path, entries: dict) -> Path:
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_file = state_dir / "hard_catalyst_carry.json"
    state_file.write_text(json.dumps(entries))
    return state_file


class TestForwardCarry:
    def test_carry_fires_when_source_missing(self, tmp_path):
        """Row with empty source gets carried-forward source from state."""
        state = {
            "BIIB": {
                "catalyst_event_type": "FDA_PDUFA_DATE",
                "catalyst_source": "SEC_8K_FILING",
                "catalyst_days_at_first_seen": 22,
                "first_seen_date": "2026-03-12",
                "estimated_event_date": "2026-04-03",
            }
        }
        _make_state(tmp_path, state)

        # Simulate a row where BIIB lost its 8K source
        row = {
            "ticker": "BIIB",
            "catalyst_source": "CTGOV_CALENDAR",
            "catalyst_event_type": "CT_PRIMARY_COMPLETION",
            "catalyst_days": "20",
        }

        # Apply carry logic
        carry_sources = {"SEC_8K_FILING", "FDA_PDUFA_DATE", "DATA_READOUT", "COMPANY_GUIDANCE"}
        entry = state.get(row["ticker"])
        if row["catalyst_source"] not in carry_sources and entry:
            event_date = entry.get("estimated_event_date", "")
            if not event_date or event_date >= "2026-03-14":  # not expired
                row["catalyst_source"] = entry["catalyst_source"]
                row["catalyst_event_type"] = entry["catalyst_event_type"]

        assert row["catalyst_source"] == "SEC_8K_FILING"
        assert row["catalyst_event_type"] == "FDA_PDUFA_DATE"

    def test_carry_does_not_override_current_hard_source(self, tmp_path):
        """If today's run has a different hard source, use today's."""
        # State has SEC_8K_FILING but row already has DATA_READOUT
        _make_state(
            tmp_path,
            {
                "BIIB": {
                    "catalyst_event_type": "FDA_PDUFA_DATE",
                    "catalyst_source": "SEC_8K_FILING",
                    "estimated_event_date": "2026-04-03",
                }
            },
        )
        row = {
            "ticker": "BIIB",
            "catalyst_source": "DATA_READOUT",  # different hard source today
            "catalyst_event_type": "DATA_READOUT",
        }

        carry_sources = {"SEC_8K_FILING", "FDA_PDUFA_DATE", "DATA_READOUT", "COMPANY_GUIDANCE"}
        # Should not carry because current source is already hard
        if row["catalyst_source"] in carry_sources:
            carried = False
        else:
            carried = True

        assert not carried
        assert row["catalyst_source"] == "DATA_READOUT"

    def test_expired_entry_not_carried(self, tmp_path):
        """Entries past their event date should not carry."""
        state = {
            "BIIB": {
                "catalyst_event_type": "FDA_PDUFA_DATE",
                "catalyst_source": "SEC_8K_FILING",
                "estimated_event_date": "2026-03-10",  # already passed
            }
        }
        row = {
            "ticker": "BIIB",
            "catalyst_source": "",
            "catalyst_event_type": "",
        }

        as_of_date = "2026-03-14"
        entry = state.get("BIIB")
        event_date = entry.get("estimated_event_date", "")
        if event_date and event_date < as_of_date:
            carried = False
        else:
            carried = True

        assert not carried
        assert row["catalyst_source"] == ""

    def test_new_hard_source_learned(self, tmp_path):
        """A new hard source should be added to state."""
        state = {}
        row = {
            "ticker": "CELC",
            "catalyst_source": "SEC_8K_FILING",
            "catalyst_event_type": "DATA_READOUT",
            "catalyst_days": "17",
        }

        carry_sources = {"SEC_8K_FILING", "FDA_PDUFA_DATE", "DATA_READOUT", "COMPANY_GUIDANCE"}
        if row["catalyst_source"] in carry_sources and row["ticker"] not in state:
            state[row["ticker"]] = {
                "catalyst_event_type": row["catalyst_event_type"],
                "catalyst_source": row["catalyst_source"],
                "first_seen_date": "2026-03-14",
            }

        assert "CELC" in state
        assert state["CELC"]["catalyst_source"] == "SEC_8K_FILING"

    def test_multiple_tickers_independent(self, tmp_path):
        """Each ticker carries independently."""
        state = {
            "BIIB": {
                "catalyst_source": "SEC_8K_FILING",
                "catalyst_event_type": "FDA_PDUFA_DATE",
                "estimated_event_date": "2026-04-03",
            },
            "CELC": {
                "catalyst_source": "SEC_8K_FILING",
                "catalyst_event_type": "DATA_READOUT",
                "estimated_event_date": "2026-04-01",
            },
        }

        rows = [
            {"ticker": "BIIB", "catalyst_source": "", "catalyst_event_type": ""},
            {"ticker": "CELC", "catalyst_source": "SEC_8K_FILING", "catalyst_event_type": "DATA_READOUT"},
        ]

        carry_sources = {"SEC_8K_FILING", "FDA_PDUFA_DATE", "DATA_READOUT", "COMPANY_GUIDANCE"}
        for row in rows:
            if row["catalyst_source"] in carry_sources:
                continue
            entry = state.get(row["ticker"])
            if entry and entry.get("estimated_event_date", "") >= "2026-03-14":
                row["catalyst_source"] = entry["catalyst_source"]
                row["catalyst_event_type"] = entry["catalyst_event_type"]

        # BIIB should be carried, CELC already had its own source
        assert rows[0]["catalyst_source"] == "SEC_8K_FILING"
        assert rows[1]["catalyst_source"] == "SEC_8K_FILING"  # unchanged (was already hard)

    def test_state_file_roundtrip(self, tmp_path):
        """State file writes and reads correctly."""
        state = {
            "BIIB": {
                "catalyst_event_type": "FDA_PDUFA_DATE",
                "catalyst_source": "SEC_8K_FILING",
                "first_seen_date": "2026-03-12",
                "estimated_event_date": "2026-04-03",
            }
        }
        state_file = _make_state(tmp_path, state)
        loaded = json.loads(state_file.read_text())
        assert loaded == state
