#!/usr/bin/env python3
"""Attach a reward signal (feedback verdict) to a logged skill execution.

STAGED — destined for tools/record_skill_feedback.py once containment gates
clear. This is the missing piece that makes the learning loop *recursive*
rather than merely self-monitoring: log_skill() records WHAT ran and whether
it errored; this records whether the output was actually GOOD.

It wraps record_feedback() from tools/skills_logger_v2.py (which already
exists but is never called from the agent flow). Three entry points:

  1. Direct verdict by execution_id:
       python3 tools/record_skill_feedback.py <exec_id> helpful "clean ranking"
       python3 tools/record_skill_feedback.py <exec_id> unhelpful "missed COGT catalyst"

  2. From a run-log JSON (uses the skill_exec_id stamped by the
     run_agent_direct feedback_capture patch):
       python3 tools/record_skill_feedback.py --from-run logs/agent/ic-evaluation_*.json helpful

  3. Deferred / automated correctness (the real reward signal): a downstream
     check that knows whether a recommendation panned out attaches the verdict
     when ground truth arrives (catalyst resolves, IC prints, gate fires).
     See attach_outcome_verdict() — call it from a cron/check, not by hand.

SAFETY: writes only to feedback_log_<env>_<YYYY-MM>.jsonl. Touches no
scoring, routing, snapshots, or agent behavior. Advisory data only.
"""

import argparse
import glob
import json
import sys
from pathlib import Path

# Repo-relative import (run from repo root, same as the learning loop)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.skills_logger_v2 import record_feedback  # noqa: E402

VALID_VERDICTS = {"helpful", "unhelpful", "missing"}


def attach_outcome_verdict(execution_id: str, was_correct: bool, evidence: str, environment: str = "prod") -> None:
    """Programmatic reward signal for automated callers.

    Map a ground-truth correctness boolean to the logger's verdict vocabulary.
    Intended to be called by a downstream check once truth is observable —
    e.g. an IC-print reconciliation, a catalyst-resolution watcher, or a
    governance-gate outcome — NOT by a human at the keyboard.
    """
    verdict = "helpful" if was_correct else "unhelpful"
    record_feedback(execution_id, verdict, notes=evidence, environment=environment)
    print(f"[FEEDBACK] {execution_id} <- {verdict} ({evidence[:80]})")


def _verdict_from_run_log(path_glob: str) -> str:
    matches = sorted(glob.glob(path_glob))
    if not matches:
        sys.exit(f"No run-log file matched: {path_glob}")
    run = json.loads(Path(matches[-1]).read_text())
    exec_id = run.get("skill_exec_id")
    if not exec_id:
        sys.exit(
            f"{matches[-1]} has no 'skill_exec_id' — was it produced before the " "feedback_capture patch was applied?"
        )
    return exec_id


def main() -> int:
    ap = argparse.ArgumentParser(description="Attach feedback to a skill execution.")
    ap.add_argument("execution_id_or_verdict", help="execution_id, OR verdict when --from-run is used")
    ap.add_argument(
        "verdict_or_notes",
        nargs="?",
        default=None,
        help="verdict (helpful|unhelpful|missing), or notes with --from-run",
    )
    ap.add_argument("notes", nargs="?", default="", help="free-text notes (redacted on write)")
    ap.add_argument("--from-run", metavar="GLOB", help="read skill_exec_id from a run-log JSON instead of arg 1")
    ap.add_argument("--env", default="prod", choices=["prod", "test"])
    args = ap.parse_args()

    if args.from_run:
        exec_id = _verdict_from_run_log(args.from_run)
        verdict = args.execution_id_or_verdict
        notes = args.verdict_or_notes or ""
    else:
        exec_id = args.execution_id_or_verdict
        verdict = args.verdict_or_notes
        notes = args.notes

    if verdict not in VALID_VERDICTS:
        sys.exit(f"verdict must be one of {sorted(VALID_VERDICTS)}, got {verdict!r}")

    record_feedback(exec_id, verdict, notes=notes, environment=args.env)
    print(f"[FEEDBACK] {exec_id} <- {verdict}" + (f" ({notes})" if notes else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
