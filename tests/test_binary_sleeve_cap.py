"""Tests for binary sleeve risk cap in L3 position sizing."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from decision_engine import DecisionRuleset, _is_binary_name, apply_binary_sleeve_caps, compute_target_weights

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_row(
    ticker: str,
    size_band: str = "M",
    catalyst_days: object = "",
    catalyst_mode: str = "no_upcoming",
    target_weight_pct: float = 0.0,
) -> dict:
    return {
        "ticker": ticker,
        "size_band": size_band,
        "catalyst_days": catalyst_days,
        "catalyst_mode": catalyst_mode,
        "target_weight_pct": target_weight_pct,
    }


def _total_weight(rows):
    return sum(float(r.get("target_weight_pct", 0) or 0) for r in rows)


# ---------------------------------------------------------------------------
# _is_binary_name
# ---------------------------------------------------------------------------


class TestIsBinaryName:

    def test_specific_days_within_threshold(self):
        row = _make_row("A", catalyst_days=15, catalyst_mode="specific_days")
        assert _is_binary_name(row, 30) is True

    def test_specific_days_above_threshold(self):
        row = _make_row("A", catalyst_days=45, catalyst_mode="specific_days")
        assert _is_binary_name(row, 30) is False

    def test_blended_window_counts_as_binary(self):
        row = _make_row("A", catalyst_days=0, catalyst_mode="blended_window")
        assert _is_binary_name(row, 30) is True

    def test_no_upcoming_not_binary(self):
        row = _make_row("A", catalyst_days=10, catalyst_mode="no_upcoming")
        assert _is_binary_name(row, 30) is False

    def test_missing_mode_not_binary(self):
        row = _make_row("A", catalyst_days=5, catalyst_mode="missing")
        assert _is_binary_name(row, 30) is False

    def test_far_window_not_binary(self):
        row = _make_row("A", catalyst_days=20, catalyst_mode="far_window")
        assert _is_binary_name(row, 30) is False


# ---------------------------------------------------------------------------
# apply_binary_sleeve_caps
# ---------------------------------------------------------------------------


class TestBinarySleeveDefaults:

    def test_defaults_no_change(self):
        """Default caps (100%) produce identical weights."""
        rs = DecisionRuleset()
        rows = [
            _make_row("BIN1", catalyst_days=10, catalyst_mode="specific_days", target_weight_pct=15.0),
            _make_row("BIN2", catalyst_days=20, catalyst_mode="specific_days", target_weight_pct=15.0),
            _make_row("SAFE", catalyst_days=90, catalyst_mode="specific_days", target_weight_pct=70.0),
        ]
        orig = [r["target_weight_pct"] for r in rows]
        apply_binary_sleeve_caps(rows, rs)
        after = [r["target_weight_pct"] for r in rows]
        assert orig == after


class TestPerNameCap:

    def test_per_name_cap_clamps(self):
        """Binary name exceeding per-name cap gets clamped; excess redistributed."""
        rs = DecisionRuleset(binary_sleeve_per_name_max_pct=10.0)
        rows = [
            _make_row("BIN1", catalyst_days=5, catalyst_mode="specific_days", target_weight_pct=20.0),
            _make_row("SAFE1", catalyst_days=90, catalyst_mode="no_upcoming", target_weight_pct=40.0),
            _make_row("SAFE2", catalyst_days=120, catalyst_mode="no_upcoming", target_weight_pct=40.0),
        ]
        apply_binary_sleeve_caps(rows, rs)
        # BIN1 should be clamped to ≤10%
        assert float(rows[0]["target_weight_pct"]) <= 10.0 + 0.01
        # Total still ~100%
        assert abs(_total_weight(rows) - 100.0) < 0.1

    def test_non_binary_unaffected_by_per_name_cap(self):
        """Non-binary weights only grow from redistribution (never shrink)."""
        rs = DecisionRuleset(binary_sleeve_per_name_max_pct=5.0)
        rows = [
            _make_row("BIN1", catalyst_days=10, catalyst_mode="specific_days", target_weight_pct=15.0),
            _make_row("SAFE1", catalyst_days=200, catalyst_mode="no_upcoming", target_weight_pct=85.0),
        ]
        apply_binary_sleeve_caps(rows, rs)
        # SAFE1 should have gained weight
        assert float(rows[1]["target_weight_pct"]) >= 85.0


class TestAggregateCap:

    def test_aggregate_cap_scales_down(self):
        """3 binary names totaling 30% capped to 20%."""
        rs = DecisionRuleset(binary_sleeve_max_weight_pct=20.0)
        rows = [
            _make_row("BIN1", catalyst_days=5, catalyst_mode="specific_days", target_weight_pct=10.0),
            _make_row("BIN2", catalyst_days=10, catalyst_mode="specific_days", target_weight_pct=10.0),
            _make_row("BIN3", catalyst_days=25, catalyst_mode="blended_window", target_weight_pct=10.0),
            _make_row("SAFE", catalyst_days=200, catalyst_mode="no_upcoming", target_weight_pct=70.0),
        ]
        apply_binary_sleeve_caps(rows, rs)
        binary_total = sum(float(rows[i]["target_weight_pct"]) for i in range(3))
        assert binary_total <= 20.0 + 0.1
        assert abs(_total_weight(rows) - 100.0) < 0.1


class TestEdgeCases:

    def test_no_binary_names_no_change(self):
        """All names > threshold → caps have zero effect."""
        rs = DecisionRuleset(
            binary_sleeve_max_weight_pct=10.0,
            binary_sleeve_per_name_max_pct=5.0,
        )
        rows = [
            _make_row("A", catalyst_days=60, catalyst_mode="specific_days", target_weight_pct=50.0),
            _make_row("B", catalyst_days=90, catalyst_mode="no_upcoming", target_weight_pct=50.0),
        ]
        orig = [r["target_weight_pct"] for r in rows]
        apply_binary_sleeve_caps(rows, rs)
        after = [r["target_weight_pct"] for r in rows]
        assert orig == after

    def test_normalization_preserved(self):
        """Weights sum to 100% after capping."""
        rs = DecisionRuleset(
            binary_sleeve_max_weight_pct=15.0,
            binary_sleeve_per_name_max_pct=8.0,
        )
        rows = [
            _make_row("BIN1", catalyst_days=5, catalyst_mode="specific_days", target_weight_pct=12.0),
            _make_row("BIN2", catalyst_days=10, catalyst_mode="specific_days", target_weight_pct=12.0),
            _make_row("BIN3", catalyst_days=20, catalyst_mode="blended_window", target_weight_pct=12.0),
            _make_row("S1", catalyst_days=100, catalyst_mode="no_upcoming", target_weight_pct=32.0),
            _make_row("S2", catalyst_days=200, catalyst_mode="no_upcoming", target_weight_pct=32.0),
        ]
        apply_binary_sleeve_caps(rows, rs)
        assert abs(_total_weight(rows) - 100.0) < 0.15  # rounding tolerance


class TestComputeTargetWeightsIntegration:

    def test_compute_target_weights_applies_caps(self):
        """compute_target_weights calls apply_binary_sleeve_caps."""
        rs = DecisionRuleset(binary_sleeve_per_name_max_pct=3.0)
        # All same band → equal raw weights → equal normalized (25% each)
        rows = [
            _make_row("BIN", catalyst_days=5, catalyst_mode="specific_days"),
            _make_row("S1", catalyst_mode="no_upcoming"),
            _make_row("S2", catalyst_mode="no_upcoming"),
            _make_row("S3", catalyst_mode="no_upcoming"),
        ]
        compute_target_weights(rows, ruleset=rs)
        # BIN should be capped to ~3% (from 25%)
        assert float(rows[0]["target_weight_pct"]) <= 3.0 + 0.1
        assert abs(_total_weight(rows) - 100.0) < 0.15


# ---------------------------------------------------------------------------
# Ruleset validation
# ---------------------------------------------------------------------------


class TestRulesetValidation:

    def test_rejects_zero_cap(self):
        with pytest.raises(ValueError, match="binary_sleeve_max_weight_pct"):
            DecisionRuleset(binary_sleeve_max_weight_pct=0.0)

    def test_rejects_negative_cap(self):
        with pytest.raises(ValueError, match="binary_sleeve_per_name_max_pct"):
            DecisionRuleset(binary_sleeve_per_name_max_pct=-5.0)

    def test_rejects_over_100_cap(self):
        with pytest.raises(ValueError, match="binary_sleeve_max_weight_pct"):
            DecisionRuleset(binary_sleeve_max_weight_pct=101.0)

    def test_rejects_negative_days_threshold(self):
        with pytest.raises(ValueError, match="binary_sleeve_days_threshold"):
            DecisionRuleset(binary_sleeve_days_threshold=-1)

    def test_accepts_valid_caps(self):
        rs = DecisionRuleset(
            binary_sleeve_max_weight_pct=25.0,
            binary_sleeve_per_name_max_pct=5.0,
            binary_sleeve_days_threshold=45,
        )
        assert rs.binary_sleeve_max_weight_pct == 25.0
        assert rs.binary_sleeve_per_name_max_pct == 5.0
        assert rs.binary_sleeve_days_threshold == 45
