# Phase 2 Step 3b — Preflight Integration Spec (2026-05-15)

**Purpose**: Wire `tools/agent_preflight.py` into `tools/run_agent_direct.py` to enforce governance before agent execution.

**Status**: Specification only (do NOT implement until Phase 2 Step 3 verification passes 2026-05-19).

---

## Current Architecture

### run_agent_direct.py Flow

```
main()
  ├─ Parse CLI args (--agent, --message, --model, --write-memory)
  ├─ Load .env
  ├─ resolve_model(agent_name, cli_model)
  ├─ run_agent(agent_name, message, model, max_tokens)  ← INTEGRATION POINT
  │    ├─ load_agent_context() → system prompt
  │    ├─ _run_agent_together() or _run_agent_anthropic()
  │    └─ return result
  ├─ maybe_write_memory() if --write-memory
  ├─ Log to JSON
  └─ exit(0 or 1)
```

### Integration Point

**Before** `run_agent()` call (line 303), add preflight check:

```python
# Line 301–302: resolve model
resolved_model = resolve_model(args.agent, args.model)
print(f"Running agent '{args.agent}' (direct SDK, {resolved_model})...")

# NEW: Preflight check (insert here)
# result = run_agent(...)  ← OLD LINE 303
```

---

## Proposed Integration

### Option A: Import & Call (Recommended)

**File**: `tools/run_agent_direct.py`

**New function** (insert after imports, ~line 35):

```python
def run_preflight(agent_name: str) -> dict | None:
    """Run preflight check before agent execution.
    
    Returns preflight report dict if available; None if unavailable.
    On error, logs and returns None (non-blocking).
    """
    preflight_script = PROJECT_ROOT / "tools" / "agent_preflight.py"
    if not preflight_script.exists():
        return None  # preflight not available yet
    
    try:
        import subprocess
        result = subprocess.run(
            [
                "python3",
                str(preflight_script),
                "--agent",
                agent_name,
                "--json",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=PROJECT_ROOT,
        )
        
        if result.returncode == 0:
            return json.loads(result.stdout)
        else:
            # Preflight script failed; log but don't block
            print(f"[PREFLIGHT_WARN] {agent_name}: {result.stderr[:200]}", file=sys.stderr)
            return None
    
    except Exception as e:
        print(f"[PREFLIGHT_WARN] {agent_name}: {str(e)[:200]}", file=sys.stderr)
        return None
```

**Modify main()** (line 301–310):

```python
    resolved_model = resolve_model(args.agent, args.model)
    print(f"Running agent '{args.agent}' (direct SDK, {resolved_model})...")
    
    # NEW: Preflight check
    preflight = run_preflight(args.agent)
    if preflight and preflight.get("status") == "error":
        print(f"\n[PREFLIGHT BLOCKED] {args.agent}", file=sys.stderr)
        print(f"  Current state: {preflight.get('current_branch_state')}", file=sys.stderr)
        print(f"  Not allowed:", file=sys.stderr)
        for item in preflight.get("not_allowed", []):
            print(f"    - {item}", file=sys.stderr)
        return 1  # Exit with error
    
    if preflight and "warnings" in preflight:
        for warn in preflight["warnings"]:
            print(f"[PREFLIGHT_WARN] {warn}", file=sys.stderr)
    
    # OLD LINE 303: run_agent
    result = run_agent(args.agent, args.message, resolved_model, args.max_tokens)
```

---

## Preflight Output Handling

### Report Format (--json)

```json
{
  "timestamp": "2026-05-15T16:14:15Z",
  "current_branch_state": "on main, clean",
  "latest_snapshot": "2026-05-15, QA PASS",
  "git_head": "1c12b6b4 tools: add evening forward-shadow watchdog",
  "blocked_specs": ["Spec 089 KG (deferred...)", ...],
  "contradictions": [],
  "active_quarantine_freeze": ["13F cohort quarantine: ACTIVE", ...],
  "allowed_next_action": "Monitor 13F filing ingest; audit forward shadow freshness...",
  "not_allowed": [
    "Ranker/selector/sizing changes (frozen during cohort quarantine)",
    "Spec 089 KG implementation (deferred pending cohort clearance)",
    ...
  ],
  "agent_metadata": { ... }
}
```

### Decision Rules

1. **If `not_allowed` contains agent's scope** → BLOCK (return 1)
   - Example: agent is "ranker_optimizer", not_allowed includes "Ranker changes"
   - Example: agent is "spec_089_builder", not_allowed includes "Spec 089 KG implementation"

