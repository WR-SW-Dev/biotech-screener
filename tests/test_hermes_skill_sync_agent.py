"""Tests for tools/hermes_skill_sync_audit.py — Hermes Skill Sync Guard."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Import the module under test
# ---------------------------------------------------------------------------
import importlib.util
import json
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "hermes_skill_sync_audit",
    REPO_ROOT / "tools" / "hermes_skill_sync_audit.py",
)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
# Register before exec_module so @dataclass can find the module in sys.modules
sys.modules["hermes_skill_sync_audit"] = _mod
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]

from hermes_skill_sync_audit import (  # noqa: E402
    RETIRED_PATTERN_ALLOWLIST,
    SYNC_DIFF_CAP,
    AuditResult,
    DriftItem,
    _has_frontmatter,
    _sha256_content,
    _strip_frontmatter,
    scan_mirror_drift,
    scan_orphaned_mirrors,
    scan_retired_patterns,
    write_heartbeat,
)

# ---------------------------------------------------------------------------
# Helpers for building test fixtures
# ---------------------------------------------------------------------------


def _make_skill(skills_dir: Path, key: str, content: str) -> None:
    """Create skills/<key>/SKILL.md with given content."""
    d = skills_dir / key
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(content, encoding="utf-8")


def _make_mirror(docs_dir: Path, filename: str, content: str) -> None:
    """Create docs/hermes_skills/<filename> with given content."""
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / filename).write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Test 1: Retired correction ledger in skills/ → CRITICAL
# ---------------------------------------------------------------------------


def test_retired_ledger_in_skills_is_critical(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    docs_dir = tmp_path / "docs" / "hermes_skills"
    _make_skill(
        skills_dir,
        "self-improving",
        textwrap.dedent("""\
            # Self-Improving Skill
            See Town Correction Ledger for candidate feed.
        """),
    )
    docs_dir.mkdir(parents=True)

    items = scan_retired_patterns(skills_dir, docs_dir, repo_root=tmp_path)

    critical = [i for i in items if i.severity == "CRITICAL"]
    assert len(critical) >= 1
    assert critical[0].drift_class == "RETIRED_CORRECTION_LEDGER"


# ---------------------------------------------------------------------------
# Test 2: Retired pattern in harvest_log.md (allowlisted) → no items
# ---------------------------------------------------------------------------


def test_retired_ledger_in_allowlisted_file_is_skipped(tmp_path: Path, monkeypatch) -> None:
    docs_dir = tmp_path / "docs" / "hermes_skills"
    docs_dir.mkdir(parents=True)
    log_file = docs_dir / "harvest_log.md"
    log_file.write_text(
        "Historical entry from Town Correction Ledger (2026-05-10)\n",
        encoding="utf-8",
    )
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    monkeypatch.setattr(
        _mod,
        "RETIRED_PATTERN_ALLOWLIST",
        frozenset({"docs/hermes_skills/harvest_log.md"}),
    )

    items = scan_retired_patterns(skills_dir, docs_dir, repo_root=tmp_path)
    assert len(items) == 0


# ---------------------------------------------------------------------------
# Test 3: Retired pattern in docs/hermes_skills/ mirror → WARNING (not CRITICAL)
# ---------------------------------------------------------------------------


def test_retired_ledger_in_mirror_is_warning(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    docs_dir = tmp_path / "docs" / "hermes_skills"
    _make_mirror(docs_dir, "self-improving.md", "Town Correction Ledger reference in mirror\n")

    items = scan_retired_patterns(skills_dir, docs_dir, repo_root=tmp_path)
    warnings = [i for i in items if i.severity == "WARNING"]
    critical = [i for i in items if i.severity == "CRITICAL"]
    assert len(warnings) >= 1
    assert len(critical) == 0


# ---------------------------------------------------------------------------
# Test 4: Source missing frontmatter → FRONTMATTER_MISSING WARNING
#
# SKILL_MAP uses directory-name keys (e.g., "foo") and bare mirror filenames
# (e.g., "foo.md"), not full paths. skills_dir / key / SKILL.md is the source.
# ---------------------------------------------------------------------------


def test_source_missing_frontmatter_is_warning(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    docs_dir = tmp_path / "docs" / "hermes_skills"
    body = "# Foo Skill\nNo frontmatter here.\n"
    _make_skill(skills_dir, "foo", body)
    _make_mirror(docs_dir, "foo.md", body)

    # SKILL_MAP key = directory name; value = bare mirror filename
    items = scan_mirror_drift(
        {"foo": "foo.md"},
        {},
        skills_dir,
        docs_dir,
    )
    classes = [i.drift_class for i in items]
    assert "FRONTMATTER_MISSING" in classes
    assert all(i.severity == "WARNING" for i in items if i.drift_class == "FRONTMATTER_MISSING")


# ---------------------------------------------------------------------------
# Test 5: Mirror file missing → MIRROR_MISSING WARNING
# ---------------------------------------------------------------------------


def test_mirror_missing_is_warning(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    docs_dir = tmp_path / "docs" / "hermes_skills"
    _make_skill(skills_dir, "bar", "---\nname: bar\n---\n# Bar\n")
    # Mirror deliberately absent; create empty docs_dir so path exists
    docs_dir.mkdir(parents=True)

    items = scan_mirror_drift(
        {"bar": "bar.md"},
        {},
        skills_dir,
        docs_dir,
    )
    classes = [i.drift_class for i in items]
    assert "MIRROR_MISSING" in classes
    warn = [i for i in items if i.drift_class == "MIRROR_MISSING"]
    assert warn[0].severity == "WARNING"


# ---------------------------------------------------------------------------
# Test 6: Source and mirror match → no drift items (except pre-existing frontmatter)
# ---------------------------------------------------------------------------


def test_matching_source_and_mirror_produces_no_drift(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    docs_dir = tmp_path / "docs" / "hermes_skills"
    body = "# Baz Skill\nSome content.\n"
    # Source has frontmatter; mirror body (after stripping) matches source body
    _make_skill(skills_dir, "baz", f"---\nname: baz\n---\n{body}")
    _make_mirror(docs_dir, "baz.md", body)

    items = scan_mirror_drift(
        {"baz": "baz.md"},
        {},
        skills_dir,
        docs_dir,
    )
    # Filter out frontmatter warnings (not caused by this test's data)
    non_fm = [i for i in items if i.drift_class != "FRONTMATTER_MISSING"]
    assert len(non_fm) == 0


# ---------------------------------------------------------------------------
# Test 7: Source and mirror content differ → MIRROR_CONTENT_MISMATCH INFO
# ---------------------------------------------------------------------------


def test_content_mismatch_is_info(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    docs_dir = tmp_path / "docs" / "hermes_skills"
    _make_skill(skills_dir, "qux", "---\nname: qux\n---\n# Qux\nUpdated content.\n")
    _make_mirror(docs_dir, "qux.md", "# Qux\nOld content.\n")

    items = scan_mirror_drift(
        {"qux": "qux.md"},
        {},
        skills_dir,
        docs_dir,
    )
    mismatch = [i for i in items if i.drift_class == "MIRROR_CONTENT_MISMATCH"]
    assert len(mismatch) == 1
    assert mismatch[0].severity == "INFO"


# ---------------------------------------------------------------------------
# Test 8: write_heartbeat produces valid JSON with required fields
# ---------------------------------------------------------------------------


def test_write_heartbeat_produces_valid_json(tmp_path: Path, monkeypatch) -> None:
    hb_path = tmp_path / "artifacts" / "governance" / "hermes_skill_sync" / "latest_heartbeat.json"
    monkeypatch.setattr(_mod, "HEARTBEAT_PATH", hb_path)

    result = AuditResult(
        as_of_date="2026-06-26",
        run_ts="2026-06-26T08:00:00+00:00",
        status="OK",
        n_critical=0,
        n_warning=0,
        n_info=2,
        skills_scanned=17,
        mirrors_scanned=20,
    )
    write_heartbeat(result)

    assert hb_path.exists()
    data = json.loads(hb_path.read_text())
    assert data["agent_id"] == "hermes-skill-sync-agent"
    assert data["status"] == "OK"
    assert data["n_critical"] == 0
    assert "run_ts" in data
    assert "schema" in data
