# Spec 089 Phase 1.5A — Implementation Deferred (2026-05-15)

**Date**: 2026-05-15  
**Schema Status**: LOCKED (commit `8bee00e4`)  
**Implementation Status**: DEFERRED pending cohort clearance  
**Expected Resume**: Post-13F validation (~2026-05-23 or later)

---

## Precondition Checklist

| Precondition | Status | Date | Notes |
|---|---|---|---|
| 2026-05-15 snapshot closure | ✅ | 2026-05-15 | Drift/QA/Phase 2 gates passed |
| Spec 105 live QA closure | ✅ | 2026-05-14 | Commit `c6bcb91ce` |
| Spec 104 Phase B closure | ✅ | 2026-05-15 | Commit `2aab7c930` |
| 13F Q1 2026 cohort validation | ❌ | Blocked | 6/48 managers filed; quarantine ACTIVE; distortion NOT cleared |

---

## Why Deferred Now

The 13F cohort distortion remains unresolved as of the filing deadline (2026-05-15):
- **Filing coverage**: Only 6/48 managers (12.5%)
- **Cohort quarantine**: STILL ACTIVE
- **inst_delta_z distortion**: NOT CLEARED
- **Validation gates**: Blocked pending fuller filings (~May 22–23)

Per governance, **no production ranker work is authorized while cohort quarantine is active**, including preparatory work on ranker governance tooling that depends on baseline-clear data.

The Spec 089 knowledge graph must encode governance state with precision; building it now against contaminated cohort data would require later revision. Deferring to post-clearance minimizes rework.

---

## What Is NOT Deferred

- Schema design (locked)
- Node/edge type definitions (locked)
- Contradiction rule specifications (locked)
- In-memory memory updates (this memo)

---

## What Remains Blocked

- **No extractor code**
- **No query code**
- **No graph build script**
- **No tests**
- **No cron integration**

---

## Resumption Condition

Start Spec 089 implementation when **ALL** of:
1. Fuller 13F Q1 2026 filings received (~May 22–23)
2. Cohort quarantine clearance validated (cohort Jaccard ≥ 0.70)
3. inst_delta_z distortion cleared (mean |x| ≠ locked 0.743 value)

**Expected**: ~May 23–26 (post-h20d IC checkpoint 2026-05-26)

---

## Implementation Timeline (When Resumed)

- **Design → Extract**: 1–2 days (spec scan, git log, grep for stubs)
- **Emit JSONL**: 1 day (node/edge generation)
- **Query layer**: 2–3 days (graph traversal, contradiction checks)
- **Validation**: 2–3 days (test suite, known-blocker verification)
- **Checkpoint memo**: 1 day (closure + evidence)

**Total**: ~1 week (May 26 → June 1)

**Deadline**: Complete pilot by 2026-05-22 ranker review → **REVISED to post-h20d checkpoint (2026-05-26+)**

---

## Governance Record

This memo documents that Spec 089 Phase 1.5A is **intentionally deferred**, not abandoned. The deferral is driven by data contamination (active cohort quarantine), not technical blockers.

**Enforcement**: All work on Spec 089 implementation is blocked until cohort clearance memo is issued.

---

## References

- **13F cohort status**: `artifacts/audit/13f_cohort_status_2026_05_15.md`
- **Spec 089 schema**: commit `8bee00e4`, `specs/changes/spec_089_phase_1_5a_ranker_governance_kg_pilot.md`
- **Cohort distortion regime**: `memory/regime_post_cohort_change_distortion_2026_04_28.md`
- **Ranker review status**: `artifacts/audit/2026_05_22_ranker_review_status_2026_05_15.md`
