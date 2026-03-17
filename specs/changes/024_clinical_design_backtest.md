# Spec 24: Clinical Design-Feature Backtest + V3 Priors

**Status**: DEFAULT-ON APPROVED
**Date**: 2026-03-16 (opt-in approved) → 2026-03-16 (default-on approved)
**Depends on**: Spec 023 (clinical PIT backfill + outcome labels v2)

## Objective

Determine which trial **design features** (phase, endpoint, enrollment) predict
binary clinical outcomes — quantify survivorship bias — and build v3 priors
with survivorship adjustment as a monitored opt-in candidate.

## Evidence Base

- 1,587 high-confidence CT.gov p-value labels
- 18,689 PIT-safe trial records in catalog
- Composite calibration slope = 0.032 (NOT a clinical predictor)

## Three-Part Analysis

### Part 1: Design-Feature Discrimination

Three additive model specs:
1. `phase_only` → [phase_num] — AUC=0.581
2. `phase_endpoint` → [phase_num, endpoint_hard] — AUC=0.598
3. `multi_feature` → [phase_num, endpoint_hard, enrollment_ordinal] — insufficient (enrollment data missing)

Method: 10-fold stratified CV, bootstrap AUC CI (200 resamples), odds ratios
with SE from full Hessian inverse. Biomarker informational only (n=68).

### Part 2: Survivorship Sensitivity

Three scenarios from catalog lifecycle fields (phases 2/3/4 only):
- **Best-case**: 63.6% (labeled set only)
- **Worst-case**: 20.6% (terminated/withdrawn/completed-no-results = failure)
- **Plausible-case**: 41.5% (terminated = failure, completed-no-results = 50/50)

### Part 3: Forward Utility of V2 Phase Prior

| Baseline | Brier | AUC | Cal. Slope |
|----------|-------|-----|-----------|
| flat_prior | 0.2322 | 0.500 | — |
| wong_reference | 0.2602 | 0.573 | 0.392 |
| v2_empirical | 0.2252 | 0.622 | 0.726 |

## V3 Prior Artifact

**Schema**: `clinical_pos_priors.v3`
**File**: `production_data/clinical_pos_priors_v3.json`

### Survivorship-Adjusted Phase Rates

| Phase | Observed (v2) | Adjusted (v3) | Shrunk (v3) | Wong Ref |
|-------|-------------|--------------|------------|----------|
| Phase 2 | 52.4% | 25.4% | 25.7% | 30.5% |
| Phase 3 | 73.5% | 53.0% | 53.4% | 58.0% |
| Phase 4 | 58.3% | 27.2% | **WONG FALLBACK** | 65.0% |

### Score Translation (v3c — approved)

Calibration history (2026-03-13 snapshot, unknown→preclinical fallback):
- v3a (down=-4, up=+1): top60=91.7%, max_shift=72, REJECTED (proxy; tail degenerate)
- v3b (down=-3, up=+1): top60=91.7%, max_shift=59, HOLD (proxy; still above 30)
- **v3c (down=-2, up=+0): APPROVED** — full DEM compare passes all gates

| Phase | V1 (Wong) | V3 | Delta |
|-------|-----------|-----|-------|
| phase 3 | 25 | 24 | -1 |
| phase 2/3 | 22 | 21 | -1 |
| phase 2 | 18 | 16 | -2 |
| phase 1/2 | 12 | 11 | -1 |
| phase 1 | 8 | 6 | -2 |
| preclinical | 3 | 2 | -1 |

Max cross-phase differential: 1pt. No adjacent bucket widens beyond today.

### Full DEM Compare (2026-03-13)

| Gate | Value | Threshold | Status |
|------|-------|-----------|--------|
| Top-60 overlap | 98.3% | >= 90% | PASS |
| Max shift (all) | 9 | <= 30 | PASS |
| Max shift (top-100) | 9 | <= 30 | PASS |
| A-tier downgrades | 0 | 0 | PASS |
| Mean shift | 0.72 | advisory | — |
| Median shift | 0 | advisory | — |
| B-tier big shifts | 0 | advisory | — |
| Unknown-phase shift | 0 | advisory | — |

Phase cohort behavior:
- Phase 3 (n=115): mean +0.15, max 7
- Phase 2 (n=45): mean +0.20, max 9
- Phase 1 (n=17): mean -1.18, max 7
- Unknown (n=15): exactly 0

Largest movers all C-tier, ranks 75-107. A-tier and B-tier untouched.

### Production Controls

- `--phase-scores-v3` opt-in flag (mutually exclusive with `--phase-scores-v2`)
- Phase 4 forced to Wong fallback (composition-distorted)
- Metadata stamps `phase_scores_version: "v3"`
- Three artifact fields: `phase_notes`, `fallback_overrides`, `survivorship_assumptions`

## Acceptance Checklist

- [x] `--phase-scores-v3` exists and is fully rollback-safe
- [x] Phase 4 uses forced Wong fallback
- [x] Metadata stamps `phase_scores_version: "v3"`
- [x] Full DEM compare shows bounded rank impact (top-60 overlap 98.3%, max shift 9)
- [x] A-tier names stable (0 downgrades, 0 upgrades)
- [x] All movers explainable by phase-table change (C-tier Phase 2 names)
- [x] Unknown-phase names treated as preclinical (no artifact)
- [x] Default behavior is now v3 (survivorship-adjusted)
- [x] `--phase-scores-v1` rollback to Wong available
- [x] 9-date multi-date aggregate compare passed all promotion gates

## Approval

**DEFAULT-ON APPROVED** (2026-03-16)

9-date aggregate compare (multi-date window) passed all promotion gates:

| Gate | Value | Threshold | Status |
|------|-------|-----------|--------|
| Mean top-60 overlap | 99.43% | >= 93% | PASS |
| Min top-60 overlap | 98.3% | >= 90% | PASS |
| Max rank shift | 13 | <= 30 | PASS |
| Worst A-tier regression | 0 | 0 | PASS |
| Flagged dates | 0 | 0 | PASS |

Rollback: `--phase-scores-v1` restores Wong reference scores.

**Survivorship caveat**: Underlying priors use plausible-case survivorship
adjustment (41.5%). This is handled by bounded translation (down=-2, up=+0)
and Phase 4 Wong fallback — both of which limit tail sensitivity to the
survivorship estimate.
