# Control Plane Agent Map

**Purpose:** Read-only reference documentation of control-plane agents, their schedules, authority levels, responsibilities, and governance boundaries.

**Status:** 7 control-plane agents, all active, mixed authority (observe_only + observe_and_propose), operational and healthy.

---

## 1. Status Summary

| Dimension | State |
|-----------|-------|
| Active agents | 7 (data_auditor, fleet_steward, ops, ops_supervisor, production_qa, qa, sentinel) |
| Authority levels | observe_only (3), observe_and_propose (4) |
| Cadence | all daily_after_production |
| Schedule | staggered 18:30–21:30 ET post-production |
| LLM policy | mixed (direct_llama_on_anomaly, manual_only) |
| Production impact | diagnostic + proposal only; no auto-execution |
| Health | Operational |
| Registry status | Active, supervised by orchestrator |

---

## 2. Agent Matrix

### data_auditor (observe_only)
- **Role:** Read-only judge that monitors data input integrity and freshness
- **Cadence:** Daily after production (~18:30 ET M-F)
- **Authority:** `observe_only`
- **What it monitors:** Data import freshness (CTgov trials, SEC 8-K, FDA, press releases), schema validation, source health, pipeline failures
- **Output surface:** `artifacts/data_audit/{date}_audit.{json,md}`; heartbeat status
- **Responsibilities:**
  - Check all production data files (trial_records.json, short_interest.json, company_ir_sources.json, universe.json) for staleness
  - Validate schema consistency across snapshots
  - Flag source failures in `data/press_releases/fetch_state.json`
  - Alert on import pipeline timeouts or errors
- **Production impact:** None (diagnostic-only; no data mutations or corrections)

### fleet_steward (observe_and_propose)
- **Role:** Fleet health, coordination, dispatch, and reporting
- **Cadence:** Daily after production (~19:00 ET M-F)
- **Authority:** `observe_and_propose`
- **What it monitors:** Agent heartbeats, memory writes, artifact production, resource utilization, inter-agent coordination
- **Output surface:** `artifacts/fleet_steward/{date}_status.{json,md}`; `agents/*/memory/` (reads only)
- **Responsibilities:**
  - Aggregate heartbeat from all agents (31-agent fleet)
  - Detect silent failures or stale agents
  - Identify resource contention or scheduling conflicts
  - Propose cron adjustments or capacity improvements
  - Coordinate multi-agent workflows (e.g., herald fetch → classify → digest)
  - Document fleet state for operator review
- **Production impact:** None (proposals only; no cron changes without operator approval)

### ops (observe_and_propose)
- **Role:** Production operator and health monitor
- **Cadence:** Daily after production (~19:30 ET M-F)
- **Authority:** `observe_and_propose`
- **What it monitors:** Production snapshot health, ruleset version, ranking/selector outputs, market data freshness, data pipeline completeness
- **Output surface:** `logs/production_{date}.log`; `artifacts/ops/{date}_health.{json,md}`
- **Responsibilities:**
  - Verify production snapshot completed and is valid
  - Check ruleset version matches expected (8887576e)
  - Validate top-30 portfolio consistency
  - Confirm ranking/selector outputs are sensible
  - Verify market data (prices, volumes) are fresh (within 1 trading day)
  - Propose rollback if production appears corrupted
  - Document production health for downstream decision-making
- **Production impact:** None (health assessment only; rollbacks proposed, not auto-executed)

### ops_supervisor (observe_only)
- **Role:** Read-only ops triage that emits one daily verdict
- **Cadence:** Daily after production (~20:30 ET M-F, after all tier-2 agents)
- **Authority:** `observe_only`
- **What it monitors:** Aggregates output from data_auditor, fleet_steward, ops, production_qa, qa, sentinel; synthesizes into single operational verdict
- **Output surface:** `artifacts/ops_supervisor/{date}_verdict.md`; heartbeat (PASS/YELLOW/RED)
- **Responsibilities:**
  - Read all tier-2 agent reports (data_auditor, fleet_steward, ops, production_qa, qa, sentinel)
  - Synthesize into single PASS/YELLOW/RED verdict
  - Identify root causes of conflicts (e.g., if qa says tests pass but sentinel says drift detected)
  - Recommend hold/proceed/investigate
  - Track suppressed agents and known-exceptions (bioshort_watch, shadow_watch, policy_shadow_watch)
  - Maintain suppressed-agent ledger with reasons and dates
- **Production impact:** None (triage and recommendation only; no auto-actions)

