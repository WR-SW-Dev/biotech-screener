# Alt 10 — No-Ranker Selector_Score Comparator
**Date:** 2026-05-08  
**Spec:** spec_094  
**Status:** DESCRIPTIVE ONLY — no significance claims, no production changes, no demotion of ranker  
**Regime caveat:** All April 2026 snapshots carry [REGIME_CAVEAT]: XBI selloff 04-21→04-25, cohort change 04-25, 13F quarantine onset 04-25

---

## 1. Snapshot Inventory

| Date | Divergent | Regime ⚠ | n_sel_only | n_ran_only | SelRet | RanRet | Diff | Sel Wins |
|------|-----------|-----------|------------|------------|--------|--------|------|----------|
| 2026-04-17 | YES | | 10 | 10 | -0.048 | -0.016 | -0.032 | no |
| 2026-04-20 | YES | | 12 | 12 | -0.036 | +0.001 | -0.038 | no |
| 2026-04-21 | YES | ⚠ | 13 | 13 | +0.012 | +0.022 | -0.010 | no |
| 2026-04-22 | YES | ⚠ | 13 | 13 | -0.010 | +0.039 | -0.048 | no |
| 2026-04-23 | YES | ⚠ | 13 | 13 | -0.009 | +0.016 | -0.025 | no |
| 2026-04-24 | YES | ⚠ | 13 | 13 | -0.007 | +0.022 | -0.029 | no |
| 2026-04-25 | YES | ⚠ | 11 | 11 | -0.005 | +0.019 | -0.024 | no |
| 2026-04-27 | YES | | 12 | 12 | +0.034 | +0.007 | +0.027 | YES |
| 2026-04-28 | YES | | 11 | 11 | +0.001 | -0.011 | +0.012 | YES |
| 2026-04-29 | YES | | 12 | 12 | +0.026 | -0.032 | +0.057 | YES |
| 2026-04-30 | YES | | 12 | 12 | +0.019 | -0.040 | +0.060 | YES |
| 2026-05-01 | YES | | 11 | 11 | n/a | n/a | n/a | n/a |
| 2026-05-04 | YES | | 13 | 13 | n/a | n/a | n/a | n/a |
| 2026-05-05 | YES | | 12 | 12 | n/a | n/a | n/a | n/a |
| 2026-05-06 | YES | | 12 | 12 | n/a | n/a | n/a | n/a |
| 2026-05-07 | YES | | 12 | 12 | n/a | n/a | n/a | n/a |
| 2026-05-08 | YES | | 12 | 12 | n/a | n/a | n/a | n/a |

**SelRet / RanRet:** median excess_return_5d across selector-only / ranker-override tickers respectively  
**Diff:** SelRet − RanRet (positive = selector-only outperformed)  
**Forward returns available:** 11/17 snapshots (05-01 to 05-08 are within 5d window; not yet complete)

---

## 2. Key Finding: All 17 Snapshots Are Divergent

The ranker always changes the top-30 composition relative to the selector alone. There are **zero identical snapshots**. Per-snapshot overlap: 10–13 tickers differ (selector-only) vs. the same count added by ranker. This confirms the ranker is an active reordering mechanism, not a pass-through.

---

## 3. Return Comparison Summary

### Pooled (all 11 return-covered snapshots)
- **Selector wins:** 4/11
- **Pooled median differential:** −0.024 (selector-only median WORSE than ranker-override by 2.4pp per snapshot)

### Clean window — 04-17, 04-20, 04-27 through 04-30 (6 snapshots)
- **Selector wins:** 4/6
- **Pooled median differential:** +0.020 (selector-only median BETTER by 2.0pp)

### Regime window — 04-21 through 04-25 [REGIME_CAVEAT] (5 snapshots)
- **Selector wins:** 0/5
- **Pooled median differential:** −0.025 (ranker-override markedly better)

---

## 4. What Drove the Regime-Window Differential

The 0/5 regime result is primarily explained by composition, not ranker signal quality:

**Ranker-override bucket (regime):** AXSM median +0.132 across 5 snapshots (PDUFA event 2026-04-30; name was in ranker top-30 during the selloff week). MIRM +0.068, NBIX +0.044, ARGX +0.026, ALKS +0.024 — larger, more defensive names that held value during the sector drawdown. ERAS (ranker-override) had −0.515 median but was a single-ticker outlier below the median in each snapshot.

