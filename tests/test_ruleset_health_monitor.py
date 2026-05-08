"""Tests for tools/ruleset_health_monitor.py — post-promotion health check."""

from __future__ import annotations

import json
from pathlib import Path

from tools.ruleset_health_monitor import (
    HealthThresholds,
    _count_consecutive_warns,
    _find_active_receipt,
    _load_history,
    _manifest_active_id,
    evaluate_health,
    run_health_check,
)


def _write_manifest(tmp_path: Path, active_id: str, retired_ids=None) -> Path:
    """Write a minimal manifest.json with one active entry and optional retired entries."""
    rulesets = []
    if retired_ids:
        for rid in retired_ids:
            rulesets.append({"id": rid, "status": "retired"})
    rulesets.append({"id": active_id, "status": "active"})
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps({"schema_version": 1, "rulesets": rulesets}, indent=2),
        encoding="utf-8",
    )
    return manifest_path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_receipt(
    new_active_id: str = "abc12345",
    mean_top60_overlap: float = 95.0,
    max_rank_shift: float = 4.0,
    mean_turnover: float = 0.12,
    created_at_utc: str = "2026-02-25T12:00:00Z",
    action: str = "promote",
) -> dict:
    return {
        "schema": "promote_receipt.v1",
        "created_at_utc": created_at_utc,
        "action": action,
        "new_active_id": new_active_id,
        "old_active_id": "old12345",
        "gate": {
            "verdict": "PASS",
            "mean_top60_overlap": mean_top60_overlap,
            "max_rank_shift": max_rank_shift,
            "mean_turnover": mean_turnover,
        },
    }


def _make_drift_report(
    top60_overlap_pct: float = 93.0,
    mean_abs_rank_delta_top60: float = 5.0,
    current_date: str = "2026-02-28",
) -> dict:
    return {
        "version": "1.0.0",
        "current_date": current_date,
        "prior_date": "2026-02-27",
        "metrics": {
            "top60_overlap_pct": top60_overlap_pct,
            "mean_abs_rank_delta_top60": mean_abs_rank_delta_top60,
            "top20_overlap_pct": 90.0,
            "rank_spearman_rho": 0.95,
        },
        "status": "PASS",
    }


def _write_receipt_file(tmp_path: Path, receipt: dict, filename: str = "promotion_2026-02-25_abc12345.json"):
    receipts_dir = tmp_path / "receipts"
    receipts_dir.mkdir(parents=True, exist_ok=True)
    path = receipts_dir / filename
    path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return receipts_dir


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestOKWithinBaseline:
    def test_ok_when_within_baseline(self, tmp_path):
        """Status is OK when today's metrics are within baseline thresholds."""
        receipt = _make_receipt(mean_top60_overlap=95.0, max_rank_shift=4.0)
        # today: overlap=93 (floor=85), rank_shift=5 (ceiling=12) → OK
        drift = _make_drift_report(top60_overlap_pct=93.0, mean_abs_rank_delta_top60=5.0)
        history = tmp_path / "history.jsonl"

        result = evaluate_health(drift, receipt, history)
        assert result["status"] == "OK"
        assert result["recommend_rollback"] is False
        assert result["consecutive_warn_days"] == 0


class TestWarnOnOverlapDegradation:
    def test_warn_on_overlap_degradation(self, tmp_path):
        """WARN when overlap drops below baseline - delta."""
        receipt = _make_receipt(mean_top60_overlap=95.0)
        # floor = 95 - 10 = 85; today=80 → WARN
        drift = _make_drift_report(top60_overlap_pct=80.0)
        history = tmp_path / "history.jsonl"

        result = evaluate_health(drift, receipt, history)
        assert result["status"] == "WARN"
        assert "top60_overlap" in result["detail"]


class TestWarnOnRankShiftSpike:
    def test_warn_on_rank_shift_spike(self, tmp_path):
        """WARN when rank shift exceeds baseline * factor."""
        receipt = _make_receipt(max_rank_shift=4.0)
        # ceiling = 4.0 * 3.0 = 12.0; today=15 → WARN
        drift = _make_drift_report(mean_abs_rank_delta_top60=15.0)
        history = tmp_path / "history.jsonl"

        result = evaluate_health(drift, receipt, history)
        assert result["status"] == "WARN"
        assert "rank_shift" in result["detail"]


