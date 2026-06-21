#!/usr/bin/env python3
"""One-command local verification for agent workflow hardening."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def run_command(command: list[str]) -> int:
    """Run a command from the repo root and return its exit code."""
    print("$ " + " ".join(command))
    result = subprocess.run(command, cwd=REPO_ROOT)
    print(f"exit_code={result.returncode}")
    return result.returncode


def main() -> int:
    from tools.agent_preflight import get_shell_health

    shell_health = get_shell_health()
    print(f"shell_health={shell_health['status']}")
    if shell_health["status"] != "ok":
        print("ERROR: shell health check failed; cannot trust verification commands.", file=sys.stderr)
        return 2

    commands = [
        [sys.executable, "tools/agent_preflight.py", "--json"],
        [sys.executable, "tools/check_agent_workflow.py"],
        [sys.executable, "-m", "pytest", "tests/test_agent_workflow_hardening.py", "-q", "-o", "addopts="],
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_hermes_recursive_improvement_queue.py",
            "-q",
            "-o",
            "addopts=",
        ],
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/scientific_cartography/test_langgraph_review.py",
            "-q",
            "-o",
            "addopts=",
        ],
    ]

    for command in commands:
        exit_code = run_command(command)
        if exit_code != 0:
            return exit_code

    return 0


if __name__ == "__main__":
    sys.exit(main())
