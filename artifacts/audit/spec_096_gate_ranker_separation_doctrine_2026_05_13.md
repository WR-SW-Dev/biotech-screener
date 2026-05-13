# Spec 096 Audit — Gate/Ranker Separation Doctrine

**Date**: 2026-05-13  
**Status**: DOCTRINE ESTABLISHED  
**Classification**: **DOCTRINE_ACCEPTED** (with evidence gates and conditional assignments)

---

## Executive Summary

This doctrine establishes clear separation of concerns for all signals in production:

1. **GATES**: Hard eligibility filters (fail = name excluded, no alpha claim)
2. **RISK_CONTROL**: Soft post-ranking overlays (reduce exposure, not alpha)
3. **RANKER_ALPHA_CANDIDATE**: Ordering signals within eligible set (requires marginal-value proof)
4. **SHADOW_ONLY**: Research signals, no production role
5. **MONITORING_ONLY**: Diagnostic tracking, no production impact
6. **RETIRED/NO_GO**: Permanently closed, do not revisit

**Core Rule**: Signals already used by the selector (coinvest, financial) cannot be reused in the ranker without explicit marginal-value evidence (Specs 094, 100 required).

**Evidence Gate**: No ranker promotion until Spec 100 (IC tooling correction) is complete or existing IC is relabeled.

---

## Doctrine Rules

### 1. Gate Integrity
- Gates remove candidates without claiming alpha
- Hard gates (false catalyst, liquidity, runway) prevent downstream analysis
- Soft gates (dilution, execution stress) can be applied post-ranking
- Gates must be applied BEFORE ranker to avoid confounding

### 2. Ranker Alpha Standards
- Alpha candidates must prove **marginal ordering value** within eligible universe
- Ranker cannot reuse selector inputs without additional evidence
- Pairwise ordinal only (no rank-weighting, no sizing, no confidence-based capital)
- All ranker IC must come from Spec 100–corrected tool (final_score on eligible universe)

### 3. Signal Reuse Prevention
- **Selector uses**: coinvest_score_z, financial_score (via Module 5 rank-norm)
- **Ranker inherits**: same signals (selector_score already incorporates both)
- **Ranker can add**: only if orthogonal to selector AND pass Spec 094 marginal-value test
- **Blocked without proof**: catalyst, clinical, event_ev, options expectation-gap

### 4. Clinical & Clinical-Derived Signals
- **PERMANENT SHADOW ONLY** unless:
  - Post-cohort validation (Spec 099 orthogonality audit PASS)
  - AND post-13F (2026-05-15+)
  - AND ≥30 resolved outcomes with clinical info
  - AND Checklist v2 approval (FM + bootstrap + FDR + LOSO + year stab)
- No selector promotion under any condition (per prior freeze 2026-04-13)
- Clinical is context/attribution only; never alpha

### 5. Event Probability Calibration ≠ Stock Return Alpha
- Event EV p_hit calibration is NOT stock-return alpha
- Binding HIT/MISS is measurement, not prediction
- Promoting p_hit requires: separate return-evidence path, NOT event-EV IC
- Blocked until: Spec 097 (≥30 calibration samples) + independent return test

### 6. Composite_Score IC is Not Ranker IC
- Existing IC backtest measures composite_score, not final_score
- Cannot cite composite IC for ranker claims (Spec 095 finding)
- All new ranker IC claims require Spec 100–corrected tool
- Blocked until: Spec 100 implemented and output explicitly labeled

---

## Signal Classification Table

### Block 1: Institutional/Sponsorship (Selector Inputs)

| Signal | Current Role | Doctrine Role | Allowed in Production | Evidence Gate | Leakage Risk | Notes |
|--------|---|---|---|---|---|---|
| **coinvest_score_z** | Selector feature | GATE + RANKER_ALPHA_CANDIDATE | ✅ Yes (selector + ranker) | Spec 094 marginal-value test (REQUIRED) | Selector dominance (92.7% variance) | Already in selector AND ranker. Do NOT increase weight without Spec 094 PASS. |
| **inst_delta_z** | Demoted from selector (2026-05-04) | SHADOW_ONLY (post-cohort observation) | ❌ No (removed 05-04) | Spec 072 (Screener vNext) conditional test | Inflated until ~05-15 (post-13F) | Monitor only until cohort stabilizes. Promotion blocked until post-13F + h20d clear. |
| **coinvest_tier1_count** | Descriptor | MONITORING_ONLY | ❌ No | None (descriptor) | None | Documentation only. |
| **coinvest_filing_age_days** | Descriptor | MONITORING_ONLY | ❌ No | None (descriptor) | None | Documentation only. |
| **sponsor_tier1_count** | Descriptor | MONITORING_ONLY | ❌ No | None (descriptor) | None | Documentation only. |

