# Ranking Alternatives Research Memo
**Date:** 2026-05-08  
**Author:** T7 [writer] — synthesis of T1–T6  
**Status:** RESEARCH ONLY — no code changes, no production changes, no signal promotion  
**Source files:** t1_ranker_anatomy_2026_05_08.md, t2_ranker_alternatives_2026_05_08.md, t3_data_readiness_2026_05_08.md, t4_risk_analysis_2026_05_08.md, t5_ablation_protocol_2026_05_08.md, t6_alpha_synthesis_2026_05_08.md

---

## A. Executive Summary

This memo synthesizes a structured, multi-agent audit of the production ranker and ten candidate alternatives, conducted 2026-05-08. The study was prompted by two converging observations: (1) the production final_score is dominated by coinvest_score_z (ρ = +0.882 median), leaving ranker marginal contribution indistinguishable from noise at the current evidence base; and (2) the pooled forward IC of -0.031 (t = -1.99) over 17 post-PIT snapshots is inconsistent with the train_accuracy = 1.0 reported at model training — a divergence that quantitatively supports the current OBSERVE posture.

**The single most urgent output of this study is not a research finding — it is a production correctness question.** The financial_score feature in the production ranker carries a negative weight (-0.0533), meaning higher Module 5 composite rank-norm yields a lower pairwise win probability. Two competing interpretations exist: (a) intentional "stress-upside" selection, or (b) coefficient sign inversion during training. This cannot be resolved by further descriptive analysis. It requires direct human review of the training configuration and intent. Until Gate 1 (financial_score sign direction documented) is resolved, Alternative 5 (revised financial_score) is blocked, and any ablation test that uses financial_score as a baseline comparison is methodologically compromised.

A secondary urgent finding: `common/ranker_active_contract.py`, referenced in five audit documents as enforcing 21 drift tests on production ranker inputs, does not exist on disk. No automatic enforcement of the ranker active contract is currently running.

**Recommended immediate actions, in order:**
1. **[CRITICAL — TODAY]** Resolve financial_score sign direction (T8 Escalation 1). Human decision required; no code analysis can substitute.
2. **[URGENT — THIS WEEK]** Document the absence of `ranker_active_contract.py` and decide whether to create the module or accept manual enforcement.
3. **[NOW — DIAGNOSTIC]** Compute Alt 10 (no-ranker selector_score comparator) divergent-snapshot analysis. This requires no gate clearance and frames all subsequent alternatives.
4. **[NOW — DIAGNOSTIC]** Shadow-track catalyst_decay_w and binary_quality_score distributions (Alts 3/4) as descriptive-only; no IC claims.
5. **[MONITOR — HIGH]** Verify Spec 077 binder is populating. The forward-only `event_ev_p_hit` binder has shipped (`_bind_event_ev_p_hit`, node_id exact + ticker/date ±7d fallback). 37 postmortems carry the field; 0 non-null to date — EV artifacts do not yet cover those events. Define the sample-size gate: how many bound post-PIT HIT/MISS records with non-null `event_ev_p_hit` are required before a calibration/return-discrimination audit can run?

---

## B. Investment Context

The production ranker was designed to add marginal ordering signal beyond the A4 selector, which already captures institutional conviction, catalyst quality, survivability, and market structure. The theoretical value of the ranker is to sharpen within-cohort ordering for tickers that all clear the same eligibility and selector gates.

**The problem:** ρ(coinvest_score_z, final_score) = +0.882 (median across snapshots). Jaccard overlap between selector top-30 and ranker top-30 = 57%. The ranker is not providing independent ordering signal — it is largely re-weighting the same institutional conviction measure already dominant in the selector. This is the coinvest double-count: coinvest_score_z appears in the selector institutional block (65% weight) and as the primary pairwise feature (trained weight +0.0613, deployed +0.02 capped). The net effect is that the production ranking pipeline applies coinvest two times on the same tickers.

At the current evidence level (17 post-PIT snapshots, 12 HIT/MISS events, pooled IC = -0.031), it is not possible to statistically distinguish whether the ranker is adding value beyond the selector, degrading it, or is neutral. **Alternative ranking improvements are the primary path to performance above the coinvest baseline.** This study evaluates 10 specific alternatives across the full spectrum from immediately actionable to permanently closed.

---

## C. Current Ranker Anatomy

### Deployment Path

