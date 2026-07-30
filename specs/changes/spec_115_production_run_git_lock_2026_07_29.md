# Change Spec: Protect mandate-eligible capture from git-state interference

**Status**: DRAFT
**Author**: Claude Code (root-cause trace from the 2026-07-23 and 2026-07-27 window losses)
**Date**: 2026-07-29
**Ruleset impact**: NO — run orchestration and evidence durability only. No ranker, selector, sizing, `final_score`, portfolio or snapshot behaviour changes. Does not reset the out-of-sample clock.

Related: `docs/incidents/FV_GAP_2026_07_27.md`, mandate SM-20260629-001, `feedback_shared_checkout_concurrency`.

---

## Objective

Two of the ten trading days from 2026-07-15 to 2026-07-28 lost a mandate-eligible forward-validation window, both to git mechanics rather than to any model, data or pipeline defect. Make the loss mechanically impossible rather than documented as a rule for humans to remember.

## The two failure modes are different, and one control does not cover both

This is the central finding. A run-scoped lock — the obvious design — fixes only the first.

### Mode A — HEAD moves *during* the run, capture refused

`tools/cron_daily_production.sh`:

```sh
127:  LOCAL_HEAD=$(git -C "${REPO_ROOT}" rev-parse --short HEAD ...)   # run start, warning only
...
275:  # wrapper's HEAD commit so it can confirm the snapshot came from this invocation.
276:  INVOCATION_COMMIT="$(git -C "${REPO_ROOT}" rev-parse HEAD ...)"
280:      --expect-commit "${INVOCATION_COMMIT}"
```

`INVOCATION_COMMIT` is **late-bound**. Despite the name and the comment, it is evaluated at step 6, not at invocation. The snapshot was stamped with HEAD at snapshot-creation time; if HEAD moved in between, the two disagree and `run_forward_validation.py` refuses. `--force` cannot recover it: it downgrades `capture_mode` to `REPLAY` unconditionally (`tools/run_forward_validation.py:756-766`), and `REPLAY` is never mandate-eligible.

**Risk window:** run start → step 6. Bounded, ~25 minutes.
**Observed:** 2026-07-27, caused by a `git pull --ff-only` plus a data-artifact commit made mid-run from an interactive session.

### Mode B — working tree reverted *after* a successful capture, evidence erased

2026-07-23 captured cleanly: `Captured 2026-07-23: top30=30 quality=PASS model=827c35a9ed3ee6e1`, and `artifacts/forward_validation/2026-07-23/TRUTH_CARD.md` is still on disk. But no commit ever contained a 07-23 line, and the current `captures.jsonl` is a byte-exact prefix match of commit `e7ed5375` (the last commit before 07-23, ending at 07-22) plus exactly `[07-24, 07-28]`.

A working-tree revert — `git checkout -- <path>`, `git restore`, `git stash`, `git reset --hard`, or a branch switch — reset the tracked ledger to its committed state between 07-23 13:12 and 07-24 16:30, destroying the append. 07-24 then appended normally, which is why the damage looks like one missing day rather than a truncation.

**Risk window:** capture written → capture committed. **Unbounded** — it stays open until someone commits, which in practice was 5 days.
**A run-scoped lock does not cover this at all.** The run had already exited; the file was already written.

## The deadlock concern does not apply — verified

An earlier draft of this design worried that blocking commits during a run would deadlock the pipeline's own writes. That is **not** the case:

- `tools/cron_daily_production.sh` contains **no** `git add|commit|push|checkout|restore|stash|reset`. It only reads: `fetch`, `rev-parse`, `rev-list`.
- **No** crontab entry references git.

Every git write to this checkout originates from an interactive or agent session. So the lock needs no allowlist for the run's own writes, and only has to keep the run's *read* operations working.

## Inputs

| Input | Source | Schema |
|-------|--------|--------|
| HEAD at run start | `git rev-parse HEAD` in the wrapper | 40-char sha |
| snapshot `commit_sha` | snapshot run manifest | 40-char sha |
| lock state | `artifacts/run_locks/production.lock` (new) | JSON: `pid`, `started_at`, `head_at_start`, `as_of_date` |

## Outputs

