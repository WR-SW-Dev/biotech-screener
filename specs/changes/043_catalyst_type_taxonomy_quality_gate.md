# Change Spec: Catalyst Type Taxonomy Quality Gate

**Status**: REJECTED
**Author**: Claude / operator
**Date**: 2026-03-31
**Ruleset impact**: N/A (rejected before implementation)

---

## Objective

Add a bounded quality gate on the clinical catalyst taxonomy path so that
low-confidence or misclassified catalyst types do not receive full clinical_quality
credit. Motivated by MAZE (rank 36, -35.2% on SAE) being carried by momentum past
a soft Phase 2 catalyst with clinical_quality 0.56.

## Why It Was Rejected

The deeper data analysis showed the gate has no viable threshold:

### Evidence

All top-book Phase 2 names share MAZE's exact taxonomy profile:

| Ticker | Rank | CatType | Source | Hard | ClinQ | Opt |
|--------|------|---------|--------|------|-------|-----|
| SION | 1 | CT_PRIMARY_COMPLETION | CTGOV_CALENDAR | 0 | 0.52 | 0.98 |
| ORKA | 7 | CT_PRIMARY_COMPLETION | CTGOV_CALENDAR | 0 | 0.48 | 0.84 |
| ARTV | 11 | CT_PRIMARY_COMPLETION | CTGOV_CALENDAR | 0 | 0.62 | 0.79 |
| CLYM | 13 | CT_PRIMARY_COMPLETION | CTGOV_CALENDAR | 0 | 0.60 | 0.72 |
| MAZE | 36* | CT_PRIMARY_COMPLETION | CTGOV_CALENDAR | 0 | 0.56 | 0.45 |

*pre-event rank

### Problems

1. **No quality threshold separates MAZE from top-book.** SION (rank 1) has clinical_quality
   0.52 — worse than MAZE (0.56). A gate at any threshold catches top names first.

2. **No taxonomy confidence dimension separates them either.** Every Phase 2 name uses
   CT_PRIMARY_COMPLETION from CTGOV_CALENDAR with is_hard=0. The parser route, source,
   and ambiguity are identical. A confidence-based gate would assign identical confidence
   to MAZE and SION.

3. **The real discriminator is optionality.** MAZE (0.45) vs SION (0.98) — the DEM already
   sorts on this correctly. MAZE ranked 36th, not 1st, because of lower optionality.

4. **SAE events are stochastic.** Clinical design quality (0.55 for MAZE) does not predict
   serious adverse events. SAE risk is not capturable from trial metadata alone.

5. **MAZE at rank 36 is acceptable mid-book noise.** One false positive out of 12 resolutions
   (8% error rate) in the mid-book is normal model behavior, not a systematic failure.

## What This Means

- The catalyst type taxonomy approach (Spec 030 multiplier, this quality gate) is a
  dead end for Phase 2 clinical readout names
- The DEM's existing optionality anchor already provides the discrimination that matters
- MAZE-type events cannot be prevented by taxonomy-level gates without harming the top book
- The monotonic calibration shape (100% → 67% → 33% → 0%) validates the existing selector

## Recommendation

Do not implement. The cost (top-book disruption) exceeds the benefit (one mid-book
false positive avoided). Document and move on.

---

## Implementation Log

### 2026-03-31 — Spec drafted and rejected
- MAZE audit → initial diagnosis: taxonomy correction candidate
- Deeper analysis: no viable threshold (top-book has worse quality than MAZE)
- All Phase 2 names share identical taxonomy profile
- Verdict: REJECTED — acceptable false positive, not fixable taxonomy error

---

*Template version: 1.0.0 — see specs/SYSTEM_SPEC.md for system invariants*