```
Module 2 → Module 5 composite_v3 (rank-norm within stage×size cohort)
  → financial_score

Coinvest size-residualized z-score (half-life 90d, filing-age exponential decay)
  → coinvest_score_z

Decision Engine → eligibility gates → eligible=1

A4 Selector (eligible tickers only):
  compute_selector_scores() → selector_score [0,1] percentile
  → temporary actionable_rank by selector_score (top-60 gate)

Ranker v2 (pairwise_minimal mode):
  filter_cohort(): eligible=1 AND actionable_rank ≤ 60
  zscore_cohort_features(): z-score both features within top-60 cohort
  score_name(): avg pairwise win probability vs all cohort members
  → final_score = ranker_v2_score (cohort members)
  → final_score = selector_score × 0.0001 (eligible non-cohort)

Top-30: sorted(eligible_rows, key=-final_score)[:30]
```

### A4 Selector Weights

| Block | Weight | Components |
|-------|--------|-----------|
| Institutional | 65% | coinvest_score_z 100%; inst_delta_z 0.00 (demoted 2026-05-04) |
| Catalyst | 15% | catalyst_decay_w 30%, binary_quality_score 25%, cat_priority 20%, catalyst_strength 15%, catalyst_family 10% |
| Survivability | 10% | financial_score 35%, severity 35%, runway_bucket 30% |
| Market structure | 10% | de_vol_60d, de_beta_xbi_60d, de_drawdown, de_rsi_14d |
| Clinical | 0% | (closed) |

### Production Ranker v2 Model

- **Schema:** ranker_v2_model.v1, type: pairwise_logistic (Bradley-Terry)
- **Features:** coinvest_score_z, financial_score
- **Weights:** coinvest_score_z +0.02 (capped; trained +0.0613); financial_score -0.05332 (uncapped, full trained strength)
- **Bias:** 0.5019
- **Training:** 36 dates, 12,400 pairs; **train_accuracy = 1.0 [OVERFITTING FLAG]**
- **Rollback artifact:** ranker_v2_model_5feat_rollback.json (5-feature set, not in production)

### Governance Finding

**`common/ranker_active_contract.py` is on an unmerged branch.** The module (21 drift tests, commit `e7c0ee47`) was developed on `hygiene/ranker-active-contract-2026-04-30` and has not been merged to main. Production code on main does not import or call it. This is a merge/governance gap — not a missing enforcement layer that is breaking anything in production. Five audit documents reference it as live enforcement; those references are stale and should be corrected. Decision required: merge the branch, or formally accept manual enforcement and update the audit documents.

### Coinvest Double-Count Confirmed

ρ(coinvest_score_z, final_score) = +0.882 median. Jaccard selector↔ranker top-30 = 57%. The ranker is not providing meaningful independent ordering signal at the current evidence base.

---

## D. Production Correctness Question

### The financial_score Sign Direction Issue [CRITICAL]

The financial_score feature in the production ranker carries weight **-0.0533** (uncapped, full trained strength). In a pairwise Bradley-Terry model, a negative weight means: *a ticker with a higher financial_score is predicted to lose more pairwise comparisons, all else equal*.

**financial_score** is the Module 5 composite rank-norm — higher values indicate stronger financials within the stage×size cohort. A negative weight therefore systematically ranks weaker-financial tickers above stronger-financial ones, within the top-60 cohort.

**Two competing interpretations exist:**

1. **Intentional "stress-upside" thesis:** The ranker is deliberately selecting tickers under financial stress that have high coinvest conviction, on the theory that high-conviction stressed companies represent asymmetric upside. This is a coherent, if aggressive, investment thesis.

2. **Coefficient sign inversion:** The training process inverted the sign, possibly due to a label encoding issue, a feature direction mismatch, or an interaction with the bias term during logistic fitting. In this case, the ranker is actively penalizing financial quality — the opposite of intent.

**Why this matters beyond research:** This is not a question about whether financial_score is a good predictor. It is a question about whether the production model is functioning as intended. If interpretation (2) is correct, every production ranking since deployment has applied an inverted quality filter to the top-60 cohort. This would affect every forward IC measurement, every HIT/MISS attribution, and every ablation baseline.

**What analysis cannot resolve this:** No amount of IC measurement or ablation testing can resolve the intent question. The training configuration, the label construction, and the original model specification must be reviewed directly by the operator who designed the training run.

