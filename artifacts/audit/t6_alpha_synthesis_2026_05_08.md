# T6 — Alpha Potential Synthesis (2026-05-08)

**Analyst:** T6 [analyst]
**Date:** 2026-05-08
**Status:** RESEARCH ONLY — no promotions, no code changes, no production changes
**Inputs:** T1 ranker anatomy, T2 ranker alternatives, T3 data readiness, T4 risk analysis, T5 ablation protocol; production ranker contract; alpha-freeze policy; EES v3 closure memo; Phase A verdicts (clinical, catalyst)
**Regime caveat:** All IC estimates referencing April 2026 snapshots carry [REGIME_CAVEAT]: XBI selloff 04-21→04-25, cohort change 04-25, 13F quarantine onset 04-25. Treat IC estimates from this window as directional signals only, not calibrated statistics.

---

## Executive Summary

The production ranker is a 2-feature pairwise Bradley-Terry model (`coinvest_score_z` +0.02 cap, `financial_score` -0.0533) applied within the A4 selector's top-60. It is functionally redundant with the selector: ρ(coinvest_score_z, final_score) = +0.882. The ranker's marginal contribution to rank ordering is dominated by a single unresolved question — whether the `financial_score` negative coefficient encodes a deliberate "stress-upside" thesis or an inverted signal. That question must be resolved before any ablation or alternative testing is valid.

Of the 10 alternatives evaluated, **one is permanently closed (Alt 7)**, **one is structurally premature (Alt 9)**, **one requires immediate human review (Alt 5)**, and **the most immediately actionable test is the no-ranker comparator (Alt 10)**. The remaining alternatives are either blocked by specific named dependencies or in shadow-only status. No alternative clears the threshold for a formal IC test under current data conditions (n=12 HIT/MISS, 17 snapshots, 13F quarantine, no Spec 077 join).

**Single highest-priority action:** Alt 10 (no-ranker comparator) can be computed from `forward_returns_panel.csv` today using divergent snapshots between selector_score top-30 and production final_score top-30. This is the null-hypothesis test that frames all other alternatives.

**Earliest formal test date for any alternative:** Alt 10 descriptive IC test is computable now. All other alternatives: Gate 4 (n≥30 HIT/MISS) ~2026-07-15 at minimum; Alt 6 (Event-EV) blocked until Spec 077 join failure resolved (no current estimate).

---

## Category Assignments Table

| Alt | Name | Category | Primary Blocker |
|-----|------|----------|-----------------|
| 1 | Momentum / mean-reversion | LOW_POTENTIAL | Double-count in selector; no fundamental anchor in event-driven biotech |
| 2 | inst_delta_z alone | MEDIUM_POTENTIAL_SHADOW | Demoted to 0.00 weight; quarantined through ~2026-05-20; no post-PIT evidence |
| 3 | Catalyst timing ranker | HIGH_POTENTIAL_BUT_BLOCKED | Spec 071 Lane 2 (false-catalyst classifier) not implemented; est. ~2026-Q3 |
| 4 | Catalyst quality ranker | HIGH_POTENTIAL_BUT_BLOCKED | Same Lane 2 blocker; mild double-count; REGIME_CAVEAT on conditional IC +0.20 |
| 5 | Revised financial_score weighting | NEEDS_HUMAN_REVIEW | Sign direction unresolved; Gate 1 (Spec 074 / code audit) required first |
| 6 | Event-EV integration | HIGH_POTENTIAL_BUT_BLOCKED | Spec 077: 70% join failure; 0 non-null bound records; calibration clock at zero |
| 7 | EES v3 (conditional_misprice_score) | NO_GO | Spearman -0.978 with pmv; monotonic transform; IC ~0 after pmv control. PERMANENT |
| 8 | Clinical design quality | NO_GO | Closed lane policy (selector NO_GO, Phase A verdict 2026-05-04); all clinical ranker use prohibited |
| 9 | Hybrid composite ranker | NO_GO | Fatally underpowered (n=12); replicates EES v3 construction path; cannot evaluate until individual signals clear Checklist v2 (>=2027) |
| 10 | No-ranker comparator | MEDIUM_POTENTIAL_SHADOW | No blockers; most immediately testable; null-hypothesis reference for all other alts |

---

## Per-Alternative Assessment

---

### Alt 1 — Momentum / Mean-Reversion
**Features:** `de_drawdown`, `de_vol_60d`, `de_rsi_14d`, `de_beta_xbi_60d`
**Category:** LOW_POTENTIAL

**Thesis coherence:** WEAK. Momentum and mean-reversion are plausible in liquid equities with persistent earnings flows. Biotech returns are event-driven: a Phase 3 read, PDUFA decision, or clinical hold dominates any 60-day price trend. Relative price momentum within a cohort of early-stage names has no clear mechanism for predicting which name resolves its binary catalyst first, or favorably.

**Alpha mechanism:** None distinct from selector. All four features are already consumed in the A4 selector's market structure block (10% weight). Using them again in the ranker is double-counting — the selector already ranks candidates partly on these dimensions, and then the ranker would re-rank on the same information.

