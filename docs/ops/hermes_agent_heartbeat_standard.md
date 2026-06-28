# Hermes Agent Heartbeat Standard

Defines the minimal heartbeat + report artifacts every supervised Hermes agent
must write after each run. Consumed by `tools/agent_heartbeat_checks.py` and
`tools/hermes_agent_health.py`.

---

## Required artifacts

### 1. `latest_heartbeat.json` (machine-readable)

Location: `artifacts/governance/<agent_id>/latest_heartbeat.json`  
Written: after every run, even partial runs  
Schema:

```jsonc
{
  "agent_id": "<agent-id>",         // matches AGENT_REGISTRY.json key
  "run_ts": "<ISO8601 UTC>",        // e.g. "2026-06-26T08:05:00.000000+00:00"
  "as_of_date": "YYYY-MM-DD",       // wall-clock date of run
  "status": "<STATUS>",             // see status enum below
  "schema": "<schema_name>.v<N>"    // e.g. "hermes_skill_sync_audit.v1"
}
```

**Status enum:**

| status | Meaning |
|---|---|
| `OK` | Run completed; no anomalies |
| `WARN` | Completed with non-blocking warnings |
| `FAIL` | Completed with blocking failures |
| `ERROR` | Run aborted by exception |
| `SKIP` | Run skipped (e.g. no new data) |
| `DRIFT_WARNING` | Domain-specific: drift detected, non-critical |
| `DRIFT_CRITICAL` | Domain-specific: drift detected, critical |

**Required additional fields (domain-specific — add as needed):**

```jsonc
{
  // Numeric counters (always include even if 0)
  "n_critical": 0,
  "n_warning": 0,
  "n_info": 0,

  // Boolean flags
  "sync_ran": false,

  // Lists or arrays (never null — use [] for empty)
  "sync_files_changed": []
}
```

---

### 2. `<agent_id>_YYYY_MM_DD.md` (human-readable report)

Location: `artifacts/governance/<agent_id>/`  
Written: after each run  
Naming: `<agent_id>_2026_06_26.md` (date = `as_of_date` from heartbeat)  
Content: free-form markdown; must contain at minimum:

```markdown
# <Agent Name> — Run Report YYYY-MM-DD

**Status:** <STATUS>  
**Run time:** <ISO8601>

## Summary

<One paragraph or table>

## Findings

<Details; use sections Critical / Warning / Info if applicable>

## Actions taken

<What the agent did: files written, syncs performed, notifications sent>
```

---

### 3. `HEARTBEAT.md` (agent-local protocol doc)

Location: `agents/<agent_id>/HEARTBEAT.md`  
Purpose: explains what the agent's heartbeat JSON fields mean  
Written: once (static documentation); only update when schema changes

---

## Heartbeat freshness thresholds

Used by `check_<agent_id>()` in `agent_heartbeat_checks.py`:

| Cadence | MISS threshold (→ WARN) | FAIL threshold |
|---|---|---|
| `daily_*` | 2 days | 3 days |
| `weekly` | 8 days | 10 days |
| `on_demand` | N/A (not checked) | N/A |

---

## Fleet receipt roll-up

`tools/hermes_agent_health.py --mode report` reads every agent's `latest_heartbeat.json`
and produces a one-line status per agent. Fleet verdict:

| Condition | Verdict |
|---|---|
| Any agent status=`FAIL` or `ERROR` | **RED** |
| Any agent status=`WARN` or `DRIFT_WARNING` | **AMBER** |
| Any expected heartbeat missing (agent is supervised, no file) | **RED** |
| All agents OK | **GREEN** |

---

## Adding heartbeat to a new agent

1. Write `agents/<agent_id>/HEARTBEAT.md` documenting the fields
2. After run completion, write `artifacts/governance/<agent_id>/latest_heartbeat.json`
3. Write dated report to `artifacts/governance/<agent_id>/<agent_id>_YYYY_MM_DD.md`
4. Add `check_<agent_id>()` to `tools/agent_heartbeat_checks.py` → `SPECIALIZED_CHECKS`
5. Set `supervised_by_orchestrator: true` in `AGENT_REGISTRY.json`

---

## Town notification

Heartbeat failures should send Town events via `send_operator_event()`:

```python
send_operator_event(
    channel="town",
    severity="FAIL",
    event_type="cron_missed",          # or agent-specific type
    title=f"<agent_id>: run FAILED",
    summary="<detail>",
    artifact="artifacts/governance/<agent_id>/latest_heartbeat.json",
    next_operator_action="investigate"
)
```

See `docs/hermes_skills/town-operator-bridge.md` for event types and API.

---

## References

- Registry: `agents/AGENT_REGISTRY.json`
- Health board: `tools/hermes_agent_health.py`
- Heartbeat checks: `tools/agent_heartbeat_checks.py`
- Example: `agents/hermes-skill-sync-agent/HEARTBEAT.md` + `artifacts/governance/hermes_skill_sync/latest_heartbeat.json`
