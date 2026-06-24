# Path C Governance Override — Formal Closure Memo
**Date**: 2026-06-24  
**Status**: CLOSED  
**Condition**: IC observable AND above floor → SATISFIED  
**Authority**: Governance condition defined in `PATH_C_DECISION_LOG_2026_06_03.md`

---

## Closure Basis

Path C was a catalyst timing policy override approved 2026-05-28 (see `GOVERNANCE_DECISION_PATH_C_2026_05_28.md`). It was extended on 2026-06-03 pending first observable IC evidence (gate: score_rank_pct mean_ic > 0.02 with ≥ 20 dates).

**Evidence confirming gate:**
- Source: `artifacts/ic_dashboard/2026-06-23_dashboard.md`
- `score_rank_pct` mean_ic = **+0.0432** (HEALTHY; threshold 0.02)
- Dates in window: **35** (threshold 20)
- Hit rate: 54%
- Latest IC: +0.1202
- Trend: sustained positive from 2026-04-23 onward after April drawdown recovery

IC is now observable and above floor. Gate condition is unambiguously met.

---

## What Changes

| Item | Before Closure | After Closure |
|------|---------------|---------------|
| Path C catalyst timing override | Active (0-30d up to 40-45%) | **CLOSED — no longer in effect** |
| Spec 100 ranker IC tooling | Blocked on Path C | **UNBLOCKED — shipped 2026-06-24 (commit `c682ac17`)** |
| IC-based ranker interpretation | Prohibited until IC observable | **Permitted with labeled Spec 100 tooling** |
| Future Path C reopening | N/A | Requires new governance event; no auto-reopening |

---

## What Does NOT Change

- **HOLD verdict remains** — 2 FAIL (bucket_drift 41.67pp, phase2_health) on 2026-06-23 scorecard. Path C closure does not lift HOLD; those FAILs require separate operator decisions.
- **Architecture freeze monitoring** — h20d re-eval gate still live (2026-07-01). Jaccard check due.
- **EES shadow monitor** — still in observation window (5d gate MET, 20d gate NOT MET as of 2026-06-24).
- **inst_delta_z** — WEAK (+0.0252); zeroed in production at v1.14.0; no change.
- **bucket_drift FAIL** — 41.67pp in 91-180d catalyst bucket (13.3% vs 55% policy). Requires operator acceptance or policy recalibration memo — not resolved by this closure.

---

## Provenance Chain

1. `GOVERNANCE_DECISION_PATH_C_2026_05_28.md` — Original Path C approval
2. `PATH_C_DECISION_LOG_2026_06_03.md` — Extension decision + IC gate definition
3. `PATH_C_WINDOW_CLOSE_DECISION_2026_06_03.md` — Extension rationale memo
4. `artifacts/ic_dashboard/2026-06-23_dashboard.md` — Evidence of gate satisfaction
5. This memo — Formal closure record

---

## Next Actions (operator)

1. **bucket_drift FAIL**: Accept 41.67pp 91-180d drift as market-driven OR order policy recalibration. Not a blocker for Spec 100 use.
2. **phase2_health FAIL**: Investigate root cause (may be transient). Check `run_phase2_daily.py` output.
3. **h20d gate (2026-07-01)**: Run `tools/check_13f_cohort_quarantine.py`. Jaccard < 0.40 → freeze re-activation.
4. **EES shadow 20d gate**: Continue daily monitor runs until ≥ 20 completed 20d observations.

---

_Closed by operator review. No automated system action taken._