### production_qa (observe_and_propose)
- **Role:** Review-first production QA — check for errors, regressions, schema drift, stale references
- **Cadence:** Daily after production (~19:15 ET M-F)
- **Authority:** `observe_and_propose`
- **What it monitors:** Regression test suite, snapshot schema, data consistency, cross-file references, historical comparisons
- **Output surface:** `artifacts/qa/{date}_production_qa.{json,md}`; heartbeat (PASS/WARN/FAIL)
- **Responsibilities:**
  - Run regression test suite on latest snapshot
  - Compare schema against known-good baseline
  - Check cross-file consistency (e.g., tickers in top-30 exist in universe)
  - Validate data types and ranges
  - Detect stale references or orphaned data
  - Propose schema updates if drift detected
  - Propose bug fixes if tests fail
  - Document QA findings for ops_supervisor synthesis
- **Production impact:** None (testing framework only; proposed fixes require approval)

### qa (observe_only)
- **Role:** Contract-test runner and failure classifier
- **Cadence:** Daily after production (~19:00 ET M-F, in parallel with production_qa)
- **Authority:** `observe_only`
- **What it monitors:** Contract tests (snapshots exist, ranking/selector outputs present, expected fields populated, type consistency)
- **Output surface:** heartbeat log; aggregated to production_qa and ops_supervisor reports
- **Responsibilities:**
  - Run contract-test suite (snapshot schema, required fields, data types)
  - Classify failures (schema, missing field, type mismatch, out-of-range)
  - Report pass/fail status
  - Provide diagnostic output for human review
  - Feed results to production_qa for more detailed analysis
- **Production impact:** None (test-only; no corrections applied automatically)

### sentinel (observe_and_propose)
- **Role:** Drift monitor and rollback advisor
- **Cadence:** Daily after production (~20:00 ET M-F, after ops and production_qa complete)
- **Authority:** `observe_and_propose`
- **What it monitors:** Ranking drift vs prior snapshot, selector output changes, rule changes, correlation shifts, scoring model behavior
- **Output surface:** `artifacts/sentinel/{date}_drift.{json,md}`; heartbeat
- **Responsibilities:**
  - Compare latest snapshot ranking/selector outputs vs prior day
  - Flag material changes (>5% top-30 reweight, >10% rank reordering)
  - Detect ruleset version changes or scoring coefficient changes
  - Correlate drift with known events (ruleset update, signal promotion, market shock)
  - Assess whether drift is expected/justified or suspicious
  - Propose rollback if drift appears unexplained or corrupted
  - Document drift assessment for operator review
- **Production impact:** None (drift assessment and proposals only; rollbacks require operator approval)

---

## 3. Execution Schedule

All times in ET (Eastern Time), M-F. All agents fire after production snapshot completes (~17:30 ET).

| Time | Agent(s) | Action |
|------|----------|--------|
| 18:30 | data_auditor | Data freshness and schema validation |
| 19:00 | fleet_steward, qa | Fleet health assessment & contract tests |
| 19:15 | production_qa | Production QA and regression tests |
| 19:30 | ops | Production snapshot health assessment |
| 20:00 | sentinel | Ranking drift and rollback assessment |
| 20:30 | ops_supervisor | Aggregate all tier-2 verdicts into single operational triage |

**Sequence:** All tier-2 agents (data_auditor, fleet_steward, ops, production_qa, qa, sentinel) complete by ~20:25 ET; ops_supervisor waits until all are done, then synthesizes verdict by ~20:35 ET.

---

## 4. Authority Levels & Responsibilities

### observe_only (3 agents)
- **data_auditor:** Read production data, emit diagnostic reports, no corrections or edits
- **ops_supervisor:** Aggregate reports, synthesize triage verdict, no action beyond recommendation
- **qa:** Run tests, classify failures, no test-suite modifications or auto-fixes

**Key constraint:** No mutations of production data, rulesets, ranking outputs, or agent configs.

### observe_and_propose (4 agents)
- **fleet_steward:** Monitor fleet health, propose cron/resource adjustments, coordinate workflows
- **ops:** Monitor production health, propose rollback if needed
- **production_qa:** Run QA, propose schema updates or bug fixes (requires approval)
- **sentinel:** Monitor drift, propose rollback if needed

**Key constraint:** Proposals are advisory only; no auto-execution of proposed changes.

---

## 5. Governance Boundaries

### Control-plane agents **CANNOT**:
- Modify production snapshots or ranking/selector outputs
- Change ruleset versions or scoring model coefficients
- Update portfolio positions or execute trades
- Alter signal-monitor schedules or anomaly thresholds
- Approve or auto-execute proposals without operator confirmation
- Modify cron entries (only propose)
- Write to production_data/ or agents/AGENT_REGISTRY.json without approval
- Bypass the Town/OpenClaw proposal workflow
- Suppress or unsuppress other agents without explicit operator directive

### Control-plane agents **CAN**:
- Read all production data, agent outputs, and market data
- Run tests and diagnostics
- Emit diagnostic reports and health verdicts
- Propose improvements, fixes, rollbacks, or cron adjustments
- Aggregate fleet status for operator review
- Document operational state and findings
- Flag anomalies and recommend next actions
- Coordinate timing of data-ingestion and signal-monitor agents

---

## 6. Recent Activity Reference

**2026-05-25 Observations:**

