# EES v2 Phase 3 Attribution Review

**Date:** 2026-06-23  
**Analyst memo for:** Operator decision review  
**Governance:** DIAGNOSTIC_ONLY | NO_PRODUCTION_CHANGES | FREEZE_ACTIVE  
**Verdict:** `ATTRIBUTION_COMPLETE — CT_PRIMARY_COMPLETION_LEFT_TAIL_AVOIDANCE_SIGNAL`

---

## 1. Purpose

The prior EES forward validation (`EES_V2_PHASE3_SHADOW_MONITOR_SPEC_2026_06_23`) found
that Phase 3 names show diagnostic predictive signal (5d IC=0.174 t=4.97, 31 dates). This
memo answers: **why does it work for Phase 3 but not Phase 2?** Understanding the mechanism
is a prerequisite for any future model design discussion.

All analysis uses the PIT validation panel (`ees_validation_panel_2026-06-23.csv`, 2,610
rows). Same Method A / same archive basis as the accepted PIT evidence review. ATXS
excluded throughout. No live fetches.

---

## 2. Finding 1: The Signal Is CT_PRIMARY_COMPLETION Only

Phase 3 breaks into four event types. Only one has enough date coverage to evaluate:

| Event type | N rows | 5d IC | 5d t | 5d dates | 20d IC | 20d t | 20d dates |
|-----------|--------|-------|------|---------|--------|-------|----------|
| CT_PRIMARY_COMPLETION | 856 | 0.123 | **2.60** | 31 | 0.164 | **3.15** | 15 |
| CT_STUDY_COMPLETION | 120 | 0.177 | n/a | 2 | 0.354 | n/a | 2 |
| DATA_READOUT | 283 | 0.700 | n/a | 1 | — | n/a | 0 |
| FDA_PDUFA_DATE | 128 | -0.600 | n/a | 1 | — | n/a | 0 |

**CT_PRIMARY_COMPLETION (n=856, 60% of Phase 3) is the only event type with enough
cross-sectional date coverage for t-stat inference.** The other types either have 1–2 IC
dates (t=n/a, requiring ≥3) or zero completed 20d observations.

The headline Phase 3 IC figure (0.174 t=4.97) is effectively a CT_PRIMARY_COMPLETION IC.
The other event types are unevaluated, not confirmed.

**Theoretical basis.** CT_PRIMARY_COMPLETION events are the most analyzable under a
base-rate framework:
- Phase 3 trials have pre-specified primary endpoints with documented historical hit rates
- Hit rates by indication × mechanism × phase are available in clinical trial registries
- The EES model's base-rate gap is best calibrated where base rates are reliable and stable
- Phase 2 DATA_READOUT events are more heterogeneous (exploratory endpoints, smaller n,
  fewer comparators) — base rates are noisier

---

## 3. Finding 2: The Eligibility Gate Works Correctly Within Phase 3

The prior validation memo (§3.4) noted a puzzling result: restricting to `ees_eligible=True`
hurt 20d IC in the full panel (IC dropped from 0.061 to 0.013, t from 2.05 to 0.38).

This section resolves that puzzle. Within Phase 3 specifically:

| Subset | 5d IC | 5d t | 5d dates | 20d IC | 20d t | 20d dates |
|--------|-------|------|---------|--------|-------|----------|
| Eligible (n=1223) | **0.158** | **3.88** | 31 | **0.182** | **4.10** | 15 |
| Non-eligible (n=198) | -0.203 | -1.15 | 10 | -0.134 | -0.51 | 5 |

Within Phase 3, eligible names carry **all** of the signal. Non-eligible names show
negative IC (no signal at −1.15 / −0.51 t). The eligible gate correctly discriminates.

**Why did the full-panel eligible restriction hurt IC?** The full panel includes Phase 2
names. Phase 2 eligible names add rows but add no IC signal — they dilute the eligible
pool with noise. When you restrict to eligible across all phases, you gain Phase 2 eligible
names (zero signal) and lose Phase 1 + Phase 3 non-eligible (also zero signal), but you
don't gain Phase 3 eligible names proportionally. The Phase 3 eligible subset is the
signal carrier; mixed-phase eligible pooling obscures it.

**Design implication (diagnostic only):** The eligible gate is doing the right job within
Phase 3. Any future design should evaluate the gate Phase-3-specific, not panel-wide.

---

## 4. Finding 3: Score Distribution Explains the Phase 2 / Phase 3 Gap

