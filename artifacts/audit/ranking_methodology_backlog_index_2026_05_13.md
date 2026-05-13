# Ranking Methodology Backlog Index — 2026-05-13

**Governance Closure**: All 8 specs (093–100) created and classified. No implementation authorized. Next review triggers: Spec 094 rerun (~2026-05-27) or explicit Spec 100 implementation decision.

---

## Backlog Status Table

| Spec | Title | Status | Classification | Blocker / Next Dependency | Implementation Allowed? | Next Review |
|------|-------|--------|-----------------|--------------------------|-------------------------|-------------|
| **093** | Financial_score sign-direction audit | CLOSED | **INTENTIONAL_STRESS_UPSIDE** | None (prerequisite satisfied) | ❌ No | — |
| **094** | Selector-only comparator analysis | CLOSED | **RANKER_UNPROVEN** | Forward-return coverage (8.7% → need 30%+); Spec 095 dependency resolved | ❌ No | 2026-05-27 (rerun with ≥30 post-PIT HIT/MISS outcomes) |
| **095** | Top-60 evaluation-scope investigation | CLOSED | **CURRENT_TOOLS_CONFLATED** | Spec 100 tool fix (blocks IC claims); Spec 094 unblocked | ❌ No | — |
| **096** | Gate/ranker separation doctrine | CLOSED | **DOCTRINE_ACCEPTED** | None (policy memo) | ❌ No (governance only) | — |
| **097** | Event-EV prospective monitoring gate | CREATED | **MONITORING_GATE_CREATED** | Forward-accumulation (n ≥ 30 resolved HIT/MISS); Spec 077 binder dependency | ✅ Yes (monitoring setup only, no scoring change) | 2026-06-03 (expected 30-outcome milestone) |
| **098** | Catalyst timing prospective monitor | CREATED | **MONITORING_GATE_CREATED** | Forward-accumulation (≥20 post-PIT snapshots); Spec 071/078 hygiene verification | ✅ Yes (monitoring setup only, no scoring change) | 2026-06-15 (correlation verdict gate) |
| **099** | Clinical orthogonality audit | CREATED | **SHADOW_ORTHOGONALITY_GATE_CREATED** | 13F refresh completion (~2026-05-15); ≥20 post-PIT snapshots + ≥30 postmortems for correlation matrix | ✅ Yes (audit only, no model changes) | 2026-06-17 (orthogonality verdict decision) |
| **100** | Ranker IC tooling correction | CREATED | **TOOLING_CORRECTION_SPEC_CREATED** | Governance hold (blocks ranker IC promotion until implemented); spec only, no tool built yet | ❌ No (governance hold) | **Deferred**: implement only if Spec 094 rerun shows positive returns AND Spec 100 is deemed critical path |

---

## Governance Rules

### 1. IC Evidence Hold (Spec 100)

**Current state**: Spec 095 audit revealed that `run_rank_ic_backtest.py` measures `composite_score` IC, **not** production ranker `final_score` IC (0.25 correlation, 23% top-30 overlap).

**Rule**: Do NOT cite prior IC evidence to justify ranker promotion or feature changes until:
- Spec 100 is implemented (tool corrected, outputs labeled), OR
- Existing IC claims are manually relabeled with caveats (e.g., "⚠️ COMPOSITE_SCORE_IC, not ranker IC")

**Affected decisions**:
- ❌ Ranker IC-based promotion claims (blocked)
- ❌ Catalyst/EV/clinical IC-based weighting (blocked until 100 complete)
- ✅ Specs 093/094/095 audits remain valid (they are investigation/audit only, not promotion)

**Impact**: Ranker is operationally changing portfolio composition (Spec 094 confirmed), but return/IC value remains **unmeasured until Spec 100 is complete**.

---

### 2. Signal Role Classification (Spec 096)

All signals classified by doctrine role:

| Role | Definition | Production Allowed? | Promotion Candidate? |
|------|------------|-------------------|----------------------|
| **GATE** | Membership filter (binary); no alpha claim | ✅ Yes | N/A (gate, not alpha) |
| **RISK_CONTROL** | Risk limiting / drawdown dampening; no alpha | ✅ Yes | N/A (risk, not alpha) |
| **RANKER_ALPHA_CANDIDATE** | Ranker feature with evidence path | ❌ No (frozen) | ✅ Yes (gated: evidence + orthogonality + Checklist v2) |
| **SHADOW_ONLY** | Non-production monitoring; diagnostic only | ✅ Yes (shadow) | ⚠️ Conditional (must pass gate tests first) |
| **MONITORING_ONLY** | Governance monitoring; no portfolio impact | ✅ Yes (reporting) | N/A (monitoring only) |
| **RETIRED** | Deprecated / no longer used | ❌ No | ❌ No |

