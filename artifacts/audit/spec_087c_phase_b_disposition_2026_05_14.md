# Spec 087C Phase B — Disposition (2026-05-14)

**Author:** Research implementation  
**Task:** Spec 087C Phase B — bioshort alpha research implementation  
**Status:** PHASE_B_COMPLETE — evidence memo delivered, forward research scoped

---

## Summary

Spec 087C Phase B research has completed with the delivery of a single-snapshot evidence memo analyzing the bioshort hedge governance evidence across 14 historical reports (2026-03-06 through 2026-05-08). The Phase A blocker (≥4 fresh weekly reports) was unblocked via historical reconstruction backfill of 9 Friday portfolio snapshots, bringing total reports from 5 to 14.

---

## Historical Reconstruction (Blocker Resolution)

### Execution

- **Fridays with portfolio snapshots:** 10 (2026-03-06 through 2026-05-08)
- **Backfilled reports:** 9 (2026-03-06, 3-13, 3-20, 3-27, 4-03, 4-10, 4-17, 4-24, 5-01)
- **Total reports after backfill:** 14
- **Method:** Idempotent re-run of `tools/biotech_hedge_report.py` with historical portfolio snapshots
- **Data sources:** Live options data (Tastytrade); BS fallback only where live options unavailable
- **Outcome:** ✓ Blocker cleared; Phase B eligible

---

## Phase B Evidence Analysis (2026-05-14)

### Deliverable: Single-Snapshot Evidence Memo

**File:** `artifacts/audit/spec_087c_phase_b_evidence_memo_2026_05_14.md`

**Scope:** Hedge governance analysis using May-08 report as reference snapshot, with week-over-week stability check (May-07 → May-08) and regime-conditional performance context.

### Key Findings

| Finding | Implication |
|---------|------------|
| **Payoff frequency: 9.1%** (1 of 11 months) | Hedge is tail insurance, not expected-value positive |
| **Carry cost: 71 bps annualized** | Insurance premium is high in low-volatility regime |
| **Verdict stability: 100%** (IBB 15% OTM across May-07/08) | Recommendation is robust to weekly data noise |
| **Confidence trending up** (60% → 85%) | Additional data reduced uncertainty |
| **Vehicle choice: IBB > XBI** | Despite XBI's superior R² (0.905 vs 0.701), IBB chosen for convex tail payoff |
| **Backtest quality: 100%** coverage, 0 BS fallback | High-confidence payoff estimates using live option Greeks |

### Research Questions (Phase B.2, Deferred)

Forward research identified for future execution:
1. Carry trend analysis across multi-week backfill (Mar-Jun)
2. Structure ranking stability (top-1 vs top-2/3)
3. Vehicle switching triggers (regime-conditional IBB ↔ XBI)
4. Portfolio composition sensitivity (60-EW vs 30-optimized)

---

## Scope Confirmations

- [x] Read-only research; no scoring, selector, ranker, EV, or sizing changes
- [x] Hedge NOT treated as trading alpha; framed as institutional carry/insurance
- [x] Cross-period comparisons (Mar-26 vs May-08) account for portfolio construction change
- [x] bioshort_watch LLM remains suppressed (separate reactivation decision per Spec 087 §1)
- [x] No Module 3/5, ranking, or decision-engine changes

---

## Held Ledger Disposition

**Current status in held ledger:** `[HELD] Spec 087C — bioshort alpha research`

**Recommended disposition:**
- Move Phase A to `[SHIPPED]` (design memo locked 2026-05-07)
- Move Phase B to `[OBSERVATION]` (evidence memo delivered 2026-05-14; awaiting Phase B.2 research decision)
- Update `last_evidence` to `spec_087c_phase_b_evidence_memo_2026_05_14.md`
- Update `alert_condition` to "Phase B.2 forward research deferred pending IC decision"

**Phase B.2 gate:** IC decision on whether to proceed with regime sensitivity / structure stability / portfolio robustness analysis. Not a blocker for operations; Spec 088 and other work may proceed in parallel.

---

## Integration Points

### Downstream Dependencies

- **Spec 088 Phase B:** ✓ Completed (catalyst_delta v2 filter) — no blocker from 087C
- **bioshort_watch LLM reactivation:** Still gated by Spec 087 B0 guard; IC decision required (separate spec)
- **Dashboard freshness envelope:** ✓ Shipped (Spec 087 B2) — supports consumer confidence checks

### Cross-References

- Phase A design: `spec_087c_phase_a_research_design_2026_05_14.md`
- Evidence memo: `spec_087c_phase_b_evidence_memo_2026_05_14.md` (this deliverable)
- Spec 087 B0 (freshness guard): `spec_087_b0_formal_closure_2026_05_14.md`
- Spec 087 B2 (dashboard envelope): `spec_087_b2_formal_closure_2026_05_14.md`

---

## Execution Log

| Date | Action | Status |
|------|--------|--------|
| 2026-05-07 | Phase A research design locked | ✓ Complete |
| 2026-05-14 | Historical reconstruction backfill approved | ✓ Complete |
| 2026-05-14 | Backfill execution (9 Fridays) | ✓ Complete (14 reports total) |
| 2026-05-14 | Phase B evidence memo analysis | ✓ Complete |

---

_Spec 087C Phase B research delivery complete. Phase A + B scoped and documented. Phase B.2 forward research deferred pending IC decision._