**Independence from selector:** VERY LOW. Market structure block overlaps 100%. Effective orthogonality is near-zero.

**Data readiness:** Features exist in production snapshots. Data is available but purpose-contaminated by selector inclusion.

**PIT safety:** ACCEPTABLE for de_drawdown, de_vol_60d, de_rsi_14d. de_beta_xbi_60d requires confirming rolling-window construction does not use forward-looking reference prices.

**Robustness risk:** HIGH. RSI and beta are regime-sensitive. The April 2026 XBI selloff would invert any momentum signal derived from pre-selloff windows. Jaccard = 0.42 vs production (T2 memo) — diverges substantially, but divergence driven by selector-already-uses-these features.

**Implementation risk:** LOW mechanically. HIGH epistemically (no mechanism to justify).

**Calibration readiness:** POOR. At 3-4 HIT/MISS per month, momentum signals with 60-day lookbacks cannot be tested in any statistically meaningful way before mid-2027.

**Production risk:** LOW if capped, but the signal would embed regime-dependent noise into rank ordering, potentially moving low-coinvest momentum names above high-coinvest fundamental names.

**Explainability:** POOR. Cannot articulate why 60-day RSI should predict event-driven biotech returns to a reasonable external reviewer.

**Time to valid test:** Not before Gate 4 (~2026-07-15) AND post-13F quarantine. Even then, the double-count problem makes test interpretation ambiguous.

**Conclusion:** Do not track. The investment thesis is weak for event-driven biotech, the data is already consumed by the selector, and there is no meaningful path to independent validation.

---

### Alt 2 — inst_delta_z Alone as Ranker
**Category:** MEDIUM_POTENTIAL_SHADOW

**Thesis coherence:** MODERATE. "Smart money accumulating ahead of catalyst" is a coherent biotech-specific thesis. Institutional flows can provide information before public catalysts. The mechanism is plausible but requires strict PIT discipline (13F filings have 45-day lag; using Q1 2026 13F filed in May 2026 for April 2026 trades would be look-ahead).

**Alpha mechanism:** Distinct from coinvest in theory: coinvest is a static ownership count (how many managers hold), while inst_delta_z measures directional change (net adds vs. trims). These are different information streams. The 2-feature complement thesis (inst_delta_z + coinvest_score_z = B6 family, Delta=+1.85pp, t=3.56) was the best pre-PIT evidence.

**Independence from selector:** PARTIAL. inst_delta_z was demoted to 0.00 in the selector (2026-05-04 governance log). At zero weight, it has zero overlap with current selector. However, this demotion was itself a data-quality response (cohort expansion distortion), not a thesis rejection — important distinction.

**Data readiness:** BLOCKED. Quarantined through ~2026-05-20 due to 4-manager cohort expansion 2026-04-25. `institutional_summary_delta.json` is the producer artifact; the 13F Q1 2026 refresh (~2026-05-15) may extend quarantine if it changes cohort membership further.

**PIT safety:** HIGH RISK. 13F filing lag (45 days from quarter-end) means March 31, 2026 positions are not knowable until approximately May 15, 2026. Any inst_delta_z values computed from Q1 2026 13F data and applied to April 2026 rankings introduce look-ahead. Must verify that inst_delta_z construction uses only filings available as of the snapshot date, not the as-of-quarter date.

**Robustness risk:** HIGH during cohort-change windows. The distortion is documented (inst_delta_z byte-identical across 04-25/27/28 despite cohort expansion). This suggests the signal does not respond to cohort changes in real time, which is either a PIT feature or a staleness bug — must be audited before any test.

**Implementation risk:** LOW mechanically (feature already exists). HIGH epistemically (demotion governance + quarantine + PIT-lag risk).

**Calibration readiness:** MODERATE after quarantine clears. Once 13F refresh settles and new snapshots are clean, shadow tracking is appropriate. Do not attempt IC test before Gate 4.

**Production risk:** MODERATE. If PIT-lag is not enforced, this signal embeds future knowledge.

**Explainability:** GOOD. "Managers adding ahead of catalysts" is communicable.

**Time to valid test:** Post-13F quarantine (~2026-05-20), post-13F refresh integration, AND Gate 4 (~2026-07-15). Earliest shadow tracking: 2026-05-20. Earliest formal IC test: 2026-07-15.

**Conclusion:** Worth shadow-tracking after quarantine clears. Do not attempt any ablation or IC test until: (1) quarantine lifted, (2) 13F refresh integrated, (3) PIT-lag construction verified, (4) Gate 4 reached. The pre-PIT-v2 IC=+0.077 is invalidated; treat as zero evidence.

---

### Alt 3 — Catalyst Timing Ranker
**Features:** `catalyst_decay_w`, `cat_priority`, `catalyst_strength`
**Category:** HIGH_POTENTIAL_BUT_BLOCKED

