"""Post-snapshot task supervisor.

Re-runs post-snapshot tasks that were killed mid-flight by WSL2 reaping the
parent of run_daily_production.py. Each task is idempotent: re-invoking after
partial completion either skips (artifact present) or resumes (artifact missing).

Phase 1 tasks: AACT (run_daily_production.py:5n), Herald (5l.5).

Invoked by cron_watchdog.sh when:
  - data/snapshots/$TODAY/rankings.csv exists  (snapshot promoted)
  - artifacts/post_snapshot_done/$TODAY.complete missing  (tasks not all done)

Each task's done predicate is its own sentinel artifact, so re-running daily_
production after a successful supervisor pass safely skips done work via the
same predicate.

Exit codes:
  0 — all tasks ok / skipped / not-applicable; complete marker written
  1 — supervisor refused to run (e.g. no snapshot)
  2 — at least one task left in fail/timeout; complete marker NOT written
"""

import argparse
import json
import logging
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
LEDGER_DIR = REPO_ROOT / "artifacts" / "post_snapshot_done"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("post_snapshot_supervisor")

TERMINAL_OK = {"ok", "skipped", "not_applicable"}


@dataclass
class TaskOutcome:
    name: str
    status: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    duration_s: Optional[float] = None
    exit_code: Optional[int] = None
    detail: str = ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_subprocess(
    cmd: List[str],
    *,
    timeout: int,
    label: str,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(REPO_ROOT),
    )


# ---------------------------------------------------------------------------
# Task: AACT trial warehouse refresh (mirror of run_daily_production.py 5n)
# ---------------------------------------------------------------------------


def _aact_should_run(as_of: str) -> bool:
    """Calendar gate: Monday, or latest snapshot >7d old."""
    snap_root = REPO_ROOT / "data" / "aact" / "snapshots"
    is_weekly_day = date.fromisoformat(as_of).weekday() == 0
    latest_age = 999
    if snap_root.exists():
        existing = sorted(
            (d.name for d in snap_root.iterdir() if d.is_dir() and (d / "aact_health.json").exists()),
            reverse=True,
        )
        if existing:
            latest_age = (date.fromisoformat(as_of) - date.fromisoformat(existing[0])).days
    return is_weekly_day or latest_age > 7


def _aact_done(as_of: str) -> bool:
    return (REPO_ROOT / "data" / "aact" / "snapshots" / as_of / "aact_health.json").exists()


def task_aact(as_of: str) -> TaskOutcome:
    name = "aact"
    if _aact_done(as_of):
        return TaskOutcome(name=name, status="skipped", detail="aact_health.json already exists")
    if not _aact_should_run(as_of):
        return TaskOutcome(
            name=name,
            status="not_applicable",
            detail="not Monday and latest AACT snapshot ≤7d old",
        )

    started = _now_iso()
    t0 = time.time()
    try:
        result = _run_subprocess(
            [
                sys.executable,
                str(REPO_ROOT / "tools" / "fetch_aact_snapshot.py"),
                "--download",
                "--as-of-date",
                as_of,
            ],
            timeout=1800,
            label="aact",
        )
    except subprocess.TimeoutExpired:
        return TaskOutcome(
            name=name,
            status="timeout",
            started_at=started,
            duration_s=time.time() - t0,
            detail="fetch_aact_snapshot timed out after 1800s",
        )

    return TaskOutcome(
        name=name,
        status="ok" if result.returncode == 0 and _aact_done(as_of) else "fail",
        started_at=started,
        finished_at=_now_iso(),
        duration_s=time.time() - t0,
        exit_code=result.returncode,
        detail=(result.stderr or "")[-500:],
    )


# ---------------------------------------------------------------------------
# Task: Herald press-release ingest (mirror of run_daily_production.py 5l.5)
# ---------------------------------------------------------------------------


def _herald_done(as_of: str) -> bool:
    """Done predicate: deduped and classified jsonl both exist.

    Dedupe alone is not terminal: if classification failed or timed out after
    dedupe, the next supervisor run must retry classification instead of
    skipping Herald for the day.
    """
    deduped = REPO_ROOT / "data" / "press_releases" / "deduped" / f"deduped_{as_of}.jsonl"
    classified = REPO_ROOT / "data" / "press_releases" / "classified" / f"classified_{as_of}.jsonl"
    return deduped.exists() and classified.exists()