**Blocker consequence:** Until Gate 1 is resolved:
- Alt 5 (revised financial_score) is fully blocked — there is no baseline to improve from.
- Any ablation test that benchmarks against the production ranker is measuring against a potentially inverted model.
- The forward IC of -0.031 cannot be interpreted cleanly — it may reflect sign inversion rather than model failure.

**This is not a research priority. It is a production correctness priority.** See Section J, T8 Escalation 1.

---

## E. The 10 Alternatives — Taxonomy and Category Assignments

The table below shows all 10 alternatives with their T6 category assignments and time-to-valid-test. See T2 for full thesis detail and T4 for full risk analysis.

| Alt | Name | T6 Category | Time to Valid Test | Key Basis |
|-----|------|-------------|-------------------|-----------|
| 1 | Momentum / mean-reversion | **LOW_POTENTIAL** | Archive; N/A | Jaccard 0.42 vs production; already captured in selector market structure block (10%); no biotech event-driven mechanism. Do not pursue. |
| 2 | inst_delta_z restoration | **MEDIUM_POTENTIAL_SHADOW** | ~2026-07-15 (post-quarantine + Gate 4) | Pre-PIT IC=+0.077, B6 Δ=+1.85pp — ALL INVALIDATED. Demoted to 0.00 in selector 2026-05-04. Post-quarantine descriptive allowed; no promotion without Checklist v2. |
| 3 | Catalyst timing (catalyst_decay_w) | **HIGH_POTENTIAL_BUT_BLOCKED** | 2026-Q4 (Lane 2 + Gate 4) | ρ=+0.19 across 17 snapshots — descriptive only, NOT alpha evidence [REGIME_CAVEAT]. Blocked on Spec 071 Lane 2 (false-catalyst classifier). |
| 4 | Catalyst quality (binary_quality_score) | **HIGH_POTENTIAL_BUT_BLOCKED** | 2026-Q4 (Lane 2 + Gate 4) | D9 conditional IC ~+0.20 within top coinvest — PRELIMINARY [REGIME_CAVEAT]. Same Lane 2 blocker as Alt 3. |
| 5 | Revised financial_score | **NEEDS_HUMAN_REVIEW** | After Gate 1 (financial_score sign direction) | Cannot assess until production correctness question resolved. Category may change to LOW_POTENTIAL, MEDIUM, or HIGH depending on Gate 1 outcome. |
| 6 | Event-EV (event_ev_p_hit) | **HIGH_POTENTIAL_BUT_BLOCKED** | 2026-Q4 at earliest (prospective accumulation) | 6-layer Bayesian framework exists. Spec 077 binder shipped (node_id exact + ±7d fallback). 37 postmortems carry the field; 0 non-null — EV artifacts not yet covering those events. Blocker is prospective sample accumulation, not binder infrastructure. |
| 7 | EES v3 (conditional_misprice_score) | **NO_GO PERMANENT** | N/A | Spearman -0.978 with pmv; monotonic transform; IC ~0 after pmv control. Cannot extract expectation error from expectation alone. Do not reopen. |
| 8 | Clinical design quality | **NO_GO** | N/A (Phase A verdict review 2026-05-22 only) | Phase A verdict NO_GO for selector; all clinical ranker use prohibited. Verdict review 2026-05-22 is a scheduled checkpoint, not a promotion path. |
| 9 | Hybrid composite | **NO_GO** | ≥2027 (after individual signals clear Checklist v2) | n=12 HIT/MISS is fatally underpowered for composite evaluation. Replicates EES v3 methodological path. Do not build until each component individually clears Checklist v2. |
| 10 | No-ranker selector_score comparator | **MEDIUM_POTENTIAL_SHADOW** | NOW (descriptive); 2026-07-15 (powered) | Null hypothesis. Computable immediately. Frames all other alternatives. Must be computed before any alternative can be evaluated against "beating production." |

### Notes on Category Assignments

**LOW_POTENTIAL (archive):** Alt 1. The momentum signal is already partially captured in the selector market structure block. Adding it as a ranker feature would create partial double-count without an event-driven mechanism. No further investigation warranted.

**NO_GO PERMANENT:** Alt 7. The structural failure (pmv-dominance, monotonic transform, IC ~0 after pmv control) is architectural, not a parameter issue. No re-formulation of EES v3 within the current data environment can resolve it. See `ees_v3_structural_failure_2026_04_30.md`.

