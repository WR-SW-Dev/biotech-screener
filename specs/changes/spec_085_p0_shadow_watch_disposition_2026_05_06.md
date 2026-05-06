# Spec 085 — P0: `shadow_watch` disposition (finish cutover vs retire) (2026-05-06)

**Status:** SCOPED ONLY. No code changes. No deletions. No cron edits. No agent runs. Decision memo + safe implementation plan; both finish-cutover and retire paths must be designed before either is taken.

**Origin:** Investment Logic Audit (`artifacts/audit/agent_fleet_investment_logic_audit_2026_05_06.md`), Section A risk #4 / cleanup #1, Section D group 1, Section F item 2, Section I P0 #3.

**Priority:** P0 #3 (after P0 #1 date-stamp corruption and P0 #2 ruleset-ID divergence — neither prerequisite blocks this ticket, but the priority order reflects user direction).

---

## Hard constraints

- Do NOT delete `agents/shadow_watch/`.
- Do NOT modify `agents/AGENT_REGISTRY.json`.
- Do NOT touch cron entries (no add, no remove, no comment).
- Do NOT retire `shadow_monitor` or `policy_shadow_watch` until disposition is decided AND user approves.
- Do NOT silence either successor's heartbeat.
- Investigation may read agent code, configs, registry, cron, memory, and artifacts — nothing else.

---

## 1. Problem statement

`agents/shadow_watch/` is documented in `AGENT_REGISTRY.json` as the "merged successor" of `shadow_monitor` + `policy_shadow_watch` but is **half-built**:

- Directory exists.
- `supervised_by_orchestrator=false`, `status=shadow`.
- No `agents/shadow_watch/memory/` subdirectory despite registry claiming the path.
- No cron entry invokes it.
- No artifacts exist under any path it would write to.
- Registry note: "Merged successor … not yet wired into cron."

Meanwhile, both predecessors continue to fire:

