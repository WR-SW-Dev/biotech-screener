# Token Budget Policy

**Version**: 1.0  
**Effective**: 2026-05-15  
**Scope**: All scheduled and manual LLM work

---

## Principle

Use the **cheapest deterministic solution first**. Only escalate to expensive models when deterministic checks cannot answer the question.

```
Deterministic check
  ↓ (if anomaly)
Llama 3.3 70B (Together, cheap)
  ↓ (if hard synthesis required)
Claude Opus (Anthropic, expensive, manual only)
```

---

## Token Tiers

| Tier | Tool | Cost | When to Use |
|------|------|------|------------|
| **Tier 0** | Bash, Python, JSON checks | $0 | Artifact freshness, schema validation, diff size |
| **Tier 1** | Llama 3.3 70B (Together) | ~$0.20 per 1M tokens | Anomaly diagnosis, missing artifact detection, cron failure drill-down |
| **Tier 2** | Claude Sonnet (Anthropic) | ~$0.90 per 1M tokens | Structured synthesis, test generation, narrow refactors |
| **Tier 3** | Claude Opus (Anthropic) | ~$3.00 per 1M tokens | Spec-to-code tracing, multi-file audits, complex knowledge work, memory compression |

---

## Tier 0: Deterministic Checks (Do This First)

**Examples**:
- Is `rankings.csv` newer than `production_qa_check.py` last run?
- Does `institutional_summary.json` have > 0 bytes?
- Did `forward_shadows/*.jsonl` update in the last 24 hours?
- Are there uncommitted files? (`git status --short`)
- Is the latest commit on `origin/main`? (`git rev-parse HEAD` vs `git rev-parse origin/main`)
- How many lines in `13f_cohort_status_2026_05_15.md`?
- What is the last line of `run_screen.py` log?

**Tool**: `agent_heartbeat_checks.py` (file mtime, JSON schema, commit hashes, line counts, grep patterns)

**Cost**: <1 second, ~0 tokens

**When escalate to Tier 1**: If Tier 0 detects:
- Artifact missing (expected but not found)
- Artifact stale (not updated in expected window)
- Schema violation (JSON parse fails, required field missing)
- Cron job did not run (log missing or timestamp very old)

---

## Tier 1: Llama 3.3 70B (Together) for Escalation

**Examples**:
- "Why did `post_snapshot_supervisor` timeout on 2026-05-07? Is it likely to happen again?"
- "I see 6/48 13F managers filed. Are we on track for cohort clearance by May 23?"
- "The forward_shadows diverged (inst_delta up 0.02, cross_signal down 0.01). Is this coherent or an anomaly?"
- "Explain why Spec 089 is deferred in one paragraph."
- "Generate a one-line commit message for the operational closure."

**Tool**: `run_agent_direct.py` + Llama 3.3 70B (Together)

**Cost**: ~$0.20 per 1M tokens (~2–5 min per diagnostic query)

**When escalate to Tier 2/3**: If Tier 1 output is:
- "I don't have enough context to answer this" (need Opus reasoning)
- Requires reading multiple files or git history (narrow Sonnet or escalate to Opus)
- Requires generating structured code or tests (Sonnet+)

---

## Tier 2: Claude Sonnet (Structured Synthesis)

**Examples**:
- "Generate a Python script to check if forward_shadows ran in the last 24 hours."
- "Write 5 unit tests for `agent_preflight.py`."
- "Summarize Spec 089 Phase 1.5A design and lock the schema."
- "Refactor `run_agent_direct.py` to split routing logic into a helper function."
- "Generate a checklist of questions to audit Spec 100 forward-return IC tooling."

**Tool**: Claude Sonnet 4.6 (Anthropic) via `run_agent_direct.py` or manual session

**Cost**: ~$0.90 per 1M tokens (~1–10 min per task)

**When escalate to Tier 3**: If Tier 2 output is:
- Incomplete or requires significant integration
- Needs multi-file tracing (git blame, cross-file logic)
- Requires knowledge compression (30+ days of memory → 1 page operational summary)
- Needs complex architectural decisions (ranker governance KG design)

---

## Tier 3: Claude Opus (Manual High-Token Engineering)

