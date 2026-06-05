#!/usr/bin/env python3
"""Read-only audit of .learnings/ for recursive self-improvement hygiene.

Reports tier line counts, Pattern-Key recurrence, promotion candidates, and
simple stale hints. Does not modify any file.

Usage:
    python3 tools/audit_learnings.py
    python3 tools/audit_learnings.py --json
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LEARNINGS = REPO / ".learnings"
ENV_JSON = REPO / ".cursor" / "environment.json"

TIER_LIMITS = {
    "memory.md": 100,
    "projects/biotech_screener.md": 200,
}

LRN_HEADING = re.compile(r"^## \[(LRN-\d{8}-\d{3})\]", re.MULTILINE)
META_LINE = re.compile(r"^- (Pattern-Key|Recurrence-Count|Skill-Path|Status):\s*(.+)$", re.MULTILINE)
STATUS_LINE = re.compile(r"^\*\*Status\*\*:\s*(\w+)", re.MULTILINE)


@dataclass
class LrnEntry:
    lrn_id: str
    status: str = "unknown"
    pattern_key: str | None = None
    recurrence_count: int = 0
    skill_path: str | None = None


@dataclass
class AuditReport:
    tier_lines: dict[str, dict] = field(default_factory=dict)
    lrn_total: int = 0
    pattern_groups: dict[str, list[str]] = field(default_factory=dict)
    promotion_candidates: list[dict] = field(default_factory=list)
    skill_candidates: list[dict] = field(default_factory=list)
    stale_hints: list[str] = field(default_factory=list)
    domain_files: list[str] = field(default_factory=list)


def _line_count(path: Path) -> int:
    if not path.exists():
        return 0
    return len(path.read_text(encoding="utf-8").splitlines())


def parse_learnings(text: str) -> list[LrnEntry]:
    entries: list[LrnEntry] = []
    parts = LRN_HEADING.split(text)
    # parts[0] is preamble; then alternating id, body
    i = 1
    while i + 1 < len(parts):
        lrn_id = parts[i].strip()
        body = parts[i + 1]
        entry = LrnEntry(lrn_id=lrn_id)
        status_m = STATUS_LINE.search(body)
        if status_m:
            entry.status = status_m.group(1).lower()
        for key, val in META_LINE.findall(body):
            val = val.strip()
            if key == "Pattern-Key":
                entry.pattern_key = val
            elif key == "Recurrence-Count":
                try:
                    entry.recurrence_count = int(val)
                except ValueError:
                    pass
            elif key == "Skill-Path":
                entry.skill_path = val
            elif key == "Status":
                entry.status = val.lower()
        entries.append(entry)
        i += 2
    return entries


def _codegraph_pin() -> str | None:
    if not ENV_JSON.exists():
        return None
    m = re.search(r"codegraph@([\d.]+)", ENV_JSON.read_text(encoding="utf-8"))
    return m.group(1) if m else None


def build_report() -> AuditReport:
    report = AuditReport()

    for rel, limit in TIER_LIMITS.items():
        path = LEARNINGS / rel
        n = _line_count(path)
        report.tier_lines[rel] = {
            "lines": n,
            "limit": limit,
            "over": max(0, n - limit),
            "exists": path.exists(),
        }

    domains = LEARNINGS / "domains"
    if domains.is_dir():
        report.domain_files = sorted(p.name for p in domains.glob("*.md"))

    learnings_path = LEARNINGS / "LEARNINGS.md"
    if not learnings_path.exists():
        report.stale_hints.append("Missing .learnings/LEARNINGS.md")
        return report

    entries = parse_learnings(learnings_path.read_text(encoding="utf-8"))
    report.lrn_total = len(entries)

    by_pattern: dict[str, list[LrnEntry]] = defaultdict(list)
    for e in entries:
        if e.pattern_key:
            by_pattern[e.pattern_key].append(e)
            report.pattern_groups.setdefault(e.pattern_key, []).append(e.lrn_id)

    for pattern, group in sorted(by_pattern.items()):
        total_rec = sum(e.recurrence_count for e in group)
        pending = [e for e in group if e.status in ("pending", "unknown")]
        if total_rec >= 3 and pending:
            report.promotion_candidates.append(
                {
                    "pattern_key": pattern,
                    "total_recurrence": total_rec,
                    "pending_lrns": [e.lrn_id for e in pending],
                    "action": "promote to memory.md or projects/biotech_screener.md",
                }
            )
        for e in group:
            if e.skill_path and e.status in ("pending", "resolved") and e.recurrence_count >= 2:
                report.skill_candidates.append(
                    {
                        "lrn_id": e.lrn_id,
                        "pattern_key": pattern,
                        "skill_path": e.skill_path,
                        "status": e.status,
                    }
                )

    pin = _codegraph_pin()
    memory_text = (LEARNINGS / "memory.md").read_text(encoding="utf-8") if (LEARNINGS / "memory.md").exists() else ""
    if pin and pin not in memory_text and "codegraph" in memory_text.lower():
        report.stale_hints.append(
            f"memory.md may stale-pin codegraph; environment.json has @{pin}"
        )
    if "pytest-xdist" in memory_text.lower() and "not required" not in memory_text.lower():
        report.stale_hints.append("memory.md: verify pytest-xdist guidance (see LRN-20260528-002)")

    return report


def print_report(report: AuditReport) -> None:
    print("# Learnings Audit\n")
    print("## Tier line counts\n")
    for rel, info in report.tier_lines.items():
        flag = " OVER LIMIT" if info.get("over", 0) > 0 else ""
        print(f"- `{rel}`: {info['lines']}/{info['limit']} lines{flag}")
    if report.domain_files:
        print(f"\nDomain files: {', '.join(report.domain_files)}")
    print(f"\n## LEARNINGS.md\n- Entries: {report.lrn_total}")
    print(f"- Distinct Pattern-Keys: {len(report.pattern_groups)}")

    print("\n## Promotion candidates (Pattern-Key ≥3 recurrence, still pending)\n")
    if not report.promotion_candidates:
        print("None.")
    else:
        for c in report.promotion_candidates:
            print(f"- `{c['pattern_key']}` (rec={c['total_recurrence']}): {', '.join(c['pending_lrns'])}")

    print("\n## Skill-patch candidates (Skill-Path + recurrence ≥2)\n")
    if not report.skill_candidates:
        print("None.")
    else:
        for c in report.skill_candidates[:15]:
            print(f"- {c['lrn_id']} → skills/{c['skill_path']}/ ({c['status']})")
        if len(report.skill_candidates) > 15:
            print(f"  ... and {len(report.skill_candidates) - 15} more")

    print("\n## Stale hints\n")
    if not report.stale_hints:
        print("None.")
    else:
        for h in report.stale_hints:
            print(f"- {h}")

    print("\n## Commands")
    print("  python3 tools/build_hermes_knowledge_layer.py  # ops ledgers")
    print("  See .learnings/README.md for full knowledge stack")


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit .learnings/ for recursion hygiene")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of markdown")
    args = parser.parse_args()

    report = build_report()
    if args.json:
        print(json.dumps(asdict(report), indent=2, sort_keys=True))
    else:
        print_report(report)

    over = any(t.get("over", 0) > 0 for t in report.tier_lines.values())
    return 1 if over else 0


if __name__ == "__main__":
    raise SystemExit(main())
