#!/usr/bin/env python3
"""LG3 Mode B: Scheduled Scientific Cartography LangGraph review wrapper.

Wraps the LG1 review orchestrator for cron-compatible daily execution.
Non-blocking, read-only diagnostic. Audit trail via JSONL.
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add repo root to sys.path so imports work from any directory
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def find_latest_snapshot_date():
    """Find the most recent snapshot date in artifacts/scientific_cartography/."""
    artifacts_root = REPO_ROOT / "artifacts" / "scientific_cartography"
    if not artifacts_root.exists():
        return None

    # List all date directories (YYYY-MM-DD format)
    dates = []
    for item in artifacts_root.iterdir():
        if item.is_dir() and len(item.name) == 10 and item.name.count("-") == 2:
            try:
                datetime.strptime(item.name, "%Y-%m-%d")
                dates.append(item.name)
            except ValueError:
                continue

    if not dates:
        return None

    # Return the latest date (lexicographically, since YYYY-MM-DD sorts correctly)
    return sorted(dates, reverse=True)[0]


def run_scheduled_review(
    as_of_date: str,
    strict: bool = False,
    auto_approve: bool = True,
    decision_reason: str | None = None,
) -> int:
    """Run the LG1 review orchestrator for the given date.

    Returns:
        0 on success (or non-blocking failure)
        Never returns non-zero (enforces non-blocking behavior)
    """
    artifact_dir = REPO_ROOT / "artifacts" / "scientific_cartography" / as_of_date
    review_dir = artifact_dir / "review"

    if not artifact_dir.exists():
        error_msg = f"Artifact directory not found: {artifact_dir}"
        log_execution_error(as_of_date, error_msg)
        return 0  # Non-blocking

    # Build command
    cmd = [
        "python3",
        str(REPO_ROOT / "tools" / "run_scientific_cartography_langgraph_review.py"),
        "--as-of-date",
        as_of_date,
        "--artifact-dir",
        str(artifact_dir),
        "--review-dir",
        str(review_dir),
    ]

    if strict:
        cmd.append("--strict")

    if auto_approve:
        cmd.extend(
            [
                "--approve-review",
                "--decision-actor",
                "scheduled-review-automation",
                "--decision-reason",
                decision_reason or "Scheduled review automation (no manual review)",
            ]
        )

    # Execute
    start_time = datetime.now(timezone.utc)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        duration = (datetime.now(timezone.utc) - start_time).total_seconds()

        if result.returncode == 0:
            log_execution_success(as_of_date, duration)
        else:
            error_msg = f"Review orchestrator exited with code {result.returncode}: {result.stderr}"
            log_execution_error(as_of_date, error_msg, duration)

    except subprocess.TimeoutExpired:
        duration = (datetime.now(timezone.utc) - start_time).total_seconds()
        error_msg = "Review orchestrator timeout (>1 hour)"
        log_execution_error(as_of_date, error_msg, duration)
    except Exception as e:
        duration = (datetime.now(timezone.utc) - start_time).total_seconds()
        error_msg = f"Execution error: {str(e)}"
        log_execution_error(as_of_date, error_msg, duration)

    # Always return 0 (non-blocking)
    return 0


def log_execution_success(as_of_date: str, duration: float) -> None:
    """Log successful execution to audit trail."""
    artifact_root = REPO_ROOT / "artifacts" / "scientific_cartography"
    log_path = artifact_root / "scheduled_review_cron.jsonl"

    log_entry = {
        "artifact_type": "scientific_cartography_lg3_scheduled_review_cron_execution",
        "schema_version": "1.0",
        "executed_at_utc": datetime.now(timezone.utc).isoformat() + "Z",
        "as_of_date": as_of_date,
        "outcome": "success",
        "duration_seconds": duration,
        "error_message": None,
        "governance": {
            "read_only_diagnostic": True,
            "review_workflow_only": True,
            "production_model_change": False,
            "ranker_change": False,
            "selector_change": False,
            "sizing_change": False,
            "final_score_change": False,
            "alpha_promotion": False,
            "trading_or_portfolio_action": False,
            "automation_approval": False,
            "non_blocking": True,
        },
    }

    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a") as f:
        f.write(json.dumps(log_entry) + "\n")


def log_execution_error(as_of_date: str, error_msg: str, duration: float = 0) -> None:
    """Log failed execution to audit trail (non-blocking)."""
    artifact_root = REPO_ROOT / "artifacts" / "scientific_cartography"
    log_path = artifact_root / "scheduled_review_cron.jsonl"

    log_entry = {
        "artifact_type": "scientific_cartography_lg3_scheduled_review_cron_execution",
        "schema_version": "1.0",
        "executed_at_utc": datetime.now(timezone.utc).isoformat() + "Z",
        "as_of_date": as_of_date,
        "outcome": "failure",
        "duration_seconds": duration,
        "error_message": error_msg,
        "governance": {
            "read_only_diagnostic": True,
            "review_workflow_only": True,
            "production_model_change": False,
            "ranker_change": False,
            "selector_change": False,
            "sizing_change": False,
            "final_score_change": False,
            "alpha_promotion": False,
            "trading_or_portfolio_action": False,
            "automation_approval": False,
            "non_blocking": True,
        },
    }

    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a") as f:
        f.write(json.dumps(log_entry) + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="LG3 Mode B: Scheduled Scientific Cartography review (cron-compatible)",
    )

    parser.add_argument(
        "--as-of-date",
        default=None,
        help="Snapshot date (YYYY-MM-DD); auto-detects latest if not provided",
    )
    parser.add_argument(
        "--auto-run-latest",
        action="store_true",
        help="Auto-detect latest snapshot and run (recommended for cron)",
    )
    parser.add_argument(
        "--auto-approve",
        action="store_true",
        default=True,
        help="Auto-approve review with scheduled-review-automation actor (default)",
    )
    parser.add_argument(
        "--no-auto-approve",
        action="store_false",
        dest="auto_approve",
        help="Do not auto-approve; require manual decision",
    )
    parser.add_argument(
        "--decision-reason",
        default=None,
        help="Decision reason if auto-approving (default: generated from schedule)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail on governance scan errors (exit code still 0, logged)",
    )

    args = parser.parse_args()

    as_of_date = args.as_of_date
    if args.auto_run_latest:
        as_of_date = find_latest_snapshot_date()
        if not as_of_date:
            error_msg = "No snapshot dates found in artifacts/scientific_cartography/"
            print(f"ERROR: {error_msg}", file=sys.stderr)
            # Still log it as a structured error (no as_of_date yet)
            artifact_root = REPO_ROOT / "artifacts" / "scientific_cartography"
            log_path = artifact_root / "scheduled_review_cron.jsonl"
            log_entry = {
                "artifact_type": "scientific_cartography_lg3_scheduled_review_cron_execution",
                "schema_version": "1.0",
                "executed_at_utc": datetime.now(timezone.utc).isoformat() + "Z",
                "as_of_date": None,
                "outcome": "failure",
                "duration_seconds": 0,
                "error_message": error_msg,
                "governance": {
                    "non_blocking": True,
                    "automation_approval": False,
                },
            }
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a") as f:
                f.write(json.dumps(log_entry) + "\n")
            return 0  # Non-blocking

    if not as_of_date:
        print(
            "ERROR: --as-of-date required (or use --auto-run-latest)",
            file=sys.stderr,
        )
        return 1  # Invalid invocation; not a review failure

    return run_scheduled_review(
        as_of_date=as_of_date,
        strict=args.strict,
        auto_approve=args.auto_approve,
        decision_reason=args.decision_reason,
    )


if __name__ == "__main__":
    sys.exit(main())
