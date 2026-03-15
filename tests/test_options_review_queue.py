"""Tests for common/options_review_queue.py."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from common.options_review_queue import build_options_review_queue, compute_review_priority, derive_review_reasons


def _row(**kwargs):
    defaults = {
        "ticker": "TEST",
        "catalyst_event_type": "",
        "catalyst_source": "",
        "cheap_vol_score": "",
        "market_model_disagreement": "",
        "ts_flag": "",
        "ts_flag_type": "",
        "opt_rr_25d": "",
        "catalyst_days": "60",
    }
    defaults.update(kwargs)
    return defaults


def _hard_row(**kwargs):
    """Row with hard catalyst defaults (SEC 8-K data readout)."""
    return _row(
        catalyst_event_type="DATA_READOUT",
        catalyst_source="SEC_8K_FILING",
        **kwargs,
    )


class TestDeriveReviewReasons:
    def test_cheap_straddle(self):
        r = _row(cheap_vol_score="1.5")
        reasons = derive_review_reasons(r)
        assert "cheap_straddle" in reasons

    def test_rich_straddle(self):
        r = _row(cheap_vol_score="0.5")
        reasons = derive_review_reasons(r)
        assert "rich_straddle" in reasons

    def test_high_disagreement(self):
        r = _row(market_model_disagreement="high")
        reasons = derive_review_reasons(r)
        assert "high_disagreement" in reasons

    def test_term_structure_flag(self):
        r = _row(ts_flag="1", ts_flag_type="BLIND_SPOT")
        reasons = derive_review_reasons(r)
        assert any("term_structure" in rr for rr in reasons)

    def test_extreme_skew(self):
        r = _row(opt_rr_25d="0.25")
        reasons = derive_review_reasons(r)
        assert "extreme_skew" in reasons

    def test_hard_catalyst_detected(self):
        r = _row(catalyst_event_type="DATA_READOUT", catalyst_source="SEC_8K_FILING")
        reasons = derive_review_reasons(r)
        assert "hard_catalyst" in reasons

    def test_no_triggers_empty(self):
        r = _row()
        reasons = derive_review_reasons(r)
        assert reasons == []

    def test_multiple_triggers(self):
        r = _row(
            market_model_disagreement="high",
            ts_flag="1",
            ts_flag_type="MARKET_SEES_SOONER",
            opt_rr_25d="-0.30",
        )
        reasons = derive_review_reasons(r)
        assert len(reasons) >= 3


class TestComputeReviewPriority:
    def test_max_priority(self):
        reasons = ["high_disagreement", "term_structure_blind_spot", "hard_catalyst", "cheap_straddle", "extreme_skew"]
        r = _row(catalyst_days="30")
        score = compute_review_priority(r, reasons)
        assert score >= 10

    def test_single_trigger(self):
        r = _row(catalyst_days="200")
        score = compute_review_priority(r, ["extreme_skew"])
        assert score == 1

    def test_near_catalyst_bonus(self):
        r_near = _row(catalyst_days="30")
        r_far = _row(catalyst_days="200")
        s_near = compute_review_priority(r_near, ["high_disagreement"])
        s_far = compute_review_priority(r_far, ["high_disagreement"])
        assert s_near > s_far


class TestBuildOptionsReviewQueue:
    def test_hard_only_default_filters_soft(self):
        """Default hard_only=True skips soft/PCD rows."""
        rows = [
            _row(ticker="SOFT_CHEAP", cheap_vol_score="1.5", catalyst_source="CTGOV_CALENDAR"),
            _hard_row(ticker="HARD_CHEAP", cheap_vol_score="1.5"),
        ]
        queue = build_options_review_queue(rows)
        assert queue["hard_only"] is True
        assert queue["summary"]["n_total"] == 1
        assert queue["summary"]["n_soft_skipped"] == 1
        assert queue["rows"][0]["ticker"] == "HARD_CHEAP"

    def test_hard_only_false_includes_all(self):
        """hard_only=False restores old behavior."""
        rows = [
            _row(ticker="SOFT_CHEAP", cheap_vol_score="1.5"),
            _hard_row(ticker="HARD_CHEAP", cheap_vol_score="1.5"),
        ]
        queue = build_options_review_queue(rows, hard_only=False)
        assert queue["hard_only"] is False
        assert queue["summary"]["n_total"] == 2
        assert queue["summary"]["n_soft_skipped"] == 0

    def test_filters_no_trigger(self):
        rows = [_hard_row(ticker="CLEAN")]
        queue = build_options_review_queue(rows)
        # hard_catalyst is itself a reason, so a hard row with no other triggers still queues
        assert queue["summary"]["n_total"] == 1

    def test_includes_triggered_hard_rows(self):
        rows = [
            _hard_row(ticker="CHEAP", cheap_vol_score="1.5"),
            _hard_row(ticker="DISAGREE", market_model_disagreement="high"),
            _hard_row(ticker="CLEAN"),
        ]
        queue = build_options_review_queue(rows)
        assert queue["summary"]["n_total"] == 3
        tickers = [r["ticker"] for r in queue["rows"]]
        assert "CHEAP" in tickers
        assert "DISAGREE" in tickers

    def test_sorted_by_priority(self):
        rows = [
            _hard_row(ticker="LOW", cheap_vol_score="1.4", catalyst_days="200"),
            _hard_row(
                ticker="HIGH",
                market_model_disagreement="high",
                ts_flag="1",
                ts_flag_type="BLIND_SPOT",
                catalyst_days="30",
            ),
        ]
        queue = build_options_review_queue(rows)
        assert queue["rows"][0]["ticker"] == "HIGH"

    def test_summary_counts(self):
        rows = [
            _hard_row(ticker="A", market_model_disagreement="high"),
            _hard_row(ticker="B", ts_flag="1", ts_flag_type="BLIND_SPOT"),
            _hard_row(ticker="C", opt_rr_25d="0.20"),
        ]
        queue = build_options_review_queue(rows)
        s = queue["summary"]
        assert s["n_high_disagreement"] == 1
        assert s["n_term_structure_flag"] == 1
        assert s["n_extreme_skew"] == 1
        assert s["n_hard_catalyst"] == 3

    def test_empty_input(self):
        queue = build_options_review_queue([])
        assert queue["summary"]["n_total"] == 0
        assert queue["rows"] == []

    def test_schema_version_v3(self):
        queue = build_options_review_queue([])
        assert queue["schema_version"] == "options_review_queue.v3"

    def test_surface_boost_cap_at_3(self):
        """Surface overlay capped at +3 even when both high move + strong ramp."""
        row = _hard_row(
            ticker="CAPPED",
            cheap_vol_score="1.5",
            surface_move_extreme="high",  # +2
            atm_iv_change_5d="0.15",  # +2 → total would be 4, capped to 3
        )
        reasons = derive_review_reasons(row)
        score = compute_review_priority(row, reasons)
        # Base: hard_catalyst=2, cheap_straddle=2, within_90d=1, surface=3(capped)
        assert score == 2 + 2 + 1 + 3  # 8

    def test_non_hard_gets_no_surface_boost(self):
        row = _row(
            ticker="SOFT",
            cheap_vol_score="1.5",
        )
        row["surface_move_extreme"] = "high"
        row["atm_iv_change_5d"] = "0.15"
        queue = build_options_review_queue([row], hard_only=False)
        if queue["rows"]:
            reasons = queue["rows"][0].get("review_reasons", "")
            assert "surface_move_high" not in reasons