**Thesis coherence:** STRONG. Events near-term and high-priority drive biotech price action. Time-decay weighting to the next binary catalyst is directly aligned with the economic mechanism: market prices become less uncertain as the event date approaches, and names with imminent high-priority catalysts carry more short-term convexity. This is arguably the most biotech-specific thesis of all 10 alternatives.

**Alpha mechanism:** DISTINCT. Temporal proximity to catalyst resolution is orthogonal to institutional ownership count. coinvest_score_z measures "who holds," catalyst timing measures "when the information event fires." The two mechanisms can complement: high-coinvest names with near-term pivotal catalysts are the most convex positions.

**Independence from selector:** MODERATE. `catalyst_decay_w` and `cat_priority` appear in the selector catalyst block (15% total weight). However, the selector uses these as a binary presence gate, not as a precise timing rank. A ranker built purely on catalyst timing would use finer-grained decay functions and could achieve meaningful orthogonality within the top-60.

**Data readiness:** PARTIAL. `catalyst_decay_w`, `cat_priority`, and `catalyst_strength` exist in snapshots. The blocker is not data availability — it is data quality: approximately 18.8% of universe-level catalyst records are estimated false catalysts (CT_PRIMARY_COMPLETION, CT_STUDY_COMPLETION sources from OLE/PK subtrials). Within the top-60, T3/T4 estimate ~21% false-catalyst contamination. Using timing signals on contaminated catalysts will rank names as "near-term event" when the event has no meaningful price impact.

**PIT safety:** ACCEPTABLE. Catalyst dates are recorded at time of snapshot. False-catalyst contamination is a quality issue, not a PIT issue.

**Robustness risk:** HIGH until Lane 2 is implemented. A timing signal built on 21% false-catalyst contamination will produce noise proportional to contamination rate. BCRX as a documented example: CT_PRIMARY_COMPLETION source coded as HIT on 2026-05-01 — this record must be excluded from any timing-signal validation.

**Implementation risk:** LOW after Lane 2 ships. HIGH before Lane 2 ships (cannot run clean test).

**Calibration readiness:** BLOCKED. Cannot accumulate clean HIT/MISS records for catalyst timing until false-catalyst filter is active.

**Production risk:** MODERATE. If deployed with contaminated catalysts, timing ranker would systematically elevate OLE/PK names near their completion dates — these have consistently low price impact.

**Explainability:** EXCELLENT. "We rank within the coinvest cohort by proximity to the next meaningful binary catalyst" is the clearest possible ranker rationale.

**Time to valid test:** Blocked by Spec 071 Lane 2. Lane 2 estimated ~2026-Q3. Earliest formal IC test: Gate 4 AND Lane 2 complete — likely 2026-Q4 at earliest.

**Blocker details:**
- Spec 071 Lane 2: false-catalyst OLE/PK-subtrial classifier. Not scoped into a specific commit window. Estimated completion: ~2026-Q3.
- No fallback: timing signal is not testable in contaminated form (bias too large).

**Conclusion:** Highest-conviction blocked alternative. Once Lane 2 ships and Gate 4 is reached, this should be the first formal catalyst-ranker IC test. Shadow-track catalyst_decay_w distribution today as a diagnostic (no scoring implication).

---

### Alt 4 — Catalyst Quality Ranker
**Features:** `binary_quality_score` (W_FAMILY=0.35, W_PHASE=0.30, W_SOURCE=0.20, W_DESIGN=0.15)
**Category:** HIGH_POTENTIAL_BUT_BLOCKED

**Thesis coherence:** STRONG. High-quality catalysts (pivotal Phase 3, well-designed, primary endpoint, non-OLE source) should be less efficiently priced than low-quality catalysts because the market under-differentiates within the "binary event" category. Sophisticated biotech readers know a Phase 3 OS read is not the same as an OLE safety update. If the market prices them similarly, quality creates alpha.

**Alpha mechanism:** DISTINCT from timing (Alt 3). Quality and timing are different dimensions — a near-term OLE completion (Alt 3: high score, Alt 4: low score) vs. a distant pivotal Phase 3 (Alt 3: low score, Alt 4: high score). The two complement each other.

**Independence from selector:** MODERATE. `binary_quality_score` components appear in the selector catalyst block. However, within the top-60, variability in quality scores may be narrower than in the full selector universe — a ranker using quality within top-60 could capture finer gradations not resolved by the selector.

**Data readiness:** PARTIAL. Same Lane 2 false-catalyst blocker applies: OLE/PK contamination distorts quality scores (these records should score LOW quality but may score HIGH on some components if source/design fields are filled). Until Lane 2 cleans the catalog, quality scores carry contamination-proportional noise.

**PIT safety:** ACCEPTABLE. Catalyst quality metadata is snapshot-time recorded.

**Robustness risk:** MODERATE after Lane 2. The conditional IC ~+0.20 within top coinvest from D9 vNext analysis is PRELIMINARY and carries [REGIME_CAVEAT] — computed in April 2026 XBI selloff window. NW-corrected t ~+3; n of snapshots and events underpowered. Do not treat this as promotion-grade evidence.

**Implementation risk:** LOW after Lane 2.