class TestRecommendRollback:
    def test_recommend_rollback_after_n_consecutive_warns(self, tmp_path):
        """Recommend rollback after K consecutive WARN days."""
        receipt = _make_receipt(mean_top60_overlap=95.0)
        history = tmp_path / "history.jsonl"

        # Pre-populate 2 prior WARN days
        prior_entries = [
            {
                "date": "2026-02-26",
                "active_ruleset_id": "abc12345",
                "status": "WARN",
                "top60_overlap_pct": 80.0,
                "max_rank_shift": 15.0,
                "consecutive_warn_days": 1,
                "recommend_rollback": False,
            },
            {
                "date": "2026-02-27",
                "active_ruleset_id": "abc12345",
                "status": "WARN",
                "top60_overlap_pct": 79.0,
                "max_rank_shift": 16.0,
                "consecutive_warn_days": 2,
                "recommend_rollback": False,
            },
        ]
        with open(history, "w") as f:
            for entry in prior_entries:
                f.write(json.dumps(entry) + "\n")

        # Today: also WARN → 3 consecutive → recommend rollback
        drift = _make_drift_report(top60_overlap_pct=78.0)
        th = HealthThresholds(consecutive_warn_days_for_rollback=3)

        result = evaluate_health(drift, receipt, history, th)
        assert result["status"] == "WARN"
        assert result["consecutive_warn_days"] == 3
        assert result["recommend_rollback"] is True


class TestNoReceiptGraceful:
    def test_no_receipt_returns_pass(self, tmp_path):
        """Cold start: no receipt → PASS."""
        drift = _make_drift_report()
        history = tmp_path / "history.jsonl"

        result = evaluate_health(drift, None, history)
        assert result["status"] == "PASS"
        assert "No promotion receipt" in result["detail"]


class TestHistoryAppended:
    def test_history_appended(self, tmp_path):
        """JSONL history grows with each new evaluation date."""
        receipt = _make_receipt()
        history = tmp_path / "history.jsonl"
        drift = _make_drift_report()

        evaluate_health(drift, receipt, history)
        lines = history.read_text().strip().splitlines()
        assert len(lines) == 1

        drift2 = _make_drift_report(current_date="2026-03-01")
        evaluate_health(drift2, receipt, history)
        lines = history.read_text().strip().splitlines()
        assert len(lines) == 2

    def test_same_day_rerun_replaces_history_entry(self, tmp_path):
        """Same-day reruns replace the existing entry instead of appending duplicates."""
        receipt = _make_receipt()
        history = tmp_path / "history.jsonl"

        first = _make_drift_report(
            top60_overlap_pct=80.0,
            mean_abs_rank_delta_top60=5.0,
            current_date="2026-02-28",
        )
        second = _make_drift_report(
            top60_overlap_pct=79.0,
            mean_abs_rank_delta_top60=6.0,
            current_date="2026-02-28",
        )

        first_result = evaluate_health(first, receipt, history)
        second_result = evaluate_health(second, receipt, history)

        assert first_result["status"] == "WARN"
        assert second_result["status"] == "WARN"
        assert second_result["consecutive_warn_days"] == 1

        lines = history.read_text().strip().splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["date"] == "2026-02-28"
        assert entry["active_ruleset_id"] == "abc12345"
        assert entry["top60_overlap_pct"] == 79.0
        assert entry["consecutive_warn_days"] == 1

    def test_same_day_rerun_does_not_inflate_rollback_counter(self, tmp_path):
        """Repeated WARN reruns for one date do not count as multiple consecutive days."""
        receipt = _make_receipt()
        history = tmp_path / "history.jsonl"
        drift = _make_drift_report(
            top60_overlap_pct=80.0,
            mean_abs_rank_delta_top60=5.0,
            current_date="2026-02-28",
        )

        evaluate_health(drift, receipt, history)
        result = evaluate_health(drift, receipt, history)
        result = evaluate_health(drift, receipt, history)

        assert result["status"] == "WARN"
        assert result["consecutive_warn_days"] == 1
        assert result["recommend_rollback"] is False
        assert len(history.read_text().strip().splitlines()) == 1


