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
    def test_filters_no_trigger(self):
        rows = [_row(ticker="CLEAN")]
        queue = build_options_review_queue(rows)
        assert queue["summary"]["n_total"] == 0

    def test_includes_triggered(self):
        rows = [
            _row(ticker="CHEAP", cheap_vol_score="1.5"),
            _row(ticker="DISAGREE", market_model_disagreement="high"),
            _row(ticker="CLEAN"),
        ]
        queue = build_options_review_queue(rows)
        assert queue["summary"]["n_total"] == 2
        tickers = [r["ticker"] for r in queue["rows"]]
        assert "CHEAP" in tickers
        assert "DISAGREE" in tickers
        assert "CLEAN" not in tickers

    def test_sorted_by_priority(self):
        rows = [
            _row(ticker="LOW", cheap_vol_score="1.4", catalyst_days="200"),
            _row(
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
            _row(ticker="A", market_model_disagreement="high"),
            _row(ticker="B", ts_flag="1", ts_flag_type="BLIND_SPOT"),
            _row(ticker="C", opt_rr_25d="0.20"),
        ]
        queue = build_options_review_queue(rows)
        s = queue["summary"]
        assert s["n_high_disagreement"] == 1
        assert s["n_term_structure_flag"] == 1
        assert s["n_extreme_skew"] == 1

    def test_empty_input(self):
        queue = build_options_review_queue([])
        assert queue["summary"]["n_total"] == 0
        assert queue["rows"] == []
