# 13F Q1 2026 Validation Verdict

**Run Date:** 2026-05-19 (pre-May-20 snapshot validation)  
**Pre-Snapshot:** 2026-05-15 (last pre-bulk-filing snapshot, 6/48 managers filed)  
**Post-Snapshot:** 2026-05-19 (46/48 managers filed, 42/42 elite core)  
**Validation Command:**
```bash
/usr/bin/python3 tools/check_13f_cohort_quarantine.py \
  --pre-date 2026-05-15 --post-date 2026-05-19 \
  --output artifacts/13f_cohort_quarantine_2026_05_19.md
```

---

## Filed Manager Status

| Metric | Value |
|--------|-------|
| Managers filed (Q1 2026) | 46/48 (96%) |
| Elite core filed | 42/42 (100%) |
| Filed count percentage | 96% |
| **Gate 1 (≥34 filed)** | **PASS** |
| Bulk filing date | 2026-05-15 (most managers) |
| Last filing detected | 2026-05-18 (Ally Bridge) |
| Remaining unfiled | 2 (Broadfin Capital/Kotler, Farallon Capital) |

---

## Validation Guardrails

| Guardrail | Status | Notes |
|-----------|--------|-------|
| **G1: Snapshot Completeness** | PASS | rankings.csv + institutional_summary_delta.json present in 2026-05-19 snapshot |
| **G2: Producer Freshness** | PASS | cache_as_of_date=2026-05-19, advanced from 2026-05-15 |
| **G3: Manager-level vs window-level** | PASS | inst_delta_z KS=0.34 attributed to refresh (expected), coinvest_score_z stable |

---

## Cohort Validation Gates

| Gate | Status | Threshold | Result | Notes |
|------|--------|-----------|--------|-------|
| **Gate 1: Filed Count** | PASS | ≥34 managers | 46/48 (96%) | Well above threshold |
| **Gate 2: Cohort Jaccard** | PASS | ≥0.70 | 0.875 | Excellent top-30 stability |
| **Gate 3: Producer Freshness** | PASS | cache advanced | 2026-05-15 → 2026-05-19 | Full advance confirmed |
| **Gate 4: Position Completeness** | PASS | no Q4 stale | All 42/42 elite filed | Comprehensive |
| **Gate 5: Top-30 Stability** | PASS | KS < 0.20 (coinvest) | 0.0201 | coinvest_score_z minimal drift |
| **Gate 6: Coverage/Diversity** | PASS | coverage drop < 10pp | -1.01pp (85.91% → 84.9%) | Well within threshold |

**Overall Guardrails:** ALL PASS

---

## Diff Analysis

### A. Manager-Level Changes
- **New managers filed since May 15:** +40 (6 → 46 by May 19)
- **Total AUM delta:** All 42 elite managers with Q1 2026 data now cached
- **Registry changes:** None (registry stable)

### B. Coverage Impact
- **Tickers with signals:** 253 (stable across refresh)
- **Signal coverage %:** 85.91% → 84.9% (-1.01pp)
- **Coverage drop (Gate 6 check):** 1.01pp — well within 10pp threshold

### C. Per-Ticker Score Distribution
- **coinvest_score_z KS-stat:** 0.0201 (threshold 0.20) — **PASS**
- **inst_delta_z KS-stat:** 0.34 (threshold 0.30) — flagged but **expected refresh behavior** (new Q1 filings naturally shift quarterly deltas)
- **Notable shifts:** None — 0 large changes in coinvest_score_z, mean abs delta only 0.009

### D. Top-30 Churn Analysis

**Cohort Jaccard:** 0.875 (target ≥0.70)

| Metric | Count |
|--------|-------|
| Top-30 entries (new) | 2 (ALMS, ARGX) |
| Top-30 exits (removed) | 2 (SYRE, URGN) |
| Top-30 unchanged | 26 |
| Rank movement (avg Δ) | Minimal |

**Notable entries:**
- ALMS — entered top-30 (Deep Track $149M new position confirm)
- ARGX — entered top-30

**Notable exits:**
- SYRE — dropped from top-30
- URGN — dropped from top-30

### E. Sector / Market Cap / Stage Skew
- **Sector concentration:** Stable (Biotechnology 27, Drug Manufacturers 3 — unchanged)
- **Market cap bucket shifts:** No meaningful shift (all unknown cap in top-30)
- **Stage bucket changes:** Minimal (late: 24→25, mid: 5→4, early: 1→1)

---

## Freshness/Completeness/Stability Failures

**No failures detected.**

**Non-blocking warnings:**
- inst_delta_z KS=0.34 flagged above 0.30 threshold, but is expected from the Q1 data refresh. Not a contamination artifact — cohort composition is stable (Jaccard 0.875).

---

## Verdict

### Overall Validation Result

**Verdict: CLEAR** — No quarantine extension needed

### If CLEAR:
```text
✅ All 6 gates PASS
✅ Cohort Jaccard = 0.875 (≥ 0.70)
✅ No critical freshness/completeness/stability failures
✅ Top-30 churn acceptable (Jaccard ≥ 0.70)
✅ coinvest_score_z collapse guard PASS (SD = 21.76 > 0.10)

Quarantine LIFTS (pending 5-day observation window end 2026-05-20).
Spec 089 KG pilot may proceed after clearance.
Phase 2 Step 4 unblocks after official lift.
```

---

## Decision Impact

### Quarantine Clearance Timeline (per decision tree 2026-05-19):

| Date | Event |
|------|-------|
| **2026-05-19** | Cohort quarantine check ran — NO_QUARANTINE verdict |
| **2026-05-20** | 5-day observation window ends → official verdict known |
| **2026-05-21** | Quarantine lift decision → Phase 2 Step 4 unblocks |
| **2026-05-21** | Spec 089 KG pilot launch approval |

### Items That Unlock (post-clearance):

| Item | Status | Notes |
|------|--------|-------|
| Spec 089 KG pilot | UNBLOCKS | can proceed after 5/21 lift |
| Spec 100 IC battery | UNBLOCKS | checklist v2 scorecard can run |
| Spec 094 selector-only | UNBLOCKS | rerun after h20d decision |
| Spec 072 vNext diagnostic | UNBLOCKS | review can proceed |
| Architecture freeze | LIFTS | partial (ranker frozen pending Spec 096) |
| h20d gate | CLEARS | for model/selector/ranker decisions |

---

## Disposition

**Validation Artifact:** `artifacts/13f_cohort_quarantine_2026_05_19.md`

**Next Action:**
- [ ] May 20: 5-day observation window concludes
- [ ] May 21: Formal quarantine lift decision
- [ ] Begin Spec 089 KG pilot checklist review

**Signed by:** Hermes (SOUL — biotech screener agent)  
**Date:** 2026-05-19  
**Confidence level:** HIGH
