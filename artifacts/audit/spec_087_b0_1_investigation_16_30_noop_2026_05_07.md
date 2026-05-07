# Spec 087 B0.1 Investigation — 2026-05-06 16:30 No-Op + Verification Path

**Date**: 2026-05-07
**Phase**: B0.1 (read-only investigation)
**Predecessors**: B0 commit `ff03788e` (2026-05-06)
**Scope**: read-only — no code, cron, or artifact changes

## TL;DR

1. **Yesterday's 16:30 cron was a complete no-op** because the Python child died at startup before any logger output. Most likely cause: **WSL2 was inactive/suspended during the 16:30 window** (matches the documented `env_wsl_uptime_required` failure mode). The shell wrapper's one tee'd "Starting" line made it into the log; nothing else did.
2. **`run_daily_production.py` does NOT have an early-exit / already-complete branch that bypasses logging silently.** Its idempotent-rerun guard logs three explicit `_logger.info` lines before returning. None of those appear in the 16:30 log section either, ruling out idempotent-skip as the cause.
3. **B0's verification path is broken regardless of WSL2 uptime.** `run_daily_production.py:_run_subprocess` calls `subprocess.run(..., capture_output=True)` and silently discards `run_screen.py`'s stdout/stderr on success. Therefore `[BIOSHORT_WATCH] SKIPPED_STALE_UPSTREAM` from B0 will never reach `logs/daily_production_*.log` under the current production wiring. **File-system signals are the only reliable verification.**

## 1. Why 16:30 produced no output

`logs/cron.log` shows the wrapper started:

```
[2026-05-06T16:30:08-04:00] WARN: stale lock file removed (PID 8819 not running)
[2026-05-06T16:30:08-04:00] Starting daily production for 2026-05-06
```

Then nothing. Wrapper has post-Python branches that always emit one of `PASS` / `WARN` / `FAIL` / `TIMEOUT` to `LOG_FILE` (lines 139–148 of `tools/cron_daily_production.sh`); none appeared. So the wrapper itself did not return — the cron's child shell was killed before reaching the post-Python branch.

Forensic evidence (file-system, post-mortem):

| Artifact | mtime | Interpretation |
|---|---|---|
| `logs/cron.log` | 2026-05-06 16:30 | last write was the "Starting" line at 16:30:08 |
| `logs/daily_production_2026-05-06.log` | 2026-05-06 16:30 | last write was the same "Starting" line tee'd into the dated log |
| `logs/.daily_production_py.lock` | 2026-05-06 16:30, size 0 | `open(_lock_path, "w")` at `run_daily_production.py:4119` truncated the file → Python child reached at least that line |
| `.daily_production.lock` (shell) | not present | trap fired; shell wrapper acquired and released the shell lock |

Inferred sequence:

1. Wrapper at 16:30:08: stale lock cleanup → fresh shell lock → tee'd "Starting" → invoked `${PYTHON} tools/run_daily_production.py --as-of-date 2026-05-06 >> "${LOG_FILE}" 2>&1`.
2. Python child started, imported modules, parsed argparse, called `run_daily()`, opened the Python lock file in write-truncate mode → that's the size-0 16:30 mtime.
3. Python child died **before** logging the `PHASE-2 DAILY RUN` banner at line 4112 or any later `_logger.info` line.
4. Wrapper child (`bash`) was killed alongside Python — never reached its `if [ ${EXIT_CODE} -eq 0 ]; then echo PASS ...` block.

The simultaneous death of both bash wrapper and Python child points to **environment-level termination**, not a script error. WSL2 sleep/resume kills bash wrappers and Python children together; a Python crash would let the wrapper continue and emit `FAIL`.

Cross-reference: memory entry `env_wsl_uptime_required` ("WSL uptime required during cron windows") and `feedback_observation_bias_cron_monitoring` ("missing polls bias toward 'structurally late'"). Both apply.

## 2. No early-exit path in `run_daily_production.py` is silent

