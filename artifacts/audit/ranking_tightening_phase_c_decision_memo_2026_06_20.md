# Ranking Tightening Phase C — DEM Decision Memo

**Date:** 2026-06-20  
**Status:** GOVERNANCE DECISION RECORD  
**Scope:** Consolidate audit findings; lock governance state; identify override path

---

## Decision Summary

```
DEM_MINIMAL_V2_RANKER: BLOCKED
WEIGHT_CHANGES: NOT_AUTHORIZED
FEATURE_ADDITIONS: NOT_AUTHORIZED
RANKER_REDESIGN: NOT_AUTHORIZED_WITHOUT_OPERATOR_OVERRIDE
METADATA_DESIGN: APPROVED (implementation deferred)
```

---

## Consolidated Evidence

### Phase 1: Code Verification ✅ CLEARED

**Finding:** 2-feature minimal_v2 ranker (coinvest_score_z + financial_score) confirmed.

**Verdict:** Ranker is what we expect. No architectural surprises.

---

### Phase 2a–2d: Robustness Audit ✅ CLEARED (except IC)

**Findings:**
- ✅ PIT safety by design (financial_score, coinvest_score_z)
- ✅ Contamination monitoring (institutional 13F, external gate)
- ✅ Z-score clamping (1.7% overall, 5% top-20; within bounds)
- ❌ **final_score IC insufficient** (Spec 100 blocker open)

**Verdict:** No defects. Ranker architecture is sound. IC blocker is the only issue.

---

### Phase A: IC Observability + Top-30 Stability ✅ ANALYZED

**Findings:**
- ✅ Top-30 churn is explainable (60% catalyst/selector, 30% DEM, 10% other)
- ✅ Top-5 stable across 17 days (COGT, DNTH, NRIX, URGN, ALMS)
- ✅ Forward-return data gaps identified; real-time window pending

**Verdict:** Ranking is stable. Churn is explainable. Real-time IC gate remains open.

---

### Phase B: Historical IC Rerun ❌ **FAILED**

**Findings:**

```
April 2026 (favorable window, 25 snapshots):
  T+10: IC = +0.0352 (marginal PASS, t = +1.20, 23 pairs)
  T+20: IC = -0.0955 (FAIL, t = -2.63, 23 pairs) ← PRIMARY HORIZON

May 2026 (recent window, 20 snapshots):
  T+5:  IC = -0.1214 (FAIL, t = -2.58, 13 pairs)
  T+10: IC = -0.1034 (FAIL, t = -2.44, 16 pairs)
  T+20: IC = -0.0188 (FAIL, t = -0.49, 17 pairs)
```

**Interpretation:** Historical data has full backward-looking coverage (100+ snapshot pairs available). Despite this advantage, final_score IC fails at the primary horizon (T+20) in both windows.

- April: Negative IC at T+20 (-0.0955) is statistically significant
- May: Weak IC at T+20 (-0.0188) consistent with April failure
- T+10 marginal pass in April (IC = +0.0352) is fragile and May shows decline

**Verdict:** `HISTORICAL_IC_FAIL` — The ranker does not meet Spec 100 threshold even when measured on ideal historical data.

---

## What Changed

### Before Phase B (June 19)

DEM blocker framing:
```
"final_score IC unobservable due to data gaps.
 Waiting on forward-return snapshots (July 8).
 Blocker may clear when data is sufficient."
```

### After Phase B (June 20)

DEM blocker reframed:
```
"final_score IC fails even on full historical data.
 Historical evidence does NOT support DEM continuation.
 Real-time June IC (pending July 8) is final confirmation gate.
 If real-time also fails, ranker changes require design override."
```

---

## Governance Decision

### Current State

```
DEM_MINIMAL_V2_AUTHORITY_LEVEL: BLOCKED

This means:
  ❌ No weight tuning (coinvest_score_z, financial_score)
  ❌ No new features (maintain 2-feature set)
  ❌ No selector gate changes
  ❌ No portfolio sizing changes
  ❌ No ranker code refactoring
  
  ✅ Metadata design (approved, not implemented)
  ✅ Read-only diagnostics / monitoring
  ✅ Top-30 stability tracking
```