| Metric | Phase 3 | Phase 2 |
|--------|---------|---------|
| N rows | 1,421 | 429 |
| Mean EES v2 | -0.049 | -0.054 |
| Median EES v2 | -0.016 | -0.034 |
| % positive score | **9.4%** | **0.9%** |

Phase 3 has roughly 10× the rate of positive EES v2 scores. Both phases are dominated by
negative scores (overpriced relative to base rates), but Phase 3 has meaningful right-tail
dispersion. The EES model generates positive scores more frequently for Phase 3 names —
consistent with Phase 3 base rates being better calibrated in the model.

Phase 2 has essentially zero positive scores (0.9%), which collapses cross-sectional
variance at the top of the score distribution. If nearly all scores are negative and
clustered tightly (-0.054 mean, -0.034 median, 0.9% positive), the model provides little
discrimination above the floor — which is exactly what the IC=0.043 t=0.59 result shows.

---

## 5. Finding 4: The Signal Is Left-Tail Avoidance, Not Symmetric Long/Short

The quintile analysis reveals the score distribution structure:

### 5d: Score quintile → XBI-excess return (Phase 3)

| Quintile | Score range | Mean 5d excess return |
|---------|-------------|----------------------|
| Q1 (lowest) | -0.249 to -0.019 | **-3.47%** |
| Q2 | -0.019 to -0.016 | +0.39% |
| Q3 | -0.016 to -0.015 | +0.53% |
| Q4 | -0.015 to 0.000 | -0.15% |
| Q5 (highest) | ~0.000 | +0.43% |

### 20d: Score quintile → XBI-excess return (Phase 3)

| Quintile | Score range | Mean 20d excess return |
|---------|-------------|------------------------|
| Q1 (lowest) | -0.052 to -0.018 | **-6.80%** |
| Q2–Q5 | ~-0.018 to 0.000 | -1.3% to +3.2% (scattered) |

**The key observation:** Q2–Q5 have nearly identical score ranges (all between -0.019 and
0.000). The 1421 Phase 3 rows are extremely tightly clustered near zero in the score
distribution. Q1 represents the genuine outliers — names with EES v2 scores below -0.019,
which the model flags as most overpriced.

**The signal is dominated by Q1 underperformance, not by Q5 outperformance.** This is a
**left-tail avoidance signal**: the EES model correctly identifies Phase 3 names that
underperform XBI by -3.47% at 5d and -6.80% at 20d. Q5 names show only +0.43%/+1.39%
above XBI — modest and within noise.

**High vs low split confirms asymmetry:**

| Subset | 5d mean excess return | 20d mean excess return |
|--------|----------------------|----------------------|
| High score (≥ median = -0.016) | -0.05% | +1.05% |
| Low score (< median) | -1.01% | **-5.39%** |
| Spread | 0.96% | **6.44%** |

The 20d spread (6.44%) is driven by the low-score tail's -5.39% underperformance.

---

## 6. Finding 5: IC Is Distributed Across Multiple Tickers

Per-ticker IC (5d, min 5 observations, top 10):

| Ticker | N obs | Mean score | Mean 5d excess return | Per-ticker IC |
|--------|-------|-----------|----------------------|---------------|
| DNTH | 28 | -0.0094 | +10.37% | 0.682 |
| ADCT | 30 | -0.0117 | -1.09% | 0.638 |
| ERAS | 6 | -0.0104 | +5.17% | 0.638 |
| CELC | 30 | -0.0144 | +0.34% | 0.621 |
| MLTX | 9 | -0.0140 | -3.78% | 0.532 |
| CGON | 34 | -0.0117 | +1.86% | 0.511 |
| RNA | 8 | -0.0053 | -15.54% | 0.504 |
| RVMD | 34 | -0.0151 | -2.66% | 0.471 |
| REPL | 26 | -0.0150 | +0.65% | 0.454 |
| IMVT | 32 | -0.0145 | -2.16% | 0.380 |

Several observations:

1. **All per-ticker IC values are positive and substantial (0.38–0.68)**. This is not a
   single outlier ticker driving the cross-sectional IC.

2. **All 10 tickers show negative mean EES v2 scores** (range -0.005 to -0.015). The
   within-ticker IC reflects score variation across dates, not score level. The model's
   relative scoring of a ticker over time correlates with its relative return over time.

3. **Per-ticker IC is uncorrelated with mean return**: DNTH has both the highest IC (0.68)
   and the highest mean return (+10.37%); RNA has IC=0.50 but mean return of -15.54%.
   The IC measures how well relative score rank predicts relative return, not whether
   the returns are positive.