**Calibration readiness:** BLOCKED until Lane 2. After Lane 2: accumulation at 3-4/month → Gate 4 (~2026-07-15). First clean quality-stratified IC test possible 2026-Q4.

**Production risk:** LOW if capped. binary_quality_score is already produced; no new data pipeline required.

**Explainability:** EXCELLENT. "We prefer pivotal Phase 3 trials over OLE continuations within the coinvest cohort" is fully explainable.

**Time to valid test:** Same as Alt 3 — Spec 071 Lane 2 (~2026-Q3) AND Gate 4 (~2026-07-15).

**Blocker details:**
- Spec 071 Lane 2 (same as Alt 3): false-catalyst classifier. ~2026-Q3.
- D9 conditional IC must be retested post-cohort-window-close (~2026-05-15) and post-Lane-2 before any formal test.

**Conclusion:** Second-highest-conviction blocked alternative after Alt 3. The D9 evidence is encouraging but regime-caveat-laden and not cleanable until Lane 2 ships. When Lane 2 is available, Alt 3 and Alt 4 should be tested together as a joint catalyst timing x quality framework — they are complements, not substitutes.

---

### Alt 5 — Revised financial_score Weighting
**Category:** NEEDS_HUMAN_REVIEW

**Thesis coherence:** CANNOT ASSESS. Two competing theses: (a) negative coefficient is intentional "stress-upside" — penalizing financially healthy names in favor of stressed names with large upside asymmetry; (b) negative coefficient is an inversion artifact from training on a small, regime-specific sample. Both are logically consistent. The memo cannot adjudicate between them without knowing the original model construction intent.

**Alpha mechanism:** POTENTIALLY DISTINCT. If the stress-upside thesis is correct, financial stress within the top-60 coinvest cohort predicts better risk-adjusted returns. This would be distinct from coinvest (which does not weight financials) and from clinical (closed lane). However, if inverted, this mechanism is actively degrading ranker performance.

**Independence from selector:** HIGH. `financial_score` (Module 5 rank-norm) is not present in the A4 selector at any weight. This is the most selector-orthogonal feature currently in the ranker.

**Data readiness:** FULL. financial_score is populated across all snapshots. Double-normalization (rank-norm within stage x size cohort, then z-scored within top-60) is a potential distortion but does not affect data availability.

**PIT safety:** ACCEPTABLE if Module 5 uses only PIT-anchored financial fields. Must verify that balance sheet / runway fields are as-of-snapshot-date, not most-recent-available.

**Robustness risk:** UNKNOWN until sign direction resolved. If inverted, the current coefficient is adding regime-correlated noise. If correct, the coefficient may be too small to detect with n=12 HIT/MISS.

**Implementation risk:** LOW mechanically (retrain or coefficient flip). HIGH epistemically — changing a production coefficient without understanding the sign question is a production correctness change, not a research change.

**Calibration readiness:** Cannot estimate until Gate 1 (sign direction) is resolved.

**Production risk:** HIGH. If the current coefficient is inverted, it is actively ranking stressed names above quality names within the top-60 in a direction opposite to the selector's intent. Resolution is a production correctness priority, not a research priority.

**Explainability:** POOR currently. "The ranker penalizes financially healthy companies" requires a clear written rationale to defend.

**Time to valid test:** Gate 1 (Spec 074 or code audit) must complete first. No estimate available for Spec 074 timeline — escalated to T8.

**Gate 1 definition:** A written determination, signed by the operator, specifying: (a) whether the negative coefficient encodes the stress-upside thesis or is an artifact; (b) whether the double-normalization is intentional; (c) whether Spec 074 findings change the coefficient sign. Until Gate 1 is documented, Alt 5 is frozen.

**Conclusion:** NEEDS_HUMAN_REVIEW. This is not a research question — it is a production correctness question. Escalated to T8. Do not run any ablation on financial_score until Gate 1 resolves.

---

### Alt 6 — Event-EV Integration
**Features:** `event_ev_p_hit` (Bayesian P(HIT) x magnitude, 6-layer framework)
**Category:** HIGH_POTENTIAL_BUT_BLOCKED

**Thesis coherence:** STRONGEST of all alternatives. If the 6-layer Bayesian EV framework correctly prices the expected value of catalyst resolution, then ranking within the top-60 by EV-weighted probability captures both magnitude and likelihood simultaneously. Names with positive expected value and high certainty represent the most efficiently priced conviction; names with positive EV and high uncertainty represent the most convex positions. This is the correct theoretical mechanism for biotech position sizing.

**Alpha mechanism:** MAXIMALLY DISTINCT. event_ev_p_hit is not present in A4 selector. It incorporates historical base rates, trial design quality, drug class priors, phase-conditional adjustment, and news sentiment — none of which enter coinvest_score_z directly.

**Independence from selector:** VERY HIGH. EV integration is conceptually orthogonal to ownership concentration. The selector answers "who believes in this?" and EV answers "what is it actually worth?"