2. **If blocked_specs includes agent's dependencies** → WARN (log but continue)
   - Example: agent depends on "Spec 089", which is BLOCKED
   - Print warning, let agent decide whether to proceed

3. **If contradictions exist** → WARN
   - Print contradictions, let operator review

4. **Otherwise** → PROCEED
   - Run agent normally

---

## Governance Enforcement Matrix

| Agent | LLM Policy | Preflight Check | Allowed If | Blocked If |
|-------|-----------|-----------------|-----------|-----------|
| fleet_steward | manual_only | Required | main, clean | ranker work frozen |
| sentinel | manual_only | Required | main, clean | ranker work frozen |
| herald | none | Optional | always | never |
| postmortem | direct_llama | Optional | anomaly detected | none (deterministic) |
| ranker_optimizer | manual_only | Required | main, clean | ranker work frozen |
| spec_089_builder | manual_only | Required | cohort cleared | cohort quarantine active |

---

## Non-Blocking Preflight (Phase 2 Step 3b+1)

After Phase 2 Step 3b ships, consider **non-blocking mode**:

```python
# After agent runs, emit preflight report as diagnostic
if preflight:
    print(f"\n[PREFLIGHT] {args.agent}")
    print(f"  Branch: {preflight['current_branch_state']}")
    print(f"  Snapshot: {preflight['latest_snapshot']}")
    if preflight.get("contradictions"):
        print(f"  Contradictions: {len(preflight['contradictions'])}")
```

This allows agents to run while surfacing governance awareness.

---

## Testing Plan

**Pre-commit verification** (after May 19):

1. **Agent with llm_policy=none** (herald)
   ```bash
   python3 tools/run_agent_direct.py --agent herald --message "TEST"
   # Should run without preflight
   ```

2. **Agent with llm_policy=manual_only** (fleet_steward)
   ```bash
   python3 tools/run_agent_direct.py --agent fleet_steward --message "TEST"
   # Should check preflight; may warn about "ranker/selector/sizing frozen"
   ```

3. **Preflight unavailable** (edge case)
   - Temporarily rename tools/agent_preflight.py
   - Should warn but continue (non-blocking)
   - Restore and verify

4. **Preflight blocks execution** (integration test)
   - Modify not_allowed list to include fleet_steward
   - Run agent; should exit 1 with clear error
   - Verify log entry

---

## Files Changed

| File | Changes |
|------|---------|
| tools/run_agent_direct.py | +run_preflight() function, +preflight check in main(), import json/sys |
| (no other changes) | preflight.py remains unchanged |
| (no other changes) | AGENT_REGISTRY.json unchanged |

---

## Commit Message Template

```
tools: wire agent_preflight into run_agent_direct (Phase 2 Step 3b)

Enforce governance before agent dispatch. Preflight checks:
- Branch state (main/clean required for certain agents)
- Snapshot freshness (must exist for Lane B/C)
- Blocked/frozen specs (e.g., ranker work frozen, Spec 089 deferred)
- Contradictions (warnings only; non-blocking)
- Agent authority level (used for routing)

Blocking behavior:
- If not_allowed contains agent scope, exit 1 with error
- Otherwise run agent; preflight warnings logged

Non-blocking: preflight unavailable or errors → warn and continue

This ensures no agent action contradicts operational governance
without breaking deterministic or anomaly-escalation paths.

Co-Authored-By: Claude Haiku 4.5 <noreply@anthropic.com>
```

---

## Rollback Plan

If Phase 2 Step 3b introduces unexpected agent blocking:

1. Modify run_preflight() to log-only (print warnings, never return error)
2. Change main() to continue even if preflight recommends blocking
3. Revert to manual preflight review (user runs agent_preflight.py manually)

---

## Next Steps

1. ✅ Phase 2 Step 3 complete (audit memo, watchdog script, crontab, test plan)
2. ⏳ Await May 19 verification (watchdog fires, May 16–17 evening jobs monitored)
3. ⏭️ Phase 2 Step 3b: Implement this spec (commit after May 19 green light)
4. ⏭️ Phase 2 Step 4: Spec 089 KG (post-cohort-clearance, ~May 23)
5. ⏭️ Phase 2 Step 5: KG gating (late phase, after KG validated)

---

**Status**: Specification locked. Ready for implementation post-May-19 verification.
