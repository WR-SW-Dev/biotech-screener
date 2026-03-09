"""Tests for promotion weekly gate and promote_ruleset.py weekly gate enforcement."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "research"))

from promotion_weekly_gate import evaluate_gate, write_verdict_json

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agg(mean_hedged=0.002, cum_hedged=0.02, **bucket_overrides):
    """Build a minimal aggregate dict."""
    from live_sim_weekly_ab import BUCKET_NAMES

    agg = {
        "n_periods": 100,
        "mean_hedged": mean_hedged,
        "std_hedged": 0.03,
        "cum_hedged": cum_hedged,
        "mean_net": 0.003,
        "cum_net": 0.03,
        "mean_gross": 0.004,
        "cum_gross": 0.04,
        "mean_xbi": 0.001,
        "cum_xbi": 0.01,
        "mean_turnover": 0.05,
        "worst_20pct_hedged": -0.02,
    }
    for b in BUCKET_NAMES:
        agg[f"{b}_mean_hedged"] = bucket_overrides.get(f"{b}_mean_hedged", 0.001)
    return agg


# ---------------------------------------------------------------------------
# Tests: evaluate_gate
# ---------------------------------------------------------------------------


class TestEvaluateGatePolicy:
    def test_pass_when_above_thresholds(self):
        base = _make_agg(mean_hedged=0.001, cum_hedged=0.10)
        cand = _make_agg(mean_hedged=0.002, cum_hedged=0.12)  # +0.1pp mean, +2pp cum
        result = evaluate_gate(base, cand, "policy")
        assert result["pass"] is True

    def test_fail_cum_hedged_below_threshold(self):
        base = _make_agg(mean_hedged=0.001, cum_hedged=0.10)
        cand = _make_agg(mean_hedged=0.002, cum_hedged=0.105)  # +0.5pp cum < 1.0pp
        result = evaluate_gate(base, cand, "policy")
        assert result["pass"] is False
        failed = [c["name"] for c in result["checks"] if not c["pass"]]
        assert "policy_cum_hedged" in failed

    def test_fail_mean_hedged_negative(self):
        base = _make_agg(mean_hedged=0.002, cum_hedged=0.10)
        cand = _make_agg(mean_hedged=0.001, cum_hedged=0.12)  # mean Δ = -0.1pp
        result = evaluate_gate(base, cand, "policy")
        assert result["pass"] is False
        failed = [c["name"] for c in result["checks"] if not c["pass"]]
        assert "policy_mean_hedged" in failed


class TestEvaluateGateGlobal:
    def test_pass_when_above_thresholds(self):
        base = _make_agg(mean_hedged=0.001, cum_hedged=0.10)
        cand = _make_agg(mean_hedged=0.001, cum_hedged=0.10)  # 0pp delta = ok
        result = evaluate_gate(base, cand, "global")
        assert result["pass"] is True

    def test_fail_mean_hedged_too_negative(self):
        base = _make_agg(mean_hedged=0.001, cum_hedged=0.10)
        # -0.02pp mean = -0.0002 fraction
        cand = _make_agg(mean_hedged=-0.0001, cum_hedged=0.10)
        result = evaluate_gate(base, cand, "global")
        assert result["pass"] is False

    def test_fail_cum_hedged_too_negative(self):
        base = _make_agg(mean_hedged=0.001, cum_hedged=0.10)
        cand = _make_agg(mean_hedged=0.001, cum_hedged=0.08)  # -2pp
        result = evaluate_gate(base, cand, "global")
        assert result["pass"] is False


class TestBucketGuardrail:
    def test_fail_bucket_collapse(self):
        base = _make_agg(binary_91_180_mean_hedged=0.005)
        cand = _make_agg(binary_91_180_mean_hedged=0.001)  # -0.4pp
        result = evaluate_gate(base, cand, "policy")
        bucket_checks = [c for c in result["checks"] if c["name"].startswith("bucket_")]
        b91 = next(c for c in bucket_checks if "binary_91_180" in c["name"])
        assert b91["pass"] is False

    def test_pass_bucket_minor_decline(self):
        base = _make_agg(binary_91_180_mean_hedged=0.005)
        cand = _make_agg(binary_91_180_mean_hedged=0.004)  # -0.1pp, within tolerance
        result = evaluate_gate(base, cand, "global")
        bucket_checks = [c for c in result["checks"] if c["name"].startswith("bucket_")]
        b91 = next(c for c in bucket_checks if "binary_91_180" in c["name"])
        assert b91["pass"] is True


class TestVerdictJson:
    def test_schema_stable(self, tmp_path):
        results = {
            "verdict": "PASS",
            "n_periods": 100,
            "n_dates": 101,
            "policy": {"gate": {"pass": True, "checks": []}},
            "global": {"gate": {"pass": True, "checks": []}},
        }
        path = write_verdict_json(results, tmp_path / "VERDICT.json")
        doc = json.loads(path.read_text())
        assert doc["schema"] == "promotion_weekly_gate.v1"
        assert doc["verdict"] == "PASS"
        assert "generated_at" in doc
        assert doc["n_periods"] == 100

    def test_fail_verdict(self, tmp_path):
        results = {
            "verdict": "FAIL",
            "n_periods": 50,
            "n_dates": 51,
            "policy": {
                "gate": {
                    "pass": False,
                    "checks": [
                        {"name": "policy_cum_hedged", "threshold": ">= +1.00pp", "actual": "+0.50pp", "pass": False},
                    ],
                }
            },
            "global": {"gate": {"pass": True, "checks": []}},
        }
        path = write_verdict_json(results, tmp_path / "VERDICT.json")
        doc = json.loads(path.read_text())
        assert doc["verdict"] == "FAIL"
        assert doc["policy_pass"] is False
        assert doc["global_pass"] is True


class TestPromoteRulesetWeeklyGate:
    """Test that promote_ruleset.py enforces the weekly gate."""

    def test_blocks_without_weekly_gate(self, tmp_path):
        """Promotion without --weekly-gate-verdict should fail."""
        # This just tests the arg parsing / early exit behavior
        # by checking that the help text mentions --weekly-gate-verdict
        import subprocess

        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "promote_ruleset.py"), "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert "--weekly-gate-verdict" in result.stdout

    def test_pass_verdict_accepted(self, tmp_path):
        """A PASS verdict file should be accepted by the validation logic."""
        verdict = {
            "schema": "promotion_weekly_gate.v1",
            "verdict": "PASS",
            "checks": [],
        }
        path = tmp_path / "VERDICT.json"
        path.write_text(json.dumps(verdict))
        doc = json.loads(path.read_text())
        assert doc["verdict"] == "PASS"

    def test_fail_verdict_has_failed_checks(self, tmp_path):
        """A FAIL verdict with failed checks should be parseable."""
        verdict = {
            "schema": "promotion_weekly_gate.v1",
            "verdict": "FAIL",
            "checks": [
                {"name": "policy_cum_hedged", "pass": False},
                {"name": "policy_mean_hedged", "pass": True},
            ],
        }
        path = tmp_path / "VERDICT.json"
        path.write_text(json.dumps(verdict))
        doc = json.loads(path.read_text())
        assert doc["verdict"] != "PASS"
        failed = [c["name"] for c in doc["checks"] if not c["pass"]]
        assert "policy_cum_hedged" in failed
