#!/usr/bin/env python3
"""IC Health Memory Hygiene — Detect stale-memory/artifact mismatches.

Phase 1 Priority 5: Observability logging for IC health state consistency.

Compares memory documentation (what we think is happening) vs artifacts (what
actually happened) to detect stale memory, missing artifacts, or state drift.

This is pure observability — logs mismatches for operator investigation but
does NOT take corrective action.

Usage:
    python3 tools/ic_health_memory_hygiene.py --as-of-date 2026-06-03
    python3 tools/ic_health_memory_hygiene.py --check-latest
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = PROJECT_ROOT / "agents"
IC_HEALTH_AGENT = AGENTS_DIR / "ic_health_monitor"
IC_MEMORY_DIR = IC_HEALTH_AGENT / "memory"
IC_ARTIFACTS_DIR = PROJECT_ROOT / "artifacts" / "ic_dashboard"
HYGIENE_LOG_PATH = PROJECT_ROOT / "artifacts" / "audit" / "ic_memory_hygiene.jsonl"


class MemoryHygieneChecker:
    """Detects inconsistencies between IC health memory and artifacts."""

    def __init__(self):
        """Initialize checker."""
        HYGIENE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    def check_as_of_date(self, as_of_date: date) -> dict[str, Any]:
        """Check memory hygiene for a specific date.

        Args:
            as_of_date: The snapshot/analysis date (YYYY-MM-DD)

        Returns:
            Report dict with findings
        """
        date_str = as_of_date.strftime("%Y-%m-%d")
        issues = []
        warnings = []

        # Check 1: Artifact existence
        artifact_path = IC_ARTIFACTS_DIR / f"{date_str}_dashboard.json"
        has_artifact = artifact_path.exists()

        if not has_artifact:
            issues.append(
                {
                    "type": "MISSING_ARTIFACT",
                    "severity": "WARN",
                    "date": date_str,
                    "description": f"No dashboard artifact for {date_str}",
                    "artifact_path": str(artifact_path),
                }
            )

        # Check 2: Artifact validity (if exists)
        artifact_content = None
        if has_artifact:
            try:
                with open(artifact_path) as f:
                    artifact_content = json.load(f)
            except json.JSONDecodeError:
                issues.append(
                    {
                        "type": "CORRUPT_ARTIFACT",
                        "severity": "ERROR",
                        "date": date_str,
                        "description": "Dashboard artifact is corrupted (invalid JSON)",
                        "artifact_path": str(artifact_path),
                    }
                )
                artifact_content = None

        # Check 3: Memory freshness
        latest_memory = self._get_latest_memory_file()
        if latest_memory:
            memory_date = latest_memory.stem  # filename YYYY-MM-DD
            memory_age = (as_of_date - self._parse_date(memory_date)).days
            if memory_age > 3:
                warnings.append(
                    {
                        "type": "STALE_MEMORY",
                        "severity": "WARN",
                        "date": date_str,
                        "description": f"Memory last updated {memory_age} days ago (file: {memory_date})",
                        "memory_file": latest_memory.name,
                        "memory_age_days": memory_age,
                    }
                )

        # Check 4: Memory content vs artifact state
        if latest_memory and artifact_content:
            memory_content = latest_memory.read_text()
            artifact_attention = artifact_content.get("attention", "UNKNOWN")

            # Look for claimed state in memory
            memory_has_alert_claim = (
                "ALERT" in memory_content or "CRITICAL" in memory_content or "alert" in memory_content.lower()
            )
            artifact_has_alert = artifact_attention in ("ALERT", "CRITICAL")

            if memory_has_alert_claim and not artifact_has_alert:
                warnings.append(
                    {
                        "type": "MEMORY_OVERSTATES_ISSUES",
                        "severity": "INFO",
                        "date": date_str,
                        "description": "Memory claims issues but artifact is healthy",
                        "memory_file": latest_memory.name,
                        "artifact_attention": artifact_attention,
                    }
                )
            elif not memory_has_alert_claim and artifact_has_alert:
                warnings.append(
                    {
                        "type": "ARTIFACT_ISSUES_UNDOCUMENTED",
                        "severity": "WARN",
                        "date": date_str,
                        "description": f"Artifact shows {artifact_attention} but memory doesn't document it",
                        "memory_file": latest_memory.name,
                        "artifact_attention": artifact_attention,
                    }
                )

        # Check 5: Signal freshness in artifact
        if artifact_content:
            signals = artifact_content.get("signals", {})
            generated_at = artifact_content.get("generated_at")
            if generated_at:
                try:
                    gen_time = datetime.fromisoformat(generated_at)
                    artifact_age_hours = (datetime.now(gen_time.tzinfo) - gen_time).total_seconds() / 3600
                    if artifact_age_hours > 48:
                        warnings.append(
                            {
                                "type": "STALE_ARTIFACT",
                                "severity": "WARN",
                                "date": date_str,
                                "description": f"Dashboard generated {artifact_age_hours:.1f} hours ago",
                                "generated_at": generated_at,
                                "age_hours": artifact_age_hours,
                            }
                        )
                except (ValueError, TypeError):
                    pass

            # Check for CRITICAL signals not warned about in memory
            critical_signals = [
                sig for sig, data in signals.items() if isinstance(data, dict) and data.get("health") == "CRITICAL"
            ]
            if critical_signals and latest_memory:
                memory_content = latest_memory.read_text()
                for sig in critical_signals:
                    if sig.upper() not in memory_content.upper():
                        warnings.append(
                            {
                                "type": "CRITICAL_SIGNAL_NOT_DOCUMENTED",
                                "severity": "WARN",
                                "date": date_str,
                                "description": f"Artifact has CRITICAL signal {sig} but memory doesn't mention it",
                                "signal": sig,
                                "memory_file": latest_memory.name,
                            }
                        )

        return {
            "analysis_date": date_str,
            "check_timestamp": datetime.now().isoformat(),
            "has_artifact": has_artifact,
            "has_memory": latest_memory is not None,
            "artifact_path": str(artifact_path),
            "memory_file": latest_memory.name if latest_memory else None,
            "issues": issues,
            "warnings": warnings,
            "summary": self._summarize(issues, warnings),
        }

    def _get_latest_memory_file(self) -> Optional[Path]:
        """Get the most recent memory file for ic_health_monitor."""
        if not IC_MEMORY_DIR.exists():
            return None
        memory_files = sorted(IC_MEMORY_DIR.glob("*.md"), reverse=True)
        return memory_files[0] if memory_files else None

    def _parse_date(self, date_str: str) -> date:
        """Parse YYYY-MM-DD string to date object."""
        try:
            return datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return date.today()

    def _summarize(self, issues: list, warnings: list) -> dict[str, Any]:
        """Summarize findings."""
        return {
            "issue_count": len(issues),
            "warning_count": len(warnings),
            "status": "HEALTHY" if not issues else "ISSUES_DETECTED",
            "requires_investigation": len(issues) > 0,
        }

    def log_findings(self, report: dict[str, Any]) -> None:
        """Log findings to JSONL file for operator review."""
        with open(HYGIENE_LOG_PATH, "a") as f:
            f.write(json.dumps(report, default=str) + "\n")
        logger.info(
            "Logged hygiene check for %s: %d issues, %d warnings",
            report["analysis_date"],
            len(report["issues"]),
            len(report["warnings"]),
        )


def main():
    parser = argparse.ArgumentParser(description="IC Health Memory Hygiene Checker")
    parser.add_argument("--as-of-date", type=str, help="Check date (YYYY-MM-DD); defaults to today")
    parser.add_argument("--check-latest", action="store_true", help="Check the most recent memory file's date")
    parser.add_argument("--verbose", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    checker = MemoryHygieneChecker()

    if args.check_latest:
        latest_memory = checker._get_latest_memory_file()
        if latest_memory:
            check_date = checker._parse_date(latest_memory.stem)
        else:
            check_date = date.today()
    else:
        check_date = datetime.strptime(args.as_of_date, "%Y-%m-%d").date() if args.as_of_date else date.today()

    report = checker.check_as_of_date(check_date)
    checker.log_findings(report)

    # Print summary
    print(json.dumps(report, indent=2, default=str))

    # Exit with status based on findings
    if report["summary"]["issue_count"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
