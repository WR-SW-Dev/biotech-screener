#!/usr/bin/env python3
"""Hermes skill canonical sync audit.

Detects drift between canonical skill sources (skills/), generated mirrors
(docs/hermes_skills/), and Hermes runtime skills (~/.hermes/skills/).

Hermes is the authority. docs/hermes_skills/ is the generated mirror.
Town is observer and reviewer only — never canonical.

Drift classes detected:
  RETIRED_CORRECTION_LEDGER        Retired Town Correction Ledger ref in skills/ (CRITICAL)
  RETIRED_CORRECTION_LEDGER_URI    Retired URI ref in skills/ (CRITICAL)
  SOURCE_MISSING                   Skill source file absent but mirror tracked (WARNING)
  MIRROR_MISSING                   Expected mirror absent for a tracked source (WARNING)
  MIRROR_CONTENT_MISMATCH          Source and mirror content diverged (INFO)
  FRONTMATTER_MISSING              Skill source file has no YAML frontmatter (WARNING)
  ORPHANED_MIRROR                  Mirror file exists but is not tracked by sync tool (INFO)

Modes:
  audit  — scan + report; exit 1 only on DRIFT_CRITICAL (default)
  check  — scan; exit 1 on any CRITICAL or WARNING drift
  sync   — scan; run sync_hermes_skills.py on mirror drift, then report

Usage:
    python3 tools/hermes_skill_sync_audit.py [--mode audit|check|sync]
                                              [--as-of-date YYYY-MM-DD]
                                              [--dry-run]
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import logging
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("hermes_skill_sync_audit")

SCHEMA_VERSION = "hermes_skill_sync_audit.v1"
AGENT_ID = "hermes-skill-sync-agent"

HEARTBEAT_PATH = REPO_ROOT / "artifacts" / "governance" / "hermes_skill_sync" / "latest_heartbeat.json"
REPORT_DIR = REPO_ROOT / "artifacts" / "governance" / "hermes_skill_sync"

# Patterns that must NOT appear in canonical skill sources after retirement
RETIRED_PATTERNS: list[tuple[str, str]] = [
    ("Town Correction Ledger", "RETIRED_CORRECTION_LEDGER"),
    (
        r"content://collections/self-improvement/correction-ledger",
        "RETIRED_CORRECTION_LEDGER_URI",
    ),
]

# Relative paths (from REPO_ROOT) exempt from retired-pattern scanning
# (e.g., historical log files where occurrence is expected and correct)
RETIRED_PATTERN_ALLOWLIST = frozenset(
    {
        "docs/hermes_skills/harvest_log.md",
    }
)

# Maximum mirror files regenerated per sync run (safety cap)
SYNC_DIFF_CAP = 3


@dataclass
class DriftItem:
    drift_class: str
    severity: str  # CRITICAL | WARNING | INFO
    file: str
    detail: str
    line: Optional[int] = None


@dataclass
class AuditResult:
    schema: str = SCHEMA_VERSION
    agent_id: str = AGENT_ID
    mode: str = "audit"
    as_of_date: str = ""
    run_ts: str = ""
    status: str = "OK"
    drift_items: List[DriftItem] = field(default_factory=list)
    n_critical: int = 0
    n_warning: int = 0
    n_info: int = 0
    skills_scanned: int = 0
    mirrors_scanned: int = 0
    sync_ran: bool = False
    sync_files_changed: List[str] = field(default_factory=list)
    error: Optional[str] = None


def _load_sync_maps() -> tuple[dict, dict, list, list]:
    """Load SKILL_MAP, REFERENCE_MAP, HERMES_SKILL, HERMES_NATIVE from sync_hermes_skills."""
    sync_path = REPO_ROOT / "tools" / "sync_hermes_skills.py"
    spec = importlib.util.spec_from_file_location("sync_hermes_skills", sync_path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return (
        getattr(mod, "SKILL_MAP", {}),
        getattr(mod, "REFERENCE_MAP", {}),
        getattr(mod, "HERMES_SKILL", []),
        getattr(mod, "HERMES_NATIVE", []),
    )


def _sha256_content(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _strip_frontmatter(text: str) -> str:
    """Remove opening YAML frontmatter block (--- ... ---) from text."""
    if not text.startswith("---"):
        return text
    end = text.find("\n---", 3)
    if end == -1:
        return text
    return text[end + 4 :].lstrip("\n")


def _has_frontmatter(text: str) -> bool:
    return text.startswith("---")


# ---------------------------------------------------------------------------
# Drift scanners
# ---------------------------------------------------------------------------


def scan_retired_patterns(skills_dir: Path, docs_dir: Path, repo_root: Optional[Path] = None) -> List[DriftItem]:
    """Scan skill sources and mirrors for retired references.

    Occurrences in skills/ (canonical sources) are CRITICAL.
    Occurrences in docs/hermes_skills/ (generated mirrors) are WARNING —
    they will be resolved by regenerating the mirror from the fixed source.
    Paths in RETIRED_PATTERN_ALLOWLIST are never scanned.
    """
    root = repo_root or REPO_ROOT
    items: List[DriftItem] = []
    scan_dirs = [skills_dir, docs_dir]
    for base_dir in scan_dirs:
        if not base_dir.exists():
            continue
        for md_file in sorted(base_dir.rglob("*.md")):
            try:
                rel = str(md_file.relative_to(root))
            except ValueError:
                rel = str(md_file)
            if rel in RETIRED_PATTERN_ALLOWLIST:
                continue
            try:
                text = md_file.read_text(encoding="utf-8")
            except OSError:
                continue
            for pattern, class_name in RETIRED_PATTERNS:
                for lineno, line in enumerate(text.splitlines(), 1):
                    if re.search(pattern, line):
                        severity = "CRITICAL" if md_file.is_relative_to(skills_dir) else "WARNING"
                        items.append(
                            DriftItem(
                                drift_class=class_name,
                                severity=severity,
                                file=rel,
                                detail=f"Retired reference: {line.strip()[:120]}",
                                line=lineno,
                            )
                        )
    return items


def _resolve_source_path(skill_key: str, mirror_name: str, ref_map: dict, skills_dir: Path) -> Optional[Path]:
    """Resolve canonical source file path from a SKILL_MAP or REFERENCE_MAP key.

    SKILL_MAP keys are directory names under skills/. REFERENCE_MAP entries use
    REFERENCE.md; everything else uses SKILL.md.
    """
    skill_dir = skills_dir / skill_key
    ref_values = set(ref_map.values())
    if mirror_name in ref_values:
        p = skill_dir / "REFERENCE.md"
    else:
        p = skill_dir / "SKILL.md"
        if not p.exists():
            p = skill_dir / "REFERENCE.md"
    return p if p.exists() else None


def scan_mirror_drift(
    skill_map: dict,
    ref_map: dict,
    skills_dir: Path,
    docs_dir: Path,
) -> List[DriftItem]:
    """Detect missing mirrors, missing sources, content mismatches, and missing frontmatter."""
    items: List[DriftItem] = []
    all_pairs = list(skill_map.items()) + list(ref_map.items())

    for source_key, mirror_name in all_pairs:
        source_path = _resolve_source_path(source_key, mirror_name, ref_map, skills_dir)
        mirror_path = docs_dir / mirror_name
        source_key_rel = f"skills/{source_key}/{'REFERENCE.md' if mirror_name in set(ref_map.values()) else 'SKILL.md'}"
        mirror_key = f"docs/hermes_skills/{mirror_name}"

        if source_path is None:
            items.append(
                DriftItem(
                    drift_class="SOURCE_MISSING",
                    severity="WARNING",
                    file=source_key_rel,
                    detail=f"Canonical source missing; mirror tracked at {mirror_key}",
                )
            )
            continue

        source_text = source_path.read_text(encoding="utf-8")

        if not _has_frontmatter(source_text):
            items.append(
                DriftItem(
                    drift_class="FRONTMATTER_MISSING",
                    severity="WARNING",
                    file=source_key_rel,
                    detail="Skill source file has no YAML frontmatter",
                )
            )

        if not mirror_path.exists():
            items.append(
                DriftItem(
                    drift_class="MIRROR_MISSING",
                    severity="WARNING",
                    file=mirror_key,
                    detail=f"Generated mirror missing; source at {source_key_rel}",
                )
            )
            continue

        mirror_text = mirror_path.read_text(encoding="utf-8")
        source_body = _strip_frontmatter(source_text)
        mirror_body = _strip_frontmatter(mirror_text)

        if _sha256_content(source_body) != _sha256_content(mirror_body):
            items.append(
                DriftItem(
                    drift_class="MIRROR_CONTENT_MISMATCH",
                    severity="INFO",
                    file=mirror_key,
                    detail=f"Mirror content differs from source {source_key_rel} — regeneration needed",
                )
            )

    return items


def scan_orphaned_mirrors(
    skill_map: dict,
    ref_map: dict,
    hermes_skill: dict,
    hermes_native: dict,
    docs_dir: Path,
) -> List[DriftItem]:
    """Find mirror .md files in docs/hermes_skills/ not tracked by any sync category.

    Checks SKILL_MAP, REFERENCE_MAP, HERMES_SKILL, and HERMES_NATIVE before
    flagging a file as orphaned.
    """
    items: List[DriftItem] = []
    # Bare filenames tracked by each category
    known_filenames = (
        set(skill_map.values())
        | set(ref_map.values())
        | {f"{k}.md" for k in hermes_skill}
        | {f"{k}.md" for k in hermes_native}
    )
    expected_filenames = {"_meta.json", "harvest_log.md"}
    if not docs_dir.exists():
        return items
    for md_file in sorted(docs_dir.glob("*.md")):
        if md_file.name not in known_filenames and md_file.name not in expected_filenames:
            rel = str(md_file.relative_to(REPO_ROOT))
            items.append(
                DriftItem(
                    drift_class="ORPHANED_MIRROR",
                    severity="INFO",
                    file=rel,
                    detail="Mirror file not tracked by SKILL_MAP, REFERENCE_MAP, HERMES_SKILL, or HERMES_NATIVE",
                )
            )
    return items


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def write_heartbeat(result: AuditResult) -> None:
    HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
    hb = {
        "agent_id": AGENT_ID,
        "run_ts": result.run_ts,
        "as_of_date": result.as_of_date,
        "status": result.status,
        "n_critical": result.n_critical,
        "n_warning": result.n_warning,
        "n_info": result.n_info,
        "skills_scanned": result.skills_scanned,
        "mirrors_scanned": result.mirrors_scanned,
        "sync_ran": result.sync_ran,
        "sync_files_changed": result.sync_files_changed,
        "schema": SCHEMA_VERSION,
    }
    HEARTBEAT_PATH.write_text(json.dumps(hb, indent=2), encoding="utf-8")
    logger.info("Heartbeat written: %s", HEARTBEAT_PATH)


def write_report(result: AuditResult, as_of_date: str) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    date_slug = as_of_date.replace("-", "_")
    report_path = REPORT_DIR / f"hermes_skill_sync_{date_slug}.md"

    lines = [
        f"# Hermes Skill Sync Audit — {as_of_date}",
        "",
        f"**Status:** {result.status}  ",
        f"**Run:** {result.run_ts}  ",
        f"**Mode:** {result.mode}  ",
        "",
        "## Summary",
        "",
        f"- Skills scanned: {result.skills_scanned}",
        f"- Mirrors scanned: {result.mirrors_scanned}",
        f"- Critical drift: {result.n_critical}",
        f"- Warnings: {result.n_warning}",
        f"- Info: {result.n_info}",
        f"- Sync ran: {'yes' if result.sync_ran else 'no'}",
        "",
    ]

    if result.drift_items:
        lines += ["## Drift Items", ""]
        for item in result.drift_items:
            loc = f" (line {item.line})" if item.line else ""
            lines.append(f"- **[{item.severity}]** `{item.drift_class}` — `{item.file}`{loc}")
            lines.append(f"  {item.detail}")
            lines.append("")
    else:
        lines += ["## Drift Items", "", "None detected.", ""]

    if result.sync_ran and result.sync_files_changed:
        lines += ["## Files Changed by Sync", ""]
        for f in result.sync_files_changed:
            lines.append(f"- `{f}`")
        lines.append("")

    if result.error:
        lines += ["## Error", "", f"```\n{result.error}\n```", ""]

    lines += [
        "---",
        "",
        "*Authority: `skills/` is canonical. `docs/hermes_skills/` is generated. Town is observer.*",
        f"*Agent: {AGENT_ID} | Schema: {SCHEMA_VERSION}*",
        "",
    ]

    report_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Report written: %s", report_path)
    return report_path


# ---------------------------------------------------------------------------
# Sync runner
# ---------------------------------------------------------------------------


def _run_sync_tool(dry_run: bool = False) -> list[str]:
    """Invoke sync_hermes_skills.py and return list of files it reported writing."""
    cmd = [sys.executable, str(REPO_ROOT / "tools" / "sync_hermes_skills.py")]
    if dry_run:
        cmd.append("--dry-run")
    logger.info("Running: %s", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
    if proc.returncode != 0:
        logger.error("sync_hermes_skills.py failed:\n%s", proc.stderr[:500])
        return []
    changed: list[str] = []
    for line in (proc.stdout + "\n" + proc.stderr).splitlines():
        for marker in ("Wrote ", "Updated "):
            if marker in line:
                changed.append(line.split(marker, 1)[1].strip())
                break
    logger.info("Sync reported %d file(s) written", len(changed))
    return changed


# ---------------------------------------------------------------------------
# Town notification
# ---------------------------------------------------------------------------


def notify_town(result: AuditResult, report_path: Optional[Path]) -> None:
    if result.n_critical == 0 and result.n_warning == 0:
        return
    try:
        from common.operator_delivery import send_operator_event  # type: ignore[import]
    except ImportError:
        logger.warning("Town notification unavailable (common.operator_delivery not importable)")
        return
    severity = "FAIL" if result.n_critical > 0 else "WARN"
    event_type = "hermes_skill_sync_failed" if result.n_critical > 0 else "hermes_skill_sync_drift"
    send_operator_event(
        channel="town",
        severity=severity,
        event_type=event_type,
        title=(f"Skill sync drift: {result.n_critical} critical, {result.n_warning} warnings"),
        summary=(
            f"Hermes skill sync guard detected {result.n_critical} CRITICAL and "
            f"{result.n_warning} WARNING drift items. "
            f"Status: {result.status}. Sync ran: {result.sync_ran}."
        ),
        artifact=str(report_path) if report_path else "",
        next_operator_action="investigate" if result.n_critical > 0 else "review",
        extra={
            "n_critical": result.n_critical,
            "n_warning": result.n_warning,
            "sync_ran": result.sync_ran,
        },
    )


# ---------------------------------------------------------------------------
# Core runner
# ---------------------------------------------------------------------------


def run_audit(mode: str, as_of_date: str, dry_run: bool = False) -> AuditResult:
    result = AuditResult(
        mode=mode,
        as_of_date=as_of_date,
        run_ts=datetime.now(timezone.utc).isoformat(),
    )

    skills_dir = REPO_ROOT / "skills"
    docs_dir = REPO_ROOT / "docs" / "hermes_skills"

    try:
        skill_map, ref_map, hermes_skill, hermes_native = _load_sync_maps()
    except Exception as exc:
        result.status = "ERROR"
        result.error = f"Failed to load sync maps from sync_hermes_skills.py: {exc}"
        logger.error(result.error)
        return result

    result.skills_scanned = sum(1 for _ in skills_dir.rglob("SKILL.md")) if skills_dir.exists() else 0
    result.mirrors_scanned = sum(1 for _ in docs_dir.glob("*.md")) if docs_dir.exists() else 0

    drift_items: list[DriftItem] = []
    drift_items.extend(scan_retired_patterns(skills_dir, docs_dir))
    drift_items.extend(scan_mirror_drift(skill_map, ref_map, skills_dir, docs_dir))
    drift_items.extend(scan_orphaned_mirrors(skill_map, ref_map, hermes_skill, hermes_native, docs_dir))

    result.drift_items = drift_items
    result.n_critical = sum(1 for d in drift_items if d.severity == "CRITICAL")
    result.n_warning = sum(1 for d in drift_items if d.severity == "WARNING")
    result.n_info = sum(1 for d in drift_items if d.severity == "INFO")

    if result.n_critical > 0:
        result.status = "DRIFT_CRITICAL"
    elif result.n_warning > 0:
        result.status = "DRIFT_WARNING"

    if mode == "sync" and (result.n_critical > 0 or result.n_warning > 0 or result.n_info > 0):
        mismatch_count = sum(1 for d in drift_items if d.drift_class == "MIRROR_CONTENT_MISMATCH")
        if mismatch_count > SYNC_DIFF_CAP:
            logger.warning(
                "Sync suppressed: %d mismatched files exceeds cap of %d. " "Run sync_hermes_skills.py manually.",
                mismatch_count,
                SYNC_DIFF_CAP,
            )
        else:
            changed = _run_sync_tool(dry_run=dry_run)
            result.sync_ran = True
            result.sync_files_changed = changed

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Hermes skill canonical sync audit")
    parser.add_argument(
        "--mode",
        choices=["audit", "check", "sync"],
        default="audit",
        help="audit=report only; check=exit 1 on drift; sync=report+regenerate mirrors",
    )
    parser.add_argument(
        "--as-of-date",
        default=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        help="Report date (default: today)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="In sync mode, do not write mirror files",
    )
    args = parser.parse_args()

    started = time.perf_counter()
    result = run_audit(args.mode, args.as_of_date, dry_run=args.dry_run)
    elapsed = time.perf_counter() - started

    write_heartbeat(result)
    report_path = write_report(result, args.as_of_date)

    logger.info(
        "Status: %s | CRITICAL=%d WARN=%d INFO=%d | %.1fs",
        result.status,
        result.n_critical,
        result.n_warning,
        result.n_info,
        elapsed,
    )

    for item in result.drift_items:
        loc = f":{item.line}" if item.line else ""
        logger.info(
            "[%s] %s — %s%s: %s",
            item.severity,
            item.drift_class,
            item.file,
            loc,
            item.detail[:80],
        )

    notify_town(result, report_path)

    if args.mode == "check" and (result.n_critical > 0 or result.n_warning > 0):
        sys.exit(1)
    elif result.status in ("DRIFT_CRITICAL", "ERROR"):
        sys.exit(1)


if __name__ == "__main__":
    main()
