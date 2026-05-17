# Agent Governance — Hermes/OpenClaw System

**Version:** 1.0.0  
**Last updated:** 2026-05-17  
**Status:** Active (Phases 1–3 deployed, Phase 4+ roadmap locked)  
**Scope:** 30-agent fleet (28 active/shadow, 2 deprecated); biotech screening deterministic + monitoring + research

---

## I. Principles

### Core Principle

> **Hermes/OpenClaw is an operating layer around deterministic production code, not a substitute for it.**

Corollary: Lane separation enforces this. Deterministic paths run without LLM. Anomalies escalate via bounded gates. Research happens in isolation.

### Non-Negotiable Constraints

1. **Determinism**: Same inputs → same outputs. No `datetime.now()`, no randomness in scoring.
2. **PIT Safety**: No future information leaks into historical decisions.
3. **Fail-Closed**: Missing data → reject, never guess or impute favorably.
4. **Bounded Influence**: No single agent, signal, or data source dominates.
5. **Evidence-Based**: No feature promotion without Checklist v2 validation.
6. **Governance Transparency**: All agent actions logged with decision rationale.

---

## II. Three Operational Lanes

### Lane A — Deterministic Production

**Purpose**: Core scoring, validation, universe maintenance. No LLM.

**Agents** (5):
- `production_qa_check` — snapshot validation gates (exit 0/1/2)
- `post_snapshot_supervisor` — promotion / rejection decision
- `universe_maintenance` — investor cohort, entity registry sync
- `trapops_daily_summary` — portfolio ops reporting
- `watchdog` — cron reliability catch-up (morning safety net)

**Execution Model**: Direct Python call or cron.

**If it fails**: It's a deterministic bug. Debug code, not prompts.

**Token Cost**: $0.

**Authority**: Immutable. Changes require code review + tests + git history.

---

### Lane B — Cheap Monitoring + Escalation

**Purpose**: Detect anomalies, escalate only on confirmation, stay cheap.

**Architecture**: Tier 0 (deterministic checks) → Tier 1 (Llama 3.3 70B escalation only if anomaly confirmed)

**Tier 0 Checks** (deterministic, $0 cost):
- File freshness (snapshot date vs. mtime)
- JSON schema validation
- Git state (clean/dirty, tracking)
- Blocked spec registry
- 13F quarantine status
- Architecture freeze status

**Tier 1 Escalation** (LLM, ~$0.20 per 1M tokens):
- Only fires if Tier 0 detects anomaly
- Model: Llama 3.3 70B (Together, ~$0.20/1M tokens)
- Gateway fallback: `run_agent_direct.py` (no Claude dependency)
- Scope: Diagnostics only. No model changes, no deployment authority.

**Agents** (18):
- All shadow agents (rank_change_monitor, forward_shadow trackers, event analysts)
- All diagnostic agents (options_quality, insider_coverage, phase2_health)
- All orchestration agents (fleet_steward, herald, memory_steward)

**If Llama escalates**: Human review required before action. System continues in safe state.

**Token Cost**: ~$0.20–2.00/day (typical), capped at monthly budget.

**Authority**: Escalation only. No production model changes. Recommendations require human sign-off.

---

### Lane C — High-Token Manual Engineering

**Purpose**: Spec-to-code tracing, refactors, test generation, research.

**Execution Model**: Manual Claude sessions only. No automation, no cron.

**Scope**:
- Multi-file refactors
- Algorithm design + implementation
- Test generation and validation
- Memory compression and organization
- Knowledge graph schema updates
- Spec-driven feature development

**Model**: Opus (Tier 3, ~$3.00/1M tokens) or Sonnet (Tier 2, ~$1.20/1M tokens).

**If it fails**: Rollback via git. Human engineer retries with corrected approach.

**Token Cost**: ~$10–50/session (typical), no automation cap.

**Authority**: Full (within frozen/quarantine constraints). Commits require pre-commit approval.

---

## III. Routing Policy

### Agent Registration

Every agent is registered in `common/agent_registry.py` with metadata:

```json
{
  "name": "rank_change_monitor",
  "llm_policy": "direct_llama_on_anomaly",
  "requires_preflight": true,
  "tier": "B",
  "authority": "escalation_only",
  "cron_schedule": "0 16 * * 1-5",
  "description": "Daily rank change audit with Tier 1 escalation"
}
```

**llm_policy enum**:
- `none` → Lane A, deterministic only
- `direct_llama_on_anomaly` → Lane B, escalation gate
- `manual_only` → Lane C, manual engineering

**requires_preflight**:
- `true` → Must pass agent_preflight.py before execution
- `false` → Deprecated or pure research, skip preflight

### Preflight Gate (agent_preflight.py)

**Executed before any Lane B or C agent runs.**

**Checks** (fail-closed):

