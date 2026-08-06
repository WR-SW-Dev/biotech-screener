"""Retention/cleanup tests (design §4).

The pruner's denylist is the part that must not be wrong: two data categories here are
unrecoverable (PIT options cache, forward-validation evidence). Each denylist entry gets
its own test so a future edit that drops one fails loudly.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from common.paths import for_user
from common.tenancy import UserContext
from tools.prune_user_data import (
    PruneRefusal,
    is_denylisted,
    list_snapshot_dirs,
    plan_prune,
    protected_dates_from_captures,
    select_prunable,
)

TODAY = date(2026, 7, 31)


def _ctx(tmp_path, user_id="alice", retention_days=180, min_keep=60):
    return UserContext(
        user_id=user_id,
        account_number="111",
        broker_server="srv",
        data_root=tmp_path / "tenants" / user_id,
        retention_days=retention_days,
        min_keep_snapshots=min_keep,
    )


def _make_snapshots(paths, dates):
    for d in dates:
        (paths.snapshots_root / d).mkdir(parents=True, exist_ok=True)
    return [paths.snapshots_root / d for d in dates]


# ---------------------------------------------------------------------------------------
# denylist — one test per protected category
# ---------------------------------------------------------------------------------------


def test_massive_options_cache_is_never_prunable(tmp_path):
    """PIT options data cannot be re-fetched; deleting it is unrecoverable."""
    base = tmp_path
    target = base / "data" / "caches" / "massive_options"
    target.mkdir(parents=True)
    assert is_denylisted(target, base=base)
    assert is_denylisted(target / "2024-01-01", base=base)


def test_forward_validation_artifacts_are_never_prunable(tmp_path):
    """captures.jsonl is the mandate's immutable evidence of record."""
    base = tmp_path
    target = base / "artifacts" / "forward_validation"
    target.mkdir(parents=True)
    assert is_denylisted(target, base=base)
    assert is_denylisted(target / "2026-07-31", base=base)


def test_ic_council_artifacts_are_never_prunable(tmp_path):
    base = tmp_path
    target = base / "artifacts" / "ic_council"
    target.mkdir(parents=True)
    assert is_denylisted(target, base=base)


def test_quarantine_snapshots_are_never_prunable(tmp_path):
    """'__pre_' dirs are kept deliberately for provenance audits."""
    base = tmp_path
    target = base / "data" / "snapshots" / "2026-07-15__pre_0409403e_provenance_mismatch"
    target.mkdir(parents=True)
    assert is_denylisted(target, base=base)


def test_ordinary_snapshot_is_not_denylisted(tmp_path):
    base = tmp_path
    target = base / "data" / "snapshots" / "2026-01-02"
    target.mkdir(parents=True)
    assert not is_denylisted(target, base=base)


def test_path_outside_tenant_root_is_treated_as_protected(tmp_path):
    """Fail safe: anything we cannot prove is ours is not ours to delete."""
    assert is_denylisted(Path("/etc"), base=tmp_path)


def test_denylist_is_not_substring_confusable(tmp_path):
    """'massive_options_backup' must not be protected by accident, nor 'x/massive_options'
    missed. Matching is on path segments, not raw substrings."""
    base = tmp_path
    sibling = base / "data" / "caches" / "massive_options_backup"
    sibling.mkdir(parents=True)
    assert not is_denylisted(sibling, base=base)


# ---------------------------------------------------------------------------------------
# capture-referenced dates
# ---------------------------------------------------------------------------------------


def test_dates_referenced_by_captures_are_extracted(tmp_path):
    captures = tmp_path / "captures.jsonl"
    captures.write_text(
        "\n".join(
            [
                json.dumps({"date": "2026-07-15", "snapshot_as_of_date": "2026-07-15"}),
                json.dumps({"date": "2026-07-20", "effective_price_date": "2026-07-20"}),
                "not json at all",
                "",
            ]
        ),
        encoding="utf-8",
    )
    got = protected_dates_from_captures(captures)
    assert got == {"2026-07-15", "2026-07-20"}


def test_missing_captures_file_yields_empty_set(tmp_path):
    assert protected_dates_from_captures(tmp_path / "nope.jsonl") == set()


def test_capture_referenced_snapshot_is_not_pruned(tmp_path):
    """Pruning a captured date would orphan the capture and break the audit trail."""
    paths = for_user(_ctx(tmp_path, min_keep=0), repo_root=tmp_path)
    _make_snapshots(paths, ["2026-01-02", "2026-01-03"])
    plan = select_prunable(
        list_snapshot_dirs(paths.snapshots_root),
        today=TODAY,
        retention_days=30,
        min_keep=0,
        protected_dates={"2026-01-02"},
        base=paths.base,
    )
    names = [p.name for p in plan]
    assert "2026-01-02" not in names
    assert "2026-01-03" in names


