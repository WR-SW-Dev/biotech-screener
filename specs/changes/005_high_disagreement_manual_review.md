# Spec 5: Manual Review of High-Disagreement Names

**Status**: COMPLETE (2026-03-14)
**Review**: `docs/research/high_disagreement_review_2026-03-14.md`

## Findings

16 names flagged as `market_model_disagreement = high`. Root cause breakdown:

| Root Cause | Count | % |
|------------|-------|---|
| stale_window (catalyst_days > 300 inflating divergence) | 7 | 44% |
| genuine_skepticism (real model-market disagreement) | 5 | 31% |
| data_artifact (archetype z-score mismatch, mode bugs) | 4 | 25% |

## Actions Taken

1. **Pre-filter added**: `catalyst_days <= 180` gate on pos_divergence computation, eliminating stale_window artifacts
2. **5 genuine overlay candidates identified**: ANNX, CMPX, DYN, AURA, CERS
3. **ESPR flagged for investigation**: 16-day catalyst in `far_window` mode (potential mode assignment bug)

## Future Work

- Archetype-aware z-scoring (compute divergence within drug_developer / commercial cohorts)
- ESPR catalyst_mode investigation
