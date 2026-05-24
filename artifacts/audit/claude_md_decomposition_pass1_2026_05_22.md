# CLAUDE.md Decomposition — Pass 1 Analysis
**Date:** 2026-05-22  
**Scope:** Read-only classification of biotech-screener CLAUDE.md (633 lines)  
**Goal:** Map behavioral coupling before restructuring  
**Status:** ANALYSIS ONLY — no rewrites, no commits

---

## 1. Section Inventory

| Line | Section | Type | Size | Purpose |
|------|---------|------|------|---------|
| 1-2 | Header | Meta | 2 | Title + divider |
| 3-11 | Project Identity + North Star Rule | Constitutional | 9 | Foundational principle (reproducible, auditable, traceable) |
| 13-18 | CCFT Principles | Constitutional | 6 | Non-negotiable data rules |
| 20-26 | Active Ruleset | Operational State | 7 | Current production version, pinned IDs, manifest |
| 28-50 | Current Operating Truths | Research History | 23 | Spec 050 context, mental model, signal performance summary |
| 53-84 | Trust Buckets | Research History | 32 | Signal safety tiers, evidence hierarchy, deprecated signals |
| 87-112 | Do Not Reopen | Research History | 26 | Dead-lane table (13 closed lanes) |
| 115-127 | Current Promotion Story | Research History | 13 | Narrative of current stack validation |
| 130-137 | PIT Rules | Constitutional | 8 | Point-in-time enforcement (appears 3 times total in file) |
| 140-160 | Canonical Benchmark Commands | Workflow/Runtime | 21 | bash command recipes for research |
| 164-171 | Heavy-Lift Jobs | Operational State | 8 | Status of PIT regen, forward monitor |
| 174-180 | Architecture Freeze Status | Operational State | 7 | Freeze lift date, post-freeze priorities |
| 182-207 | Governance Artifacts | Governance/Policy | 26 | PR #286, tier policy, hash rotations, compliance memo |
| 209-262 | External AI Landscape | External Intel | 54 | OpenClaw, Hermes, ODIN, BiotechEdge, FDA RTCT, AI drug pipeline, industry adoption |
| 264-283 | 13F Cycle Status | Operational State | 20 | Q1 2026 filing details, manager changes, post-filing actions |
| 285-314 | Active Spec Status | Operational State | 30 | Resolved/active/blocked/monitoring table |
| 316-322 | Insider Diagnostic (Spec 104) | Governance/Policy | 7 | Diagnostic-only designation, blank vs. zero, promotion requirements |
| 326-328 | Expectation Layer (Spec 105) | Governance/Policy | 3 | Coverage gates and thresholds |
| 330-336 | Hermes Knowledge Layer (Spec 089/090) | Governance/Policy | 7 | Ops brain architecture, Town bridge |
| 338-346 | Forward Shadow & IC Status | Operational State | 9 | Accumulation dates, IC measurements, refresh conditions |
| 348-360 | What to Update After Every Session | Operational State | 13 | Post-session checklist |
| 362-379 | Decision Engine Architecture | Workflow/Runtime | 18 | Core files, pipeline flow, sort anchor |
| 383-389 | Promotion Governance | Governance/Policy | 7 | Manifest, battery, promote script, rollback, policy |
| 391-396 | Event Ledger & Cache Warming | Workflow/Runtime | 6 | Ledger sources, cache warmer, always-warm rule |
| 398-404 | Daily Production Pipeline | Workflow/Runtime | 7 | Runner, cron, 13-step orchestrator, readiness |
| 406-411 | OpenClaw Ops Agent | Workflow/Runtime | 6 | Workspace, role, gateway, model, fleet size |
| 413-417 | Shadow Portfolio | Workflow/Runtime | 5 | File, policy, family sleeves, forward test results |
| 419-424 | Adding a 13F Manager | Governance/Policy | 6 | Onboard tool, one-shot flow, example |
| 426-430 | Data Provenance Rules | Governance/Policy | 5 | Holdings truth source, CUSIP-first |
| 432-437 | Before Writing Any Code | Constitutional | 6 | Module classification, test-first, look-ahead bias, tier classification |
| 439-449 | Coding Standards | Constitutional | 11 | Encoding, hashing, determinism, PIT fixtures |
| 451-455 | What NOT To Do | Constitutional | 5 | Refactoring, agent weights, forbidden APIs, survivorship bias |
| 457-455 | Test Requirements | Constitutional | 5 | Unit test, leakage test, ablation test |
| 457-544 | Long-Call Contract Recommendations | Governance/Policy | 88 | Step-by-step recipe for options triage |
| 546-553 | Options Expression Layer (Spec 062) | Governance/Policy | 8 | Status, modules, wiring, tests, policy |
| 555-560 | Data Explorer Agent | Governance/Policy | 6 | CLI, package, tests, policy, output |
| 562-594 | Key File Locations | Reference | 33 | Table of key files by area |
| 596-632 | Developer Profile | Reference/Context | 37 | Role, quantitative background, tech stack |

