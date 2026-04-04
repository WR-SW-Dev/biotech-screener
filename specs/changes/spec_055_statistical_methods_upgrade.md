# Spec 055 — Statistical Methods Upgrade Pass

**Status**: COMPLETE — 6 methods production-ready, promotion checklist v2 established
**Date**: 2026-04-04
**Predecessor**: Specs 049-054 (signal framework, selector-ranker, ranker v2, options study, execution study)

## Motivation

The biotech screener has a mature signal evaluation pipeline (signal cards, bundle tests,
ablation, year/regime splits) but relies on naive t-statistics and uncorrected p-values.
With 37+ options signals, 12 execution signals, insider bundles, and ongoing mining, the
risk of false promotion from multiple testing is real. The promotion bar needs upgrading.

Current stack: institutional is dominant, risk is second, clinical hurts, options/insider
are noise. This spec does NOT search for more alpha. It upgrades the **statistical QA
layer** so future promotions require rigorous evidence.

## Methods (in priority order)

### 1. Fama-MacBeth Cross-Sectional Regression

**Question**: Does a signal have incremental predictive power after controlling for
incumbent signals?

**Method**: For each monthly snapshot, regress forward return on candidate signal(s)
plus controls. Collect monthly coefficient estimates. Compute time-series mean, t-stat,
and Newey-West standard errors across months.

**Models**:
- Univariate: candidate only
- Controls only: coinvest_score_z + inst_delta_z + financial_score
- Candidate + controls (incremental test)
- Block models: institutional, risk, clinical, options, execution

**PIT**: Uses research panel (already PIT-safe). Forward returns are PIT by construction.

**Acceptance**: A signal survives if its coefficient t-stat ≥ 1.96 in the candidate +
controls model (two-sided) with Newey-West SEs.

### 2. Block Bootstrap on Portfolio Returns

**Question**: Is a backtest result robust to serial dependence and fat tails?

**Method**: Moving block bootstrap (block length ~6 months) on monthly excess return
series. Compute bootstrapped mean, 95% CI, P(strategy > 0), P(challenger > baseline).

**Apply to**: Selector bundle deltas, ranker comparisons, production vs challenger.

**Acceptance**: A result is robust if bootstrapped 95% CI excludes zero.

### 3. Multiple-Testing Correction

**Question**: Would this result survive after accounting for how many things we tested?

**Methods**:
- Benjamini-Hochberg FDR (q < 0.10)
- White's Reality Check / max-stat bootstrap for families of tests

**Families**: Signal card sweeps, selector bundle sweeps, ranker bundle sweeps,
per-study groupings (options, execution, insider).

**Acceptance**: A signal passes if BH q-value < 0.10 within its testing family.

### 4. Pairwise Score Calibration

**Question**: Are ranker scores calibrated enough for confidence-weighted sizing?

**Method**: Reliability curves, Brier score, expected calibration error (ECE).
Compare raw vs isotonic/Platt-calibrated scores. Slice by regime, cap bucket,
catalyst proximity.

**Acceptance**: Calibrated enough for ranking if ECE < 0.10; for sizing if ECE < 0.05.

### 5. Leave-One-Slice-Out Robustness

**Question**: Is a signal carried by one narrow pocket?

**Method**: Re-evaluate selector/ranker performance after dropping each slice (year,
regime, cap bucket, catalyst family). Report worst-slice, best-slice, stability verdict.

**Acceptance**: Stable if worst-slice delta is still positive and within 50% of
full-sample delta.

### 6. Survival / Hazard Scaffold

**Question**: Can we model catalyst timing quality instead of hand-waving it?

**Method**: Cox proportional hazards or Kaplan-Meier for time-to-catalyst-resolution
conditioned on execution features, update cadence, date confidence.

**Scope**: Research scaffold only. Not production-ready.

## Architecture

```
common/stats/
  __init__.py
  cross_sectional.py    — OLS, Fama-MacBeth, Newey-West
  bootstrap.py          — block bootstrap, stationary bootstrap
  multiple_testing.py   — BH FDR, White's Reality Check
  calibration.py        — reliability curves, Brier, ECE, Platt, isotonic
  robustness.py         — leave-one-slice-out harness
  survival.py           — Cox PH, Kaplan-Meier scaffold

scripts/research/
  statistical_methods_upgrade.py  — main runner

tests/
  test_stats_cross_sectional.py
  test_stats_bootstrap.py
  test_stats_multiple_testing.py
  test_stats_calibration.py
  test_stats_robustness.py

output/statistical_methods/
  cross_sectional_results.json
  cross_sectional_summary.md
  bootstrap_results.json
  bootstrap_summary.md
  multiple_testing_results.json
  multiple_testing_summary.md
  calibration_results.json
  calibration_memo.md
  robustness_results.json
  robustness_summary.md
  survival_scaffold_memo.md
  final_operator_memo.md
```

## Promotion Checklist (proposed)

After this spec, promoting any signal requires:

1. ✅ Signal card: selector Δ > 0, ranker IC > 0, coverage ≥ 40%
2. ✅ Fama-MacBeth: incremental coefficient t ≥ 1.96 with Newey-West SEs
3. ✅ Bootstrap: 95% CI on portfolio delta excludes zero
4. ✅ Multiple-testing: BH q-value < 0.10 within testing family
5. ✅ Robustness: worst-slice delta still positive
6. ✅ Year stability: negative in ≤ 1 of 6 years

## Deliverables

1. Design doc (this spec)
2. Statistical utilities package (`common/stats/`)
3. Tests for all utilities
4. Runner script + output artifacts
5. Final operator memo with blunt verdicts