1. **Git State**
   - On main? (deferred work OK on branch)
   - Clean working tree? (uncommitted changes detected)
   - HEAD commit hash & message

2. **Snapshot State**
   - Latest snapshot age (< 1 day expected)
   - QA status: PASS/WARN/FAIL
   - Data freshness (holdings, trial records, institutions)

3. **Governance Registry**
   - Is architecture freeze active? (blocks selector/ranker/sizing agents)
   - Is 13F quarantine active? (blocks cohort-dependent agents)
   - Are blocked specs preventing this agent? (e.g., Spec 089 KG pilot)
   - Is this agent in `FROZEN_AGENTS` list?

4. **Metadata**
   - Agent exists in registry?
   - requires_preflight = true?
   - llm_policy matches execution mode?

**Output**:
- `allowed_action` (list): What this agent is permitted to do
- `not_allowed` (list): What is blocked (reason + until date)
- `contradictions` (list): Conflicting requirements

**Failure Behavior**:
- Preflight FAIL → agent exits with `exit 2` (blocked, safe state)
- Preflight WARN → agent logs warning and continues (with flag in governance block)
- Preflight PASS → agent proceeds

**Example Output**:
```json
{
  "preflight_status": "PASS",
  "allowed_action": [
    "Run diagnostic analysis",
    "Log findings to artifacts/audit/",
    "Report via Slack"
  ],
  "not_allowed": [
    "Modify selector_score (architecture freeze until 2026-05-26)",
    "Promote ranker features (13F quarantine active until ~2026-05-23)",
    "Merge to main (requires pre-commit approval)"
  ],
  "git_state": {
    "branch": "main",
    "clean": true,
    "head": "eaf74b82"
  },
  "snapshot_state": {
    "latest": "2026-05-15",
    "age_days": 2,
    "qa_status": "PASS"
  },
  "governance_holds": [
    "architecture_freeze (until 2026-05-26)",
    "13f_quarantine (until ~2026-05-23)"
  ]
}
```

---

## IV. Token Budget & Cost Management

### Tier Definitions

| Tier | Model | Cost/1M Tokens | Use Case | Monthly Budget |
|------|-------|----------------|----------|----------------|
| 0 | None (deterministic) | $0 | Lane A production | N/A |
| 1 | Llama 3.3 70B (Together) | $0.20 | Lane B escalation | $50–100 |
| 2 | Claude Sonnet | $1.20 | Lane C focused tasks | $100–200 |
| 3 | Claude Opus | $3.00 | Lane C complex tasks | $50–100 |

**Monthly Target**: $200–400 (typical). Tier 1 should dominate (escalation gate gates most work).

### Decision Tree

```
Does this task require LLM?
  ├─ NO → Lane A (deterministic production)
  │   └─ Cost: $0
  │
  ├─ YES (anomaly detection only)
  │   ├─ Is this production-critical and automated?
  │   │   ├─ YES → Tier 1 Llama (cheap, via run_agent_direct.py)
  │   │   │   └─ Cost: ~$0.20/1M tokens
  │   │   │
  │   │   └─ NO → Manual session, approve first
  │   │       └─ Continue to next question
  │   │
  │   └─ Is this spec-driven implementation or research?
  │       ├─ Spec-driven (algorithm, multi-file) → Tier 3 Opus
  │       │   └─ Cost: ~$3.00/1M tokens
  │       │
  │       └─ Focused task (single feature, quick fix) → Tier 2 Sonnet
  │           └─ Cost: ~$1.20/1M tokens
```

### Monthly Budget Allocation

- **Tier 0** (deterministic): Unlimited, $0
- **Tier 1** (Llama escalation): $50–100/month (capped at 500K tokens/day during business hours)
- **Tier 2** (Sonnet research): $100–200/month (manual approval per session)
- **Tier 3** (Opus complex): $50–100/month (manual approval per session)

**Enforcement**: Cron jobs track token usage via `run_agent_direct.py` logs. Monthly report generated on 1st of month.

---

## V. Authority Levels

### Lane A Authority

- Execute deterministic production code
- Fail decisively (exit 1 = hard error, exit 2 = blocked, exit 0 = clean)
- Log decision rationale to `_governance` block
- No interpretation required; if it fails, code is wrong

**Who can change Lane A?**
- Code review (1 approval minimum)
- All tests pass
- Commit must have git history explaining why

### Lane B Authority

- Run Tier 1 Llama only on confirmed anomaly
- Generate diagnostics, alert, recommend actions
- **Cannot** deploy model changes
- **Cannot** modify selector/ranker/sizing
- **Cannot** force merge or override gates

**Who can act on Lane B output?**
- Human engineer (you)
- Escalation → human review → decision
- If recommendation approved: open spec, design, implement in Lane C

### Lane C Authority