**Data readiness:** BLOCKED — CRITICAL. Current state:
- `event_ev_p_hit` field exists in ResolutionRecord schema (Spec 077)
- Join failure rate: 70% (EV expected_date vs CRT catalyst_date divergence of 36-62+ days)
- Non-null bound records in production: 0
- Calibration clock: not started
- n(HIT/MISS with bound EV): 0

Until the Spec 077 join failure is resolved, this alternative has zero data. The join failure is the single most important infrastructure issue for the entire ranker roadmap.

**PIT safety:** HIGH RISK if external EV priors (PubMed citations, HINT benchmark) are not frozen at snapshot time. Must confirm that the 6-layer prior construction uses only information available as of the snapshot date. PubMed 24h cache may introduce partial look-ahead on recent publications.

**Robustness risk:** HIGH conceptually (Bayesian priors are calibration-sensitive), but cannot assess empirically until join is fixed.

**Implementation risk:** HIGH. Spec 077 join logic requires architectural changes to the CRT-EV linkage. The divergence between expected_date (EV node) and catalyst_date (CRT node) is a structural mismatch, not a simple field mapping fix.

**Calibration readiness:** ZERO. Cannot accumulate evidence until join is fixed. Even after fix: forward-only, no backfill safe (T3 memo: 30% historical join rate makes backfill unreliable). Calibration clock starts only after first clean bound HIT/MISS records appear.

**Production risk:** LOW currently (the field is not in the ranker). HIGH if deployed before calibration.

**Explainability:** EXCELLENT once operational. "We rank by expected value of catalyst resolution" is the most analytically defensible ranker rationale.

**Time to valid test:** Spec 077 join fix (no timeline; escalated to T8) → first clean bound records → Gate 4 equivalent for bound subset (n≥30 bound HIT/MISS) → formal IC test. Minimum total: 2026-Q4 if Spec 077 is resolved in June 2026; more likely 2027.

**Blocker details:**
- Spec 077 join failure: EV expected_date vs CRT catalyst_date divergence 36-62+ days. Fix requires either: (a) fuzzy date matching with +/-N-day window and disambiguation logic, or (b) shared node_id assignment at CRT entry time. Option (b) is architecturally cleaner. No timeline estimate available.
- No backfill: 30% historical join rate makes backfill unreliable; forward-only accumulation.
- PIT audit of prior construction: must confirm 6-layer prior frozen at snapshot time.

**Conclusion:** Strongest conceptual mechanism of all alternatives. Infrastructure fix is the critical path. Escalate Spec 077 join resolution to T8 as the highest-priority infrastructure ask.

---

### Alt 7 — EES v3 (conditional_misprice_score)
**Category:** NO_GO — PERMANENT

This lane is closed. No further assessment is required.

`conditional_misprice_score` has Spearman correlation -0.978 with `priced_move_pct`. It is a monotonic transform of pmv. IC after pmv control ~0. The structural constraint "cannot extract expectation error from expectation alone" is a logical impossibility, not a data limitation. Future revisits require external (non-pmv) inputs: IV-vs-realized history, cross-sectional dispersion, microstructure flow.

Any future proposal to reopen this lane must be accompanied by a non-pmv information source. Without that, the proposal is precluded by the structural argument.

---

### Alt 8 — Clinical Design Quality
**Features:** `clinical_design_quality`, `clinical_50`
**Category:** NO_GO

Closed-lane policy applies. The Phase A verdict (2026-05-04) is Selector NO_GO. All clinical lanes as selector or ranker inputs are closed per alpha-freeze policy. `clinical_design_quality` is permitted in SHADOW ONLY for attribution analysis — not for ranker construction.

Evidence for closure:
- `clinical_score_v2_z` REJECTED in selector: Delta=-0.68pp
- Phase A verdict (2026-05-04): Selector NO_GO; Ranker SHADOW only
- EV non-evaluable until outcome-binder wired (same Spec 077 dependency as Alt 6)
- Verdict review: 2026-05-22

The 2026-05-22 review may re-evaluate the shadow-only status. If the verdict changes, this category assignment should be updated. Until then: NO_GO for any ranker construction use.

Distinction from Alt 6: clinical_design_quality could theoretically be an input to the EV prior (prior on P(HIT) conditioned on design quality) — that is a different use than a direct ranker feature. If Spec 077 resolves and EV calibration begins, clinical design quality's role should be evaluated within the EV prior framework, not as a standalone ranker signal.

---

### Alt 9 — Hybrid Composite Ranker
**Category:** NO_GO

This alternative cannot be meaningfully evaluated under current data conditions, and its construction method replicates the EES v3 failure path.

The problem is not just underpowerment. It is structural: compositing N underpowered signals into a weighted ensemble introduces N x M interaction terms that cannot be disambiguated from noise at n=12 HIT/MISS. The composite will overfit to whatever regime-specific patterns happened to be present in 17 snapshots. When the regime changes (post-13F refresh, post-XBI selloff), the composite will systematically fail. This is precisely how `conditional_misprice_score` was constructed — combining signals that were individually predictive but jointly entangled with pmv.

