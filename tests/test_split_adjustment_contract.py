"""
Split-adjustment contract tests.

Codifies the invariant that stock splits must be detected and excluded
from all return calculations. This prevents contaminated IC signals.

Contract:
1. detect_split_warnings flags anchor-to-forward jumps > +300% or < -75%
2. Forward returns for flagged tickers are NEVER included in IC computation
3. Thresholds are constants (not configurable at runtime)
"""

from tools.warm_price_cache import SPLIT_DROP_THRESHOLD, SPLIT_JUMP_THRESHOLD, detect_split_warnings


class TestSplitDetectionContract:
    """Verify split detection thresholds and behavior."""

    def test_thresholds_are_fixed(self):
        """Thresholds must not drift — they're part of the data contract."""
        assert SPLIT_JUMP_THRESHOLD == 3.0, "Split jump threshold changed"
        assert SPLIT_DROP_THRESHOLD == -0.75, "Split drop threshold changed"

    def test_2_for_1_split_not_flagged(self):
        """2:1 forward split: -50%. Below threshold (-75%), NOT flagged."""
        rows = [{"ticker": "ACME", "anchor_close": "100", "h20_close": "50"}]
        warnings = detect_split_warnings(rows)
        assert len(warnings) == 0  # -50% > -75% threshold

    def test_4_for_1_split_flagged(self):
        """4:1 forward split: -80%. Below threshold (-75%), IS flagged."""
        rows = [{"ticker": "ACME", "anchor_close": "100", "h20_close": "20"}]
        warnings = detect_split_warnings(rows)
        assert len(warnings) == 1
        assert warnings[0]["pct_change"] == -0.8

    def test_reverse_split_detected(self):
        """Reverse split: price jumps > 300%, should be flagged."""
        rows = [{"ticker": "REVS", "anchor_close": "2", "h20_close": "20"}]
        warnings = detect_split_warnings(rows)
        assert len(warnings) == 1
        assert warnings[0]["ticker"] == "REVS"
        assert warnings[0]["pct_change"] == 9.0  # +900%

    def test_normal_move_not_flagged(self):
        """Normal price movement should not trigger split warning."""
        rows = [
            {"ticker": "NORM", "anchor_close": "50", "h20_close": "65"},  # +30%
            {"ticker": "DIP", "anchor_close": "50", "h20_close": "35"},  # -30%
        ]
        warnings = detect_split_warnings(rows)
        assert len(warnings) == 0

    def test_multiple_horizons_independent(self):
        """Split at one horizon should not contaminate other horizons."""
        rows = [
            {
                "ticker": "MULTI",
                "anchor_close": "10",
                "h5_close": "12",  # +20% — normal
                "h20_close": "50",  # +400% — split
            }
        ]
        warnings = detect_split_warnings(rows)
        flagged_horizons = {w["horizon"] for w in warnings}
        assert 5 not in flagged_horizons
        assert 20 in flagged_horizons

    def test_zero_anchor_skipped(self):
        """Zero or negative anchor should not cause division errors."""
        rows = [
            {"ticker": "ZERO", "anchor_close": "0", "h20_close": "10"},
            {"ticker": "NEG", "anchor_close": "-1", "h20_close": "10"},
        ]
        warnings = detect_split_warnings(rows)
        assert len(warnings) == 0

    def test_missing_forward_price_skipped(self):
        """Missing forward price should not produce warnings."""
        rows = [{"ticker": "MISS", "anchor_close": "50", "h20_close": ""}]
        warnings = detect_split_warnings(rows)
        assert len(warnings) == 0

    def test_return_schema_has_required_keys(self):
        """Each warning must have ticker, horizon, anchor_close, forward_close, pct_change."""
        rows = [{"ticker": "SPL", "anchor_close": "10", "h20_close": "50"}]
        warnings = detect_split_warnings(rows)
        assert len(warnings) == 1
        w = warnings[0]
        assert set(w.keys()) == {"ticker", "horizon", "anchor_close", "forward_close", "pct_change"}
