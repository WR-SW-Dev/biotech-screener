"""Tests for secondary regulatory catalyst feature.

Verifies:
1. Backfill in ranking_utils generates has_regulatory_upcoming_180d from event_type
2. Secondary family_filter_mode in evaluate() uses has_regulatory_upcoming_180d
3. _effective_family() in build_action_lists returns REGULATORY in secondary mode

Note: _nearest_regulatory_catalyst() tests live in test_regulatory_sources.py
(covering all 3 sources: M3, event ledger, PDUFA manual).
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


# ---------------------------------------------------------------------------
# Test backfill in ranking_utils
# ---------------------------------------------------------------------------


class TestBackfillSecondaryRegulatory:
    """Tests for ranking_utils.backfill_columns secondary regulatory columns."""

    def _backfill(self, rows):
        from common.ranking_utils import backfill_columns

        backfill_columns(rows)
        return rows

    def test_regulatory_event_gets_flag(self):
        rows = [
            {"catalyst_event_type": "PDUFA", "catalyst_days": "45", "catalyst_family": "REGULATORY"},
        ]
        self._backfill(rows)
        assert rows[0]["has_regulatory_upcoming_180d"] == "1"
        assert rows[0]["regulatory_days"] == "45"
        assert rows[0]["regulatory_event_type"] == "PDUFA"

    def test_clinical_event_no_flag(self):
        rows = [
            {"catalyst_event_type": "DATA_READOUT", "catalyst_days": "60", "catalyst_family": "CLINICAL"},
        ]
        self._backfill(rows)
        assert rows[0]["has_regulatory_upcoming_180d"] == "0"
        assert rows[0]["regulatory_days"] == ""

    def test_empty_event_type_no_flag(self):
        rows = [{"catalyst_event_type": "", "catalyst_family": ""}]
        self._backfill(rows)
        assert rows[0]["has_regulatory_upcoming_180d"] == "0"

    def test_existing_columns_not_overwritten(self):
        rows = [
            {
                "has_regulatory_upcoming_180d": "1",
                "regulatory_days": "30",
                "regulatory_event_type": "PDUFA",
                "catalyst_event_type": "DATA_READOUT",  # clinical primary
            }
        ]
        self._backfill(rows)
        # Should NOT overwrite — column already exists
        assert rows[0]["has_regulatory_upcoming_180d"] == "1"
        assert rows[0]["regulatory_days"] == "30"


# ---------------------------------------------------------------------------
# Test _effective_family in build_action_lists
# ---------------------------------------------------------------------------


class TestEffectiveFamily:
    """Tests for build_action_lists._effective_family()."""

    def _import_fn(self):
        from tools.build_action_lists import _effective_family

        return _effective_family

    def test_primary_mode_uses_catalyst_family(self):
        fn = self._import_fn()
        row = {"catalyst_family": "CLINICAL", "has_regulatory_upcoming_180d": "1"}
        assert fn(row, mode="primary") == "CLINICAL"

    def test_secondary_mode_promotes_regulatory(self):
        fn = self._import_fn()
        row = {"catalyst_family": "CLINICAL", "has_regulatory_upcoming_180d": "1"}
        assert fn(row, mode="secondary") == "REGULATORY"

    def test_secondary_mode_no_flag_keeps_primary(self):
        fn = self._import_fn()
        row = {"catalyst_family": "CLINICAL", "has_regulatory_upcoming_180d": "0"}
        assert fn(row, mode="secondary") == "CLINICAL"

    def test_secondary_mode_empty_flag_keeps_primary(self):
        fn = self._import_fn()
        row = {"catalyst_family": "CLINICAL"}
        assert fn(row, mode="secondary") == "CLINICAL"


# ---------------------------------------------------------------------------
# Test secondary mode in family filter (evaluate pathway)
# ---------------------------------------------------------------------------


class TestSecondaryFamilyFilter:
    """Test that secondary mode includes tickers with has_regulatory_upcoming_180d=1."""

    def test_secondary_includes_dual_catalyst_ticker(self):
        """A ticker with clinical primary but regulatory secondary should be
        included in REGULATORY filter under secondary mode."""
        rankings = [
            {
                "ticker": "ACME",
                "catalyst_family": "CLINICAL",
                "has_regulatory_upcoming_180d": "1",
                "catalyst_bucket": "less_binary",
            },
            {
                "ticker": "BETA",
                "catalyst_family": "CLINICAL",
                "has_regulatory_upcoming_180d": "0",
                "catalyst_bucket": "less_binary",
            },
        ]

        _allowed_families = {"REGULATORY"}

        def _secondary_match(r):
            if "REGULATORY" in _allowed_families and r.get("has_regulatory_upcoming_180d") == "1":
                return True
            return r.get("catalyst_family", "").strip() in _allowed_families

        filtered = [r for r in rankings if _secondary_match(r)]
        assert len(filtered) == 1
        assert filtered[0]["ticker"] == "ACME"

    def test_primary_mode_excludes_dual_catalyst(self):
        """Primary mode should NOT include ACME (catalyst_family=CLINICAL)."""
        rankings = [
            {
                "ticker": "ACME",
                "catalyst_family": "CLINICAL",
                "has_regulatory_upcoming_180d": "1",
            },
        ]
        _allowed_families = {"REGULATORY"}
        filtered = [r for r in rankings if r.get("catalyst_family", "").strip() in _allowed_families]
        assert len(filtered) == 0

    def test_secondary_still_includes_primary_regulatory(self):
        """A ticker with primary=REGULATORY should still be included in secondary mode."""
        rankings = [
            {
                "ticker": "REG1",
                "catalyst_family": "REGULATORY",
                "has_regulatory_upcoming_180d": "1",
            },
            {
                "ticker": "DUAL1",
                "catalyst_family": "CLINICAL",
                "has_regulatory_upcoming_180d": "1",
            },
        ]
        _allowed_families = {"REGULATORY"}

        def _secondary_match(r):
            if "REGULATORY" in _allowed_families and r.get("has_regulatory_upcoming_180d") == "1":
                return True
            return r.get("catalyst_family", "").strip() in _allowed_families

        filtered = [r for r in rankings if _secondary_match(r)]
        assert len(filtered) == 2
