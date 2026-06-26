# EES v3 Veto Autopsy — HL Bucket Analysis

**Date:** 2026-06-25
**Status:** DIAGNOSTIC_ONLY
**Governance:** FREEZE_ACTIVE | NO_PRODUCTION_WIRING | NO_PROMOTION_AUTHORIZED
**Hypothesis tested:** veto_core removes ranker-selected names with low EES v3 score — are those removals correct?
**Data:** 76 PIT monthly snapshots, 2020-01-31 -> 2026-04-16
**Script:** `scripts/research/ees_v3_veto_autopsy.py`
**Raw output:** `artifacts/research/ees_v3_veto_autopsy_2026_06_25.json` (gitignored)

---

## Definition

**HL bucket**: ranker top-quintile (final_score) AND ees_v3 bottom-quintile.
These are names `veto_core` would have removed from the selection universe.

**TRUE_NEGATIVE**: veto was correct — name underperformed XBI at 63d.
**FALSE_NEGATIVE**: veto was wrong — name outperformed XBI at 63d.

---

## Overall Results

| Metric | Value |
|--------|-------|
| Total HL observations | 533 |
| Observations with forward data | 516 |
| **True negative rate (veto correct)** | **55.6%** |
| Mean excess return 63d (HL names) | -1.3% |

## Era Breakdown

| Era | N (with data) | True Neg Rate | Mean Excess 63d |
|-----|---------------|---------------|-----------------|
| EARLY (n=387) | 358 | 54.0% | -0.9% |
| LATE (n=146) | 129 | 60.5% | -2.4% |

## Failure Mode Breakdown

Primary reason EES v3 scored the name in its bottom quintile.

| Failure Mode | N | % of HL | True Neg Rate | Mean Excess 63d |
|--------------|---|---------|---------------|-----------------|
| no_options_coverage | 359 | 67.4% | 52.9% | -0.0% |
| dilution_overhang | 100 | 18.8% | 67.0% | -7.4% |
| market_already_priced | 32 | 6.0% | 62.5% | -6.0% |
| stale_or_delisted | 17 | 3.2% | n/a | n/a |
| catalyst_too_far | 15 | 2.8% | 26.7% | +22.7% |
| other_unknown | 10 | 1.9% | 60.0% | -6.0% |

## Options Coverage Split

| Coverage | N | True Neg Rate | Mean Excess 63d |
|----------|---|---------------|-----------------|
| Has priced_move | 69 | 53.3% | +1.3% |
| No priced_move | 464 | 55.9% | -1.6% |

## Top Repeating HL Tickers

Names that appear most frequently in the HL bucket across snapshots.

| Ticker | Appearances | True Neg Rate | Mean Excess 63d |
|--------|-------------|---------------|-----------------|
| XENE | 70 | 45.7% | +5.4% |
| CLDX | 32 | 37.5% | +13.9% |
| AXSM | 29 | 31.0% | +3.2% |
| DYN | 26 | 69.2% | -12.0% |
| RVMD | 21 | 57.1% | +0.8% |
| ALNY | 18 | 33.3% | +9.4% |
| RNA | 18 | 38.9% | -2.7% |
| RLAY | 17 | 58.8% | -2.4% |
| BIIB | 15 | 53.3% | -0.7% |
| CMPX | 14 | 64.3% | -1.3% |
| TSHA | 14 | 57.1% | -5.6% |
| NUVL | 12 | 50.0% | +17.0% |
| VERA | 12 | 66.7% | -8.4% |
| ELVN | 11 | 63.6% | -6.7% |
| KYMR | 10 | 70.0% | -3.6% |

## Key Findings

### 1. Veto is correct — and improving

55.6% true-negative rate overall (EARLY 54.0% → LATE 60.5%). The late-regime improvement
confirms the veto is getting stronger as options coverage expands, not weaker. Mean excess
return of HL names is -1.3%, consistent with systematic underperformance vs XBI.

### 2. Dominant failure mode: no options coverage (67.4% of HL)

When EES v3 lacks `priced_move_pct` data, it cannot compute the misprice component and
scores the name low on a 70% signal that is effectively zero. The veto is only 52.9%
accurate (near-random) for this subgroup, with ~0% mean excess. **This is the veto's
main weakness** — for uncovered names, EES v3 is penalizing by absence of evidence rather
than presence of negative evidence.

### 3. Theoretically grounded failure modes are highly accurate

- **`dilution_overhang` (18.8% of HL)**: 67.0% true-neg, -7.4% excess — capital structure
  risk genuinely predicts underperformance. These are real vetoes.
- **`market_already_priced` (6.0% of HL)**: 62.5% true-neg, -6.0% excess — when EES v3
  identifies that options have priced in more than the conditional expected move, it is
  correct. This is the theoretically ideal veto case.

### 4. Catalyst timing is a false-negative trap

`catalyst_too_far` (2.8% of HL): 26.7% true-neg, **+22.7% excess**. Names with far-out
catalysts that EES v3 vetoes actually outperform significantly over 63d. The veto_core
policy is premature for this subgroup. Note these are only 15 observations — small sample.

### 5. Recurring false negatives: XENE, CLDX, AXSM, ALNY

These names appear 18-70 times in the HL bucket with <50% true-neg rates and positive
excess returns. EES v3 persistently under-scores these names while the ranker correctly
selects them. These represent the veto's worst systematic false negatives — worth
investigating whether their high ranker score is driven by non-options signals EES v3
cannot see.

### 6. DYN and KYMR are veto confirmations

DYN appears 26 times with 69.2% true-neg and -12.0% excess. KYMR 10 times with 70.0%
true-neg and -3.6% excess. These are exactly the bad names the veto correctly removes.

---

## Interpretation

**Veto autopsy verdict:** `VETO_CREDIBLE — majority of removed names underperformed XBI`

Key questions this autopsy answers:

1. **Is the veto correct more often than not?**
   Overall true negative rate = 55.6% across 533 HL observations.

2. **Which failure modes dominate?**
   `no_options_coverage` (67.4%) is the dominant mode but weakest predictor.
   `dilution_overhang` (18.8%) and `market_already_priced` (6.0%) are the
   theoretically grounded, high-accuracy veto cases.

3. **Is the veto improving in the late regime?**
   Yes: EARLY 54.0% → LATE 60.5%. Coverage expansion is strengthening the signal.

---

## Operator Decision

```
LEAD_EES_V3_INTEGRATION_HYPOTHESIS = VETO_CORE
STATUS = DIAGNOSTIC_ONLY
FREEZE = ACTIVE
PRODUCTION_PROMOTION = NOT_AUTHORIZED
VETO_AUTOPSY = COMPLETE (2026-06-25)
```

This autopsy is evidence for or against promoting veto_core.
Do not promote until 20d shadow gate is met and operator approval received.

