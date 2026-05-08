# T5 — Future Ablation and Evaluation Protocol (2026-05-08)

**Author:** T5 [analyst]
**Task:** Design future ablation and evaluation protocol (Task #5 in ranking-alternatives research queue)
**Date:** 2026-05-08
**Status:** Design document only — read-only research plus one memo write. No code changes. No production artifact writes beyond this memo.

---

## Executive statement

This document is a design specification for a future ablation protocol. It authorizes nothing. No test in this document may be executed until every applicable pre-condition in the Pre-conditions checklist (Section 1) is verified. No ablation result — however positive — constitutes authorization to modify production. Human operator sign-off is required at every promotion gate. This document contains no recommendation to implement, promote, or change any production component. The architecture freeze (`policy_freeze_architecture_2026_04_19.md`) and the Checklist v2 requirement (`policy_alpha_freeze_2026_04_04.md`) remain in full force.

---

## Section 1 — Pre-conditions checklist

All seven gates must be explicitly verified (with artifact evidence) before any ablation run begins. Partial gate satisfaction permits only the subset of alternatives whose specific gates are met (see Section 5, Ablation sequencing). No gate may be self-certified by the analyst running the ablation; each requires the specific verification method described below.

### Gate 1 — financial_score sign direction confirmed
**Required for:** All alternatives (production correctness; affects interpretation of the current baseline and all alternatives containing financial_score as a component or comparator).
**Verification method:** Read `docs/MODEL_DOCUMENTATION.md` Module 5 rank-norm section and confirm: (a) whether high financial_score = financially safe / solvent OR financially stressed / distressed; (b) whether the -0.0533 coefficient in `production_data/ranker_v2_model.json` is intentional stress-upside penalization or a directional error. Cross-reference Spec 074 §2 hypothesis statement. Record conclusion as CONFIRMED_CORRECT, CONFIRMED_WRONG, or STILL_UNCERTAIN with evidence citation.
**Blocking condition:** If CONFIRMED_WRONG, halt. This is a production correctness issue requiring operator sign-off before any ablation proceeds. Route to T8 with [URGENT FINDING] classification.
**If STILL_UNCERTAIN:** Do not run or interpret any ablation where financial_score direction affects the result, except descriptive membership/overlap analysis with a clear [DIRECTION UNCERTAIN — results not interpretable] label on every output. No return/IC interpretation until direction is resolved. financial_score sign direction is a production-correctness gate, not a modeling assumption that can be waived.
**Estimated resolution date:** Immediate (readable from documentation; no additional data collection required).
**Spec reference:** Spec 074; T4 §3.5.

### Gate 2 — Spec 071 Lane 2 shipped
**Required for:** Alternatives 3 (catalyst timing) and 4 (catalyst quality) only.
**Verification method:** Confirm `specs/changes/spec_071_catalyst_quality_gate.md` Lane 2 section shows status SHIPPED, and confirm Lane 2 classifier is active in a production snapshot (check `catalyst_quality` field distribution — `registry_only` count should decrease relative to 2026-05-08 baseline of 174). Check diff artifact for Lane 2 analogous to `artifacts/audit/spec_071_lane1_diff_2026-05-06.md`.
**Estimated resolution date:** [UNCERTAIN] — Lane 2 requires Checklist v2 and an OLE/PK-subtrial/observational classifier. No implementation date committed. Estimated ~2026-Q3.
**Spec reference:** Spec 071 §Lane2; T3 §catalyst quality coverage.

### Gate 3 — 13F Q1 2026 refresh complete and quarantine lifted
**Required for:** All inst_delta-adjacent alternatives; required for all alternatives as a regime-stability precondition.
**Verification method:** (a) Q1 2026 13F refresh landed: check `institutional_summary.json` datestamp and confirm Q1 2026 holdings data. (b) One-cycle contamination rule applied: first clean post-13F snapshot must be ≥2 production cycles after the refresh snapshot. Earliest: ~2026-05-20. (c) `inst_delta_regime` field in rankings.csv must read "stable" for ≥2 consecutive snapshots (not "transition"). (d) If `13F_COHORT_QUARANTINE_PREP_2026_05_01.md` G1/G2/G3 guardrails are triggered, quarantine is not lifted regardless of (a)-(c).
**Jaccard trigger:** Top-30 Jaccard pre/post refresh < 0.70 = quarantine continues; do not begin ablation.
**Estimated resolution date:** ~2026-05-20 (one cycle after ~2026-05-15 refresh).
**Spec reference:** `13F_COHORT_QUARANTINE_PREP_2026_05_01.md`; T3 §13F quarantine.

### Gate 4 — n ≥ 30 post-PIT HIT/MISS resolved outcomes
**Required for:** Alternatives 3 (catalyst timing), 4 (catalyst quality), and the formal descriptive phase of all alternatives.
**Verification method:** Count `artifacts/postmortem/` files with: (a) catalyst_date ≥ 2026-04-17 (post-PIT boundary); (b) outcome IN ("HIT", "MISS"); (c) price data confirmed present. The current count is 12. Log the count and the list of tickers/dates before any ablation run. Do not count NEEDS_REVIEW, DELAYED, or null.
**BCRX flag:** BCRX (2026-05-01) is a potential false-catalyst-that-resolved-as-HIT. Exclude from timing/quality ablation unless post-Spec071-Lane2 reclassification confirms it as a genuine catalyst event.
**Estimated resolution date:** ~2026-07-15 at current accumulation rate (~3–4 HIT/MISS per month).
**Spec reference:** T3 §resolved catalyst outcomes; T4 §3.1.

### Gate 5 — n ≥ 50 post-PIT clean production snapshots
**Required for:** Checklist v2 formal battery for any alternative (FM + bootstrap + FDR + LOSO + year stability).
**Verification method:** Count canonical snapshot directories under `data/snapshots/` with date ≥ 2026-04-17, excluding all variant directories (suffixes: `__stale_pit_cache`, `__stale_trials`, `.morning_backup_*`, `__pre_*`). Current count: 17. Target: 50.
**Estimated resolution date:** ~2026-07-31 (accumulating at ~5–6 snapshots/week).
**Spec reference:** `policy_alpha_freeze_2026_04_04.md` (Checklist v2 components); T3 §post-PIT snapshots.

### Gate 6 — prospective non-null event_ev_p_hit sample gate (n ≥ 30 bound records)
**Required for:** Alternative 6 (event-EV ranker) only.
**Verification method:** (a) Spec 077 binder health confirmed: `_bind_event_ev_p_hit` ran on resolution files; verify via Spec 096 monthly monitoring log. The binder shipped forward-only (2026-05-06); no join-fix is required — the binder is operational. (b) Count non-null bound records across ALL post-PIT resolution files. Current count: 0. Target: ≥30. Non-null values will appear as prospective EV artifacts are produced for newly resolved events. (c) Do NOT require join failure rate to improve — historical ~70% rate was the rationale for forward-only design; it is not a current gate condition.
**Selection bias note:** Document the catalyst-family distribution of the first non-null bound records when they arrive. Early records may be biased toward events with EV artifact coverage (high-visibility, near-term catalysts). If > 50% of first 30 bound records come from a single catalyst family, flag as [PROSPECTIVE_SELECTION_BIAS_RISK].
**Monthly check:** Run Spec 096 binder population check on the first of each month (or after each new HIT/MISS resolution). Next check: 2026-06-08.
**Estimated resolution date:** ~2026-07-01 per Spec 079 (requires prospective EV artifact coverage to reach ~30 new post-PIT resolved events, accumulating at ~3–4 HIT/MISS per month).
**Spec reference:** Spec 077; Spec 079; Spec 096; T3 §event_ev_p_hit bound records.

### Gate 7 — False-catalyst contamination rate confirmed ≤ 5% in the test sample
**Required for:** Alternatives 3 and 4 specifically; advisory for all alternatives using catalyst-adjacent features.
**Verification method:** In the set of ≥30 post-PIT HIT/MISS outcomes to be used in the ablation test sample, calculate: (a) fraction where `catalyst_quality` = "registry_only" (not "binary_alpha"); (b) for the "registry_only" subset, apply the Lane 2 classifier (if shipped) or apply manual review to identify probable false catalysts. If estimated false-catalyst fraction in the test sample exceeds 5%, the sample is contaminated for timing/quality ablation purposes.
**Alternative action if Gate 7 fails:** Restrict the test sample to `binary_alpha` rows only. Document the restriction and reduced effective n before proceeding.
**Estimated resolution date:** Contingent on Gate 2 (Lane 2). Before Lane 2: [UNCERTAIN]. After Lane 2: measurable from production data.
**Spec reference:** Spec 071; Spec 078; T4 §Alternative 3; T3 §false-catalyst hygiene.

### Pre-conditions summary table

| Gate | Requirement | Blocks | Estimated date |
|---|---|---|---|
| 1 | financial_score sign direction confirmed | All alternatives (correctness) | Immediate |
| 2 | Spec 071 Lane 2 shipped | Alternatives 3, 4 | ~2026-Q3 [UNCERTAIN] |
| 3 | 13F refresh complete + quarantine lifted | All (regime stability) | ~2026-05-20 |
| 4 | n ≥ 30 post-PIT HIT/MISS | Alternatives 3, 4; formal descriptive | ~2026-07-15 |
| 5 | n ≥ 50 post-PIT clean snapshots | Checklist v2 for all alternatives | ~2026-07-31 |
| 6 | n ≥ 30 prospective non-null event_ev_p_hit records (binder operational; sample accumulation gate) | Alternative 6 | ~2026-07-01 |
| 7 | False-catalyst rate ≤ 5% in test sample | Alternatives 3, 4 | Contingent on Gate 2 |

---

## Section 2 — Baseline definitions

### Baseline 1 — Current production ranker (frozen reference)

**Definition:** The production 2-feature pairwise Bradley-Terry ranker as deployed on 2026-05-08. Features: `coinvest_score_z` (weight +0.02, capped from trained +0.0613) and `financial_score` (weight -0.0533, uncapped). Bias: +0.5019. Architecture: pairwise logistic, cohort = top-60 by selector_score.
**Data source:** `production_data/ranker_v2_model.json` (model_variant = "deployed_live_pilot"). `data/snapshots/{date}/rankings.csv` for per-snapshot scores.
**How to compute:** Score each top-60 ticker using the pairwise scoring method in `ranker_v2_pairwise.py` with z-scoring performed within the top-60 cohort at each snapshot date. Do not retrain or alter weights. Snapshot-level top-30 is sorted descending on final_score.
**Frozen artifact:** Lock the exact `ranker_v2_model.json` SHA before beginning the ablation. If the production model artifact changes during the ablation study, the baseline must be re-established using the new artifact and all prior results treated as against a different baseline.
**Gate requirement:** Gate 1 (financial_score direction verification recorded, even if STILL_UNCERTAIN, before baseline is characterized).

### Baseline 2 — Selector-only ordering (no pairwise ranker)

**Definition:** Top-30 selected by descending selector_score. The pairwise ranker is not applied. All eligible tickers ranked by selector_score alone; top-30 taken.
**Data source:** `data/snapshots/{date}/rankings.csv`, column `selector_score`. Eligible rows only (eligible = 1). Confirmed available for all 17 post-PIT snapshots.
**How to compute:** Sort eligible rows by selector_score descending; take top-30. Assign equal weight within size-bands. Compute all metrics for this top-30 vs production top-30.
**Gate requirement:** None beyond Gate 1. Testable in descriptive mode NOW at n=17 snapshots.

### Baseline 3 — Ranker without coinvest (financial_score only; coinvest weight = 0)

**Definition:** Production ranker with coinvest_score_z weight set to 0.00. financial_score weight retained at -0.0533. Bias retained at +0.5019. Cohort still top-60 by selector_score.
**Data source:** Synthetic — apply modified weight vector to `data/snapshots/{date}/rankings.csv` columns for top-60 cohort members.
**How to compute:** For each top-60 ticker at each snapshot date, compute pairwise win probability using only financial_score (z-scored within top-60). Average pairwise wins to produce per-ticker score. Take top-30 descending.
**Gate requirement:** Gate 1 (financial_score direction must be documented before results are characterized). Gate 3 recommended for clean measurement.
**Investment logic check:** If Gate 1 returns CONFIRMED_WRONG, the financial_score-only baseline would be systematically inverted relative to its investment thesis. Document explicitly.

### Baseline 4 — Ranker without financial_score (coinvest only; financial_score weight = 0)

**Definition:** Production ranker with financial_score weight set to 0.00. coinvest_score_z weight retained at +0.02. Bias retained at +0.5019. Cohort still top-60 by selector_score.
**Data source:** Same as Baseline 3 — synthetic modification of weight vector applied to `data/snapshots/{date}/rankings.csv`.
**How to compute:** For each top-60 ticker at each snapshot date, compute pairwise win probability using only coinvest_score_z (z-scored within top-60). Average pairwise wins. Take top-30 descending.
**Gate requirement:** Gate 1 (for comparison interpretation). Gate 3 recommended.
**Notes:** Because coinvest_score_z is the dominant selector signal (92.7% variance explained) AND the primary ranker feature, this baseline will likely produce near-identical top-30 ordering to Baseline 2 (selector-only). The Jaccard overlap between Baseline 4 and Baseline 2 is itself a diagnostic of the ranker's marginal contribution from financial_score.

### Baseline 5 — Current ranker + catalyst timing (catalyst_decay_w; Spec 080 variants A1/A2/A3)

**Definition:** Production ranker augmented with `catalyst_decay_w` as a third pairwise feature. Spec 080 defines four variants: A0 (no timing; retained as Baseline 1 for comparison), A1 (decay_half_life = 60d), A2 (decay_half_life = 90d), A3 (decay_half_life = 120d). Weight for new feature must be pre-specified (NOT selected in-sample): start at w=0.02. Do not tune the weight on the validation data.
**Data source:** `catalyst_decay_w` column in `data/snapshots/{date}/rankings.csv` (299/299 non-null).
**How to compute:** Three-feature pairwise logistic, z-scoring all three features within top-60 cohort at each date. Pre-specify variant weights before looking at outcomes. Test all three variants simultaneously; apply BH FDR correction across variants A1/A2/A3 as a family.
**Gate requirement:** Gates 1, 2, 3, 4, 7. BLOCKED until approximately 2026-Q3 (Gate 2 is the binding constraint).
**Pre-registration requirement:** A pre-specified prior for catalyst_decay_w half-life must be committed in a written artifact BEFORE any outcome data is consulted. This artifact must be created before Phase 3 begins.

### Baseline 6 — Current ranker + catalyst quality / catalyst_score (Spec 080 variant A2)

**Definition:** Production ranker augmented with `catalyst_score` as a third pairwise feature. Pre-specified weight: w=0.02. Cohort top-60. No weight tuning on validation data.
**Data source:** `catalyst_score` column in `data/snapshots/{date}/rankings.csv` (299/299 non-null). Cross-reference `catalyst_quality` field (binary_alpha vs registry_only) to confirm catalyst_score reliability.
**How to compute:** Three-feature pairwise logistic. Z-score within top-60. Compute pairwise win probabilities. Take top-30 descending. Separately compute results restricting to `binary_alpha` rows only.
**Gate requirement:** Gates 1, 2, 3, 4, 7. Same binding constraint as Baseline 5 (Lane 2 required because catalyst_score inherits registry_only false positives). BLOCKED until ~2026-Q3.
**Notes:** The Phase A audit finding (catalyst_score conditional ρ=+0.19, 17/17 snapshots positive) is a descriptive shadow result only and does not pre-authorize this baseline for formal testing.

### Baseline 7 — Current ranker + event_ev_p_hit (Spec 079; after Gate 6)

**Definition:** Production ranker augmented with `event_ev_p_hit` from resolution records as a third pairwise feature. Applied only to top-60 cohort members that have a non-null, Spec-077-bound event_ev_p_hit value. For cohort members with null event_ev_p_hit, the two-feature production score is used unchanged. Pre-specified weight: w=0.02 initially.
**Data source:** `data/snapshots/resolutions/{year}/{month}/{TICKER}_{DATE}.json`, field `event_ev_p_hit`. Current: 0 non-null (binder operational; prospective EV artifacts not yet covering post-PIT resolved events). This baseline CANNOT be instantiated until Gate 6 is met (≥30 non-null bound records).
**How to compute:** At each snapshot date, identify top-60 cohort members with non-null event_ev_p_hit. For those members only, compute a modified pairwise score using all three features. For non-null coverage below 50% of the top-60 cohort, mark results [PARTIAL COVERAGE — n={count}].
**Gate requirement:** Gates 1, 3, 6. Gate 6 is the binding constraint.
**Calibration pre-check:** Before running Baseline 7, verify Spec 079 calibration review has been completed. If event_ev_p_hit has Brier score ≥ 0.25 at n≥30, this baseline must be held until calibration improves.

### Baseline 8 — Current ranker + risk-control overlay (runway_severity_score; eligibility refinement only)

**Definition:** NOT an alpha-seeking alternative. Tests whether penalizing high runway_severity_score names within the top-60 cohort (as an eligibility refinement, not a ranking signal) reduces drawdown without reducing returns. Operationalized as: within top-60, names with runway_severity_score above P75 of cohort are excluded from the final top-30 selection. Remaining slots filled by production ranker ordering.
**Data source:** `runway_severity_score` column in `data/snapshots/{date}/rankings.csv` (299/299 non-null).
**How to compute:** At each snapshot: (1) rank top-60 by production ranker score descending; (2) exclude names in top-quartile of runway_severity_score within cohort; (3) take top-30 from remaining. Record: count of excluded names per snapshot.
**Gate requirement:** Gate 1. Gate 3 recommended.
**Policy constraint:** This baseline is evaluated on drawdown and risk-adjusted returns ONLY. It must NOT be reported as an alpha-generating alternative. If the overlay produces higher mean returns than the production ranker, the result must be labeled [RISK-CONTROL ONLY — return improvement not attributable to alpha].

### Baseline 9 — Current ranker + expectation-gap overlay (options-implied; shadow descriptor only)

**Definition:** Shadow-only descriptor: the subset of the top-30 where `opt_liquidity_ok = 1` AND `priced_move_pct` is available. Compute the cross-sectional distribution of priced_move_pct within the top-30 and top-60. This is a descriptive overlay only. priced_move_pct must NOT be added as a ranker feature under any circumstances (EES v3 closure applies — Spearman ρ(conditional_misprice_score, priced_move_pct) = -0.978).
**Data source:** `data/snapshots/{date}/rankings.csv`, columns `opt_liquidity_ok`, `priced_move_pct`. Options liquid coverage: 87/299 (29.1%).
**How to compute:** Descriptive statistics only: mean, median, P25/P75 of priced_move_pct within top-30 and within cohort, by catalyst family, by cap bucket. No IC computation. No regression.
**Gate requirement:** Gate 1. No other gates (descriptive only).
**Hard constraint:** Label all outputs: [SHADOW DESCRIPTOR — NOT AN ALPHA CANDIDATE — EES v3 CLOSURE APPLIES].

### Baseline 10 — Equal-weight / deterministic comparator (noise floor)

**Definition:** Top-30 selected by random permutation within the top-60 (coinvest tier), establishing a noise floor. Three sub-variants:
- 10a: Alphabetical sort within top-60 (deterministic negative control)
- 10b: Reverse-alphabetical sort within top-60 (deterministic negative control)
- 10c: Random permutation (1,000 draws; reports mean and CI of returns)

**Data source:** `data/snapshots/{date}/rankings.csv`, eligible column and selector_score for top-60 identification. Ticker symbol for alphabetical variants. Random seed must be fixed and documented before any draw.
**How to compute:** For 10a/10b: sort top-60 alphabetically / reverse-alphabetically; take top-30. For 10c: draw 1,000 permutations of the top-60, take first 30 of each; compute return distribution. Report: mean, P5, P95 of top-30 return across 1,000 permutations.
**Gate requirement:** None. Testable at n=17 snapshots NOW.
**Role:** Any alternative must outperform the 10c P95 (upper tail of noise floor) to be considered non-trivial. If an alternative's IC falls inside the [P5, P95] band of 10c random permutations, the alternative adds no reliable signal above random within-cohort ordering.

---

## Section 3 — Metric definitions

### 3.1 Return metrics

**Top-30 and top-60 overlap vs production (Jaccard coefficient)**
- Definition: |A ∩ B| / |A ∪ B| where A = production top-30 (or top-60) and B = alternative top-30 (or top-60) at the same snapshot date.
- Computation: Set intersection and union on ticker symbols. Compute per snapshot date; report mean, median, min, max across all post-PIT snapshots included.
- Data source: `data/snapshots/{date}/rankings.csv`, column `actionable_rank` for production.
- Sample-size requirement: Minimum 5 snapshots for a stable mean; 17 available now for Baselines 2 and 10.

**Turnover / churn (fraction of top-30 that changes each snapshot)**
- Definition: (Number of tickers in top-30 at date t NOT in top-30 at date t+1) / 30. Computed for each consecutive snapshot pair.
- Computation: For each consecutive pair (t, t+1) in the post-PIT snapshot series, count tickers entering and exiting. Report mean churn rate. Compare across alternatives.
- Sample-size requirement: Minimum 3 consecutive snapshot pairs (available now).
- Note: Higher turnover without proportional return improvement = NO_GO signal.

**Forward returns vs XBI: 1d, 5d, 10d, 20d holding periods**
- Definition: Mean equal-weighted return of top-30 names minus XBI return over the same holding period, measured from snapshot date.
- Computation: Use `data/snapshots/_forward_returns_panel.csv`, columns `xbi_return_5d` and `excess_return_5d` for the 5d series. For 1d, 10d, 20d: verify column availability before protocol execution; if absent, specify per-ticker price data source.
- Data source: `data/snapshots/_forward_returns_panel.csv` (primary; 5,949 rows through 2026-05-08). `data/indices_prices.csv` for XBI benchmark (stale through 2026-01-15 — confirm current XBI price feed before use).
- Regime caveat: All measurements across 2026-04-17 to 2026-05-08 carry the label [REGIME_CAVEAT: XBI selloff + cohort change events].

**Event-day excess return (resolved catalysts only)**
- Definition: Ticker return on catalyst event date minus XBI return on same date, for tickers in the top-30 at the most recent snapshot before the catalyst date.
- Computation: For each post-PIT HIT/MISS event in `artifacts/postmortem/`, check whether the ticker was in the production top-30 at the snapshot date immediately prior to catalyst_date. Compute `postmortem.excess_vs_xbi_t1`. Aggregate by outcome (HIT vs MISS) and by catalyst family.
- Sample-size requirement: Current n=12; label ALL results [n=12 — PRELIMINARY].

**Pre-event run-up: T-14 and T-30 relative to event date**
- Definition: Ticker return from T-30 (or T-14) business days before catalyst_date to T-1, minus XBI return over same window.
- Computation: Requires daily price history per ticker. [UNCERTAIN] whether a PIT-valid per-ticker daily price series is available beyond `_forward_returns_panel.csv` — confirm source before protocol execution.
- Sample-size requirement: Same as event-day excess return. Label [PRELIMINARY] until n ≥ 30.

**Post-event drift: +5d, +10d, +20d**
- Definition: Ticker return from catalyst_date+1 to catalyst_date+5, +10, +20, minus XBI return over same window.
- Computation: Use `postmortem.excess_vs_xbi_t3` (3-day) and `postmortem.excess_vs_xbi_t5` (5-day) from resolution files. 10d and 20d require supplemental price source — confirm before execution.

**Drawdown: max peak-to-trough over forward window**
- Definition: Maximum cumulative loss from any peak to any subsequent trough within the forward window (5d, 10d, 20d), measured against XBI.
- Computation: Compute portfolio NAV series (equal-weight top-30) daily from snapshot date through forward window. Find max peak-to-trough drawdown. Compare to XBI drawdown.
- Sample-size requirement: Minimum 10 non-overlapping windows for stable estimate.

### 3.2 Event-specific metrics

**Hit/miss calibration (Alternative 6 only; unblocked after Gate 6)**
- Definition: Compare model-predicted P(HIT) to realized outcome (HIT=1, MISS=0). Compute calibration curve (predicted probability bins vs realized frequency).
- Computation: Bin event_ev_p_hit into deciles. For each bin, compute fraction of events that were HITs. Compare to 45-degree calibration line.
- Sample-size requirement: ≥30 non-null bound records minimum. ≥100 for stable decile analysis (not achievable in 2026).

**Brier score (Alternative 6 only)**
- Definition: Mean squared error between predicted probability and realized binary outcome.
- Pass threshold: Brier score < baseline (base-rate predictor) at n ≥ 30. If Brier ≥ 0.25, the model is not better than base rate and Alternative 6 remains BLOCKED.

**Event-window excess returns: [-1,+1], [0,+2], [0,+5] vs XBI**
- Computation: `postmortem.excess_vs_xbi_t1` covers [0,+1]. `excess_vs_xbi_t3` and `excess_vs_xbi_t5` cover [0,+2] and [0,+5] approximately. [-1,+1] requires pre-event price.
- Sample-size requirement: n ≥ 12 available (PRELIMINARY); n ≥ 30 for formal reporting.

### 3.3 Slice metrics (required for every alternative)

**Cap-bucket slice**
- Compute all return metrics separately for micro, small, and mid-cap names. Report: (a) fraction of top-30 from each cap bucket per alternative, (b) return contribution per cap bucket, (c) IC per cap bucket within top-60 cohort.

**Catalyst-family slice**
- Compute all return metrics separately for PDUFA, data readout (Phase 2/3), ADCOM, CORPORATE_UPDATE.
- Flag: If any family accounts for > 50% of all positive IC contribution, mark [FRAGILE — family-concentrated].

**Stage slice**
- Compute all return metrics separately for Phase 1, Phase 2, Phase 3, and pre-clinical names.
- Data source: `stage_bucket` column in rankings.csv (Spec 068 output).
- Flag: If any stage accounts for > 50% of positive return contribution, mark [FRAGILE — stage-concentrated].

**Regime slice (XBI bull vs bear)**
- Pre-specified threshold (do not adjust in-sample): XBI 20d rolling return ≥ 0% = bull; < 0% = bear.
- Flag: If an alternative has IC > 0 only in one regime, mark [FRAGILE — regime-concentrated].

### 3.4 Statistical rigor metrics

**Rank IC (Spearman) — within top-60 cohort only**
- Definition: Spearman rank correlation between the alternative's ranker score and realized forward excess return (vs XBI, 5d horizon), computed WITHIN the top-60 selector cohort at each snapshot date.
- CRITICAL: Do NOT compute across the full ~297-ticker universe — the ranker only operates on the top-60, and full-universe IC mixes selector and ranker signal.
- Computation: At each snapshot date t: (1) identify top-60 by selector_score; (2) compute the alternative's ranker score for each of those 60; (3) match each ticker to its `excess_return_5d` from `_forward_returns_panel.csv` using (ticker, date) join; (4) compute Spearman correlation of (ranker_score, excess_return_5d) over the 60-ticker cohort. Repeat for all n post-PIT snapshot dates.
- Sample-size requirement: Minimum 10 snapshot dates for stable mean IC. Minimum 30 for NW correction to be meaningful.

**NW-corrected t-statistic (≥ 5 lags)**
- Definition: Newey-West HAC t-statistic on the time series of per-snapshot IC values.
- Lag selection rule: L = floor(4 × (n/100)^(2/9)), minimum 5 lags.
- Threshold for promotion eligibility: NW t-statistic ≥ 2.0. If NW t < 2.0 but conventional t ≥ 2.0, label [NW FAIL — OLS ONLY].
- Sample-size requirement: Minimum 30 snapshots for NW correction to be stable. At n < 30, label [UNDERPOWERED — n={count}].

**Block bootstrap confidence intervals (≥ 1,000 draws)**
- Definition: Moving-block bootstrap CI on mean IC. Block length: L_block = max(5, floor(n^(1/3))). Number of draws: 1,000 minimum, 5,000 preferred.
- Promotion threshold: 95% CI lower bound > 0 (CI excludes zero from below). If CI includes zero, alternative is SHADOW_CANDIDATE only.

**BH/FDR correction for multiple variants**
- Family definitions:
  - Family A: Baselines 5 variants A1/A2/A3 (catalyst timing half-life variants — three tests)
  - Family B: Baselines 3/4 (ablation of individual ranker components — two tests)
  - Family C: Baselines 5/6 together (catalyst-adjacent features — if tested simultaneously)
  - Cross-family correction: Apply BH at q=0.10 across all alternative hypotheses in a single ablation run (conservative).
- Reporting requirement: Always report raw p-values AND BH-corrected p-values side by side.

**LOSO (leave-one-ticker-family-out)**
- Definition: Leave-one-out validation where "one" is defined as a catalyst-family group. At each LOSO fold, exclude all tickers from one catalyst family, compute IC on remaining tickers, repeat for all families.
- Report: mean IC across LOSO folds, min fold IC, max fold IC, fraction of folds with IC > 0.
- FRAGILE criterion: Any single LOSO fold exclusion causes IC to drop by more than 50% of mean IC.
- When to apply: Checklist v2 only (n ≥ 50 snapshots required for stable LOSO).

---

## Section 4 — Sample size requirements table

| # | Alternative | Descriptive shadow min | Formal review min | Checklist v2 min | Earliest descriptive | Earliest formal | Earliest Checklist v2 |
|---|---|---|---|---|---|---|---|
| 1 | Current baseline | 17 snapshots (MET) | 30 snapshots | 50 snapshots + Gates 1,3 | NOW | ~2026-07-01 | ~2026-07-31 |
| 2 | Selector-only (null) | 17 snapshots (MET) | 30 snapshots | 50 snapshots + Gates 1,3 | NOW | ~2026-07-01 | ~2026-07-31 |
| 3 | Ranker without coinvest | 17 snapshots (MET) | 30 snapshots + Gate 1 confirmed | 50 snapshots + Gates 1,3 | NOW (with uncertainty label) | ~2026-07-01 | ~2026-07-31 |
| 4 | Ranker without financial | 17 snapshots (MET) | 30 snapshots + Gates 1,3 | 50 snapshots + Gates 1,3 | NOW (with uncertainty label) | ~2026-07-01 | ~2026-07-31 |
| 5 | Ranker + catalyst timing | Gates 2,3,4,7 all required | Gates 2,3,4,7 + 30 post-13F snapshots | 50 post-13F snapshots + Gates 2,4,7 | ~2026-Q3 (Gate 2 binding) | ~2026-Q3 | ~2026-Q4 [UNCERTAIN] |
| 6 | Ranker + catalyst quality | Same as Alternative 5 | Same as Alternative 5 | Same as Alternative 5 | ~2026-Q3 | ~2026-Q3 | ~2026-Q4 [UNCERTAIN] |
| 7 | Ranker + event_ev_p_hit | Gate 6: n ≥ 30 non-null | Gate 6 + 30 post-13F snapshots | 50 snapshots + Gates 3,6 + Spec 079 pass | ~2026-07-01 | ~2026-08-01 | ~2026-Q4 [UNCERTAIN] |
| 8 | Risk-control overlay | 17 snapshots (MET) | 30 snapshots + Gate 3 | 50 snapshots + Gate 3; drawdown metrics only | NOW (drawdown descriptor) | ~2026-07-01 | ~2026-07-31 |
| 9 | Expectation-gap descriptor | 17 snapshots (MET) — no IC | PERMANENTLY BLOCKED | PERMANENTLY BLOCKED | NOW (no IC allowed) | N/A | N/A |
| 10 | No-ranker comparator | 17 snapshots (MET) | 30 snapshots | 50 snapshots + Gate 3 | NOW | ~2026-07-01 | ~2026-07-31 |

**Year stability note:** Year stability (Checklist v2 component) requires ≥12 months of post-PIT data. Post-PIT period begins 2026-04-17. Year stability cannot be assessed before 2027-04-17. Any Checklist v2 run before that date must flag year stability as [INCOMPLETE — insufficient span]. PROMOTION_ELIGIBLE status cannot be finalized for any alternative before 2027.

---

## Section 5 — Ablation sequencing

### Phase 0 — Immediate (before any ablation begins)

**Gate 1 verification (NOW — no data collection needed)**
Read `docs/MODEL_DOCUMENTATION.md` Module 5 rank-norm section. Record CONFIRMED_CORRECT, CONFIRMED_WRONG, or STILL_UNCERTAIN. Create artifact `artifacts/audit/financial_score_direction_verification_{date}.md` before any ablation measurement proceeds. If CONFIRMED_WRONG, halt and route to T8.

**Gate 3 verification (~2026-05-20)**
After Q1 2026 13F refresh: verify `inst_delta_regime` transitions to "stable." Record verification in a short artifact.

### Phase 1 — Descriptive shadow (now through ~2026-07-01)

Computable descriptively using n=17 post-PIT snapshots (Gate 3 recommended but not blocking for descriptive):
- Baseline 1 (production) vs Baseline 2 (selector-only): Jaccard, churn, descriptive return comparison
- Baseline 10 (deterministic comparator): noise floor establishment
- Baselines 3 (no coinvest) and 4 (no financial): cohort membership overlap only — no forward-return IC claim
- Baseline 8 (risk-control overlay): descriptive drawdown comparison
- Baseline 9 (expectation-gap): options-implied move distribution only — no IC computation

All Phase 1 outputs must be labeled [PHASE 1 — DESCRIPTIVE SHADOW — n=17 — PRELIMINARY — NO PROMOTION ELIGIBILITY].

**Rationale:** Phase 1 establishes the noise floor (Baseline 10) and the selector-only null (Baseline 2) so that all future phases have calibrated comparators.

### Phase 2 — Formal descriptive (~2026-07-01 to ~2026-07-31)

After Gate 3 confirmed AND n ≥ 30 post-PIT snapshots:
- Add NW-corrected IC measurements for Baselines 1, 2, 3, 4, 10 (within top-60 cohort)
- Add block bootstrap CIs for same
- Add BH FDR correction across {Baselines 3, 4} as Family B
- Add HIT/MISS event-day metrics if Gate 4 is met (n ≥ 30 HIT/MISS)
- Begin Baseline 7 (event-EV) if Gate 6 is met (n ≥ 30 non-null bound records)

All Phase 2 outputs labeled [PHASE 2 — FORMAL DESCRIPTIVE — NW-CORRECTED — NO PROMOTION ELIGIBILITY].

**Serial dependency:** Baselines 3 and 4 must run before Baselines 5 or 6 can be sensibly interpreted. Component ablations establish the null decomposition that timing/quality features will be tested against.

### Phase 3 — Catalyst alternatives (~2026-Q3, after Gates 2,3,4,7)

After Spec 071 Lane 2 ships AND Gates 3, 4, 7 all confirmed:
- Baselines 5 (A1, A2, A3) and 6 together, as a single family (Family A + Family C under BH FDR)
- Pre-registration artifact for catalyst_decay_w half-life prior must be created BEFORE any outcome data is consulted
- Alternative 9 (hybrid two-stage) cannot enter Phase 3 — requires Alternatives 3 and 5 to individually validate in formal review first

### Phase 4 — Checklist v2 battery (~2026-07-31 onwards, after Gate 5)

After n ≥ 50 post-PIT snapshots:
- Apply full Checklist v2 to any alternative that reached SHADOW_CANDIDATE in Phase 2 or Phase 3
- Checklist v2 sequence: (1) Feature-marginal test; (2) Block bootstrap CI excludes zero; (3) BH FDR across family; (4) LOSO robustness; (5) Year stability [INCOMPLETE until 2027-04 minimum — flag but do not block Phase 4]

**Parallel vs serial execution:**
- Baselines 1, 2, 3, 4, 10 are parallel (can be computed simultaneously for same snapshot set)
- Baselines 5 and 6 are parallel with each other but serial after Baselines 3 and 4
- Baseline 7 is fully independent of Baselines 5/6 (different data gate)
- Baseline 8 is parallel to all others (different metrics)
- Baseline 9 is permanently parallel as descriptor (never enters the IC sequence)
- Alternative 9 (hybrid two-stage): SERIAL ONLY after both Alternatives 3 AND 5 individually clear formal review. Do not begin before 2026-Q4 at earliest.

---

## Section 6 — Pass/fail framework

**SHADOW_CANDIDATE**
Eligible for shadow reporting only. Cannot be promoted.
Criteria: At least one of the following (plus no NO_GO or UNSAFE criteria met):
- Descriptive return differential > 0 for ≥ 60% of snapshots
- Within-cohort IC above P75 of the n=1,000 random-permutation noise floor (Baseline 10c)
- Cohort Jaccard ≥ 0.50 with production

**FORMAL_CANDIDATE**
Eligible for Checklist v2 battery. Cannot be promoted without completing full Checklist v2.
Criteria (ALL required):
- NW-corrected t-statistic ≥ 1.5 on within-cohort IC
- Block bootstrap CI lower bound > 0
- BH FDR-corrected p < 0.20 within its testing family
- No single LOSO fold eliminates positive IC entirely (IC > 0 in ≥ 70% of LOSO folds)
- No NO_GO or UNSAFE criteria met

**PROMOTION_ELIGIBLE**
Cleared Checklist v2. Still requires human operator sign-off.
Criteria (ALL required):
- NW-corrected t-statistic ≥ 2.0 on within-cohort IC
- Block bootstrap 95% CI lower bound > 0
- BH FDR-corrected p < 0.10 within its testing family
- LOSO robustness: IC > 0 in ≥ 80% of LOSO folds; no single fold exclusion reduces IC by > 50%
- Year stability: [INCOMPLETE until 2027-04 minimum]; flag as [YEAR_STABILITY_INCOMPLETE] and defer final PROMOTION_ELIGIBLE until stable
- Not FRAGILE, not UNSAFE
- Human operator sign-off required before any production change

**NO_GO**
Falsification criterion met. Do not test further unless evidence substantially changes.
Criteria (any ONE sufficient):
- Within-cohort IC ≤ 0 AND NW t < -1.5 (reliably negative)
- IC > 0 only in EES-class formulations (collapsed to monotonic transform of existing signal after residualization)
- Cohort Jaccard with Baseline 10 random permutation > Jaccard with Baseline 1 production
- Alternative violates a standing policy (EES v3 closure, risk-control-only constraint)
- All LOSO folds show IC ≤ 0

**FRAGILE**
Alternative wins only in a specific slice.
Criteria (any ONE sufficient):
- > 50% of positive IC contribution comes from a single catalyst-family LOSO fold
- IC > 0 only in one XBI regime and ≤ 0 in the other
- IC > 0 only in one cap bucket and ≤ 0 in others
- Single LOSO fold exclusion reduces mean IC by > 50%
FRAGILE blocks FORMAL_CANDIDATE and PROMOTION_ELIGIBLE progression unless the fragility is explained by investment logic.

**UNSAFE**
Alternative improves returns but degrades risk profile.
Criteria (any ONE sufficient):
- Improves mean excess return vs production but increases max drawdown by > 50% relative to production drawdown
- Increases false-catalyst exposure (proportion of top-30 with catalyst_quality = "registry_only") by > 15 percentage points vs production
- Increases turnover by > 50% without proportional return improvement
UNSAFE does not block further research but blocks any promotion path.

### Per-alternative classification thresholds

| Alternative | Current status | NO_GO criterion | SHADOW_CANDIDATE | FORMAL_CANDIDATE | PROMOTION_ELIGIBLE |
|---|---|---|---|---|---|
| 1 (Baseline) | Active production — frozen reference | IC persistently ≤ -0.05 + NW t < -2.0 | n/a (frozen reference) | n/a | n/a (architecture frozen) |
| 2 (Selector-only) | Testable now | Jaccard < 0.30 with production AND return differential < -0.50pp | Return differential > 0 ≥ 60% snapshots | NW t ≥ 1.5 + CI > 0 | Checklist v2 complete + operator sign-off |
| 3 (No coinvest) | Testable now | IC < -0.03 + NW t < -1.5 | IC above noise floor P75 | NW t ≥ 1.5 + CI > 0 | Checklist v2 + operator sign-off |
| 4 (No financial) | Testable now | IC same as Baseline 1 + direction verified wrong | IC above noise floor P75 | NW t ≥ 1.5 + CI > 0 | Checklist v2 + operator sign-off |
| 5 (Catalyst timing) | BLOCKED — Gates 2,4,7 | Timing IC ≤ 0 in ≥ 80% of LOSO folds post-Lane2 | Conditional ρ > 0 in ≥ 70% of snapshots (post-gate) | NW t ≥ 1.5 + CI > 0 + FDR pass | Checklist v2 + operator sign-off |
| 6 (Catalyst quality) | BLOCKED — Gates 2,4,7 | catalyst_score residual IC ≤ 0 after selector_score control | Conditional ρ > 0 in ≥ 70% of snapshots (post-gate) | NW t ≥ 1.5 + CI > 0 + FDR pass | Checklist v2 + operator sign-off |
| 7 (Event-EV) | BLOCKED — Gate 6 | Brier ≥ 0.25 at n ≥ 30 | Event-EV IC > 0 at n ≥ 30 + Brier < baseline | NW t ≥ 1.5 + CI > 0 + Spec 079 calibration pass | Checklist v2 + operator sign-off |
| 8 (Risk-control) | Testable (drawdown only) | No drawdown reduction + turnover increase > 50% | Drawdown reduction ≥ 20% relative to production | Not applicable (risk-control only) | Not applicable |
| 9 (Expectation-gap) | Descriptive only | EES v3 closure applies | Not eligible for IC-based classification | Not eligible | PERMANENTLY BLOCKED for current formulation |
| 10 (Null comparator) | Testable now | Rescued-vs-suppressed > +0.50pp at n ≥ 30 (ranker proven necessary) | Differential ≤ 0 at n ≥ 30 (ranker not adding value) | n/a (null hypothesis) | n/a |

---

## Section 7 — Evaluation rules

The following rules are binding for all ablation analysts. Rules may not be waived without explicit written operator sign-off.

1. **No train/test conflation.** Never use the same snapshot dates to select feature variants AND to validate them. If in-sample period spans 2026-04-17 to {X}, out-of-sample validation must use dates strictly after {X}.

2. **Frozen baseline required at all times.** Baseline 1 (current production ranker, 2026-05-08 artifact SHA) must appear in every comparison table. Never substitute a retrained or parameter-adjusted version as the primary comparator.

3. **Model selection separate from validation.** If any hyperparameter is tuned (e.g., catalyst_decay_w half-life), the tuning must occur on a designated selection period and the validation on a strictly disjoint held-out period. Specify both periods before looking at any outcome data.

4. **No pre-PIT evidence.** Do not use, cite, or draw inferences from any snapshot dated before 2026-04-17. Label any such result [PRE-PIT DATA INCLUDED — POTENTIALLY CONTAMINATED].

5. **Explicit sample-size qualification required.** Every metric report must include n(snapshots), n(HIT/MISS), and the applicable [PRELIMINARY], [UNDERPOWERED], or [CHECKLIST_V2_ELIGIBLE] label.

6. **Descriptive shadow cannot become a recommendation.** A shadow-phase result cannot be cited as evidence supporting a production change.

7. **Single-window wins are FRAGILE by definition.** If a result is positive in one snapshot window and has not been confirmed across multiple regimes, mark FRAGILE regardless of statistical significance within that window.

8. **False-catalyst exposure must accompany return metrics.** Any positive return result for catalyst-adjacent alternatives must include: fraction of contributing names with catalyst_quality = "registry_only" vs "binary_alpha." If > 50% of the return gain comes from registry_only names, label [FALSE_CATALYST_EXPOSURE_RISK].

9. **Turnover increase without return improvement = NO_GO.** Compute return per unit of turnover for each alternative. If an alternative increases turnover by > 50% without proportional increase in excess return, classify NO_GO.

10. **Hit rate improvement (event-EV) does not transfer to ranker without return evidence.** If Alternative 7 (event_ev_p_hit; Spec 079) shows improved Brier score but does not improve within-cohort IC vs production, classify as Event EV diagnostic improvement only — not a ranker candidate. Note: Alternative 7 requires Gate 6 (≥30 non-null prospective bound records); do not run until that gate is met regardless of calibration results on earlier smaller samples.

11. **No implementation on positive ablation result alone.** PROMOTION_ELIGIBLE classification is a necessary but not sufficient condition for any production change.

12. **Interaction features (Alternative 9) must post-date individual validation of both component features.** Order is non-negotiable: individual feature validation first (Checklist v2 level), then interaction design, then interaction testing on fresh data.

13. **EES v3 closure is permanent for all pmv-derived formulations.** Any analyst who finds a signal correlated with priced_move_pct at |ρ| > 0.80 must immediately apply residualization before reporting. If IC ≈ 0 after residualization, the signal is closed.

14. **BCRX must be excluded from catalyst-timing and catalyst-quality ablations until reclassification.** BCRX (2026-05-01 HIT, CT_PRIMARY_COMPLETION source) is a potential false-catalyst-as-HIT case.

15. **IC measurement scope: within top-60 cohort only.** Any IC measurement cited for ranker evaluation must be computed within the top-60 selector cohort. If the IC decomposition tool does not support cohort restriction, the tool must be modified or a manual restricted computation must be performed before any IC results are reported.

---

## Section 8 — Required artifacts before protocol can run

| Artifact | Purpose | Current status | Gate dependency |
|---|---|---|---|
| `docs/MODEL_DOCUMENTATION.md` (Module 5 rank-norm section) | Gate 1: financial_score direction verification | Exists; content unverified in this memo | Gate 1 |
| `production_data/ranker_v2_model.json` (SHA recorded) | Baseline 1 frozen reference | Exists; SHA must be recorded before ablation begins | All baselines |
| `data/snapshots/_forward_returns_panel.csv` | Primary forward returns source | Exists; 5,949 rows through 2026-05-08 | All return metrics |
| XBI current price feed (post-2026-01-15) | Benchmark for recent snapshots | `data/indices_prices.csv` stale through 2026-01-15; current source [UNCERTAIN] | All return metrics vs XBI |
| `data/snapshots/{date}/rankings.csv` for all 17 post-PIT dates | Per-snapshot feature data | Exists (17 confirmed clean) | All snapshot metrics |
| `artifacts/postmortem/{date}/{TICKER}.json` for all post-PIT HIT/MISS | Event-day metrics | 12 files confirmed | Event metrics |
| Post-13F `institutional_summary.json` refresh | Gate 3 verification | Does not exist yet (~2026-05-15) | All inst-adjacent alternatives |
| Spec 079 calibration review artifact | Gate 6 pre-check for Alternative 7 | Does not exist yet (0 bound records) | Alternative 7 only |
| Per-ticker daily price history (PIT-valid, post-2026-04-17) | Pre/post event window metrics, drawdown | [UNCERTAIN] whether available beyond `_forward_returns_panel.csv` | Pre-event run-up, post-event drift, drawdown |
| `financial_score_direction_verification_{date}.md` | Gate 1 output artifact | Must be created before ablation begins | All alternatives |
| Pre-registration artifact for catalyst_decay_w half-life prior | Prevents in-sample half-life selection | Does not exist; must be created before Phase 3 | Baseline 5 only |
| Spec 071 Lane 2 diff artifact | Gate 2 verification | Does not exist; blocked on Lane 2 implementation | Baselines 5, 6 |

---

## Section 9 — Explicit no-promotion statement

**A positive ablation result, a PROMOTION_ELIGIBLE classification, or any combination of favorable metrics in this protocol does not authorize any change to the production ranker, selector, eligibility gate, or any other production component.**

The architecture freeze (`policy_freeze_architecture_2026_04_19.md`) and the Checklist v2 requirement (`policy_alpha_freeze_2026_04_04.md`) remain in force. The demotion path governance policy (`policy_demotion_path_2026_05_06.md`) applies equivalently to promotions.

The production workflow after PROMOTION_ELIGIBLE:
1. Human operator reads the full Checklist v2 output and the ablation memo
2. Operator confirms: (a) investment logic is sound; (b) no unresolved [UNCERTAIN] items remain; (c) financial_score direction is confirmed (Gate 1 CONFIRMED); (d) no FRAGILE, UNSAFE, or EES-class flags outstanding
3. Operator writes a sign-off artifact documenting the promotion decision
4. Implementation is scoped as a new Spec, reviewed against the held-spec ledger, and shipped in a separate commit with a diff artifact

No analyst in this Kanban workflow has authority to self-authorize a production change. T5 and subsequent task analysts produce design and analysis artifacts only.

---

## Files inspected

- `artifacts/audit/t1_ranker_anatomy_2026_05_08.md`
- `artifacts/audit/t2_ranker_alternatives_2026_05_08.md`
- `artifacts/audit/t3_data_readiness_2026_05_08.md`
- `artifacts/audit/t4_risk_analysis_2026_05_08.md`

---

## Handoff summary

T5 delivers a complete ablation protocol design with 10 baselines, full metric definitions (return, event, slice, and statistical), a 7-gate pre-conditions checklist, a 4-phase sequenced execution plan, and a crisp SHADOW_CANDIDATE / FORMAL_CANDIDATE / PROMOTION_ELIGIBLE / NO_GO / FRAGILE / UNSAFE pass/fail framework. The binding near-term action is Gate 1 verification (financial_score direction — readable immediately from `docs/MODEL_DOCUMENTATION.md`) and Gate 3 (~2026-05-20). For T6 (alpha potential synthesis): no alternative currently clears FORMAL_CANDIDATE, and PROMOTION_ELIGIBLE requires Checklist v2 plus operator sign-off that cannot complete before 2026-07-31 at the absolute earliest, with year stability requiring 2027-04-17 minimum. For T7 (memo writer): the three critical framing points are (a) financial_score sign direction is the single most consequential unresolved item in the current production ranker; (b) IC must be measured within the top-60 cohort, not the full universe; and (c) PROMOTION_ELIGIBLE is a 2027 horizon event for any new ranker feature due to the year stability requirement.
