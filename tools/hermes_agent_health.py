#!/usr/bin/env python3
"""Hermes agent health board.

Reads AGENT_REGISTRY.json and every latest_heartbeat.json to produce a
one-page fleet health report.

Usage:
    python3 tools/hermes_agent_health.py                  # --mode report (default)
    python3 tools/hermes_agent_health.py --mode report
    python3 tools/hermes_agent_health.py --mode json
    python3 tools/hermes_agent_health.py --mode check     # exit 1 on RED verdict

Exit codes (--mode check):
    0 = GREEN
    1 = AMBER or RED
    2 = error reading registry/heartbeats
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.artifact_freshness import age_days, newest_artifact_freshness  # noqa: E402

REGISTRY_PATH = REPO_ROOT / "agents" / "AGENT_REGISTRY.json"
GOVERNANCE_DIR = REPO_ROOT / "artifacts" / "governance"

AUTHORITY_TO_TIER: dict[str, int] = {
    "observe_only": 0,
    "observe_and_propose": 1,
    "write_artifacts": 2,
    "mutate_data": 3,
    "mutate_config": 4,
}

STALENESS_WARN: dict[str, int] = {
    "daily_after_production": 2,
    "daily_premarket": 2,
    "intraday": 1,
    "weekly": 8,
}
STALENESS_FAIL: dict[str, int] = {
    "daily_after_production": 3,
    "daily_premarket": 3,
    "intraday": 2,
    "weekly": 10,
}

STATUS_RANK = {"RED": 3, "AMBER": 2, "GREEN": 1, "UNKNOWN": 0}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


class AgentRow:
    def __init__(
        self,
        agent_id: str,
        role: str,
        status: str,
        cadence: str,
        authority_level: str,
        supervised: bool,
        heartbeat: dict | None,
        artifact_paths: list[str] | None = None,
    ):
        self.agent_id = agent_id
        self.role = role
        self.status = status
        self.cadence = cadence
        self.authority_level = authority_level
        self.tier = AUTHORITY_TO_TIER.get(authority_level, -1)
        self.supervised = supervised
        self.heartbeat = heartbeat
        self.artifact_paths = artifact_paths or []
        self.health_status = self._compute_health()
        self.detail = self._compute_detail()

    def _snapshot_age(self) -> tuple[int | None, str]:
        """Fast qa check: walk back from today to find the most recent dated snapshot dir.

        Uses only Path.is_dir() calls (no rglob) so it stays fast on WSL/NTFS.
        """
        snap_base = REPO_ROOT / "data" / "snapshots"
        if not snap_base.is_dir():
            return None, "NO_SNAPSHOTS_DIR"
        today = date.today()
        for delta in range(15):
            d = today - timedelta(days=delta)
            if (snap_base / d.strftime("%Y-%m-%d")).is_dir():
                return delta, f"snapshot {d} exists ({delta}d ago)"
        return None, "NO_RECENT_SNAPSHOT (>14d)"

    def _artifact_age(self) -> tuple[int | None, str]:
        """Return (age_in_days, detail_str) from artifact_paths freshness, or (None, reason)."""
        if not self.artifact_paths:
            return None, "no artifact_paths"
        newest, sample, method = newest_artifact_freshness(REPO_ROOT, self.artifact_paths)
        if newest is None:
            return None, "NO_ARTIFACTS"
        today = date.today()
        a = age_days(today, newest)
        if a < 0:
            # Future-dated files (e.g. resolution data) are spurious — treat as fresh.
            label = sample.relative_to(REPO_ROOT) if sample else "?"
            return 0, f"artifact 0d ago [future-date clamped: {label}]"
        label = sample.relative_to(REPO_ROOT) if sample else "?"
        return a, f"artifact {a}d ago [{method}] {label}"

    def _compute_health(self) -> str:
        if self.status in ("deprecated", "suppressed") or not self.supervised:
            return "SKIP"

        # on_demand agents: skip if no heartbeat (no regular cadence)
        if self.cadence in ("on_demand", "unknown"):
            if self.heartbeat is None:
                return "SKIP"

        hb = self.heartbeat
        if hb is None:
            # Fallback: snapshot-dir check for qa; artifact-based for all others
            a, _ = self._snapshot_age() if self.agent_id == "qa" else self._artifact_age()
            if a is None:
                return "RED"
            fail_thresh = STALENESS_FAIL.get(self.cadence)
            warn_thresh = STALENESS_WARN.get(self.cadence)
            if fail_thresh and a > fail_thresh:
                return "RED"
            if warn_thresh and a > warn_thresh:
                return "AMBER"
            return "GREEN"

        run_ts_str = hb.get("run_ts")
        if run_ts_str:
            try:
                run_ts = datetime.fromisoformat(run_ts_str)
                hb_age = (datetime.now(timezone.utc) - run_ts).days
                warn_thresh = STALENESS_WARN.get(self.cadence)
                fail_thresh = STALENESS_FAIL.get(self.cadence)
                if fail_thresh and hb_age > fail_thresh:
                    return "RED"
                if warn_thresh and hb_age > warn_thresh:
                    return "AMBER"
            except ValueError:
                return "RED"

        hb_status = hb.get("status", "")
        n_critical = hb.get("n_critical", 0)
        n_warning = hb.get("n_warning", 0)

        if hb_status in ("FAIL", "ERROR", "DRIFT_CRITICAL") or n_critical > 0:
            return "RED"
        if hb_status in ("WARN", "DRIFT_WARNING") or n_warning > 0:
            return "AMBER"
        if hb_status in ("OK", "SKIP", "DRIFT_INFO"):
            return "GREEN"

        return "UNKNOWN"

    def _compute_detail(self) -> str:
        if self.health_status == "SKIP":
            return self.status

        hb = self.heartbeat
        if hb is None:
            if self.agent_id == "qa":
                _, detail = self._snapshot_age()
            else:
                _, detail = self._artifact_age()
            return detail

        run_ts_str = hb.get("run_ts", "")
        age_str = ""
        if run_ts_str:
            try:
                run_ts = datetime.fromisoformat(run_ts_str)
                hb_age = (datetime.now(timezone.utc) - run_ts).days
                age_str = f"{hb_age}d ago"
            except ValueError:
                age_str = "invalid_ts"

        hb_status = hb.get("status", "?")
        n_c = hb.get("n_critical", 0)
        n_w = hb.get("n_warning", 0)
        parts = [f"hb:{hb_status}"]
        if age_str:
            parts.append(age_str)
        if n_c:
            parts.append(f"critical={n_c}")
        if n_w:
            parts.append(f"warn={n_w}")
        return " | ".join(parts)


def load_heartbeat(agent_id: str) -> dict | None:
    # Normalise agent_id to snake_case for dir lookup
    agent_snake = agent_id.replace("-", "_")
    candidates = [
        GOVERNANCE_DIR / agent_id / "latest_heartbeat.json",
        GOVERNANCE_DIR / agent_snake / "latest_heartbeat.json",
        # hermes_skill_sync special dir
        (
            GOVERNANCE_DIR / "hermes_skill_sync" / "latest_heartbeat.json"
            if agent_id == "hermes-skill-sync-agent"
            else None
        ),
    ]
    for path in candidates:
        if path and path.exists():
            try:
                return json.loads(path.read_text())
            except Exception:
                return None
    return None


def load_registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text())


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


HEALTH_SYMBOL = {"GREEN": "✓", "AMBER": "⚠", "RED": "✗", "SKIP": "–", "UNKNOWN": "?"}


def build_rows(registry: dict) -> list[AgentRow]:
    rows = []
    for agent_id, entry in registry.get("agents", {}).items():
        hb = load_heartbeat(agent_id)
        row = AgentRow(
            agent_id=agent_id,
            role=entry.get("role", ""),
            status=entry.get("status", "active"),
            cadence=entry.get("cadence", "unknown"),
            authority_level=entry.get("authority_level", "observe_only"),
            supervised=entry.get("supervised_by_orchestrator", False),
            heartbeat=hb,
            artifact_paths=entry.get("artifact_paths", []),
        )
        rows.append(row)
    return rows


def fleet_verdict(rows: list[AgentRow]) -> str:
    worst = "GREEN"
    for row in rows:
        if row.health_status in ("RED", "AMBER") and STATUS_RANK.get(row.health_status, 0) > STATUS_RANK.get(worst, 0):
            worst = row.health_status
    return worst


def report_text(rows: list[AgentRow], registry: dict) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    verdict = fleet_verdict(rows)

    lines = [
        f"# Hermes Fleet Health — {now}",
        f"Fleet verdict: **{verdict}**",
        f"Registry as_of: {registry.get('as_of', '?')}",
        "",
    ]

    # Supervised active agents
    active = [r for r in rows if r.health_status != "SKIP"]
    skipped = [r for r in rows if r.health_status == "SKIP"]

    lines.append(f"## Active + Supervised ({len(active)} agents)")
    lines.append("")
    col_w = max((len(r.agent_id) for r in active), default=20)
    lines.append(f"  {'Status':<6}  {'Agent':<{col_w}}  {'T'}  {'Cadence':<25}  {'Detail'}")
    lines.append(f"  {'------':<6}  {'-'*col_w}  {'-'}  {'-'*25}  ------")

    for row in sorted(active, key=lambda r: (-STATUS_RANK.get(r.health_status, 0), r.agent_id)):
        sym = HEALTH_SYMBOL.get(row.health_status, "?")
        lines.append(
            f"  {sym} {row.health_status:<5}  {row.agent_id:<{col_w}}  {row.tier}  {row.cadence:<25}  {row.detail}"
        )

    lines.append("")
    lines.append(f"## Skipped ({len(skipped)} agents — suppressed/deprecated/opted-out)")
    for row in sorted(skipped, key=lambda r: r.agent_id):
        lines.append(f"  – {row.agent_id:<{col_w}}  {row.status}")

    # Summary
    n_red = sum(1 for r in active if r.health_status == "RED")
    n_amber = sum(1 for r in active if r.health_status == "AMBER")
    n_green = sum(1 for r in active if r.health_status == "GREEN")
    lines.append("")
    lines.append("## Summary")
    lines.append(f"  GREEN={n_green}  AMBER={n_amber}  RED={n_red}  SKIP={len(skipped)}")
    return "\n".join(lines)


def report_json(rows: list[AgentRow], registry: dict) -> dict:
    verdict = fleet_verdict(rows)
    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "registry_as_of": registry.get("as_of", ""),
        "fleet_verdict": verdict,
        "agents": [
            {
                "agent_id": r.agent_id,
                "health_status": r.health_status,
                "registry_status": r.status,
                "cadence": r.cadence,
                "authority_level": r.authority_level,
                "tier": r.tier,
                "supervised": r.supervised,
                "detail": r.detail,
            }
            for r in rows
        ],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Hermes fleet health board")
    parser.add_argument(
        "--mode",
        choices=["report", "json", "check"],
        default="report",
        help="Output mode (default: report)",
    )
    args = parser.parse_args()

    try:
        registry = load_registry()
    except Exception as exc:
        print(f"ERROR loading registry: {exc}", file=sys.stderr)
        return 2

    rows = build_rows(registry)

    if args.mode == "json":
        print(json.dumps(report_json(rows, registry), indent=2))
        return 0

    if args.mode == "check":
        verdict = fleet_verdict(rows)
        print(f"Fleet verdict: {verdict}")
        return 0 if verdict == "GREEN" else 1

    # Default: report
    print(report_text(rows, registry))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
