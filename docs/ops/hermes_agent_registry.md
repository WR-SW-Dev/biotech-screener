# Hermes Agent Registry — Governance Reference

**Canonical file:** `agents/AGENT_REGISTRY.json`  
**Schema version:** 1.0  
**Tests:** `tests/test_agent_registry.py`

---

## Purpose

`AGENT_REGISTRY.json` is the single source of truth for every agent directory under `agents/`. It serves three functions:

1. **Audit surface** — every agent must appear here exactly once; test suite enforces this
2. **Orchestrator input** — `agent_heartbeat_checks.py` reads this to decide which agents to supervise
3. **Authorization record** — `authority_level` and `permission_tier` fields gate what each agent may touch

---

## Schema

```jsonc
{
  "schema_version": "1.0",
  "as_of": "YYYY-MM-DD",
  "agents": {
    "<agent_id>": {
      // Required fields
      "role": "<one-line description>",
      "category": "<enum: see below>",
      "cadence": "<enum: see below>",
      "status": "<enum: see below>",
      "artifact_paths": ["<relative-repo-path>/"],
      "authority_level": "<enum: see below>",
      "llm_policy": "<enum: see below>",
      "requires_preflight": true,
      "supervised_by_orchestrator": true,
      "owner": "<team or role>",
      "notes": "",

      // Optional fields
      "permission_tier": 0,            // integer 0–4; if absent, derived from authority_level
      "cron_enabled": false,           // true when Hermes cron job is registered
      "hermes_job_id": "",             // Hermes cron job ID (e.g. "49b6a56cc6ee")
      "sunset_review_date": "",        // YYYY-MM-DD; for suppressed agents
      "merged_into": ""                // canonical agent ID if this dir was merged
    }
  }
}
```

---

## Enums

### category

| Value | Meaning |
|---|---|
| `control_plane` | Orchestrator, supervisor, governance agents |
| `signal_monitor` | Live signal watchers (price, catalyst, shorts) |
| `data_ingestion` | Raw data fetch and normalization |
| `research` | IC/calibration/evidence agents |
| `portfolio_risk` | Portfolio and risk monitoring |

### cadence

| Value | Staleness threshold |
|---|---|
| `daily_after_production` | 2 days |
| `daily_premarket` | 2 days |
| `intraday` | 1 day |
| `weekly` | 10 days |
| `on_demand` | N/A (skipped by freshness checks) |
| `unknown` | N/A (skipped) |

### status

| Value | Meaning |
|---|---|
| `active` | Running; supervised by orchestrator if `supervised_by_orchestrator: true` |
| `shadow` | Runs but output is observation-only; no production wiring |
| `suppressed` | Disabled; cron removed; code retained |
| `deprecated` | Directory kept for history; `supervised_by_orchestrator: false`; tombstone fields set |

### authority_level (maps to permission_tier)

| authority_level | Tier | What the agent may do |
|---|---|---|
| `observe_only` | 0 | Read repo, read snapshots, write to own `artifact_paths` only |
| `observe_and_propose` | 1 | Tier 0 + write spec proposals / pending-approval files |
| `write_artifacts` | 2 | Tier 1 + write to `artifacts/` dirs outside own path |
| `mutate_data` | 3 | Tier 2 + modify `data/` (snapshots, joined tables) |
| `mutate_config` | 4 | Tier 3 + modify config, cron, workflows |

### llm_policy

| Value | Meaning |
|---|---|
| `none` | Deterministic only; no LLM calls |
| `direct_llama_on_anomaly` | LLM invoked on anomaly detection |
| `manual_only` | LLM invoked only on operator command |

---

## Tombstone pattern (deprecated agents)

When an agent is retired:

1. Set `status: deprecated`
2. Set `requires_preflight: false`
3. Set `supervised_by_orchestrator: false`
4. Set `artifact_paths: []`
5. Add `notes` with removal commit hash and reason

The test suite enforces that a deprecated agent's directory need not exist, but a non-deprecated agent's directory **must** exist.

---

## Lifecycle transitions

```
active → suppressed  (disable cron; keep code; set supervised_by_orchestrator: false)
active → shadow      (wire shadow_monitor; no production writes)
suppressed → deprecated  (after sunset_review_date passes; clear artifact_paths)
deprecated → active  (requires explicit operator decision + new spec)
```

---

## Adding a new agent

1. Create `agents/<agent_id>/` directory with at least one file (`run_job.py`, `HEARTBEAT.md`, or `README.md`)
2. Add entry to `AGENT_REGISTRY.json`
3. Set `supervised_by_orchestrator: true` if the daily fleet receipt should monitor it
4. Add `check_<agent_id>` function to `tools/agent_heartbeat_checks.py` → `SPECIALIZED_CHECKS` (or rely on `check_generic_freshness` fallback)
5. Run `pytest tests/test_agent_registry.py` — must pass

---

## Invariants (test-enforced)

- Every non-deprecated directory under `agents/` is registered
- Every non-deprecated registered entry has a corresponding directory
- `authority_level` values are from the allowed enum
- `status` values are from the allowed enum
- `supervised_by_orchestrator: false` entries are either `status: suppressed/deprecated` or have an explicit `notes` justification

---

## References

- Permission tiers detail: `docs/ops/hermes_permission_tiers.md`
- Heartbeat standard: `docs/ops/hermes_agent_heartbeat_standard.md`
- Health board: `tools/hermes_agent_health.py`
- Path guard: `tools/hermes_path_guard.py`
- Tests: `tests/test_agent_registry.py`, `tests/test_hermes_agent_hardening.py`
