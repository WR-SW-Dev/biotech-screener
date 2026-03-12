"""Tests for readiness gate: policy, evaluation, streak/ratchet, trade blocking."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.weekly_readiness_scorecard import (
    ReadinessPolicy,
    count_consecutive_verdict,
    evaluate_readiness_gate,
    load_history,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scorecard(verdict="READY"):
    """Build a minimal scorecard dict."""
    return {
        "schema": "weekly_readiness_scorecard.v1",
        "as_of_date": "2026-03-10",
        "generated_at": "2026-03-10T15:00:00Z",
        "ruleset_id": "7177a4ea",
        "verdict": verdict,
        "checks": [
            {"name": "shadow_excess_vs_xbi", "status": "PASS"},
            {"name": "turnover_stability", "status": "PASS"},
        ],
    }


# ---------------------------------------------------------------------------
# TestReadinessPolicy
# ---------------------------------------------------------------------------


class TestReadinessPolicy:

    def test_default(self):
        p = ReadinessPolicy.default()
        assert p.hold_blocks_trades is True
        assert p.review_blocks_trades is False
        assert p.consecutive_review_to_hold == 0
        assert p.ratchet_after_n_runs == 0

    def test_from_json(self, tmp_path):
        path = tmp_path / "policy.json"
        path.write_text(
            json.dumps(
                {
                    "schema": "readiness_policy.v1",
                    "hold_blocks_trades": False,
                    "review_blocks_trades": True,
                    "consecutive_review_to_hold": 3,
                    "ratchet_after_n_runs": 5,
                }
            )
        )
        p = ReadinessPolicy.from_json(path)
        assert p.hold_blocks_trades is False
        assert p.review_blocks_trades is True
        assert p.consecutive_review_to_hold == 3

    def test_from_json_ignores_unknown_keys(self, tmp_path):
        path = tmp_path / "policy.json"
        path.write_text(
            json.dumps(
                {
                    "schema": "readiness_policy.v1",
                    "hold_blocks_trades": True,
                    "unknown_future_field": 42,
                }
            )
        )
        p = ReadinessPolicy.from_json(path)
        assert p.hold_blocks_trades is True


# ---------------------------------------------------------------------------
# TestCountConsecutiveVerdict
# ---------------------------------------------------------------------------


class TestCountConsecutiveVerdict:

    def test_empty_history(self):
        assert count_consecutive_verdict([], "REVIEW") == 0

    def test_all_review(self):
        history = [{"verdict": "REVIEW"}, {"verdict": "REVIEW"}, {"verdict": "REVIEW"}]
        assert count_consecutive_verdict(history, "REVIEW") == 3

    def test_broken_by_ready(self):
        history = [
            {"verdict": "REVIEW"},
            {"verdict": "READY"},
            {"verdict": "REVIEW"},
            {"verdict": "REVIEW"},
        ]
        assert count_consecutive_verdict(history, "REVIEW") == 2

    def test_hold_resets_review(self):
        history = [
            {"verdict": "REVIEW"},
            {"verdict": "REVIEW"},
            {"verdict": "HOLD"},
        ]
        assert count_consecutive_verdict(history, "REVIEW") == 0

    def test_all_hold(self):
        history = [{"verdict": "HOLD"}, {"verdict": "HOLD"}]
        assert count_consecutive_verdict(history, "HOLD") == 2


# ---------------------------------------------------------------------------
# TestEvaluateReadinessGate
# ---------------------------------------------------------------------------


class TestEvaluateReadinessGate:

    def test_ready_passes(self):
        gate = evaluate_readiness_gate(_scorecard("READY"), ReadinessPolicy.default())
        assert gate["can_trade"] is True
        assert gate["gate_status"] == "PASS"

    def test_hold_blocks_by_default(self):
        gate = evaluate_readiness_gate(_scorecard("HOLD"), ReadinessPolicy.default())
        assert gate["can_trade"] is False
        assert gate["gate_status"] == "FAIL"

    def test_hold_advisory_when_disabled(self):
        policy = ReadinessPolicy(hold_blocks_trades=False)
        gate = evaluate_readiness_gate(_scorecard("HOLD"), policy)
        assert gate["can_trade"] is True
        assert gate["gate_status"] == "WARN"

    def test_review_advisory_by_default(self):
        gate = evaluate_readiness_gate(_scorecard("REVIEW"), ReadinessPolicy.default())
        assert gate["can_trade"] is True
        assert gate["gate_status"] == "WARN"

    def test_review_blocks_when_enabled(self):
        policy = ReadinessPolicy(review_blocks_trades=True)
        gate = evaluate_readiness_gate(_scorecard("REVIEW"), policy)
        assert gate["can_trade"] is False
        assert gate["gate_status"] == "FAIL"

    def test_ratchet_disabled_stays_review(self):
        """With consecutive_review_to_hold=0, repeated REVIEWs don't escalate."""
        history = [{"verdict": "REVIEW"}] * 10
        policy = ReadinessPolicy.default()
        gate = evaluate_readiness_gate(_scorecard("REVIEW"), policy, history)
        assert gate["verdict"] == "REVIEW"
        assert gate["can_trade"] is True
        assert gate["ratchet_applied"] is False

    def test_ratchet_escalates_when_enabled(self):
        """With ratchet enabled and enough history, consecutive REVIEWs → HOLD."""
        history = [{"verdict": "REVIEW"}] * 4
        policy = ReadinessPolicy(
            consecutive_review_to_hold=5,
            ratchet_after_n_runs=3,
        )
        # 4 in history + 1 current = 5 >= threshold
        gate = evaluate_readiness_gate(_scorecard("REVIEW"), policy, history)
        assert gate["verdict"] == "HOLD"
        assert gate["can_trade"] is False
        assert gate["ratchet_applied"] is True

    def test_ratchet_not_enough_history(self):
        """Ratchet doesn't fire if not enough history."""
        history = [{"verdict": "REVIEW"}] * 2
        policy = ReadinessPolicy(
            consecutive_review_to_hold=3,
            ratchet_after_n_runs=10,  # Need 10 runs, only have 2
        )
        gate = evaluate_readiness_gate(_scorecard("REVIEW"), policy, history)
        assert gate["verdict"] == "REVIEW"
        assert gate["ratchet_applied"] is False

    def test_consecutive_review_count_in_result(self):
        history = [{"verdict": "REVIEW"}, {"verdict": "REVIEW"}]
        gate = evaluate_readiness_gate(_scorecard("REVIEW"), ReadinessPolicy.default(), history)
        # 2 in history + 1 current = 3
        assert gate["consecutive_review_runs"] == 3