**NO_GO:** Alt 8. The Phase A verdict for clinical lanes is explicit: selector NO_GO, ranker SHADOW for clinical_design_quality only within the clinical block (which carries 0% weight in production). Applying clinical features to the main ranker is prohibited.

**HIGH_POTENTIAL_BUT_BLOCKED (Alts 3, 4, 6):** These are the most promising alternatives by thesis strength. For Alt 6: the Spec 077 binder infrastructure is shipped; the blocker is prospective EV artifact accumulation (0 non-null binds to date). For Alts 3 and 4: data quality (Spec 071 Lane 2 false-catalyst classifier). No descriptive analysis substitutes for resolving these blockers before formal IC testing.

---

## F. Data and Evidence State

### What Is Available Now

| Dataset | State | Usable for |
|---------|-------|-----------|
| Post-PIT canonical snapshots | 17 clean (2026-04-17 to 2026-05-08) | Descriptive analysis; NOT powered for formal IC |
| forward_returns_panel.csv | 5,949 rows; excess_return_5d through 2026-05-08 | Divergent-snapshot comparisons; descriptive only |
| Post-PIT HIT/MISS records | 12 total (HIT=7, MISS=5) | Descriptive; Gate 4 (n≥30) requires ~2026-07-15 |
| catalyst_decay_w, binary_quality_score | Available in selector scoring artifacts | Distribution diagnostics; NOT ranker IC testing |
| coinvest_score_z, financial_score | Available in all snapshots | Ablation baseline (after Gate 1 cleared) |

### What Is Blocked

| Blocker | Gates | Expected clearance |
|---------|-------|-------------------|
| Gate 1: financial_score sign direction | Alt 5; ablation baseline integrity | Unscheduled; T8 Escalation 1 required |
| Gate 2: Spec 071 Lane 2 (false-catalyst classifier) | Alts 3, 4 formal IC | ~2026-Q3 |
| Gate 3: n≥N bound post-PIT HIT/MISS with non-null event_ev_p_hit | Alt 6 (Event-EV) formal IC | Prospective accumulation; binder shipped; 0 non-null to date |
| Gate 4: n≥30 post-PIT HIT/MISS | All formal IC tests | ~2026-07-15 at ~3-4 events/month |
| Gate 5: 13F quarantine lifted | Alt 2 (inst_delta_z) | ~2026-05-20 |
| Gate 6: ≥30 non-overlapping snapshots post-cohort-change | Catalog-level comparisons | ~2026-06-15 |

### IC Measurement Tool Bug [CRITICAL FOR METHODOLOGY]

**Gate 7 (from T5):** The current `ic_decomposition.py` computes IC across the full ~297-ticker universe. The production ranker operates exclusively within the top-60 selector cohort. **Any IC measurement run on the full universe is measuring the wrong population.** The tool must be corrected before any formal ranker IC test is reported. IC estimates from the full universe are not comparable to ranker performance.

### Regime Caveats

The April 2026 window carries structural confounds that invalidate IC estimates from that period for alpha-quality inference:

- XBI selloff: 2026-04-21 to 2026-04-25 (sector-wide drawdown)
- Cohort change: 2026-04-25 (4 new managers added; inst_delta_z byte-identical across 04-25/27/28)
- 13F quarantine: Q1 2026 refresh ~2026-05-15; inst_delta_z contaminated until cleared

**All IC estimates from April 2026 carry [REGIME_CAVEAT].** The preliminary D9 conditional IC ~+0.20 (Alts 3/4) was measured in this window. It is PRELIMINARY only and cannot be treated as alpha evidence.

---

## G. Risk Register Highlights

Full risk analysis in T4. The five highest-priority risks for this research program:

### Risk 1: financial_score Sign Direction [CRITICAL]

- **Nature:** Production correctness. If the coefficient is inverted, the ranker has been systematically penalizing financial quality since deployment.
- **Impact:** Every forward IC measurement, every HIT/MISS attribution, every ablation baseline is potentially measuring an inverted model.
- **Resolution path:** Human review of training configuration (T8 Escalation 1). No code analysis substitutes.
- **Current status:** UNRESOLVED.

### Risk 2: EES v3 Governance [CRITICAL]

- **Nature:** Any softening of the EES v3 NO_GO PERMANENT verdict (e.g., "let's test a variant") replicates the exact methodological error that made EES v3 a years-long false lead.
- **Rule:** Alt 7 is CLOSED. No re-formulation of expectation error from expectation-derived inputs. T8 Escalation 2 exists to formally confirm this closure.
- **Current status:** Closed in this memo. Requires T8 confirmation of permanent closure.