### Authority Levels (Reference)

```
LEVEL 0: BLOCKED
  No model changes permitted.
  Historical + real-time IC gates failed.
  Governance decision required to proceed.

LEVEL 1: DESIGN_ONLY
  Design but do not implement.
  Metadata provenance design (approved for Phase 3 if gate clears).

LEVEL 2: TESTING
  Implement in test environment.
  Shadow mode; non-production.
  No portfolio impact.

LEVEL 3: PRODUCTION
  Live deployment.
  Portfolio and ranking changes authorized.
  Governance gates passed.
```

**Current DEM status:** LEVEL 0 (BLOCKED)

---

## IC Gate Timeline

| Date | Event | Status |
|------|-------|--------|
| 2026-06-20 | Phase B historical IC rerun | ❌ FAIL (T+20 = -0.0955 / -0.0188) |
| 2026-06-23 | T+5 becomes observable (2026-06-18 + 5 days) | Pending |
| 2026-06-29 | T+10 reaches 10+ pairs (confidence threshold) | Pending |
| 2026-07-08 | T+20 becomes observable (2026-06-18 + 20 days) | **DECISION GATE** |
| 2026-07-09+ | Phase C decision: IC passed or redesign override | Operator choice |

**Primary gate:** 2026-07-08 (T+20 real-time IC observable on 2026-06-18 base date)

**Success criterion:** final_score T+20 IC >= 0.0200

**Failure consequence:** DEM remains blocked OR operator approves Phase 3 redesign override

---

## Operator Override Path (Phase 3)

**If real-time June IC also fails (probable):**

Operator may approve Phase 3 redesign by explicit governance memo:

```
OPERATOR_OVERRIDE_APPROVAL_REQUIRED

Content:
  1. Acknowledgment: final_score IC failed on historical data
  2. Acknowledgment: real-time June IC failed (if applicable)
  3. Justification: Why redesign is justified despite failed gates
  4. Scope: What changes are approved (new features? new cohort? new ranker type?)
  5. Risk acceptance: What happens if redesign IC also fails?
  6. Governance: Who approves Phase 3 and by what date?

This memo is required to unblock Phase 3.
Without it, DEM remains LEVEL 0 (BLOCKED).
```

**Phase 3 scope (examples, not pre-approved):**

- Add new signals (disease-map, scientific-cartography, options-implied moves)
- Change cohort definition (e.g., expand from 60 to 80, or focus on biotech sub-sectors)
- Switch ranker type (e.g., gradient boosting instead of pairwise logistic)
- Rebuild feature engineering (e.g., use recent IC-positive features from other projects)
- Downgrade IC threshold (e.g., accept T+10 as primary instead of T+20)

---

## Metadata Provenance (Approved, Not Implemented)

**Status:** Design complete, implementation deferred.

**Fields designed:**
- Tier 1 (critical): source_date, filing_date, stale_flag, contamination_flag
- Tier 2 (useful): days_since_update, data_state, confidence
- Tier 3 (nice): provider, hash, quality_flags

**Implementation gate:** Phase 3 approval (if redesign proceeds) or separate metadata phase (if redesign blocked).

**No implementation without separate governance approval.**

---

## Recommended Actions (June 20 – July 8)

### Immediate (This Week)

1. **Archive Phase A/B findings** → Consolidated into this memo
2. **Notify stakeholders** → DEM is blocked; IC evidence is negative
3. **Lock DEM configuration** → Prevent accidental changes; treat as frozen
4. **Continue real-time monitoring** → Phase 2 data quality checks, top-30 stability

### June 22–July 7 (Accumulation Window)

5. **Monitor forward-return snapshot generation** → Ensure June 23, 29, July 8 snapshots are created
6. **Track top-30 ranking stability** → Document any unexplained churn (triggers review)
7. **Plan Phase 3 (if needed)** → Draft operator override memo in parallel; do not start implementation

### July 8 (Decision Point)

8. **Rerun real-time T+20 IC** → Measure final_score IC on 2026-06-18 base date
9. **Decision:**
   - If IC >= 0.0200 → UNBLOCK DEM; proceed with tuning / Phase 3
   - If IC < 0.0200 → CONFIRM blocker; await operator override memo (if Phase 3) OR accept frozen ranker