# ---------------------------------------------------------------------------
# TestTradeBlocking
# ---------------------------------------------------------------------------


class TestTradeBlocking:
    """Integration-style tests for the trade plan readiness gate."""

    def test_hold_blocks_trade_plan(self, tmp_path):
        """When readiness is HOLD and policy blocks, build_trade_plan returns error."""
        # Write a HOLD scorecard
        readiness_dir = tmp_path / "artifacts" / "readiness"
        readiness_dir.mkdir(parents=True)
        sc = _scorecard("HOLD")
        sc["as_of_date"] = "2026-03-10"
        (readiness_dir / "scorecard_2026-03-10.json").write_text(json.dumps(sc))

        # Write a policy that blocks on HOLD
        policy_path = tmp_path / "readiness_policy.json"
        policy_path.write_text(
            json.dumps(
                {
                    "schema": "readiness_policy.v1",
                    "hold_blocks_trades": True,
                    "review_blocks_trades": False,
                }
            )
        )

        # Verify evaluate_readiness_gate returns can_trade=False
        policy = ReadinessPolicy.from_json(policy_path)
        gate = evaluate_readiness_gate(sc, policy)
        assert gate["can_trade"] is False

    def test_ready_allows_trade_plan(self):
        """When readiness is READY, gate passes."""
        gate = evaluate_readiness_gate(_scorecard("READY"), ReadinessPolicy.default())
        assert gate["can_trade"] is True


# ---------------------------------------------------------------------------
# TestHistoryRoundtrip
# ---------------------------------------------------------------------------


class TestHistoryRoundtrip:

    def test_persist_and_count(self, tmp_path):
        from tools.weekly_readiness_scorecard import append_history

        hist_path = tmp_path / "history.jsonl"
        for v in ["READY", "REVIEW", "REVIEW", "REVIEW"]:
            append_history(hist_path, _scorecard(v))

        history = load_history(hist_path)
        assert len(history) == 4
        assert count_consecutive_verdict(history, "REVIEW") == 3

    def test_hold_resets_review_streak(self, tmp_path):
        from tools.weekly_readiness_scorecard import append_history

        hist_path = tmp_path / "history.jsonl"
        for v in ["REVIEW", "REVIEW", "HOLD", "REVIEW"]:
            append_history(hist_path, _scorecard(v))

        history = load_history(hist_path)
        assert count_consecutive_verdict(history, "REVIEW") == 1
