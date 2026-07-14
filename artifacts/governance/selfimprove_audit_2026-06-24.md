# Self-Improvement Commit Audit — 2026-06-24

**Auditor:** Claude Code (claude-sonnet-4-6)  
**Audit date:** 2026-06-24  
**Repo:** /mnt/c/Projects/biotech_screener/biotech-screener  
**Commits audited:**  
- `20da2dd0` — "feat(selfimprove): wire immediate verdict in run_agent_direct (Step 2)"  
- `49985271` — "feat: selfimprove Steps 3-4 + Nous Gateway research tools"

---

## 1. Commit 20da2dd0

### Files changed

| File | Lines (+/-) | Classification |
|------|-------------|----------------|
| `tools/run_agent_direct.py` | +12 / -1 | **Agent runner** |

### What the diff does

Adds one new import (`record_feedback` from `tools/skills_logger_v2`) and 11 lines
inside the existing `try/except` block that wraps `log_skill()`. Immediately after a
skill execution is logged, the patch reads the execution result status and calls
`record_feedback(skill_exec_id, _verdict, ...)` with `_verdict = "helpful"` on
success or `"unhelpful"` on error. No control-flow change — the new block is inside
the same `try/except` that already guards `log_skill()`, so any failure is caught and
printed to stderr rather than propagated. No new imports beyond the one added symbol
from an already-imported module.

### Production model surface check

No files touching ranker, selector, sizing, final_score, or portfolio are modified.
The only file is `run_agent_direct.py`, which is the Hermes agent dispatch runner.

### Autonomous git write path check

No added lines contain `subprocess.*git`, `os.system.*git`, `push`, or `commit` in
executable form. The only reference to "commit" in the added lines is the existing
comment carried over from context — not in the new 12-line block.

### Risk assessment

The change introduces an automatic feedback verdict (helpful/unhelpful) written
immediately after every agent run, without operator review of individual verdicts.
This is a **low-execution-risk** change — `record_feedback` writes to a JSONL
feedback log, which is advisory data; it does not alter routing, scoring, or
selection. The risk that warrants attention is **signal quality**: auto-immediate
verdicts based solely on exit status (success/error) are a coarse proxy for actual
output quality. Execution success does not equal recommendation quality. If downstream
tooling eventually uses this feedback log to weight skills or promote patterns, a
noisy immediate-verdict stream could pollute that signal.

A second, smaller concern: `run_agent_direct.py` is the live runtime dispatcher. The
patch executes unconditionally on every agent run in production mode (`environment="prod"`).
There is no dry-run flag or observation-only gate on this specific call.

### Verdict: FENCE

The logging write itself is low risk, but the auto-verdict mechanism should not run
silently in production before the EES shadow monitor gates are met. The freeze-state
memo (`scoped_work_freeze_2026_06_22.md`) explicitly freezes the production model
surface; `run_agent_direct.py` is within that surface as the live dispatcher.

**Fence constraint:** Wrap the new `record_feedback` block in a feature flag
(e.g., `SELFIMPROVE_IMMEDIATE_VERDICT=1` env var, defaulting to off) so the
feedback write is opt-in until the 7-day governance observation window closes and
both EES shadow gates are met. Alternatively, move the call to a no-op stub that
logs the intended verdict to stderr only, and wire the real write after the
governance window.

---

## 2. Commit 49985271

### Files changed

| File | Lines (+/-) | Classification |
|------|-------------|----------------|
| `tools/record_skill_feedback.py` | +100 / 0 | **Feedback/reward loop** (new file) |
| `tools/pattern_to_skillpatch.py` | +148 / 0 | **Feedback/reward loop** (new file) |
| `tools/research_ticker.sh` | +88 / 0 | **Skill/docs — research tool** (new file) |
| `tools/research_landscape.sh` | +96 / 0 | **Skill/docs — research tool** (new file) |

### What the diff does

**record_skill_feedback.py:** A CLI wrapper around `record_feedback()` from
`skills_logger_v2`. Three entry points: direct verdict by execution ID, verdict
derived from a run-log JSON file, and a programmatic `attach_outcome_verdict()`
function for automated callers. Writes only to `feedback_log_<env>_<YYYY-MM>.jsonl`.

**pattern_to_skillpatch.py:** Reads `.learnings/LEARNINGS.md`, identifies LRN
entries meeting a recurrence threshold (default 3x), and drafts proposed skill-doc
additions to `artifacts/skill_patch_drafts/`. Explicitly maintains a
`FROZEN_SKILL_TARGETS` set (`selector-ranker`, `selector_ranker`, `clinical-scoring`,
`ic-evaluation`, `financial-health`, `institutional-signal`, `catalyst-resolution`)
and refuses to draft patches against those targets. The blocked case emits a warning
directing the operator to open a Spec instead. All output is draft markdown for
operator review — the tool never edits a skill file directly.

**research_ticker.sh / research_landscape.sh:** Bash wrappers around `hermes chat -q`
that issue a structured prompt for ticker deep-dives or landscape sweeps. The prompt
body explicitly instructs the model to write only to `artifacts/research_notes/` and
lists explicit prohibitions: no git commands, no pipeline file edits, no cron
scheduling, no trading actions.

### Production model surface check

