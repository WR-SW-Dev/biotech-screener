# 13F Q1 2026 Validation Verdict

**Run Date:** [FILL: validation run date]  
**Pre-Snapshot:** 2026-05-14 (last pre-bulk-filing snapshot)  
**Post-Snapshot:** [FILL: snapshot date with refresh landed]  
**Validation Command:**
```bash
python -m tools.check_13f_cohort_quarantine \
  --pre-date 2026-05-14 --post-date [POST_DATE] \
  --output artifacts/13f_validation_[DATE].md
```

---

## Filed Manager Status

| Metric | Value |
|--------|-------|
| Managers filed (Q1 2026) | [FILL: N/48] |
| Filed count percentage | [FILL: X%] |
| **Gate 1 (≥34 filed)** | [FILL: PASS/FAIL] |
| Bulk filing date | 2026-05-15 |
| Last filing detected | [FILL: date] |
| Remaining unfiled | [FILL: count + names] |

---

## Validation Guardrails

| Guardrail | Status | Notes |
|-----------|--------|-------|
| **G1: Snapshot Completeness** | [FILL] | rankings.csv + institutional_summary_delta.json present |
| **G2: Producer Freshness** | [FILL] | cache_as_of_date advanced past pre-snapshot |
| **G3: Manager-level vs window-level** | [FILL] | Distinguish refresh impact from data window roll |

---

## Cohort Validation Gates

| Gate | Status | Threshold | Result | Notes |
|------|--------|-----------|--------|-------|
| **Gate 1: Filed Count** | PASS | ≥34 managers | 46/48 | Already passed pre-validation |
| **Gate 2: Cohort Jaccard** | [FILL] | ≥0.70 | [FILL] | Top-30 overlap post-refresh |
| **Gate 3: Producer Freshness** | [FILL] | cache advanced | [FILL] | institutional_summary advancement |
| **Gate 4: Position Completeness** | [FILL] | no Q4 stale | [FILL] | All positions post-Q1 filing date |
| **Gate 5: Top-30 Stability** | [FILL] | KS-stat < threshold | [FILL] | coinvest/inst_delta distribution drift |
| **Gate 6: Coverage/Diversity** | [FILL] | coverage drop < 10pp | [FILL] | sector/mcap/stage_bucket skew |

**Overall Guardrails:** [FILL: all pass / some failed / critical failure]

---

## Diff Analysis

### A. Manager-Level Changes
- **New managers filed since May 14:** [FILL: count]
- **Total AUM delta:** [FILL: $ change]
- **Registry changes:** [FILL: adds/removes/restructures]

### B. Coverage Impact
- **Tickers with new signals:** [FILL: count]
- **Signal coverage % change:** [FILL: before → after]
- **Coverage drop (Gate 6 check):** [FILL: percentage points]

### C. Per-Ticker Score Distribution
- **coinvest_score_z KS-stat:** [FILL: value] (threshold 0.20)
- **inst_delta_z KS-stat:** [FILL: value] (threshold 0.30)
- **Notable shifts:** [FILL: tickers with large score changes]

### D. Top-30 Churn Analysis

**Cohort Jaccard:** [FILL: value] (target ≥0.70)

| Metric | Count |
|--------|-------|
| Top-30 entries (new) | [FILL] |
| Top-30 exits (removed) | [FILL] |
| Top-30 unchanged | [FILL] |
| Rank movement (avg Δ) | [FILL] |

**Notable entries:**
- [FILL: ticker, score, prior rank]

**Notable exits:**
- [FILL: ticker, score, new rank or dropped]

### E. Sector / Market Cap / Stage Skew
- **Sector concentration change:** [FILL: delta %]
- **Market cap bucket shifts:** [FILL: observation]
- **Stage bucket changes:** [FILL: observation]
- **Diversification impact:** [FILL: good / concerning / minor]

---

## Freshness/Completeness/Stability Failures

**List any failed checks (if any):**
- [FILL: Gate/check name — reason for failure — impact]

**Non-blocking warnings (if any):**
- [FILL: warning name — context — mitigation]

---

## Verdict

### Overall Validation Result

**Verdict:** [FILL: **CLEAR** / **EXTEND QUARANTINE** / **MANUAL REVIEW**]

---

### If CLEAR:
```text
✅ All 6 gates PASS
✅ Cohort Jaccard ≥ 0.70
✅ No critical freshness/completeness/stability failures
✅ Top-30 churn acceptable (Jaccard ≥ 0.70)

Quarantine LIFTS.
Spec 089 KG pilot may proceed.
Phase 2 Step 4 unblocks.
```

---

### If EXTEND QUARANTINE:
```text
❌ Validation FAILED on: [FILL: gate names]
❌ Cohort Jaccard < 0.70 OR critical gate failure detected

Quarantine EXTENDS.
Determine cause:
- Manager composition stability (G3)
- Coverage drop or signal loss (Gate 6)
- Distribution drift (Gate 5)
- Completeness gaps (Gate 4)

Options:
1. Re-baseline post-May-20 if data/cache issue
2. Request manual review of gate failures
3. Extend monitoring window for slower filing completion
```

---

### If MANUAL REVIEW:
```text
⚠️ Validation AMBIGUOUS on: [FILL: gate names]
⚠️ Mixed results (some gates pass, others unclear)

Manual review required before KG unlock.
Summarize ambiguous checks and remediation path.
```

---

## Decision Impact

### If Quarantine Clears:

| Item | Status | Notes |
|------|--------|-------|
| Spec 089 KG pilot | UNBLOCKS | can proceed post-approval |
| Spec 100 IC battery | UNBLOCKS | Checklist v2 scorecard can run |
| Spec 094 selector-only | UNBLOCKS | rerun post-May-27 eligible |
| Spec 072 vNext diagnostic | UNBLOCKS | review can proceed |
| Architecture freeze | LIFTS | subject to post-refresh governance |
| h20d gate | CLEARS | for model/selector/ranker decisions |

### If Quarantine Extends:

| Item | Status | Notes |
|------|--------|-------|
| Spec 089 KG pilot | BLOCKED | no launch until quarantine clears |
| Spec 100 IC battery | BLOCKED | no dashboard work |
| All model changes | BLOCKED | selector/ranker/sizing hold |
| Phase 2 Step 4 | BLOCKED | KG remains deferred |

---

## Disposition

**Validation Artifact:** [FILL: link to full `13f_validation_[DATE].md`]

**Next Action (if CLEAR):**
- [ ] Review Spec 089 KG pilot launch checklist
- [ ] Confirm Phase 2 Step 4 readiness
- [ ] Begin KG implementation per spec 089 design

**Next Action (if QUARANTINE EXTENDS):**
- [ ] Isolate failed gates
- [ ] Schedule manual review
- [ ] Determine re-baseline window

---

**Signed by:** [FILL: validation agent/human reviewer]  
**Date:** [FILL]  
**Confidence level:** [FILL: high / medium / low]
