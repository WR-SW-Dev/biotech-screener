"""Tests for scripts/research/eval_crowding_penalty.py."""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "research"))

from eval_crowding_penalty import _z_score, compute_crowding_z, compute_raw_ic, evaluate_decision_rule


class TestZScore:
    def test_basic(self):
        result = _z_score([1.0, 2.0, 3.0])
        assert len(result) == 3
        assert abs(result[1]) < 1e-10

    def test_with_nan(self):
        result = _z_score([1.0, float("nan"), 3.0])
        assert math.isnan(result[1])
        assert not math.isnan(result[0])


class TestComputeCrowdingZ:
    def test_basic(self):
        rows = [
            {"pre_event_volume_mean": 100.0, "pre_event_volume_surge": 2.0},
            {"pre_event_volume_mean": 200.0, "pre_event_volume_surge": 5.0},
            {"pre_event_volume_mean": 50.0, "pre_event_volume_surge": 1.0},
        ]
        compute_crowding_z(rows)
        # Highest volume + highest surge → highest crowding_z
        assert rows[1]["crowding_z"] > rows[0]["crowding_z"]
        assert rows[0]["crowding_z"] > rows[2]["crowding_z"]

    def test_labels(self):
        rows = [
            {"pre_event_volume_mean": 1000.0, "pre_event_volume_surge": 10.0},
            {"pre_event_volume_mean": 100.0, "pre_event_volume_surge": 2.0},
            {"pre_event_volume_mean": 10.0, "pre_event_volume_surge": 0.5},
        ]
        compute_crowding_z(rows)
        # First should be "high" with very large z
        assert rows[0]["crowding_label"] == "high"
        assert rows[2]["crowding_label"] == "low"

    def test_missing_data(self):
        rows = [
            {"pre_event_volume_mean": float("nan"), "pre_event_volume_surge": float("nan")},
            {"pre_event_volume_mean": 100.0, "pre_event_volume_surge": 2.0},
        ]
        compute_crowding_z(rows)
        assert math.isnan(rows[0]["crowding_z"])
        assert rows[0]["crowding_label"] == ""


class TestComputeRawIc:
    def test_sufficient(self):
        dataset = [{"crowding_z": float(i), "fwd_ret_5d": float(i) * 0.01} for i in range(25)]
        result = compute_raw_ic(dataset, "crowding_z", "fwd_ret_5d", min_obs=20)
        assert result["status"] == "ok"
        assert result["n"] == 25

    def test_insufficient(self):
        dataset = [{"crowding_z": float(i), "fwd_ret_5d": float(i) * 0.01} for i in range(5)]
        result = compute_raw_ic(dataset, "crowding_z", "fwd_ret_5d", min_obs=20)
        assert result["status"] == "insufficient_sample"


class TestDecisionRule:
    def test_negative_alpha(self):
        tests = {
            "raw": {"ic_crowding_z_vs_fwd_ret_5d": {"status": "ok", "ic": -0.15, "n": 100}},
            "incremental": {
                "incr_crowding_z_ctrl_composite_vs_fwd_ret_5d": {
                    "status": "ok",
                    "raw_ic": -0.15,
                    "incremental_ic": -0.12,
                    "n": 100,
                }
            },
            "double_sort": {},
        }
        result = evaluate_decision_rule(tests, [5])
        assert result["classification"] == "negative_alpha_candidate"

    def test_not_incremental(self):
        tests = {
            "raw": {"ic_crowding_z_vs_fwd_ret_5d": {"status": "ok", "ic": -0.10, "n": 100}},
            "incremental": {
                "incr_crowding_z_ctrl_composite_vs_fwd_ret_5d": {
                    "status": "ok",
                    "raw_ic": -0.10,
                    "incremental_ic": -0.02,
                    "n": 100,
                }
            },
            "double_sort": {},
        }
        result = evaluate_decision_rule(tests, [5])
        assert result["classification"] == "signal_present_but_not_incremental"

    def test_abandon(self):
        tests = {
            "raw": {"ic_crowding_z_vs_fwd_ret_5d": {"status": "ok", "ic": -0.02, "n": 100}},
            "incremental": {
                "incr_crowding_z_ctrl_composite_vs_fwd_ret_5d": {
                    "status": "ok",
                    "raw_ic": -0.02,
                    "incremental_ic": -0.01,
                    "n": 100,
                }
            },
            "double_sort": {},
        }
        result = evaluate_decision_rule(tests, [5])
        assert result["classification"] == "abandon"

    def test_insufficient_data(self):
        tests = {
            "raw": {"ic_crowding_z_vs_fwd_ret_5d": {"status": "insufficient_sample", "n": 5}},
            "incremental": {},
            "double_sort": {},
        }
        result = evaluate_decision_rule(tests, [5])
        assert result["classification"] == "insufficient_data"