The two candidate early-exit branches:

### 2.1 Idempotent rerun (line 4131–4140)

```python
if _step_done(_final_snap, "manifest_written"):
    _logger.info(f"\n  Snapshot for {as_of_date} already has a completed manifest.")
    _logger.info("Skipping expensive steps (price, cache, screen, audit, gates).")
    _logger.info(f"To force a full rerun, delete: {_final_snap / _PROGRESS_FILE}")
    ...
    return existing_manifest
```

Three `_logger.info` lines before returning. None appear in the 16:30 log section. **Not the cause.** Also: `data/snapshots/2026-05-06/.run_progress.json` does not exist, so `_step_done(...)` would have returned `False` regardless.

### 2.2 Snapshot overwrite protection (line 4002–4022)

```python
if existing_hash == staging_hash:
    logging.getLogger(__name__).info(
        "SNAPSHOT OVERWRITE PROTECTION: %s already exists with identical "
        "rankings (hash=%s). Skipping promotion (idempotent rerun).",
        ...
    )
```

This branch fires inside `promote_snapshot()`, which runs **after** `run_screen.py` has executed. It cannot explain a no-op that never reached `run_screen` — `run_screen` itself isn't gated by this. **Not the cause.**

### 2.3 Idempotent step skip (`_step_done` per step)

Each pipeline step (price refresh, cache warm, run_screen, audit, gates) checks `_step_done(snap_dir, step_name)` and skips on done. But each skip emits a log line, and there's no `.run_progress.json` for 2026-05-06 anyway. **Not the cause.**

**Conclusion**: There is no path through `run_daily_production.py` that would produce zero log output on a successful execution. The 16:30 run did not execute meaningfully.

## 3. The verification gate B0 specified is unreachable

Even if WSL2 had been alive yesterday, B0's log-token verification (`grep [BIOSHORT_WATCH] SKIPPED_STALE_UPSTREAM logs/cron.log`) would have failed.

The chain:

```
crontab line:        ... cron_daily_production.sh >> logs/cron.log 2>&1
cron wrapper:        ... run_daily_production.py >> logs/daily_production_${date}.log 2>&1
run_daily_production.py: subprocess.run(["run_screen.py", ...], capture_output=True)
run_screen.py:       logger.info("[BIOSHORT_WATCH] SKIPPED_STALE_UPSTREAM ...")
                     → captured into result.stdout (Python string)
_run_subprocess:     if result.returncode != 0: log captured stderr
                     else: silently discard captured output
```

The `capture_output=True` flag at `tools/run_daily_production.py:407–414` means run_screen's stdout/stderr are captured into Python strings and only logged on **failure or timeout**. On success they are discarded. The B0 token is therefore unreachable from any log file.

This was a spec-level miss: I did not trace the cron→wrapper→Python→subprocess chain when writing B0's acceptance criteria. The fix is structural, not a tweak.

## 4. The file-system signals B0 writes ARE reliable

These signals are independent of stdout capture:

| Signal | Path | Verification approach |
|---|---|---|
| `latest_status.json` exists | `artifacts/bioshort_watch/latest_status.json` | `cat` → check `status`, `upstream_age_days` |
| Watch body suppressed when stale | `artifacts/bioshort_watch/{today}_watch.{json,md}` | absence == suppression worked |

Today (2026-05-07) state confirms B0 has not yet had a chance to fire:
- No `logs/daily_production_2026-05-07.log` — today's 16:30 cron has not run yet (or hasn't completed).
- No `latest_status.json` — B0 helper has not yet executed against current state.
- No `2026-05-07_watch.{json,md}` — neither the old code nor B0 has produced a watch artifact for today.

## 5. Recommended next steps (operator decision)

### 5.1 Confirm WSL2 uptime for today's 16:30 cron

Operator action: ensure WSL2 is alive at 2026-05-07 16:30 ET (preferably with an open terminal or active session). After 16:30 ET today, expected file-system state:

```
artifacts/bioshort_watch/latest_status.json   # B0 helper writes this
  → {status: STALE, upstream_as_of_date: 2026-03-26, upstream_age_days: 42, threshold_days: 9, consumer_status: suppressed}

artifacts/bioshort_watch/2026-05-07_watch.{json,md}
  → DOES NOT EXIST (B0 skipped artifact write because upstream STALE)

logs/daily_production_2026-05-07.log
  → completes with [PASS] or [WARN] in cron.log
  → does NOT contain "[BIOSHORT_WATCH] SKIPPED_*" (subprocess capture)
```

If those file-system signals match, B0 is verified for production. The log-line gate stays unmet, which is a separate problem — see §5.2.

### 5.2 B0.1 logging patch — only if operator wants log-line verification too

The patch I proposed earlier was to add a post-`run_screen` readback in `run_daily_production.py` that reads `latest_status.json` and emits one explicit `_logger.info` line. This makes the bioshort gate visible in `logs/daily_production_*.log` without relying on captured child stdout.

**Worth doing** if the operator wants log-line verification in addition to file signals. **Not required** for B0 correctness — the file signals alone are determinative.

If approved, B0.1 patch would be:
- 1 file edited: `tools/run_daily_production.py`
- ~10 lines added inside `run_daily()`, after the `run_screen` subprocess result is checked, before any post-screen step
- Reads `artifacts/bioshort_watch/latest_status.json`, emits `_logger.info("[BIOSHORT_WATCH] status=... upstream_as_of_date=... age_days=... consumer_status=suppressed")`
- No change to `run_screen.py`, B0 helper, or cron
- Tests: extend `tests/test_bioshort_freshness_guard.py` with a fixture that calls the readback function and asserts log content

Spec amendment to record before the patch lands:

```
B0 acceptance gate (revised, post-investigation):

Primary verification (file-system, determinative):
- artifacts/bioshort_watch/latest_status.json exists and reports STALE/ORPHANED
- no fresh-dated bioshort_watch body generated post-B0 deployment

Secondary verification (log-line, if B0.1 ships):
- logs/daily_production_*.log contains a "[BIOSHORT_WATCH] status=..." readback
  line emitted by run_daily_production.py after the run_screen subprocess.

Note: the original spec's expectation that [BIOSHORT_WATCH] tokens flow into
logs/cron.log via run_screen.py's logger is unreachable — run_daily_production.py's
_run_subprocess(capture_output=True) silently discards run_screen stdout on
success.
```

### 5.3 What stays held

- B1a (CLI default repair + producer code changes)
- B1b (cron install)
- B2 (dashboard envelope)
- 087C (alpha shadow research)
- bioshort_watch LLM reactivation
- Manual `run_screen.py` invocation
- `output/hedge_report/` mutation

## 6. Out-of-scope notes (surfaced for context, not action items)

- `run_daily_production.py` does not call `logging.basicConfig()` anywhere; INFO-level output during the morning run came from logging configured elsewhere (likely a child module's import side-effect, or a separate setup_logging() helper I didn't trace). Worth knowing if logging behavior ever differs between contexts, but not relevant to B0's correctness.
- The morning run (09:22–09:53:58) did not log the `PHASE-2 DAILY RUN` banner either, despite logging the later `Ruleset governance: PASS` line. This means `_logger.info` calls before some setup point are silently dropped. Not a B0 blocker; flagged for the next time someone debugs run_daily_production.py log gaps.
- Morning run died at or after 09:53:58 ("Clinical transmission shadow — 2026-05-06") without releasing its lock cleanly. PID 8819 was already gone by 16:30:08 when the wrapper found its stale lock. Cause unknown; likely also WSL2 sleep mid-run. Not a B0 issue but a recurring environmental risk.

---

_Generated 2026-05-07 as Spec 087 B0.1 read-only investigation per operator direction. No code, cron, or artifact changes made beyond writing this memo._
