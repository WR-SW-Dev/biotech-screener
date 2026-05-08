# T4 — Quant Finance Risk Analysis (2026-05-08)

**Author:** T4 [analyst]
**Task:** Quant finance risk analysis of current ranker and 10 ranking alternatives (Task #4 in ranking-alternatives research queue)
**Date:** 2026-05-08
**Status:** Research memo — read-only. No code changes. No production artifact writes. No promotions recommended.

---

## Scope and method

This memo assesses quantitative finance risks for (1) the current production ranker as deployed and (2) each of the 10 ranking alternatives documented in T2. Risk categories analyzed:

- **Overfitting and sample fragility** — in-sample vs out-of-sample reliability
- **Data snooping and multiple-comparisons exposure** — family-wise error and specification search
- **Signal collapse under production conditions** — leakage, double-counting, contamination
- **Model error and correctness** — coefficient sign, normalization, feature directionality
- **Structural regime risk** — sensitivity to market/cohort shifts
- **Inference bias risks** — PIT validity, forward-contamination, survivorship

Hard constraint honored throughout: no code changes, no backtests, no IC computations. All claims grounded in T1/T2/T3 findings, memory files, and the IC decomposition readout (2026-05-08).

---

## Section 1 — Current production ranker: risk profile

### 1.1 Overfitting: training accuracy = 1.0

The ranker artifact (`production_data/ranker_v2_model.json`) records `train_accuracy = 1.0` on the pairwise set. T1 notes this explicitly as an overfitting flag.

**Risk level: MEDIUM-HIGH.**

A Bradley-Terry pairwise logistic model with 2 features trained on 36 snapshot dates and 12,400 pairs achieving 1.0 training accuracy is consistent with — though not conclusive evidence of — overfitting. The pairs are drawn from a highly correlated universe (same tickers, overlapping dates, within-cohort pairings), so the effective independent-sample count is substantially below 12,400. The model's extreme accuracy more likely reflects the fact that `coinvest_score_z` nearly perfectly separates institutional-quality tiers within the training cohort than that the model has memorized individual pairs — but the distinction matters for generalization.

**Manifestation:** The deployed cap on `coinvest_score_z` (+0.02 vs trained +0.0613) partially addresses this by preventing the model from applying the full learned separation, but the cap was applied empirically ("Family C calibration") and the derivation basis is not clearly documented. If the cap was fit to the same or overlapping data, the practical overfitting risk is not substantially reduced.

**Forward evidence check:** The IC decomposition readout (2026-05-08) shows pooled coinvest IC = -0.031 (t = -1.99) across 14 snap dates. This is not consistent with the strong in-sample performance. The post-cohort mean IC = -0.008 (flat). The divergence between in-sample accuracy = 1.0 and out-of-sample IC near zero is quantitatively significant and should be monitored.

---

### 1.2 Coinvest double-counting: selector-to-ranker amplification

As established in T1, the confirmed median Spearman ρ(coinvest_score_z, final_score) = +0.882 on clean snapshots. `coinvest_score_z` drives 92.7% of selector variance and appears as Feature 1 in the ranker.

**Risk level: HIGH (structural).**

The pipeline structure creates systematic amplification of the primary signal through both stages. Even with the ranker coinvest cap at +0.02, the ranker operates on a pre-filtered cohort where all members were selected primarily by `coinvest_score_z`. Range restriction within the top-60 cohort reduces the effective variance of coinvest within the ranking problem — making the coinvest ranker weight less meaningful per unit of coefficient than it was during training (where the signal ranged across the full universe).

**Implication for IC measurement:** Spec 081 §5 item 3 explicitly flags this: "IC within the selected cohort (coinvest-filtered) may be lower. Measure and document this separately." The current IC decomposition tool measures IC across the full ~297-ticker universe, not within the top-60 cohort where the ranker actually operates. Any IC claim for the ranker should be assessed within the restricted cohort, not universally.

---

### 1.3 Financial_score sign direction: open correctness question

The ranker's `financial_score` coefficient is -0.0533 (deployed at full trained strength, not capped). The negative sign means: higher Module 5 rank-norm → lower pairwise win probability.

**Risk level: MEDIUM-HIGH (correctness, not just research quality).**

Spec 074 documents the causal hypothesis (financially-constrained names within coinvest cohort have higher binary upside) but explicitly states this is "the best-supported interpretation," not confirmed design intent. Spec 081 §5 item 1 identifies this as a design decision that "must be answered before any ranker retrain."

The correctness risk: if `financial_score` (Module 5 rank-norm) actually scores names where higher = better balance-sheet quality for survival, the -0.0533 weight is paradoxically penalizing the most financially resilient names. In a biotech universe where ~5-10% of names face significant near-term dilution risk, penalizing good balance sheets means systematically overweighting the most distressed segment.

**Falsification criteria from Spec 074:** The hypothesis is falsified if (a) bottom-quartile financial_score names in the top-30 have > 2× base MISS rate at n ≥ 10; (b) top-30 financial_score median falls below P25 of universe for ≥ 3 consecutive snapshots without proportional performance improvement. Neither criterion has been formally monitored against current data.

**T4 priority escalation:** Verify the directional interpretation of `financial_score` against `docs/MODEL_DOCUMENTATION.md` and Module 5 rank-norm construction before any downstream risk assessment involving this coefficient is treated as settled.

---

### 1.4 Absent field contract enforcement

T1 found that `common/ranker_active_contract.py` — referenced in 5 audit documents as enforcing 21 drift tests on active ranker fields — does not exist on disk.

**Risk level: MEDIUM (governance/monitoring gap).**

The deployed ranker's feature selection is effectively enforced only by the `feature_names` list in `ranker_v2_model.json` and the pairwise scoring code path. There is no runtime assertion that the fields presented to the ranker at scoring time match the fields used at training time in units, normalization, or z-score method. A silent drift in, e.g., the cohort used for z-scoring `coinvest_score_z` within the top-60 ranker cohort would not be caught by any test currently on disk.

---

### 1.5 Pre-PIT training contamination

The ranker was trained on 36 snapshot dates predating the PIT-fix (post-PIT-valid production period begins 2026-04-17). Training data is therefore partially contaminated.

**Risk level: MEDIUM.**

Per the Historical Backtest Invalidated finding (2026-04-17 audit): "Prior PIT v2 snapshots (ruleset `69a0c7f8`) contaminated; 3-8/30 top-30 overlap with current." The coinvest cap (+0.02 vs +0.0613) reduces the impact on coinvest, but the financial_score weight was NOT capped — it runs at full trained strength (-0.0533) against a coefficient fit under potentially contaminated conditions.

---

### 1.6 Cohort contamination and regime sensitivity

The 2026-04-25 manager addition (+4 managers to `elite_core`) introduced a cohort-change distortion. Post-cohort snapshots (5 dates) show mean IC = -0.008 (flat), while pre-cohort (9 dates) showed mean IC = -0.051. The IC decomposition readout attributes the pre-cohort negativity to the XBI selloff cluster (April 21-25) rather than structural signal inversion.

**Risk level: MEDIUM (regime sensitivity, interpretive ambiguity).**

The Q1 2026 13F refresh (~2026-05-15) is a second regime event that will shift `coinvest_score_z` values across the universe again. The ranker was trained in one manager-registry regime and deployed into a different regime. Forward IC measurements straddling both regimes conflate signal quality changes with registry changes. The post-13F-refresh clean snapshots (≥2026-05-20) will be the first regime-stable data for the current ranker configuration.

---

### 1.7 Current production risk summary

| Risk | Category | Level | Primary mitigation | Gap |
|---|---|---|---|---|
| Training accuracy = 1.0 | Overfitting | MEDIUM-HIGH | Coinvest cap at deployment | Cap derivation undocumented |
| Coinvest double-counting (ρ=+0.882) | Signal amplification | HIGH | Cap (+0.02 vs +0.0613) | Range restriction not corrected |
| financial_score sign direction | Correctness | MEDIUM-HIGH | Spec 074 documents hypothesis | Directionality unverified |
| No ranker field contract enforcement | Governance | MEDIUM | Manual code review | Contract module missing |
| Pre-PIT training contamination | Data quality | MEDIUM | Cap at deployment reduces impact | Full post-PIT retrain not done |
| Manager registry regime sensitivity | Structural | MEDIUM | 13F refresh guardrails | IC conflates regime changes |
| IC near zero (forward, post-PIT) | Generalization | HIGH | OBSERVE posture | No gate trigger reached |

---

## Section 2 — Per-alternative risk analysis

### Alternative 1 — Current baseline (coinvest + financial_score)

**Overfitting risk:** MEDIUM-HIGH (train_accuracy=1.0 on potentially contaminated pre-PIT data).

**Snooping risk:** LOW for this alternative (not selected via feature search). However, the cap deployment (+0.02) was a post-training adjustment that could be interpreted as in-sample tuning of the deployment threshold.

**Signal collapse risk:** MEDIUM-HIGH. The pooled IC of -0.031 (t=-1.99) across 14 post-PIT dates is negative and borderline significant. The OBSERVE posture is appropriate — but the risk that coinvest signal has genuinely weakened cannot be dismissed with n=14 dates.

**Correctness risk:** MEDIUM-HIGH (financial_score sign unverified; see §1.3).

**Regime risk:** MEDIUM (manager registry change 2026-04-25 + 13F refresh 2026-05-15 both affect coinvest_score_z).

**Structural risk:** LOW. Two-feature model is transparent and auditable.

**Overall risk level:** MEDIUM-HIGH. The main risk is that the model is effectively a coinvest re-sort with a financial noise term — not a genuinely two-dimensional predictor. Forward evidence is too thin to confirm or deny this.

---

### Alternative 2 — Orthogonal ranker (non-coinvest signals; Spec 081)

**Overfitting risk: VERY HIGH.**

The process of identifying "orthogonal" signals involves searching for features that correlate with returns after controlling for coinvest — methodologically indistinguishable from running a feature search on residualized returns. The D8/D9 finding (clinical_quality conditional IC ≈ +0.20 within gated cohort) is PRELIMINARY at n=7 resolved observations. Any coefficient estimated on 7 events has near-zero reliability.

**Snooping risk: VERY HIGH.** The orthogonality constraint is constructed post-hoc by searching the feature space for what is left after coinvest. This is the same structural failure mode that closed EES v3.

**Data gate:** Not satisfied. Post-PIT n=12 HIT/MISS; need ≥30. Post-13F window not closed.

**EES v3 analogy:** EES v3 appeared to be a principled formulation. After residualization, IC collapsed to zero because the primary component was a monotonic transform of the market signal. Alternative 2 faces the same risk: the "orthogonal" signal may orthogonalize to coinvest while remaining dependent on some other confound (market returns, XBI regime, calendar effects).

**Overall risk level:** VERY HIGH. Do not test until data gates are satisfied and a specific investment-logic hypothesis (not a search result) is committed BEFORE looking at outcomes.

---

### Alternative 3 — Catalyst-timing ranker (catalyst_decay_w; Spec 080)

**Overfitting risk: MEDIUM-HIGH.**

`catalyst_decay_w = exp(-days_to_catalyst / decay_half_life)` has a free hyperparameter (`decay_half_life`). Spec 080 proposes testing 60d/90d/120d variants (A0–A3). Selecting the best-performing half-life on 12 HIT/MISS events adds one degree of freedom to a model with roughly 1.5 effective degrees of freedom — deeply underpowered. Any half-life selection in-sample will be noise.

**Snooping risk: HIGH.** Four variants (A0–A3) plus the half-life tuning grid amount to ~12 specifications. Under BH FDR with n=12 events and α=0.05, the expected false positive rate is non-negligible. Effective power for detecting true IC at this sample is below 20% — most positive results will be false positives.

**False-catalyst contamination: HIGH.** `catalyst_decay_w` is computed from CT.gov dates. ~18.8% of CT.gov-derived catalysts are false. A timing ranker trained on false-catalyst rows will learn: "names with imminent CT.gov dates rank higher" — a data-artifact, not an alpha signal. Spec 071 Lane 2 must ship before this is mitigable.

**Double-counting risk: MEDIUM.** Selector already applies `catalyst_decay_w` via selector_catalyst_block. Phase A catalyst verdict found top-30% representation FLAT across proximity buckets — suggesting the selector has already absorbed the proximity sweet spot.

**Data gate:** Blocked. n=12 post-PIT HIT/MISS vs ≥30 required. Spec 071 Lane 2 not implemented. Post-13F window not closed.

**Overall risk level: HIGH.** Do not test before ~2026-07-15.

---

### Alternative 4 — Catalyst-quality ranker (catalyst_score; Spec 080 A2)

**Overfitting risk: MEDIUM-HIGH.**

`catalyst_score` conditional ρ = +0.19 within top-coinvest tertile, 17/17 snapshots positive. Descriptively encouraging but: the Spearman SE at n≈297 tickers per snapshot is ~0.058; 17 overlapping snapshots give ~3-4 effective independent cohorts. The 17/17 positive hit rate is stable but the effect-size estimate is noisy.

**Snooping risk: HIGH.** The Phase A audit warned: "hard to disentangle from selector_catalyst_block which already encodes most of it." If catalyst_score's ρ = +0.19 is largely explained by the selector already filtering on catalyst quality, residual within the ranker cohort could be near zero. Requires explicit residualization against selector_score — not available in current evidence.

**False-catalyst contamination: HIGH.** Same as Alternative 3. CORPORATE_UPDATE 0/6 HIT rate finding (n=8) is directionally correct but below conclusion threshold.

**Data gate:** Blocked (same as Alternative 3). n=12 post-PIT HIT/MISS vs ≥30 required.

**Overall risk level: HIGH.** Despite having the most consistent descriptive correlation among shadow candidates, double-count and false-catalyst risks mean this cannot be reliably tested at current sample sizes.

---

### Alternative 5 — Financial-stress/upside ranker (financial_score primary or refined)

**Overfitting risk: MEDIUM.**

The -0.0533 coefficient was fit jointly with coinvest — it may represent genuine financial-stress predictiveness or may be a regularization artifact of the Bradley-Terry fitting with a strongly dominant first feature. The feature itself is not the signal that separates cohort members most sharply (coinvest dominates), so it is less individually overfit-vulnerable.

**Correctness risk: CRITICAL.**

This is the highest-severity finding in the entire T4 analysis. The Spec 074 causal hypothesis is the best-supported interpretation of the -0.0533 weight — but explicitly not confirmed design intent. If the sign is wrong (i.e., if high `financial_score` = financially healthy, and the -0.0533 weight penalizes precisely the most durable names), then the deployed model is systematically underweighting the most resilient names within the coinvest cohort.

**Risk magnitude:** financial_score weight runs at FULL trained strength (-0.0533), unlike coinvest which is capped. In a biotech universe where runway < 1 year represents existential risk, penalizing financially strongest names is a direct tail-risk amplifier.

**Regime risk: HIGH.** Module 5's rank-norm is computed within stage×size cohort. If cohort composition changes (manager registry changes, 13F refresh), rank-norm boundaries shift. A name that was P80 of its cohort before the 13F refresh may fall to P60 after — the -0.0533 weight applied to P60 is a different absolute effect from P80. The coefficient does not know this.

**Priority action for T8:** Verify `financial_score` directionality using Module 5 `docs/MODEL_DOCUMENTATION.md` and rank-norm construction path. If sign is wrong, this is an immediate production correctness issue — not a research question — requiring operator sign-off before any other ranker work proceeds.

**Overall risk level: CRITICAL (correctness question → route to T8). MEDIUM (overfitting). LOW (snooping).**

---

### Alternative 6 — Event-EV ranker (event_ev_p_hit × expected_return; Spec 077/079)

**Overfitting risk: LOW now** (cannot overfit with 0 observations; risk deferred to calibration phase).

**Data availability: BLOCKED.** T3 confirms 0 non-null event_ev_p_hit records. Spec 077 binder wired but ~70% join failure rate (EV `expected_date` vs CRT `catalyst_date` divergence of 36-62+ days). Calibration clock has not started.

**When unblocked — future overfitting risks:** At n=30 (earliest evaluable), fitting a pairwise logistic with `event_ev_p_hit` leaves ~10 independent effective observations after within-cohort dependence. Heavily underpowered. Expected false positive rate for any IC-positive finding at n=30 is high.

**Calibration bias risk: MEDIUM-HIGH.** Event_ev Bayesian priors are derived from FDA historical precedent and endpoint type, fit before the post-PIT-fix period. If those priors are miscalibrated (e.g., FDA approval rates shifted with accelerated-approval scrutiny), `event_ev_p_hit` values may be systematically biased. Spec 079 calibration review is the correct gate — but requires n≥30 resolved records before it can run.

**Binder selection bias:** The 30% of records that successfully join the binder may be systematically different from the 70% that do not (e.g., only events with exact date matches, biased toward near-term catalysts or specific catalyst families). If so, the calibration sample will not be representative of the general event universe.

**Overall risk level: BLOCKED (0/30 records). Future risk: MEDIUM-HIGH (underpowered at first evaluable sample; calibration bias possible).**

---

### Alternative 7 — Expectation-gap ranker (EES v3 / Polymarket; closed lane)

**Structural risk: CLOSED AND DOCUMENTED.**

Three independent residualization tests on the full n=1,856 clean forward-return panel all returned IC ≈ 0 for every EES v3 formulation variant. Root cause: `conditional_misprice_score` Spearman -0.978 with `priced_move_pct` — it is a monotonic transform of implied move, not an independent signal. EES v2's bin-residualized IC = -0.039 (t=-1.69) — anti-predictive after pmv control. General principle: **you cannot extract expectation error from expectation alone.**

**Snooping risk if EES is revisited: CRITICAL.** Any attempt to "re-residualize" or "reweight components" would constitute running another search iteration on an already-exhausted family. The three-test convergence is the last word on this formulation class. New external inputs (IV-vs-realized history, cross-sectional dispersion, microstructure flow) would constitute a genuinely new formulation.

**Polymarket:** Below 25-event minimum for shadow research. AXSM is the one usable data point (HIT, +12%). No alpha signal can be derived from a single event.

**Overall risk level: CLOSED.** Reopening any variant of this alternative absent external (non-pmv) inputs constitutes a governance violation of the standing EES v3 closure decision.

---

### Alternative 8 — Risk-adjusted ranker (short_interest, vol, runway; defensive overlay)

**Overfitting risk: VERY HIGH if used as alpha signal.**

Risk-control features are the easiest to overfit. A feature like `runway_severity_score` that separates distressed names from solvent names will correlate with ex-post returns in any period containing biotech distress events — but this is not alpha, it is avoidance of known catastrophic losses.

**Double-gate risk:** `severity` and `runway_bucket` are already in the eligibility gate. All ranker-cohort members have already been filtered on severity. The residual gradient within the passed cohort may be much smaller than the raw signal across the universe. Adding them to the ranker may add negligible discrimination within the filtered cohort while appearing effective in full-universe testing.

**Policy status:** Per `feedback_runway_severity_architecture.md`, severity and runway are cross-layer control variables, not alpha sources. Promoting to ranker features would violate this standing architectural decision.

**Short_interest PIT risk:** T3 marks short_interest_pct PIT validity as UNCERTAIN — reported with delay, snapshot may not reflect actual position at observation date.

**Overall risk level: VERY HIGH (if used as alpha; policy-blocked). LOW (if kept as eligibility gate).**

---

### Alternative 9 — Hybrid two-stage ranker (timing × financial stress interaction)

**Overfitting risk: CRITICAL.**

Interaction terms are exponentially more vulnerable to overfitting than main effects. With n≈30 post-PIT resolved outcomes (earliest gate), a timing × financial_score interaction has 1 effective degree of freedom for approximately 10 observations — a ratio that makes any estimated coefficient unreliable.

**EES v3 analogy: DIRECT.** EES v3 was an interaction-style formulation combining two components (0.70/0.30 weights) that collapsed to a monotonic transform of its dominant input. Alternative 9 faces the identical risk: the timing × financial interaction will be dominated by whichever component has higher within-cohort variance, and the interaction may reduce to a scaled version of that component alone.

**Snooping risk: CRITICAL.** The "discovery" of an interaction inherently requires having tested both components first. Under any multiple-testing framework, three related tests (Alt 3, Alt 5, Alt 9) share family-wise error — the effective correction required makes Alt 9 effectively untestable at current sample sizes.

**Dependencies not met:** Alternative 3 (timing) requires n≥30 + false-catalyst hygiene + post-13F. Alternative 5 (financial_score) requires sign-direction verification. Alternative 9 cannot begin until BOTH are individually validated — not merely tested.

**Overall risk level: CRITICAL.** Do not test before 2026-Q4.

---

### Alternative 10 — No-ranker comparator (selector-only; null hypothesis)

**Overfitting risk: N/A (descriptive, not modeled).**

**Evidence status:** Rescued-vs-suppressed differential at n=8 = +0.10pp (≈ 0). SE ≈ 0.5pp. Indistinguishable from zero AND from a meaningful positive differential. Re-run at 2026-05-22 (≥30 resolved snapshots) is the correct gate.

**Regime contamination risk: MEDIUM.** The n=8 test period overlaps with the XBI selloff (April 21-25) and cohort change (2026-04-25). If the ranker's deviations from coinvest were value-adding in a different regime but harmful in the selloff, the n=8 null result may be regime-specific rather than structural.

**Decision risk: MEDIUM.** If the null test at 2026-05-22 shows differential ≈ 0, the correct decision is not automatic ranker removal — it is human review. The ranker may provide portfolio stability (reduced turnover relative to a pure coinvest sort) even without point-in-time IC. Stabilization value is not captured by rescued-vs-suppressed differential.

**Overall risk level: LOW (as descriptive null hypothesis test). MEDIUM (if used to drive a production removal decision without governance review).**

---

## Section 3 — Cross-cutting risk themes

### 3.1 Small-sample overconfidence

At n=17 post-PIT snapshots and n=12 HIT/MISS, the SE on Spearman IC per snapshot is ≥0.058 (1/√297). Over 17 overlapping 5-day windows, the effective independent-snapshot count is approximately 4-5. The SE on pooled IC is therefore ~0.025-0.030. Any single-alternative IC estimate below 0.08 in absolute value is inside the 3-sigma noise band. **No IC-positive finding for any new alternative is reliable at n=17 snapshots.**

### 3.2 Multiple testing exposure: the 10-alternative search

Under FDR control with α=0.05 and 10 tests, the expected number of false positives is 0.5 per family — which means any IC-positive finding in this family has roughly a 50% probability of being a false positive even before accounting for within-sample dependence. Checklist v2 requirements (NW-corrected t ≥ 2.0, bootstrap CI excludes 0, BH FDR-corrected p < 0.05, LOSO robustness, year stability) are the correct mitigation — but cannot be run until n≥50 post-PIT snapshots (~2026-07-31).

### 3.3 The regime-conflation problem

The post-PIT period (2026-04-17 to 2026-05-08) spans an XBI selloff, a manager registry expansion, and the onset of a 13F quarantine — no 17-day window containing all of these events can reliably separate signal quality from regime noise.

**Clean evidence window:**
- After 13F refresh quarantine clears: ~2026-05-20
- After h20d verdict checkpoint: 2026-05-26
- After n≥30 HIT/MISS accumulates: ~2026-07-15

Until those gates pass, all IC estimates carry a regime-conflation caveat.

### 3.4 EES v3 as canonical overfitting postmortem

A formulation that appeared IC-positive (+0.089, t=2.07) before PIT correction and residualization collapsed to IC ≈ 0 after. The mechanism: a multi-component formula's dominant term was a monotonic transform of the market's own implied signal. This applies directly to Alternatives 2, 7, and 9. Before testing any compound or interaction formulation, component signals must be individually validated with rigorous residualization to their most correlated market variable.

### 3.5 Financial_score correctness: priority escalation

The single finding with the highest immediate operational consequence is the unresolved direction question for `financial_score`. This is the only risk that:
1. Is currently active in production
2. Has a plausible wrong-direction scenario with direct portfolio harm
3. Can be resolved by reading a documentation file — not by running tests

This should be the first item addressed before T5, T6, or T7 proceed.

---

## Section 4 — Risk severity ranking

| Priority | Alternative / Risk | Severity | Action | Gate |
|---|---|---|---|---|
| 1 | financial_score sign direction (production correctness) | CRITICAL | Verify Module 5 rank-norm directionality vs Spec 074 hypothesis | T8 human gate |
| 2 | Alternative 7 (EES v3) reopening | CRITICAL | Closed. Do not reopen without non-pmv external inputs | Standing policy |
| 3 | Alternative 9 (hybrid two-stage interaction) | CRITICAL | Blocked. Components must individually validate first | ~2026-Q4 |
| 4 | Alternative 2 (orthogonal ranker post-hoc search) | VERY HIGH | Commit investment-logic hypothesis BEFORE data search | After 13F + n≥30 |
| 5 | Alternative 8 (risk-adjusted) used as alpha signal | VERY HIGH | Policy-blocked. Eligibility gate is the correct home | Standing policy |
| 6 | Coinvest double-counting ρ=+0.882 | HIGH | Ongoing monitoring. Measure IC within cohort, not universe | 2026-05-26 h20d |
| 7 | Forward IC near zero (pooled -0.031) | HIGH | OBSERVE. No action until h20d + 13F both clear | 2026-05-26 |
| 8 | Alternative 3 (catalyst timing) false-catalyst contamination | HIGH | Blocked. Spec 071 Lane 2 required before testing | ~2026-07-15 |
| 9 | Alternative 4 (catalyst quality) selector double-count | HIGH | Blocked. Residualize vs selector_score before testing | ~2026-07-15 |
| 10 | Training on pre-PIT contaminated data | MEDIUM-HIGH | Cap partially mitigates. Full retrain deferred | Post n≥50 snapshots |
| 11 | Alternative 6 (event-EV) calibration risk at first evaluable n | MEDIUM-HIGH | Spec 079 calibration protocol is the correct gate | ~2026-07-01 |
| 12 | Missing ranker_active_contract.py enforcement | MEDIUM | Document manually; add to governance checklist | Next governance session |
| 13 | Small-sample overconfidence (n=17 snapshots, n=12 HIT/MISS) | MEDIUM | All results labeled PRELIMINARY; Checklist v2 required | Ongoing |
| 14 | Alternative 10 (null) removal without governance review | MEDIUM | Any removal decision requires operator sign-off | 2026-05-22 re-run |
| 15 | Regime conflation in IC estimates | MEDIUM | Wait for regime-stable window (≥2026-05-20) | 13F refresh |

---

## Section 5 — Handoff to T5, T6, T7, T8

### For T5 (ablation protocol):
1. Alternative 10 (no-ranker comparator) is the only alternative testable today in descriptive mode. Mandatory baseline in every ablation run.
2. Spec 080 (timing; A0–A3) and Spec 081 (orthogonality; B0–B5) share pre-conditions and should be run in a single evidence session.
3. The ablation evaluation protocol must measure IC within the selector-passed cohort (top-60), not across the full universe. Current IC decomposition tool operates on full universe — must be restricted for ranker-relevant IC.
4. Alternatives 3 and 4 cannot enter the ablation battery until Spec 071 Lane 2 is implemented.
5. Alternative 6 cannot enter the ablation battery until ≥30 non-null event_ev_p_hit records are available (~2026-07-01).

### For T6 (alpha potential synthesis):
1. Strongest investment-logic alternatives (pre-data): Alternative 6 (event-EV; logic VERY HIGH, BLOCKED on data) and Alternative 3 (catalyst timing; logic HIGH, BLOCKED on data).
2. Strongest current empirical correlation: Alternative 4 (catalyst_score ρ=+0.19, 17/17 positive) — cannot be interpreted as alpha evidence until selector double-count controls are applied.
3. Alternative 1 (baseline): logic coherent, forward evidence INCONCLUSIVE (n=8).
4. T6 should not assert alpha potential above SHADOW_CANDIDATE for any alternative until post-July 2026 evidence gates clear.

### For T7 (memo writer):
1. Financial_score correctness must be resolved before T7 can accurately characterize the current model's design intent.
2. EES v3 precedent should be featured prominently as the quantitative risk anchor.
3. Alternative 10 (null hypothesis) should be presented as an active research question — the evidence is genuinely ambiguous.
4. The regime-conflation caveat must appear on every IC estimate cited from the April 2026 window.

### For T8 (human gate) — three items requiring immediate human attention:

**URGENT — financial_score sign direction:** Confirm the Module 5 rank-norm directional interpretation (high score = financially safe names; low score = financially stressed names). If high score = safe and the ranker coefficient is -0.0533, the model is penalizing safety — verify this is intended design and not an error. This is a production correctness question, not a research question.

**Architecture frozen scope:** Confirm that all alternatives except the baseline (Alternative 1) remain blocked from code implementation pending evidence gates specified in this memo.

**EES v3 permanent closure confirmation:** Confirm that the current EES v3 closure is standing policy for ALL pmv-derived expectation-error formulations, and that any future expectation-gap research must begin with a genuinely external input before any IC testing.

---

## Appendix A — Evidence source table

| Claim | Source |
|---|---|
| train_accuracy = 1.0 | `production_data/ranker_v2_model.json` via T1 |
| ρ(coinvest_score_z, final_score) = +0.882 | `RANKER_HYGIENE_NOTE_2026_05_01.md` via T1 |
| coinvest = 92.7% of selector variance | `scoring_model_identity_2026_04_06.md` |
| Coinvest cap: +0.02 deployed vs +0.0613 trained | `ranker_v2_model.json` via T1 |
| financial_score weight: -0.0533 (not capped) | `ranker_v2_model.json` via T1, Spec 074 |
| financial_score directionality: [UNCERTAIN] | Spec 074 §2, T1 ambiguity list #2 |
| common/ranker_active_contract.py missing | T1 URGENT FINDING |
| 17 post-PIT clean snapshots | T3 detail §1 |
| 12 post-PIT HIT/MISS (7 HIT, 5 MISS) | T3 detail §2 |
| 0 bound event_ev_p_hit records | T3 detail §3 |
| Pooled IC = -0.031 (t=-1.99) | IC decomposition readout 2026-05-08 |
| Post-cohort mean IC = -0.008 | IC decomposition readout 2026-05-08 |
| Rescued-vs-suppressed differential = +0.10pp | `forward_return_test_prod_vs_coinvest_2026_05_01.md` |
| EES v3 IC ≈ 0 after pmv control | `ees_v3_structural_failure_2026_04_30.md` |
| catalyst_score ρ=+0.19 (17/17 positive) | `catalyst_phase_a_verdict_2026_05_04.md` |
| 18.8% false-catalyst rate at universe | T3, Spec 078, catalyst Phase A verdict |
| Spec 071 Lane 2 not implemented | T3 detail §5 |
| inst_delta_z weight = 0.00 since 2026-05-04 | Scoring model identity update |
| 13F quarantine through ~2026-05-15 | T3 detail §4 |
| Spec 077 binder: 0 non-null values, 70% join failure | T3 detail §3 |
| Policy: pairwise ordinal only, no rank-weighting | `policy_alpha_freeze_2026_04_04.md` |
| Architecture frozen since 2026-04-19 | `policy_freeze_architecture_2026_04_19.md` |
| Demotion path: 5-element governed | `policy_demotion_path_2026_05_06.md` |

---

*End of T4 memo. No code changes. No production writes. All findings are read-only analyses for handoff to T5, T6, T7, and T8.*
