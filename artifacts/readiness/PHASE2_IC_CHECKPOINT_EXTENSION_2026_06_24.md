# Phase 2 IC Checkpoint — Extension Decision
**Date**: 2026-06-24  
**Monitoring Day**: 12  
**Decision**: EXTEND — continue Phase 2 observation  
**Authority**: Operator approval 2026-06-24

---

## Context

The Phase 2 IC first-print checkpoint was scheduled for Day 5 (2026-06-17). It was not formally closed at that date and is now 7 calendar days / 5 trading days overdue. This memo documents the operator's decision to extend the observation window.

---

## Basis for Extension

| Factor | Value | Assessment |
|--------|-------|------------|
| score_rank_pct mean_ic | +0.0432 | HEALTHY (>0.02 floor) |
| IC observation dates | 35 | Sufficient |
| Path C gate | SATISFIED 2026-06-24 | IC is observable and above floor |
| Drawdown vs XBI | -2.88pp | TRIPPED (threshold -2.0pp); see separate gate decision |
| DRUG position | -24.69% | Under review; does not trigger emergency exit alone |
| Portfolio return vs entry | +7.16% absolute | Positive absolute return |
| XBI return vs entry | +10.04% | Broad sector outpacing |

**IC signal is performing (HEALTHY).** The primary question is whether underperformance vs XBI constitutes a revert trigger. Operator decision: EXTEND — the drawdown gate is accepted separately (see `DRAWDOWN_GATE_ACCEPTANCE_2026_06_24.md`).

---

## Extension Terms

- **Extended through**: h20d re-evaluation gate 2026-07-01 (7 days)
- **Hard exit triggers** (unchanged):
  - Drawdown vs XBI ≤ -5.0pp (emergency exit)
  - Jaccard < 0.40 (cohort drift; freeze re-activation)
  - IC mean drops below 0.00 on next dashboard refresh
- **Next formal checkpoint**: 2026-07-01 (h20d gate + IC re-evaluation)
- **HOLD verdict**: Unchanged. Extension does not authorize new trades.

---

## Provenance

- `PATH_C_DECISION_LOG_2026_06_03.md` — IC gate definition
- `PATH_C_FORMAL_CLOSURE_2026_06_24.md` — Path C IC gate satisfied
- `artifacts/ic_dashboard/2026-06-23_dashboard.md` — Evidence
- `artifacts/monitoring/daily_2026_06_24.json` — Day 12 snapshot