### Block 2: Financial Health (Selector Input, Ranker Feature)

| Signal | Current Role | Doctrine Role | Allowed in Production | Evidence Gate | Leakage Risk | Notes |
|--------|---|---|---|---|---|---|
| **financial_score** | Selector feature + Ranker feature (weight -0.0533) | GATE + RANKER_ALPHA_CANDIDATE | ✅ Yes (selector + ranker) | Spec 093 sign-direction PASS (DONE) | Stress-upside intentional | Negative weight is correct (Spec 093). Do NOT change sign. Do NOT increase weight without Spec 094 PASS + Spec 100 IC proof. |
| **runway_months / runway_score** | GATE (hard minimum, ~6mo) | GATE | ✅ Yes (gate only) | None (gate, no alpha claim) | None | Hard gate. No promotion. |
| **dilution_score / cash_to_mcap** | Selector descriptor | RISK_CONTROL (soft) | ⚠️ Conditional (post-ranking overlay) | None (risk overlay, not alpha) | Double-counting with financial | If applied as soft gate: use post-ranking. Do NOT add to ranker score. |
| **severity / financial_data_state** | Descriptor / quality flag | MONITORING_ONLY | ❌ No | None | None | Diagnostic only. |

### Block 3: Catalyst / Event Timing

| Signal | Current Role | Doctrine Role | Allowed in Production | Evidence Gate | Leakage Risk | Notes |
|--------|---|---|---|---|---|---|
| **catalyst_days** | Shadow research (Spec 098) | SHADOW_ONLY | ❌ No | Spec 098 (stability + ≥30 postmortems + orthogonality pre-check) | Correlation with event_ev (0.6 threshold) | Monitor post-hygiene-fix (2026-05-20). Do NOT promote until Spec 098 PASS + orthogonality PASS. |
| **catalyst_decay_w** | Shadow research (Spec 098) | SHADOW_ONLY | ❌ No | Spec 098 same gates | Same | Same as catalyst_days. |
| **binary_quality_score** | Shadow research (Spec 098) | SHADOW_ONLY | ❌ No | Spec 098 same gates | Overlap with clinical quality | Monitor only. |
| **catalyst_quality_buckets** | Descriptor | SHADOW_ONLY | ❌ No | Spec 098 | None | Monitor via Spec 098. |
| **catalyst_bucket / catalyst_mode** | Descriptor | MONITORING_ONLY | ❌ No | None | None | Documentation only. |
| **catalyst_source / catalyst_family** | Descriptor | MONITORING_ONLY | ❌ No | None | None | Documentation only. |
| **false_catalyst_flag (BPIQ/IR validation)** | GATE | GATE | ✅ Yes (gate only) | None (gate, hygiene verified 2026-05-06) | None | Hard gate per Spec 071/078. Already stable. |
| **stale_thesis_flag (days_since_update)** | GATE | GATE | ✅ Yes (gate only) | None (gate) | None | Hard gate. |

### Block 4: Clinical / Event Quality

| Signal | Current Role | Doctrine Role | Allowed in Production | Evidence Gate | Leakage Risk | Notes |
|--------|---|---|---|---|---|---|
| **clinical_design_quality_z** | Shadow (Spec 057 conditional IC +0.103) | SHADOW_ONLY | ❌ No | Spec 099 (orthogonality audit PASS) + post-13F + ≥30 resolved outcomes | Silent leakage with coinvest (EES v3 pattern) | Permanent shadow unless Spec 099 PASS + Checklist v2. Do NOT promote under any condition (prior freeze). |
| **clinical_score_v2_z** | REJECTED (Δ=-0.68pp pre-PIT) | RETIRED / NO_GO | ❌ No | None (closed 2026-04-13) | Never promote | Do not revisit. |
| **endpoint_strength_score** | Descriptor | SHADOW_ONLY | ❌ No | Spec 099 if used | None | Diagnostic only. |
| **design_rigor_tier** | Descriptor | SHADOW_ONLY | ❌ No | Spec 099 if used | None | Diagnostic only. |
| **prior_evidence_tier** | Descriptor | SHADOW_ONLY | ❌ No | Spec 099 if used | None | Diagnostic only. |
| **mechanism_maturity_tier** | Descriptor | SHADOW_ONLY | ❌ No | Spec 099 if used | None | Diagnostic only. |

### Block 5: Event Probability / Expectation