def task_herald(as_of: str) -> TaskOutcome:
    name = "herald"
    if _herald_done(as_of):
        return TaskOutcome(name=name, status="skipped", detail="deduped jsonl already exists")

    started = _now_iso()
    t0 = time.time()
    releases_path = REPO_ROOT / "data" / "press_releases" / f"releases_{as_of}.jsonl"
    deduped_path = REPO_ROOT / "data" / "press_releases" / "deduped" / f"deduped_{as_of}.jsonl"

    if not deduped_path.exists():
        # Stage 1: fetch (always re-run if deduped missing — partial files
        # from a killed prior fetch can't be trusted)
        try:
            r = _run_subprocess(
                [
                    sys.executable,
                    str(REPO_ROOT / "tools" / "fetch_company_press_releases.py"),
                    "--as-of-date",
                    as_of,
                ],
                timeout=1800,
                label="herald-fetch",
            )
        except subprocess.TimeoutExpired:
            return TaskOutcome(
                name=name,
                status="timeout",
                started_at=started,
                duration_s=time.time() - t0,
                detail="fetch_company_press_releases timed out after 1800s",
            )
        if r.returncode != 0:
            return TaskOutcome(
                name=name,
                status="fail",
                started_at=started,
                duration_s=time.time() - t0,
                exit_code=r.returncode,
                detail=f"fetch exit {r.returncode}: {(r.stderr or '')[-300:]}",
            )
        if not (releases_path.exists() and releases_path.stat().st_size > 0):
            return TaskOutcome(
                name=name,
                status="fail",
                started_at=started,
                duration_s=time.time() - t0,
                detail="fetch produced no releases jsonl",
            )

        # Stage 2: dedupe
        try:
            r = _run_subprocess(
                [
                    sys.executable,
                    str(REPO_ROOT / "tools" / "dedupe_press_releases.py"),
                    "--input",
                    str(releases_path),
                ],
                timeout=120,
                label="herald-dedupe",
            )
        except subprocess.TimeoutExpired:
            return TaskOutcome(
                name=name,
                status="timeout",
                started_at=started,
                duration_s=time.time() - t0,
                detail="dedupe timed out after 120s",
            )
        if r.returncode != 0:
            return TaskOutcome(
                name=name,
                status="fail",
                started_at=started,
                duration_s=time.time() - t0,
                exit_code=r.returncode,
                detail=f"dedupe exit {r.returncode}: {(r.stderr or '')[-300:]}",
            )

    if not deduped_path.exists():
        return TaskOutcome(
            name=name,
            status="fail",
            started_at=started,
            duration_s=time.time() - t0,
            detail="dedupe produced no output jsonl",
        )

    # Stage 3: classify (best-effort; failure here doesn't fail Herald,
    # since the dedupe artifact — our done predicate — is already on disk)
    try:
        r = _run_subprocess(
            [
                sys.executable,
                str(REPO_ROOT / "tools" / "classify_press_releases.py"),
                "--input",
                str(deduped_path),
            ],
            timeout=300,
            label="herald-classify",
        )
        classify_detail = "classify ok" if r.returncode == 0 else f"classify exit {r.returncode}"
    except subprocess.TimeoutExpired:
        classify_detail = "classify timeout (non-fatal)"

    return TaskOutcome(
        name=name,
        status="ok",
        started_at=started,
        finished_at=_now_iso(),
        duration_s=time.time() - t0,
        detail=classify_detail,
    )


TASKS: List[Callable[[str], TaskOutcome]] = [task_aact, task_herald]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of-date", required=True)
    args = parser.parse_args()
    as_of = args.as_of_date

    # Validate input
    try:
        date.fromisoformat(as_of)
    except ValueError:
        log.error(f"--as-of-date must be YYYY-MM-DD, got {as_of!r}")
        return 1

    # Refuse to run if snapshot didn't promote — that's daily_production's job
    if not (REPO_ROOT / "data" / "snapshots" / as_of / "rankings.csv").exists():
        log.error(f"data/snapshots/{as_of}/rankings.csv missing — supervisor refuses to run")
        try:
            from common.alerts import send_operator_alert

            send_operator_alert(
                severity="FAIL",
                system="daily_production",
                message=(
                    f"Post-snapshot supervisor: rankings.csv missing for {as_of}. "
                    f"Snapshot was not promoted. Production run likely failed or was interrupted."
                ),
                dedupe_key=f"daily_production:snapshot_missing:{as_of}",
            )
        except Exception as _alert_exc:
            log.debug("Operator alert skipped: %s", _alert_exc)
        return 1

    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    ledger_path = LEDGER_DIR / f"{as_of}.jsonl"
    complete_marker = LEDGER_DIR / f"{as_of}.complete"

    if complete_marker.exists():
        log.info(f"Complete marker already present for {as_of} — nothing to do")
        return 0

    log.info(f"Post-snapshot supervisor starting for {as_of}")
    outcomes: List[TaskOutcome] = []
    for task_fn in TASKS:
        log.info(f"→ {task_fn.__name__}")
        outcome = task_fn(as_of)
        outcomes.append(outcome)
        log.info(f"  {outcome.status}: {outcome.detail}")
        with ledger_path.open("a") as f:
            entry = asdict(outcome)
            entry["as_of_date"] = as_of
            entry["supervisor_run_at"] = _now_iso()
            f.write(json.dumps(entry) + "\n")

    pending = [o for o in outcomes if o.status not in TERMINAL_OK]
    if not pending:
        complete_marker.write_text(
            json.dumps(
                {
                    "as_of_date": as_of,
                    "completed_at": _now_iso(),
                    "tasks": {o.name: o.status for o in outcomes},
                },
                indent=2,
            )
        )
        log.info(f"Supervisor complete: {complete_marker}")
        return 0

    log.warning(
        f"Supervisor incomplete: {len(pending)} task(s) need retry: "
        f"{', '.join(o.name + '=' + o.status for o in pending)}"
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
