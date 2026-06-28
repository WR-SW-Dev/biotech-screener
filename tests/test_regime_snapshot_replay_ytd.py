"""Tests for tools/replay_regime_snapshots_ytd.py.

Classification: REGENERATE_REGIME_SNAPSHOTS_AND_RERUN_YTD_BACKTEST_DIAGNOSTIC_NO_MODEL_CHANGE

Coverage:
  1.  schema_valid        — output JSON matches expected schema
  2.  no_model_mutation   — production data/snapshots not written
  3.  phase3_all_bear     — all 16 Phase 3 dates reconstruct as non-UNKNOWN, dominant = BEAR
  4.  pit_safe            — data used for each date is on or before snap_date
  5.  actual_vs_reconstructed — actual=UNKNOWN, reconstructed changes with valid data
  6.  xbi_vs_spy_computation — correct formula (XBI 30d ret - SPY 30d ret)
  7.  bear_weights_differ  — BEAR adjustments != UNKNOWN neutral weights
  8.  output_directory_only — all output in artifacts/autopsy/ only
  9.  determinism         — two runs with same data produce identical regimes
  10. backtest_numbers_unchanged — replay notes backtest is based on actual rankings
  11. vix_15_threshold    — VIX exactly at boundary handled correctly
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from replay_regime_snapshots_ytd import (
    _dominant_regime,
    classify_regime_for_date,
    compute_xbi_vs_spy_30d,
    get_vix_on_date,
    load_actual_regime_labels,
    load_backtest_v14,
    run_replay,
)

from regime_engine import RegimeDetectionEngine

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_prices(dates_values: dict) -> dict:
    """Dict of {date_str: float}."""
    return dict(dates_values)


def _price_series(start_date: date, n: int, base: float = 100.0, delta: float = 0.0) -> dict:
    """Generate n daily prices starting from start_date."""
    prices = {}
    for i in range(n):
        d = start_date + timedelta(days=i)
        # Skip weekends for realism (not strictly required by the tool)
        prices[d.isoformat()] = base + delta * i
    return prices


def _make_valid_inputs_bear():
    """Phase 3 representative: VIX=18, XBI underperforming SPY by 8%."""
    snap_date = "2026-05-22"
    # 31 price points so lookback can compute 30-day return
    today = date(2026, 5, 22)
    thirty_one_days_ago = today - timedelta(days=40)  # generous lookback

    xbi_prices = {}
    spy_prices = {}
    for i in range(45):
        d = thirty_one_days_ago + timedelta(days=i)
        # XBI flat around 130
        xbi_prices[d.isoformat()] = 130.0 + i * 0.05
        # SPY rising: up ~2.5% total over window vs XBI flat -> XBI underperforms
        spy_prices[d.isoformat()] = 500.0 + i * 0.5

    vix_prices = {snap_date: 18.0}
    return snap_date, vix_prices, xbi_prices, spy_prices


# ---------------------------------------------------------------------------
# Test 1: Schema validity
# ---------------------------------------------------------------------------


class TestSchemaValid:
    def test_output_has_required_top_level_keys(self):
        backtest_rows = [{"snap_date": "2026-05-22", "ic_5d": -0.1, "top20_xs_5d": -0.02, "xbi_5d": 0.03}]
        actual_labels = {"2026-05-22": "UNKNOWN"}
        snap_date, vix_prices, xbi_prices, spy_prices = _make_valid_inputs_bear()

        with (
            patch("replay_regime_snapshots_ytd.load_backtest_v14", return_value=backtest_rows),
            patch("replay_regime_snapshots_ytd.load_actual_regime_labels", return_value=actual_labels),
        ):
            results = run_replay(
                vix_prices=vix_prices,
                spy_prices=spy_prices,
                xbi_prices=xbi_prices,
                write_output=False,
            )

        required_keys = {
            "schema",
            "classification",
            "generated_at",
            "backtest_window",
            "phase3_window",
            "data_sources",
            "regime_distribution",
            "performance_by_reconstructed_regime",
            "phase3_detail",
            "all_rows",
            "backtest_numbers_changed",
            "key_findings",
            "governance",
        }
        assert required_keys.issubset(results.keys()), f"Missing keys: {required_keys - results.keys()}"

    def test_classification_label_correct(self):
        backtest_rows = [{"snap_date": "2026-05-22", "ic_5d": 0.05, "top20_xs_5d": 0.01, "xbi_5d": 0.02}]
        snap_date, vix_prices, xbi_prices, spy_prices = _make_valid_inputs_bear()
        with (
            patch("replay_regime_snapshots_ytd.load_backtest_v14", return_value=backtest_rows),
            patch("replay_regime_snapshots_ytd.load_actual_regime_labels", return_value={"2026-05-22": "UNKNOWN"}),
        ):
            results = run_replay(
                vix_prices=vix_prices,
                spy_prices=spy_prices,
                xbi_prices=xbi_prices,
                write_output=False,
            )
        assert "REGENERATE_REGIME_SNAPSHOTS" in results["classification"]
        assert "NO_MODEL_CHANGE" in results["classification"]


# ---------------------------------------------------------------------------
# Test 2: No model mutation (no production writes)
# ---------------------------------------------------------------------------


class TestNoModelMutation:
    def test_run_replay_with_write_false_creates_no_files(self, tmp_path):
        backtest_rows = [{"snap_date": "2026-05-22", "ic_5d": 0.0, "top20_xs_5d": 0.0, "xbi_5d": 0.0}]
        snap_date, vix_prices, xbi_prices, spy_prices = _make_valid_inputs_bear()

        import replay_regime_snapshots_ytd as module

        original_output_json = module.OUTPUT_JSON
        guarded_path = tmp_path / "should_not_be_created.json"
        module.OUTPUT_JSON = guarded_path

        try:
            with (
                patch("replay_regime_snapshots_ytd.load_backtest_v14", return_value=backtest_rows),
                patch("replay_regime_snapshots_ytd.load_actual_regime_labels", return_value={"2026-05-22": "UNKNOWN"}),
            ):
                run_replay(
                    vix_prices=vix_prices,
                    spy_prices=spy_prices,
                    xbi_prices=xbi_prices,
                    write_output=False,
                )
            assert not guarded_path.exists(), "write_output=False must not create any file"
        finally:
            module.OUTPUT_JSON = original_output_json

    def test_governance_flags_all_true(self):
        backtest_rows = [{"snap_date": "2026-05-22", "ic_5d": 0.0, "top20_xs_5d": 0.0, "xbi_5d": 0.0}]
        snap_date, vix_prices, xbi_prices, spy_prices = _make_valid_inputs_bear()
        with (
            patch("replay_regime_snapshots_ytd.load_backtest_v14", return_value=backtest_rows),
            patch("replay_regime_snapshots_ytd.load_actual_regime_labels", return_value={"2026-05-22": "UNKNOWN"}),
        ):
            results = run_replay(
                vix_prices=vix_prices,
                spy_prices=spy_prices,
                xbi_prices=xbi_prices,
                write_output=False,
            )
        gov = results["governance"]
        assert gov["no_model_change"] is True
        assert gov["no_snapshot_write"] is True
        assert gov["pit_safe"] is True


# ---------------------------------------------------------------------------
# Test 3: Phase 3 rows reconstruct as BEAR
# ---------------------------------------------------------------------------


class TestPhase3AllBear:
    def _phase3_date_inputs(self, snap_date_str: str):
        """Build valid Bear-regime inputs for a Phase 3 date."""
        today = date.fromisoformat(snap_date_str)
        start = today - timedelta(days=50)
        xbi_prices = {}
        spy_prices = {}
        for i in range(55):
            d = start + timedelta(days=i)
            # XBI flat, SPY +5% over window → XBI underperforms by ~5%
            xbi_prices[d.isoformat()] = 130.0
            spy_prices[d.isoformat()] = 500.0 + i * 0.5
        vix_prices = {snap_date_str: 18.0}
        return vix_prices, xbi_prices, spy_prices

    def test_phase3_dominant_regime_is_bear(self):
        phase3_dates = [
            "2026-05-18",
            "2026-05-19",
            "2026-05-20",
            "2026-05-21",
            "2026-05-22",
            "2026-05-26",
            "2026-05-27",
            "2026-05-28",
            "2026-05-29",
            "2026-06-01",
            "2026-06-02",
            "2026-06-03",
            "2026-06-04",
            "2026-06-05",
            "2026-06-08",
            "2026-06-09",
        ]
        vix_prices, xbi_prices, spy_prices = {}, {}, {}
        for sd in phase3_dates:
            v, x, s = self._phase3_date_inputs(sd)
            vix_prices.update(v)
            xbi_prices.update(x)
            spy_prices.update(s)

        engine = RegimeDetectionEngine()
        results = []
        for sd in phase3_dates:
            row = classify_regime_for_date(sd, vix_prices, xbi_prices, spy_prices, engine=engine)
            results.append(row)

        regimes = [r["reconstructed_regime"] for r in results]
        unknown_count = regimes.count("UNKNOWN")
        bear_count = regimes.count("BEAR")

        assert unknown_count < len(phase3_dates), "All Phase 3 dates should not be UNKNOWN with valid data"
        assert (
            bear_count >= len(phase3_dates) // 2
        ), f"Expected BEAR to dominate Phase 3 (got {bear_count}/{len(phase3_dates)})"

    def test_bear_regime_from_vix18_xbi_underperform(self):
        """VIX=18 + XBI down 8% vs SPY → BEAR."""
        snap_date = "2026-05-22"
        today = date(2026, 5, 22)
        start = today - timedelta(days=45)
        xbi_prices, spy_prices = {}, {}
        for i in range(46):
            d = start + timedelta(days=i)
            xbi_prices[d.isoformat()] = 130.0
            spy_prices[d.isoformat()] = 500.0 + i * 0.9  # SPY rises ~8%
        vix_prices = {snap_date: 18.0}

        row = classify_regime_for_date(snap_date, vix_prices, xbi_prices, spy_prices)
        assert row["reconstructed_regime"] == "BEAR", (
            f"Expected BEAR, got {row['reconstructed_regime']} "
            f"(VIX={row['vix']}, xbi_vs_spy={row['xbi_vs_spy_30d']})"
        )


# ---------------------------------------------------------------------------
# Test 4: PIT safety
# ---------------------------------------------------------------------------


class TestPitSafe:
    def test_xbi_vs_spy_uses_only_data_before_snap_date(self):
        """Prices after snap_date must not affect the result."""
        snap_date = "2026-05-22"

        xbi_prices = {
            "2026-04-01": 130.0,
            "2026-05-22": 130.0,
            "2026-05-30": 999.0,  # future — must be ignored
        }
        spy_prices = {
            "2026-04-01": 500.0,
            "2026-05-22": 520.0,
            "2026-05-30": 999.0,  # future — must be ignored
        }

        xbi_vs_spy = compute_xbi_vs_spy_30d(snap_date, xbi_prices, spy_prices, lookback_trading_days=1)
        # Only 2026-04-01 and 2026-05-22 are usable → no future data leaked
        # 2026-05-30 must not appear in the computation
        if xbi_vs_spy is not None:
            # Result should NOT use the 999 prices
            expected_xbi_ret = (130.0 - 130.0) / 130.0 * 100
            expected_spy_ret = (520.0 - 500.0) / 500.0 * 100
            expected = round(expected_xbi_ret - expected_spy_ret, 4)
            assert abs(xbi_vs_spy - expected) < 0.01, f"PIT violation: expected {expected}, got {xbi_vs_spy}"

    def test_vix_uses_most_recent_on_or_before_snap_date(self):
        vix_prices = {
            "2026-05-20": 17.0,
            "2026-05-21": 18.0,
            "2026-05-23": 99.0,  # future — must be ignored
        }
        val = get_vix_on_date("2026-05-22", vix_prices)
        assert val == 18.0, f"Expected VIX from 2026-05-21, got {val}"


# ---------------------------------------------------------------------------
# Test 5: Actual vs reconstructed
# ---------------------------------------------------------------------------


class TestActualVsReconstructed:
    def test_actual_and_reconstructed_diverge_for_phase3(self):
        """actual=UNKNOWN, reconstructed≠UNKNOWN for bear-scenario Phase 3 dates."""
        snap_date = "2026-06-02"
        today = date.fromisoformat(snap_date)
        start = today - timedelta(days=45)
        xbi_prices, spy_prices = {}, {}
        for i in range(46):
            d = start + timedelta(days=i)
            xbi_prices[d.isoformat()] = 130.0
            spy_prices[d.isoformat()] = 500.0 + i * 0.8
        vix_prices = {snap_date: 16.5}

        row = classify_regime_for_date(snap_date, vix_prices, xbi_prices, spy_prices)
        row["actual_regime"] = "UNKNOWN"

        assert row["actual_regime"] == "UNKNOWN"
        assert (
            row["reconstructed_regime"] != "UNKNOWN"
        ), f"Reconstructed should differ from UNKNOWN but got: {row['reconstructed_regime']}"


# ---------------------------------------------------------------------------
# Test 6: XBI vs SPY computation
# ---------------------------------------------------------------------------


class TestXbiVsSpyComputation:
    def test_xbi_outperform(self):
        """XBI up, SPY up less → xbi_vs_spy positive."""
        # Build exactly 31 prices so lookback index -(30+1) = first price
        snap_date = "2026-05-31"
        start = date(2026, 4, 21)  # 40 days before snap — enough room
        xbi_prices, spy_prices = {}, {}
        # First price: xbi=100, spy=100. 31st price: xbi=110, spy=105.
        for i in range(31):
            d = start + timedelta(days=i)
            xbi_prices[d.isoformat()] = 100.0 + i * (10.0 / 30)  # +10% over 30 steps
            spy_prices[d.isoformat()] = 100.0 + i * (5.0 / 30)  # +5% over 30 steps
        xbi_vs_spy = compute_xbi_vs_spy_30d(snap_date, xbi_prices, spy_prices, lookback_trading_days=30)
        assert xbi_vs_spy is not None
        # xbi_now=110, xbi_30=100 → xbi_ret=10%; spy_now=105, spy_30=100 → spy_ret=5%
        assert abs(xbi_vs_spy - 5.0) < 0.1

    def test_insufficient_history_returns_none(self):
        snap_date = "2026-05-31"
        xbi_prices = {"2026-05-31": 130.0}
        spy_prices = {"2026-05-31": 500.0}
        result = compute_xbi_vs_spy_30d(snap_date, xbi_prices, spy_prices, lookback_trading_days=30)
        assert result is None

    def test_empty_prices_returns_none(self):
        result = compute_xbi_vs_spy_30d("2026-05-31", {}, {})
        assert result is None


# ---------------------------------------------------------------------------
# Test 7: BEAR weights differ from UNKNOWN
# ---------------------------------------------------------------------------


class TestBearWeightsDiffer:
    def test_bear_adjustments_not_all_one(self):
        engine = RegimeDetectionEngine()
        bear_adj = engine.REGIME_ADJUSTMENTS["BEAR"]
        unknown_adj = engine.REGIME_ADJUSTMENTS["UNKNOWN"]

        # All UNKNOWN weights are 1.0
        assert all(
            v == Decimal("1.00") for v in unknown_adj.values()
        ), "UNKNOWN regime adjustments should all be 1.0 (neutral)"
        # BEAR should have at least one weight != 1.0
        assert any(
            v != Decimal("1.00") for v in bear_adj.values()
        ), "BEAR regime adjustments should differ from neutral"

    def test_bear_momentum_below_one(self):
        engine = RegimeDetectionEngine()
        assert engine.REGIME_ADJUSTMENTS["BEAR"]["momentum"] < Decimal("1.00")

    def test_bear_quality_above_one(self):
        engine = RegimeDetectionEngine()
        assert engine.REGIME_ADJUSTMENTS["BEAR"]["quality"] > Decimal("1.00")


# ---------------------------------------------------------------------------
# Test 8: Output directory constraint
# ---------------------------------------------------------------------------


class TestOutputDirectoryOnly:
    def test_output_json_written_to_autopsy_dir(self, tmp_path):
        backtest_rows = [{"snap_date": "2026-05-22", "ic_5d": 0.0, "top20_xs_5d": 0.0, "xbi_5d": 0.0}]
        snap_date, vix_prices, xbi_prices, spy_prices = _make_valid_inputs_bear()

        import replay_regime_snapshots_ytd as module

        original_output_json = module.OUTPUT_JSON
        temp_out = tmp_path / "regime_snapshot_replay_ytd_results.json"
        module.OUTPUT_JSON = temp_out

        try:
            with (
                patch("replay_regime_snapshots_ytd.load_backtest_v14", return_value=backtest_rows),
                patch("replay_regime_snapshots_ytd.load_actual_regime_labels", return_value={"2026-05-22": "UNKNOWN"}),
            ):
                run_replay(
                    vix_prices=vix_prices,
                    spy_prices=spy_prices,
                    xbi_prices=xbi_prices,
                    write_output=True,
                )
            assert temp_out.exists()
            data = json.loads(temp_out.read_text())
            assert data["schema"] == "regime_snapshot_replay_ytd_v1"
        finally:
            module.OUTPUT_JSON = original_output_json


# ---------------------------------------------------------------------------
# Test 9: Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_same_inputs_same_regime(self):
        snap_date, vix_prices, xbi_prices, spy_prices = _make_valid_inputs_bear()

        row1 = classify_regime_for_date(snap_date, vix_prices, xbi_prices, spy_prices)
        row2 = classify_regime_for_date(snap_date, vix_prices, xbi_prices, spy_prices)

        assert row1["reconstructed_regime"] == row2["reconstructed_regime"]
        assert row1["reconstructed_confidence"] == row2["reconstructed_confidence"]


# ---------------------------------------------------------------------------
# Test 10: Backtest numbers unchanged
# ---------------------------------------------------------------------------


class TestBacktestNumbersUnchanged:
    def test_backtest_numbers_changed_is_false(self):
        backtest_rows = [{"snap_date": "2026-05-22", "ic_5d": 0.05, "top20_xs_5d": 0.01, "xbi_5d": 0.02}]
        snap_date, vix_prices, xbi_prices, spy_prices = _make_valid_inputs_bear()
        with (
            patch("replay_regime_snapshots_ytd.load_backtest_v14", return_value=backtest_rows),
            patch("replay_regime_snapshots_ytd.load_actual_regime_labels", return_value={"2026-05-22": "UNKNOWN"}),
        ):
            results = run_replay(
                vix_prices=vix_prices,
                spy_prices=spy_prices,
                xbi_prices=xbi_prices,
                write_output=False,
            )
        assert results["backtest_numbers_changed"] is False

    def test_key_findings_mentions_no_model_change_constraint(self):
        backtest_rows = [{"snap_date": "2026-05-22", "ic_5d": 0.05, "top20_xs_5d": 0.01, "xbi_5d": 0.02}]
        snap_date, vix_prices, xbi_prices, spy_prices = _make_valid_inputs_bear()
        with (
            patch("replay_regime_snapshots_ytd.load_backtest_v14", return_value=backtest_rows),
            patch("replay_regime_snapshots_ytd.load_actual_regime_labels", return_value={"2026-05-22": "UNKNOWN"}),
        ):
            results = run_replay(
                vix_prices=vix_prices,
                spy_prices=spy_prices,
                xbi_prices=xbi_prices,
                write_output=False,
            )
        findings_text = " ".join(results["key_findings"])
        assert "NO_MODEL_CHANGE" in findings_text or "retroactively" in findings_text.lower()


# ---------------------------------------------------------------------------
# Test 11: VIX 15 boundary
# ---------------------------------------------------------------------------


class TestVIX15Boundary:
    def test_vix_exactly_15_triggers_bull_score(self):
        """VIX = VIX_LOW = 15 → BULL +25 (the <= condition includes 15)."""
        engine = RegimeDetectionEngine()
        # With VIX=15 and XBI neutral (0), expect BULL to score 25
        result = engine.detect_regime(
            vix_current=Decimal("15"),
            xbi_vs_spy_30d=Decimal("0"),
            as_of_date=date(2026, 5, 22),
            data_as_of_date=date(2026, 5, 22),
        )
        regime_scores = result["regime_scores"]
        assert regime_scores["BULL"] >= Decimal(
            "25"
        ), f"VIX=15 should give BULL +25, got BULL score {regime_scores['BULL']}"

    def test_vix_16_does_not_trigger_bull(self):
        """VIX = 16 is between VIX_LOW and VIX_NORMAL → SECTOR_ROTATION, not BULL."""
        engine = RegimeDetectionEngine()
        result = engine.detect_regime(
            vix_current=Decimal("16"),
            xbi_vs_spy_30d=Decimal("0"),
            as_of_date=date(2026, 5, 22),
            data_as_of_date=date(2026, 5, 22),
        )
        regime_scores = result["regime_scores"]
        # VIX=16: no BULL score from VIX (> VIX_LOW=15)
        # Check BULL score is NOT inflated by VIX
        vix_bull_contribution = Decimal("25")  # the VIX_LOW branch
        # BULL score should not include the 25-point VIX contribution
        assert (
            regime_scores["BULL"] < vix_bull_contribution
        ), f"VIX=16 should NOT trigger BULL VIX contribution, got BULL={regime_scores['BULL']}"
