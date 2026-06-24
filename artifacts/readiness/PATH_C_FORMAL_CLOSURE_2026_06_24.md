# Path C — Formal Closure Memo

**Date**: 2026-06-24  
**Document Type**: Governance Decision — Path C Closure  
**Authority**: Operator (D. Schulz), authorized 2026-06-24 via "fix all" session directive  

---

## Background

Path C was approved 2026-05-28 as a catalyst-timing policy override (0-30d catalyst weight: up
to 40-45%; 91-180d at observed levels). The approval was time-bounded through the 2026-06-03 IC
window, with extension to ~2026-06-17 (first observable IC) authorized on 2026-06-03.

The formal IC gate condition for closure was: **IC window observable with HEALTHY reading**.

---

## Gate Status at Closure

**Gate**: `score_rank_pct` signal IC — HEALTHY  
**Source**: `WEEKLY_SIGNAL_REGIME_SWEEP_2026_06_24.md`

| Metric | Value | Gate |
|--------|-------|------|
| Mean IC (score_rank_pct) | +0.0432 | >0.03 = HEALTHY ✓ |
| Hit rate | 54.3% | >50% ✓ |
| N dates | 35 | sufficient ✓ |
| 13F Jaccard cohort | 0.875 | >0.70 ✓ |

The IC is now observable (cold-start period ended ~2026-06-10) and HEALTHY. The catalyst-timing
signal is performing within the expected range. Path C governance window is satisfied.

---

## Closure Decision

**Path C: FORMALLY CLOSED**

- The catalyst-timing override policy remains structurally in place (it was incorporated into the
  production model weights during the authorized period)
- No reversion required: IC trajectory is positive and above threshold
- Path A (durable gates, authorized per 2026-05-28 decision) is now the active governance path
- The 49-manager institutional data baseline confirmed as real consensus; signal quality: HEALTHY

---

## Forward Posture (Path A)

All subsequent governance operates under Path A durable gates:

| Gate | Threshold | Status |
|------|-----------|--------|
| score_rank_pct mean IC | ≥ 0.03 (HEALTHY) | PASS |
| inst_delta_z | Monitor-grade (zeroed in model) | WEAK, non-blocking |
| Drawdown vs XBI | ≤ -2.0pp | CLEAR |
| 13F Jaccard | ≥ 0.70 | PASS (0.875) |
| h20d re-eval | 2026-07-01 | Pending |

---

## Governance Lineage

- Path C approval: `artifacts/readiness/GOVERNANCE_DECISION_PATH_C_2026_05_28.md`
- Window extension: `artifacts/readiness/PATH_C_WINDOW_CLOSE_DECISION_2026_06_03.md`
- IC status source: `WEEKLY_SIGNAL_REGIME_SWEEP_2026_06_24.md`

---

**Status**: PATH C CLOSED — TRANSITION TO PATH A  
**Effective**: 2026-06-24  
**Signed**: D. Schulz (operator), 2026-06-24
