#!/usr/bin/env python3
"""Sentinel agent baseline collector — observe-only instrumentation.

Wraps sentinel agent execution to capture baseline metrics without behavior changes.
Sentinel monitors fleet health and production readiness; it is failure-prone due to
preflight checks and system state dependencies.

Baseline metrics:
- Preflight check pass/fail (blockers vs warnings vs clean)
- Execution success rate
- Health check latency by category
- Error patterns (preflight, ranker/selector drift, snapshot missing, etc.)
- System state checks (ruleset, schema, cache freshness)

Baseline usage:
    python3 tools/sentinel_baseline_collector.py [--dry-run]
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).parent))
try:
    from skills_logger_v2 import SkillExecutionLoggerV2

    SKILLS_LOGGER = SkillExecutionLoggerV2()
except Exception:
    SKILLS_LOGGER = None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE_DIR = REPO_ROOT / "artifacts" / "sentinel_baseline"
BASELINE_DIR.mkdir(parents=True, exist_ok=True)


def extract_sentinel_metrics(stdout: str, stderr: str) -> Dict[str, Any]:
    """Extract baseline metrics from sentinel execution output."""
    metrics = {
        "raw_output_lines": len((stdout + stderr).split("\n")),
        "has_errors": "error" in stderr.lower(),
        "has_warnings": "warning" in stdout.lower() or "warning" in stderr.lower(),
    }

    # Parse for preflight status
    if "[PREFLIGHT" in stdout:
        metrics["preflight_check_detected"] = True
        if "BLOCKED" in stdout:
            metrics["preflight_status"] = "BLOCKED"
        elif "WARN" in stdout:
            metrics["preflight_status"] = "WARN"
        else:
            metrics["preflight_status"] = "PASS"
    else:
        metrics["preflight_check_detected"] = False

    # Parse for health gates
    if "health_gate" in stdout.lower() or "health check" in stdout.lower():
        metrics["health_checks_run"] = True
        if "fail" in stdout.lower() or "fail" in stderr.lower():
            metrics["health_gate_result"] = "FAIL"
        else:
            metrics["health_gate_result"] = "PASS"
    else:
        metrics["health_checks_run"] = False

    return metrics


def run_sentinel() -> tuple[int, float, str, str]:
    """Run sentinel agent and return exit code, latency, stdout, stderr."""
    # Sentinel is invoked via openclaw agents run or directly
    # For baseline, we just call the agent via python path
    cmd = [
        sys.executable,
        "-m",
        "tools.run_agent_direct",
        "--agent",
        "sentinel",
        "--message",
        "Daily health check (baseline instrumentation)",
    ]

    start_time = time.time()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        elapsed_ms = (time.time() - start_time) * 1000
        return result.returncode, elapsed_ms, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        elapsed_ms = (time.time() - start_time) * 1000
        logger.error("Sentinel execution timed out after 300s")
        return 1, elapsed_ms, "", "TIMEOUT"
    except Exception as e:
        elapsed_ms = (time.time() - start_time) * 1000
        logger.error("Sentinel execution failed: %s", e)
        return 1, elapsed_ms, "", str(e)


def main(argv: list[str] | None = None) -> int:
    """Instrument sentinel execution and collect baseline metrics."""
    logger.info("Starting sentinel baseline instrumentation")

    time.time()

    # Run sentinel
    exit_code, elapsed_ms, stdout, stderr = run_sentinel()

    # Extract metrics
    sentinel_metrics = extract_sentinel_metrics(stdout, stderr)
    sentinel_metrics["execution_timestamp"] = datetime.now(timezone.utc).isoformat()
    sentinel_metrics["execution_latency_ms"] = elapsed_ms
    sentinel_metrics["exit_code"] = exit_code
    sentinel_metrics["success"] = exit_code == 0

    # Save baseline
    baseline_file = BASELINE_DIR / f"baseline_{datetime.now(timezone.utc).strftime('%Y-%m-%d_%H-%M-%S')}.json"
    try:
        baseline_file.write_text(json.dumps(sentinel_metrics, indent=2))
        logger.info("Baseline metrics saved to %s", baseline_file)
    except Exception as e:
        logger.warning("Failed to save baseline metrics: %s", e)

    # Log to skills logger (non-blocking)
    if SKILLS_LOGGER:
        try:
            # Count metrics for output summary
            preflight_status = sentinel_metrics.get("preflight_status", "UNKNOWN")
            health_gate_result = sentinel_metrics.get("health_gate_result", "UNKNOWN")

            SKILLS_LOGGER.log_execution(
                skill_name="sentinel-health-monitor",
                task_context="Daily fleet health and readiness check",
                inputs={"agent": "sentinel"},
                outputs={
                    "preflight_status": preflight_status,
                    "health_gate_result": health_gate_result,
                    "exit_code": exit_code,
                },
                latency_ms=elapsed_ms,
                success=(exit_code == 0),
                error=None if exit_code == 0 else f"exit_code_{exit_code}",
            )
            logger.info("Execution logged to skills logger")
        except Exception as e:
            logger.warning("Failed to log to skills logger: %s", e)

    # Report
    status = "✅ PASS" if exit_code == 0 else "❌ FAIL"
    logger.info(
        "Sentinel baseline complete: %s, preflight=%s, latency=%.1fs",
        status,
        sentinel_metrics.get("preflight_status", "?"),
        elapsed_ms / 1000,
    )

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
