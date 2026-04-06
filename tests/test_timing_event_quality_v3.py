"""Tests for timing hazard v3 + event quality infrastructure upgrade.

Covers:
  - Warning severity and context_bucket fields
  - REGULATORY_DETERMINISTIC suppression
  - Family hygiene check
  - Calibration status computation
  - Calibration cycle log emission
  - Ground truth expansion
  - Ground truth review queue
  - Outlier review queue
  - Review packet markdown rendering
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.compute_timing_hazard import (
    _compute_calibration_status,
    _compute_execution_warning,
    _hygiene_check_family,
    emit_calibration_cycle_summary,
)

# ---------------------------------------------------------------------------
# Warning severity + context tests
# ---------------------------------------------------------------------------


class TestWarningSeverityAndContext:
    """Verify new severity, context_bucket, and suppression fields."""

    def _call(self, **overrides):
        defaults = dict(
            on_time_prob=0.70,
            last_update_age=30,
            aact_delta=None,
            is_hard=True,
            logistic_prob=0.65,
            catalyst_family="REGULATORY",
            catalyst_days=45,
            precision="DAY",
            date_confidence=0.85,
            source="FDA_CALENDAR",
            n_revisions=0,
            last_revision_pushout=False,
            source_action="ALLOW",
        )
        defaults.update(overrides)
        positional = [
            defaults.pop("on_time_prob"),
            defaults.pop("last_update_age"),
            defaults.pop("aact_delta"),
            defaults.pop("is_hard"),
        ]
        return _compute_execution_warning(*positional, **defaults)

    def test_warnings_have_severity_field(self):
        """Every warning dict must have a severity field."""
        _, reasons = self._call(catalyst_family="", precision="QUARTER")
        for w in reasons:
            assert "severity" in w
            assert w["severity"] in ("HIGH", "MEDIUM", "INFO")

    def test_warnings_have_context_bucket(self):
        """Every warning dict must have a context_bucket field."""
        _, reasons = self._call(catalyst_family="", precision="QUARTER")
        for w in reasons:
            assert "context_bucket" in w
            assert "_" in w["context_bucket"]  # format: FAMILY_HARDNESS_HORIZON

    def test_regulatory_deterministic_suppresses_all(self):
        """REGULATORY + HARD + NEAR returns REGULATORY_DETERMINISTIC, no other warnings."""
        has_warn, reasons = self._call(
            catalyst_family="REGULATORY",
            is_hard=True,
            catalyst_days=15,
            precision="QUARTER",  # would normally trigger LOW_CONFIDENCE_DATE
            last_update_age=150,  # would normally trigger STALE_EVENT_RECORD
        )
        labels = [w["label"] for w in reasons]
        assert "REGULATORY_DETERMINISTIC" in labels
        assert len(labels) == 1  # only the positive signal
        assert not has_warn  # has_warning is False for deterministic

    def test_regulatory_deterministic_only_near(self):
        """REGULATORY_DETERMINISTIC only fires for NEAR horizon."""
        _, reasons = self._call(
            catalyst_family="REGULATORY",
            is_hard=True,
            catalyst_days=60,  # MEDIUM, not NEAR
        )
        labels = [w["label"] for w in reasons]
        assert "REGULATORY_DETERMINISTIC" not in labels

    def test_regulatory_deterministic_requires_hard(self):
        """REGULATORY_DETERMINISTIC requires hard catalyst."""
        _, reasons = self._call(
            catalyst_family="REGULATORY",
            is_hard=False,
            catalyst_days=15,
        )
        labels = [w["label"] for w in reasons]
        assert "REGULATORY_DETERMINISTIC" not in labels

    def test_clinical_soft_near_elevates_short_dated(self):
        """CLINICAL + SOFT + NEAR elevates SHORT_DATED_REVISION_RISK to HIGH."""
        _, reasons = self._call(
            catalyst_family="CLINICAL",
            is_hard=False,
            catalyst_days=15,
            last_revision_pushout=True,
        )
        short_dated = [w for w in reasons if w["label"] == "SHORT_DATED_REVISION_RISK"]
        assert len(short_dated) == 1
        assert short_dated[0]["severity"] == "HIGH"

    def test_hard_catalyst_downgrades_stale(self):
        """STALE_EVENT_RECORD downgraded to INFO for hard catalysts."""
        _, reasons = self._call(
            catalyst_family="CLINICAL",
            is_hard=True,
            last_update_age=150,
        )
        stale = [w for w in reasons if w["label"] == "STALE_EVENT_RECORD"]
        assert len(stale) == 1
        assert stale[0]["severity"] == "INFO"

    def test_soft_catalyst_stale_stays_medium(self):
        """STALE_EVENT_RECORD stays MEDIUM for soft catalysts."""
        _, reasons = self._call(
            catalyst_family="CLINICAL",
            is_hard=False,
            last_update_age=150,
        )
        stale = [w for w in reasons if w["label"] == "STALE_EVENT_RECORD"]
        assert len(stale) == 1
        assert stale[0]["severity"] == "MEDIUM"

    def test_family_missing_always_high(self):
        """FAMILY_MISSING is always HIGH severity."""
        _, reasons = self._call(catalyst_family="")
        missing = [w for w in reasons if w["label"] == "FAMILY_MISSING"]
        assert len(missing) == 1
        assert missing[0]["severity"] == "HIGH"

    def test_warnings_sorted_by_severity(self):
        """Warnings are sorted HIGH first, then MEDIUM, then INFO."""
        _, reasons = self._call(
            catalyst_family="",
            precision="QUARTER",
            last_update_age=200,
            is_hard=False,
        )
        severities = [w["severity"] for w in reasons]
        sev_order = {"HIGH": 0, "MEDIUM": 1, "INFO": 2}
        assert severities == sorted(severities, key=lambda s: sev_order[s])

    def test_source_suppress_is_high(self):
        """SOURCE_UNRELIABLE with SUPPRESS action is HIGH severity."""
        _, reasons = self._call(source_action="SUPPRESS")
        unreliable = [w for w in reasons if w["label"] == "SOURCE_UNRELIABLE"]
        assert unreliable[0]["severity"] == "HIGH"

    def test_source_demote_is_medium(self):
        """SOURCE_UNRELIABLE with DEMOTE action is MEDIUM severity."""
        _, reasons = self._call(source_action="DEMOTE")
        unreliable = [w for w in reasons if w["label"] == "SOURCE_UNRELIABLE"]
        assert unreliable[0]["severity"] == "MEDIUM"

    def test_pcd_delayed_near_is_high(self):
        """PCD_DELAYED is HIGH for NEAR horizon catalysts."""
        _, reasons = self._call(
            catalyst_days=15,
            catalyst_family="CLINICAL",
            is_hard=False,
            aact_delta={"n_pcd_delayed": 1, "n_status_downgrades": 0},
        )
        pcd = [w for w in reasons if w["label"] == "PCD_DELAYED"]
        assert pcd[0]["severity"] == "HIGH"

    def test_pcd_delayed_far_is_medium(self):
        """PCD_DELAYED is MEDIUM for FAR horizon catalysts."""
        _, reasons = self._call(
            catalyst_days=120,
            aact_delta={"n_pcd_delayed": 1, "n_status_downgrades": 0},
        )
        pcd = [w for w in reasons if w["label"] == "PCD_DELAYED"]
        assert pcd[0]["severity"] == "MEDIUM"

    def test_status_downgrade_always_high(self):
        """STATUS_DOWNGRADE is always HIGH severity."""
        _, reasons = self._call(
            aact_delta={"n_pcd_delayed": 0, "n_status_downgrades": 1},
        )
        down = [w for w in reasons if w["label"] == "STATUS_DOWNGRADE"]
        assert down[0]["severity"] == "HIGH"


# ---------------------------------------------------------------------------
# Family hygiene tests
# ---------------------------------------------------------------------------


class TestFamilyHygiene:
    def test_all_known(self):
        catalysts = [
            {"family_bucket": "CLINICAL"},
            {"family_bucket": "REGULATORY"},
            {"family_bucket": "CLINICAL"},
        ]
        result = _hygiene_check_family(catalysts)
        assert result["n_total"] == 3
        assert result["n_missing"] == 0
        assert result["missing_pct"] == 0.0

    def test_some_unknown(self):
        catalysts = [
            {"family_bucket": "CLINICAL"},
            {"family_bucket": "UNKNOWN"},
            {"family_bucket": "UNKNOWN"},
        ]
        result = _hygiene_check_family(catalysts)
        assert result["n_missing"] == 2
        assert result["missing_pct"] > 60

    def test_empty_list(self):
        result = _hygiene_check_family([])
        assert result["n_total"] == 0
        assert result["n_missing"] == 0

    def test_by_family_counts(self):
        catalysts = [
            {"family_bucket": "CLINICAL"},
            {"family_bucket": "CLINICAL"},
            {"family_bucket": "REGULATORY"},
        ]
        result = _hygiene_check_family(catalysts)
        assert result["n_by_family"]["CLINICAL"] == 2
        assert result["n_by_family"]["REGULATORY"] == 1


# ---------------------------------------------------------------------------
# Calibration status tests
# ---------------------------------------------------------------------------


class TestCalibrationStatus:
    def test_no_ledger(self, tmp_path):
        """EXPERIMENTAL when ledger doesn't exist."""
        with patch("tools.compute_timing_hazard.CALIBRATION_LEDGER", tmp_path / "missing.jsonl"):
            assert _compute_calibration_status() == "EXPERIMENTAL"

    def test_few_resolved(self, tmp_path):
        """EXPERIMENTAL when < 50 resolved."""
        ledger = tmp_path / "ledger.jsonl"
        lines = []
        for i in range(30):
            lines.append(json.dumps({"actual_outcome": "ON_TIME"}))
        for i in range(100):
            lines.append(json.dumps({"actual_outcome": None}))
        ledger.write_text("\n".join(lines))
        with patch("tools.compute_timing_hazard.CALIBRATION_LEDGER", ledger):
            assert _compute_calibration_status() == "EXPERIMENTAL"

    def test_under_calibration(self, tmp_path):
        """UNDER_CALIBRATION when 50-199 resolved."""
        ledger = tmp_path / "ledger.jsonl"
        lines = [json.dumps({"actual_outcome": "ON_TIME"}) for _ in range(100)]
        ledger.write_text("\n".join(lines))
        with patch("tools.compute_timing_hazard.CALIBRATION_LEDGER", ledger):
            assert _compute_calibration_status() == "UNDER_CALIBRATION"

    def test_calibrated(self, tmp_path):
        """CALIBRATED when >= 200 resolved."""
        ledger = tmp_path / "ledger.jsonl"
        lines = [json.dumps({"actual_outcome": "ON_TIME"}) for _ in range(250)]
        ledger.write_text("\n".join(lines))
        with patch("tools.compute_timing_hazard.CALIBRATION_LEDGER", ledger):
            assert _compute_calibration_status() == "CALIBRATED"