**Key assignments** (from Spec 096):
- **coinvest_score_z**: GATE (quality filter, 92.7% selector variance; cannot reuse in ranker without marginal-value proof)
- **financial_score**: RANKER_ALPHA_CANDIDATE (live in ranker; sign-direction confirmed INTENTIONAL_STRESS_UPSIDE)
- **catalyst_timing**: SHADOW_ONLY (monitoring via Spec 098 until correlation proven)
- **event_ev_p_hit**: SHADOW_ONLY (monitoring via Spec 097 until calibration ≥30 samples)
- **clinical_design_quality**: SHADOW_ONLY (monitoring via Spec 099 until orthogonality proven)
- **composite_score**: RETIRED (conflated IC measurement; not used for ranker evaluation)

---

### 3. Promotion Path Requirements

**No signal may move from SHADOW_ONLY to RANKER_ALPHA_CANDIDATE without**:

1. ✅ **Orthogonality proof** (Spec 099 for clinical; no collinearity with existing signals)
2. ✅ **Forward-return validation** (Specs 097/098 calibration/correlation gates; positive evidence threshold)
3. ✅ **Spec 094-style marginal-value test** (ranker-added vs selector-removed; incremental return differential)
4. ✅ **Checklist v2 gate** (FM + bootstrap + FDR + LOSO + year stab; within-sample stability)
5. ✅ **Human approval** (Operator sign-off; no autonomous promotion)

**Spec 094 precedent**: Ranker does change membership deterministically (Jaccard 42.7%, financial_score delta -22.9 pp), confirming operational logic. But forward-return evidence insufficient (8.7% coverage) → classification **RANKER_UNPROVEN**, not approved.

---

### 4. No Silent Leakage (EES v3 Prevention)

**Lesson from EES v3 structural failure** (2026-04-30):
- Clinical formulations can be cryptographically dominated by institutional signals (pmv correlation -0.978; conditional_misprice_score is rank transform of pmv)
- Orthogonality audit is **mandatory governance**, not optional
- Proof required; domain reasoning insufficient

**Enforcement**:
- All future clinical/EV/catalyst ranker features must pass Spec 099-style orthogonality audit
- Collinear signals are rejected (|ρ| > 0.70 with coinvest/financial → no promotion)
- Partial regression required: signal must retain ΔR² > 0.02 after controlling for existing alpha

---

## Evidence Accumulation Timeline

### Immediate (2026-05-13 → 2026-05-20)

- **Spec 097 dashboard**: Event-EV calibration tracking scaffolded; begin daily observation
  - Current: n_resolved = 7 post-PIT postmortems
  - Target: n_resolved ≥ 30 by ~2026-06-03

- **Spec 098 monitoring**: Catalyst timing correlation metrics computed weekly
  - Current: snapshot-level catalyst intensity metrics not yet aggregated
  - Target: ≥20 post-PIT snapshots, time-series correlation computed by ~2026-05-27

- **Spec 099 preparation**: Post-13F-refresh (2026-05-15) snapshot data available for orthogonality analysis
  - Target: correlation matrix + partial regression ready by ~2026-05-27

### Scheduled (2026-05-27 → 2026-06-17)

- **2026-05-27**: Spec 094 rerun ready (projected 30–50 resolved outcomes; sufficient for IC/return decision)
  - Verdict: if hit-rate differential > 2pp and ranker-added > selector-only, promote to Checklist v2 gate
  - Otherwise: remain RANKER_UNPROVEN; continue shadowing

- **2026-06-03**: Spec 097 (Event-EV) projected 30-outcome milestone
  - Calibration verdict: Brier ≤ 0.08? No bin >2× overconfident? mean_p_hit_hits > mean_p_hit_misses?
  - Pass → eligible for Checklist v2 (conditional on Spec 099 orthogonality)
  - Fail → remain SHADOW_ONLY; investigate root cause

- **2026-06-15**: Spec 098 (Catalyst) correlation verdict
  - Pass: correlation(catalyst_hit_rate_30d, forward_5d) > 0.15? Tier-A >> Tier-C returns?
  - Fail: catalyst remains shadow-only; no ranker weighting

- **2026-06-17**: Spec 099 (Clinical) orthogonality verdict
  - Pass: |ρ(clinical, coinvest)| < 0.60? ΔR² > 0.02? No monotonic-transform signature?
  - Fail: clinical remains shadow-only; no promotion pathway opens

---

## What This Backlog Does (And Doesn't Do)

### ✅ DOES

- Clarify ranker governance: what signals can be used, under what conditions
- Prevent silent leakage: all promotions blocked until evidence gates pass
- Document unproven claims: Specs 094/095 audit findings remain valid but non-actionable
- Enable safe monitoring: Specs 097–099 are governance-safe (no scoring impact)
- Establish decision points: clear timeline and verdict dates for future promotion decisions

