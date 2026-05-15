#!/usr/bin/env python3
"""
Agent preflight state reporter.

Outputs current operational state before any agent work starts:
- git branch/status
- latest snapshot
- blocked/frozen specs
- contradictions
- active quarantines/freezes
- allowed next action
- not allowed

Usage:
  python tools/agent_preflight.py
  python tools/agent_preflight.py --agent fleet_steward
  python tools/agent_preflight.py --json
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def run_cmd(cmd, capture=True):
    """Run shell command; return output or None on error."""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=capture, text=True, timeout=5)
        return result.stdout.strip() if capture else result.returncode == 0
    except Exception:
        return None


def get_git_state():
    """Read git branch, status, and recent log."""
    branch = run_cmd("git rev-parse --abbrev-ref HEAD")
    head = run_cmd("git rev-parse --short HEAD")
    message = run_cmd("git log -1 --pretty=%B")
    is_clean = run_cmd("git status --short") == ""

    return {
        "branch": branch or "unknown",
        "head": head or "unknown",
        "message": (message or "unknown")[:100],
        "clean": is_clean,
        "state": (
            "on main, clean" if branch == "main" and is_clean else f"on {branch}, {'clean' if is_clean else 'dirty'}"
        ),
    }


def get_latest_snapshot():
    """Find and describe latest snapshot."""
    snapshots_dir = Path("data/snapshots")
    if not snapshots_dir.exists():
        return {"latest": None, "status": "unknown"}

    # Filter to date-based snapshots only (YYYY-MM-DD format)
    snapshots = [
        d
        for d in snapshots_dir.glob("*/")
        if d.is_dir() and len(d.name) == 10 and d.name[4] == "-" and d.name[7] == "-"
    ]
    snapshots = sorted(snapshots, reverse=True)
    if not snapshots:
        return {"latest": None, "status": "no snapshots"}

    latest = snapshots[0].name
    drift_report = snapshots[0] / "drift_report.md"

    if drift_report.exists():
        content = drift_report.read_text()
        if "**Status**: PASS" in content or "Status: PASS" in content:
            qa_status = "PASS"
        elif "**Status**: YELLOW" in content or "Status: YELLOW" in content:
            qa_status = "YELLOW"
        elif "**Status**: FAIL" in content or "Status: FAIL" in content:
            qa_status = "FAIL"
        else:
            qa_status = "unknown"
    else:
        qa_status = "unknown"

    return {"latest": latest, "qa_status": qa_status, "description": f"{latest}, QA {qa_status}"}


def load_agent_registry():
    """Load agents/AGENT_REGISTRY.json."""
    registry_file = Path("agents/AGENT_REGISTRY.json")
    if not registry_file.exists():
        return None

    try:
        return json.loads(registry_file.read_text())
    except Exception:
        return None


def get_blocked_specs():
    """Read blocked/frozen specs from operational memos."""
    blocked = []

    # Check operational closure memo
    closure_memos = list(Path("artifacts/audit").glob("operational_closure_*.md"))
    for memo in sorted(closure_memos, reverse=True)[:1]:
        try:
            content = memo.read_text()
            if "Spec 089" in content and "DEFERRED" in content:
                blocked.append("Spec 089 KG (deferred, pending cohort clearance)")
            if "Spec 100" in content and "BLOCKED" in content:
                blocked.append("Spec 100 (blocked by Spec 096 doctrine)")
            if "ranker/selector/sizing" in content and "FROZEN" in content:
                blocked.append("Ranker/selector/sizing work (frozen)")
        except Exception:
            pass

    return blocked or ["none"]


def get_contradictions():
    """Read contradiction ledger if available."""
    contradiction_file = Path("artifacts/ops/contradiction_ledger/latest.md")
    if not contradiction_file.exists():
        return []

    try:
        content = contradiction_file.read_text()
        # Simple parsing: look for contradiction markers
        lines = content.split("\n")
        contradictions = [line.strip() for line in lines if line.strip().startswith("-")]
        return contradictions[:5]  # Return top 5
    except Exception:
        return []


def get_quarantine_freeze():
    """Read 13F/cohort/architecture freeze status."""
    status = []

    # Check 13F cohort status
    cohort_memos = list(Path("artifacts/audit").glob("13f_cohort_status_*.md"))
    for memo in sorted(cohort_memos, reverse=True)[:1]:
        try:
            content = memo.read_text()
            if "STILL ACTIVE" in content:
                status.append("13F cohort quarantine: ACTIVE")
            if "NOT cleared" in content or "NOT CLEARED" in content:
                status.append("inst_delta_z distortion: NOT CLEARED")
        except Exception:
            pass

    # Check architecture freeze
    if Path("policies/policy_alpha_freeze_2026_04_04.md").exists():
        status.append("Architecture freeze: ACTIVE (until post-h20d 2026-05-26)")

    return status or ["none"]


def get_allowed_action():
    """Infer allowed next action based on current state."""
    git = get_git_state()
    blocked = get_blocked_specs()

    # Simple heuristics
    if git["branch"] != "main":
        return "Merge branch to main first"

    if "ranker/selector/sizing" in str(blocked):
        return "Monitor 13F filing ingest; audit forward shadow freshness; write governance docs"

    if "Spec 089" in str(blocked):
        return "Cannot start Spec 089 (deferred); can prepare: evening cron audit, preflight tool, registry metadata"

    return "Follow Phase 2 roadmap: finish preflight tool, audit evening cron, wait for 13F clearance (~May 23)"


def get_not_allowed():
    """List explicitly forbidden work."""
    return [
        "Ranker/selector/sizing changes (frozen during cohort quarantine)",
        "Spec 089 KG implementation (deferred pending cohort clearance)",
        "Spec 100 implementation (blocked by Spec 096 doctrine)",
        "Broad crontab edits without approval",
        "Production model promotion",
    ]


def build_preflight_report(
    git_state, snapshot, blocked, contradictions, quarantine, allowed, not_allowed, agent_registry=None, agent_name=None
):
    """Assemble preflight report."""
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "current_branch_state": git_state["state"],
        "latest_snapshot": snapshot["description"],
        "git_head": f"{git_state['head']} {git_state['message']}",
        "blocked_specs": blocked,
        "contradictions": contradictions,
        "active_quarantine_freeze": quarantine,
        "allowed_next_action": allowed,
        "not_allowed": not_allowed,
    }

    # Add agent metadata if requested
    if agent_name and agent_registry:
        agents = agent_registry.get("agents", {})
        if agent_name in agents:
            agent = agents[agent_name]
            report["agent_metadata"] = {
                "name": agent_name,
                "role": agent.get("role", "unknown"),
                "category": agent.get("category", "unknown"),
                "status": agent.get("status", "unknown"),
                "authority_level": agent.get("authority_level", "unknown"),
                "llm_policy": agent.get("llm_policy", "unknown"),
                "requires_preflight": agent.get("requires_preflight", True),
                "cadence": agent.get("cadence", "unknown"),
            }
        else:
            report["agent_metadata"] = {"error": f"Agent '{agent_name}' not found in registry"}

    return report


def format_report_text(report):
    """Format report as human-readable text."""
    lines = [
        "## Preflight Report",
        "",
        f"**Timestamp**: {report['timestamp']}",
        f"**Current branch state**: {report['current_branch_state']}",
        f"**Latest snapshot**: {report['latest_snapshot']}",
        f"**Git HEAD**: {report['git_head']}",
        "",
        "**Blocked/frozen specs**:",
    ]

    for spec in report["blocked_specs"]:
        lines.append(f"  - {spec}")

    lines.extend(
        [
            "",
            "**Contradictions**:",
        ]
    )

    if report["contradictions"]:
        for contra in report["contradictions"]:
            lines.append(f"  - {contra}")
    else:
        lines.append("  None detected")

    lines.extend(
        [
            "",
            "**Active quarantine/freeze**:",
        ]
    )

    for item in report["active_quarantine_freeze"]:
        lines.append(f"  - {item}")

    lines.extend(
        [
            "",
            "**Allowed next action**:",
            f"  {report['allowed_next_action']}",
            "",
            "**Not allowed**:",
        ]
    )

    for item in report["not_allowed"]:
        lines.append(f"  - {item}")

    if "agent_metadata" in report:
        lines.extend(
            [
                "",
                "**Agent metadata**:",
            ]
        )
        meta = report["agent_metadata"]
        if "error" not in meta:
            lines.append(f"  - name: {meta['name']}")
            lines.append(f"  - role: {meta['role']}")
            lines.append(f"  - authority_level: {meta['authority_level']}")
            lines.append(f"  - llm_policy: {meta['llm_policy']}")
            lines.append(f"  - requires_preflight: {meta['requires_preflight']}")
            lines.append(f"  - status: {meta['status']}")
        else:
            lines.append(f"  {meta['error']}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Report current operational state before agent work")
    parser.add_argument("--agent", type=str, help="Optional: agent name to include metadata for")
    parser.add_argument("--json", action="store_true", help="Output as JSON instead of text")

    args = parser.parse_args()

    # Load state
    git = get_git_state()
    snapshot = get_latest_snapshot()
    blocked = get_blocked_specs()
    contradictions = get_contradictions()
    quarantine = get_quarantine_freeze()
    allowed = get_allowed_action()
    not_allowed = get_not_allowed()
    registry = load_agent_registry()

    # Build report
    report = build_preflight_report(
        git,
        snapshot,
        blocked,
        contradictions,
        quarantine,
        allowed,
        not_allowed,
        agent_registry=registry,
        agent_name=args.agent,
    )

    # Output
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(format_report_text(report))

    return 0


if __name__ == "__main__":
    sys.exit(main())
