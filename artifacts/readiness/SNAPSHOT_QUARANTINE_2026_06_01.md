# Snapshot Quarantine: 2026-06-01

**Date:** 2026-06-01  
**Status:** QUARANTINED — Do not use for Phase 2  
**Verdict:** CANONICAL_BAD

## Summary

The 2026-06-01 production snapshot has a composite scoring aggregation failure. All component scores are normal (SmartMoney 27–40, Financial -26 to -41), but the final composite scores collapse to near-zero (0.06–0.10) instead of expected 50–60 range.

**Result:** Top 30 is tier-A clinical holdings only; portfolio composition invalid.

## Diagnostic Evidence

- **Canonical top 3:** DNTH(0.0566), NRIX(0.0599), URGN(0.1000)
- **Expected (2026-05-29 reference):** BMRN(60.82), BEAM(59.34), BNTX(57.51)
- **Top-30 overlap:** 0/30
- **Component scores:** DNTH smart_money=38.1, financial=-41.7, clinical=-41.9 → composite=0.0566
- **Aggregation failure:** Components normal, composite broken

## Root Cause (TBD)

Likely Module 5 ranker composite aggregation logic:
- Gating too aggressive (100% valuation gating)
- Weighting mismatch (multiply/aggregate error)
- Regime forced UNKNOWN (0% confidence) → haircut cascade
- Other: TBD (requires tracing)

## Phase 2 Status

**DO NOT USE** 2026-06-01 snapshot for Phase 2 Day 1.

**Phase 2 Phase Status:** SUSPENDED_PENDING_COMPOSITE_AGGREGATION_DIAGNOSIS

Reference 2026-05-29 snapshot for comparison, but do not lock as replacement Day 1 without explicit governance approval.

## Next Diagnostic

Narrow trace: Why does canonical composite aggregation collapse to 0.06–0.10 despite normal component inputs? 

**Scope:** Investigate Module 5 ranker scoring logic only.  
**No rollback. No relock. No Phase 2 restart until root cause isolated.**

---

**Quarantine Date:** 2026-06-01 12:30 UTC  
**Snapshot Path:** `data/snapshots/2026-06-01/`  
**Canonical Rankings:** `data/snapshots/2026-06-01/rankings.csv` (INVALID)
