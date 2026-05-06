# Spec 083 — P0: Agent date-stamp corruption (`policy_shadow_watch`, `bioshort_watch`) (2026-05-06)

**Status:** SCOPED ONLY. No code changes. No cron edits. No agent runs. Ticket scopes investigation + minimal fix plan; implementation requires explicit user approval.

**Origin:** Investment Logic Audit (`artifacts/audit/agent_fleet_investment_logic_audit_2026_05_06.md`), Sections E rows 1–2, F items 3–4, P0 #1.

**Priority:** P0 #1 (highest — investigate before P0 #2 ruleset-ID divergence and P0 #3 `shadow_watch` disposition).

---

## Hard constraints

- Read-only investigation in this ticket. No fixes applied without separate approval.
- Do NOT change cron entries.
- Do NOT change `--as-of-date` resolution semantics anywhere yet.
- Do NOT delete artifacts (the corrupt files are evidence).
- Distinguish two failure modes that look similar but require different fixes:
  - **A. Artifact-timestamp bug** — file mtime is today (2026-05-06) but filename / inner stamp is `2026-01-15` or `2026-01-20`.
  - **B. Stale-upstream bug** — upstream producer hasn't run; agent is faithfully reporting on old data.
- `bioshort_watch` is suspected to have BOTH (A and B); `policy_shadow_watch` may have only A.

---

## 1. Problem statement

Two agents are writing today's artifacts under January date stamps:

### `policy_shadow_watch`
- Cron: `5 18 * * 1-5` invokes `tools/build_policy_shadow_compare.py` with `--as-of-date $(date +%Y-%m-%d)`.
- Recent files in `artifacts/policy_shadow/tier_weighted/`: most-recent inode mtime is 2026-05-06 13:33, but filenames `2026-01-15_comparison.md` and `2026-01-20_comparison.md` predominate.
- Legitimately-named files exist for `2026-05-04` and `2026-05-01` (mtime 2026-05-06 08:04).
- `history.jsonl` last 3 lines all dated `2026-01-15` or `2026-01-20`.
- `tools/cron_evening_catchup.sh:109` invokes `run_agent policy_shadow_watch 1805` — strongly suspected back-loop source.
- Heartbeat flagged STALE on 2026-05-05 ("newest=2026-04-28 (7.4d)") — the agent's verifier is correctly catching the symptom but cannot fix the upstream invocation path.

### `bioshort_watch`
- Cron: weekly Friday 18:10.
- Recent `artifacts/bioshort_watch/*_watch.{json,md}` written 2026-05-06 13:33 with filename stamps `2026-01-15` / `2026-01-20`.
- Latest legitimate-content `_watch.md` body dates 2026-03-26 (>40 days old).
- Upstream `output/hedge_report/hedge_report_2026-03-26.json` is the latest hedge report; no obvious cron writes new ones (out-of-scope for this ticket but flagged).
- Agent's own memory `agents/bioshort_watch/memory/2026-05-03_cron_misescalation_issue.md` documents an entry-point breakage.

---

## 2. Investigation scope

Read-only checks, in this order:

1. **Reproduce the date-stamp bug deterministically.**
   - Read `tools/build_policy_shadow_compare.py` and `tools/biotech_hedge_report.py` (or whichever script `bioshort_watch` invokes).
   - Find every place `--as-of-date` (or its parsed value) becomes a filename component or an inner JSON `as_of_date` field.
   - Identify any path that reads a default value from a config, file, or last-known-good record (rather than respecting the CLI argument).

2. **Audit `tools/cron_evening_catchup.sh` end-to-end.**
   - Specifically the lines that invoke `policy_shadow_watch` (around line 109 per audit memo) and any bioshort invocation.
   - Determine what `--as-of-date` the catchup loop passes — fixed historical date? wrong env var? stale `state.json` lookup?
   - Map every input/output path consumed/written by the catchup invocation vs the primary daily cron invocation.

