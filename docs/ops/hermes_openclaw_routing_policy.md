# Hermes/OpenClaw Routing Policy

**Version**: 1.0  
**Effective**: 2026-05-15  
**Scope**: All LLM agent scheduling and execution

---

## Principle

> Hermes/OpenClaw is an operating layer around deterministic production code, not a substitute for it.

The gateway is optional for scheduled work. The default path is `tools/run_agent_direct.py`, which routes to Llama 3.3 70B (Together) or Claude (Anthropic) without requiring gateway availability.

---

## Three Lanes

### **Lane A — Deterministic Production**

Runs without any LLM dependency.

```
run_screen.py
production_qa_check.py
13F ingest scripts
post-snapshot supervisor
forward shadow monitors
universe maintenance
rank-change monitor
cron artifact verification
```

**Policy**: No Hermes, no OpenClaw, no model API calls. If Lane A fails, it is a deterministic bug (code, data, cron), not a token/gateway issue.

### **Lane B — Cheap Monitoring & Escalation**

File/JSON checks first. LLM only on anomaly.

```
agent_heartbeat_checks.py (deterministic file checks)
  ↓ (if anomaly detected)
Llama 3.3 70B (Together) via run_agent_direct.py
  ↓ (if severe)
human escalation alert
```

**Policy**: 
- Routine "is artifact fresh?" checks are deterministic (file mtime, JSON last_run field).
- "What does this cron failure mean?" → Llama escalation.
- "Should we trigger Phase 2?" → manual decision.
- Gateway is optional; Llama is primary; human is final.

### **Lane C — High-Token Manual Engineering**

For synthesis, audits, refactoring, knowledge work.

```
Spec-to-code tracing
Multi-file refactors
Test generation
Memory compression
Knowledge graph updates
Closure memos
Audit synthesis
Failure diagnosis (complex)
```

**Policy**: Manual sessions only. Use Hermes/OpenClaw for interactive engineering. Use Claude Opus when token budget allows. No autonomous cron for Lane C.

---

## Routing Rules

| Work | Lane | Default Tool | Gateway? |
|------|------|--------------|----------|
| Production jobs | A | cron (shell/Python) | ❌ Never |
| Routine monitoring | B | `agent_heartbeat_checks.py` | ❌ Never |
| Anomaly escalation | B | `run_agent_direct.py` + Llama | ❌ Optional fallback |
| Manual engineering | C | `run_agent_direct.py` + Claude, or Hermes/OpenClaw | ✅ Interactive use |
| Scheduled LLM agents | B | `run_agent_direct.py` | ❌ No gateway dependency |

---

## Critical Constraint

**No cron job may depend on a gateway token.**

This means:
- Scheduled agents must use `run_agent_direct.py` (auto-routes meta-llama to Together, claude to Anthropic)
- If gateway is down, scheduled agents still run via fallback
- If Both gateway AND direct APIs are down, scheduled agents gracefully degrade (write failure log, alert human)

---

## Agent Authority

All agents operate under one of three authority levels:

| Level | Can Read | Can Write | Can Commit | Can Promote |
|-------|----------|-----------|-----------|------------|
| **Advisor** | ✅ Yes | Audit memos, test files | ✅ (narrow) | ❌ No |
| **Producer** | ✅ Yes | Deterministic artifacts | ✅ (narrow) | ❌ No |
| **Monitor** | ✅ Yes | Heartbeat logs | ❌ (append-only) | ❌ No |

**Forbidden for all unattended agents**:
- Ranker/selector/sizing changes
- Broad crontab edits
- Production model promotion
- Forced snapshot mutation

---

## When to Use Each Lane

### Lane A (Deterministic Production)
- **Always** for batch scoring (run_screen.py)
- **Always** for data ingest (13F, market data, clinical trials)
- **Always** for QA checks (drift, ruleset, phase 2 health)
- **Never** for decision-making that depends on LLM reasoning

### Lane B (Cheap Monitoring)
- Heartbeat checks (file freshness, JSON schema, last-run timestamps)
- Cron artifact verification (did the job run? did it produce expected files?)
- Anomaly detection (forward shadow variance spikes, inst_delta distortion flags)
- Escalation to human or Llama when anomaly found

### Lane C (High-Token Manual)
- "Trace ev_severity_score from compute through to CSV output"
- "Read all Specs 072/091/096/100 and produce blocker graph"
- "Summarize 30 days of agent memory into operational state"
- "Generate tests for Spec 100 forward-return IC tooling"
- "Audit all active cron jobs against expected artifacts"

---

## If Gateway Falls

```
Hermes/OpenClaw → down
  ↓
run_agent_direct.py → routes to Together/Anthropic direct API
  ↓
Direct APIs → down
  ↓
Fallback: deterministic checks + log + human alert
  ↓
Production continues (no model changes, no ranker decisions)
```

**Expected behavior**: System degrades gracefully. Lane A and Lane B baseline checks still run. Lane C work pauses (expected for interactive engineering).

---

## References

- [Token budget policy](token_budget_policy.md)
- [Agent preflight checklist](agent_preflight_checklist.md)
- [AGENT_REGISTRY.json](../../agents/AGENT_REGISTRY.json) — authority levels and llm_policy per agent
- [run_agent_direct.py](../../tools/run_agent_direct.py) — default tool for scheduled LLM agents
- [agent_heartbeat_checks.py](../../agents/agent_heartbeat_checks.py) — Lane B monitoring