Minimum conditions for evaluating a composite ranker:
1. Each component signal has cleared Checklist v2 independently (earliest: 2027-04-17 per year-stability requirement)
2. Component IC estimates are non-overlapping in information content (demonstrated independence)
3. Ensemble construction method is pre-specified, not data-mined

None of these conditions are met. Do not revisit until all individual alternatives that survive evaluation have cleared Checklist v2.

---

### Alt 10 — No-Ranker Comparator (selector_score top-30)
**Category:** MEDIUM_POTENTIAL_SHADOW

**Thesis coherence:** This is the null hypothesis, not an investment thesis. The question is whether the current ranker adds positive marginal value over the selector alone. Given ρ(coinvest_score_z, final_score) = +0.882 and train_accuracy = 1.0 (overfitting flag), the ranker may be adding primarily noise. If selector_score top-30 performs equivalently to or better than final_score top-30, the case for ranker complexity is weakened.

**Alpha mechanism:** Not applicable — this is the comparator, not a mechanism.

**Independence from selector:** BY DEFINITION 100%. This removes the ranker entirely.

**Data readiness:** FULL. `forward_returns_panel.csv` exists. selector_score and final_score are both recorded per snapshot. The analysis requires: (a) identifying snapshots where selector_score top-30 does not equal final_score top-30 (divergent snapshots), (b) computing forward returns for each set, (c) comparing medians.

**PIT safety:** FULL. Both scores are snapshot-computed from PIT-safe inputs.

**Robustness risk:** LOW for the test itself. The result may be regime-sensitive (April 2026 XBI selloff), so [REGIME_CAVEAT] applies to interpretation.

**Implementation risk:** ZERO. No code changes. Descriptive analysis of existing panel.

**Calibration readiness:** COMPUTABLE NOW. n=12 HIT/MISS is still severely underpowered for definitive conclusions, but the descriptive sign-test (how many divergent snapshots does selector top-30 outperform ranker top-30) is immediately informative.

**Production risk:** ZERO. This is a read-only analysis.

**Explainability:** PERFECT. "We tested whether adding the ranker helps; here is the comparison."

**Time to valid test:** Computable now. Formal statistical power: Gate 4 (~2026-07-15). But the descriptive analysis at n=12 is the most informative single test currently available.

**Methodology note:** The analysis must separate "divergent snapshots" (selector top-30 not equal to final_score top-30) from "identical snapshots" (ranker causes no reordering). In identical snapshots, the ranker adds zero information and the comparison is undefined. The relevant n is the count of divergent snapshots.

**Conclusion:** This is the most immediately actionable task in the entire T6 memo. It requires no new data, no code changes, and no governance approvals. It frames all other alternatives — if selector_score alone performs equivalently, the ranker complexity burden is unjustified until a specific mechanism (Alt 3, Alt 4, or Alt 6) clears evidence gates. Assign to T5 ablation protocol as the first test.

---

## Priority Queue
*Ranked by: (expected alpha contribution) x (time-to-valid-test)^(-1)*

| Rank | Alt | Category | Next Action | Est. First Valid Test |
|------|-----|----------|-------------|----------------------|
| 1 | 10 — No-ranker comparator | MEDIUM_POTENTIAL_SHADOW | Compute selector vs. final_score divergent-snapshot comparison from existing panel | Now (descriptive); 2026-07-15 (powered) |
| 2 | 6 — Event-EV | HIGH_POTENTIAL_BUT_BLOCKED | Escalate Spec 077 join fix to T8; define fix spec (fuzzy match vs. shared node_id); get timeline commitment | 2026-Q4 at earliest (if fix begins June 2026) |
| 3 | 3 — Catalyst timing | HIGH_POTENTIAL_BUT_BLOCKED | Shadow-track catalyst_decay_w distribution diagnostics; no scoring. Wait for Spec 071 Lane 2 (~2026-Q3) | 2026-Q4 (Lane 2 complete AND Gate 4) |
| 4 | 4 — Catalyst quality | HIGH_POTENTIAL_BUT_BLOCKED | Same as Alt 3; shadow-track binary_quality_score distribution within top-60 | 2026-Q4 (same blockers as Alt 3) |
| 5 | 5 — financial_score direction | NEEDS_HUMAN_REVIEW | Gate 1: operator resolves sign-direction question via Spec 074 or code audit | Unblocks only after Gate 1 |
| 6 | 2 — inst_delta_z | MEDIUM_POTENTIAL_SHADOW | Wait for 13F quarantine lift (~2026-05-20); audit PIT-lag construction; re-evaluate post-refresh | 2026-07-15 (post-quarantine + Gate 4) |
| 7 | 1 — Momentum | LOW_POTENTIAL | No action; archive | N/A |
| 8 | 8 — Clinical design quality | NO_GO | No action; shadow-only attribution; revisit 2026-05-22 verdict review only | N/A |
| 9 | 9 — Hybrid composite | NO_GO | No action until individual signals clear Checklist v2 (>=2027) | >=2027 |
| 10 | 7 — EES v3 | NO_GO | CLOSED PERMANENTLY | N/A |