- Design and implement specs
- Commit code with full pre-commit approval
- Modify any codebase (within frozen/quarantine constraints)
- Promote features (if Checklist v2 passes)
- Merge to main

**Who can execute Lane C?**
- You (primary engineer)
- Authorized team members (if delegated)

**Constraints**:
- Architecture freeze: No model changes until h20d (~2026-05-26)
- 13F quarantine: No selector/ranker/sizing changes until cohort clears (~2026-05-26)
- Blocked specs: Spec 089 (KG pilot), Spec 072 (vNext redesign) deferred

---

## VI. Failure Modes & Escalation

### Deterministic Failures (Lane A)

**Symptom**: Snapshot promotion fails, validation gate triggers, cron job exits 1

**Diagnosis**:
1. Check `_governance` block in snapshot JSON (run_screen.py output)
2. Read pre-commit hook output (if applicable)
3. Review latest 3 commits to see recent changes

**Response**:
- Bug in deterministic code → fix code, rerun, commit
- Data corruption → investigate source, backfill if safe, notify stakeholders
- Git state issue → resolve branch/commit state, retry

**Cost**: Investigation + 1–2 hours fix + testing

### Escalation Anomalies (Lane B)

**Symptom**: Llama flags anomaly (file fresh, schema valid, but distribution off)

**Examples**:
- Rank change > 30% between consecutive snapshots
- inst_delta_z drift persists after cohort refresh
- Options quality coverage gap (< 80%)
- Forward shadow divergence (inst vs cross-signal)

**Diagnosis**:
1. Read Llama escalation summary (why flagged)
2. Run `tools/data_explorer compare --date-a X --date-b Y --field Z` to quantify
3. Check git log for recent changes (model update? data source change?)
4. Review memory (is there a known issue?)

**Response**:
- Known issue (e.g., 13F distortion) → log, monitor, wait for clearance
- New bug → spec + implement fix in Lane C
- Data anomaly → investigate source, backfill or mark as PIT-unsafe
- False alarm → update Tier 0 check thresholds

**Cost**: 15–60 min investigation + escalation decision

### Manual Engineering Failures (Lane C)

**Symptom**: Code breaks tests, pre-commit fails, or feature behaves unexpectedly

**Response**:
1. Revert (git reset --hard origin/main if needed)
2. Diagnose root cause (missing import? logic error? test flake?)
3. Fix incrementally, test locally
4. Re-commit with clear message
5. If stuck: document blocker, open issue, escalate

**Cost**: 1–8 hours (depends on complexity)

### Escalation Path

```
Deterministic failure
  ├─ Code bug → fix + test + commit
  ├─ Data issue → investigate + backfill/mark-unsafe + notify
  └─ Git state → resolve + retry

Anomaly detection (Lane B)
  ├─ Known issue → log + monitor
  ├─ New issue → spec + implement (Lane C)
  └─ False alarm → tune threshold + re-baseline

Manual task stuck (Lane C)
  ├─ Reversible → git reset + try again
  └─ Irreversible → escalate to architecture review
```

---

## VII. Monitoring & Observability

### Logging Standard

Every agent must log a `_governance` block to JSON output:

```json
{
  "_governance": {
    "agent_name": "rank_change_monitor",
    "agent_version": "1.0.0",
    "execution_time_utc": "2026-05-17T15:30:00Z",
    "lane": "B",
    "preflight_status": "PASS",
    "git_state": {
      "branch": "main",
      "head": "eaf74b82"
    },
    "decision_rationale": "Rank change 12.5% vs prior day; within threshold (30%); logged for monitoring",
    "escalation_triggered": false,
    "errors": [],
    "warnings": []
  }
}
```

### Monitoring Checklist

**Daily** (automatic via `run_daily.py`):
- ✓ Lane A jobs completed (exit code 0)
- ✓ Lane B escalations (if any, logged with rationale)
- ✓ Snapshot promotion (PASS/WARN/FAIL)
- ✓ Forward shadows (inst_delta, cross_signal daily checkpoints)

**Weekly** (manual):
- ✓ Token budget consumption (Tier 1, 2, 3 spend)
- ✓ Cron job success rate (> 95% expected)
- ✓ Escalation rate (should be < 5% of automated runs)
- ✓ Open issues (specs, blockers, known anomalies)

**Monthly** (manual + generate report):
- ✓ Token budget reconciliation
- ✓ Fleet health summary (agent uptime, escalation trends)
- ✓ Architecture review (any drift from governance?)
- ✓ Next month roadmap (phases, priorities, blockers)

### Health Metrics

| Metric | Target | Alert Threshold |
|--------|--------|-----------------|
| Lane A success rate | 99% | < 95% |
| Lane B escalation rate | < 5% | > 10% |
| Preflight gate pass rate | 98% | < 90% |
| Monthly token budget | $200–400 | > $500 |
| Cron job uptime | 99% | < 95% |
| Forward shadow sync (Jaccard) | > 0.70 | < 0.60 |

