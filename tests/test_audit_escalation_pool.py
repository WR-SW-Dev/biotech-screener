"""Tests for CH-7 escalation-pool audit tool (tools/audit_escalation_pool.py)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import audit_escalation_pool as mod


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def test_in_escalation_pool_matches_spec():
    yes = {"needs_review": True, "informational_only": False, "ticker_collision_flag": False}
    assert mod._in_escalation_pool(yes)

    # Legacy records with ticker_collision_flag=None must still be in the pool
    legacy = {"needs_review": True, "informational_only": False, "ticker_collision_flag": None}
    assert mod._in_escalation_pool(legacy)

    # Hard excludes
    assert not mod._in_escalation_pool(
        {"needs_review": True, "informational_only": True, "ticker_collision_flag": False}
    )
    assert not mod._in_escalation_pool(
        {"needs_review": True, "informational_only": False, "ticker_collision_flag": True}
    )
    assert not mod._in_escalation_pool(
        {"needs_review": False, "informational_only": False, "ticker_collision_flag": False}
    )


def test_audit_reads_and_samples(tmp_path, monkeypatch):
    classified = tmp_path / "classified"
    classified.mkdir()
    records = []
    for i in range(10):
        records.append(
            {
                "event_id": f"e-{i}",
                "dedupe_key": f"d-{i}",
                "ticker": f"TKR{i}",
                "headline": f"headline {i} phase 3 trial",
                "event_category": "clinical",
                "confidence": 0.5,
                "needs_review": True,
                "informational_only": False,
                "ticker_collision_flag": False,
            }
        )
    _write_jsonl(classified / "classified_2026-04-17.jsonl", records)
    # audit_escalation_pool uses _load_company_names which reads from
    # production_data/company_ir_sources.json relative to PROJECT_ROOT.
    (tmp_path / "production_data").mkdir()
    (tmp_path / "production_data" / "company_ir_sources.json").write_text('{"sources": []}')
    import tools.classify_press_releases as clf_mod

    monkeypatch.setattr(clf_mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)

    report = mod.audit(classified, n=5, seed=42)
    assert report["raw_record_count"] == 10
    assert report["raw_pool_count"] == 10
    assert report["pool_count_deduped"] == 10
    assert report["sample_n"] == 5
    assert len(report["sample_rows"]) == 5
    for row in report["sample_rows"]:
        assert "manual_label" in row  # placeholder present for reviewer


def test_audit_dedupes_on_dedupe_key(tmp_path, monkeypatch):
    classified = tmp_path / "classified"
    classified.mkdir()
    _write_jsonl(
        classified / "classified_2026-04-17.jsonl",
        [
            {
                "event_id": "a",
                "dedupe_key": "same",
                "ticker": "A",
                "headline": "h1",
                "event_category": "clinical",
                "confidence": 0.5,
                "needs_review": True,
                "informational_only": False,
                "ticker_collision_flag": False,
            },
            {
                "event_id": "b",
                "dedupe_key": "same",
                "ticker": "A",
                "headline": "h1",
                "event_category": "clinical",
                "confidence": 0.5,
                "needs_review": True,
                "informational_only": False,
                "ticker_collision_flag": False,
            },
        ],
    )
    (tmp_path / "production_data").mkdir()
    (tmp_path / "production_data" / "company_ir_sources.json").write_text('{"sources": []}')
    import tools.classify_press_releases as clf_mod

    monkeypatch.setattr(clf_mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)

    report = mod.audit(classified, n=5, seed=42)
    assert report["raw_pool_count"] == 2
    assert report["pool_count_deduped"] == 1


def test_sample_balanced_prefers_category_targets():
    import random

    pool = (
        [{"event_category": "clinical", "id": i} for i in range(50)]
        + [{"event_category": "regulatory", "id": i + 100} for i in range(50)]
        + [{"event_category": "other", "id": i + 200} for i in range(50)]
    )
    sample = mod._sample_balanced(
        pool,
        n=10,
        rng=random.Random(1),
        targets={"clinical": 4, "regulatory": 3, "other": 3},
    )
    cats = [r["event_category"] for r in sample]
    assert cats.count("clinical") == 4
    assert cats.count("regulatory") == 3
    assert cats.count("other") == 3