### Risk 3: Underpowered Composite (Alt 9) [CRITICAL]

- **Nature:** n=12 HIT/MISS is fatally underpowered for evaluating any composite signal. At this sample size, FDR-corrected significance is unreachable for a 2-feature composite, let alone a multi-feature one.
- **Governance rule:** Alt 9 is NO_GO until every individual component independently clears Checklist v2. That is a 2027+ horizon.
- **Current status:** Closed. No exceptions.

### Risk 4: Multiple Testing / FDR [HIGH]

- **Nature:** With 10 alternatives under evaluation, the family-wise error rate at α=0.05 allows 0.5 false discoveries by chance. At n=12 HIT/MISS, standard FDR correction (Benjamini-Hochberg) will reject essentially all results.
- **Mitigation:** Formal IC tests must use block bootstrap with NW-corrected t (≥5 lags) and pre-registered hypotheses. No post-hoc significance claims on descriptive distributions.
- **Current status:** No formal tests have been run. Risk is prospective.

### Risk 5: IC Evaluation Scope Gap (Gate 7) [HIGH]

- **Nature:** `ic_decomposition.py` was designed to measure `coinvest_score_z` IC across all eligible tickers — that is its correct designed purpose. For ranker-specific IC measurement (final_score or an alternative signal within the top-60 cohort), a different evaluation scope is required. The current tool cannot directly answer "does this ranker signal add value within the top-60?" without modification.
- **Mitigation:** Before running any formal ranker alternative IC test, confirm the evaluation is filtered to the top-60 cohort and measures the appropriate signal (final_score or the alternative, not coinvest_score_z alone).
- **Current status:** Evaluation scope gap documented. The tool is not broken; it is measuring what it was designed to measure. Ranker IC testing requires a different or extended scope.

---

## H. Evaluation Protocol Design

### The 7 Gates

| Gate | Condition | Status | Alts Gated |
|------|-----------|--------|-----------|
| G1 | financial_score sign direction documented | UNRESOLVED [CRITICAL] | Alt 5; ablation baseline integrity |
| G2 | Spec 071 Lane 2 complete | BLOCKED (~2026-Q3) | Alts 3, 4 formal IC |
| G3 | Spec 077 join fix + n≥1 bound EV record | BLOCKED (no timeline) | Alt 6 |
| G4 | n≥30 post-PIT HIT/MISS | 12/30 (~2026-07-15) | All formal IC tests |
| G5 | 13F quarantine lifted | ~2026-05-20 | Alt 2 (inst_delta_z) |
| G6 | ≥30 non-overlapping snapshots post-cohort-change | ~2026-06-15 | Catalog-level IC |
| G7 | IC evaluation scoped to top-60 cohort (not full eligible universe) | SCOPE GAP | All formal ranker alternative IC tests |

### The 4 Evaluation Phases

**Phase 0 — IMMEDIATE (no gates required)**
- Gate verification: confirm G5 clearance date; log G1 escalation outcome.
- Alt 10 descriptive: compute selector_score vs. final_score divergent-snapshot comparison across all 17 post-PIT snapshots.
- financial_score audit: confirm weight direction in `ranker_v2_model.json`; escalate to T8.
- Fix ic_decomposition.py scope (G7).

**Phase 1 — NOW, descriptive shadow (no formal IC)**
- Alt 10: identify snapshots where selector_score top-30 ≠ final_score top-30; classify divergent tickers by feature direction.
- Alts 3/4: track catalyst_decay_w and binary_quality_score distributions in top-60 cohort; descriptive statistics only. No IC claims.
- Alt 2: wait for G5 (13F quarantine lift ~2026-05-20); then descriptive comparison of pre/post inst_delta_z distributions.

**Phase 2 — ~2026-07-01, formal descriptive IC (G4 + G7 required)**
- Alt 10: formal IC comparison selector_score vs. final_score within top-60 cohort. Block bootstrap, NW-corrected t (≥5 lags).
- Alt 2: formal IC for inst_delta_z (post-quarantine + G4). Pre-register hypothesis before running.

**Phase 3 — ~2026-Q3, catalyst alternatives (G2 + G4 required)**
- Alts 3, 4: formal IC for catalyst_decay_w and binary_quality_score within top-60 cohort.
- Report separately; do NOT combine into composite (Alt 9 is NO_GO).

