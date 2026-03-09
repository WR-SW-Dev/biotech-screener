"""Tests for bucketed verdict automation.

Validates:
  1. compute_bucket_verdict — PROMOTE, ARCHIVE, NEEDS_MORE
  2. BUCKET_FILTER_MAP used correctly
  3. write_bucket_verdict — output files well-formed
  4. Integration with mock evaluate()
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.research.run_bucketed_verdict import compute_bucket_verdict, run_bucketed_verdict, write_bucket_verdict


class TestComputeBucketVerdict:
    def test_promote(self):
        cand = {"84": {"mean_net_return": 0.05}, "126": {"mean_net_return": 0.06}}
        base = {"84": {"mean_net_return": 0.04}, "126": {"mean_net_return": 0.0375}}
        verdict = compute_bucket_verdict(cand, base, primary_pp=0.20, guardrail_pp=-0.05)
        # 126d delta = (0.06-0.0375)*100 = 2.25pp >= 0.20; 84d delta = (0.05-0.04)*100 = 1.0pp >= -0.05
        assert verdict == "PROMOTE"

    def test_archive(self):
        cand = {"84": {"mean_net_return": 0.03}, "126": {"mean_net_return": 0.02}}
        base = {"84": {"mean_net_return": 0.04}, "126": {"mean_net_return": 0.035}}
        verdict = compute_bucket_verdict(cand, base, primary_pp=0.20, guardrail_pp=-0.05)
        # 126d delta = (0.02-0.035)*100 = -1.5pp < -0.10 → ARCHIVE
        assert verdict == "ARCHIVE"

    def test_needs_more(self):
        cand = {"84": {"mean_net_return": 0.04}, "126": {"mean_net_return": 0.04}}
        base = {"84": {"mean_net_return": 0.04}, "126": {"mean_net_return": 0.0395}}
        verdict = compute_bucket_verdict(cand, base, primary_pp=0.20, guardrail_pp=-0.05)
        # 126d delta = (0.04-0.0395)*100 = 0.05pp, between thresholds → NEEDS_MORE
        assert verdict == "NEEDS_MORE"


class TestBucketFilterMaps:
    def test_maps_used(self):
        from scripts.research.eval_by_bucket import BUCKET_FILTER_MAP

        assert "binary_91_180" in BUCKET_FILTER_MAP
        assert BUCKET_FILTER_MAP["binary_91_180"] == ["less_binary"]


class TestWriteBucketVerdict:
    def test_output_files(self, tmp_path):
        result = {
            "bucket": "binary_91_180",
            "verdict": "PROMOTE",
            "oos_delta": {"84": 1.0, "126": 2.25},
            "is_delta": {"84": 0.5, "126": 1.0},
            "evidence_table": [
                {"horizon": 84, "cand_net": 0.05, "base_net": 0.04, "delta_pp": 1.0},
                {"horizon": 126, "cand_net": 0.06, "base_net": 0.0375, "delta_pp": 2.25},
            ],
            "recommendation": "Candidate clears both primary and guardrail thresholds.",
        }
        out_dir = tmp_path / "verdict"
        md_path, json_path = write_bucket_verdict(result, out_dir)
        assert md_path.is_file()
        assert json_path.is_file()
        text = md_path.read_text()
        assert "PROMOTE" in text
        assert "binary_91_180" in text
        data = json.loads(json_path.read_text())
        assert data["verdict"] == "PROMOTE"


class TestRunBucketedVerdictIntegration:
    def test_with_mock_evaluate(self, tmp_path):
        """Mock evaluate() to test the full pipeline without real data."""
        from collections import namedtuple

        EvalSummary = namedtuple("EvalSummary", ["n_evaluated", "n_dates", "by_horizon"])
        mock_cand_summary = EvalSummary(
            n_evaluated=100,
            n_dates=50,
            by_horizon={
                84: {"mean_net_return": 0.05, "mean_ic": 0.03},
                126: {"mean_net_return": 0.06, "mean_ic": 0.04},
            },
        )
        mock_base_summary = EvalSummary(
            n_evaluated=100,
            n_dates=50,
            by_horizon={
                84: {"mean_net_return": 0.04, "mean_ic": 0.02},
                126: {"mean_net_return": 0.0375, "mean_ic": 0.025},
            },
        )

        with patch("scripts.research.run_bucketed_verdict.evaluate") as mock_eval:
            mock_eval.side_effect = [
                (mock_cand_summary, [], []),
                (mock_base_summary, [], []),
            ]
            result = run_bucketed_verdict(
                candidate_dir=tmp_path / "cand",
                baseline_dir=tmp_path / "base",
                bucket="binary_91_180",
                horizons=[84, 126],
            )

        assert result["verdict"] == "PROMOTE"
        assert result["bucket"] == "binary_91_180"
        assert len(result["evidence_table"]) == 2