**Examples**:
- "Trace ev_severity_score from definition in `common/` through all uses in ranker, selector, and output CSV. Identify all touching files."
- "Read Specs 072, 091, 096, 100, 089 and produce a blocker graph showing dependencies."
- "Compress 30 days of agent memory (operational memos, spec closures, audit logs) into a 2-page executive summary."
- "Audit all 19 active cron jobs against their expected artifacts and report gaps or stale runs."
- "Design the schema for Spec 089 knowledge graph: node types, edge types, contradiction rules."

**Tool**: Claude Opus 4.7 (Anthropic) via manual Hermes/OpenClaw session or high-token `run_agent_direct.py` call

**Cost**: ~$3.00 per 1M tokens (~5–30 min per complex task)

**When use**: 
- Once per spec for "read all and synthesize"
- Once per major refactor for cross-file tracing
- Once per month for memory compression
- When unblocking a critical path (e.g., Spec 089 design was worth the token cost)

**Never use Tier 3 for**:
- Routine QA pass/fail (Tier 0)
- "Is artifact X fresh?" (Tier 0 or Tier 1)
- Daily heartbeat checks (Tier 0)
- Repeated summaries (compress to memory once, then reference)

---

## Decision Tree

```
Question or task arises
  │
  ├─→ Can deterministic script answer it? (file mtime, JSON schema, grep, git log)
  │     └─→ YES: Use Tier 0 (Bash/Python/JSON checks)
  │
  ├─→ Is it an anomaly diagnosis or escalation from Tier 0?
  │     └─→ YES: Use Tier 1 (Llama 3.3 70B, ~$0.20 per 1M tokens)
  │
  ├─→ Does it require generating structured code, tests, or narrow synthesis?
  │     └─→ YES: Use Tier 2 (Claude Sonnet, ~$0.90 per 1M tokens)
  │
  └─→ Does it require multi-file tracing, architectural decisions, or knowledge synthesis?
        └─→ YES: Use Tier 3 (Claude Opus, ~$3.00 per 1M tokens, manual only)
```

---

## Budget Targets (Monthly)

For this project (341 tickers, ~20 agents, daily production):

| Tier | Monthly Budget | Typical Use |
|------|----------------|-------------|
| **Tier 0** | $0 | Unlimited |
| **Tier 1** | $50–100 | ~5–10 anomaly escalations/week |
| **Tier 2** | $30–60 | ~2 synthesis tasks/week (specs, tests, refactors) |
| **Tier 3** | $100–200 | ~1 major architectural task/month, memory compression |
| **Total** | **~$200–400/month** | Sustains current ops + planned engineering |

**Assumption**: Tier 0 catches 90% of work (deterministic), Tier 1 escalates 8% (anomalies), Tier 2 handles 1.5% (synthesis), Tier 3 handles 0.5% (hard design).

---

## Implementation

### For Scheduled Agents (Lane B)

```python
# run_agent_direct.py default behavior
if anomaly_detected(heartbeat_checks):
    # Tier 0 detected anomaly
    result = llama_query("Diagnose this cron failure")  # Tier 1
    if result["severity"] > threshold:
        alert_human()  # Operator decides next step
else:
    log("Heartbeat OK, no escalation needed")
```

### For Manual Sessions (Lane C)

Start with a question:
- "Is this Tier 0/1/2/3?" (use decision tree above)
- If Tier 3: explicitly authorize in memory or CLAUDE.md
- If Tier 2: scope narrowly (don't tokenmax for trivial work)
- If Tier 1: use Llama; escalate to Opus only if Llama says "I need more context"

---

## Audit & Review

**Monthly**: Review token usage by tier and by agent.
- Are Tier 0 checks catching what they should?
- Are Tier 1 escalations justified?
- Are any Tier 3 tasks being repeated (should be compressed to memory instead)?

**Quarterly**: Adjust tier thresholds if anomaly patterns change.

---

## References

- [Hermes/OpenClaw routing policy](hermes_openclaw_routing_policy.md)
- [Agent preflight checklist](agent_preflight_checklist.md)
- [agent_heartbeat_checks.py](../../agents/agent_heartbeat_checks.py) — Tier 0 implementation
- [run_agent_direct.py](../../tools/run_agent_direct.py) — routing to Tier 1 and above