| Output | Destination | Schema |
|--------|-------------|--------|
| `head_at_start` | run manifest (new field) | 40-char sha |
| `RUN_HEAD_MOVED` diagnostic | run log + non-zero exit | distinct, greppable, alertable |
| lock file | `artifacts/run_locks/production.lock` | created at start, removed on exit incl. signal paths |

## Invariants

1. A mandate-eligible capture is written **only** if HEAD is unchanged from run start through capture.
2. A capture that cannot be written is **loudly diagnosed**, never silently skipped. Losing a window must be noisy.
3. The lock must never block the production run's own git **reads**.
4. The lock must be **self-healing**: a stale lock from a killed run must not wedge the next one (PID liveness + age bound).
5. Mode A must not be "fixed" by making the gate more permissive. Early-binding `INVOCATION_COMMIT` alone would *mask* a genuinely mixed-code run, which is worse than losing a window.
6. No cron job may `push`. Commit-only at most, preserving INC-2026-06-20-AUTOPUSH containment.

## Failure Modes

| Scenario | Expected behavior |
|----------|-------------------|
| HEAD moved mid-run | `RUN_HEAD_MOVED` error naming both shas; capture refused; run exits non-zero |
| Lock present, owning PID alive | Interactive git write refused with the owning `as_of_date` and elapsed time |
| Lock present, owning PID dead | Lock treated as stale, removed, warning logged |
| Lock older than 2× the 6000s run timeout | Stale, removed, warning logged |
| Lock directory unwritable | Run proceeds, WARN — never fail production for a missing advisory lock |
| Uncommitted capture at next run start | WARN naming the uncommitted dates, so Mode B is visible before it bites |

## Phased plan

### Phase 1 — early-bind and diagnose (Mode A). Zero risk, do first.

Hoist HEAD capture to run start beside the existing drift guard, record it in the run manifest, and at step 6 compare current HEAD against it. On mismatch emit `RUN_HEAD_MOVED` with both shas and refuse. Net outcome is unchanged — no bogus capture — but the operator gets an unambiguous diagnosis instead of a generic provenance refusal that reads like a pipeline fault, and the condition becomes alertable.

### Phase 2 — collapse Mode B's window. Highest value per unit of risk.

Two options; **recommend 2a.**

**2a. Relocate the evidence ledger out of the tracked working tree.** `captures.jsonl` and `fills.jsonl` move to a location git does not manage, with the existing artifacts path kept as a published copy. A working-tree revert then cannot destroy evidence, and cron never needs to write git state. Cost: the mandate's book of record moves, which is a governance decision, and backup/retention becomes explicit rather than inherited from git.

**2b. Commit immediately after capture.** Collapses the window to near zero but puts a `git commit` inside the cron path — adjacent to what INC-2026-06-20 was about. Must be commit-only, never push. Cheaper to implement, worse for containment posture.

### Phase 3 — the advisory lock proper (defence in depth for Mode A).

Lock file written at run start, removed on exit including signal paths. A git hook refuses state-changing operations while the lock is held, with a documented override for genuine emergencies. Given the verification above, no allowlist for pipeline writes is required.

Phase 3 is deliberately last: Phases 1 and 2 remove the actual observed losses, while Phase 3 is the control-plane change with the largest blast radius. Per `feedback_pause_between_control_plane_changes`, it should land on its own, after 1 and 2 have been observed working.

## Validation Plan

### Tests (write BEFORE implementation)

- [ ] `test_head_recorded_at_run_start_not_at_capture` — the Mode A regression; fails against today's late binding
- [ ] `test_head_moved_midrun_emits_run_head_moved` — distinct diagnostic, non-zero exit
- [ ] `test_head_moved_midrun_does_not_write_capture` — invariant 1
- [ ] `test_head_unchanged_writes_live_eligible_capture` — happy path stays LIVE + eligible
- [ ] `test_stale_lock_dead_pid_is_reclaimed` — invariant 4
- [ ] `test_stale_lock_beyond_age_bound_is_reclaimed` — invariant 4
- [ ] `test_lock_does_not_block_git_reads` — invariant 3
- [ ] `test_unwritable_lock_dir_warns_but_run_proceeds`
- [ ] `test_uncommitted_capture_dates_warn_at_next_run_start` — Mode B visibility
- [ ] `test_lock_removed_on_sigterm` — no wedging after a timeout kill
- [ ] Determinism: same inputs → same manifest fields

