"""Tests for common/review_queue.py."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from common.review_queue import assign_action, build_review_queue, compute_blind_spot_streaks, compute_queue_summary


def _row(**kwargs) -> dict:
    defaults = {
        "ticker": "TEST",
        "eligible": "1",
        "tier_any": "A",
        "composite_score": "55.0",
        "catalyst_days": "30",
        "catalyst_family": "CLINICAL",
        "market_model_disagreement": "",
        "ts_flag_type": "",
        "options_quality_composite": "",
        "has_regulatory_upcoming_180d": "0",
        "regulatory_days": "",
    }
    defaults.update(kwargs)
    return defaults


class TestAssignAction:
    def test_rule1_high_disagree_near_catalyst_fresh(self):
        r = _row(market_model_disagreement="high", catalyst_days="60")
        action, reason = assign_action(r, options_data_fresh=True)
        assert action == "no_add_until_review"
        assert "near-term" in reason.lower()

    def test_rule1_suppressed_when_stale(self):
        """High disagreement + near catalyst but stale data → not no_add."""
        r = _row(market_model_disagreement="high", catalyst_days="60")
        result = assign_action(r, options_data_fresh=False)
        # Should fall through to rule 3 (size_haircut) since cat_days <= 90
        # but rule 3 requires cat_days > 90, so it should be monitor_only
        assert result is not None
        action, _ = result
        assert action != "no_add_until_review"

    def test_rule2_persistent_blind_spot(self):
        r = _row(ts_flag_type="BLIND_SPOT")
        action, reason = assign_action(r, options_data_fresh=True, blind_spot_days=5)
        assert action == "no_add_until_review"
        assert "persistent" in reason.lower()

    def test_rule3_high_disagree_far_catalyst(self):
        r = _row(market_model_disagreement="high", catalyst_days="120")
        action, _ = assign_action(r, options_data_fresh=True)
        assert action == "size_haircut"

    def test_rule4_market_sees_sooner_ranked(self):
        r = _row(ts_flag_type="MARKET_SEES_SOONER", tier_any="A", composite_score="65.0")
        action, _ = assign_action(r, options_data_fresh=True)
        assert action == "size_haircut"

    def test_rule4_not_ranked_enough(self):
        """MARKET_SEES_SOONER but score < 60 → doesn't match rule 4."""
        r = _row(ts_flag_type="MARKET_SEES_SOONER", tier_any="A", composite_score="50.0")
        result = assign_action(r, options_data_fresh=True)
        assert result is not None
        action, _ = result
        assert action != "size_haircut"

    def test_rule5_early_blind_spot(self):
        r = _row(ts_flag_type="BLIND_SPOT")
        action, _ = assign_action(r, options_data_fresh=True, blind_spot_days=1)
        assert action == "manual_review_required"

    def test_rule6_not_pricing_near_ranked(self):
        r = _row(ts_flag_type="MARKET_NOT_PRICING_EVENT", catalyst_days="20", tier_any="B")
        action, _ = assign_action(r, options_data_fresh=True)
        assert action == "manual_review_required"

    def test_rule7_step10_regulatory(self):
        r = _row(
            has_regulatory_upcoming_180d="1",
            regulatory_days="120",
            options_quality_composite="0.5",
            tier_any="B",
        )
        action, reason = assign_action(r, options_data_fresh=True)
        assert action == "manual_review_required"
        assert "Step-10" in reason

    def test_rule8_medium_disagree_monitor(self):
        r = _row(market_model_disagreement="medium")
        action, _ = assign_action(r, options_data_fresh=True)
        assert action == "monitor_only"

    def test_no_flags_no_action(self):
        r = _row()
        result = assign_action(r, options_data_fresh=True)
        assert result is None

    def test_priority_order(self):
        """Rule 1 beats rule 3 when both could match."""
        r = _row(market_model_disagreement="high", catalyst_days="60")
        action, _ = assign_action(r, options_data_fresh=True)
        assert action == "no_add_until_review"


class TestBuildReviewQueue:
    def test_sorted_by_severity(self):
        rows = [
            _row(ticker="MONITOR", market_model_disagreement="medium"),
            _row(ticker="NOADD", market_model_disagreement="high", catalyst_days="30"),
            _row(ticker="HAIRCUT", market_model_disagreement="high", catalyst_days="120"),
        ]
        queue = build_review_queue(rows, options_data_fresh=True)
        actions = [r["action"] for r in queue]
        assert actions[0] == "no_add_until_review"
        assert actions[1] == "size_haircut"
        assert actions[2] == "monitor_only"

    def test_empty_universe(self):
        queue = build_review_queue([], options_data_fresh=True)
        assert queue == []

    def test_no_flags_empty_queue(self):
        rows = [_row(ticker="CLEAN")]
        queue = build_review_queue(rows, options_data_fresh=True)
        assert queue == []


class TestComputeQueueSummary:
    def test_counts(self):
        queue = [
            {"action": "no_add_until_review"},
            {"action": "no_add_until_review"},
            {"action": "size_haircut"},
            {"action": "monitor_only"},
        ]
        summary = compute_queue_summary(queue)
        assert summary["no_add_until_review"] == 2
        assert summary["size_haircut"] == 1
        assert summary["manual_review_required"] == 0
        assert summary["monitor_only"] == 1
        assert summary["total_flagged"] == 4


class TestBlindSpotStreaks:
    def test_new_blind_spot(self, tmp_path):
        rows = [_row(ticker="PRLD", ts_flag_type="BLIND_SPOT")]
        streaks = compute_blind_spot_streaks(rows, None, tmp_path)
        assert streaks["PRLD"] == 1

    def test_increment_streak(self, tmp_path):
        # Seed prior state
        (tmp_path / "blind_spot_streak.json").write_text(json.dumps({"PRLD": 2}))
        # Current run has BLIND_SPOT, prior snapshot also had it
        rows = [_row(ticker="PRLD", ts_flag_type="BLIND_SPOT")]
        prev_path = tmp_path / "prev_rankings.csv"
        with open(prev_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["ticker", "ts_flag_type"])
            w.writeheader()
            w.writerow({"ticker": "PRLD", "ts_flag_type": "BLIND_SPOT"})
        streaks = compute_blind_spot_streaks(rows, prev_path, tmp_path)
        assert streaks["PRLD"] == 3

    def test_reset_on_clear(self, tmp_path):
        (tmp_path / "blind_spot_streak.json").write_text(json.dumps({"PRLD": 5}))
        rows = [_row(ticker="PRLD", ts_flag_type="")]  # no longer BLIND_SPOT
        streaks = compute_blind_spot_streaks(rows, None, tmp_path)
        assert "PRLD" not in streaks