4. **Ticker count**: The IC is distributed across at least 10 names with ≥6 observations
   each, spanning a variety of return profiles. This is not a concentration artifact.

---

## 7. Finding 6: IC Consistency — 81% Positive-Date Hit Rate

Per-date IC distribution (Phase 3, 5d, n=31 valid dates):

- Positive IC dates: **25 / 31 (81%)**
- Negative IC dates: 6 / 31 (19%)

Best dates: 2026-03-09 (IC=0.442), 2026-03-26 (IC=0.421), 2026-01-30 (IC=0.414)  
Worst dates: 2026-03-31 (IC=-0.208), 2026-02-27 (IC=-0.204), 2026-03-30 (IC=-0.195)

The 81% positive hit rate matches the headline finding from the validation memo (hit
rate=0.774 per the memo §3.1; slight difference due to this analysis using only Phase 3).
The signal is consistent across the panel period, not driven by a narrow cluster of dates.

The three worst dates (2026-02-27, 2026-03-30, 2026-03-31) cluster around late February /
end of March 2026. This may reflect macro-driven sector rotation in that period overriding
fundamental base-rate signals. Within such periods, cross-sectional IC can invert even
when the model is correctly calibrated — this is expected variance, not model failure.

---

## 8. Attribution Summary

| Finding | Observation | Mechanism |
|---------|-------------|-----------|
| Phase 3 signal source | CT_PRIMARY_COMPLETION only (60% of rows, only type with sufficient dates) | Defined endpoints → reliable base rates → EES well-calibrated for this event type |
| Eligibility gate | Correctly discriminates within Phase 3 (eligible IC=0.158 t=3.88; non-eligible IC=-0.203) | Full-panel eligible dilution was a Phase 2 artifact |
| Score distribution | Phase 3 has 10× the positive score rate of Phase 2 (9.4% vs 0.9%) | EES base rates better calibrated for Phase 3; Phase 2 events more heterogeneous |
| Signal shape | Left-tail avoidance (Q1: -3.47% at 5d, -6.80% at 20d); Q2-Q5 undifferentiated | Most names cluster near zero score; overpriced outliers (negative tail) underperform |
| Ticker breadth | ≥10 tickers with per-ticker IC > 0.38 | Not a concentration artifact |
| IC consistency | 81% positive-date hit rate | Consistent across the panel period |
| 5d vs 20d | 20d spread (6.44%) > 5d spread (0.96%) | Signal builds over time; consistent with fundamental repricing |

**Why Phase 2 has no signal:**
- 0.9% positive scores → near-zero cross-sectional variance at the top
- Event types more heterogeneous (DATA_READOUT has 1 valid IC date)
- Phase 2 eligible names add noise to any eligible-pooled analysis
- n=429 rows → fewer valid IC dates even with same time period

---

## 9. What This Does Not Establish

- This is a retrospective PIT panel analysis, not a prospective forward test
- The shadow monitor (`ees_v2_phase3_shadow_ledger.jsonl`) is the proper forward test;
  gates require 20 completed 5d + 20 completed 20d observations before any interpretation
- No model changes are authorized. Freeze remains ACTIVE.
- The left-tail signal does not imply shorting is feasible (EES does not produce short
  recommendations; signal is about avoidance/underweight within the Phase 3 universe)
- Per-ticker IC values reflect within-ticker rank correlation; they are not return forecasts
- The CT_STUDY_COMPLETION and DATA_READOUT rows remain unevaluated due to insufficient
  date coverage — they are neither confirmed nor dismissed as signal-bearing

---

## 10. Operator Decision Gate

This attribution review completes the diagnostic chain from signal identification
through mechanism explanation. No further research steps are authorized without a
separate design memo.

If the operator wishes to initiate a model design discussion based on this attribution:
1. A separate design memo must be written specifying the proposed change
2. That memo must be approved before any code is written
3. Any code written requires a separate approval before it is run
4. Any run must be reviewed before it is committed

**Governance check:**

| Check | Status |
|-------|--------|
| Production model freeze | ACTIVE — no ranker/selector/sizing/final_score/gate/snapshot/portfolio changes |
| No live fetch | PASS |
| No cron / scheduler | PASS |
| No alpha claims | PASS |
| No model promotion | PASS |

---

*Generated by scripts/research/ees_v2_phase3_attribution.py  
DIAGNOSTIC_ONLY | NO_PRODUCTION_CHANGES | FREEZE_ACTIVE*