### Integration

- [ ] Full suite passes
- [ ] Pre-commit chain green including the semgrep governance gate
- [ ] Dry-run against 2026-07-27 reproducing `RUN_HEAD_MOVED` from the real shas (`e7ed5375` snapshot vs `233239a7` invocation)

## Expected Effect Size

**No alpha impact. Evidence-durability only.** The measurable claim: over the ten trading days 2026-07-15 → 2026-07-28, two mandate-eligible windows were lost to git mechanics — roughly 20% attrition against a 52-window gate currently standing at n=4. Phase 1 makes Mode A diagnosable, Phase 2 makes Mode B impossible, Phase 3 makes Mode A impossible.

Attrition at that rate is the binding constraint on the mandate finishing at all. Nothing here improves the model; it stops the evidence from leaking.

## Non-Goals

- Does **not** recover 07-23 or 07-27. Both are permanently lost — `--force` yields `REPLAY`, which is never mandate-eligible. Do not backfill either.
- Does **not** change the freshness/provenance gate's strictness. The gate behaved correctly in both incidents.
- Does **not** add push capability to any cron job.
- Does **not** address host availability (separate: WSL uptime as a single point of failure).
- Does **not** change the 6000s run timeout or the catch-up scanner.

---

## Governance

- **Tier**: 3 for Phase 1–2 (production orchestration + evidence integrity), Tier 4 for Phase 3 (control-plane guard affecting operator git usage).
- **Freeze**: compatible with the DEM NO_MODEL_CHANGE window — orchestration and durability, not model behaviour. No OOS reset.
- **Sequencing**: Phase 3 lands alone, after 1 and 2 are observed working.

## Implementation Log

### 2026-07-29 — Phase 1 implemented (uncommitted)

- Files modified: `tools/cron_daily_production.sh`
- `RUN_START_COMMIT` now bound at run start, beside the drift guard (~line 127),
  instead of being re-read at step 6. `INVOCATION_COMMIT` falls back to the
  step-6 value when the drift-guard block did not run (git unavailable), so
  there is no regression in that path.
- Added `HEAD_MOVED` detection at step 6 emitting a distinct, greppable
  `RUN_HEAD_MOVED` ERROR naming both shas, and stating that `--force` must not
  be used because it yields `REPLAY`.
- The capture is refused on a HEAD move rather than proceeding — early-binding
  alone would mask a genuinely mixed-code run (invariant 5).
- **Only the capture is gated.** `fill_forward_returns.py` and
  `weekly_validation_summary.py` still run, since they operate on *prior*
  captures and skipping them would delay evidence maturation. (First draft of
  this change incorrectly gated all three.)

Verification: `bash -n` clean. Logic exercised across four cases —
(1) unchanged HEAD → `HEAD_MOVED=0`, `expect_commit` = run-start sha, behaviour
identical to today; (2) the real 2026-07-27 pair `e7ed5375` → `233239a7` →
`HEAD_MOVED=1`, capture refused with diagnosis; (3) git unavailable at run start
→ falls back to the step-6 sha, no spurious trip; (4) git unavailable entirely →
empty `expect_commit`, as today. No case introduces a new failure path.

### 2026-07-29 — Phase 2 visibility half implemented (uncommitted)

- Files modified: `tools/cron_daily_production.sh`
- Warns at run start when `captures.jsonl` holds appends not present in `HEAD`,
  naming the affected dates: `UNCOMMITTED_MANDATE_EVIDENCE`.
- This does **not** prevent Mode B. It makes it visible within one run instead
  of the five days 2026-07-23 went unnoticed. Non-blocking, warn-only.
- Chosen because it needs no 2a-vs-2b decision and carries near-zero risk,
  unlike relocating the book of record.

Verification: `bash -n` clean. Dry-run against the live checkout on 2026-07-29
reported `committed=17 working=19` → **2 uncommitted captures: 2026-07-28,
2026-07-29** — i.e. the exact exposure that lost 07-23 was live at the moment
the control was written.

Phase 2 relocation (2a) / commit-after-capture (2b) still needs the operator's
decision. Phase 3 not started.

---

*Template version: 1.0.0 — see specs/SYSTEM_SPEC.md for system invariants*