**Total lines:** 633  
**Section count:** 32  
**Types represented:** 6 (Constitutional, Operational State, Research History, Workflow/Runtime, Governance/Policy, External Intel, Reference)

---

## 2. Dependency Map

### Critical Coupling Chains

**Chain 1: Operational State → Governance → Decisions**
```
Active Ruleset (20-26)
  ↓ references
Active Spec Status (285-314)
  ↓ references
Promotion Governance (383-389)
  ↓ blocks
Before Writing Any Code (432-437)
```
**Risk:** Active Spec Status and Ruleset must sync. If split across files, updates could desync.

**Chain 2: Research Validation → Trust → Decisions**
```
Current Operating Truths (30-50)
  ↓ references
Trust Buckets (53-84)
  ↓ references
Do Not Reopen (87-112)
  ↓ informs
Test Requirements (451-455)
  ↓ blocks
Before Writing Code (432-437)
```
**Risk:** Test requirements depend on knowing which signals are safe. Moving research history without updating test context creates silent instruction corruption.

**Chain 3: Ruleset Freeze → Architecture → Code Changes**
```
Architecture Freeze Status (174-180)
  ↓ gates
Decision Engine Architecture (362-379)
  ↓ gates
Promotion Governance (383-389)
  ↓ gates
Before Writing Code (432-437)
```
**Risk:** Freeze lift date is a hard gate. If moved to operational-state, code changes might proceed without realizing freeze is still active.

**Chain 4: PIT Compliance (Appears 3 Places)**
```
PIT Rules (130-137)
  ↓ reinforces (independently)
CCFT Principles (13-18, line 18 mentions timestamping)
  ↓ reinforces (independently)
Before Writing Code (432-437, line 436)
  ↓ reinforces (independently)
Test Requirements (451-455, line 451-455 mentions leakage test)
  ↓ reinforces (independently)
Coding Standards (439-449, line 442 mentions "no datetime.now()")
```
**Risk:** PIT compliance appears in 5 places. This is intentional repetition for behavioral anchoring. Over-deduplication would weaken enforcement. **Must preserve in root.**

### Secondary Dependencies

**13F Updates affect IC Measurement:**
```
13F Cycle Status (264-283)
  ↓ triggers
Forward Shadow & IC Status (338-346, line 346 "Refresh IC decomposition after Q1 2026 13F cache warm")
  ↓ affects
Active Spec Status (285-314)
```

**External AI Landscape affects Runtime Decision:**
```
External AI Landscape (209-262, OpenClaw maintenance-only status)
  ↓ informs
Daily Production Pipeline (398-404, lines 410 model=Llama 3.3)
  ↓ informs
Architecture Freeze Status (174-180, potential Hermes migration)
```

**Governance Tier Classification gates all code changes:**
```
Governance Artifacts (182-207)
  ↓ classifies
Before Writing Any Code (432-437, line 437 "Classify the diff by governance tier")
  ↓ gates
Promotion Governance (383-389)
```

---

## 3. Duplication Map

### Exact / Near-Exact Repetitions

