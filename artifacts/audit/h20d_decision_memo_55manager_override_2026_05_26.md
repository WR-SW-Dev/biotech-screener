# h20d Decision Memo — 55-Manager Registry Override — 2026-05-26

**Decision:** CLEARED (with manual override authorization)  
**Authority:** Operator approval OPTION_B_OVERRIDE_2026_05_26  
**Effective Date:** 2026-05-26 11:55 ET  
**Freeze Status:** **LIFTED** (all restrictions removed)  
**Phase 2 Status:** **Step 5 UNBLOCKED**  
**Spec 089 Status:** **ACTIVATED** (enforcement active)

---

## Executive Summary

The h20d decision gate has been **CLEARED** based on operator override authorization. The 55-manager elite core registry was formally committed to main (2026-05-26, commit e61b806d) and validated on complete Q1 2026 holdings data. The validation suite **FAILED** on Jaccard similarity (0.463 < 0.70) and inst_delta distortion (1.0285 > 0.50) gates, but the operator has approved manual override to proceed with freeze lift.

**Key decision:** The 7 new managers introduce legitimate institutional AUM coverage (+$22.48B, +17.1%) that outweighs short-term signal volatility. The cohort will be monitored weekly; re-evaluation gate scheduled 2026-07-01.

---

## Part 1: 13F Validation Summary

### Validation Run: 2026-05-26 (55-manager cohort, complete data)

| Gate | Criterion | Result | Threshold | Status |
|------|-----------|--------|-----------|--------|
| 1 | Filed count | 49/55 (89%) | ≥34 (61%) | ✓ PASS |
| 2 | Jaccard similarity | 0.463 | ≥0.70 | ✗ FAIL |
| 3 | Producer freshness | post-refresh verified | verified | ✓ PASS |
| 4 | Position completeness | no stale Q4 | verified | ✓ PASS |
| 5 | Top-30 stability (KS) | coinvest 0.148, inst_delta 0.171 | <0.20 | ⚠ MARGINAL |
| 6 | Coverage | 84.9% (−1.01pp) | <10pp drop | ✓ PASS |

**Validation verdict:** 4/6 gates PASS, 2 gates FAIL (Jaccard, inst_delta).

### Top-30 Churn Analysis

**Baseline (48-manager cohort, 2026-05-19):**
- Top-30 churn: 2 entering / 2 exiting
- Jaccard: 0.875 ✓
- Status: QUARANTINE CLEARED

**Current (55-manager cohort, 2026-05-26):**
- Top-30 churn: 11 entering / 11 exiting
- Names entering: ALMS, APGE, ARWR, CMPS, DRUG, MLTX, MLYS, NRIX, SNDX, TRVI, TYRA
- Names leaving: ACAD, APLS, ASND, AXSM, BCRX, JAZZ, JBIO, SION, TARS, TSHA, ZYME
- Jaccard: 0.463 ✗
- Status: QUARANTINE (NOT CLEARED per validation framework)

**Root cause:** The 7 new managers (Frazier, Siren, TCG, Braidwell, Integral Health, Affinity, Paradigm) hold concentrated biotech/clinical positions that diverge from existing elite core holdings. Clinical-stage tilt increases significantly (stage: late 24→22, mid 5→7).

---

## Part 2: Governance Analysis

### Why Override Is Justified

1. **Data integrity:** All 7 managers have verified Q1 2026 13F filings (no missing/fabricated data)
2. **Strategic alignment:** All 7 fit biotech-specialist profile (see expansion proposal for full rationale)
3. **Institutional weight:** +$22.48B AUM expansion is material
4. **Churn is manageable:** 11-enter/11-exit is elevated but not catastrophic
   - Previous "acceptable" churn threshold during 48-manager cohort transition was 14-in/14-out (May 22 provisional data)
   - Current 11-in/11-out is below that precedent
5. **Monitoring framework:** Weekly Jaccard tracking + re-eval gate (2026-07-01) mitigates risk

### Risks Accepted

- **Short-term signal volatility:** Top-30 rankings will fluctuate more frequently
- **Institutional signal distortion:** Mean |inst_delta_z| = 1.0285 vs. target <0.50
- **Cohort stability:** Weekly Jaccard trending (currently 0.463, target ≥0.70 by mid-June)
- **Escalation triggers:** If Jaccard drops <0.40 or inst_delta >1.50, freeze re-activation will be considered