---

## T8 Escalations

### Escalation 1 (Carried from T4): financial_score sign direction [CRITICAL — PRODUCTION CORRECTNESS]
- **Question:** Is the negative coefficient (-0.0533) on financial_score an intentional stress-upside encoding or an inversion artifact?
- **Decision owner:** Operator / model architect
- **Materials needed:** Original model training log; rationale for financial_score feature construction; Spec 074 findings if completed
- **Blocker consequence:** All Alt 5 research frozen; ranker interpretation ambiguous until resolved
- **Urgency:** HIGH. This is not a research question — if the coefficient is inverted, the production ranker is systematically misranking.

### Escalation 2 (Carried from T4): EES v3 architecture scope confirmation
- **Question:** Is the EES v3 lane closure (conditional_misprice_score, base_rate_gap_score) understood by all parties as permanent? Are there any planned future reformulations using pmv as an input?
- **Decision owner:** Operator sign-off
- **Urgency:** LOW. Confirm once; then archive. No future T-series memo needs to assess this.

### Escalation 3 (New — T6): Spec 077 join failure prioritization [HIGH — INFRASTRUCTURE]
- **Question:** What is the timeline for resolving the 70% Spec 077 join failure? Is the preferred fix (a) fuzzy date matching +/-N-day window, or (b) shared node_id assigned at CRT entry time?
- **Decision owner:** Infrastructure/engineering owner
- **Blocker consequence:** Alt 6 (Event-EV) is the highest-potential alternative; zero evidence accumulation is possible until this fix ships. Every month of delay is ~3-4 lost HIT/MISS calibration records.
- **Urgency:** HIGH. If fix is targeted for June 2026, the first clean bound records could appear before Gate 4 (~2026-07-15), enabling an early read. If fix slips to Q4, Event-EV cannot contribute to any 2026 analysis.

### Escalation 4 (New — T6): Spec 071 Lane 2 timeline confirmation
- **Question:** Is the ~2026-Q3 estimate for Spec 071 Lane 2 (false-catalyst OLE/PK classifier) firm? What are the specific dependencies (data labeling, model training, validation)?
- **Decision owner:** Spec owner / engineering
- **Blocker consequence:** Alts 3 and 4 (both HIGH_POTENTIAL_BUT_BLOCKED) cannot begin shadow testing or IC accumulation until Lane 2 ships.
- **Urgency:** MODERATE. Plan around Q3 estimate; if it slips, adjust Alt 3/4 timelines accordingly.

---

## Blocking Dependency Map

```
Alt 10 (no-ranker comparator)
  No blockers. Computable now from existing panel.

Alt 2 (inst_delta_z)
  13F quarantine lift (~2026-05-20)
  13F Q1 2026 refresh integration (~2026-05-15)
  PIT-lag construction audit
  Gate 4: n>=30 HIT/MISS (~2026-07-15)

Alt 3 (catalyst timing)
  Spec 071 Lane 2: false-catalyst OLE/PK classifier (~2026-Q3)
  Gate 4: n>=30 HIT/MISS (~2026-07-15)
  [Both required; either alone is insufficient]

Alt 4 (catalyst quality)
  Spec 071 Lane 2 (~2026-Q3) [same blocker as Alt 3]
  Gate 4: n>=30 HIT/MISS (~2026-07-15)
  D9 conditional IC retest post-cohort-window-close (~2026-05-15)

Alt 5 (financial_score direction)
  Gate 1: Operator resolves sign-direction question (Spec 074 or code audit)
  [No timeline estimate; escalated to T8]

Alt 6 (Event-EV)
  Spec 077 join failure fix (no timeline; escalated to T8)
  PIT audit of 6-layer prior construction
  Forward accumulation: n>=30 bound HIT/MISS (starts counting only after join fix)
  [Total pipeline: likely 2026-Q4 at earliest]

Alt 1 (momentum)     -> NO ACTION
Alt 7 (EES v3)       -> PERMANENT NO_GO
Alt 8 (clinical)     -> CLOSED LANE; revisit 2026-05-22 verdict review only
Alt 9 (hybrid)       -> All individual signals must clear Checklist v2 (>=2027)
```

**Shared dependency — Gate 4 (n>=30 HIT/MISS):**
Accumulation rate: ~3-4 resolved HIT/MISS per month. Current count: 12. Estimated Gate 4: ~2026-07-15. This gate is shared by Alts 2, 3, 4, and all formal IC tests. It cannot be accelerated.

**Shared dependency — 13F quarantine / cohort-window close:**
~2026-05-15 (13F refresh) + ~2026-05-20 (quarantine lift). Affects inst_delta_z stability and any signals computed from institutional holdings. Affects interpretation of April 2026 IC estimates.

---

## What Can Be Done Now vs. What Must Wait

### Doable now (no blockers, no governance risk)

1. **Alt 10 descriptive analysis:** Compute selector_score top-30 vs. final_score top-30 divergent-snapshot comparison from `forward_returns_panel.csv`. Identify how many of the 17 snapshots produced divergent top-30 sets; compute per-name forward return differentials; sign-test. This is the most informative single test available. Assign to T5 ablation as the priority.

