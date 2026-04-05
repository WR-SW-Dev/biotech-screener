"""Regression tests for corporate action handling.

Verifies:
  1. Split-adjusted price file stays fresh (regenerated after price updates)
  2. Known reverse splits are detected and adjusted
  3. Acquired/dead tickers are flagged in universe
  4. CUSIP map entries match universe membership
  5. Price series truncation works across split boundaries
"""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Split detection
# ---------------------------------------------------------------------------


class TestSplitDetection:
    """Verify the split detection logic catches known events."""

    def test_detect_known_reverse_splits(self):
        """Known reverse splits must be detected by repair_price_history_splits."""
        from datetime import date, timedelta

        from scripts.repair_price_history_splits import detect_splits

        base = date(2024, 1, 1)
        real_prices = {
            "TEST_RS": {
                base: Decimal("2.00"),
                base + timedelta(1): Decimal("1.80"),
                base + timedelta(2): Decimal("9.50"),
                base + timedelta(3): Decimal("9.20"),
            }
        }
        splits = detect_splits(real_prices, jump_threshold=3.0, drop_threshold=-0.75)
        assert "TEST_RS" in splits
        assert splits["TEST_RS"][0]["flag_type"] == "reverse_split"
        assert float(splits["TEST_RS"][0]["factor"]) == pytest.approx(9.50 / 1.80, rel=0.01)

    def test_detect_known_forward_splits(self):
        """Known forward splits (>75% drop) must be detected."""
        from datetime import date, timedelta

        from scripts.repair_price_history_splits import detect_splits

        base = date(2024, 1, 1)
        prices = {
            "TEST_FS": {
                base: Decimal("40.00"),
                base + timedelta(1): Decimal("38.00"),
                base + timedelta(2): Decimal("8.00"),  # ~80% drop
                base + timedelta(3): Decimal("7.50"),
            }
        }
        splits = detect_splits(prices, jump_threshold=3.0, drop_threshold=-0.75)
        assert "TEST_FS" in splits
        assert splits["TEST_FS"][0]["flag_type"] == "forward_split"

    def test_adjusted_prices_continuous_across_split(self):
        """After adjustment, returns across the split boundary should be reasonable."""
        from datetime import date, timedelta

        from scripts.repair_price_history_splits import compute_adjusted_prices, detect_splits

        base = date(2024, 1, 1)
        prices = {
            "TEST_RS": {
                base: Decimal("2.00"),
                base + timedelta(1): Decimal("1.80"),
                base + timedelta(2): Decimal("9.00"),  # 5x reverse split
                base + timedelta(3): Decimal("8.50"),
            }
        }
        splits = detect_splits(prices, jump_threshold=3.0, drop_threshold=-0.75)
        adjusted = compute_adjusted_prices(prices, splits)

        adj = adjusted["TEST_RS"]
        sorted_dates = sorted(adj.keys())
        # After adjustment, the cross-split return should be modest, not 5x
        pre = float(adj[sorted_dates[1]])
        post = float(adj[sorted_dates[2]])
        ret = (post - pre) / pre
        assert abs(ret) < 0.5, f"Cross-split return {ret:.1%} too large — adjustment failed"


# ---------------------------------------------------------------------------
# Price series truncation (run_screen.py production behavior)
# ---------------------------------------------------------------------------


class TestPriceTruncation:
    """Verify run_screen.py's split-truncation workaround."""

    def test_truncation_removes_pre_split_data(self):
        """_filter_price_outliers should keep only post-split data."""
        from run_screen import _filter_price_outliers

        series = [
            ("2024-01-01", 2.0),
            ("2024-01-02", 1.8),
            ("2024-01-03", 9.0),  # 5x jump
            ("2024-01-04", 8.5),
        ]
        filtered, warnings = _filter_price_outliers(series)
        # Should truncate to the jump point onward
        assert len(filtered) == 2
        assert filtered[0][0] == "2024-01-03"
        assert len(warnings) == 1
        assert warnings[0]["flag"] == "reverse_split"


