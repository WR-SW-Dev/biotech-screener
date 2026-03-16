# Spec 24: Clinical Design-Feature Backtest

**Status**: IN_PROGRESS
**Date**: 2026-03-16
**Depends on**: Spec 023 (clinical PIT backfill + outcome labels v2)

## Objective

Determine which trial **design features** (phase, endpoint, enrollment) predict
binary clinical outcomes — and quantify how survivorship bias inflates the
63.3% global success rate.

## Evidence Base

- 1,587 high-confidence CT.gov p-value labels
- 18,689 PIT-safe trial records in catalog
- Composite calibration slope = 0.032 (NOT a clinical predictor)

## Three-Part Analysis

### Part 1: Design-Feature Discrimination

Three additive model specs:
1. `phase_only` → [phase_num]
2. `phase_endpoint` → [phase_num, endpoint_hard]
3. `multi_feature` → [phase_num, endpoint_hard, enrollment_ordinal]

Method: 10-fold stratified CV, bootstrap AUC CI (200 resamples), odds ratios
with SE from inverse Hessian diagonal. Biomarker informational only (n=70).

### Part 2: Survivorship Sensitivity

Three scenarios from catalog lifecycle fields (phases 2/3/4 only):
- **Best-case**: labeled set only (current 63.3%)
- **Worst-case**: terminated/withdrawn = failure, completed-no-results = failure
- **Plausible-case**: terminated/withdrawn = failure, completed-no-results = 50/50

### Part 3: Forward Utility of V2 Phase Prior

Three baselines on the 1,587 labeled set:
1. Flat prior (global 63.3%)
2. Wong et al. reference (REFERENCE_PRIORS)
3. V2 shrunk phase+endpoint (production artifact)

Metrics: Brier score, calibration slope, reliability bins (10), AUC.

## Schema

`clinical_design_backtest.v1`

## Output

- `data/research/clinical_design_backtest.json`
- `data/research/clinical_design_backtest.md`

## Acceptance Criteria

- multi_feature AUC > phase_only AUC
- worst_case success rate << 63.3%
- v2_empirical Brier < flat_prior Brier
