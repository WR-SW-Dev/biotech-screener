"""Tests for CH-6 cache re-classification (tools/reclassify_press_release_cache.py).

Verifies:
- Originals are never mutated (side-dir semantics, CCFT "Frozen" rule).
- Diff report captures dropped-as-noise, new soft/hard collisions, category flips.
- Re-classification preserves event_id lineage.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import reclassify_press_release_cache as mod


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def _setup_fixture(tmp_path: Path, monkeypatch) -> Path:
    """Point the module's CLASSIFIED_DIR / OUT_DIR / REPORT_DIR at tmp_path."""
    classified = tmp_path / "classified"
    out = classified / "reclassified"
    reports = out / "_reports"
    classified.mkdir(parents=True)
    monkeypatch.setattr(mod, "CLASSIFIED_DIR", classified)
    monkeypatch.setattr(mod, "OUT_DIR", out)
    monkeypatch.setattr(mod, "REPORT_DIR", reports)
    # Also patch PROJECT_ROOT in classify_press_releases so _load_company_names
    # doesn't try to read production IR sources during tests.
    import tools.classify_press_releases as clf_mod

    (tmp_path / "production_data").mkdir()
    (tmp_path / "production_data" / "company_ir_sources.json").write_text('{"sources": []}')
    monkeypatch.setattr(clf_mod, "PROJECT_ROOT", tmp_path)
    return classified


def test_originals_not_mutated(tmp_path, monkeypatch):
    classified = _setup_fixture(tmp_path, monkeypatch)
    src = classified / "classified_2026-04-17.jsonl"
    original = [
        {
            "event_id": "e1",
            "dedupe_key": "d1",
            "ticker": "SION",
            "company": "Sionna",
            "headline": "Sionna Reports Positive Phase 3 Trial Data With Primary Endpoint Met",
            "source_url": "",
            "source_type": "company_ir",
            "published_at_utc": "2026-04-17",
            "classified_at_utc": "2026-04-17T00:00:00+00:00",
            "classification_method": "local_keywords",
            "event_category": "clinical",
            "event_outcome_guess": "hit",
            "confidence": 0.6,
            "informational_only": False,
            "needs_review": True,
        },
    ]
    _write_jsonl(src, original)
    src_before = src.read_text()

    kept, diff = mod.reclassify_file(src)
    mod.write_output(src, kept)
    mod.write_per_file_report(diff)

    assert src.read_text() == src_before, "original jsonl must not be mutated"
    out_path = mod.OUT_DIR / src.name
    assert out_path.exists()
    assert out_path != src


def test_new_noise_pattern_drops_record(tmp_path, monkeypatch):
    classified = _setup_fixture(tmp_path, monkeypatch)
    src = classified / "classified_2026-03-15.jsonl"
    # CH-5 added "halper sadeh" — a record that slipped the old noise filter
    # should be dropped now.
    _write_jsonl(
        src,
        [
            {
                "event_id": "e2",
                "dedupe_key": "d2",
                "ticker": "ACLX",
                "company": "Arcellx",
                "headline": "Halper Sadeh LLC is Investigating Whether ACLX is Obtaining Fair Deals",
                "source_url": "",
                "source_type": "company_ir",
                "published_at_utc": "2026-03-15",
                "event_category": "other",
                "informational_only": False,
                "confidence": 0.3,
                "needs_review": True,
            }
        ],
    )
    kept, diff = mod.reclassify_file(src)
    assert diff.n_dropped_as_new_noise == 1
    assert diff.n_reclassified == 0
    assert len(kept) == 0


