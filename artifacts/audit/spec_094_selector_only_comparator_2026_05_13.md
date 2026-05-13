# Spec 094 Audit — Selector-Only Comparator

**Date**: 2026-05-13  
**Status**: ANALYSIS COMPLETE  
**Classification**: **RANKER_UNPROVEN** (insufficient forward-return sample; membership/overlap evidence shows churn but no return validation)

---

## Executive Summary

The production ranker makes **significant membership changes** vs selector-only ordering (~42% Jaccard overlap), and those changes are consistent with **INTENTIONAL_STRESS_UPSIDE logic confirmed in Spec 093**:

- Ranker **adds** financially stressed names (lower financial_score: 24.5 vs 47.4)
- Ranker **adds** lower-conviction institutional names (coinvest_z: 0.55 vs 0.95)
- Ranker **removes** stable, well-capitalized names

**However**, forward-return evidence is **insufficient** (6 resolved outcomes of 69 post-PIT postmortems, 8% coverage). Cannot yet classify ranker as adding value or being competitive without more forward data.

---

## Scope & Comparators

**Analysis universe**: Post-PIT snapshots (2026-04-20 onwards)  
**Snapshots analyzed**: 19 post-PIT eligible datasets  
**Top-N cohort**: Top-30 by final score (ranker) vs top-30 by selector_score (selector-only)

**Comparators**:
1. **Production Ranker** — Final score from current 2-feature pairwise model + coinvest weight cap
2. **Selector-Only** — Top-30 by selector_score (ignoring ranker adjustment)
3. **Coinvest-Binary** — Not yet tested (would require separate rank-by-binary-gate pass/fail)

---

## Data Constraints & Limitations

### Forward Return Availability
- **Post-PIT postmortems**: 69 records across 11 snapshot dates
- **T+5 coverage**: 6 outcomes resolved (8.7%), too sparse for IC or return analysis
- **Implication**: Cannot validate whether ranker-added names outperform selector-only alternatives on forward returns

### Snapshot-Postmortem Alignment
- Postmortems link to original snapshot_dates, not analysis dates
- Most post-PIT postmortems reference 2026-04-29 and 2026-04-30 (24 events from 2 days)
- Recent snapshots (2026-05-07+) have insufficient postmortem data for outcome validation

### Key Metrics Limited
- Hit rate / forward returns: INSUFFICIENT_SAMPLE
- Drawdown / risk-adjusted return: No postmortem drawdown fields
- Catalyst exposure: Can extract, but no outcome linkage yet

---

## Results

### Membership Comparison

| Metric | Mean (19 snapshots) | Description |
|--------|-------------------|-------------|
| **Jaccard Overlap** | 42.7% | Only ~43% of top-30 are same between methods |
| **Overlap Count (top-30)** | 18 / 30 names | 12 added, 12 removed by ranker vs selector-only |
| **Added by Ranker** | 12.1 names / snapshot | Names in ranker top-30 but not selector top-30 |
| **Removed by Ranker** | 12.1 names / snapshot | Names in selector top-30 but not ranker top-30 |
| **Churn Rate** | ~40% | Significant reordering |

### Financial Profile of Ranker Changes

| Signal | Added by Ranker | Selector-Only Set | Difference |
|--------|-----------------|-------------------|-----------|
| **financial_score** (Module 5 rank-norm) | 24.5 | 47.4 | -22.9 (22.5 pp lower) |
| **coinvest_score_z** | 0.55 | 0.95 | -0.41 (lower inst quality) |
| **Interpretation** | Financially stressed, lower sponsor conviction | Financially stable, higher sponsor conviction | Ranker systematically prefers stress |

**Validation**: Spec 093 classified financial_score as INTENTIONAL_STRESS_UPSIDE. This overlap/churn data confirms the ranker is **executing the stress-upside thesis operationally**: it removes stable names and adds stressed names.

### Forward Return Evidence

