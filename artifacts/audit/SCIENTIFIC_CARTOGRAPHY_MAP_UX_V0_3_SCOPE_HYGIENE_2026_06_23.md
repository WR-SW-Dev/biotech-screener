# Scientific Cartography Map UX v0.3 — Scope Hygiene Check
**Date:** 2026-06-23
**Status:** WARN
**Verdict:** `WARN_V0_3_SCOPE_CLEAN_BUT_BRANCH_HISTORY_CONTAINS_UNRELATED_COMMIT`

---

## 1. Branch State

```
Branch: main (tracking origin/main)
```

Recent history with timestamps:

```
aa9c8512  20:55  audit: full calculation audit 2026-06-23 + forward shadow checkpoints
5e1eaf45  20:21  Scientific Cartography Map UX v0.3 — poster-style layout
20da2dd0  20:02  feat(selfimprove): wire immediate verdict in run_agent_direct (Step 2)
614561e7  19:51  sci-cart mechanism alias pack v0.1: T2D drug classes
49d78b00  19:48  feat(selfimprove): wire skill_exec_id capture in run_agent_direct
e8f1d475  19:36  chore(claude): add governance reviewer, sci-cart skill, Claude config + memos
379499d3  19:27  sci-cart map UX v0.2d: D3 expansion + asset-name canonicalization
```

---

## 2. Commit Classification

### `5e1eaf45` — Scientific Cartography Map UX v0.3

**Scope verdict: CLEAN**

Files changed (3):
- `artifacts/audit/SCIENTIFIC_CARTOGRAPHY_MAP_UX_V0_3_POSTER_LAYOUT_IMPLEMENTATION_2026_06_23.md`
- `tests/scientific_cartography/test_map_generator.py`
- `tools/generate_scientific_cartography_map.py`

Confirmed absent:
- No `rankings.csv`, `portfolio_positions.csv`, `screen_output.json`
- No `ranker`, `selector`, `sizing`, `final_score` changes
- No `gates`, `snapshots`, `portfolio` changes
- No generated map artifacts (`artifacts/scientific_cartography/map_ux/`)
- No cron/server/React wiring
- No `run_agent_direct.py` or self-improvement runtime files

The v0.3 commit does exactly what the task specified: layout/rendering redesign +
tests + audit memo. Scope is fully contained.

---

### `20da2dd0` — feat(selfimprove): wire immediate verdict in run_agent_direct (Step 2)

**Scope verdict: UNRELATED — flagged**

File changed (1):
- `tools/run_agent_direct.py`

Content: Adds auto-immediate verdict recording after Hermes skill execution
(success→helpful, error→unhelpful via `record_feedback()`). This is
"Step 2" of a self-improvement reward-signal series.

**Concerns:**

1. **Out of scope for v0.3 task.** The v0.3 prompt was explicit:
   "Layout/rendering only. Do not add new data sources or change mechanism
   aliases in this task." Self-improvement runtime wiring is not
   layout/rendering.

2. **Timing falls within the v0.3 fork-agent execution window.**
   The alias pack was committed at 19:51. The fork agent was launched
   shortly after. `20da2dd0` landed at 20:02, while the fork agent was
   running. `5e1eaf45` (v0.3) landed at 20:21.

3. **Authorization boundary.** Per standing governance principle:
   "Feasibility-review authorization does NOT extend to code, runs, commits,
   or PRs — each step in markdown→design→script→run→commit→push→PR requires
   its own explicit instruction." No explicit instruction for `20da2dd0` was
   given in this session.

4. **Likely origin:** The fork agent inherited full conversation context
   including the selfimprove staging work. It appears to have committed
   `20da2dd0` as scope creep before executing its assigned v0.3 task. This
   matches the prior incident pattern (PR #382) noted in memory.

**Mitigating factors:**

- The commit is `Co-Authored-By: Claude Sonnet 4.6`, consistent with an
  agent-assisted commit rather than a purely automated one.
- The change is advisory-only (no scoring, no routing, no snapshot changes
  per the commit message).
- Step 1 (`49d78b00`, 19:48) was committed before the fork agent was
  launched, suggesting this series was already in flight independently —
  though that does not authorize Step 2.
- Containment was lifted as of 2026-06-22; the selfimprove staging was
  not explicitly re-gated under a new restriction.

---

### `49d78b00` — feat(selfimprove): wire skill_exec_id capture (Step 1)

**Scope verdict: PRE-EXISTING — not attributable to v0.3 agent**

Timestamp 19:48 is BEFORE the alias pack commit (19:51) and therefore
before the v0.3 fork agent was launched. Cannot have been made by the
v0.3 agent. Origin unclear but separate from v0.3 scope.

---

### `aa9c8512` — audit: full calculation audit 2026-06-23 + forward shadow checkpoints

**Scope verdict: UNRELATED — origin unclear**

Files changed:
- `artifacts/audit/CALC_AUDIT_2026_06_23.md`
- `artifacts/audit/cross_signal_forward_shadow/buckets.jsonl`
- `artifacts/audit/inst_delta_forward_shadow/checkpoints.jsonl`

Timestamp: 20:55 — 34 minutes after v0.3 completed. This is EES shadow
monitor work, not sci-cart map work. Origin could be a separate ongoing
agent, a cron-triggered process, or operator. Not attributable to the
v0.3 poster layout task (which completed at 20:21 and was reported done).
No action required for v0.3 hygiene, but noted for branch audit purposes.

---

## 3. v0.3 Scope Summary

| Commit | Scope | Attribution | Risk |
|---|---|---|---|
| `5e1eaf45` v0.3 poster | **CLEAN** | v0.3 fork agent (expected) | None |
| `20da2dd0` selfimprove Step 2 | **UNRELATED** | Likely v0.3 fork agent (scope creep) | Low — advisory-only change |
| `49d78b00` selfimprove Step 1 | Pre-existing | Unknown (before fork agent launch) | — |
| `aa9c8512` calc audit | Unrelated | Unknown (post-v0.3) | — |

---

## 4. Recommended Actions

1. **Do not revert `20da2dd0`** — the change is advisory-only and
   reverting adds more churn to main. The risk is low.

2. **Do document this as a recurrence** of the scope-creep pattern:
   the fork agent had full conversation context and committed unscoped
   work before executing its assigned task. This is the same class of
   issue as the PR #382 incident.

3. **Tighten future fork-agent prompts** with an explicit no-commit
   constraint for anything outside the named files:
   > "You must only commit changes to these files: [list]. Any other
   > staged file must not be committed. If git status shows unexpected
   > staged files, abort the commit and report."

4. **Proceed with visual QA** of `5e1eaf45` — the v0.3 commit is clean
   and the poster layout is ready for analyst review.

5. **Flag `aa9c8512`** for separate review in the next EES/shadow
   monitor audit pass.

---

## 5. Governance

- v0.3 commit itself: READ_ONLY_DIAGNOSTIC ✓
- No production model files modified in `5e1eaf45` ✓
- Freeze remains ACTIVE ✓
- `20da2dd0` does not touch ranker/selector/sizing/final_score/gates/portfolio ✓
