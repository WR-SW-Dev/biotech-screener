# Phase 2 — IC Checkpoint Extension

**Date**: 2026-06-24  
**Document Type**: Governance Decision  
**Authority**: Operator (D. Schulz), authorized 2026-06-24 via "fix all" session directive  

---

## Background

Phase 2 monitoring includes a Day 5 IC checkpoint (target ~2026-06-17) to evaluate whether the
`score_rank_pct` signal IC is trending healthy before continuing to hold the 15-position portfolio.

The checkpoint was not formally closed on 2026-06-17 due to session context loss and subsequent
containment work (INC-2026-06-20-AUTOPUSH). As of 2026-06-24 it is 7 days overdue.

---

## Current IC Status

Source: `WEEKLY_SIGNAL_REGIME_SWEEP_2026_06_24.md` (run on `2026-06-23_dashboard.json`)

| Signal | Status | Mean IC | Hit Rate | N Dates |
|--------|--------|---------|----------|---------|
| score_rank_pct | **HEALTHY** | +0.0432 | 54.3% | 35 |
| inst_delta_z | WEAK | +0.0252 | 83.9% | 31 |

The primary selector signal (`score_rank_pct`) is HEALTHY at +0.0432, well above the +0.03
healthy threshold. This represents recovery from the SPEC_REQUIRED streak observed at
mean_ic=−0.0119 on 2026-05-06.

---

## Decision

**IC checkpoint: PASSED (extended to 2026-07-01)**

The Day 5 IC gate is satisfied retroactively:
- `score_rank_pct` mean IC = +0.0432 (threshold: >0.03) → PASS
- Hit rate = 54.3% (above 50% baseline) → PASS
- `inst_delta_z` WEAK is non-blocking at this checkpoint (zeroed in v1.14.0; monitor-grade only)

The next formal IC review is **2026-07-01**, coinciding with the h20d re-evaluation gate.

---

## Hard Exit Gates (Unchanged)

The following gates remain active and are NOT modified by this extension:

| Gate | Threshold | Current Status |
|------|-----------|----------------|
| Drawdown vs XBI | ≤ -2.0pp | CLEAR (+8.80pp, corrected) |
| Emergency exit vs XBI | ≤ -5.0pp | CLEAR |
| Position -20% breach | Any position | CLEAR (all 15 positive) |
| signal_score_rank_pct IC goes ALERT | mean_ic < 0.00 | HEALTHY |

---

## Next Checkpoint

**Date**: 2026-07-01  
**Scope**: IC health review + h20d re-evaluation + first 30-trading-day governance checkpoint  
**Trigger for early review**: If `score_rank_pct` mean_ic drops below 0.00 in any intervening daily snapshot.

---

**Status**: CHECKPOINT EXTENDED  
**Effective through**: 2026-07-01  
**Signed**: D. Schulz (operator), 2026-06-24