# ---------------------------------------------------------------------------
# Calibration cycle log tests
# ---------------------------------------------------------------------------


class TestCalibrationCycleLog:
    def test_emits_log_entry(self, tmp_path):
        log_path = tmp_path / "cycle_log.jsonl"
        result = {
            "catalysts": [
                {"family_bucket": "CLINICAL", "horizon_bucket": "NEAR"},
                {"family_bucket": "REGULATORY", "horizon_bucket": "FAR"},
            ],
            "rolling_base_rate": 0.85,
            "calibration_status": "CALIBRATED",
        }
        with (
            patch("tools.compute_timing_hazard.CALIBRATION_CYCLE_LOG", log_path),
            patch("tools.compute_timing_hazard.CALIBRATION_BY_SLICE", tmp_path / "missing.json"),
            patch("tools.compute_timing_hazard.OUTPUT_DIR", tmp_path),
        ):
            emit_calibration_cycle_summary(result, "2026-04-03")

        assert log_path.exists()
        entry = json.loads(log_path.read_text().strip())
        assert entry["cycle_date"] == "2026-04-03"
        assert entry["n_predictions"] == 2
        assert entry["family_dist"]["CLINICAL"] == 1
        assert entry["rolling_base_rate"] == 0.85

    def test_dedup_guard(self, tmp_path):
        log_path = tmp_path / "cycle_log.jsonl"
        log_path.write_text(json.dumps({"cycle_date": "2026-04-03"}) + "\n")
        result = {"catalysts": [], "rolling_base_rate": 0.80, "calibration_status": "?"}
        with (
            patch("tools.compute_timing_hazard.CALIBRATION_CYCLE_LOG", log_path),
            patch("tools.compute_timing_hazard.CALIBRATION_BY_SLICE", tmp_path / "missing.json"),
            patch("tools.compute_timing_hazard.OUTPUT_DIR", tmp_path),
        ):
            emit_calibration_cycle_summary(result, "2026-04-03")

        # Should still be 1 entry (dedup)
        lines = [ln for ln in log_path.read_text().strip().split("\n") if ln]
        assert len(lines) == 1