**Phase 4 — ~2026-07-31+, Checklist v2 eligible tests**
- Any signal that clears Phase 2 or Phase 3 with sufficient IC (t > 2.0, NW-corrected, ≥5 lags) may be presented for Checklist v2 evaluation.
- Checklist v2 requires: FM test + bootstrap + FDR + LOSO + year stability.
- **PROMOTION_ELIGIBLE is a 2027 horizon. No exceptions. State this explicitly in every Phase 4 planning document.**

### Pass/Fail Verdict Categories

| Verdict | Meaning |
|---------|---------|
| SHADOW_CANDIDATE | Descriptive patterns consistent with hypothesis; no formal power |
| FORMAL_CANDIDATE | Formal IC test passed (G4 + G7 cleared); Checklist v2 not yet run |
| PROMOTION_ELIGIBLE | Checklist v2 5/5 complete; ready for human promotion decision |
| NO_GO | Failed formal IC, or governance rule closed the lane |
| FRAGILE | Passed but not robust to regime change or cohort shift |
| UNSAFE | Methodological failure (e.g., pmv-leakage); permanent closure |

### Binding Evaluation Rules

1. IC must be computed within the top-60 cohort (not full universe) after G7 fix.
2. Block bootstrap with NW-corrected t (≥5 lags) required for all formal IC tests.
3. No promotion before Checklist v2 5/5.
4. No composite (Alt 9) before individual components clear Checklist v2.
5. **PROMOTION_ELIGIBLE is a 2027 horizon.** Do not soften this estimate in any downstream planning document.
6. All April 2026 IC estimates retain [REGIME_CAVEAT] in perpetuity. They are not alpha evidence.

---

## I. Recommended Immediate Actions

Actions are ordered by urgency. "NOW" means within 48 hours. "THIS WEEK" means before 2026-05-15. "BLOCKED" means no action possible until prerequisite resolved.

### NOW (no gates required)

1. **Escalate financial_score sign direction to T8 (Escalation 1).** Provide: (a) production weight = -0.0533; (b) feature definition = Module 5 composite rank-norm, higher = stronger financials; (c) the two competing interpretations; (d) the training run configuration or contact for the person who ran it. Decision must be documented in writing before any ablation test proceeds.

2. **Resolve `ranker_active_contract.py` merge gap.** The module (21 drift tests, commit `e7c0ee47`) exists on branch `hygiene/ranker-active-contract-2026-04-30` but is not on main. Decision: (a) merge the branch, (b) formally accept manual enforcement and update the 5 stale audit documents, or (c) scope a replacement. Do not leave the discrepancy unresolved — 5 audit documents currently assert enforcement that is not running.

3. **Compute Alt 10 descriptive analysis.** Using `forward_returns_panel.csv` and the 17 post-PIT canonical snapshots: identify all snapshots where selector_score top-30 ≠ final_score top-30 (divergent snapshots); for each divergent snapshot, compute excess_return_5d for the selector-only tickers vs. ranker-override tickers. This is a descriptive comparison, not a formal IC test. No significance claims. Report counts and median return differentials only.

4. **Define the IC evaluation scope for ranker testing.** `ic_decomposition.py` correctly measures `coinvest_score_z` IC across all eligible tickers (its designed purpose). For ranker alternative IC tests (final_score or alternative signal within top-60 cohort), a separate evaluation scope is needed. Document this as a Gate 7 precondition before any formal ranker IC test is reported — no code change required now, but the scope must be specified before Phase 2 opens.

### THIS WEEK (before 2026-05-15)

5. **Shadow-track catalyst_decay_w and binary_quality_score distributions in the top-60 cohort.** Compute 17-snapshot time series of: median, p25, p75, and fraction of tickers with catalyst_decay_w > 0.5. Descriptive only. No IC claims. This establishes the baseline before Spec 071 Lane 2 data quality work begins.

6. **Confirm G5 clearance date (13F quarantine).** The Q1 2026 13F refresh is expected ~2026-05-15. On clearance, run the pre/post quarantine comparison harness (`tools/check_13f_cohort_quarantine.py`) and record the Jaccard score. If Jaccard < 0.70, the quarantine is not clear regardless of date.

### AFTER GATE CLEARANCE

7. **Alt 2 (inst_delta_z) descriptive:** After G5 cleared, compute distribution comparison of inst_delta_z in top-60 cohort, pre and post quarantine. Descriptive only.