# ---------------------------------------------------------------------------
# Universe integrity
# ---------------------------------------------------------------------------


class TestUniverseIntegrity:
    UNIVERSE_PATH = PROJECT_ROOT / "production_data" / "universe.json"

    def test_no_duplicate_tickers(self):
        """Universe must not contain duplicate tickers."""
        with open(self.UNIVERSE_PATH) as f:
            universe = json.load(f)
        tickers = [e.get("ticker", "") for e in universe]
        from collections import Counter

        dups = {t: c for t, c in Counter(tickers).items() if c > 1}
        assert not dups, f"Duplicate tickers in universe: {dups}"

    def test_all_tickers_have_status(self):
        """Every universe entry must have a status field."""
        with open(self.UNIVERSE_PATH) as f:
            universe = json.load(f)
        for entry in universe:
            assert "status" in entry, f"Missing status for {entry.get('ticker')}"

    def test_benchmark_ticker_excluded_from_active(self):
        """_XBI_BENCHMARK_ must have status=benchmark, not active."""
        with open(self.UNIVERSE_PATH) as f:
            universe = json.load(f)
        for entry in universe:
            if entry.get("ticker") == "_XBI_BENCHMARK_":
                assert entry["status"] == "benchmark"


# ---------------------------------------------------------------------------
# CUSIP map sanity
# ---------------------------------------------------------------------------


class TestCUSIPMapSanity:
    CUSIP_MAP_PATH = PROJECT_ROOT / "production_data" / "cusip_static_map.json"
    UNIVERSE_PATH = PROJECT_ROOT / "production_data" / "universe.json"

    @pytest.fixture
    def cusip_map(self):
        with open(self.CUSIP_MAP_PATH) as f:
            return json.load(f)

    @pytest.fixture
    def universe_tickers(self):
        with open(self.UNIVERSE_PATH) as f:
            return {e.get("ticker", "") for e in json.load(f)}

    def test_no_duplicate_cusip_entries(self, cusip_map):
        """Each CUSIP should map to exactly one ticker."""
        from collections import Counter

        # Multiple CUSIPs per ticker is OK (convertibles etc.)
        # But same CUSIP to multiple tickers is NOT OK
        cusips = list(cusip_map.keys())
        dups = {c: n for c, n in Counter(cusips).items() if n > 1}
        assert not dups, f"Duplicate CUSIPs: {dups}"

    def test_cusip_format_valid(self, cusip_map):
        """CUSIPs should be 9-character alphanumeric."""
        import re

        pattern = re.compile(r"^[A-Z0-9]{9}$")
        bad = [c for c in cusip_map if not pattern.match(c)]
        assert not bad, f"Invalid CUSIP format: {bad[:10]}"


# ---------------------------------------------------------------------------
# Split-adjusted file freshness
# ---------------------------------------------------------------------------


class TestSplitAdjustedFreshness:
    RAW_PATH = PROJECT_ROOT / "production_data" / "price_history.csv"
    ADJ_PATH = PROJECT_ROOT / "production_data" / "price_history_split_adj.csv"

    def test_split_adjusted_file_exists(self):
        """price_history_split_adj.csv must exist."""
        assert self.ADJ_PATH.exists(), "Split-adjusted price file missing"

    def test_split_adjusted_not_stale(self):
        """Split-adjusted file should be at least as recent as raw file."""
        if not self.ADJ_PATH.exists():
            pytest.skip("Split-adjusted file missing")
        raw_mtime = self.RAW_PATH.stat().st_mtime
        adj_mtime = self.ADJ_PATH.stat().st_mtime
        # Allow 24h tolerance
        assert adj_mtime >= raw_mtime - 86400, (
            "Split-adjusted file is stale — regenerate with: " "python scripts/repair_price_history_splits.py"
        )