# ---------------------------------------------------------------------------
# Ground truth expansion tests
# ---------------------------------------------------------------------------


class TestExpandGroundTruth:
    def test_expand_labels(self, tmp_path):
        from scripts.research.expand_ground_truth import expand_labels

        # Create a minimal batch file
        batch = tmp_path / "batch.jsonl"
        records = [
            {
                "ticker": "ACME",
                "published_at_utc": "2026-01-15T10:00:00Z",
                "event_category": "clinical",
                "informational_only": True,
                "gt_label_source": "unlabeled",
            },
            {
                "ticker": "ACME",
                "published_at_utc": "2026-01-16T10:00:00Z",
                "event_category": "regulatory",
                "informational_only": False,
                "gt_label_source": "keyword_auto",
                "gt_event_category": "regulatory",
            },
        ]
        batch.write_text("\n".join(json.dumps(r) for r in records))

        # Mock prices so ACME has data
        prices = {"ACME": {f"2026-01-{d:02d}": 100.0 + d * 0.1 for d in range(1, 31)}}

        with (
            patch("scripts.research.expand_ground_truth._load_prices", return_value=prices),
            patch("scripts.research.expand_ground_truth.GT_DIR", tmp_path),
        ):
            result = expand_labels(batch)

        assert result["n_unlabeled_input"] == 1  # only 1 unlabeled
        assert result["n_auto_labeled"] == 1

    def test_no_unlabeled(self, tmp_path):
        from scripts.research.expand_ground_truth import expand_labels

        batch = tmp_path / "batch.jsonl"
        records = [
            {"gt_label_source": "keyword_auto", "gt_event_category": "clinical"},
        ]
        batch.write_text("\n".join(json.dumps(r) for r in records))

        result = expand_labels(batch)
        assert result["n_unlabeled"] == 0