| Content | Locations | Type | Risk |
|---------|-----------|------|------|
| **PIT compliance rule** | PIT Rules (lines 131-137), CCFT Principles (line 18), Before Writing Code (line 436), Test Requirements (lines 451-455), Coding Standards (line 442) | Intentional repetition | HIGH — deduplication weakens behavioral anchoring |
| **Deterministic output rule** | Coding Standards (line 442), Decision Engine Architecture (line 378), Current Operating Truths (line 40) | Intentional repetition | HIGH — appears because it's foundational |
| **Checklist v2 evidence standard** | Trust Buckets (lines 56-58), Current Operating Truths (line 41), Current Promotion Story (line 119) | Intentional evidence narrative | LOW — can consolidate if kept visible |
| **inst_delta_z zeroed note** | Active Ruleset (line 23), Current Operating Truths (line 38), Current Promotion Story (line 121) | Operational state repetition | MEDIUM — reflects current status, should move to operational-state |
| **Forward shadow 7 arms** | Current Operating Truths (line 49), Active Spec Status (line 314 implicit), Forward Shadow & IC Status (line 339) | Operational state reference | LOW — consistent, not duplicate |
| **B6 bundle +2.34pp/mo result** | Current Operating Truths (line 40), Trust Buckets (line 56), Current Promotion Story (line 118) | Evidence narrative | LOW — consensus number, keep visible |

### Subtle Variants (Same Rule, Different Wording)

| Rule | Variant A | Variant B | Type | Risk |
|------|-----------|-----------|------|------|
| Test discipline | Test Requirements (lines 451-455 "Unit test... leakage test... ablation test") | Before Writing Code (line 433 "Write the failing test FIRST") | Complementary | LOW — both reinforce, wording drift is acceptable |
| Governance tier classification | Governance Artifacts (lines 188-192 tier definitions) | Before Writing Code (line 437 "Classify the diff by governance tier") | Reference vs. Action | LOW — artifact defines, before-code checks |
| Deterministic inputs | CCFT Principles (line 18 "data_available_timestamp <= as_of_date always enforced") | Data Provenance Rules (line 429 "CUSIP-first, not issuer-first") | Data rules | LOW — different layers, both needed |

**Total exact duplications:** 5  
**Total variant duplications:** 3  
**Assessment:** Duplication is intentional. Exact copies appear for behavioral reinforcement (PIT, determinism). Variants appear because they belong in multiple mental models. This is NOT over-duplication.

---

## 4. Must-Remain-Root-Visible Candidates

Based on the repetition analysis and coupling chains, these items must stay in root or be duplicated for reinforcement:

### A. Constitutional Invariants (Essential in Root)

| Item | Lines | Reason | Risk if Moved |
|------|-------|--------|---------------|
| **Project Identity + North Star Rule** | 3-11 | Foundational. Appears first. Sets expectations. | If moved, every architecture decision loses context |
| **CCFT Principles** | 13-18 | Non-negotiable data contract. Reinforces PIT. | Silent bugs if data_available_timestamp rule is not visible on first read |
| **PIT Rules** | 130-137 | Appears in 5 places total. Critical for backtest safety. | Removing from root creates risk of PIT violations in new code |
| **Determinism Rule** | 439-449 + 442 | Deterministic output is core to reproducibility. | Moving to scoped file risks float arithmetic, datetime.now() creeping in |
| **Before Writing Code** | 432-437 | Test-first discipline + tier classification. Blocks all code. | Scoped rule loads after development starts, too late |
| **Coding Standards** | 439-449 | Encoding, hashing, byte-identical outputs. | Encoding drift breaks audit trails. Must be visible before coding. |
| **Test Requirements** | 451-455 | Leakage test ties to trust buckets. Blocks promotions. | Trust buckets can move to research file, but test requirements must stay visible |

### B. Operational State That Could Move (But Requires Careful Transition)