class TestFirstDayAfterPromotion:
    def test_first_day_after_promotion(self, tmp_path):
        """First day after promotion — no false alarm when within baseline."""
        receipt = _make_receipt(
            mean_top60_overlap=95.0,
            max_rank_shift=4.0,
            created_at_utc="2026-02-27T12:00:00Z",
        )
        drift = _make_drift_report(
            top60_overlap_pct=94.0,
            mean_abs_rank_delta_top60=3.0,
            current_date="2026-02-28",
        )
        history = tmp_path / "history.jsonl"

        result = evaluate_health(drift, receipt, history)
        assert result["status"] == "OK"
        assert result["days_since_promotion"] == 1
        assert result["consecutive_warn_days"] == 0


class TestStatusClearsAfterGoodDay:
    def test_status_clears_after_good_day(self, tmp_path):
        """Consecutive WARN counter resets after a good day."""
        receipt = _make_receipt(mean_top60_overlap=95.0)
        history = tmp_path / "history.jsonl"

        # Pre-populate 2 consecutive WARNs
        prior_entries = [
            {
                "date": "2026-02-26",
                "active_ruleset_id": "abc12345",
                "status": "WARN",
                "consecutive_warn_days": 1,
                "recommend_rollback": False,
            },
            {
                "date": "2026-02-27",
                "active_ruleset_id": "abc12345",
                "status": "WARN",
                "consecutive_warn_days": 2,
                "recommend_rollback": False,
            },
        ]
        with open(history, "w") as f:
            for entry in prior_entries:
                f.write(json.dumps(entry) + "\n")

        # Today: good day → resets to 0
        drift = _make_drift_report(top60_overlap_pct=92.0, mean_abs_rank_delta_top60=3.0)
        result = evaluate_health(drift, receipt, history)
        assert result["status"] == "OK"
        assert result["consecutive_warn_days"] == 0
        assert result["recommend_rollback"] is False


class TestMissingDriftReport:
    def test_missing_drift_report_graceful(self, tmp_path):
        """Missing drift report → PASS with detail."""
        receipt = _make_receipt()
        history = tmp_path / "history.jsonl"

        result = evaluate_health(None, receipt, history)
        assert result["status"] == "PASS"
        assert "No drift report" in result["detail"]


class TestGateIntegration:
    def test_gate_result_wrapper(self, tmp_path):
        """check_ruleset_health returns a correct GateResult."""
        # Set up receipts dir with a receipt
        receipts_dir = tmp_path / "receipts"
        receipts_dir.mkdir()
        receipt = _make_receipt()
        (receipts_dir / "promotion_2026-02-25_abc12345.json").write_text(json.dumps(receipt), encoding="utf-8")

        # Set up staging dir with drift report
        staging = tmp_path / "staging"
        staging.mkdir()
        drift = _make_drift_report()
        (staging / "drift_report.json").write_text(json.dumps(drift), encoding="utf-8")

        history = tmp_path / "history.jsonl"

        result = run_health_check(
            drift_report_path=staging / "drift_report.json",
            receipts_dir=receipts_dir,
            history_path=history,
            output_dir=staging,
            active_ruleset_id="abc12345",
        )

        assert result["schema"] == "ruleset_health.v1"
        assert result["active_ruleset_id"] == "abc12345"
        assert result["status"] in ("OK", "WARN")

        # Sidecar written
        sidecar = staging / "ruleset_health.json"
        assert sidecar.exists()
        sidecar_data = json.loads(sidecar.read_text())
        assert sidecar_data["schema"] == "ruleset_health.v1"


class TestMalformedHistory:
    def test_skips_malformed_lines(self, tmp_path):
        """Malformed JSONL lines should be skipped, valid lines loaded."""
        history = tmp_path / "history.jsonl"
        history.write_text(
            '{"status": "OK", "active_ruleset_id": "abc"}\n'
            '{"broken json\n'
            '{"status": "WARN", "active_ruleset_id": "abc"}\n',
            encoding="utf-8",
        )
        entries = _load_history(history)
        assert len(entries) == 2
        assert entries[0]["status"] == "OK"
        assert entries[1]["status"] == "WARN"

    def test_empty_history_returns_empty(self, tmp_path):
        """Empty history file should return empty list."""
        history = tmp_path / "history.jsonl"
        history.write_text("", encoding="utf-8")
        assert _load_history(history) == []

    def test_missing_history_returns_empty(self, tmp_path):
        """Non-existent history file should return empty list."""
        assert _load_history(tmp_path / "nonexistent.jsonl") == []

    def test_consecutive_warns_with_malformed_gap(self, tmp_path):
        """Malformed line between WARNs should break consecutive count."""
        history = tmp_path / "history.jsonl"
        history.write_text(
            '{"status": "WARN", "active_ruleset_id": "abc"}\n'
            '{"broken\n'
            '{"status": "WARN", "active_ruleset_id": "abc"}\n',
            encoding="utf-8",
        )
        entries = _load_history(history)
        # Only 2 valid entries loaded (both WARN), but the gap is invisible
        count = _count_consecutive_warns(entries, "abc")
        assert count == 2