# ---------------------------------------------------------------------------
# Ground truth review queue tests
# ---------------------------------------------------------------------------


class TestReviewQueue:
    def test_build_review_queue(self):
        from scripts.research.ground_truth_review_queue import build_review_queue

        records = [
            {"gt_label_source": "unlabeled", "ticker": "A", "event_category": "clinical"},
            {
                "gt_label_source": "price_reaction_low_conf",
                "gt_auto_confidence": 0.3,
                "ticker": "B",
                "event_category": "clinical",
                "gt_event_category": "other",
                "gt_return_pct": 0.5,
            },
            {
                "gt_label_source": "keyword_auto",
                "gt_event_category": "clinical",
                "event_category": "clinical",
                "ticker": "C",
            },
        ]
        result = build_review_queue(records)
        assert result["n_total_records"] == 3
        assert result["n_labeled"] == 2  # keyword_auto + price_reaction_low_conf
        assert result["n_needing_review"] >= 2  # unlabeled + low_conf
        assert result["queue"][0]["urgency"] >= result["queue"][-1]["urgency"]

    def test_empty_records(self):
        from scripts.research.ground_truth_review_queue import build_review_queue

        result = build_review_queue([])
        assert result["n_total_records"] == 0
        assert result["queue"] == []


# ---------------------------------------------------------------------------
# Outlier review queue tests
# ---------------------------------------------------------------------------


class TestOutlierReviewQueue:
    def test_build_outlier_queue(self, tmp_path):
        from tools.build_event_quality_confusion import build_outlier_review_queue

        records = [
            {
                "event_category": "clinical",
                "gt_event_category": "other",
                "gt_label_source": "keyword_auto",
                "ticker": "ACME",
                "published_at_utc": "2026-01-15",
                "headline": "Test headline",
                "gt_return_pct": 15.0,
                "gt_informational_only": True,
            },
        ]

        with (
            patch("tools.build_event_quality_confusion.load_ground_truth", return_value=records),
            patch("tools.build_event_quality_confusion.OUTPUT_DIR", tmp_path),
        ):
            result = build_outlier_review_queue()

        assert result["n_outliers"] >= 1
        assert result["queue"][0]["ticker"] == "ACME"


# ---------------------------------------------------------------------------
# Review packet markdown tests
# ---------------------------------------------------------------------------


class TestReviewPacketMarkdown:
    def test_render_markdown(self):
        from tools.build_review_packet import render_review_packet_md

        packet = {
            "snapshot_date": "2026-04-03",
            "generated_at": "2026-04-06T00:00:00Z",
            "artifacts_loaded": {"a": True, "b": True, "c": False},
            "health": {"sections_available": 3, "sections_total": 5},
            "timing": {
                "n_warnings": 2,
                "rolling_base_rate": 0.87,
                "base_rate_trend": -0.02,
                "warnings": [
                    {
                        "ticker": "ACME",
                        "rank": 5,
                        "catalyst_days": 15,
                        "catalyst_family": "CLINICAL",
                        "on_time_prob": 0.28,
                        "warnings": ["SHORT_DATED_REVISION_RISK"],
                    },
                ],
            },
            "calibration": {
                "available": True,
                "n_resolved": 200,
                "overall_brier": 0.184,
                "by_horizon": {"NEAR": {"n": 50, "brier": 0.22, "actual_rate": 0.30}},
            },
            "event_type_distribution": {
                "available": True,
                "event_type_dist": {"PDUFA": 3},
                "mean_event_type_score": 2.1,
            },
            "confusion": {"available": True, "accuracy": 0.965, "n_labeled": 193},
            "herald_precision": {"available": False},
            "review_queue": {"top_priorities": [{"ticker": "XYZ"}]},
        }

        md = render_review_packet_md(packet)
        assert "# Review Packet" in md
        assert "2026-04-03" in md
        assert "ACME" in md
        assert "DIAGNOSTIC" in md
        assert "Brier" in md
