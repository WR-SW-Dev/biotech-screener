# Phase 2 Step 3b — Preflight Integration Completion (2026-05-15)

**Status**: ✅ COMPLETE AND TESTED

**Commit**: `f29f53ed` — tools: wire agent_preflight into run_agent_direct (Phase 2 Step 3b)

---

## Implementation Summary

Integrated `tools/agent_preflight.py` governance checks into `tools/run_agent_direct.py` to enforce operational governance before agent execution.

### Changes

**`tools/run_agent_direct.py`:**
- Added `import subprocess` and `import sys`
- Added `_AGENT_SCOPE_KEYWORDS` dict mapping agents to governance scope keywords
- Added `run_preflight(agent_name) -> dict | None` function
  - Spawns `agent_preflight.py --json` as subprocess
  - Returns parsed preflight report or None (non-blocking on error)
  - Timeout: 10 seconds
- Added `--skip-preflight` CLI flag for override/rollback
- Integrated preflight check in `main()` before agent dispatch
  - **Blocking**: If agent scope keyword matches `not_allowed` list, exit 1
  - **Warning**: Print contradictions and blocked specs to stderr, continue
  - **Non-blocking**: Preflight unavailable → warn and continue
- Include preflight result in JSON log for audit trail
- Updated module docstring with usage examples and governance behavior

**`tests/test_run_agent_direct.py`:**
- Added `test_preflight_blocks_scoped_agent()` — verifies exit 1 when scope blocked
- Added `test_preflight_warns_but_proceeds_on_contradiction()` — verifies warnings printed, agent runs
- Added `test_preflight_unavailable_is_non_blocking()` — verifies agent runs when preflight unavailable

### Behavior

**Scoped Agents** (require preflight enforcement):
- `fleet_steward` — blocked if "Ranker/selector/sizing" in not_allowed
- `sentinel` — blocked if "Ranker/selector/sizing" in not_allowed
- `spec_089_builder` — blocked if "Spec 089" in not_allowed
- `ranker_optimizer` — blocked if "Ranker/selector/sizing" in not_allowed

**Unscoped Agents** (no blocking):
- `herald`, `ops`, `calibration`, etc. — run normally, preflight logged

**Exit Codes**:
- 0 = agent ran successfully (or blocked but --skip-preflight used)
- 1 = agent execution blocked by preflight, or agent error

---

## Verification Results

### Unit Tests: 5/5 PASS

```
test_main_returns_nonzero_when_agent_run_errors PASS
test_log_filename_is_unique_for_same_second_reruns PASS
test_preflight_blocks_scoped_agent PASS
test_preflight_warns_but_proceeds_on_contradiction PASS
test_preflight_unavailable_is_non_blocking PASS
```

### Integration Tests: ✅ PASS

1. **Blocking Agent** (`sentinel` without --skip-preflight):
   ```
   [PREFLIGHT BLOCKED] sentinel
     Branch: on main, dirty
     - Ranker/selector/sizing changes (frozen during cohort quarantine)
   Exit code: 1
   ```

2. **Passing Agent** (`herald` with preflight enabled):
   ```
   [PREFLIGHT_WARN] contradiction: ...
   Running agent 'herald' (direct SDK, meta-llama/Llama-3.3-70B-Instruct-Turbo)...
   [agent output...]
   Logged: logs/agents_direct/herald_20260515_164624_780473_dc142beb.json
   Exit code: 0
   ```

3. **Preflight in Log**: ✅ Verified
   - Log includes complete preflight report
   - Fields: timestamp, branch_state, snapshot, git_head, blocked_specs, contradictions, quarantine_freeze, allowed_action, not_allowed, agent_metadata

4. **--skip-preflight Override**: ✅ Verified
   ```
   python3 tools/run_agent_direct.py --agent ops --message HEARTBEAT --skip-preflight
   Running agent 'ops' (direct SDK, meta-llama/Llama-3.3-70B-Instruct-Turbo)...
   [agent output...]
   Exit code: 0
   ```

---

## Design Notes

### Why Non-Blocking?

Preflight tool failures (subprocess timeout, JSON parse error, script missing) are logged but don't block execution. This allows:
- Lane A (deterministic) to always run
- Lane B agents to escalate on anomalies even if preflight unavailable
- Rollback on preflight bugs without cron downtime

### Scope Keyword Matching

Simple substring matching: if any agent scope keyword appears in any not_allowed item, agent is blocked. Examples:
- Agent: `fleet_steward`, Scope: `["Ranker/selector/sizing"]`, Not Allowed: `"Ranker/selector/sizing changes (frozen..."` → **BLOCKED**
- Agent: `ops`, Scope: `[]`, Not Allowed: `"Ranker changes"` → **PROCEED** (no scope)
- Agent: `herald`, Scope: `[]`, Not Allowed: `"Ranker changes"` → **PROCEED** (no scope)

### Audit Trail

All preflight reports (including warnings, contradictions, blocked specs) are persisted in JSON logs. Operators can trace governance decisions post-hoc:
```bash
jq '.preflight | {blocked_specs, contradictions, not_allowed}' logs/agents_direct/*.json
```

---

## Next Steps

**Phase 2 Step 4** (post-May-19 green light):
- Evening cron reliability watchdog verification (May 16–19)
- Spec 089 KG implementation (pending 13F cohort clearance ~May 23)

**Phase 2 Step 5** (post-KG validation):
- KG gating enforcement

---

## Rollback Plan

If preflight causes unexpected blocking:
1. Modify `run_preflight()` to always return None (disable check)
2. Revert to `--skip-preflight` for cron agents
3. Manual governance review until root cause resolved

```bash
git revert f29f53ed  # Revert this commit
```

---

**Signed off by**: Phase 2 Step 3b implementation  
**Date**: 2026-05-15  
**Spec**: `artifacts/audit/phase_2_step_3b_preflight_integration_spec_2026_05_15.md`