8. **Alt 6 (Event-EV) Spec 077 join fix:** After T8 Escalation 3 decision, if Spec 077 is prioritized, confirm the fix with n≥1 non-null `event_ev_p_hit` record joined to a canonical snapshot. Do not proceed to formal IC until G3 and G4 both cleared.

9. **Phase 2 formal IC (Alt 10, Alt 2):** After G4 (~2026-07-15) and G7 both cleared, run formal block-bootstrap IC comparison for Alt 10 and Alt 2 within top-60 cohort. Pre-register hypotheses in a spec document before running.

### PERMANENTLY BLOCKED (do not attempt)

- Alt 7 (EES v3): CLOSED. No reformulation.
- Alt 8 (clinical ranker features): CLOSED. Phase A verdict NO_GO.
- Alt 9 (hybrid composite): NO_GO until 2027+.
- Any formal IC test before G7 fixed.
- Any ablation test before G1 (financial_score sign direction) resolved.

---

## J. T8 Escalations (Decision Items for Human Gate)

These four items require human decision. They are not resolvable by further analysis. All four are surfaced simultaneously.

---

### Escalation 1: financial_score Sign Direction [CRITICAL]

**Question:** Was the negative weight on financial_score in the production ranker v2 intentional (stress-upside thesis) or the result of a sign inversion during training?

**Decision owner:** The operator who designed the ranker v2 training run and approved deployment.

**Evidence to review:**
- Production weight: -0.05332 (uncapped, full trained strength)
- Feature: Module 5 composite_v3, rank-norm within stage×size cohort (higher = stronger financials)
- Training: 36 dates, 12,400 pairs; train_accuracy = 1.0 (overfitting flag)
- Deployed cap: coinvest_score_z capped at +0.02; financial_score uncapped

**Blocker consequence:** Until resolved, Alt 5 is blocked, ablation baselines are unreliable, and the interpretation of pooled IC = -0.031 is ambiguous. This blocks Gate 1 and partially blocks Phases 1–4.

**Urgency: IMMEDIATE — before any ablation test proceeds.**

---

### Escalation 2: EES v3 Permanent Closure Confirmation [LOW]

**Question:** Is the EES v3 / conditional_misprice_score formulation permanently closed, with no path to reopening under the current data environment?

**Decision owner:** Research governance lead.

**Evidence:** Spearman ρ(conditional_misprice_score, pmv) = -0.978; IC ≈ 0 after pmv control; base_rate_gap_score remains anti-predictive; structural diagnosis in `ees_v3_structural_failure_2026_04_30.md`. The rule "cannot extract expectation error from expectation alone" is correctly identified.

**Blocker consequence:** If not formally confirmed as CLOSED, future agents may attempt to reopen the lane. Formal closure prevents governance drift.

**Urgency: LOW — confirm at next scheduled research governance review. Not blocking anything today.**

---

### Escalation 3: Event-EV Calibration Sample-Size Gate [HIGH]

**Question:** (a) What count of bound post-PIT HIT/MISS records with non-null `event_ev_p_hit` is required before a calibration / return-discrimination audit can run for Alt 6? (b) What monitoring should confirm the binder is populating future records correctly?

**Decision owner:** Research lead.

**Evidence:** The Spec 077 forward-only binder has shipped (`_bind_event_ev_p_hit` in `catalyst_resolution_tracker.py`; node_id exact match + ticker/date ±7d fallback; no unsafe historical backfill). The field `event_ev_p_hit` is present in 37 postmortem records under `resolution_source`; all 37 are currently null because EV artifacts do not yet cover those specific events. The binder architecture is correct; the blocker is prospective EV artifact accumulation.

**Blocker consequence:** Alt 6 cannot contribute to any formal IC test until enough bound HIT/MISS records accumulate. Without a defined sample-size gate, there is no clear trigger for when the first calibration audit runs.

**Recommended next step:** Define the minimum n of bound records required (suggested: n≥15 for first calibration look, n≥30 for formal IC). Verify the postmortem pipeline is producing new EV artifacts post-binder-ship to ensure prospective population is happening.

**Urgency: HIGH — gate definition needed before 2026-05-20. No code change needed.**

---

### Escalation 4: Spec 071 Lane 2 Timeline Confirmation [MODERATE]

**Question:** Is the ~2026-Q3 estimate for Spec 071 Lane 2 (false-catalyst OLE/PK classifier) still the expected delivery date, and is it on the development roadmap?

