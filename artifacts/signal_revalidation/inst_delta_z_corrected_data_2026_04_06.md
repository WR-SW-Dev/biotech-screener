# inst_delta_z Revalidation — Post-CUSIP Fix

**Date:** 2026-04-06
**Trigger:** CUSIP fix corrected inst_delta_z for 70+ tickers. Rerun required to check if signal improved.
**Verdict:** WEAKER. Signal diluted by phantom-exit bias removal. Coinvest-only remains best selector.

## Old vs New (corrected data)

| Metric | inst_delta_z (OLD) | inst_delta_z (NEW) | coinvest_z (NEW) |
|--------|-------------------|-------------------|-----------------|
| Selector Δ (pp) | +0.80 | +0.45 | +0.83 |
| Selector t-stat | ~1.5 | 1.29 | 2.20 |
| Selector hit% | ~52% | 46% | 58% |
| Ranker IC | +0.077 | +0.05 | +0.08 |
| Ranker IC t | ~1.8 | 2.09 | 2.93 |
| Signal card decision | SHADOW | SHADOW | PROMOTE |

## Bundle Comparison (20d, top-30, corrected data)

| Bundle | Δ pp | t-stat | hit% |
|--------|------|--------|------|
| B5 coinvest only | +0.83 | 2.20 | 58% |
| B6 coinvest + inst_delta (65/35) | +0.75 | 2.13 | 55% |
| inst_delta_z standalone | +0.45 | 1.29 | 46% |

B6 is now WORSE than B5. inst_delta dilutes the selector.

## Why it got weaker

The old (broken) inst_delta_z contained phantom "exits" — sponsors who appeared to leave
because their holdings had blank tickers in the PIT cache. These phantom exits were
correlated with subsequent returns (tickers with "lost" sponsors were smaller, more
volatile names that happened to outperform in the sample). With corrected CUSIPs, those
phantom patterns disappear and the true delta signal is weaker.

## Remaining value

inst_delta_z retains mild within-cohort ranking power (IC=0.05, t=2.09 within top-30).
It is already used this way in the 2-feature pairwise ranker (coinvest_z + financial_score).
No change to the ranker is warranted.

## Closure

- inst_delta_z = SHADOW / complement only
- Not a standalone selector signal
- Does not improve the selector on corrected data
- Alpha freeze confirmed correct
- No second orthogonal selector signal exists in the current data