---

## Part 3: Operational Impact

### Freeze Lift (Effective immediately)

**Unlocked:**
- ✓ Alpha freeze LIFTED
- ✓ Ranker freeze LIFTED
- ✓ Selector freeze LIFTED
- ✓ Sizing freeze LIFTED
- ✓ Phase 2 Step 5 implementation AUTHORIZED
- ✓ Spec 089 KG enforcement ACTIVATED

**Contingencies:**
- yfinance recovery monitoring (if rate-limit incident continues beyond 2026-05-27 14:00 ET, freeze may be partially re-activated for data quality reasons)
- Weekly Jaccard check (Fridays 6:22 PM ET) begins 2026-05-31

### Implementation Timeline (Phase 2 Step 5)

| Date | Action | Owner |
|------|--------|-------|
| 2026-05-26 (now) | Freeze lift authorization issued | OPERATOR |
| 2026-05-27 | Deploy KG pipeline (Phase 2 Step 5, 4d integration) | ENGINEER |
| 2026-05-28 to 2026-05-31 | KG queries live in production; monitor for anomalies | MONITOR |
| 2026-05-31 | First weekly 13F validation check | CRON |
| 2026-06-01 | Hermes KG decision agents operational (if yfinance recovered) | MONITOR |
| 2026-07-01 | h20d re-evaluation gate (if cohort stabilization trend positive) | OPERATOR |

---

## Part 4: Spec 089 Activation

**Knowledge graph governance enforcement:** ACTIVATED

- Contradictions engine: LIVE (detects registry/signal conflicts)
- Ranker governance queries: LIVE (traces decision provenance)
- Spec drift audit: LIVE (daily, 07:00 ET)
- Manual override audit: LIVE (tracks all operator approvals)

**Hermes agent layer ready:**
- Agent_preflight: checks KG state before permitting model changes
- Agent_contradiction_monitor: continuous watch for policy violations
- Agent_h20d_monitor: daily reconciliation of h20d gate conditions

---

## Part 5: Monitoring Requirements

### Weekly h20d Gate Check (Starting 2026-05-31)

```bash
python3 tools/check_13f_cohort_quarantine.py \
  --pre-date 2026-05-15 \
  --post-date [FRIDAY_DATE] \
  --output artifacts/13f_validation_verdict_55manager_weekly_[DATE].md
```

**Success criteria:**
- Jaccard trending toward ≥0.70 (by 2026-06-15, target ≥0.65)
- inst_delta distortion trending toward <0.50 (by 2026-06-15, target <0.75)
- Filing coverage ≥80% (expect 49/55 to remain stable)

**Failure triggers (re-activation candidate):**
- Jaccard < 0.40 → immediate escalation
- inst_delta > 1.50 → immediate escalation
- Coverage drop >10pp → audit phase

### yfinance Monitoring (Ongoing)

- **Status:** Rate-limit incident ongoing (81+ hours)
- **Escalation point:** 2026-05-27 14:00 ET (96h threshold)
- **Expected recovery:** 2026-05-27 to 2026-05-28
- **Fallback:** SIP-2026-003 (provider swap evaluation)

---

## Part 6: Related Documentation

- **Override Authorization:** `artifacts/audit/h20d_override_authorization_2026_05_26.md`
- **Registry Expansion Proposal:** `artifacts/audit/manager_registry_expansion_proposal_2026_05_26.md`
- **Registry Authority Reconciliation:** `artifacts/audit/h20d_registry_authority_reconciliation_2026_05_26.md`
- **13F Validation (55-manager, complete):** `artifacts/13f_validation_verdict_55manager_complete_2026_05_26.md`
- **13F Validation (48-manager, baseline):** `artifacts/13f_validation_verdict_2026_05_19.md`

---

**h20d Status:** ✓ CLEARED (with override OPTION_B_OVERRIDE_2026_05_26)  
**Freeze:** ✓ LIFTED  
**Phase 2 Step 5:** ✓ UNBLOCKED  
**Spec 089:** ✓ ACTIVATED  
**Next review:** 2026-07-01 (or earlier if trigger thresholds exceeded)

---

**Approved by:** D. Schulz  
**Approval ID:** OPTION_B_OVERRIDE_2026_05_26  
**Date:** 2026-05-26  
**Time:** 11:55 ET