2. **Alt 4 shadow diagnostic:** Compute distribution of `binary_quality_score` within the current top-60 across all 17 snapshots. Characterize variability, identify whether quality scores are concentrated or spread. This is diagnostic only — no scoring implication.

3. **Alt 3 shadow diagnostic:** Compute distribution of `catalyst_decay_w` within the current top-60. How many top-60 names have near-term (<=60d) primary-endpoint catalysts vs. OLE/continuation? This characterizes the opportunity set without requiring Lane 2.

4. **Alt 2 quarantine monitoring:** Flag in ops runbook to re-evaluate inst_delta_z post-2026-05-20. No action needed now.

5. **Gate 4 tracker:** Maintain count of clean post-PIT HIT/MISS records. Current: 12. Target: 30. Expected: ~2026-07-15. Update weekly.

### Must wait (blocked by specific named gates)

| Item | Blocker | Estimated Unblock |
|------|---------|-------------------|
| Alt 3 shadow test | Spec 071 Lane 2 | ~2026-Q3 |
| Alt 4 shadow test | Spec 071 Lane 2 | ~2026-Q3 |
| Alt 4 D9 IC retest | Cohort-window close | ~2026-05-15 |
| Alt 5 any evaluation | Gate 1 (sign direction) | Unscheduled |
| Alt 6 any evaluation | Spec 077 join fix | Unscheduled |
| Alt 2 formal test | 13F quarantine + Gate 4 | ~2026-07-15 |
| Any formal IC test | Gate 4 (n>=30 HIT/MISS) | ~2026-07-15 |
| Any Checklist v2 test | Year stability (>=12mo post-PIT) | 2027-04-17 |
| Alt 9 evaluation | Individual signals clear Checklist v2 | >=2027 |

---

## Handoff to T7

T7 [implementation planner] receives the following from T6:

### Immediate tasks (T7 can schedule)

1. **Alt 10 analysis** — Priority 1. Compute selector_score vs. final_score divergent-snapshot comparison. Input: `forward_returns_panel.csv`, all 17 snapshots. Output: signed return differential per divergent snapshot; sign-test result; conclusion on ranker marginal value at current sample. No code changes — analysis only.

2. **Alt 3 + Alt 4 shadow diagnostics** — Priority 2. Distribution analysis of `catalyst_decay_w` and `binary_quality_score` within top-60 across 17 snapshots. Output: distribution stats; qualitative characterization of opportunity set. No IC claims.

3. **Gate 4 tracker** — Priority 3. Weekly update to HIT/MISS count. Flag when n=20 (midpoint) and n=30 (gate).

### Blocked tasks (T7 documents for future scheduling)

4. **Alt 6 Spec 077 join fix** — Cannot schedule implementation until T8 escalation (Escalation 3) returns with architecture decision (fuzzy match vs. node_id). T7 should hold a slot for this task.

5. **Alt 3 / Alt 4 shadow test** — Cannot begin until Spec 071 Lane 2 ships. T7 should checkpoint against Q3 estimate.

6. **Alt 5 coefficient audit** — Cannot schedule until Gate 1 (T8 Escalation 1) resolves.

### Standing constraints for T7

- Architecture is frozen: no model surgery, no feature engineering, no pipeline changes without governance approval
- All alt tests are descriptive only until Gate 4 AND Checklist v2 gates are met
- EES v3 (Alt 7), Alt 8 (clinical ranker), Alt 9 (hybrid) are closed; do not schedule
- BCRX 2026-05-01 HIT record (CT_PRIMARY_COMPLETION source) must be flagged as potential false-catalyst in any validation dataset; exclude from timing-signal tests until Lane 2 cleans it
- [REGIME_CAVEAT] on all April 2026 IC estimates; note in any T7 analysis output

### Key dates for T7 planning calendar

| Date | Event | Action |
|------|-------|--------|
| 2026-05-15 | 13F Q1 2026 refresh | Check cohort membership changes; assess inst_delta_z stability |
| 2026-05-20 | 13F quarantine target lift | Begin Alt 2 shadow tracking if quarantine cleared |
| 2026-05-22 | Phase A verdict review (clinical) | Update Alt 8 status if verdict changes |
| 2026-05-22 | D8/D9 vNext verdict review | Update Alt 4 D9 conditional IC assessment |
| 2026-05-26 | inst_delta forward shadow h20d verdict | Update Alt 2 assessment |
| 2026-07-15 | Gate 4 target (n>=30 HIT/MISS) | First formal IC tests become powered |
| 2026-Q3 | Spec 071 Lane 2 target | Alt 3 + Alt 4 shadow tests unblock |
| 2026-Q4 | Alt 6 earliest (if Spec 077 fixed June 2026) | First bound EV records expected |
| 2027-04-17 | Year stability gate | Checklist v2 Year-Stability module earliest eligible |

---

*End of T6 memo. This document is research only. No signal has been promoted, no code changed, no production system modified.*
