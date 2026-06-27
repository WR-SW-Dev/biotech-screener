# Phase 3 Component Attribution

> Classification: `PHASE3_COMPONENT_ATTRIBUTION_DIAGNOSTIC_NO_MODEL_CHANGE`
> Date: 2026-06-26
> Scope: Diagnostic only. No model, ranker, selector, or production change.

---

## Purpose

For each Phase 3 drag name (CELC, DRUG, PRAX, TYRA, ABVX), determine which
model components promoted it into the verified top-30 basket, and whether those
components behaved differently for winners (TNGX, ALKS, SYRE).

---

## Model Architecture (ranker_v2)

```
final_score = sigmoid(w0 * coinvest_z + w1 * financial_z + bias)
  w0 (coinvest_score_z) = +0.020   [higher institutional interest = higher score]
  w1 (financial_score)  = −0.053   [lower financial health  = higher score]
  bias                  =  0.502
```

The **negative financial weight** is the key: names with below-average financial
health receive a positive contribution. This is the structural amplifier.

---

## Per-Ticker Attribution

### CELC (LOSER)

| Metric | Value |
|--------|------:|
| Appearances in Phase 3 | 16 |
| Mean rank | 22.4 |
| Mean 5d return | -0.123 |
| Mean coinvest_z | -0.174 |
| Mean financial_z | -0.475 |
| Coinvest contribution | -0.0035 |
| Financial contribution | +0.0253 |
| Mean ees_v3 | -0.898 |
| Primary driver | financial_stress |
| CF rank if fi=0 | 28 |
| CF rank if ci=0 | 21 |
| Rank drop if primary=0 | +5.1 |
| **Failure mode** | **EES_VETO_FAILED** |

*Evidence: ees_v3_score=-0.898 (strongly negative) flagged financing risk; mean_ret=-0.123 confirms; ranker_v2 has no ees_v3 input; financial stress (fi_z=-0.475, fi_contrib=0.0253) also contributed*

### DRUG (LOSER)

| Metric | Value |
|--------|------:|
| Appearances in Phase 3 | 13 |
| Mean rank | 9.8 |
| Mean 5d return | -0.107 |
| Mean coinvest_z | -0.188 |
| Mean financial_z | -1.437 |
| Coinvest contribution | -0.0038 |
| Financial contribution | +0.0766 |
| Mean ees_v3 | +0.270 |
| Primary driver | financial_stress |
| CF rank if fi=0 | 29 |
| CF rank if ci=0 | 9 |
| Rank drop if primary=0 | +18.8 |
| **Failure mode** | **FINANCING_UNDER_PENALIZED** |

*Evidence: fi_z=-1.437 (financially stressed; weight=-0.053 → promoted); fi_contrib=0.0766 dominates; mean_ret=-0.107; counterfactual rank if fi_zeroed: +18.8 positions worse*

### PRAX (LOSER)

| Metric | Value |
|--------|------:|
| Appearances in Phase 3 | 16 |
| Mean rank | 11.4 |
| Mean 5d return | -0.074 |
| Mean coinvest_z | +1.206 |
| Mean financial_z | -0.725 |
| Coinvest contribution | +0.0241 |
| Financial contribution | +0.0387 |
| Mean ees_v3 | -0.072 |
| Primary driver | financial_stress |
| CF rank if fi=0 | 21 |
| CF rank if ci=0 | 17 |
| Rank drop if primary=0 | +10.1 |
| **Failure mode** | **UNEXPLAINED** |

*Evidence: ci_z=1.206, fi_z=-0.725, ret=-0.074; no dominant single cause*

### TYRA (LOSER)

| Metric | Value |
|--------|------:|
| Appearances in Phase 3 | 13 |
| Mean rank | 24.2 |
| Mean 5d return | -0.076 |
| Mean coinvest_z | +0.128 |
| Mean financial_z | -0.256 |
| Coinvest contribution | +0.0026 |
| Financial contribution | +0.0136 |
| Mean ees_v3 | -0.159 |
| Primary driver | financial_stress |
| CF rank if fi=0 | 28 |
| CF rank if ci=0 | 25 |
| Rank drop if primary=0 | +3.5 |
| **Failure mode** | **UNEXPLAINED** |

*Evidence: ci_z=0.128, fi_z=-0.256, ret=-0.076; no dominant single cause*

### ABVX (LOSER)

| Metric | Value |
|--------|------:|
| Appearances in Phase 3 | 15 |
| Mean rank | 14.9 |
| Mean 5d return | -0.064 |
| Mean coinvest_z | +0.586 |
| Mean financial_z | -0.642 |
| Coinvest contribution | +0.0117 |
| Financial contribution | +0.0342 |
| Mean ees_v3 | -0.983 |
| Primary driver | financial_stress |
| CF rank if fi=0 | 24 |
| CF rank if ci=0 | 18 |
| Rank drop if primary=0 | +9.4 |
| **Failure mode** | **EES_VETO_FAILED** |