**Decision owner:** Development lead for Spec 071.

**Evidence:** Lane 2 is the prerequisite for formal IC testing of Alts 3 and 4. Without the false-catalyst classifier, catalyst_decay_w and binary_quality_score cannot be trusted as clean alpha inputs — they may reflect OLE/PK filings (false catalysts) that inflate the signal.

**Blocker consequence:** If Lane 2 slips to 2026-Q4 or beyond, Alts 3 and 4 formal IC testing moves to 2027, and the 2026 research calendar has no formal IC tests for the highest-potential alternatives.

**Urgency: MODERATE — confirm at next sprint planning, before 2026-05-20.**

---

## K. Research Calendar

The calendar below covers the period through 2027-04-17 (year stability gate for Checklist v2). Milestones marked **[HARD GATE]** are non-negotiable prerequisites — no subsequent work in that lane can proceed without them.

### Near-Term (2026-05-08 to 2026-06-15)

| Date | Milestone |
|------|-----------|
| 2026-05-08 | T7 memo complete; T8 escalations surfaced |
| 2026-05-09 | T8 decision on Escalation 1 (financial_score sign direction) [HARD GATE] |
| 2026-05-09 | T8 decision on Escalation 3 (Spec 077 timeline) |
| ~2026-05-12 | Event-analyst builder verification (cron fire check for 6 weekday artifacts 05-04→05-11) |
| ~2026-05-15 | 13F Q1 2026 refresh expected; run quarantine check harness |
| ~2026-05-20 | Gate 5 clearance: 13F quarantine lift (if Jaccard ≥ 0.70) [HARD GATE for Alt 2] |
| ~2026-05-20 | T8 decision on Escalation 4 (Lane 2 timeline) |
| 2026-05-22 | Clinical Phase A verdict review (scheduled checkpoint; not a promotion path) |
| 2026-05-22 | Forward return test prod vs. coinvest re-run (n=8→n≥12) |
| 2026-05-26 | inst_delta forward shadow verdict h20d |
| 2026-05-26 | Cross-signal forward shadow verdict h20d |
| ~2026-06-15 | Gate 6: 30 non-overlapping snapshots post-cohort-change |

### Medium-Term (2026-06-15 to 2026-09-30)

| Date | Milestone |
|------|-----------|
| ~2026-07-01 | Phase 2 opens: formal descriptive IC for Alt 10 + Alt 2 (if G4 + G7 cleared) |
| ~2026-07-01 | Check event_ev_p_hit binder population: how many postmortems now have non-null records? Gate 3 progress update. |
| ~2026-07-15 | **Gate 4: n≥30 post-PIT HIT/MISS** [HARD GATE for all formal IC tests] |
| ~2026-07-21 | inst_delta forward shadow final verdict |
| ~2026-07-31 | Phase 4 opens: first Checklist v2 eligible test (if Phase 2 produced FORMAL_CANDIDATE) |
| ~2026-Q3 | Spec 071 Lane 2 delivery (if confirmed); gates Alts 3 + 4 formal IC |
| ~2026-Q3 | Phase 3 opens: Alts 3 + 4 formal IC (if G2 + G4 + G7 all cleared) |

### Long-Term (2026-Q4 to 2027-Q2)

| Date | Milestone |
|------|-----------|
| ~2026-Q4 | Alt 6 (Event-EV) formal IC (if G3 — bound EV sample gate — + G4 + G7 all cleared) |
| ~2026-Q4 | Year stability gate eligible for any signal promoted in Q3 2026 |
| ~2026-12-31 | Review which alternatives have reached FORMAL_CANDIDATE or PROMOTION_ELIGIBLE |
| **2027-04-17** | **Year stability gate for any signal trained on 2026 data** [Checklist v2 requirement] |
| ~2027-H1 | First realistic PROMOTION_ELIGIBLE verdict for any alternative |

### Standing Weekly Cadence

- **Daily 19:30 ET:** inst_delta forward shadow update
- **Daily 19:40 ET:** Cross-signal forward shadow update
- **Weekly:** Canonical snapshot count; HIT/MISS accumulation rate check against Gate 4 timeline
- **Monthly:** Forward return test re-run; forward shadow rolling median update
- **Quarterly:** Research calendar review; update gate clearance estimates

---

*End of memo. This document is research only. No signal has been promoted, no code changed, no production system modified.*
