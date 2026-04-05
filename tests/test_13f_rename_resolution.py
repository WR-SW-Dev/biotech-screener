"""Tests for ticker rename resolution in the 13F pipeline.

Verifies that holdings filed under old ticker symbols (e.g. BGNE) are
correctly resolved to their current names (e.g. ONC) using the corporate
actions registry, and that the resolution is PIT-safe.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.corporate_actions import load_actions
from scripts.build_coinvest_features_from_13f import _resolve_ticker


class TestResolveTickerRename:
    """Verify _resolve_ticker handles renames via corporate actions."""

    def setup_method(self):
        self.reg = load_actions()

    def test_bgne_to_onc_after_rename(self):
        """BGNE holding resolves to ONC after 2025-01-02."""
        h = {"ticker": "BGNE"}
        result = _resolve_ticker(h, {}, ca_registry=self.reg, as_of="2025-06-01")
        assert result == "ONC"

    def test_bgne_stays_bgne_before_rename(self):
        """BGNE stays BGNE before the rename date (PIT safety)."""
        h = {"ticker": "BGNE"}
        result = _resolve_ticker(h, {}, ca_registry=self.reg, as_of="2024-12-01")
        assert result == "BGNE"

    def test_agle_to_syre(self):
        """AGLE resolves to SYRE after rename."""
        h = {"ticker": "AGLE"}
        result = _resolve_ticker(h, {}, ca_registry=self.reg, as_of="2024-01-01")
        assert result == "SYRE"

    def test_normal_ticker_unchanged(self):
        """Tickers without renames pass through unchanged."""
        h = {"ticker": "VRTX"}
        result = _resolve_ticker(h, {}, ca_registry=self.reg, as_of="2025-06-01")
        assert result == "VRTX"

    def test_cusip_fallback_then_rename(self):
        """CUSIP resolution + rename chain works together."""
        # Simulate: holding has no ticker but a CUSIP that maps to old name
        h = {"ticker": "", "cusip": "TEST123AB"}
        cusip_map = {"TEST123AB": "BGNE"}
        result = _resolve_ticker(h, cusip_map, ca_registry=self.reg, as_of="2025-06-01")
        assert result == "ONC"

    def test_no_registry_passthrough(self):
        """Without a registry, old tickers pass through unresolved."""
        h = {"ticker": "BGNE"}
        result = _resolve_ticker(h, {}, ca_registry=None, as_of="")
        assert result == "BGNE"