| Item | Lines | Can Move? | Transition Strategy |
|------|-------|-----------|-------------------|
| Active Ruleset | 20-26 | YES | Move to operational-state.md BUT keep 2-line reference in root (pinned version ID, freeze status) |
| 13F Cycle Status | 264-283 | YES | Move to operational-state.md. Referenced by Forward Shadow. Keep sync note in root. |
| Forward Shadow & IC Status | 338-346 | YES | Move to operational-state.md. Keep evaluation threshold (30+ days) note in root. |
| Architecture Freeze Status | 174-180 | MAYBE | Move to operational-state.md BUT keep gate conditions in root near Before Writing Code. |
| Active Spec Status | 285-314 | YES | Move to operational-state.md as brief table. Root gets 3-line summary + "see operational-state for full table." |
| Heavy-Lift Jobs | 164-171 | YES | Move to operational-state.md. These are status, not rules. |
| What to Update After Every Session | 348-360 | YES | Move to operational-state.md. Checklist is procedural, not constitutional. |

### C. What Can Definitely Move

| Item | Lines | Destination | Reason |
|------|-------|-------------|--------|
| Trust Buckets (full) | 53-84 | research-backtest.md | Evidence history, not a coding rule. Can load on demand. |
| Do Not Reopen | 87-112 | research-backtest.md | Research lane closure documentation. Load during research sessions. |
| Current Operating Truths (detail) | 30-50 | research-backtest.md | Spec 050 context and signal performance history. Research background. |
| Current Promotion Story | 115-127 | research-backtest.md | Narrative of validation. Belongs with evidence. |
| Canonical Benchmark Commands | 140-160 | research-backtest.md | bash recipes for research work. Load when touching scripts/research/. |
| External AI Landscape | 209-262 | external-intel.md or delete | Competitive context, not coding rule. Reference only. |
| Long-Call Contract Recommendations | 457-544 | governance.md | Post-screen recipe. Governance/policy, not core coding rule. |
| Options Expression Layer | 546-553 | governance.md | Policy and wiring documentation. |
| Data Explorer Agent | 555-560 | governance.md | Tool documentation and policy. |
| Key File Locations | 562-594 | Trim to 10-line reference in root; detail moves to governance.md | Navigation aid, but 33 lines is bloat. |
| Developer Profile | 596-632 | external-intel.md or reference file | Role context, not coding rule. Can load on demand. |

---

## 5. Proposed Destination Map

### Root CLAUDE.md (~120 lines target)

**Keep (with minimal rewrite):**
- Project Identity + North Star Rule (9 lines)
- CCFT Principles (6 lines)
- PIT Rules (8 lines, preserve exact wording)
- Determinism + Governance (5 lines)
- Before Writing Any Code (8 lines, preserve exact wording)
- Coding Standards (11 lines, preserve exact wording)
- Test Requirements (5 lines, preserve exact wording)
- What NOT To Do (5 lines)
- Key File Locations — brief version (10 lines, not 33)
- Quick reference to scoped rules (8 lines)

**Cut from root (move to scoped files):**
- Active Ruleset (move to operational-state.md, keep 2-line summary in root)
- Current Operating Truths detail (move to research-backtest.md)
- Trust Buckets full detail (move to research-backtest.md)
- Do Not Reopen full table (move to research-backtest.md)
- Current Promotion Story (move to research-backtest.md)
- Canonical Benchmark Commands (move to research-backtest.md)
- Heavy-Lift Jobs (move to operational-state.md)
- Architecture Freeze Status detail (keep gate condition in root, move detail to operational-state.md)
- 13F Cycle Status (move to operational-state.md)
- Active Spec Status tables (move to operational-state.md, keep gate summary in root)
- Forward Shadow & IC Status (move to operational-state.md)
- What to Update After Every Session (move to operational-state.md)
- External AI Landscape (move to external-intel.md)
- Long-Call Contract Recommendations (move to governance.md)
- Options Expression Layer (move to governance.md)
- Data Explorer Agent (move to governance.md)
- Developer Profile (move to external-intel.md or standalone reference file)

### .claude/rules/operational-state.md (~80 lines)

