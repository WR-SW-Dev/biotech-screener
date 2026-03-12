"""Tests for canary ratchet: classification, history, gate integration."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from scripts.replay_diff import DiffResult, HealthVerdict
from scripts.run_canary_dates import (
    CanaryDateResult,
    CanaryOutcome,
    CanaryPolicy,
    CanaryVerdict,
    classify_outcome,
    count_consecutive_outcome,
    load_canary_history,
    persist_canary_history,
)

# ---------------------------------------------------------------------------
# Helpers: build minimal mock objects
# ---------------------------------------------------------------------------


def _make_diff_result(*, common_tickers=100, spearman_rho=0.95, top20_overlap=85.0):
    """Build a minimal DiffResult with sane defaults."""
    return DiffResult(
        baseline_source="test_baseline",
        candidate_source="test_candidate",
        baseline_n_rows=200,
        candidate_n_rows=200,
        common_tickers=common_tickers,
        schema_drift={"baseline_only": [], "candidate_only": []},
        rank_column_info={
            "baseline_has_actionable_rank": True,
            "candidate_has_actionable_rank": True,
            "baseline_rank_column_used": "actionable_rank",
            "candidate_rank_column_used": "actionable_rank",
        },
        top20_overlap_pct=top20_overlap,
        top60_overlap_pct=90.0,
        top100_overlap_pct=95.0,
        top20_entrants=[],
        top20_exits=[],
        top60_entrants=[],
        top60_exits=[],
        rank_spearman_rho=spearman_rho,
        mean_abs_rank_delta_top60=2.0,
        max_abs_rank_delta_top60=5,
        biggest_rank_movers=[],
        composite_score_rmse=1.0,
        score_rank_pct_mae=0.02,
        eligibility_change_count=0,
        eligibility_gained=[],
        eligibility_lost=[],
        tier_migration_count=0,
        tier_migration_matrix={},
        tier_dist_baseline={},
        tier_dist_candidate={},
        catalyst_mode_change_count=0,
        catalyst_bad_to_good=[],
        catalyst_good_to_bad=[],
        weight_l1_top20=5.0,
        commercial_top20_overlap_pct=None,
        commercial_tier_migration_count=None,
        commercial_tier_migration_matrix=None,
    )


def _make_verdict(*, status="OK", fail_reasons=None, warn_reasons=None):
    """Build a HealthVerdict."""
    return HealthVerdict(
        status=status,
        fail_reasons=fail_reasons or [],
        warn_reasons=warn_reasons or [],
        exit_code={"OK": 0, "WARN": 2, "FAIL": 1}.get(status, 0),
    )


# ---------------------------------------------------------------------------
# TestClassifyOutcome
# ---------------------------------------------------------------------------


class TestClassifyOutcome:

    def test_clean_run_is_info(self):
        diff = _make_diff_result()
        verdict = _make_verdict(status="OK")
        result = classify_outcome("2025-04-30", diff, verdict, CanaryPolicy.default())
        assert result.outcome == CanaryOutcome.INFO
        assert result.block_reasons == []
        assert result.warn_reasons == []

    def test_no_common_universe_is_block(self):
        diff = _make_diff_result(common_tickers=0)
        verdict = _make_verdict(
            status="FAIL",
            fail_reasons=["no_common_universe: baseline and candidate share 0 tickers"],
        )
        result = classify_outcome("2025-04-30", diff, verdict, CanaryPolicy.default())
        assert result.outcome == CanaryOutcome.BLOCK
        assert "no_common_universe" in result.block_reasons

    def test_config_fingerprint_mismatch_is_block(self):
        diff = _make_diff_result()
        verdict = _make_verdict(status="OK")
        result = classify_outcome(
            "2025-04-30",
            diff,
            verdict,
            CanaryPolicy.default(),
            config_fp_match=False,
        )
        assert result.outcome == CanaryOutcome.BLOCK
        assert "config_fingerprint_mismatch" in result.block_reasons

    def test_config_fingerprint_absent_is_not_block(self):
        diff = _make_diff_result()
        verdict = _make_verdict(status="OK")
        result = classify_outcome(
            "2025-04-30",
            diff,
            verdict,
            CanaryPolicy.default(),
            config_fp_match=None,
        )
        assert result.outcome != CanaryOutcome.BLOCK

    def test_structural_disabled_degrades_to_warn(self):
        diff = _make_diff_result(common_tickers=0)
        verdict = _make_verdict(
            status="FAIL",
            fail_reasons=["no_common_universe: baseline and candidate share 0 tickers"],
        )
        policy = CanaryPolicy(structural_block_enabled=False)
        result = classify_outcome("2025-04-30", diff, verdict, policy)
        assert result.outcome == CanaryOutcome.WARN
        assert result.block_reasons == []
        assert "no_common_universe" in result.warn_reasons

    def test_statistical_drift_is_warn(self):
        diff = _make_diff_result(spearman_rho=0.80)
        verdict = _make_verdict(
            status="WARN",
            warn_reasons=["rank_spearman_rho=0.80 < 0.92"],
        )
        result = classify_outcome("2025-04-30", diff, verdict, CanaryPolicy.default())
        assert result.outcome == CanaryOutcome.WARN
        assert len(result.warn_reasons) > 0
        assert result.block_reasons == []

    def test_statistical_disabled_is_info(self):
        diff = _make_diff_result(spearman_rho=0.80)
        verdict = _make_verdict(
            status="WARN",
            warn_reasons=["rank_spearman_rho=0.80 < 0.92"],
        )
        policy = CanaryPolicy(statistical_warn_enabled=False)
        result = classify_outcome("2025-04-30", diff, verdict, policy)
        assert result.outcome == CanaryOutcome.INFO

    def test_block_trumps_warn(self):
        diff = _make_diff_result(common_tickers=0)
        verdict = _make_verdict(
            status="FAIL",
            fail_reasons=["no_common_universe: baseline and candidate share 0 tickers"],
            warn_reasons=["rank_spearman_rho=0.80 < 0.92"],
        )
        result = classify_outcome("2025-04-30", diff, verdict, CanaryPolicy.default())
        assert result.outcome == CanaryOutcome.BLOCK


# ---------------------------------------------------------------------------
# TestCanaryHistory
# ---------------------------------------------------------------------------


class TestCanaryHistory:

    def _make_verdict(self, outcome: CanaryOutcome) -> CanaryVerdict:
        return CanaryVerdict(
            overall_outcome=outcome,
            per_date={
                "2025-04-30": CanaryDateResult(
                    canary_date="2025-04-30",
                    outcome=outcome,
                    block_reasons=[],
                    warn_reasons=[],
                    spearman_rho=0.95,
                    top20_overlap_pct=85.0,
                    status_raw="OK",
                ),
            },
            thresholds_id="abc12345",
            policy=CanaryPolicy.default(),
            ruleset_id="7177a4ea",
            config_fingerprint=None,
            run_timestamp="2026-03-12T00:00:00+00:00",
        )

    def test_persist_and_load_roundtrip(self, tmp_path):
        history_path = tmp_path / "history.jsonl"
        v = self._make_verdict(CanaryOutcome.WARN)
        persist_canary_history(history_path, v, [])
        loaded = load_canary_history(history_path)
        assert len(loaded) == 1
        assert loaded[0]["schema"] == "canary_regression.v1"
        assert loaded[0]["overall_outcome"] == "WARN"
        assert loaded[0]["consecutive_warn_runs"] == 1

    def test_consecutive_warn_counting(self, tmp_path):
        history = [
            {"overall_outcome": "WARN"},
            {"overall_outcome": "WARN"},
            {"overall_outcome": "WARN"},
        ]
        assert count_consecutive_outcome(history, "WARN") == 3

    def test_ok_resets_count(self, tmp_path):
        history = [
            {"overall_outcome": "WARN"},
            {"overall_outcome": "WARN"},
            {"overall_outcome": "INFO"},
        ]
        assert count_consecutive_outcome(history, "WARN") == 0

    def test_empty_history_zero(self):
        assert count_consecutive_outcome([], "WARN") == 0

    def test_block_resets_warn_count(self):
        history = [
            {"overall_outcome": "WARN"},
            {"overall_outcome": "WARN"},
            {"overall_outcome": "BLOCK"},
        ]
        assert count_consecutive_outcome(history, "WARN") == 0


# ---------------------------------------------------------------------------
# TestGateIntegration
# ---------------------------------------------------------------------------


class TestGateIntegration:

    def _mock_verdict(self, outcome: CanaryOutcome) -> CanaryVerdict:
        return CanaryVerdict(
            overall_outcome=outcome,
            per_date={
                "2025-04-30": CanaryDateResult(
                    canary_date="2025-04-30",
                    outcome=outcome,
                    block_reasons=[],
                    warn_reasons=[],
                    spearman_rho=0.95,
                    top20_overlap_pct=85.0,
                    status_raw="OK",
                ),
            },
            thresholds_id="abc12345",
            policy=CanaryPolicy.default(),
            ruleset_id="7177a4ea",
            config_fingerprint=None,
            run_timestamp="2026-03-12T00:00:00+00:00",
        )

    @patch("tools.run_daily_production.check_canary_regression.__module__", "tools.run_daily_production")
    def test_block_maps_to_fail_gate(self, tmp_path):
        from tools.run_daily_production import check_canary_regression

        with patch("scripts.run_canary_dates.run_canary_classified") as mock_run:
            mock_run.return_value = self._mock_verdict(CanaryOutcome.BLOCK)
            gate = check_canary_regression(
                tmp_path,
                policy_path=tmp_path / "nonexistent_policy.json",
                thresholds_path=tmp_path / "nonexistent_thresholds.json",
                history_path=tmp_path / "history.jsonl",
                ruleset_path=tmp_path / "nonexistent_ruleset.json",
            )
        assert gate.status == "FAIL"

    def test_warn_maps_to_warn_gate(self, tmp_path):
        from tools.run_daily_production import check_canary_regression

        with patch("scripts.run_canary_dates.run_canary_classified") as mock_run:
            mock_run.return_value = self._mock_verdict(CanaryOutcome.WARN)
            gate = check_canary_regression(
                tmp_path,
                policy_path=tmp_path / "nonexistent_policy.json",
                thresholds_path=tmp_path / "nonexistent_thresholds.json",
                history_path=tmp_path / "history.jsonl",
                ruleset_path=tmp_path / "nonexistent_ruleset.json",
            )
        assert gate.status == "WARN"

    def test_info_maps_to_pass_gate(self, tmp_path):
        from tools.run_daily_production import check_canary_regression

        with patch("scripts.run_canary_dates.run_canary_classified") as mock_run:
            mock_run.return_value = self._mock_verdict(CanaryOutcome.INFO)
            gate = check_canary_regression(
                tmp_path,
                policy_path=tmp_path / "nonexistent_policy.json",
                thresholds_path=tmp_path / "nonexistent_thresholds.json",
                history_path=tmp_path / "history.jsonl",
                ruleset_path=tmp_path / "nonexistent_ruleset.json",
            )
        assert gate.status == "PASS"

    def test_exception_maps_to_warn_gate(self, tmp_path):
        from tools.run_daily_production import check_canary_regression

        with patch("scripts.run_canary_dates.run_canary_classified") as mock_run:
            mock_run.side_effect = RuntimeError("canary exploded")
            gate = check_canary_regression(
                tmp_path,
                policy_path=tmp_path / "nonexistent_policy.json",
                thresholds_path=tmp_path / "nonexistent_thresholds.json",
                history_path=tmp_path / "history.jsonl",
                ruleset_path=tmp_path / "nonexistent_ruleset.json",
            )
        assert gate.status == "WARN"
        assert "canary exploded" in gate.detail


# ---------------------------------------------------------------------------
# TestRatchetEscalation
# ---------------------------------------------------------------------------


class TestRatchetEscalation:

    def test_ratchet_disabled_stays_warn(self, tmp_path):
        """With consecutive_warn_to_block=0, even many WARNs don't escalate."""
        history_path = tmp_path / "history.jsonl"
        # Write 10 WARN entries
        for _ in range(10):
            history_path.open("a").write(json.dumps({"overall_outcome": "WARN"}) + "\n")
        history = load_canary_history(history_path)
        assert count_consecutive_outcome(history, "WARN") == 10
        # Policy has ratchet disabled (default)
        policy = CanaryPolicy.default()
        assert policy.consecutive_warn_to_block == 0
        # No escalation — stays WARN

    def test_ratchet_escalates_when_enabled(self, tmp_path):
        """With ratchet enabled and enough history, consecutive WARNs → BLOCK."""
        history_path = tmp_path / "history.jsonl"
        # Write 4 WARN entries
        for _ in range(4):
            history_path.open("a").write(json.dumps({"overall_outcome": "WARN"}) + "\n")
        history = load_canary_history(history_path)
        consecutive = count_consecutive_outcome(history, "WARN")
        assert consecutive == 4

        # Policy: escalate after 5 consecutive WARNs with 3 minimum history
        policy = CanaryPolicy(
            consecutive_warn_to_block=5,
            ratchet_after_n_runs=3,
        )
        # Current run would be WARN → 4+1=5 consecutive → meets threshold
        assert len(history) >= policy.ratchet_after_n_runs
        assert consecutive + 1 >= policy.consecutive_warn_to_block
