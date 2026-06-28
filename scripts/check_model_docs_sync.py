#!/usr/bin/env python3
"""Guard: model-affecting changes must ship with a documentation update.

Rationale (item #10): the model is hash-locked and governed. When a commit
touches scoring / ranking / selection / sizing / ruleset / model-weight files,
it MUST also touch a documentation or changelog artifact so the change is
recorded where reviewers and the docs/skills sync expect it. This is the
"fast-but-not-misleading" guard — it does not let a silent model-affecting
diff land without a paper trail.

Usage:
    # Pre-commit (default): check the staged index
    python scripts/check_model_docs_sync.py

    # CI / review: check a commit range against a base ref
    python scripts/check_model_docs_sync.py --base origin/main

Exit codes:
    0 — no model-affecting change, OR a doc update accompanies it, OR overridden
    1 — model-affecting change with no doc update and no override

Override (use sparingly, with justification in the commit body):
    ALLOW_MODEL_DOCS_SKIP=1 git commit ...
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

# Files whose change alters model behaviour (scoring, ranking, selection,
# sizing, ruleset, or the locked model weights). Matched against repo-relative
# POSIX paths.
MODEL_AFFECTING = [
    r"^decision_engine\.py$",
    r"^ranker_engine\.py$",
    r"^ranker_v2_pairwise\.py$",
    r"^selector_engine\.py$",
    r"^pos_engine\.py$",
    r"^pos_model_v2\.py$",
    r"^regime_engine\.py$",
    r"^module_\d+_.*\.py$",
    r"^module_5_composite.*\.py$",
    r"^module_5_scoring.*\.py$",
    r"^pit_enforcement\.py$",
    r"^pit_financials\.py$",
    r"^production_data/ranker_v2_model.*\.json$",
    r"^production_data/module5_weights.*\.json$",
    r"^production_data/decision_rulesets/.*\.json$",
]

# A change to any of these counts as the required documentation update.
DOC_SATISFYING = [
    r"^model_documentation\.md$",
    r".*CHANGELOG.*\.md$",
    r"^RULESET_CHANGELOG\.md$",
    r"^GOVERNANCE\.md$",
    r"^docs/.*",
    r"^specs/.*",
    r"^skills/.*",
    r".*\.claude/skills/.*",
]

_MODEL_RE = [re.compile(p) for p in MODEL_AFFECTING]
_DOC_RE = [re.compile(p) for p in DOC_SATISFYING]


def _changed_files(base: str | None) -> list[str]:
    """Return changed files: staged index (default) or diff vs base ref."""
    if base:
        cmd = ["git", "diff", "--name-only", f"{base}...HEAD"]
    else:
        cmd = ["git", "diff", "--cached", "--name-only"]
    out = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]


def _matches(path: str, patterns: list[re.Pattern]) -> bool:
    return any(p.search(path) for p in patterns)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Require docs update for model-affecting changes.")
    parser.add_argument("--base", default=None, help="Base ref to diff against (CI mode). Default: staged index.")
    args = parser.parse_args(argv)

    changed = _changed_files(args.base)
    model_files = [f for f in changed if _matches(f, _MODEL_RE)]
    if not model_files:
        return 0  # nothing model-affecting — fast pass

    doc_files = [f for f in changed if _matches(f, _DOC_RE)]
    if doc_files:
        print(f"[model-docs-sync] OK — {len(model_files)} model file(s) accompanied by doc update: {doc_files[:3]}")
        return 0

    if os.environ.get("ALLOW_MODEL_DOCS_SKIP") == "1":
        print(
            "[model-docs-sync] OVERRIDE (ALLOW_MODEL_DOCS_SKIP=1) — model-affecting change "
            "committed WITHOUT a doc update. Ensure the rationale is in the commit body.",
            file=sys.stderr,
        )
        return 0

    print(
        "[model-docs-sync] BLOCKED: model-affecting files changed with no documentation update.\n"
        "  Model-affecting files:\n    " + "\n    ".join(model_files) + "\n"
        "  Add a doc/changelog update (one of: model_documentation.md, RULESET_CHANGELOG.md,\n"
        "  CHANGELOG.md, GOVERNANCE.md, docs/, specs/, or skills/), then re-commit.\n"
        "  To override with justification: ALLOW_MODEL_DOCS_SKIP=1 git commit ...",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