**Content:**
- Last updated, update cadence, authority notation
- Active Ruleset (from root lines 20-26)
- Architecture Freeze Status (from root lines 174-180)
- Heavy-Lift Jobs (from root lines 164-171)
- 13F Cycle Status (from root lines 264-283)
- Forward Shadow & IC Status (from root lines 338-346)
- Active Spec Status (from root lines 285-314)
- What to Update After Every Session (from root lines 348-360)

### .claude/rules/research-backtest.md (~80 lines)

**Content:**
- Trust Buckets (from root lines 53-84)
- Do Not Reopen table (from root lines 87-112)
- Current Operating Truths (from root lines 30-50)
- Current Promotion Story (from root lines 115-127)
- Canonical Benchmark Commands (from root lines 140-160)
- PIT deep-dive notes (supplement to root PIT Rules lines 130-137)

**Path scope:**
```yaml
paths:
  - scripts/research/**
  - tools/run_*benchmark*.py
  - tools/run_promotion_battery.py
```

### .claude/rules/production-pipeline.md (~70 lines)

**Content:**
- Decision Engine Architecture (from root lines 362-379)
- Pipeline Flow Diagram (summarize lines 369-376)
- Event Ledger & Cache Warming (from root lines 391-396)
- Daily Production Pipeline (from root lines 398-404)
- OpenClaw Ops Agent (from root lines 406-411)
- Shadow Portfolio (from root lines 413-417)
- Data Provenance Rules (from root lines 426-430)

**Path scope:**
```yaml
paths:
  - src/wake_robin_screener/decision_engine.py
  - src/wake_robin_screener/selector_engine.py
  - tools/run_daily_production.py
  - tools/warm_caches.py
```

### .claude/rules/governance.md (~60 lines)

**Content:**
- Governance Artifacts summary (from root lines 182-207, brief)
- Tier definitions (from root lines 188-192)
- Promotion Governance (from root lines 383-389)
- Adding a 13F Manager recipe (from root lines 419-424)
- Insider Diagnostic (from root lines 316-322)
- Expectation Layer (from root lines 326-328)
- Hermes Knowledge Layer (from root lines 330-336)
- Long-Call Contract Recommendations (from root lines 457-544)
- Expression Layer policy (from root lines 546-553)
- Data Explorer policy (from root lines 555-560)

**Path scope:**
```yaml
paths:
  - governance/**
  - production_data/decision_rulesets/**
  - tools/promote_ruleset.py
```

### .claude/rules/external-intel.md (~60 lines)

**Content:**
- External AI Landscape (from root lines 209-262)
- Developer Profile (from root lines 596-632)

**Path scope:**
```yaml
paths: []  # Loaded on-demand via @external-intel, not path-scoped
```

---

## 6. Extraction Risk Notes

### A. High Risk (Behavioral Coupling)

**Issue 1: Freeze Lift Date blocks code changes**
- **Current:** Architecture Freeze Status (line 176) appears immediately before "Before Writing Code" context section
- **Risk:** If freeze is in operational-state.md, a developer starting new work might not realize freeze is still active (freeze lift ~2026-05-26, after this decomposition date)
- **Mitigation:** Keep a 2-line gate condition in root CLAUDE.md near Before Writing Code: "Check Architecture Freeze Status in operational-state.md before any code change. Current freeze lifts ~2026-05-26."

**Issue 2: Test Requirements depend on Trust Buckets**
- **Current:** Test Requirements (line 451-455) says "Ablation test stub showing Sharpe contribution >= 0.1" — but which signals are safe to test?
- **Risk:** Test Requirements stay visible, but Trust Buckets move to research file. New developer might skip ablation test because they don't see which signals pass Checklist v2
- **Mitigation:** Keep a 1-line reference in Test Requirements: "Check Trust Buckets in research-backtest.md to confirm signal is safe before ablation."

**Issue 3: PIT Rules appear in 5 places (intentional repetition)**
- **Current:** PIT Rules (130-137), CCFT (18), Before Writing Code (436), Test Requirements (453), Coding Standards (442)
- **Risk:** Removing any instance weakens behavioral anchoring. "Just check PIT Rules once" creates risk of drift.
- **Mitigation:** Keep PIT Rules in root. Do NOT deduplicate. Reinforce in every related section.