None of the four new files touch ranker, selector, sizing, final_score, or portfolio
code. The two references to `selector-ranker` and `selector_ranker` in
`pattern_to_skillpatch.py` are entries in the frozen-exclusion set — they are guard
rails preventing auto-patching, not access points.

### Autonomous git write path check

No added lines in these four files contain subprocess git calls, `os.system` git
calls, or executable push/commit commands. The string "commit on a branch" appears
once in `pattern_to_skillpatch.py` inside a `print()` string that describes the
intended manual apply path to the human operator — it is not executable. The shell
scripts include `- No git commands (no add, commit, push, status, log)` as constraint
text passed in the prompt body, not as shell commands.

### Risk assessment

**record_skill_feedback.py:** Clean wrapper. No novel risk beyond what `20da2dd0`
already introduced via `record_feedback()`. Adds useful CLI ergonomics and a
programmatic hook for deferred ground-truth attachment.

**pattern_to_skillpatch.py:** The frozen-skill guard is correctly implemented. The
remaining risk is **social engineering of the boundary**: the `DEFAULT_TARGETS`
set and the `FROZEN_SKILL_TARGETS` exclusion logic are both mutable at the source
level, and the `--learnings` and `--out` arguments accept arbitrary paths. A future
caller could supply a `LEARNINGS.md` that nominates an unfrozen but sensitive skill.
More importantly, the tool's commit message says it is "STAGED — destined for
tools/pattern_to_skillpatch.py once containment gates clear" while the file was
committed to main in a non-containment-gated state. The docstring and commit body
are in tension with each other; the file is present on main and executable today.

**research_ticker.sh / research_landscape.sh:** The hard-constraint text in the
hermes prompt is advisory — the model receiving it is not bound by it in the same
way code is. The constraint works against an honest, well-aligned model but provides
no enforcement if the model misbehaves or if a future Hermes version has different
tool permissions. The output path (`artifacts/research_notes/`) is appropriate.
No cron wiring is present. Risk is low for these two files.

### Verdict: FENCE (pattern_to_skillpatch.py) / KEEP (the other three)

**record_skill_feedback.py — KEEP.** It is a thin wrapper with well-scoped writes.
No production surface impact. No autonomous write path. Safe to leave on main.

**research_ticker.sh / research_landscape.sh — KEEP.** Read-only research tools with
explicit prohibitions in the prompt. Low risk. Appropriate output path. No cron.

**pattern_to_skillpatch.py — FENCE.** The file is committed as if it is staging-only
but is fully executable on main today. The `FROZEN_SKILL_TARGETS` guard is correct
in spirit but is just a Python dict — no enforcement layer outside the script itself.
The "commit on a branch" instruction in the apply-path string is a manual-only
advisory with no machine enforcement.

**Fence constraint for pattern_to_skillpatch.py:** Add a runtime gate that aborts
execution unless a `SELFIMPROVE_GATES_MET` env var is set, or the gate check passes
against the EES shadow monitor ledger (same condition as the production-model freeze).
Until both shadow gates are met (20 completed 5d + 20 completed 20d), the script
should print a clear "not yet operational — governance gates unmet" message and exit 0
without writing any draft files. This converts the "STAGED" docstring intent into
enforced behavior.

---

## 3. Overall Summary

### Does either commit touch ranker/selector/sizing/final_score/portfolio?

No. The only references to those terms in either diff are:
- `selector-ranker` and `selector_ranker` appear in `FROZEN_SKILL_TARGETS` in
  `pattern_to_skillpatch.py` as exclusion guards.
- `sizing` and `scoring` appear in a comment in `pattern_to_skillpatch.py` explaining
  what the freeze covers.

No production scoring, selection, or portfolio file is modified by either commit.

### Is there an autonomous git write path introduced?

No. Grep of all `+`-prefixed lines in both commits for `subprocess.*git`,
`os.system.*git`, executable `push`, or executable `commit` returns no matches.
The one string "commit on a branch" is a human-facing instruction inside a print
statement, not an executable command.

### Consolidated verdict table

| Commit | File | Classification | Verdict | Constraint |
|--------|------|----------------|---------|------------|
| 20da2dd0 | `tools/run_agent_direct.py` | Agent runner | FENCE | Gate `record_feedback` call behind `SELFIMPROVE_IMMEDIATE_VERDICT` env flag defaulting off; activate after governance window closes |
| 49985271 | `tools/record_skill_feedback.py` | Feedback/reward loop | KEEP | None required |
| 49985271 | `tools/pattern_to_skillpatch.py` | Feedback/reward loop | FENCE | Add runtime abort unless `SELFIMPROVE_GATES_MET` env var set; reflects "STAGED" docstring intent as enforcement |
| 49985271 | `tools/research_ticker.sh` | Research tool | KEEP | None required |
| 49985271 | `tools/research_landscape.sh` | Research tool | KEEP | None required |

### Priority

The fence on `run_agent_direct.py` (20da2dd0) is the higher priority because that
file executes on every live agent dispatch — the feedback write is already running
in production. The fence on `pattern_to_skillpatch.py` is lower urgency because the
script is not wired to any cron and requires manual invocation.

---

*Memo written to working tree only. No commits, no branches, no pushes performed.*