---

## VIII. Governance Holds (Current State — 2026-05-17)

### Active Freezes

1. **Architecture Freeze** (~2026-05-26)
   - **Scope**: No model logic changes, feature promotions, ranking modifications
   - **Exception**: Deterministic tooling (preflight, monitoring, verification) OK
   - **Lift condition**: h20d checkpoint + 13F cohort clearance
   - **Agents affected**: All ranker/selector/sizing agents (blocked via preflight)

2. **13F Q1 2026 Cohort Quarantine** (~2026-05-23 or later)
   - **Status**: 6/48 managers filed (2026-05-15)
   - **Trigger for clearance**: ≥34 managers filed + all 6 validation gates pass
   - **Scope**: No selector/ranker/sizing changes until cohort Jaccard ≥0.70
   - **Agents affected**: selector_ranker, rank_change_monitor, cohort-dependent diagnostics
   - **Timeline**:
     - ~2026-05-23: Fuller filing coverage expected
     - ~2026-05-26: Clearance decision or extension

### Blocked Specs

| Spec | Status | Blocker | Resume |
|------|--------|---------|--------|
| 089 (KG pilot) | Deferred | 13F quarantine + cohort clearance | ~2026-05-23+ |
| 072 (vNext) | Diagnostic-only | Architecture freeze | ~2026-05-26 |
| 095 (evaluation scope) | ✓ Resolved | — | — |
| 100 (IC tooling) | ✓ Implemented | Interpretation deferred | Post-freeze |

---

## IX. Decision Gates & Checkpoints

### Immediate (May 19–26)

- **May 19 (Monday)**: Phase 2 Step 3 verification (evening cron watchdog runs)
- **~May 23 (Thursday)**: 13F refresh trigger expected (≥34 managers filed)
- **~May 26 (Sunday)**: h20d checkpoint, architecture freeze lift decision

### Post-Freeze (May 27+)

- Spec 100 corrected IC evaluation (Checklist v2 battery)
- KG pilot implementation (if cohort clears)
- vNext diagnostic → conditional promotion path

---

## X. Phase Roadmap

### Phase 1 ✅ (2026-05-15)
Governance docs committed (routing, preflight, token budget)

### Phase 2 ✅ (2026-05-15)
Registry metadata added (llm_policy, requires_preflight)
Preflight tool created and validated

### Phase 2 Step 3 ✅ (2026-05-15)
Evening cron reliability audit + watchdog deployed

### Phase 2 Step 3b ✅ (2026-05-15)
Preflight integrated into run_agent_direct.py

### Phase 2 Step 4 (Locked, ~2026-05-23+)
KG sprint (Spec 089 Phase 1.5A) — 13 hrs coding, 60+ tests
**Blocked on**: Phase 3 verification + cohort clearance

### Phase 3 (Roadmap, Post-Freeze)
Evening audit + cron monitoring expansion
IC evaluation framework refresh

### Phase 4+ (Roadmap, Post-Clearance)
KG gating (specs 4a–4e)
Ranker governance layer (vNext conditional ranking)

---

## XI. Contact & Escalation

**Questions about governance?**
- Check this doc first (you're reading it!)
- Check memory system: `/home/arrenchulz/.claude/projects/*/memory/`
- Check agent_roster.md for agent metadata

**Issues with specific agents?**
- Check agent_preflight.py output for blockers
- Review git history for recent changes
- Check artifacts/audit/ for diagnostics

**Blocked by freeze/quarantine?**
- Check operating_state memory (current blockers + unblock dates)
- Check 13f_q1_2026_refresh_runbook.md for validation gates

**Budget overrun or cost concerns?**
- Check token usage logs in `run_agent_direct.py`
- Monthly report generated on 1st of month
- Escalate if > 20% over budget

---

## XII. References

**Primary governance docs**:
- `docs/ops/hermes_openclaw_routing_policy.md`
- `docs/ops/agent_preflight_checklist.md`
- `docs/ops/token_budget_policy.md`

**Agent metadata & registry**:
- `common/agent_registry.py`
- `docs/hermes_agents/agent_roster.md`

**Memory system**:
- `operating_state_post_spec_100_2026_05_17.md` (blockers, next actions)
- `architecture_optimization_2026_05_15.md` (phase roadmap, design rationale)

**Tooling**:
- `tools/agent_preflight.py` (preflight gate implementation)
- `tools/run_agent_direct.py` (agent execution with token tracking)

**Audit & debug**:
- `docs/hermes_skills/openclaw-agent-scope-audit.md`
- `artifacts/audit/agent_preflight_validation_2026_05_15.md`

---

**Document Version**: 1.0.0 (2026-05-17)  
**Next Review**: 2026-06-15 or upon Phase 3 start, whichever is first
