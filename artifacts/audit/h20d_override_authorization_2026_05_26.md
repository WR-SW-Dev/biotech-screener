# h20d Override Authorization — 2026-05-26

**Status:** APPROVED  
**Decision Authority:** Operator (D. Schulz)  
**Effective Date:** 2026-05-26 11:50 ET  
**Severity:** CRITICAL (overrides validation guardrails; freeze lift authorized)

---

## Executive Summary

The 55-manager elite core registry has been formally committed to main (commit e61b806d, 2026-05-26). The 13F validation suite on this expanded cohort **FAILS** on two critical gates:

- **Jaccard similarity: 0.463** (threshold ≥0.70) ✗ FAIL
- **inst_delta distortion: 1.0285** (target <0.50) ✗ FAIL

Despite these failures, the operator has approved **manual override** to proceed with freeze lift and h20d clearance.

---

## Validation Failure Details

### Gate Status (55-Manager Cohort)

| Gate | Metric | Result | Threshold | Status |
|------|--------|--------|-----------|--------|
| 1 | Filed count | 49/55 | ≥34 | ✓ PASS |
| 2 | Jaccard similarity | 0.463 | ≥0.70 | ✗ FAIL |
| 3 | Producer freshness | post-refresh verified | verified | ✓ PASS |
| 4 | Position completeness | no stale Q4 | verified | ✓ PASS |
| 5 | Top-30 stability (KS) | 0.148 (coinvest), 0.171 (inst_delta) | <0.20 | ⚠ MARGINAL |
| 6 | Coverage | -1.01pp | <10pp drop | ✓ PASS |

**Root cause of instability:** The 7 new managers introduce **11 names entering / 11 exiting** the Top-30 (vs. 2 in / 2 out for 48-manager baseline). This is a **cohort-composition effect**, not a data quality issue. The new managers' concentrated biotech/clinical positions diverge from the existing elite core, creating legitimate signal overlap reduction.

---

## Operator Rationale for Override

**Justification:**
- **Institutional AUM expansion:** +$22.48B (+17.1%) from 7 Q1 2026 filing managers
- **Strategic legitimacy:** All 7 managers verified with Q1 2026 13F filings; no data integrity issues
- **Manageable churn:** 11-enter / 11-exit Top-30 churn is elevated but not catastrophic; previous acceptable churn baseline was 14-in/14-out (2026-05-22 provisional metrics)
- **Governance precedent:** Option B formalization establishes pathway for future registry expansions with proper validation + operator sign-off
- **Monitoring framework:** Enhanced weekly Jaccard tracking + inst_delta distortion watch mitigates ongoing risk

**Risk acceptance:** Operator acknowledges that elevated Top-30 churn increases institutional signal volatility. This is acceptable under the following conditions:
1. Weekly monitoring of Jaccard (target stabilization toward ≥0.70 by 2026-06-15)
2. inst_delta distortion tracking (target <0.50 by 2026-06-15)
3. h20d re-evaluation scheduled 2026-07-01 if cohort does not stabilize
4. Immediate freeze re-activation if Jaccard drops below 0.40 or inst_delta exceeds 1.50

---

## Freeze Lift Authorization

**Effective immediately:**

- ✓ **Alpha freeze LIFTED** (model changes authorized)
- ✓ **Ranker freeze LIFTED** (ranker modifications authorized)
- ✓ **Selector freeze LIFTED** (selector modifications authorized)
- ✓ **Sizing freeze LIFTED** (portfolio weighting changes authorized)
- ✓ **Phase 2 Step 5 UNBLOCKED** (KG pipeline implementation authorized)
- ✓ **Spec 089 KG enforcement ACTIVATED** (advisory → active enforcement)
- ✓ **inst_delta alpha weight RESTORED** (unfrozen from governance ceiling)

**Conditions:**
- All freeze lift contingent on yfinance rate-limit recovery (expected 2026-05-27 to 2026-05-28)
- Enhanced monitoring schedule begins immediately (see Part 3)
- If yfinance remains unrecovered beyond 2026-05-27 14:00 ET (96h threshold), escalate to SIP-2026-003 (provider fallback evaluation)

---

## Part 3: Enhanced Monitoring Schedule

**Weekly h20d gate conditions check (Fridays 6:22 PM ET starting 2026-05-31):**

```bash
python3 tools/check_13f_cohort_quarantine.py \
  --pre-date 2026-05-15 \
  --post-date [current_friday_date] \
  --output artifacts/13f_validation_verdict_55manager_weekly_[DATE].md
```

**Key metrics to track:**
- Jaccard similarity (target: stabilization trend toward ≥0.70)
- inst_delta_z distortion (target: <0.50 by 2026-06-15)
- Top-30 churn rate (target: convergence toward ≤5 in/5 out)
- Filing progress (target: maintain ≥89% coverage)

**Re-evaluation triggers:**
- If Jaccard drops below 0.40: re-activate freeze, convene emergency review
- If inst_delta exceeds 1.50: flag as escalation point, prepare freeze reversion
- If filing coverage drops below 80%: audit manager status, possible registry revision

**h20d re-decision gate:** 2026-07-01 (if stabilization trend is positive) or sooner if any trigger threshold is exceeded

---

## Part 4: h20d Decision Finalization

**Finalized h20d decision memo regenerated at:** `artifacts/audit/h20d_decision_memo_55manager_override_2026_05_26.md`

**Outcome:** h20d CLEARED (with override authorization OPTION_B_OVERRIDE_2026_05_26)

---

## Authorization Record

```
OPERATOR OVERRIDE AUTHORIZATION — h20d MANUAL CLEARANCE

Registry: 55-manager elite core (v3.2, committed 2026-05-26)

Validation Status: FAILED
- Jaccard: 0.463 (FAIL, threshold ≥0.70)
- inst_delta: 1.0285 (FAIL, target <0.50)

Override Decision: APPROVED

Authorization ID: OPTION_B_OVERRIDE_2026_05_26
Operator Name: D. Schulz
Operator Email: dschulz@wakerobin.co
Approval Date: 2026-05-26 11:50 ET
Approval Time: 11:50:00 ET

Conditions:
1. Weekly monitoring of Jaccard/inst_delta (starting 2026-05-31)
2. Re-evaluation scheduled 2026-07-01
3. Freeze re-activation threshold: Jaccard < 0.40 or inst_delta > 1.50
4. yfinance recovery monitoring (escalation 2026-05-27 14:00 ET)

Signed: D. Schulz
Date: 2026-05-26
```

---

## Related Documentation

- **Registry Expansion Proposal:** `artifacts/audit/manager_registry_expansion_proposal_2026_05_26.md`
- **Registry Authority Reconciliation:** `artifacts/audit/h20d_registry_authority_reconciliation_2026_05_26.md`
- **13F Validation (55-manager, complete data):** `artifacts/13f_validation_verdict_55manager_complete_2026_05_26.md`
- **h20d Decision Memo (override):** `artifacts/audit/h20d_decision_memo_55manager_override_2026_05_26.md`

---

**Status:** FINALIZED  
**Freeze lift:** AUTHORIZED  
**h20d decision:** CLEARED (with override)  
**Phase 2 Step 5:** UNBLOCKED  
**Spec 089:** ACTIVATED