| Agent | Status | Finding |
|-------|--------|---------|
| data_auditor | PASS | All data sources fresh; CTgov, SEC, FDA, press releases current |
| fleet_steward | PASS | 31-agent fleet healthy; no stale heartbeats; memory writes on schedule |
| ops | PASS | Snapshot complete, ruleset 8887576e, top-30 coherent, market data fresh |
| production_qa | PASS | 297/299 regression tests pass; 2 known exceptions (morningstar fixes verified live) |
| qa | PASS | Contract tests pass; schema valid; all required fields populated |
| sentinel | PASS | Ranking stable vs 2026-05-24; minor reweight <2% acceptable |
| ops_supervisor | PASS | All tier-2 verdicts GREEN; no anomalies; proceed normally |

**Fleet state:** Fully operational, no escalations, all agents healthy.

---

## 7. Relationship to Town/OpenClaw Flow Contract

See reference documents:
- `docs/TOWN_OPENCLAW_AGENT_FLOW_CONTRACT.md` — agent communication, authority, decision gates
- `docs/FAILURE_PATTERN_LIBRARY.md` — common agent failure modes and recovery patterns
- `docs/templates/SELF_IMPROVEMENT_PROPOSAL.md` — proposal workflow for agent changes

**Change governance:** Any proposed control-plane agent change (new diagnostic, modified threshold, additional LLM context) **must go through the Town/OpenClaw proposal-only workflow first**:

1. Submit `SelfImprovementProposal` via `/town-brief` command
2. Town agent routes to OpenClaw for preflight review
3. Preflight validates:
   - Does it stay within authority boundaries?
   - Does it avoid auto-execution of changes?
   - Does it maintain the proposal-first workflow?
   - Does it preserve observability and traceability?
4. If SAFE: proposal approved for implementation (separate ticket)
5. If BLOCKED: feedback provided; revise or defer

---

## 8. Suppressed Agents Ledger

The control-plane infrastructure tracks intentionally suppressed agents (agents present in registry but not running):

**Current suppressed agents (as of 2026-05-06):**

| Agent | Category | Reason | Date | Registry Status |
|-------|----------|--------|------|-----------------|
| bioshort_watch | portfolio_risk | Upstream producer unscheduled (hedge_report 41d stale); reactivation requires restoration of upstream wiring + confirmation of hedge governance need | 2026-05-06 | `status=deprecated`, `supervised_by_orchestrator=false` |
| shadow_watch | signal_monitor | Intentional placeholder (merged successor design deferred); not wired to cron, no memory writes, no artifacts; Spec 085 Path C disposition | 2026-05-06 | `status=shadow`, `supervised_by_orchestrator=false` |
| policy_shadow_watch | signal_monitor | Under Spec 085 evaluation for retire vs keep; currently active with P0 #1 date-stamp corruption known | 2026-05-06 | `status=active` (monitored) |

**Suppressed agent liveness check:** ops_supervisor maintains a `SUPPRESSED_AGENTS` dict in `agents/ops_supervisor/supervisor.py` with explicit reasons for each suppression. If a suppressed agent needs reactivation, a new spec must define:
- Cron entry and schedule
- Memory-write contract (artifact paths)
- Consumer rewiring plan (which agents/tools will read the outputs)
- Authority escalation (if applicable)
- Integration test plan

---

## 9. Non-Goals

This document is reference-only. It does **not** authorize or describe:

- Live control-plane agent changes, enhancements, or feature additions
- Automatic execution of proposed fixes or rollbacks
- Modification of cron entries (proposals only)
- Changes to production data, rulesets, ranking, or portfolio execution
- Authority escalation from observe_only to mutate_data or mutate_config
- Bypassing the Town/OpenClaw proposal workflow
- Reactivation of suppressed agents without operator approval and new spec

Any of the above require a separate spec with full design, governance review, test plan, and operator approval.

---

## 10. Appendix: Authority Tier Reference

**Tier 1: Operations Leadership (operator-only)**
- `mutate_config` — authority to modify AGENT_REGISTRY.json, cron entries, production model configs, governance ledgers
- Only authority level reserved for human operators

**Tier 2: Control-Plane Agents**
- `observe_and_propose` — 4 agents (fleet_steward, ops, production_qa, sentinel) can propose changes but cannot execute
- `observe_only` — 3 agents (data_auditor, ops_supervisor, qa) read-only, diagnostic + triage synthesis

**Tier 3: Operational Agents (data ingestion, signal monitors)**
- `observe_only` / `write_artifacts` — deterministic pipelines + LLM-on-anomaly cost-optimized monitors

**Key principle:** Proposals flow UP from agents to operator via reports → operator decision → new spec → implementation. No auto-execution at any agent tier.

---

**Document version:** 2026-05-26  
**Last verified:** 2026-05-26 (control-plane inspection clean)  
**Next review:** Upon any control-plane agent proposal or governance change
