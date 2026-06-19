#!/usr/bin/env python3
"""Audit Hermes skill coverage across skills/, docs/hermes_skills/, and _meta.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILLS = REPO / "skills"
HERMES = REPO / "docs" / "hermes_skills"
META = HERMES / "_meta.json"

sys.path.insert(0, str(REPO))
from tools.sync_hermes_skills import (  # noqa: E402
    HERMES_AUTHORITATIVE,
    HERMES_NATIVE,
    REFERENCE_MAP,
    SKILL_MAP,
    SOURCE_AUTHORITY_HERMES_AUTHORITATIVE,
    SOURCE_AUTHORITY_HERMES_NATIVE,
    all_sync_keys,
    sync_pair,
    source_authority_for,
)

SKIP_FILES = {"harvest_log.md", "SKILLS_REGISTRY.md"}
SKIP_PREFIXES = ("SKILLS_AUDIT_",)


def should_skip_hermes_doc(path: Path) -> bool:
    """Exclude operational reports that live beside Hermes skill docs."""
    return path.name in SKIP_FILES or (
        path.suffix == ".md" and path.name.startswith(SKIP_PREFIXES)
    )


def main() -> int:
    meta = json.loads(META.read_text()) if META.exists() else {"skills": {}}
    registered = set(meta.get("skills", {}))
    hermes_files = sorted(p for p in HERMES.glob("*.md") if not should_skip_hermes_doc(p))
    synced_targets = set(SKILL_MAP.values()) | set(REFERENCE_MAP.values())

    print("# Hermes Skills Audit\n")
    print(f"Hermes docs:     {len(hermes_files)}")
    print(f"_meta.json:      {len(registered)} registered")
    print(f"SKILL_MAP:       {len(SKILL_MAP)}")
    print(f"REFERENCE_MAP:   {len(REFERENCE_MAP)}")
    print(f"HERMES_NATIVE:   {len(HERMES_NATIVE)} (docs-only)")
    print()

    unreg = [p for p in hermes_files if p.stem not in registered]
    if unreg:
        print("## Unregistered in _meta.json")
        for p in unreg:
            tag = "cursor_sync" if p.name in synced_targets else "hermes_native"
            print(f"  {p.name:40} [{tag}]")
    else:
        print("## _meta.json: all Hermes .md files registered\n")

    print("\n## Missing Hermes file for registry key")
    for key in sorted(registered):
        fname = meta["skills"][key].get("file", f"{key}.md")
        if not (HERMES / fname).exists():
            print(f"  {key} -> {fname}")

    print("\n## skills/ without sync map")
    for d in sorted(SKILLS.iterdir()):
        if not d.is_dir() or d.name in ("self-improvement", "__pycache__"):
            continue
        if d.name in SKILL_MAP or d.name in REFERENCE_MAP:
            continue
        has = (d / "SKILL.md").exists() or (d / "REFERENCE.md").exists()
        print(f"  {d.name}/" + (" (has content)" if has else " (empty)"))

    print("\n## Authoritative (no skills/ overwrite)")
    for k in sorted(HERMES_AUTHORITATIVE):
        print(f"  {k}")

    print("\n## source_authority (_meta.json)")
    missing_auth = [
        key for key, entry in meta.get("skills", {}).items() if not entry.get("source_authority")
    ]
    if missing_auth:
        print("  MISSING source_authority:")
        for key in sorted(missing_auth):
            print(f"    {key}")
    else:
        print("  All registered skills have source_authority")

    print("\n## Mirror drift (cursor-synced skills only)")
    drift: list[str] = []
    reverse = {v: k for k, v in all_sync_keys().items()}
    for fname in sorted(synced_targets):
        skill_key = reverse.get(fname)
        if not skill_key or skill_key in HERMES_AUTHORITATIVE:
            continue
        authority = source_authority_for(Path(fname).stem, fname)
        if authority in (SOURCE_AUTHORITY_HERMES_NATIVE, SOURCE_AUTHORITY_HERMES_AUTHORITATIVE):
            continue
        result = sync_pair(skill_key, fname, dry_run=True)
        if result.startswith("DRY "):
            drift.append(f"  {fname}: hand-edited mirror? ({result})")
    if drift:
        for line in drift:
            print(line)
        print("  Fix: edit skills/ source and run python3 tools/sync_hermes_skills.py")
    else:
        print("  No drift detected (mirrors match skills/ sources)")

    print("\n## Commands")
    print("  See docs/hermes_agents/operator_host_skills.md for WSL ~/.hermes layout")
    print("  python3 tools/sync_hermes_skills.py --register-meta")
    print("  python3 tools/sync_hermes_skills.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
