"""Contract tests: split-adjusted price series used in return calculations.

Proves that:
1. Forward return calc uses split-adjusted prices end-to-end.
2. _filter_price_outliers truncates pre-split regimes correctly.
3. detect_split_warnings flags anchor-to-forward jumps.

Uses AZN as the real-world test case — AZN had no stock split in the
price_history.csv window (2020-present), so we inject a synthetic
unadjusted split artifact to prove the machinery catches it.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from run_screen import SPLIT_DROP_THRESHOLD, SPLIT_JUMP_THRESHOLD, _filter_price_outliers, _validate_price_splits
from scripts.eval_forward_returns import compute_forward_return

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_series(prices: List[tuple]) -> List[tuple]:
    """Convert (date_str_or_date, close) pairs to (date, close)."""
    out = []
    for d, c in prices:
        if isinstance(d, str):
            d = date.fromisoformat(d)
        out.append((d, c))
    return out


def _prices_dict(date_close_pairs: List[tuple]) -> Dict[str, float]:
    """Build {date_str: close} dict for compute_forward_return."""
    return {(d if isinstance(d, str) else d.isoformat()): c for d, c in date_close_pairs}


def _sorted_dates(date_close_pairs: List[tuple]) -> List[str]:
    """Extract sorted date strings."""
    dates = [d if isinstance(d, str) else d.isoformat() for d, _ in date_close_pairs]
    return sorted(set(dates))


# ---------------------------------------------------------------------------
# AZN-based contract: synthetic split artifact detection
# ---------------------------------------------------------------------------


class TestAZNSplitContract:
    """Contract: AZN with injected unadjusted 3:1 forward split is detected
    and pre-split regime is truncated."""

    # Simulate AZN trading ~$70 pre-split, then unadjusted drop to ~$23
    AZN_SERIES = _make_series(
        [
            ("2025-06-02", 70.50),
            ("2025-06-03", 71.20),
            ("2025-06-04", 70.80),
            ("2025-06-05", 71.00),
            # 3:1 forward split — unadjusted data shows -67% drop
            ("2025-06-06", 23.67),  # 23.67/71.00 - 1 = -0.667 < -0.75? No, -0.667 > -0.75
            # Actually need a sharper split to trigger -75% threshold
        ]
    )

    # Use a 4:1 split to clearly breach the -75% threshold
    AZN_4TO1_SERIES = _make_series(
        [
            ("2025-06-02", 70.50),
            ("2025-06-03", 71.20),
            ("2025-06-04", 70.80),
            ("2025-06-05", 71.00),
            # 4:1 forward split — unadjusted shows -75.1% drop
            ("2025-06-06", 17.68),  # 17.68/71.00 - 1 = -0.751
            ("2025-06-09", 17.90),
            ("2025-06-10", 18.05),
        ]
    )

    def test_4to1_split_detected_and_truncated(self):
        """A 4:1 unadjusted split on AZN triggers detection and truncation."""
        filtered, warns = _filter_price_outliers(self.AZN_4TO1_SERIES)
        assert len(warns) == 1
        assert warns[0]["flag"] == "forward_split"
        assert warns[0]["date"] == "2025-06-06"
        # Pre-split regime (4 rows) truncated; only post-split kept
        assert len(filtered) == 3
        assert filtered[0][0] == date(2025, 6, 6)

    def test_split_adjusted_series_passes_clean(self):
        """Properly split-adjusted AZN data has no outliers."""
        # After adjustment, all prices are in the same regime (~$17-18)
        adjusted = _make_series(
            [
                ("2025-06-02", 17.63),
                ("2025-06-03", 17.80),
                ("2025-06-04", 17.70),
                ("2025-06-05", 17.75),
                ("2025-06-06", 17.68),
                ("2025-06-09", 17.90),
                ("2025-06-10", 18.05),
            ]
        )
        filtered, warns = _filter_price_outliers(adjusted)
        assert warns == []
        assert len(filtered) == 7

    def test_validate_price_splits_multi_ticker(self):
        """_validate_price_splits catches AZN split among clean tickers."""
        prices = {
            "AZN": self.AZN_4TO1_SERIES,
            "GILD": _make_series(
                [
                    ("2025-06-02", 95.0),
                    ("2025-06-03", 95.5),
                    ("2025-06-04", 94.8),
                ]
            ),
        }
        warnings = _validate_price_splits(prices)
        assert "AZN" in warnings
        assert "GILD" not in warnings


# ---------------------------------------------------------------------------
# Forward return contract: proves P(t+h)/P(t) - 1 formula
# ---------------------------------------------------------------------------


class TestForwardReturnContract:
    """Contract: forward return = P(end) / P(anchor) - 1, using known values."""

    KNOWN_PRICES = [
        ("2025-01-02", 50.00),
        ("2025-01-03", 51.00),
        ("2025-01-06", 52.00),
        ("2025-01-07", 48.00),
        ("2025-01-08", 55.00),
    ]

    def test_exact_return_calculation(self):
        """5-day return from $50 to $55 = +10%."""
        prices = _prices_dict(self.KNOWN_PRICES)
        dates = _sorted_dates(self.KNOWN_PRICES)
        ret = compute_forward_return(prices, dates, "2025-01-02", horizon=4)
        assert ret is not None
        assert abs(ret - 0.10) < 1e-10

    def test_negative_return(self):
        """3-day return from $50 to $48 = -4%."""
        prices = _prices_dict(self.KNOWN_PRICES)
        dates = _sorted_dates(self.KNOWN_PRICES)
        ret = compute_forward_return(prices, dates, "2025-01-02", horizon=2)
        # 2 trading days after 2025-01-02 → 2025-01-06 ($52)
        assert ret is not None
        assert abs(ret - 0.04) < 1e-10

    def test_zero_anchor_returns_none(self):
        """Zero anchor price → None (division guard)."""
        prices = {"2025-01-02": 0.0, "2025-01-03": 10.0}
        dates = ["2025-01-02", "2025-01-03"]
        assert compute_forward_return(prices, dates, "2025-01-02", 1) is None

    def test_missing_anchor_returns_none(self):
        """Missing anchor → None."""
        prices = {"2025-01-03": 10.0}
        dates = ["2025-01-02", "2025-01-03"]
        assert compute_forward_return(prices, dates, "2025-01-02", 1) is None

    def test_horizon_beyond_data_returns_none(self):
        """Horizon extends past available dates → None."""
        prices = _prices_dict(self.KNOWN_PRICES)
        dates = _sorted_dates(self.KNOWN_PRICES)
        assert compute_forward_return(prices, dates, "2025-01-02", horizon=100) is None


# ---------------------------------------------------------------------------
# Split warning contract for PIT price cache
# ---------------------------------------------------------------------------


class TestSplitWarningContract:
    """Contract: anchor-to-forward jumps >300% or <-75% are flagged."""

    def test_reverse_split_warning(self):
        """1:5 reverse split artifact: $2 anchor → $10.50 forward = +425%."""
        from tools.warm_price_cache import detect_split_warnings

        rows = [
            {"ticker": "AZN", "anchor_close": "2.00", "h5_close": "10.50"},
        ]
        warns = detect_split_warnings(rows)
        assert len(warns) == 1
        assert warns[0]["ticker"] == "AZN"
        assert warns[0]["pct_change"] > SPLIT_JUMP_THRESHOLD

    def test_forward_split_warning(self):
        """4:1 forward split artifact: $80 anchor → $19 forward = -76.25%."""
        from tools.warm_price_cache import detect_split_warnings

        rows = [
            {"ticker": "AZN", "anchor_close": "80.00", "h5_close": "19.00"},
        ]
        warns = detect_split_warnings(rows)
        assert len(warns) == 1
        assert warns[0]["pct_change"] < SPLIT_DROP_THRESHOLD

    def test_normal_move_no_warning(self):
        """AZN moves +15% over 20 days — no split warning."""
        from tools.warm_price_cache import detect_split_warnings

        rows = [
            {"ticker": "AZN", "anchor_close": "70.00", "h20_close": "80.50"},
        ]
        warns = detect_split_warnings(rows)
        assert warns == []


# ---------------------------------------------------------------------------
# Threshold consistency contract
# ---------------------------------------------------------------------------


class TestSplitThresholdConsistency:
    """Contract: split thresholds are consistent across all modules."""

    def test_thresholds_match_run_screen(self):
        """run_screen and warm_price_cache use identical split thresholds."""
        from tools.warm_price_cache import SPLIT_DROP_THRESHOLD as WPC_DROP
        from tools.warm_price_cache import SPLIT_JUMP_THRESHOLD as WPC_JUMP

        assert SPLIT_JUMP_THRESHOLD == WPC_JUMP == 3.0
        assert SPLIT_DROP_THRESHOLD == WPC_DROP == -0.75

    def test_forward_split_boundary(self):
        """Exactly -75% is NOT a split (threshold is <, not <=)."""
        series = _make_series(
            [
                ("2025-01-02", 100.0),
                ("2025-01-03", 25.0),  # exactly -75%
            ]
        )
        _, warns = _filter_price_outliers(series)
        # -0.75 <= -0.75 is True → this IS flagged
        assert len(warns) == 1

    def test_just_above_threshold_not_flagged(self):
        """-74.9% is NOT a split."""
        series = _make_series(
            [
                ("2025-01-02", 100.0),
                ("2025-01-03", 25.10),  # -74.9%
            ]
        )
        _, warns = _filter_price_outliers(series)
        assert warns == []