**Selector-only bucket (regime):** NAMS −0.059, VERA −0.045, DYN −0.026, PTCT −0.026 — smaller, higher-beta names that fell with XBI. KALV selector-only with +0.379 median was a large positive outlier (catalyst event), but the per-snapshot median was dragged down by the majority of beta-sensitive names.

**Interpretation:** During the XBI selloff, the ranker's `financial_score` negative weight and `coinvest_score_z` cap appear to have shifted composition toward larger, more liquid names (AXSM, MIRM, NBIX) that are less correlated with XBI beta. This is not evidence the ranker is generating alpha — it is regime-correlated composition shift. The ranker did not "predict" the selloff; the composition happened to be more defensive.

**This finding is NOT actionable.** Five selloff snapshots cannot distinguish regime correlation from signal quality.

---

## 5. What Drove the Clean-Window Differential

**Clean window (4/6 selector wins):** The two snapshots where the selector lost (04-17, 04-20) had ERAS in the ranker-override bucket doing well (+0.170, +0.164). The four snapshots where the selector won (04-27 to 04-30) had ERAS doing very poorly (−0.484 on 04-27 alone), which dragged the ranker-override median down, and KALV in the selector-only bucket doing very well (+0.396, +0.368).

The clean-window result is heavily influenced by two name-specific events:
- **ERAS** (consistently in ranker-override): went from strong performer pre-selloff to severe negative post-selloff (−0.484 on 04-27 is a single-name event, likely related to the ERAS-out / RVMD-in cohort shift that occurred 04-25)
- **KALV** (in selector-only on 04-27 and 04-28): catalyst event with +0.39 excess return; single-name positive outlier

**With n=6 clean snapshots and results driven by 2 individual names, no directional conclusion is valid.**

---

## 6. Regime-Window Confounding — Assessment

The pooled result (4/11, diff = −0.024) is dominated by the regime window. The regime-window composition effect is qualitatively understandable but not a signal quality verdict: the ranker's selection of AXSM during a PDUFA week is a calendar-coincidence, not a systematic feature. ERAS being in the ranker-override bucket during regime with −51.5% was a large governance-related effect (the ERAS-to-RVMD transition that occurred at the cohort change on 04-25 and is documented as a quarantine artifact).

The pooled result is therefore non-interpretable as a ranker quality verdict.

---

## 7. Observation Count Context

- 69 (ticker, date) observations in selector-only clean window
- 69 (ticker, date) observations in ranker-override clean window
- 18 unique tickers in each bucket (clean)
- Many tickers appear multiple consecutive days — observations are NOT independent

The effective independent sample size is substantially less than 69. At the per-snapshot level (n=6 clean), the test has near-zero statistical power. Per Spec 094, no p-values or t-statistics are reported.

---

## 8. Verdict

**INCONCLUSIVE — consistent with OBSERVE posture.**

The data is insufficient to determine whether the ranker adds or detracts value relative to the selector:

1. All 17 snapshots are divergent (ranker is an active reordering mechanism)
2. Pooled result: ranker-override slightly better, BUT dominated by regime confounding
3. Clean-window result: selector slightly better (4/6), BUT driven by 2 individual names (ERAS, KALV) and n=6 has no statistical power
4. 6 snapshots with no forward returns yet (05-01 to 05-08)

This result neither strengthens nor weakens the OBSERVE posture established at the IC first read (2026-05-08). The ranker is active; its marginal value remains unknown at current sample sizes.

**For a powered verdict:** Gate 4 (n≥30 HIT/MISS) + Gate 7 (top-60 IC scope) + formal block-bootstrap IC test within the top-60 cohort. Earliest: ~2026-07-15.

---

## 9. Names to Watch

The following tickers appeared most frequently in the divergent bucket and drove the results. These are the names where selector vs. ranker disagreement is most persistent:

**Consistently in ranker-override (ranker prefers, selector doesn't):** AXSM, ERAS, MIRM, NBIX, ARGX, ALKS, ORKA, INSM  
**Consistently in selector-only (selector prefers, ranker demotes):** KALV, JBIO, NGNE, NAMS, VERA, DYN, CTNM, CGEM, MLTX, IRON

These name patterns are worth monitoring as new snapshots accumulate. If ERAS remains in ranker-override and continues to underperform, that is the strongest single-name signal in the dataset — but 17 snapshots is not enough to distinguish a signal from a name-specific event sequence.

---

*No significance claims. No demotion or promotion of any ranker alternative. No production changes. Descriptive analysis per Spec 094.*  
*Forward return coverage: 11/17 snapshots. Remaining 6 (05-01 to 05-08) will complete the 5d window by 2026-05-13.*