*Evidence: ees_v3_score=-0.983 (strongly negative) flagged financing risk; mean_ret=-0.064 confirms; ranker_v2 has no ees_v3 input; financial stress (fi_z=-0.642, fi_contrib=0.0342) also contributed*

### TNGX (WINNER)

| Metric | Value |
|--------|------:|
| Appearances in Phase 3 | 16 |
| Mean rank | 20.2 |
| Mean 5d return | +0.113 |
| Mean coinvest_z | +1.714 |
| Mean financial_z | +0.083 |
| Coinvest contribution | +0.0343 |
| Financial contribution | -0.0045 |
| Mean ees_v3 | -0.279 |
| Primary driver | coinvest_signal |
| CF rank if fi=0 | 19 |
| CF rank if ci=0 | 28 |
| Rank drop if primary=0 | +7.6 |
| **Failure mode** | **WINNER_OFFSET** |

*Evidence: TNGX positive return offset — used as comparison baseline*

### ALKS (WINNER)

| Metric | Value |
|--------|------:|
| Appearances in Phase 3 | 16 |
| Mean rank | 18.1 |
| Mean 5d return | +0.065 |
| Mean coinvest_z | +0.478 |
| Mean financial_z | -0.457 |
| Coinvest contribution | +0.0096 |
| Financial contribution | +0.0244 |
| Mean ees_v3 | +0.862 |
| Primary driver | financial_stress |
| CF rank if fi=0 | 26 |
| CF rank if ci=0 | 21 |
| Rank drop if primary=0 | +7.4 |
| **Failure mode** | **WINNER_OFFSET** |

*Evidence: ALKS positive return offset — used as comparison baseline*

### SYRE (WINNER)

| Metric | Value |
|--------|------:|
| Appearances in Phase 3 | 15 |
| Mean rank | 5.9 |
| Mean 5d return | +0.043 |
| Mean coinvest_z | -0.318 |
| Mean financial_z | -1.784 |
| Coinvest contribution | -0.0064 |
| Financial contribution | +0.0951 |
| Mean ees_v3 | +1.438 |
| Primary driver | financial_stress |
| CF rank if fi=0 | 29 |
| CF rank if ci=0 | 6 |
| Rank drop if primary=0 | +23.3 |
| **Failure mode** | **WINNER_OFFSET** |

*Evidence: SYRE positive return offset — used as comparison baseline*

---

## Loser vs Winner Comparison

| Metric | Losers (avg) | Winners (avg) |
|--------|------------:|---------------:|
| Mean 5d return | -0.089 | +0.074 |
| Mean coinvest_z | +0.312 | +0.625 |
| Mean financial_z | -0.707 | -0.719 |
| Mean ees_v3 | -0.368 | +0.674 |
| Mean clinical_score | 36.2 | 57.1 |
| Mean momentum_score | 48.8 | 83.6 |

---

## Structural Finding

financial_score has a negative model weight (−0.053). Names with below-cohort-average financial health (fi_z < 0) receive a POSITIVE financial contribution to ranker_v2_score. This promotes both winners (SYRE fi_z≈−1.7) and losers (DRUG fi_z≈−1.4) equally. ranker_v2 cannot discriminate between financially-stressed names that have strong catalysts and those that do not.

ees_v3_score provides a financing/overpricing signal but is not an input to ranker_v2. For CELC (ees_v3=−1.15) and ABVX (ees_v3=−1.21), the EES signal correctly identified risk but had no path to suppress rank.

---

## BEAR Sensitivity

PHASE3_CORRECTED_REGIME_RANKING_REPLAY confirmed 16/16 Phase 3 dates produce identical top-30 under corrected BEAR regime. Module-5 BEAR weights apply only to composite_score, which is NOT the production sort key in pairwise_minimal mode (final_score = ranker_v2_score). Component attribution is regime-invariant for this model.

BEAR module-5 weights (momentum −0.562, financial −0.245, valuation −0.184, clinical +0.009) would have depressed composite_score for momentum-heavy names like TNGX (momentum=91pp on May 18). But composite_score is not the decision key.

**Conclusion:** Component attribution is regime-invariant. The failure modes
documented here would have been identical under correctly-classified BEAR.

---

## Failure Mode Summary

- **EES_VETO_FAILED**: CELC, ABVX
- **FINANCING_UNDER_PENALIZED**: DRUG
- **UNEXPLAINED**: PRAX, TYRA

---

## Governance Verdict

```
Classification:             PHASE3_COMPONENT_ATTRIBUTION_DIAGNOSTIC_NO_MODEL_CHANGE
Model change:               NO
Ranker change:              NO
Selector change:            NO
Regime change:              NO
Snapshot write:             NO (output to artifacts/autopsy/ only)
Production wiring:          NO

Failure modes identified:
  EES_VETO_FAILED: CELC, ABVX
  FINANCING_UNDER_PENALIZED: DRUG
  UNEXPLAINED: PRAX, TYRA

Primary structural issue:
  financial_score weight = −0.053 promotes financially stressed names
  without discriminating catalyst quality. ees_v3 signal exists but
  is not an input to ranker_v2, so financing risk cannot suppress rank.
```
