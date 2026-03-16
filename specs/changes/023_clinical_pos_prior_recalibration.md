# Spec 23: Clinical PoS Prior Recalibration

**Status**: HOLD — comparison shows large prior shifts (+17pp median), integration path undefined
**Date**: 2026-03-16
**Depends on**: clinical PIT backfill, CT.gov outcome labels v2, DEM clinical prior path

## Objective

Recalibrate the DEM's clinical PoS prior using PIT-safe, high-confidence
clinical outcome labels from this universe. Creates a bounded clinical prior
table. Does NOT replace the ranking composite or introduce a new classifier.

## Evidence Base

- 1,587 high-confidence CT.gov p-value labels
- Phase 2: 52.2%, Phase 3: 73.2% (21pp lift)
- OS endpoint: 57.7%, Other: 65.9%
- Biomarker: 51.4% (n=70, confounded)
- Composite calibration slope: 0.032 (not a clinical predictor)

## Scope

In: deterministic prior table, bounded endpoint modifiers, DEM integration
Out: multivariate classifier, completion-proxy labels, biomarker penalty

## Shrinkage Rule

shrunk_rate = (n * raw_rate + k * reference_rate) / (n + k)
k=25 strong, k=50 moderate, k=100 sparse

## Biomarker Policy

Do NOT apply biomarker negative effect. n=70, likely selection bias.
Neutral until controlled follow-up.

## Acceptance Criteria

1. clinical_pos_priors_v2.json exists with PIT-safe labels only
2. Contains global, phase, endpoint priors with support metadata
3. DEM consumes safely with fallback
4. Tests cover generation, shrinkage, integration