### July 9+ (Post-Decision)

10. **Execute chosen path:**
    - Path A (IC passed): Begin careful weight/feature tuning; metadata implementation
    - Path B (IC failed, override approved): Begin Phase 3 redesign per operator memo
    - Path C (IC failed, no override): Maintain frozen ranker; focus on data quality / monitoring

---

## Communication

### To Stakeholders

```
DEM Ranker Status (2026-06-20)

The historical IC rerun found that final_score does not meet the 0.0200 threshold at the primary (T+20) horizon, even on full backward-looking data. This confirms the real-time IC gate (pending July 8) is critical.

Current decision: DEM changes are blocked. No weight tuning, feature additions, or redesign are authorized until:
  1. Real-time June IC is measured (July 8), AND
  2. Either passes the 0.0200 gate OR operator approves Phase 3 redesign override

We recommend waiting for the July 8 gate before making staffing or design decisions.
```

### To Engineering

```
DEM Minimal_V2 Frozen (2026-06-20 – 2026-07-08)

Do not modify:
  - ranker_v2_pairwise.py
  - production_data/ranker_v2_model.json
  - Feature extraction or z-scoring logic
  - Selector integration

Approved activities:
  - Metadata design review
  - Top-30 stability monitoring
  - Data quality audits
  - Phase 3 planning (design-only, no code)

Next governance gate: 2026-07-08
```

---

## Success / Failure Scenarios

### Scenario A: Real-Time IC Passes (Optimistic, Unlikely)

```
2026-07-08: final_score T+20 IC >= 0.0200

→ UNBLOCK DEM changes
→ Begin Phase 3 or continue Phase 2 improvements
→ Implement metadata (Tier 1) with next ranker update
→ Resume normal DEM development cadence
```

### Scenario B: Real-Time IC Fails, Operator Approves Override (Realistic)

```
2026-07-08: final_score T+20 IC < 0.0200
2026-07-09: Operator submits Phase 3 redesign override memo

→ UNBLOCK Phase 3 work
→ Begin architecture redesign (new features, new ranker, expanded cohort)
→ Expect 3–6 week redesign + validation cycle
→ Retest IC on new design; gate remains 0.0200
```

### Scenario C: Real-Time IC Fails, No Override (Conservative)

```
2026-07-08: final_score T+20 IC < 0.0200
2026-07-09: No operator override memo received

→ MAINTAIN DEM freeze
→ Treat ranker as stable but unproven
→ Continue operational monitoring
→ Reassess in Q3 2026 (after more data)
→ Focus on portfolio quality, risk management, other improvements
```

---

## Governance Boundary

✅ **ALL PHASES EXECUTED READ-ONLY**

- ✅ No ranker code changes
- ✅ No weight modifications
- ✅ No feature formula changes
- ✅ No production output changes
- ✅ Metadata design-only
- ✅ No commits
- ✅ Git status clean

---

## Files Modified

**None (production files).**

---

## Summary: DEM Governance State (2026-06-20)

```
LIVE_RANKER: minimal_v2 (2 features, stable, audited)
PIT_SAFETY: ✅ CONFIRMED
ARCHITECTURE: ✅ CONFIRMED
CONTAMINATION_MONITORING: ✅ CONFIRMED
CLAMPING: ✅ CONFIRMED
IC_EVIDENCE: ❌ FAILED (historical T+20 = -0.0955, May = -0.0188)

DECISION: DEM_BLOCKED
REASON: final_score IC below 0.0200 threshold at primary horizon

NEXT_GATE: 2026-07-08 (real-time T+20 IC on 2026-06-18 base date)
GATE_SUCCESS_CRITERION: IC >= 0.0200
GATE_FAILURE_PATH: Operator override for Phase 3 redesign OR maintain freeze

STATUS_LEVEL: LEVEL_0_BLOCKED (no weight/feature changes)
METADATA: APPROVED_DESIGN_ONLY (Tier 1–3 fields proposed)
```

---

## Next Review Point

**2026-07-08:** Rerun real-time T+20 IC; make Phase 3 decision (proceed, override, or freeze).

---