**Issue 4: Spec Status affects Active Ruleset versioning**
- **Current:** Active Ruleset (20-26) references Spec 100 blockers (line 180)
- **Risk:** Ruleset versioning and Spec Status are tightly coupled. If split across files and one is stale, code changes could use wrong baseline.
- **Mitigation:** Keep active ruleset ID (8887576e) in root. Move detailed spec table to operational-state.md. Add sync note: "All spec status changes must update Active Ruleset if ruleset version changes."

### B. Medium Risk (Update Cadence Mismatch)

**Issue 5: 13F cycle affects IC measurement refresh**
- **Current:** 13F Cycle Status (264-283) + Forward Shadow & IC Status (338-346) are in same file
- **Risk:** After new 13F filing, line 346 says "Refresh IC decomposition after Q1 2026 13F cache warm" — but if they're in same operational-state.md, developer might refresh IC before 13F is cached
- **Mitigation:** Keep them in same file (operational-state.md) and add explicit sequential gate: "1. Wait for 13F filing. 2. Warm 13F cache (tools/warm_13f_cache.py). 3. Run cohort quarantine. 4. Refresh IC decomposition."

**Issue 6: External AI Landscape → Runtime decision**
- **Current:** OpenClaw maintenance-only status (line 211) + Model choice (line 410 Llama 3.3) in separate sections
- **Risk:** Model migration is deferred pending OpenClaw patch cadence. If external-intel is loaded only on demand, operator might miss the planning horizon.
- **Mitigation:** Keep runtime decision (Llama 3.3 on Together AI) in production-pipeline.md. Move competitive context to external-intel.md. Add reminder in root: "OpenClaw maintenance-only as of May 2026. Hermes migration is Q4 2026 evaluation, not urgent."

### C. Low Risk (Safe to Move)

- Trust Buckets → research-backtest.md (evidence history, only needed during research)
- Do Not Reopen → research-backtest.md (dead lanes, reference only)
- Benchmark Commands → research-backtest.md (bash recipes, load during research sessions)
- Developer Profile → external-intel.md (role context, reference only)
- Long-Call Contract Recommendations → governance.md (post-screen recipe, not core coding rule)

---

## 7. Recommended Pass 2 Sequence

### Phase 1: Create .claude/rules/ directory structure (no file writes)
1. Create `.claude/rules/` directory
2. Create `.claude/rules/operational-state.md` stub
3. Create `.claude/rules/research-backtest.md` stub
4. Create `.claude/rules/production-pipeline.md` stub
5. Create `.claude/rules/governance.md` stub
6. Create `.claude/rules/external-intel.md` stub

### Phase 2: Extract and write operational-state.md (volatile content, most frequent updates)
1. Extract Active Ruleset (lines 20-26)
2. Extract Architecture Freeze Status (lines 174-180)
3. Extract Heavy-Lift Jobs (lines 164-171)
4. Extract 13F Cycle Status (lines 264-283)
5. Extract Forward Shadow & IC Status (lines 338-346)
6. Extract Active Spec Status (lines 285-314)
7. Extract What to Update After Every Session (lines 348-360)
8. Add header with last_updated, update_cadence, authority notation
9. Add sequential gates between 13F and IC refresh
10. Write operational-state.md