| Signal | Current Role | Doctrine Role | Allowed in Production | Evidence Gate | Leakage Risk | Notes |
|--------|---|---|---|---|---|---|
| **event_ev_p_hit** | Monitoring (Spec 077 forward-only binder) | MONITORING_ONLY | ❌ No (shadow only) | Spec 097 (≥30 calibration samples) + independent return test | Calibration ≠ alpha | Monitor via Spec 097. Do NOT promote until ≥30 post-PIT HIT/MISS bound + separate return evidence. |
| **event_ev_p_miss** | Monitoring (Spec 077) | MONITORING_ONLY | ❌ No | Spec 097 same gates | Same | Monitor only. |
| **event_ev_p_mixed** | Monitoring (Spec 077) | MONITORING_ONLY | ❌ No | Spec 097 same gates | Same | Monitor only. |
| **event_ev_confidence** | Descriptor | MONITORING_ONLY | ❌ No | None | None | Diagnostic only. |
| **event_ev_asof_date** | Descriptor | MONITORING_ONLY | ❌ No | None | None | Diagnostic only. |

### Block 6: Options / Volatility Expectation

| Signal | Current Role | Doctrine Role | Allowed in Production | Evidence Gate | Leakage Risk | Notes |
|--------|---|---|---|---|---|---|
| **ovf_composite / ovf11_score** | Shadow (Spec 059 expression layer) | SHADOW_ONLY | ❌ No | Spec 100 IC proof (not yet available) | Hidden correlation with misprice proxy | Monitor via expression layer (Spec 062, 30d review). Do NOT promote without Spec 100 corrected IC. |
| **cheap_vol_score** | Shadow (Spec 059) | SHADOW_ONLY | ❌ No | Spec 100 IC proof | Same | Monitor only. |
| **priced_move_pct** | Descriptor | MONITORING_ONLY | ❌ No | None (unit drift observed 13/250 tickers) | Data quality drift | Monitor. |
| **opt_rr_25d / opt_term_slope** | Shadow research | SHADOW_ONLY | ❌ No | Spec 100 IC proof | Microstructure noise | Monitor only. |
| **opt_event_premium** | Shadow research | SHADOW_ONLY | ❌ No | Spec 100 IC proof | Same | Monitor only. |
| **options_quality_manifest fields** | Descriptors | MONITORING_ONLY | ❌ No | None | None | Quality check only (Spec 062 audit). |

### Block 7: Market Structure & Stress

| Signal | Current Role | Doctrine Role | Allowed in Production | Evidence Gate | Leakage Risk | Notes |
|--------|---|---|---|---|---|---|
| **liquidity_gate (ADV, bid-ask, OI min)** | GATE | GATE | ✅ Yes (gate only) | None (gate, no alpha claim) | None | Hard gate. |
| **execution_stress** | Descriptor | RISK_CONTROL (soft) | ⚠️ Conditional (post-ranking) | None (overlay, not alpha) | Double-counting with liquidity | If applied: post-ranking only. Do NOT add to ranker. |
| **dollar_adv_20d** | Gate input / descriptor | MONITORING_ONLY | ❌ No (gate input, not output) | None | None | Used for gate only. |
| **de_vol_60d / de_beta_xbi_60d** | Descriptor | MONITORING_ONLY | ❌ No | None | None | Attribution only. |
| **drawdown / max_drawdown_intraday** | Risk descriptor | RISK_CONTROL (soft) | ⚠️ Conditional (overlay post-ranking) | None (overlay) | Lookback-bias (measurement artifact) | Use intraday draw as risk indicator post-ranking. Do NOT backtest historically (PIT unsafe). |

### Block 8: Trap Flags & Quality

| Signal | Current Role | Doctrine Role | Allowed in Production | Evidence Gate | Leakage Risk | Notes |
|--------|---|---|---|---|---|---|
| **delisted_risk / bankruptcy_risk / late_stage_distress** | GATE | GATE | ✅ Yes (gate only) | None (gate) | None | Hard gate. |
| **quality_trap_flag** | Shadow research | SHADOW_ONLY | ❌ No | Spec 100 IC proof | Overfit to prior returns | Monitor only. |
| **trap_overlay_score** | Shadow research | SHADOW_ONLY | ❌ No | Spec 100 IC proof | Same | Monitor only. |

### Block 9: External Data / Crowd Signals