3. **Distinguish A vs B per agent.**
   - For `policy_shadow_watch`: confirm Mode A (timestamp bug) by checking whether any legitimate `policy_shadow_*` upstream input has `2026-05-06` data — if so, the agent's input is fresh but its output filename is wrong.
   - For `bioshort_watch`: confirm both. Check `output/hedge_report/` mtime distribution; if upstream is stale → Mode B is real even after Mode A is fixed.

4. **Identify back-loop source.**
   - Hypothesis: `cron_evening_catchup.sh` iterates over a "missed dates" list and re-invokes the agent for each date, but a state file or default-arg path resolves to January.
   - Confirm or refute by reading the script and any state file it consults.

5. **Cross-check `history.jsonl`.**
   - Determine whether the corrupt entries are appended (additive bug) or whether they overwrite legitimate ones (destructive bug). Different fix shapes.

---

## 3. Deliverables (this ticket)

A follow-up document at `artifacts/audit/p0_date_stamp_root_cause_2026_05_06.md` with:

1. **Root-cause hypothesis** for each agent (A vs B vs both), with the specific file:line that produces the wrong stamp.
2. **Files/functions likely touched** by a fix:
   - `tools/build_policy_shadow_compare.py` (function names that handle `--as-of-date`)
   - `tools/cron_evening_catchup.sh` (line numbers)
   - `tools/biotech_hedge_report.py` (or actual bioshort entry point)
   - any state file (`state/`, `production_data/cron_state*.json`, etc.) that holds a stale "last-as-of"
3. **Minimal fix plan** — smallest diff that fixes the date-stamp bug without changing schedule/scope. Two separable diffs:
   - Diff 1: stop writing wrong stamps (CLI arg respected → filename + inner JSON).
   - Diff 2: stop the back-loop in `cron_evening_catchup.sh` if it's a separate root cause.
4. **Tests / smoke command** — exact one-liner that, after the fix, demonstrates the agent writes today's date when invoked with `--as-of-date $(date +%Y-%m-%d)`. Should be runnable from the user's WSL host without a full snapshot rebuild.
5. **Rollback path** — for each diff:
   - Pre-state evidence (file SHA, line numbers).
   - Revert command (single `git revert <sha>` or named commit).
   - "What breaks if rolled back" assessment (likely: nothing — current state already broken).
6. **Stale-upstream separability** — explicit note on whether `bioshort_watch` Mode B (upstream stale) is fixable as part of this ticket or punts to a different P2 ticket; default expectation: PUNT, since `output/hedge_report/` producer identification is not a fleet-agent issue.

---

## 4. Out of scope for this ticket

- Any actual fix.
- Any cron change.
- Identifying or restoring the `output/hedge_report/` upstream producer (separate P2).
- Any other agent's date handling.
- Heartbeat suppression for the affected agents.

---

## 5. Risk if implementation later proceeds

- **Low risk** if the fix is a simple CLI-arg passthrough: behavior change is bounded to two agents, both shadow / governance only, no production scoring impact.
- **Medium risk** if the fix touches `cron_evening_catchup.sh` shared logic that other agents depend on — must confirm no other agent's catchup-path date handling regresses.
- **Reversible** — agents are observe_only (`policy_shadow_watch`) and observe_only/research-shadow (`bioshort_watch`). Rolling back would just re-introduce the date-stamp bug, not break production.

---

## 6. Acceptance for closure (when implementation later happens)

1. After fix lands and one full weekday cron cycle, `policy_shadow_watch` writes `artifacts/policy_shadow/tier_weighted/2026-MM-DD_comparison.md` with today's date in both filename and inner content.
2. `history.jsonl` last 3 entries all date to today's run.
3. Heartbeat STALE alert clears within one cycle.
4. `bioshort_watch` Mode A fixed (correct filename); Mode B remains until `output/hedge_report/` upstream is restored — this ticket does not block on that.
