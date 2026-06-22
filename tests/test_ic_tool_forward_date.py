"""Tests for forward-date hardening in tools/measure_final_score_ic_spec100.py.

Covers the resolver (pure) and the measurement metadata. Tooling/test only —
no ranker/model/selector/sizing/final_score behavior is exercised, and the
default (exact) forward-date behavior must remain unchanged.
"""

import sys
from pathlib import Path

import pytest

# The tool is a top-level script under tools/ (no package); import by path.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import measure_final_score_ic_spec100 as ic  # noqa: E402

# ---------------------------------------------------------------------------
# resolve_forward_date — pure resolver
# ---------------------------------------------------------------------------


class TestResolveForwardDate:
    def test_exact_available(self):
        obs, delta, fallback, reason = ic.resolve_forward_date("2026-07-08", ["2026-06-18", "2026-07-08"])
        assert obs == "2026-07-08"
        assert delta == 0
        assert fallback is False
        assert reason == "exact"

    def test_exact_missing_nearest_later_within_tolerance(self):
        obs, delta, fallback, reason = ic.resolve_forward_date(
            "2026-07-08", ["2026-07-09"], mode="nearest_later", tolerance_days=7
        )
        assert obs == "2026-07-09"
        assert delta == 1
        assert fallback is True
        assert "nearest_later" in reason

    def test_nearest_later_picks_soonest(self):
        obs, delta, _, _ = ic.resolve_forward_date(
            "2026-07-08", ["2026-07-11", "2026-07-09"], mode="nearest_later", tolerance_days=7
        )
        assert obs == "2026-07-09"
        assert delta == 1

    def test_exact_missing_none_within_tolerance(self):
        obs, delta, fallback, reason = ic.resolve_forward_date(
            "2026-07-08", ["2026-07-20"], mode="nearest_later", tolerance_days=7
        )
        assert obs is None
        assert delta is None
        assert fallback is False
        assert "no forward snapshot" in reason

    def test_explicit_forward_date_present(self):
        obs, delta, fallback, reason = ic.resolve_forward_date(
            "2026-07-08", ["2026-07-08", "2026-07-10"], explicit_forward_date="2026-07-10"
        )
        assert obs == "2026-07-10"
        assert delta == 2
        assert fallback is True
        assert reason == "explicit_forward_date"

    def test_explicit_forward_date_missing(self):
        obs, delta, fallback, reason = ic.resolve_forward_date(
            "2026-07-08", ["2026-07-08"], explicit_forward_date="2026-07-11"
        )
        assert obs is None
        assert delta is None
        assert fallback is False
        assert "no snapshot" in reason

    def test_default_mode_is_exact_no_fallback(self):
        # Default mode must NOT fall back even when a later snapshot exists.
        obs, delta, fallback, reason = ic.resolve_forward_date("2026-07-08", ["2026-07-09"])
        assert obs is None
        assert fallback is False
        assert "mode=exact" in reason

    def test_never_returns_earlier_date(self):
        # An earlier snapshot must never be substituted, even in nearest_later.
        obs, _, fallback, _ = ic.resolve_forward_date(
            "2026-07-08", ["2026-07-07"], mode="nearest_later", tolerance_days=7
        )
        assert obs is None
        assert fallback is False


# ---------------------------------------------------------------------------
# measure_final_score_ic — metadata records requested vs observed
# ---------------------------------------------------------------------------


def _snapshot(date: str, base_price: float, bump: float):
    """Synthetic snapshot: 12-ticker cohort, varied final_score and prices."""
    rows = []
    for i in range(12):
        rows.append(
            {
                "ticker": f"TK{i:02d}",
                "actionable_rank": str(i + 1),  # all <= 60 → in cohort
                "final_score": str(0.10 + 0.01 * i),
                "composite_score": str(0.20 + 0.01 * i),
                # distinct forward moves so returns have variance (non-degenerate IC)
                "close_price": str(base_price + bump * i),
            }
        )
    return {"date": date, "rows": rows}


class TestMeasurementMetadata:
    def _snapshots(self, forward_date: str):
        base = _snapshot("2026-06-18", base_price=100.0, bump=0.0)
        fwd = _snapshot(forward_date, base_price=101.0, bump=0.5)
        return base, {"2026-06-18": base, forward_date: fwd}

    def test_exact_metadata(self):
        base, snaps = self._snapshots("2026-07-08")  # base + 20 cal days
        res = ic.measure_final_score_ic(base, snaps, horizon_days=20)
        assert res["requested_forward_date"] == "2026-07-08"
        assert res["observed_forward_date"] == "2026-07-08"
        assert res["forward_date_delta_days"] == 0
        assert res["forward_date_mode"] == "exact"
        assert res["forward_fallback_used"] is False
        assert res["forward_unobservable_reason"] is None
        assert res["future_date"] == "2026-07-08"  # back-compat key
        # Happy path still computes real observations (guard must not break it).
        assert res["final_score_observations"] == 12
        assert res["final_score_ic"] == res["final_score_ic"]  # not NaN

    def test_nearest_later_metadata(self):
        # No 2026-07-08 snapshot; 2026-07-09 available within tolerance.
        base, snaps = self._snapshots("2026-07-09")
        res = ic.measure_final_score_ic(
            base,
            snaps,
            horizon_days=20,
            forward_date_mode="nearest_later",
            forward_tolerance_days=7,
        )
        assert res["requested_forward_date"] == "2026-07-08"
        assert res["observed_forward_date"] == "2026-07-09"
        assert res["forward_date_delta_days"] == 1
        assert res["forward_fallback_used"] is True
        assert res["forward_unobservable_reason"] is None

    def test_unobservable_when_exact_missing_default_mode(self):
        # Default exact mode + no 2026-07-08 snapshot → unobservable, reason set.
        base, snaps = self._snapshots("2026-07-09")
        res = ic.measure_final_score_ic(base, snaps, horizon_days=20)
        assert res["observed_forward_date"] is None
        assert res["forward_fallback_used"] is False
        assert "mode=exact" in res["forward_unobservable_reason"]
        # Must be genuinely unobservable, NOT a misleading measured 0.0000 IC.
        assert res["final_score_observations"] == 0
        assert res["final_score_ic"] != res["final_score_ic"]  # NaN
        assert res["composite_score_observations"] == 0