# ---------------------------------------------------------------------------
# Manifest-aware fallback (P0 #2 reader bug fix)
# ---------------------------------------------------------------------------


class TestManifestActiveIdHelper:
    def test_returns_active_entry_id(self, tmp_path):
        manifest = _write_manifest(tmp_path, active_id="8887576e", retired_ids=["2a3e79eb", "bebe73f8"])
        assert _manifest_active_id(manifest) == "8887576e"

    def test_missing_manifest_returns_none(self, tmp_path):
        assert _manifest_active_id(tmp_path / "missing.json") is None

    def test_no_active_entry_returns_none(self, tmp_path):
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(
            json.dumps({"rulesets": [{"id": "x", "status": "retired"}]}),
            encoding="utf-8",
        )
        assert _manifest_active_id(manifest_path) is None


class TestManifestBeatsRollback:
    """Rollback / promotion receipts on same or older dates must not beat
    the active manifest entry. Reproduces the 2026-05-05 sentinel bug:
    rollback_2026-03-09_bebe73f8.json was returned because filename re-sort
    puts 'r' before 'p', even though canonical was 8887576e."""

    def test_rollback_does_not_override_canonical(self, tmp_path):
        receipts_dir = tmp_path / "receipts"
        receipts_dir.mkdir()
        # Stale rollback receipt that would otherwise win the lexicographic sort
        rollback = _make_receipt(new_active_id="bebe73f8", action="rollback")
        (receipts_dir / "rollback_2026-03-09_bebe73f8.json").write_text(json.dumps(rollback), encoding="utf-8")
        # Older promotion receipts (March 10) — would have won under default
        # behavior with no manifest
        prom = _make_receipt(new_active_id="9f1f4587")
        (receipts_dir / "promotion_2026-03-10_9f1f4587.json").write_text(json.dumps(prom), encoding="utf-8")
        # Manifest says canonical is the new id (no receipt for it on disk)
        manifest = _write_manifest(tmp_path, active_id="8887576e", retired_ids=["bebe73f8"])

        receipt = _find_active_receipt(receipts_dir, manifest_path=manifest)
        assert receipt is not None
        assert receipt["new_active_id"] == "8887576e"
        assert receipt.get("missing_receipt") is True

    def test_legacy_no_manifest_preserves_old_behavior(self, tmp_path):
        """Calling without manifest_path should preserve the legacy
        most-recent-by-filename fallback (still buggy, but backward-compatible
        for callers we don't know about)."""
        receipts_dir = tmp_path / "receipts"
        receipts_dir.mkdir()
        prom = _make_receipt(new_active_id="9f1f4587")
        (receipts_dir / "promotion_2026-03-10_9f1f4587.json").write_text(json.dumps(prom), encoding="utf-8")
        receipt = _find_active_receipt(receipts_dir)
        assert receipt is not None
        assert receipt["new_active_id"] == "9f1f4587"