| Cohort | T+5 Count | Hit Rate | Median Return | Limitation |
|--------|-----------|----------|---------------|-----------|
| **Selector-Only Top-30** | 0 | — | — | No postmortem data yet |
| **Ranker Top-30** | 0 | — | — | No postmortem data yet |
| **Added by Ranker** | 0 | — | — | No postmortem data yet |
| **Post-PIT Postmortem Total** | 6 / 69 | — | — | 8.7% T+5 coverage; insufficient for IC |

**Status**: Forward-return validation is **blocked by data sparsity**. Ranker changes are deterministic and observable, but outcomes are not yet resolved.

---

## Snapshot-by-Snapshot Detail

See `spec_094_detailed_results.csv` for per-snapshot:
- Overlap counts and Jaccard
- Financial_score / coinvest_z profiles of added/removed names
- Postmortem count per snapshot (for tracking when forward data will be available)

**Pattern**: Consistent stress-upside behavior across all 19 snapshots; no snapshot where ranker prefers higher financial_score.

---

## Falsification Criteria

### Would Support RANKER_ADDS_VALUE:
- ✗ Added names show significantly higher T+5 hit rate than selector-only (insufficient sample)
- ✗ Added names show positive T+5 median return vs negative for removed names (insufficient sample)
- ✗ Risk-adjusted return (Sharpe / drawdown) better for ranker vs selector-only (no drawdown data)

### Would Support SELECTOR_ONLY_COMPETITIVE:
- ✗ Selector-only T+5 hit rate ≈ ranker hit rate (insufficient sample)
- ✗ Names removed by ranker outperform names added by ranker (insufficient sample)

### Observed (Deterministic, Not False-Positive):
- ✓ Ranker systematically removes financially strong names (financial_score 47.4)
- ✓ Ranker systematically adds financially stressed names (financial_score 24.5)
- ✓ Stress-upside thesis is operationally consistent
- ✓ No evidence of a sign bug or label inversion (consistent with Spec 093 verdict)

---

## Classification: RANKER_UNPROVEN

**Reasoning**:

1. **Membership change is real and intentional** (confirmed by Spec 093 + operational overlap evidence)
2. **Stress-upside logic is being executed** (financial_score delta = -22.9 pp; coinvest_z delta = -0.41)
3. **Forward returns are insufficient to validate value-add** (6/69 = 8.7% coverage)

**Next step**: Re-run this analysis in ~2 weeks (2026-05-27) when post-PIT postmortems have resolved forward returns. Expected coverage: 30-50 resolved outcomes, sufficient for IC or hit-rate comparison.

---

## Recommended Next Steps

1. **Hold**: Do not promote or change ranker based on current evidence
2. **Monitor**: Track postmortem T+5 coverage weekly
3. **Spec 095 (Top-60 Scope)**: Proceed — ranker evaluation scope question is orthogonal to this data
4. **Spec 094 Rerun**: Target 2026-05-27 (2 weeks) for re-analysis with sufficient forward data
5. **Spec 098/099**: Proceed with catalyst timing and clinical orthogonality audits (independent of ranker value proof)

---

## Files Generated

- `artifacts/audit/spec_094_detailed_results.csv` — Per-snapshot overlap, financial profile
- `artifacts/audit/spec_094_results.json` — Full summary + per-snapshot data
- `spec_094_selector_only_analysis.py` — Analysis script (temporary, for reproducibility)

---

## Appendix: Postmortem Coverage Timeline

| Snapshot Date | Postmortem Records | T+5 Resolved |
|---------------|--------------------|--------------|
| 2026-04-20 | 1 | 0 |
| 2026-04-29 | 16 | 0 |
| 2026-04-30 | 35 | 6 |
| 2026-05-04 | 2 | 0 |
| 2026-05-05 | 2 | 0 |
| 2026-05-06 | 1 | 0 |
| **Total** | **69** | **6 (8.7%)** |

Expected coverage growth: By 2026-05-27, events from 2026-04-20 to 2026-05-20 will have resolved T+5, providing 40-50+ outcomes.
