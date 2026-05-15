# classifier_escalation_pool Gate — QA Observation 2026-05-15

**Gate:** classifier_escalation_pool
**Date:** 2026-05-15 production QA check
**Verdict:** TRIAGED / QA-semantics mismatch
**Status:** No logic change pending

---

## QA Finding

| Metric | Value |
|--------|-------|
| Pool size | 788 |
| Clean records | 30/30 |
| Other share | 58.2% |
| Status | FAIL (QA) |

---

## Context

The gate failure is a **semantic mismatch between QA expectations and classifier behavior**, not a logic or data quality issue.

- **Classifier logic:** Working as designed
- **Pool composition:** Stable and expected
- **QA contract:** Under separate refinement

---

## Action

**No classifier logic changes** pending separate QA contract work. The 58.2% "other_share" is a known signal property and does not indicate a defect.

This gate will be resolved as part of the QA governance contract refinement effort (separate from 2026-05-15 QA cycle).

**Record:** TRIAGED. No code changes required at this time.