class TestManifestActiveWithMissingReceipt:
    """Canonical id known from manifest but no matching receipt on disk:
    return explicit missing-receipt stub, not a stale receipt for an old id."""

    def test_returns_missing_receipt_stub(self, tmp_path):
        receipts_dir = tmp_path / "receipts"
        receipts_dir.mkdir()
        # Receipts exist for other (retired) ids only
        old = _make_receipt(new_active_id="2a3e79eb")
        (receipts_dir / "promotion_2026-04-06_2a3e79eb.json").write_text(json.dumps(old), encoding="utf-8")
        manifest = _write_manifest(tmp_path, active_id="8887576e", retired_ids=["2a3e79eb"])

        receipt = _find_active_receipt(receipts_dir, manifest_path=manifest)
        assert receipt["new_active_id"] == "8887576e"
        assert receipt["missing_receipt"] is True
        assert receipt["gate"] == {}

    def test_evaluate_health_handles_missing_receipt(self, tmp_path):
        """Pure missing-receipt stub (no synthetic markers): detail says
        'no promotion receipt available — baseline metrics unavailable
        (consider backfilling receipt)'. Back-compat for the manifest-only
        fallback path."""
        stub = {
            "schema": "promote_receipt.stub.v1",
            "new_active_id": "8887576e",
            "missing_receipt": True,
            "created_at_utc": "",
            "gate": {},
        }
        drift = _make_drift_report()
        history = tmp_path / "history.jsonl"

        result = evaluate_health(drift, stub, history)
        assert result["active_ruleset_id"] == "8887576e"
        assert result["status"] == "PASS"
        assert "no promotion receipt available" in result["detail"]
        assert "baseline metrics unavailable" in result["detail"]
        assert "consider backfilling receipt" in result["detail"]
        assert result["recommend_rollback"] is False
        # Stub path skips history append (consistent with cold-start path)
        assert not history.exists()

    def test_evaluate_health_handles_synthetic_backfilled_receipt(self, tmp_path):
        """Synthetic-backfilled receipt (Spec 086 Option (a) shape): detail
        says 'synthetic backfilled receipt present; promotion baseline metrics
        unavailable'. Distinguishes from the pure-missing-receipt case so
        future audits don't see 'no receipt' when one exists on disk."""
        synthetic = {
            "schema": "promote_receipt.v1.synthetic",
            "receipt_type": "synthetic_backfill",
            "new_active_id": "8887576e",
            "missing_receipt": True,
            "change_class": "signal_demotion_hygiene_patch",
            "source_spec": "Spec 086",
            "created_at_utc": "2026-05-04T22:35:00Z",
            "gate": {},
        }
        drift = _make_drift_report()
        history = tmp_path / "history.jsonl"

        result = evaluate_health(drift, synthetic, history)
        assert result["active_ruleset_id"] == "8887576e"
        assert result["status"] == "PASS"
        assert "synthetic backfilled receipt present" in result["detail"]
        assert "promotion baseline metrics unavailable" in result["detail"]
        # Must NOT use the pure-missing-receipt phrasing
        assert "no promotion receipt available" not in result["detail"]
        assert "consider backfilling receipt" not in result["detail"]
        assert result["recommend_rollback"] is False
        # Stub path skips history append
        assert not history.exists()

    def test_no_receipts_dir_with_manifest_still_returns_stub(self, tmp_path):
        """If receipts_dir doesn't exist but manifest does, still return stub
        rather than None — caller should report the right id."""
        manifest = _write_manifest(tmp_path, active_id="8887576e")
        receipt = _find_active_receipt(
            tmp_path / "nonexistent_receipts_dir",
            manifest_path=manifest,
        )
        assert receipt is not None
        assert receipt["new_active_id"] == "8887576e"
        assert receipt["missing_receipt"] is True


class TestExplicitActiveIdStillWorks:
    """Explicit --active-ruleset-id should override both manifest and
    name-sort fallback."""

    def test_explicit_id_finds_matching_receipt(self, tmp_path):
        receipts_dir = tmp_path / "receipts"
        receipts_dir.mkdir()
        wanted = _make_receipt(new_active_id="targetID")
        other = _make_receipt(new_active_id="otherID")
        (receipts_dir / "promotion_2026-03-01_targetID.json").write_text(json.dumps(wanted), encoding="utf-8")
        (receipts_dir / "promotion_2026-03-10_otherID.json").write_text(json.dumps(other), encoding="utf-8")
        manifest = _write_manifest(tmp_path, active_id="8887576e")

        receipt = _find_active_receipt(
            receipts_dir,
            active_ruleset_id="targetID",
            manifest_path=manifest,
        )
        assert receipt["new_active_id"] == "targetID"
        # Did not get fooled by the lexicographically-later otherID receipt,
        # nor by the manifest's 8887576e.

    def test_explicit_id_with_no_match_returns_stub(self, tmp_path):
        receipts_dir = tmp_path / "receipts"
        receipts_dir.mkdir()
        unrelated = _make_receipt(new_active_id="unrelatedID")
        (receipts_dir / "promotion_2026-03-01_unrelatedID.json").write_text(json.dumps(unrelated), encoding="utf-8")

        receipt = _find_active_receipt(receipts_dir, active_ruleset_id="targetID")
        assert receipt["new_active_id"] == "targetID"
        assert receipt["missing_receipt"] is True
