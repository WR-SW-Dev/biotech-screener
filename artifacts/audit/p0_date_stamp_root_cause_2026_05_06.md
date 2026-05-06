# P0 #1 Phase 1 — Date-stamp Corruption Root Cause Memo (2026-05-06)

**Status:** Phase 1 read-only investigation per Spec 083. **No fixes implemented.** Implementation requires explicit user approval.

**Headline:** The audit memo's specific symptom claims were partially wrong. Filenames on disk are correctly dated for both agents. The real residual issue is **`history.jsonl` row-stamp contamination** in `policy_shadow_watch`, caused by something invoking `tools/build_policy_shadow_compare.py` with January-2026 `--as-of-date` arguments. The contamination is **ongoing** (2 new corrupt rows appended between 09:11 and 13:33 today). `bioshort_watch` shows no corruption — only Mode B (stale upstream).

---

## 1. Audit-memo claims vs. ground truth

| Audit claim | Ground truth |
|---|---|
| `policy_shadow_watch` files written today bear filename stamps `2026-01-15` / `2026-01-20` | **WRONG.** Filenames in `artifacts/policy_shadow/tier_weighted/` are correctly dated (most recent: `2026-05-04_comparison.{json,md}` mtime 2026-05-06 08:04, and `2026-05-05_comparison.{json,md}` mtime 2026-05-05 20:45). No January-stamped filenames exist. |
| `policy_shadow_watch` `history.jsonl` last 3 rows dated 2026-01-15/20 | **CORRECT.** Live file tail is `2026-01-20, 2026-01-20, 2026-01-15` (file mtime 2026-05-06 13:33, 554 lines). |
| `bioshort_watch` artifacts written today (2026-05-06 13:33) bear filename stamps `2026-01-15` / `2026-01-20` | **WRONG.** `artifacts/bioshort_watch/2026-05-06_watch.{json,md}` exists, mtime 2026-05-06 09:48. No January-stamped files in the directory. |
| `bioshort_watch` body content dates to 2026-03-26 | **PARTIALLY CORRECT.** Today's `2026-05-06_watch.md` title reads "Bioshort Watch — 2026-03-26" (the upstream `output/hedge_report/hedge_report_2026-03-26.json` `as_of_date`). Filename is today, content is March 26 — Mode B (stale upstream), not Mode A. |
| `tools/cron_evening_catchup.sh:109` is the suspected back-loop source | **PARTIALLY CORRECT.** Line 109 (`run_agent policy_shadow_watch 1805`) does invoke the LLM HEARTBEAT path (the deprecated path per agent's own 2026-05-05 memory note), but today's three catchup fires (10:02, 13:57, 15:16 ET) all DEFERRED policy_shadow_watch (NOW < 18:05). The catchup did NOT cause today's 13:33 corruption. |

---

## 2. Root cause

### 2.1 What is actually broken

`artifacts/policy_shadow/tier_weighted/history.jsonl` has 3 trailing rows stamped with January 2026 dates. The rows were appended today (mtime 2026-05-06 13:33). Their internal field values reflect TODAY's cumulative state (e.g., `INSM` headwind_streak=26, `NRIX`/`KRYS` present — both added in the 2026-04-25 cohort change). The dates are 2026-01-20 (×2) and 2026-01-15.

**Backup evidence — the corruption is ongoing:**
- `history.jsonl.bak.20260506_091154` (552 lines) was already corrupt at the tail (last row dated 2026-01-15) when it was taken at 09:11 ET today.
- Live `history.jsonl` (554 lines, mtime 13:33) has 2 new rows since the backup, both dated 2026-01-20.
- Net: at least 1 invocation pre-09:11 today wrote a 2026-01-15 row; 2 more invocations between 09:11 and 13:33 wrote 2026-01-20 rows.

### 2.2 Mechanical cause

`tools/build_policy_shadow_compare.py` (`build_policy_shadow_compare()`, lines 176–311) writes `history.jsonl` by appending `{"date": as_of_date, ...}` (lines 298–311). The `as_of_date` value comes verbatim from the `--as-of-date` CLI argument. **The script is doing what it is told.**

The `headwind_streaks` field reflects current cumulative state because `compute_tiered_exit_weights(positions, rankings, tier_weights, history_path)` (line 213) reads the full existing `history.jsonl` to accumulate streaks. So when the script is invoked with an old `--as-of-date`:
- It loads `artifacts/live_shadow/positions/{old-date}.json` (returns early on `error` if absent — but rows exist, so the position file exists for those dates).
- It loads `data/snapshots/{old-date}/rankings.csv` (similar early-exit on missing).
- It computes streaks from the entire history file (including today's accumulation).
- It appends a row with `date: <old-date>` and current-state field values — the "Frankenstein row" pattern.

**The bug is in the CALLER, not the script.** Some caller is passing January 2026 dates to `--as-of-date` today.

### 2.3 Suspected callers (not yet identified)

I could not pin down which process invoked the script at 13:33 today. The candidates:

| Candidate | Status | Note |
|---|---|---|
| Direct daily cron `5 18 * * 1-5 ... build_policy_shadow_compare.py --as-of-date $(date +%Y-%m-%d)` | RULED OUT (timing) | Not yet fired today; would pass today's date anyway |
| `cron_evening_catchup.sh:109` (LLM HEARTBEAT) | RULED OUT (deferred) | Today's three fires (10:02, 13:57, 15:16) all logged "defer policy_shadow_watch — scheduled 1805 not yet past" |
| LLM agent invocation reading "missed dates" hint | UNKNOWN | If WSL just rebooted at 13:33, a delayed @reboot job may have triggered the LLM agent path; but I see no evidence in `agents.log` |
| Manual user invocation | UNKNOWN | Plausible — `agents/policy_shadow_watch/TOOLS.md:7` shows the example `--as-of-date 2026-03-28`, so an operator could be running backfills with old dates |
| Some other backfill / one-shot script | UNKNOWN — not found by `grep -rn 'build_policy_shadow_compare' tools/` | Only the script itself, the agent's SOUL/TOOLS, and the `shadow_watch` SOUL reference it |

A targeted next-step would be `grep` of bash history, recent `.claude` session logs, or `lsof`/`ps`-style introspection at corruption time — but those are forensic and beyond Phase 1's read-only scope on file content.

### 2.4 Already-fixed-but-incomplete prior work

`agents/policy_shadow_watch/memory/2026-05-05.md:29` records that yesterday the daily cron path was changed:

> "Changed cron from `run_agent_direct.py --message HEARTBEAT` to `build_policy_shadow_compare.py --as-of-date $(date +%Y-%m-%d)`. Builder now runs directly at 18:05 ET weekdays. The HEARTBEAT message was causing the LLM agent to read artifacts without invoking the builder (Class F pattern)."

This fix is correct for the daily cron but **`cron_evening_catchup.sh:109` was not updated to match.** The catchup still uses the deprecated LLM HEARTBEAT path. If the catchup ever fires after 18:05 (per current code) without the daily cron having run, the LLM agent would be invoked — but the agent's own 2026-05-05 memory says that path was broken (Class F: read artifacts without invoking the builder). It's not the corruption source today (deferred), but it is a latent inconsistency.

### 2.5 `bioshort_watch` separate finding

The audit memo's bioshort claims about January-stamped filenames are not reproducible. `artifacts/bioshort_watch/` shows correctly-dated files including `2026-05-06_watch.{json,md}` (mtime 09:48 today). The actual issue:

- `tools/build_bioshort_watch.py:400` resolves `date_str = as_of_date or current_date` where `current_date = current.get("as_of_date", "unknown")` (line 321) — i.e., the upstream `output/hedge_report/*.json`'s `as_of_date`.
- Today's file body title reads "Bioshort Watch — 2026-03-26" (the upstream's `as_of_date`).
- Upstream `output/hedge_report/hedge_report_2026-03-26.json` is the latest hedge report. No new hedge report has been written since March 26.
- Filename stamps appear OK because the LLM agent (which is the only entry point — `10 18 * * 5 ... run_agent_direct.py --agent bioshort_watch --message HEARTBEAT`) likely passes `--as-of-date $(date +%Y-%m-%d)` explicitly when it invokes `build_bioshort_watch.py`.

**This is Mode B (stale upstream) only. Spec 083 should not block on this.** The `output/hedge_report/` upstream-producer identification belongs in a separate P2 ticket as the original spec scoped.

---

## 3. Production-decision impact

**None.** Both agents are observe_only governance / research-shadow:

- `policy_shadow_watch` — `tools/eval_policy_candidate.py:226` reads `history.jsonl`. That's a research evaluator, not a production cron. The 3 corrupt rows would contaminate any policy-candidate analysis that aggregates over history. **Effect: research fidelity, not scoring.**
- `bioshort_watch` — observe_only research-shadow per audit registry. No selector / ranker / EV / sizing impact.
- Neither participates in `run_screen.py`, `module_*` scoring, ranker, or EV layer.

The freeze regime is not threatened. The blast-radius of inaction is human-confusion (operators reading wrong-dated rows in policy-candidate analysis) and one stale weekly hedge report.

---

## 4. Affected files / functions

| File | Function / Line | Role |
|---|---|---|
| `tools/build_policy_shadow_compare.py` | `build_policy_shadow_compare()` 176–311; history append 297–311 | Script faithfully writes whatever date is passed; no inherent bug |
| `tools/build_policy_shadow_compare.py` | `compute_tiered_exit_weights()` (called 213) | Source of "current state under old date" — reads cumulative history |
| `tools/cron_evening_catchup.sh:109` | `run_agent policy_shadow_watch 1805` | Stale path; needs alignment to new deterministic-build pattern |
| `tools/build_bioshort_watch.py:321,400` | `date_str = as_of_date or current_date` | Body content date follows upstream when no CLI date provided |
| `output/hedge_report/hedge_report_*.json` | upstream producer | Last write 2026-03-26; producer not in `crontab -l`, ownership unclear |
| `artifacts/policy_shadow/tier_weighted/history.jsonl` | data | Contaminated tail (3 rows) |
| `artifacts/policy_shadow/tier_weighted/history.jsonl.bak.20260506_091154` | data | Pre-corruption-during-today backup; itself ALREADY contaminated (1 row) |

---

## 5. Exact artifact examples

`artifacts/policy_shadow/tier_weighted/history.jsonl` last 3 lines (truncated, file mtime 2026-05-06 13:33):

```jsonl
{"date": "2026-01-20", "n_current": 30, "n_tiered": 30, "n_exit": 23, "pnl_current": 1.1493, ..., "headwind_streaks": {"REPL": 186, ..., "INSM": 26, ..., "NRIX": 0, "KRYS": 0}}
{"date": "2026-01-20", "n_current": 30, "n_tiered": 30, "n_exit": 23, "pnl_current": 1.1493, ..., "headwind_streaks": {"REPL": 186, ..., "INSM": 26, ..., "NRIX": 0, "KRYS": 0}}
{"date": "2026-01-15", "n_current": 30, "n_tiered": 30, "n_exit": 22, "pnl_current": 2.2328, ..., "headwind_streaks": {"REPL": 185, ..., "INSM": 26, ..., "NRIX": 0, "KRYS": 0}}
```

Tells:
- `INSM`=26 was reached on 2026-05-04 per the prior (legitimate) row; the 2026-01-15-stamped row also shows `INSM`=26, which is structurally impossible for January (the streak would have been ~7 in January).
- `NRIX`, `KRYS` are present in the streak dict; both tickers entered the cohort on 2026-04-25. They cannot be in a January row.

`artifacts/bioshort_watch/2026-05-06_watch.md` first line:

```
# Bioshort Watch — 2026-03-26
```

Filename is correct (today); body title carries upstream's stale `as_of_date`.

---

## 6. Minimal fix plan (NOT IMPLEMENTED — pending approval)

Three separable diffs. None should be applied without explicit user approval.

### Fix A — Cleanup `history.jsonl` (smallest, immediate)

- Truncate the 3 trailing wrong-stamped rows from `history.jsonl`.
- Preserve current `history.jsonl.bak.20260506_091154` and create a fresh `.bak.cleanup_2026_05_06` BEFORE editing.
- After cleanup, the file's tail should be `2026-04-30, 2026-05-01, 2026-05-04` (the legitimate run sequence).
- **Risk:** None to production; minimal to research (`eval_policy_candidate.py` evaluates fewer rows).
- **Caveat:** Does NOT prevent recurrence. Without Fix C, the next invocation with an old `--as-of-date` will reintroduce the same row pattern.

### Fix B — Catchup alignment (small)

In `cron_evening_catchup.sh`, replace:

```bash
run_agent policy_shadow_watch     1805
```

with a `run_tool` block that mirrors the corrected daily cron:

```bash
check_policy_shadow() { file_exists "$REPO/artifacts/policy_shadow/tier_weighted/${TODAY}_comparison.json"; }
run_tool policy_shadow 1805 "$REPO/logs/agents_direct_cron.log" check_policy_shadow \
    "$PYTHON $REPO/tools/build_policy_shadow_compare.py --as-of-date $TODAY"
```

- **Risk:** Low. The LLM HEARTBEAT path was already documented as broken (Class F) in 2026-05-05 memory. Removing the broken fallback cannot regress functionality.
- **Caveat:** Does NOT address the unidentified-caller problem. If the corruption is being driven by something OTHER than the catchup (which it is — see §2.3), Fix B alone won't stop it.

### Fix C — Defensive guard in builder (most targeted at recurrence)

Add a precondition to `tools/build_policy_shadow_compare.py`: if `--as-of-date` is older than the most recent date in the existing `history.jsonl`, refuse to append unless `--allow-backfill` is explicitly passed.

- **Risk:** Medium. Legitimate backfills (e.g., regenerating a missing day) would need `--allow-backfill`. Need to verify no automated catchup expects the silent-old-date behavior.
- **Caveat:** Surfaces the unknown caller — the next invocation with a January date will fail loudly with a clear error message, identifying who is calling.

### Recommended sequence (if approved)

1. **Fix A immediately** to clean the contaminated tail (deterministic, zero-risk).
2. **Fix C before Fix B** to expose the actual caller. Run for 24–48 hours, observe which process trips the guard.
3. **Fix B last**, only if observation confirms no other process needs the catchup's LLM path for legitimate reasons.

---

## 7. Tests / smoke commands

After any fix, verify:

### Cleanup verification (after Fix A)
```bash
tail -3 /mnt/c/Projects/biotech_screener/biotech-screener/artifacts/policy_shadow/tier_weighted/history.jsonl | python3 -c 'import json, sys; [print(json.loads(l)["date"]) for l in sys.stdin]'
```
Expected output: 3 dates, all from May 2026, sorted ascending. No January dates.

### Catchup verification (after Fix B, dry-run since Fix B requires post-18:05)
```bash
TZ=America/Detroit date +%H%M  # confirm NOW
grep -A2 'policy_shadow' /mnt/c/Projects/biotech_screener/biotech-screener/tools/cron_evening_catchup.sh
```
Expected: catchup uses `run_tool` (not `run_agent`) for policy_shadow.

### Defensive guard verification (after Fix C)
```bash
cd /mnt/c/Projects/biotech_screener/biotech-screener && \
  /usr/bin/python3 tools/build_policy_shadow_compare.py --as-of-date 2026-01-15
```
Expected: non-zero exit, stderr message like `refusing to append: --as-of-date 2026-01-15 is older than latest history entry 2026-05-04; pass --allow-backfill to override`.

### Recurrence smoke (next-day, after all fixes)
```bash
ls -lt /mnt/c/Projects/biotech_screener/biotech-screener/artifacts/policy_shadow/tier_weighted/history.jsonl
tail -3 .../history.jsonl | python3 -c 'import json, sys; [print(json.loads(l)["date"]) for l in sys.stdin]'
```
Expected next weekday after 18:05: tail's last row dated to that day, file mtime within a few minutes of 18:05.

---

## 8. Rollback path

| Fix | Rollback |
|---|---|
| A (cleanup) | `cp artifacts/policy_shadow/tier_weighted/history.jsonl.bak.20260506_091154 artifacts/policy_shadow/tier_weighted/history.jsonl` (note: the `.bak` itself contains 1 corrupt row; this would re-introduce it). For complete rollback, fall back to `git history` of the file (ignored from git, but `.bak.cleanup_2026_05_06` should be the safer pre-edit copy created during Fix A). |
| B (catchup) | `git revert <commit>` — single-file shell change. |
| C (defensive guard) | `git revert <commit>` — single-file Python change. To preserve the new `--allow-backfill` flag while disabling the precondition, an alternative is to flip a `STRICT_MODE = True` constant. |

**What breaks if rolled back:** Nothing in production. Research fidelity returns to current (slowly-corrupting) state.

---

## 9. Out-of-scope confirmations

- **Bioshort Mode B (stale upstream):** punted to a separate P2 ticket as Spec 083 §6 specified. Producer for `output/hedge_report/` not identifiable from `crontab -l` or `tools/build_*` filenames.
- **No change** to `policy_shadow_watch` or `bioshort_watch` agent code, registry entries, schedules, or memory files in this Phase.
- **No change** to selector/ranker/EV/sizing — confirmed unaffected.

---

## 10. Recommendation summary

**Proceed only if approved:**
1. **Fix A** (history.jsonl cleanup) — safest, zero-risk, immediate.
2. **Fix C** (defensive `--as-of-date` guard) — surface the unknown caller.
3. After 24–48h observation: **Fix B** (catchup alignment) if no legitimate consumer of the LLM HEARTBEAT path surfaces.

**Do NOT proceed yet:**
- bioshort upstream investigation (separate P2).
- catchup-script-wide refactor (Fix B touches one line; broader refactor is out of scope).
- any production cron schedule change.

---

_Generated by Phase 1 read-only investigation per Spec 083. Implementation gated on user approval._