| Signal | Current Role | Doctrine Role | Allowed in Production | Evidence Gate | Leakage Risk | Notes |
|--------|---|---|---|---|---|---|
| **Polymarket prices** | Shadow (anecdotal, <25 markets) | SHADOW_ONLY | ❌ No | Spec 072+ (coverage >50 markets + PIT validity + return evidence) | Archive truncation, selection bias | Anecdotal only. Do NOT promote without >50 liquidity-resolved markets + PIT-safe data. |
| **insider_net_buy_value_90d (Form 4)** | Monitoring (Spec 065 data-integrity gate) | MONITORING_ONLY | ❌ No (gate only, not ranker) | None (gate, not alpha) | None | Data integrity gate only. Do NOT use for alpha. |
| **short_interest / borrow_stress** | Shadow research | SHADOW_ONLY | ❌ No | Spec 100 IC proof | Crowding indicator, not fundamental | Monitor only. |

### Block 10: News / Herald / Company Communications

| Signal | Current Role | Doctrine Role | Allowed in Production | Evidence Gate | Leakage Risk | Notes |
|--------|---|---|---|---|---|---|
| **news_status / herald_status / company_news_ingest** | Shadow (Spec 063 intraday mover watch) | MONITORING_ONLY | ❌ No | None (intraday tactical only) | Lookahead bias | Intraday monitoring only (Spec 063). Do NOT use for ranking. |
| **Grok sentiment / news NLP** | Shadow research | SHADOW_ONLY | ❌ No | Spec 100+ IC proof | Language drift, sentiment overfit | Research only. |

### Block 11: Morningstar & Data Quality

| Signal | Current Role | Doctrine Role | Allowed in Production | Evidence Gate | Leakage Risk | Notes |
|--------|---|---|---|---|---|---|
| **ms_return_ytd** | Forward-return label source | MONITORING_ONLY | ✅ Yes (data source, not ranking) | None (measurement source) | None | Source of truth for returns. ✅ Audit passed 2026-05-05. |
| **morningstar_category / analyst_rating** | Descriptor | MONITORING_ONLY | ❌ No | None | None | Diagnostic only. |

### Block 12: Selector Outputs (Do Not Reuse in Ranker)

| Signal | Current Role | Doctrine Role | Allowed in Production | Evidence Gate | Leakage Risk | Notes |
|--------|---|---|---|---|---|---|
| **selector_score** | Selector ranking output | RANKER_INPUT (inherited, not reused) | ✅ Yes (ranker input) | Spec 094 marginal-value test for any augmentation | Selector dominance (0.77 corr with final_score) | Ranker operates on top selector candidates. Do NOT add selector_score again as ranker feature. |
| **actionable_rank** | Final portfolio ranking | PRODUCTION_OUTPUT | ✅ Yes (final ranking) | None (output, not input) | None | Top-30 post-gates. |
| **composite_rank / composite_score** | Shadow quality metric (source TBD) | MONITORING_ONLY (NOT RANKER) | ❌ No | Spec 100 (source clarification required) | Conflated with ranker IC in prior tools | Do NOT use for ranking. Source unknown (Spec 095 finding). Mark existing IC as composite_score IC, not ranker IC. |

---

## "Do Not Touch" List

**Permanently closed, do NOT revisit without explicit reopening vote**:

1. **clinical_score_v2_z** — REJECTED pre-PIT (Δ=-0.68pp). Closed 2026-04-13. Alpha freeze locked clinical.
2. **EES v3 (expectation-error via pmv)** — STRUCTURAL FAILURE (pmv-dominant, cannot extract expectation error from expectation alone). Closed 2026-04-30.
3. **All clinical-as-ranker paths** — SHADOW ONLY per prior freeze. Do NOT revisit until Spec 099 PASS + Checklist v2.
4. **Family B selector variant** — SCRAPPED 2026-04-19 (institutional filter-gate removed). Do not revive.
5. **Execution delta (IC=-0.13)** — Anti-predictive post-PIT. Do not revisit.
6. **Total volume_z** — Closed. Do not revisit.
7. **Fixed sleeves / always-on rank-weighting** — Governance frozen 2026-04-04. Do not attempt without explicit policy change.

---

## Evidence Gates by Signal Type

### Gate Signals (Hard Eligibility)
- **No alpha proof required** — Gates prevent bad candidates, not alpha
- **Required evidence for demotion**: Evidence that gate is incorrectly excluding good candidates
- **Example**: False catalyst gate (Spec 071/078 hygiene fix 2026-05-06)

### Risk Control Overlays (Soft)
- **No alpha proof required** — Risk overlays reduce exposure, not claims to outperformance
- **Must be applied POST-ranking** to avoid confounding with alpha signals
- **Example**: Drawdown-based position size reduction

