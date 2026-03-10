"""Tests for run_promotion_battery.py."""

from __future__ import annotations

import json

from scripts.research.run_promotion_battery import (
    build_packet,
    compute_overall_verdict,
    write_packet_json,
    write_packet_md,
)

# ---------------------------------------------------------------------------
# Helpers — minimal verdict dicts
# ---------------------------------------------------------------------------


def _bucket_v(verdict: str, delta_pp: float = 0.5) -> dict:
    return {
        "verdict": verdict,
        "bucket": "test",
        "oos_delta": {"84": delta_pp, "126": delta_pp + 0.1},
    }


def _weekly_v(verdict: str) -> dict:
    return {
        "verdict": verdict,
        "n_periods": 10,
        "n_dates": 10,
        "policy": {
            "gate": {
                "pass": verdict == "PASS",
                "checks": [
                    {
                        "name": "policy_cum_hedged",
                        "threshold": ">= +1.00pp",
                        "actual": "+1.50pp",
                        "pass": verdict == "PASS",
                    },
                ],
            },
        },
        "global": {
            "gate": {
                "pass": verdict == "PASS",
                "checks": [
                    {
                        "name": "global_mean_hedged",
                        "threshold": ">= -0.01pp",
                        "actual": "+0.10pp",
                        "pass": verdict == "PASS",
                    },
                ],
            },
        },
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestComputeOverallVerdict:
    def test_compute_overall_verdict_pass(self):
        """All buckets PROMOTE + weekly PASS -> PASS."""
        buckets = {
            "binary_0_30": _bucket_v("PROMOTE"),
            "binary_31_90": _bucket_v("PROMOTE"),
            "binary_91_180": _bucket_v("PROMOTE"),
            "less_binary": _bucket_v("PROMOTE"),
        }
        weekly = _weekly_v("PASS")
        assert compute_overall_verdict(buckets, weekly) == "PASS"

    def test_compute_overall_verdict_fail_weekly(self):
        """Weekly FAIL -> FAIL regardless of buckets."""
        buckets = {
            "binary_0_30": _bucket_v("PROMOTE"),
            "less_binary": _bucket_v("PROMOTE"),
        }
        weekly = _weekly_v("FAIL")
        assert compute_overall_verdict(buckets, weekly) == "FAIL"

    def test_compute_overall_verdict_fail_archive(self):
        """One bucket ARCHIVE -> FAIL."""
        buckets = {
            "binary_0_30": _bucket_v("PROMOTE"),
            "less_binary": _bucket_v("ARCHIVE"),
        }
        weekly = _weekly_v("PASS")
        assert compute_overall_verdict(buckets, weekly) == "FAIL"

    def test_compute_overall_verdict_needs_more(self):
        """No ARCHIVE, weekly PASS, but one bucket NEEDS_MORE -> NEEDS_MORE."""
        buckets = {
            "binary_0_30": _bucket_v("PROMOTE"),
            "less_binary": _bucket_v("NEEDS_MORE"),
        }
        weekly = _weekly_v("PASS")
        assert compute_overall_verdict(buckets, weekly) == "NEEDS_MORE"


class TestWritePacket:
    def test_write_packet_md(self, tmp_path):
        """Write PROMOTION_PACKET.md and verify key sections."""
        buckets = {
            "binary_0_30": _bucket_v("PROMOTE", 0.3),
            "less_binary": _bucket_v("NEEDS_MORE", -0.02),
        }
        weekly = _weekly_v("PASS")
        overall = compute_overall_verdict(buckets, weekly)
        packet = build_packet(
            buckets,
            weekly,
            overall,
            candidate_id="abc123",
            baseline_id="def456",
        )
        md_path = tmp_path / "PROMOTION_PACKET.md"
        write_packet_md(packet, md_path)

        text = md_path.read_text(encoding="utf-8")
        assert "# Promotion Battery" in text
        assert "**Overall Verdict**: **NEEDS_MORE**" in text
        assert "abc123" in text
        assert "def456" in text
        assert "## Per-Snapshot Bucketed Verdicts" in text
        assert "## Weekly Live-Sim Verdict" in text
        assert "## Difference Audit" in text
        assert "binary_0_30" in text

    def test_write_packet_json(self, tmp_path):
        """Write PROMOTION_PACKET.json and verify schema fields."""
        buckets = {"binary_0_30": _bucket_v("PROMOTE")}
        weekly = _weekly_v("PASS")
        overall = "PASS"
        packet = build_packet(
            buckets,
            weekly,
            overall,
            candidate_id="cand1",
            baseline_id="base1",
        )
        json_path = tmp_path / "PROMOTION_PACKET.json"
        write_packet_json(packet, json_path)

        loaded = json.loads(json_path.read_text(encoding="utf-8"))
        assert loaded["schema"] == "promotion_packet.v1"
        assert loaded["overall_verdict"] == "PASS"
        assert loaded["candidate_id"] == "cand1"
        assert loaded["baseline_id"] == "base1"
        assert "bucket_verdicts" in loaded
        assert "weekly_verdict" in loaded
        assert "summary" in loaded
        assert loaded["summary"]["buckets_promote"] == 1
        assert "generated_at" in loaded