- `shadow_monitor` — daily 18:25 LLM call (`--write-memory`), persistent WARN MAX_DRAWDOWN.
- `policy_shadow_watch` — daily 18:05 (currently affected by P0 #1 date-stamp corruption).

This is the worst possible state: cost is paid for both predecessors, but the merge is incomplete so the consolidated view doesn't exist either. Two viable paths:

- **Path A — Finish cutover:** complete `shadow_watch` so it does the union of both predecessors' jobs, then retire predecessors.
- **Path B — Retire `shadow_watch`:** keep predecessors (with P0 #1 fixed), remove the half-built merger.

---

## 2. Investigation scope

### 2.1 Comparison matrix

Read each agent's entry-point script, config, and most recent artifacts. Build a table:

| dimension | `shadow_watch` | `shadow_monitor` | `policy_shadow_watch` |
|---|---|---|---|
| status | shadow / not wired | active | active |
| cron | none | 18:25 daily M-F | 18:05 daily M-F |
| entry point | `agents/shadow_watch/...` | `tools/build_shadow_monitor.py` | `tools/build_policy_shadow_compare.py` |
| inputs (snapshot fields, files) | TBD | TBD | TBD |
| outputs (artifacts, paths) | none yet | `artifacts/shadow_monitor/{date}_monitor.{json,md}` | `artifacts/policy_shadow/tier_weighted/{date}_comparison.{json,md}`, `history.jsonl` |
| consumers (grep `import` / artifact paths) | none | `agent_heartbeat_checks.py:check_shadow_monitor`, `ops_supervisor` | `tools/eval_policy_candidate.py`, manual review |
| LLM step? | TBD (likely yes if planned as merged) | yes (`--write-memory`) | no (deterministic) |
| memory writes | none | `agents/shadow_monitor/memory/` | none |
| authority level | observe_only (registry) | observe_only | observe_only |
| failure modes today | not running | persistent WARN | date-stamp corruption (P0 #1) |

### 2.2 Coverage analysis

Determine: does the union of `shadow_monitor` + `policy_shadow_watch` outputs cover the SAME analytical surface the merged `shadow_watch` would cover, or is there scope drift?

- If `shadow_watch` was designed to cover NEW territory that neither predecessor covers, retire is the wrong call.
- If `shadow_watch` is a superset of both predecessors' outputs (just consolidated), retire is plausible.
- If `shadow_watch` is a subset (lighter-weight summary), neither path is satisfying — flag for human decision.

### 2.3 Consumer impact analysis

For each consumer of `shadow_monitor` and `policy_shadow_watch`, determine whether the consumer would need rewiring under each path:

- Path A (finish cutover): every consumer must be rewired to read `shadow_watch` outputs OR the merged outputs must be a superset that includes the predecessors' artifact paths as a transitional measure.
- Path B (retire `shadow_watch`): no consumer changes; predecessors continue.

### 2.4 Cost comparison

Estimate (qualitative, not full cost-per-call):

- LLM calls / day for current state (both predecessors).
- LLM calls / day for Path A (single merged).
- LLM calls / day for Path B (predecessors, status quo).

Path A is only attractive if it materially reduces LLM burn AND provides at least equivalent coverage.

### 2.5 Documentation review

Look for:

- Any spec in `specs/changes/` mentioning the merger's design.
- Any memory file in `~/.claude/projects/-home-arrenchulz/memory/` referencing the merger.
- Any commit in git history touching `agents/shadow_watch/`.
- Any TODO/FIXME comments in `agents/shadow_watch/` or related code.

---

## 3. Deliverables (this ticket)

A disposition memo at `artifacts/audit/p0_shadow_watch_disposition_2026_05_06.md` containing:

1. **Recommendation: KEEP / FINISH-MERGE / RETIRE.** One choice, with rationale tied to the §2.2 coverage analysis.
2. **Evidence** — the comparison matrix from §2.1, the consumer map from §2.3, the cost note from §2.4.
3. **Safe implementation plan for the chosen path** (do NOT execute):
   - **Path A (finish cutover)** plan:
     - Steps to wire `shadow_watch` into cron, with specific cron line.
     - Steps to migrate consumers from predecessor artifacts to `shadow_watch` artifacts (file paths, expected fields).
     - Steps to retire predecessors safely (mark deprecated in registry → remove from cron after one observation week → delete agent directories after another observation week).
     - Rollback at each step.
   - **Path B (retire `shadow_watch`)** plan:
     - Steps to mark `shadow_watch` as REMOVED in `AGENT_REGISTRY.json`.
     - Steps to delete the directory.
     - Confirm no consumer would break.
     - Rollback (single `git revert`).
   - **Path C (KEEP — defer)** plan:
     - Document the half-built state in registry status field as "blocked on X" with explicit blocker description.
     - Add a tickler memory entry to revisit on a date.
4. **Decision dependencies** — flag whether the decision is contingent on anything outside this ticket:
   - Does fixing P0 #1 (date-stamp corruption) change the calculus? (e.g., if `policy_shadow_watch` becomes healthy after the fix, the case for keeping it strengthens).
   - Are there pending Specs that intend to consume `shadow_watch` outputs?
5. **Risk register** — for each path, the failure modes that would surface within one observation week.

---

## 4. Out of scope for this ticket

- Any agent retirement, deletion, or registry edit.
- Any cron change.
- Any heartbeat suppression for `shadow_monitor` or `policy_shadow_watch`.
- Code changes to wire the cutover.
- Building `shadow_watch` features.

---

## 5. Risk if implementation later proceeds

- **Path A risk** — incomplete cutover regresses governance coverage; predecessors' consumers (heartbeat, `ops_supervisor`, `eval_policy_candidate.py`) break if not rewired before predecessors retire.
- **Path B risk** — low; `shadow_watch` has no consumers and no artifacts. Removing it is reversible via git.
- **Path C risk** — pays cost of both predecessors indefinitely; future maintainer re-encounters the same half-built state.

All three paths preserve the freeze regime — none touch selector/ranker/EV.

---

## 6. Acceptance for closure (when implementation later lands)

- **Path A:** `shadow_watch` produces daily artifacts, all predecessor consumers verified to either read from new path OR be retired. Two-week stable observation. `AGENT_REGISTRY.json` shows `shadow_watch` active and predecessors deprecated.
- **Path B:** `agents/shadow_watch/` removed; registry updated. `shadow_monitor` and `policy_shadow_watch` continue functioning (P0 #1 fix prerequisite).
- **Path C:** registry status field updated with explicit blocker description; tickler entry recorded.