### ❌ DOES NOT

- Implement any code changes (all specs are documentation only)
- Change production scoring (ranker formula frozen at 2 features: coinvest, financial)
- Promote clinical, event-EV, catalyst, Polymarket, options, or composite signals
- Authorize ranker retrain or architectural changes
- Commit to Spec 100 tooling fix (governance hold placed; defer until evidence warrants it)
- Backtest or re-analyze pre-PIT snapshots (forward-only evaluation)

---

## Current Production State (Frozen)

**Ranker**: 2-feature pairwise (coinvest_score_z +0.02, financial_score -0.0533)
- Feature freeze enacted 2026-04-04 (Checklist v2 gate)
- Ranker changes require explicit governance gate + human approval
- Marginal-value proof required (Spec 094 standard)

**Selector**: A4 model (institutional + financial + (clinical shadow-only))
- Coinvest selects; no promotion authority until Spec 094 validates ranker value
- Financial penalizes safe (stress-upside) — confirmed INTENTIONAL via Spec 093

**Gates**: Coinvest (membership), liquidity, runway, dilution, stale-thesis
- Classification: GATE role (filter, not alpha)
- No promotion authority needed (gates freeze independent of alpha stack)

---

## Deferred / Out-of-Scope

| Item | Reason | Next Review |
|------|--------|-------------|
| Spec 100 implementation (IC tooling fix) | Governance hold placed; defer unless Spec 094 rerun + 095 resolution demands it | 2026-05-27 (Spec 094 rerun) |
| Clinical ranker promotion | Orthogonality not yet proven (Spec 099 in-flight) | 2026-06-17 (Spec 099 verdict) |
| Catalyst ranker weighting | Correlation not yet validated (Spec 098 in-flight) | 2026-06-15 (Spec 098 verdict) |
| Event-EV sizing | Calibration threshold not yet met (Spec 097 in-flight) | 2026-06-03 (Spec 097 verdict) |
| Polymarket alpha | Insufficient anecdotal evidence (5/25 closed markets with history); forward-only observation | TBD (>50 resolved markets needed for Checklist v2) |
| Options overlay promotion | IC uncertain; coverage unstable (29% liquid, down from 35% at Spec 062 ship); deferred | 2026-06-30 (coverage re-audit) |
| Composite ranker (clinical+catalyst+EV) | Requires all 3 orthogonality gates to pass first; no design work until gates clear | 2026-06-17+ (post-Spec-099 verdict) |

---

## Governance Notes for Next Session

1. **If Spec 094 rerun (2026-05-27) shows positive returns**: Ranker becomes PROMOTION_ELIGIBLE (contingent on Specs 099 orthogonality + Checklist v2 gate). Decision point: commit to Spec 100 tooling fix?

2. **If Spec 097/098/099 verdicts are all PASS**: Portfolio redesign pathway opens (Spec 072 vNext becomes eligible). But DO NOT implement without all 3 gates passing AND Checklist v2 approval.

3. **If any gate FAILS**: Signal remains shadow-only indefinitely; investigate root cause; no promotion.

4. **If Spec 100 is deferred**: Manually label any existing IC output as "⚠️ COMPOSITE_SCORE_IC (not ranker IC)" and enforce governance hold on IC-based ranker claims.

---

## Commit Guidance

**Commit now**: `ranking_methodology_backlog_index_2026_05_13.md` (this memo)

**Do NOT commit now**:
- Individual spec files (093–098 already committed; 097/098/099/096 new versions can be staged separately if desired)
- Code/config/scoring changes (none present)
- Runtime/generated files

**Suggested commit message**:
```
docs(audit): index ranking methodology backlog — governance closure

Specs 093–100 created; all classified. Governance rules documented:
- IC evidence hold (Spec 100) blocks ranker IC-based claims
- Signal role classification (Spec 096) defines promotion paths
- Monitoring gates (Specs 097–099) establish next review dates
- No implementation authorized; forward-only evaluation (Spec 094 rerun ~2026-05-27)

Blocker: Spec 100 tool fix (deferred pending Spec 094 verdict)
Next action: resume ranking work upon Spec 094 rerun or Spec 100 decision
```

---

## Reference

- **Backlog index**: `ranking_methodology_spec_backlog_2026_05_13.md` (memory file with detailed spec list)
- **Governance hold**: `governance_ic_evidence_hold_2026_05_13.md` (memory file enforcing IC restrictions)
- **Individual specs**: `specs/changes/spec_09{3..9}_*.md` + `specs/changes/spec_100_*.md` (research memos)
- **Audit memos**: `artifacts/audit/spec_09{3..5}_*.md` (investigation write-ups)
