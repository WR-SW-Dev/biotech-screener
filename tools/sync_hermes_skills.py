#!/usr/bin/env python3
"""Sync Cursor skills/ SKILL.md bodies into docs/hermes_skills/ mirrors.

Preserves YAML frontmatter on existing Hermes skill files. Injects Hermes-only
sections (e.g. Path C block in screener-ops) when the mirror has content absent
from the Cursor skill source.

Usage:
    python3 tools/sync_hermes_skills.py              # all mapped pairs
    python3 tools/sync_hermes_skills.py --dry-run
    python3 tools/sync_hermes_skills.py --only codegraph,screener_ops
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILLS = REPO / "skills"
HERMES = REPO / "docs" / "hermes_skills"
META = HERMES / "_meta.json"

# Cursor skill dir -> Hermes markdown filename
SKILL_MAP: dict[str, str] = {
    "screener_ops": "screener-ops.md",
    "codegraph": "codegraph.md",
    "catalyst_resolution": "catalyst-resolution.md",
    "clinical_scoring": "clinical-scoring.md",
    "financial_health": "financial-health.md",
    "institutional_signal": "institutional-signal.md",
    "selector_ranker": "selector-ranker.md",
    "ic_evaluation": "ic-evaluation.md",
    "memory_steward": "memory-steward.md",
    "validation": "validation.md",
    "spending_liquidity": "spending-liquidity.md",
    "sfo_liquidity_architecture": "sfo-liquidity-architecture.md",
    "self-improving": "self-improving.md",
    "pe_pacing": "pe-pacing.md",
    "openclaw-agent-optimize": "openclaw-agent-optimize.md",
}

# Sections kept from Hermes mirror when not present in skills/ source
HERMES_ONLY_SECTIONS: dict[str, list[str]] = {
    "screener-ops.md": [
        r"(## Path C Governance Monitoring[\s\S]*?)(?=\n---\n\n## Town-Hermes Bridge)",
    ],
}

# Hermes mirror is longer / authoritative — do not overwrite from skills/
HERMES_AUTHORITATIVE: set[str] = {
    "memory_steward",
}


def unescape_md(text: str) -> str:
    return text.replace("\\(", "(").replace("\\)", ")").replace("\\-", "-")


def split_frontmatter(text: str) -> tuple[str, str]:
    if not text.startswith("---"):
        return "", text
    end = text.find("\n---", 3)
    if end == -1:
        return "", text
    return text[: end + 4], text[end + 4 :].lstrip("\n")


def extract_hermes_only(hermes_body: str, filename: str) -> list[str]:
    blocks: list[str] = []
    for pattern in HERMES_ONLY_SECTIONS.get(filename, []):
        match = re.search(pattern, hermes_body)
        if match:
            blocks.append(match.group(1).strip())
    return blocks


def inject_after_host_authority(skill_body: str, blocks: list[str]) -> str:
    if not blocks:
        return skill_body
    marker = "**Standing rule:**"
    idx = skill_body.find(marker)
    if idx == -1:
        return skill_body + "\n\n---\n\n" + "\n\n---\n\n".join(blocks) + "\n"
    line_end = skill_body.find("\n", idx)
    insert_at = line_end + 1 if line_end != -1 else len(skill_body)
    injection = "\n---\n\n" + "\n\n---\n\n".join(blocks) + "\n\n"
    return skill_body[:insert_at] + injection + skill_body[insert_at:]


def sync_pair(skill_key: str, hermes_name: str, dry_run: bool) -> str:
    if skill_key in HERMES_AUTHORITATIVE:
        return f"SKIP {skill_key}: Hermes mirror authoritative"
    skill_path = SKILLS / skill_key / "SKILL.md"
    hermes_path = HERMES / hermes_name
    if not skill_path.exists():
        return f"SKIP {skill_key}: missing {skill_path}"
    skill_body = unescape_md(skill_path.read_text())
    frontmatter, old_body = split_frontmatter(hermes_path.read_text()) if hermes_path.exists() else ("", "")
    if not frontmatter:
        frontmatter = f"---\nname: {hermes_path.stem}\n---\n"
    only_blocks = extract_hermes_only(old_body, hermes_name) if old_body else []
    if only_blocks:
        skill_body = inject_after_host_authority(skill_body, only_blocks)
    new_text = frontmatter.rstrip() + "\n\n" + skill_body.lstrip()
    if hermes_path.exists() and hermes_path.read_text() == new_text:
        return f"OK   {skill_key}: already in sync"
    if dry_run:
        return f"DRY  {skill_key}: would update {hermes_path.name}"
    hermes_path.write_text(new_text)
    return f"SYNC {skill_key} -> {hermes_path.name}"


def update_meta(dry_run: bool) -> None:
    if not META.exists():
        return
    data = json.loads(META.read_text())
    data["last_updated"] = date.today().isoformat()
    if not dry_run:
        META.write_text(json.dumps(data, indent=2) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync skills/ to docs/hermes_skills/")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only", help="Comma-separated skill keys (e.g. codegraph,screener_ops)")
    args = parser.parse_args()
    keys = list(SKILL_MAP.keys())
    if args.only:
        keys = [k.strip() for k in args.only.split(",") if k.strip()]
    results = [sync_pair(k, SKILL_MAP[k], args.dry_run) for k in keys if k in SKILL_MAP]
    update_meta(args.dry_run)
    for line in results:
        print(line)
    synced = sum(1 for r in results if r.startswith("SYNC"))
    print(f"\nDone: {synced} updated, {len(results) - synced} unchanged/skipped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
