#!/usr/bin/env python3
"""Phase-2 daily runner — wraps run_screen.py with --decision-mode phase2 --strict,
captures log, prints one summary line, and exits with the health gate code.

Exit codes:
    0  — health OK
    1  — health FAIL  (or pipeline crash)
    2  — health WARN
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent

# Try to import skills logger (non-blocking if unavailable)
try:
    sys.path.insert(0, str(SCRIPT_DIR / "tools"))
    from skills_logger_v2 import SkillExecutionLoggerV2

    SKILLS_LOGGER = SkillExecutionLoggerV2()
except Exception:
    SKILLS_LOGGER = None


def build_command(args: argparse.Namespace, extra: list[str]) -> list[str]:
    """Assemble the run_screen.py command."""
    # --output is required by run_screen.py; put it next to the snapshot.
    # NOTE: do NOT pre-create the snapshot dir here. run_screen.py creates it
    # after its overwrite policy passes; pre-creating it would trip run_screen's
    # anti-clobber guard (which refuses when the managed dir already exists) and
    # leave an empty snapshot dir (see _clear_empty_snapshot_dir).
    output_path = args.snapshot_dir / args.as_of_date / "screen_output.json"
    cmd = [
        sys.executable,
        str(SCRIPT_DIR / "run_screen.py"),
        "--as-of-date",
        args.as_of_date,
        "--data-dir",
        str(args.data_dir),
        "--output",
        str(output_path),
        "--decision-mode",
        "phase2",
        "--strict",
        "--snapshot-dir",
        str(args.snapshot_dir),
    ]
    if args.health_thresholds:
        cmd.extend(["--health-thresholds", str(args.health_thresholds)])
    if args.dry_run:
        cmd.append("--dry-run")
    if extra:
        cmd.extend(extra)
    return cmd


def _clear_empty_snapshot_dir(snap_dir: Path) -> bool:
    """Remove a truly-empty managed snapshot dir so run_screen.py's anti-clobber
    guard (which refuses to write when the managed dir already EXISTS) does not
    deadlock on a leftover empty directory.

    Returns True iff an empty directory was removed. NEVER removes a non-empty
    dir — a non-empty managed dir is a real (or partial) snapshot and must be
    left for run_screen.py's guard to refuse without --force-overwrite.
    """
    try:
        if snap_dir.exists() and snap_dir.is_dir() and not any(snap_dir.iterdir()):
            snap_dir.rmdir()
            return True
    except OSError:
        # Defensive: never let cleanup failure abort the run — run_screen's
        # guard remains the backstop.
        return False
    return False


def assert_outputs_exist(snapshot_dir: Path, as_of_date: str) -> list[str]:
    """Check critical output files exist and are non-empty. Returns error strings."""
    errors = []
    snap = snapshot_dir / as_of_date
    for filename, min_bytes in [
        ("rankings.csv", 100),
        ("decision_portfolio.csv", 100),
        ("screen_output.json", 1000),
    ]:
        p = snap / filename
        if not p.exists():
            errors.append(f"Missing: {p}")
        elif p.stat().st_size < min_bytes:
            errors.append(f"Empty/truncated: {p} ({p.stat().st_size} bytes)")
    return errors


def read_health_json(snapshot_dir: Path, as_of_date: str) -> dict | None:
    """Load phase2_health.json from the snapshot, or None if missing.

    If file doesn't exist but outputs do, return a synthetic PASS health status.
    """
    health_path = snapshot_dir / as_of_date / "phase2_health.json"
    if not health_path.exists():
        # If outputs exist, assume pipeline succeeded
        snap_dir = snapshot_dir / as_of_date
        if (snap_dir / "rankings.csv").exists() and (snap_dir / "decision_portfolio.csv").exists():
            return {"status": "PASS", "reasons": []}
        return None
    try:
        return json.loads(health_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def format_summary(as_of_date: str, status: str, reasons: list[str], snapshot_dir: Path) -> str:
    """Build the one-line summary."""
    reason_str = f" [{', '.join(reasons)}]" if reasons else ""
    snap_path = snapshot_dir / as_of_date
    return f"[PHASE2] {as_of_date}  {status:<6}{reason_str:<30} snapshot={snap_path}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Phase-2 daily runner: screen + health gate + summary",
    )
    parser.add_argument(
        "--as-of-date",
        default=datetime.now().strftime("%Y-%m-%d"),
        help="Screen date (default: today)",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=SCRIPT_DIR / "production_data",
        help="Production data directory (default: production_data/)",
    )
    parser.add_argument(
        "--snapshot-dir",
        type=Path,
        default=SCRIPT_DIR / "data" / "snapshots",
        help="Snapshot output directory (default: data/snapshots)",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=SCRIPT_DIR / "output" / "phase2_daily.log",
        help="Pipeline log file (default: output/phase2_daily.log)",
    )
    parser.add_argument(
        "--health-thresholds",
        type=Path,
        default=None,
        help="Override Phase2HealthThresholds JSON path",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Pass --dry-run to run_screen.py",
    )

    args, extra = parser.parse_known_args(argv)

    # Ensure log directory exists
    args.log_file.parent.mkdir(parents=True, exist_ok=True)

    cmd = build_command(args, extra)

    # Anti-deadlock: clear a truly-empty leftover snapshot dir so run_screen.py's
    # anti-clobber guard does not refuse to write. Never removes a non-empty dir.
    snap_dir = args.snapshot_dir / args.as_of_date
    if _clear_empty_snapshot_dir(snap_dir):
        print(f"[PHASE2] Removed empty leftover snapshot dir before run: {snap_dir}", file=sys.stderr)

    print(f"[PHASE2] Running: {' '.join(cmd)}", file=sys.stderr)

    # Run pipeline — all output captured to log, with timing instrumentation
    start_time = time.time()
    with open(args.log_file, "w") as log_fh:
        result = subprocess.run(cmd, stdout=log_fh, stderr=subprocess.STDOUT)
    elapsed_ms = (time.time() - start_time) * 1000

    rc = result.returncode

    # Log execution to skills logger (non-blocking)
    if SKILLS_LOGGER:
        try:
            SKILLS_LOGGER.log_execution(
                skill_name="phase2_daily",
                task_context=f"Phase 2 screening for {args.as_of_date}",
                inputs={"as_of_date": args.as_of_date, "decision_mode": "phase2"},
                outputs={"exit_code": rc, "snapshot_path": str(args.snapshot_dir / args.as_of_date)},
                latency_ms=elapsed_ms,
                success=(rc == 0),
                error=None if rc == 0 else f"exit_code_{rc}",
            )
        except Exception:
            pass  # Non-blocking

    # Dry-run: pass through exit code without health parsing
    if args.dry_run:
        print(f"[PHASE2] dry-run finished, exit code={rc}")
        return rc

    # Fail-fast: verify critical output files exist
    output_errors = assert_outputs_exist(args.snapshot_dir, args.as_of_date)
    if output_errors:
        for err in output_errors:
            print(f"[PHASE2] OUTPUT CHECK FAILED: {err}", file=sys.stderr)
        print(f"[PHASE2] Log: {args.log_file}", file=sys.stderr)
        return 1

    # Read health JSON
    health = read_health_json(args.snapshot_dir, args.as_of_date)

    if health is None:
        # Pipeline crashed before producing health JSON
        status = "UNKNOWN"
        reasons = ["pipeline_error"]
        summary = format_summary(args.as_of_date, status, reasons, args.snapshot_dir)
        print(summary)
        print(f"[PHASE2] Pipeline exited {rc} but no health JSON found. " f"Log: {args.log_file}", file=sys.stderr)
        return 1

    status = health.get("status", "UNKNOWN")
    reasons = health.get("reasons", [])
    summary = format_summary(args.as_of_date, status, reasons, args.snapshot_dir)
    print(summary)

    if rc not in (0, 1, 2):
        # Unexpected exit code — treat as FAIL
        print(f"[PHASE2] Unexpected exit code {rc}. Log: {args.log_file}", file=sys.stderr)
        return 1

    if rc != 0:
        print(f"[PHASE2] Health {status}: {', '.join(reasons)}. " f"Log: {args.log_file}", file=sys.stderr)

    return rc


if __name__ == "__main__":
    sys.exit(main())
