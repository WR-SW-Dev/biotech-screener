"""Tests for the classifier escalation-pool check in tools/production_qa_check.py.

Validates the post-cutover validation hook added with the classifier hardening
rollout (2026-04-19).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import production_qa_check as mod


def _write_record(path: Path, rec: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(rec) + "\n")


def _setup_env(tmp_path: Path, monkeypatch, min_date: str | None) -> Path:
    """Point production_qa_check + audit_escalation_pool + classify_press_releases
    at a tmp repo root. Returns the tmp repo root for further fixture writes."""
    (tmp_path / "config").mkdir()
    cfg = {"classifier_min_date": min_date} if min_date is not None else {}
    (tmp_path / "config" / "post_cutover_floor.json").write_text(json.dumps(cfg))

    (tmp_path / "data" / "press_releases" / "classified").mkdir(parents=True)
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "production_data").mkdir()
    (tmp_path / "production_data" / "company_ir_sources.json").write_text('{"sources": []}')

    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(mod, "OUTPUT_DIR", tmp_path / "artifacts" / "production_qa")

    import tools.audit_escalation_pool as audit_mod

    monkeypatch.setattr(audit_mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(audit_mod, "CANONICAL_DIR", tmp_path / "data" / "press_releases" / "classified")
    monkeypatch.setattr(
        audit_mod, "RECLASSIFIED_DIR", tmp_path / "data" / "press_releases" / "classified" / "reclassified"
    )

    import tools.classify_press_releases as clf_mod

    monkeypatch.setattr(clf_mod, "PROJECT_ROOT", tmp_path)

    return tmp_path


def test_missing_config_fails(tmp_path, monkeypatch):
    # Intentionally no config file
    (tmp_path / "data" / "press_releases" / "classified").mkdir(parents=True)
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    res = mod.check_classifier_escalation_pool("2026-04-20")
    assert res["status"] == "FAIL"
    assert "missing" in res["detail"].lower()


def test_config_without_min_date_fails(tmp_path, monkeypatch):
    _setup_env(tmp_path, monkeypatch, min_date=None)
    res = mod.check_classifier_escalation_pool("2026-04-20")
    assert res["status"] == "FAIL"
    assert "classifier_min_date" in res["detail"]


def test_empty_pool_awaiting_cron_passes(tmp_path, monkeypatch):
    _setup_env(tmp_path, monkeypatch, min_date="2026-04-20")
    # No classified files dated on/after min_date → pool empty
    res = mod.check_classifier_escalation_pool("2026-04-20")
    assert res["status"] == "PASS"
    assert "awaiting" in res["detail"]


def test_healthy_pool_passes_and_emits_hard_collision_sample(tmp_path, monkeypatch):
    root = _setup_env(tmp_path, monkeypatch, min_date="2026-04-20")
    classified = root / "data" / "press_releases" / "classified"
    # 20 clean biotech items + 10 hard collisions
    for i in range(20):
        _write_record(
            classified / "classified_2026-04-21.jsonl",
            {
                "event_id": f"clean-{i}",
                "dedupe_key": f"dc-{i}",
                "ticker": f"TKR{i:02d}",
                "headline": f"Phase 3 clinical trial data for TKR{i:02d}",
                "event_category": "clinical",
                "confidence": 0.6,
                "needs_review": True,
                "informational_only": False,
                "ticker_collision_flag": False,
                "collision_severity": "none",
            },
        )
    for i in range(10):
        _write_record(
            classified / "classified_2026-04-21.jsonl",
            {
                "event_id": f"hard-{i}",
                "dedupe_key": f"dh-{i}",
                "ticker": f"HRD{i:02d}",
                "headline": f"Unrelated mining company {i} quarterly update",
                "event_category": "other",
                "confidence": 0.2,
                "needs_review": False,
                "informational_only": True,
                "ticker_collision_flag": True,
                "collision_severity": "hard",
            },
        )
    res = mod.check_classifier_escalation_pool("2026-04-21")
    assert res["status"] == "PASS", res["detail"]
    assert "pool=20" in res["detail"]
    # hard-collision artifact emitted
    hard_path = root / "artifacts" / "production_qa" / "hard_collisions_2026-04-21.json"
    assert hard_path.exists()
    data = json.loads(hard_path.read_text())
    assert data["hard_collision_pool_size"] == 10
    assert len(data["hard_collision_sample"]) == 10


def test_elevated_other_share_fails(tmp_path, monkeypatch):
    root = _setup_env(tmp_path, monkeypatch, min_date="2026-04-20")
    classified = root / "data" / "press_releases" / "classified"
    # Pool of 20 items, 15 in "other" category (75% > 50% threshold)
    for i in range(15):
        _write_record(
            classified / "classified_2026-04-21.jsonl",
            {
                "event_id": f"oth-{i}",
                "dedupe_key": f"do-{i}",
                "ticker": f"OTH{i:02d}",
                "headline": f"Some other update {i}",
                "event_category": "other",
                "confidence": 0.3,
                "needs_review": True,
                "informational_only": False,
                "ticker_collision_flag": False,
                "collision_severity": "none",
            },
        )
    for i in range(5):
        _write_record(
            classified / "classified_2026-04-21.jsonl",
            {
                "event_id": f"cln-{i}",
                "dedupe_key": f"dn-{i}",
                "ticker": f"CLN{i:02d}",
                "headline": f"Phase 3 trial data {i}",
                "event_category": "clinical",
                "confidence": 0.6,
                "needs_review": True,
                "informational_only": False,
                "ticker_collision_flag": False,
                "collision_severity": "none",
            },
        )
    res = mod.check_classifier_escalation_pool("2026-04-21")
    assert res["status"] == "FAIL"
    assert "other_share" in res["detail"]


def test_disabled_floor_audits_full_cache(tmp_path, monkeypatch):
    root = _setup_env(tmp_path, monkeypatch, min_date="")  # explicitly disabled
    classified = root / "data" / "press_releases" / "classified"
    for i in range(5):
        _write_record(
            classified / "classified_2024-01-15.jsonl",
            {
                "event_id": f"old-{i}",
                "dedupe_key": f"dx-{i}",
                "ticker": f"OLD{i:02d}",
                "headline": f"Phase 3 trial {i}",
                "event_category": "clinical",
                "confidence": 0.6,
                "needs_review": True,
                "informational_only": False,
                "ticker_collision_flag": False,
                "collision_severity": "none",
            },
        )
    res = mod.check_classifier_escalation_pool("2026-04-21")
    # Floor disabled → reads old files too → pool non-empty → healthy
    assert res["status"] == "PASS"
    assert "pool=5" in res["detail"]