def test_soft_collision_tracked_in_diff(tmp_path, monkeypatch):
    classified = _setup_fixture(tmp_path, monkeypatch)
    src = classified / "classified_2026-03-20.jsonl"
    # Headline with exactly one discriminative biotech indicator (efficacy)
    # + missing registry entry → soft collision under CH-4 + P2.
    _write_jsonl(
        src,
        [
            {
                "event_id": "e3",
                "dedupe_key": "d3",
                "ticker": "ZZZZ",
                "company": "Unknown",
                "headline": "Long Term Data Published in JAMA Neurology Demonstrate Sustained Efficacy and Consistent Safety of BRIUMVI in Relapsing Multiple Sclerosis",
                "source_url": "",
                "source_type": "company_ir",
                "published_at_utc": "2026-03-20",
                "event_category": "other",
                "informational_only": False,
                "confidence": 0.3,
                "needs_review": True,
            }
        ],
    )
    kept, diff = mod.reclassify_file(src)
    assert diff.n_newly_collision_soft == 1
    assert diff.n_newly_collision_hard == 0
    assert len(kept) == 1
    rec = kept[0]
    assert rec["ticker_collision_flag"] is True
    assert rec["collision_severity"] == "soft"
    assert rec["informational_only"] is False  # P2: stays visible


def test_hard_collision_tracked_in_diff(tmp_path, monkeypatch):
    classified = _setup_fixture(tmp_path, monkeypatch)
    src = classified / "classified_2026-03-21.jsonl"
    _write_jsonl(
        src,
        [
            {
                "event_id": "e4",
                "dedupe_key": "d4",
                "ticker": "ZZZZ",
                "company": "Unknown",
                "headline": "Fancamp Acquires Iron Ore Royalty and Provides Corporate Update",
                "source_url": "",
                "source_type": "company_ir",
                "published_at_utc": "2026-03-21",
                "event_category": "other",
                "informational_only": False,
                "confidence": 0.3,
                "needs_review": True,
            }
        ],
    )
    kept, diff = mod.reclassify_file(src)
    assert diff.n_newly_collision_hard == 1
    assert diff.n_newly_collision_soft == 0
    rec = kept[0]
    assert rec["ticker_collision_flag"] is True
    assert rec["collision_severity"] == "hard"
    assert rec["informational_only"] is True  # hard → silent drop


def test_event_id_preserved(tmp_path, monkeypatch):
    classified = _setup_fixture(tmp_path, monkeypatch)
    src = classified / "classified_2026-03-22.jsonl"
    original_id = "e-preserve-me-123"
    original_ts = "2026-03-22T14:33:00+00:00"
    _write_jsonl(
        src,
        [
            {
                "event_id": original_id,
                "dedupe_key": "d5",
                "ticker": "SION",
                "company": "Sionna",
                "headline": "Sionna Announces Positive Phase 3 Trial Primary Endpoint Met",
                "source_url": "",
                "source_type": "company_ir",
                "published_at_utc": "2026-03-22",
                "classified_at_utc": original_ts,
                "event_category": "clinical",
                "informational_only": False,
                "confidence": 0.6,
                "needs_review": True,
            }
        ],
    )
    kept, _ = mod.reclassify_file(src)
    assert len(kept) == 1
    assert kept[0]["event_id"] == original_id
    assert kept[0].get("classified_at_utc_original") == original_ts


def test_aggregate_report_has_totals(tmp_path, monkeypatch):
    _setup_fixture(tmp_path, monkeypatch)
    diff1 = mod.FileDiff(
        path="a.jsonl", n_original=3, n_reclassified=2, n_dropped_as_new_noise=1, n_newly_collision_soft=1
    )
    diff2 = mod.FileDiff(path="b.jsonl", n_original=5, n_reclassified=5, n_newly_collision_hard=2, n_category_changed=1)
    rpt = mod.write_aggregate_report([diff1, diff2])
    data = json.loads(rpt.read_text())
    assert data["files_processed"] == 2
    assert data["totals"]["n_original"] == 8
    assert data["totals"]["n_dropped_as_new_noise"] == 1
    assert data["totals"]["n_newly_collision_hard"] == 2
    assert data["totals"]["n_newly_collision_soft"] == 1
    assert data["totals"]["n_category_changed"] == 1