### Phase 3: Extract and write research-backtest.md (research context, load on-demand)
1. Extract Trust Buckets (lines 53-84)
2. Extract Do Not Reopen (lines 87-112)
3. Extract Current Operating Truths (lines 30-50)
4. Extract Current Promotion Story (lines 115-127)
5. Extract Canonical Benchmark Commands (lines 140-160)
6. Add PIT deep-dive section (supplement to root PIT Rules)
7. Add YAML path scope: scripts/research/**, tools/run_*benchmark*.py
8. Write research-backtest.md

### Phase 4: Extract and write production-pipeline.md (runtime context, path-scoped)
1. Extract Decision Engine Architecture (lines 362-379)
2. Extract Event Ledger & Cache Warming (lines 391-396)
3. Extract Daily Production Pipeline (lines 398-404)
4. Extract OpenClaw Ops Agent (lines 406-411)
5. Extract Shadow Portfolio (lines 413-417)
6. Extract Data Provenance Rules (lines 426-430)
7. Add YAML path scope: decision_engine.py, selector_engine.py, run_daily_production.py
8. Write production-pipeline.md

### Phase 5: Extract and write governance.md (policy context, path-scoped)
1. Extract Governance Artifacts summary (lines 182-207, condense to 10 lines)
2. Extract Tier definitions (lines 188-192)
3. Extract Promotion Governance (lines 383-389)
4. Extract Adding a 13F Manager (lines 419-424)
5. Extract Insider Diagnostic (lines 316-322)
6. Extract Expectation Layer (lines 326-328)
7. Extract Hermes Knowledge Layer (lines 330-336)
8. Extract Long-Call Contract Recommendations (lines 457-544)
9. Extract Expression Layer policy (lines 546-553)
10. Extract Data Explorer policy (lines 555-560)
11. Add YAML path scope: governance/**, production_data/decision_rulesets/**
12. Write governance.md

### Phase 6: Extract and write external-intel.md (reference context, on-demand)
1. Extract External AI Landscape (lines 209-262)
2. Extract Developer Profile (lines 596-632)
3. Write external-intel.md (no path scope, loaded on-demand)

### Phase 7: Trim and rewrite root CLAUDE.md (~120 lines)
1. Keep Project Identity + North Star Rule (9 lines, no changes)
2. Keep CCFT Principles (6 lines, no changes)
3. Keep PIT Rules (8 lines, PRESERVE EXACT WORDING)
4. Consolidate Determinism + Governance (5 lines)
5. Keep Before Writing Any Code (8 lines, PRESERVE EXACT WORDING)
6. Keep Coding Standards (11 lines, PRESERVE EXACT WORDING)
7. Keep Test Requirements (5 lines, add reference to Trust Buckets in research-backtest.md)
8. Keep What NOT To Do (5 lines, no changes)
9. Trim Key File Locations to 10 lines (preserve key files, remove detail)
10. Add Quick Links section (8 lines):
    - See `.claude/rules/operational-state.md` for: ruleset version, 13F cycle, freeze dates, spec status
    - See `.claude/rules/research-backtest.md` for: evidence hierarchy, dead lanes, benchmark commands
    - See `.claude/rules/production-pipeline.md` for: pipeline architecture, cron behavior
    - See `.claude/rules/governance.md` for: tier policy, promotion path, 13F onboarding
    - See `.claude/rules/external-intel.md` for: competitive landscape, developer profile
11. Add Architecture Freeze gate (2 lines): "Check operational-state.md before code change. Freeze lifts ~2026-05-26."
12. Add Active Ruleset summary (2 lines): "Current: 8887576e (v1.14.0). See operational-state.md for details."
13. Write new root CLAUDE.md

### Phase 8: Test and validate
1. Do NOT commit yet
2. Run 2-3 typical Claude Code sessions (e.g., fix a test, add a metric)
3. Verify that path-scoped rules load correctly
4. Check that constitutional invariants (PIT, determinism) remain visible and reinforce
5. Observe whether reference to operational-state.md feels natural or forced
6. Document any behavioral changes

---

## 8. Critical Decisions Requiring User Approval Before Pass 2

### A. Repetition vs. Deduplication

**Current state:** PIT Rules appear in 5 places (lines 130-137, 18, 436, 453, 442).

**Option 1:** Keep all 5 (current behavior, intentional repetition)
- Pro: Behavioral reinforcement. Developer sees PIT rule before writing test, before writing code, before using Decimal.
- Con: File bloat. Manual sync needed if wording changes.

**Option 2:** Keep PIT Rules in root + 2 reference lines elsewhere
- Pro: Single source of truth. Easier to maintain.
- Con: Behavioral weight decreases. Developer might miss reference when reading Before Writing Code section.

**Option 3:** Keep PIT Rules in root. Move other instances to research-backtest.md as "Reinforcement" section.
- Pro: Preserves primary rule in root. Secondary references available for research context.
- Con: Requires careful structural separation so reinforcement loads at right time.

**Recommendation:** Keep Option 1 (current repetition). The behavioral weight of seeing PIT mentioned 5 times outweighs file bloat. Deduplication is a trap here.

### B. Freeze Lift Date as Hard Gate

**Current state:** Architecture Freeze Status (line 176) is prominent in root, before Before Writing Code section.

**Option 1:** Keep freeze status in root, move detail to operational-state.md
- Pro: Gate remains visible.
- Con: Two locations for one fact (freeze status vs. detail).

**Option 2:** Move freeze status to operational-state.md, add 2-line gate in root
- Pro: All operational state in one file. Easier to update.
- Con: Developer might miss gate if they skim root.

**Recommendation:** Keep freeze status visible in root. Move detailed "post-freeze priorities" to operational-state.md. Add explicit gate near Before Writing Code: "Architecture Freeze in effect until ~2026-05-26. See operational-state.md."

### C. External AI Landscape — Keep or Cut?

**Current state:** 54 lines of OpenClaw status, Hermes competitive frame, ODIN benchmarks, FDA RTCT, industry adoption.

**Option 1:** Move to external-intel.md (reference only, loaded on-demand)
- Pro: Reduces root bloat. Still available for context.
- Con: Developer might not know Hermes exists as potential successor.

**Option 2:** Cut entirely (except 1-line note in root)
- Pro: Maximum reduction. Competitive context is not coding rule.
- Con: Loses valuable external reference.

**Option 3:** Keep in root but condense to 8 lines
- Pro: Preserve context awareness.
- Con: Contradicts "thin root" goal.

**Recommendation:** Move to external-intel.md but add 1-line reminder in root near OpenClaw Ops Agent section: "OpenClaw maintenance-only as of May 2026; see external-intel.md for competitive context and Hermes evaluation timeline."

### D. Trust Buckets — Move or Keep?

**Current state:** 32 lines of evidence hierarchy, safe signals, deprecated signals.

**Option 1:** Move to research-backtest.md (loads for research sessions)
- Pro: Belongs with research history. Only needed during research.
- Con: Test Requirements reference it. Might not be visible when writing tests.

**Option 2:** Keep in root but trim to 5-line summary
- Pro: Visible when writing tests.
- Con: Research detail is redundant.

**Option 3:** Move to research-backtest.md, add 2-line reference in root near Test Requirements
- Pro: Both preserved. Reference ties them together.
- Con: Requires maintaining cross-file reference.

**Recommendation:** Move to research-backtest.md. Add 1-line reference in root Test Requirements section: "Check Trust Buckets in research-backtest.md for signal safety assessment before ablation test."

---

## Summary: Key Takeaways for Pass 2

**What will improve:**
1. Root CLAUDE.md from 633 lines → ~120 lines (81% reduction)
2. Constitutional rules stay visible and reinforced
3. Volatile operational state (13F, spec status, freeze dates) lives in one file with clear update cadence
4. Research history separated from coding instructions
5. Path-scoped rules load only when needed

**What must be preserved:**
1. PIT Rules repetition (intentional behavioral anchoring)
2. Determinism / encoding standards in root
3. Tier classification gate (Before Writing Code)
4. Test-first discipline (leakage test requirement)
5. Freeze lift date as hard gate near code-change section

**What requires user approval:**
1. Keep repetition of PIT rules in 5 places? (Recommendation: YES)
2. How to represent freeze lift date gate? (Recommendation: Visible in root + detail in operational-state.md)
3. Move External AI Landscape or keep condensed? (Recommendation: Move to external-intel.md)
4. Move Trust Buckets to research file? (Recommendation: YES, with 1-line reference in root)

**No changes recommended before user approval on decisions A-D above.**