# ---------------------------------------------------------------------------------------
# age window and count floor
# ---------------------------------------------------------------------------------------


def test_recent_snapshots_are_kept(tmp_path):
    paths = for_user(_ctx(tmp_path, min_keep=0), repo_root=tmp_path)
    _make_snapshots(paths, ["2026-07-30", "2026-07-29"])
    plan = select_prunable(
        list_snapshot_dirs(paths.snapshots_root),
        today=TODAY,
        retention_days=30,
        min_keep=0,
        base=paths.base,
    )
    assert plan == []


def test_old_snapshots_are_pruned(tmp_path):
    paths = for_user(_ctx(tmp_path, min_keep=0), repo_root=tmp_path)
    _make_snapshots(paths, ["2026-01-02", "2026-07-30"])
    plan = select_prunable(
        list_snapshot_dirs(paths.snapshots_root),
        today=TODAY,
        retention_days=30,
        min_keep=0,
        base=paths.base,
    )
    assert [p.name for p in plan] == ["2026-01-02"]


def test_count_floor_wins_over_age(tmp_path):
    """A long production gap must not empty the tree: min_keep is a hard floor."""
    paths = for_user(_ctx(tmp_path), repo_root=tmp_path)
    old = ["2025-01-%02d" % d for d in range(1, 11)]
    _make_snapshots(paths, old)
    plan = select_prunable(
        list_snapshot_dirs(paths.snapshots_root),
        today=TODAY,
        retention_days=30,
        min_keep=10,
        base=paths.base,
    )
    assert plan == []


def test_count_floor_keeps_the_newest(tmp_path):
    paths = for_user(_ctx(tmp_path), repo_root=tmp_path)
    _make_snapshots(paths, ["2025-01-01", "2025-01-02", "2025-01-03"])
    plan = select_prunable(
        list_snapshot_dirs(paths.snapshots_root),
        today=TODAY,
        retention_days=30,
        min_keep=2,
        base=paths.base,
    )
    assert [p.name for p in plan] == ["2025-01-01"]


@pytest.mark.parametrize("bad_retention", [0, -1, -365])
def test_nonsense_retention_is_refused(tmp_path, bad_retention):
    paths = for_user(_ctx(tmp_path), repo_root=tmp_path)
    with pytest.raises(PruneRefusal):
        select_prunable([], today=TODAY, retention_days=bad_retention, min_keep=0, base=paths.base)


def test_negative_min_keep_is_refused(tmp_path):
    paths = for_user(_ctx(tmp_path), repo_root=tmp_path)
    with pytest.raises(PruneRefusal):
        select_prunable([], today=TODAY, retention_days=30, min_keep=-1, base=paths.base)


def test_non_date_directories_are_ignored(tmp_path):
    paths = for_user(_ctx(tmp_path), repo_root=tmp_path)
    paths.snapshots_root.mkdir(parents=True, exist_ok=True)
    (paths.snapshots_root / "resolutions").mkdir()
    (paths.snapshots_root / "_archive_weekends").mkdir()
    (paths.snapshots_root / "state").mkdir()
    assert list_snapshot_dirs(paths.snapshots_root) == []


# ---------------------------------------------------------------------------------------
# tenant containment
# ---------------------------------------------------------------------------------------


def test_plan_never_leaves_the_tenant_tree(tmp_path):
    paths = for_user(_ctx(tmp_path, min_keep=0), repo_root=tmp_path)
    _make_snapshots(paths, ["2026-01-02"])
    plan = plan_prune(_ctx(tmp_path, min_keep=0), paths=paths, today=TODAY, retention_days=30)
    for path in plan:
        assert paths.owns(path)


def test_one_tenants_prune_cannot_touch_another(tmp_path):
    """alice's pruner must never return a path inside bob's tree."""
    alice = for_user(_ctx(tmp_path, "alice", min_keep=0), repo_root=tmp_path)
    bob = for_user(_ctx(tmp_path, "bob", min_keep=0), repo_root=tmp_path)
    _make_snapshots(alice, ["2026-01-02"])
    _make_snapshots(bob, ["2026-01-02"])

    plan = plan_prune(_ctx(tmp_path, "alice", min_keep=0), paths=alice, today=TODAY, retention_days=30)

    assert [p.name for p in plan] == ["2026-01-02"]
    for path in plan:
        assert alice.owns(path)
        assert not bob.owns(path)
    # bob's identically-named snapshot survives
    assert (bob.snapshots_root / "2026-01-02").is_dir()


def test_plan_is_a_plan_and_deletes_nothing(tmp_path):
    """plan_prune must be pure: dry-run is the default for a reason."""
    paths = for_user(_ctx(tmp_path, min_keep=0), repo_root=tmp_path)
    made = _make_snapshots(paths, ["2026-01-02"])
    plan_prune(_ctx(tmp_path, min_keep=0), paths=paths, today=TODAY, retention_days=30)
    assert made[0].is_dir()