### Ranker Alpha Candidates
- **Required evidence** (in priority order):
  1. **Spec 094**: Marginal ordering value within eligible universe (vs selector-only)
  2. **Spec 095**: Correct evaluation scope (final_score on eligible universe, not composite_score)
  3. **Spec 100**: True ranker IC measurement (final_score, not composite_score)
  4. **Orthogonality**: Prove not collinear with existing features (selector IC, financial stress-upside)
  5. **Checklist v2**: FM + bootstrap + FDR + LOSO + year stability
- **Gate**: No promotion without **all five** completed

### Shadow-Only Signals
- **Current status**: Monitoring, no production role
- **Promotion path**: Complete evidence gates above (Specs 094–100) + orthogonality audit + Checklist v2
- **Timeline**: Earliest 2026-06+ (after Spec 100 tool fix + orthogonality audits)

### Monitoring-Only Signals
- **Current status**: Diagnostic, no production role
- **Promotion path**: Requires separate evidence (not standardized Checklist v2)
- **Example**: Event EV p_hit calibration (measurement, not alpha; requires independent return test)

---

## Dependency Map

```
Promotion Path Blocked By:

   Catalyst Timing
   ↓
   ├─ Spec 098 (stability + postmortem threshold) [OPEN]
   └─ Spec 100 (IC tool fix) [REQUIRED]
   └─ Orthogonality vs coinvest (corr <0.40) [SPEC 098 pre-check]

   Clinical Design Quality
   ↓
   ├─ Spec 099 (orthogonality audit vs coinvest) [OPEN]
   └─ Spec 100 (IC tool fix) [REQUIRED]
   └─ Post-13F (2026-05-15+) [REQUIRED]
   └─ Post-cohort-window (h20d=2026-05-26) [REQUIRED]
   └─ Checklist v2 (FM + bootstrap + FDR + LOSO + year stab) [REQUIRED]

   Event EV P_Hit
   ↓
   ├─ Spec 097 (≥30 calibration samples) [OPEN, ~2026-09]
   └─ Spec 100 (IC tool fix) [REQUIRED]
   └─ Independent return test (not binder IC) [REQUIRED]

   Options / Expectation Gap
   ↓
   ├─ Spec 100 (IC tool fix) [REQUIRED]
   └─ Coverage >50 markets [NOT MET, <25]
   └─ PIT-valid data [TBD]

   Any Ranker Feature Change
   ↓
   └─ Spec 100 (IC tooling correction) [BLOCKER]
   └─ Spec 094 (marginal-value baseline) [BLOCKER]
```

---

## Classification: DOCTRINE_ACCEPTED

**Reasoning**:
- ✅ Clear separation of concerns defined (GATE / RISK_CONTROL / RANKER_ALPHA / SHADOW / MONITORING / RETIRED)
- ✅ All major signals classified with current and recommended roles
- ✅ Evidence gates defined for each signal type
- ✅ Dependencies map shows blockers (Spec 100, Spec 094)
- ✅ "Do not touch" list prevents revisiting closed lanes
- ✅ Rules prevent reuse of selector inputs without evidence (Spec 094 requirement)
- ✅ No code changes, no scoring impact

**Governance Impact**:
- Clinical remains SHADOW ONLY until Spec 099 + Checklist v2
- Catalyst remains SHADOW ONLY until Spec 098 + orthogonality
- Event EV remains MONITORING_ONLY until ≥30 samples + independent return test
- Ranker promotion blocked until Spec 100 IC tool is corrected
- Composite_score IC is NOT ranker evidence

---

## Next Steps

1. **Spec 097** (Event-EV Monitoring) — Simple governance monitor for ≥30 sample threshold
2. **Spec 098** (Catalyst Timing Monitor) — Shadow monitoring post-hygiene-fix
3. **Spec 099** (Clinical Orthogonality Audit) — Orthogonality vs coinvest validation
4. **Spec 100** (IMPLEMENT) — Fix IC tooling, enable true ranker IC measurement

No changes to production scoring until Spec 100 is complete and promotion gates are passed.

---

## Files Inspected

- Memory: `scoring_model_identity_2026_04_06.md` (current roles)
- Specs: 071/078 (catalyst hygiene), 094 (selector baseline), 095 (scope), 100 (IC tool)
- Policy: `policy_alpha_freeze_2026_04_04.md` (Checklist v2 requirement)
- Audits: `ees_v3_structural_failure_2026_04_30.md` (expectation error closure)

---

## Doctrine Approval Signature

**Doctrine created**: 2026-05-13  
**Status**: ACTIVE  
**Enforcement**: All future signal proposals must reference this doctrine and evidence gates.  
**Review date**: 2026-06-13 (after Spec 100 implementation)
