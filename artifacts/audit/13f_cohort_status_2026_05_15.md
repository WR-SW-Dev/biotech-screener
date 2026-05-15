# 13F Q1 2026 Cohort Status — May 15, 2026

**Date:** May 15, 2026 (13F filing deadline)
**Status:** Partial refresh only; distortion NOT cleared
**Next validation:** ~May 22–23 (post-fuller filing coverage)

---

## Filing Status

| Metric | Status |
|--------|--------|
| Deadline | Today (2026-05-15) |
| Managers filed | 6/48 (~12.5%) |
| Data ingested | YES (`holdings_2026-03-31.json`, May 15 09:09) |
| Coverage | Partial |

---

## Cohort Quarantine State

**Status:** ACTIVE (not cleared)

**Quarantine trigger:** Top-30 Jaccard < 0.70 (detected post-cohort change ~2026-04-25)

**Distortion present:** inst_delta_z inflated
- Byte-identical across 2026-04-25/27/28 snapshots
- SIGNAL_ALERT persistent (as designed)
- Top-30 changes (RVMD-in, ERAS-out) treated as cohort artifact
- **Status:** NOT cleared as of 2026-05-15

**Release condition:**
- Materially complete Q1 2026 filings (estimated ~May 22–23)
- Re-validation passing all gates
- Cohort Jaccard >= 0.70

---

## Production Impact

**Selector/ranker/sizing:** No changes authorized during quarantine

**Attribution lane:** ACTIVE (post-cohort distortion audit in place)

**2026-05-22 ranker review:** Governance/evidence briefing only
- No promotion gate opens until cohort clears
- No ranker/selector/sizing implementation authorized

---

## Key Dates

| Event | Date |
|-------|------|
| Cohort change detected | 2026-04-25 |
| Distortion begins | 2026-04-25 |
| Filing deadline | 2026-05-15 |
| Expected fuller coverage | ~2026-05-22 |
| Expected re-validation | ~2026-05-23 |
| Architecture freeze lift | ~2026-05-26 |

---

## Governance Record

This memo documents that:
1. 13F Q1 2026 refresh is partial as of filing deadline
2. Cohort quarantine remains active
3. inst_delta distortion is NOT cleared
4. No production changes are authorized pending cohort clearance
5. 2026-05-22 review is evidence/briefing only, not decision-gate

**Enforcement:** Memory-backed governance. All ranker/selector/sizing work blocked until formal cohort-clearance memo is issued.

