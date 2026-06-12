# Spec 111: IC Signal Remediation — Phase 1 (Remove)

**Status:** PENDING OPERATOR DECISION  
**Created:** 2026-06-12  
**Author:** Hermes ops_supervisor escalation  
**Severity:** HIGH (Phase 2 gate health)  
**Authority:** Governance decision required  

---

## Summary

Remove `clinical_optionality_pct_dev` signal from IC health monitoring pool due to demonstrated negative predictive power (mean_ic=-0.0338, hit rate 23.68%).

Signal selection is backwards: higher clinical optionality correlates with lower returns. Removing noisy negative signal restores IC pool to 2-signal model (score_rank_pct + inst_delta_z).

---

## Problem Statement

### Current Situation

**IC Health Dashboard (2026-06-12):**
```json
{
  "attention": "HIGH",
  "signals": {
    "clinical_optionality_pct_dev": {
      "mean_ic": -0.0338,           ← ALERT (threshold -0.03)
      "hit_rate": 0.2368,            ← Weak (vs random 50%)
      "latest_ic": -0.0964,          ← Degrading
      "health": "ALERT"
    }
  }
}
```

**Backtest Performance (Mar 26 → May 12, 38 trading days):**
- Signal IC consistently negative throughout period
- Selection accuracy 23.68% (worse than random)
- Latest IC -0.0964 shows worsening trend
- Only signal in ALERT state; other signals WEAK but positive

### Root Cause

Clinical optionality (therapy development stage %) is not a useful predictor in current market regime. Higher optionality (early-stage therapies) predicts LOWER returns. Signal formulation is backwards relative to market expectations.

### Impact

**Phase 2 Gates:**
- 13F Jaccard: 0.875 ✓ (still passing)
- IC Observable: Expected ~June 17 (signal status affects baseline)
- Drawdown: 0.00pp ✓ (safe)

**Operational:**
- ic_health_monitor currently FAIL due to this signal
- Removes noisy negative signal from institutional cohort validator
- Shifts Phase 2 to 2-signal IC model (sufficient, lower noise)

---

## Solution: Remove Signal

### Implementation

**Step 1: Remove from IC health dashboarding**
- File: `tools/ic_health_memory_hygiene.py`
- Change: Exclude `clinical_optionality_pct_dev` from dashboard generation
- Effect: Dashboard now shows 2 signals (score_rank_pct, inst_delta_z)

**Step 2: Document in IC signal registry**
- File: `artifacts/ic_dashboard/_meta.json` (or equivalent)
- Change: Mark signal as "removed" with reason + date
- Effect: Maintains audit trail for future analysis

**Step 3: Update ops_supervisor alerting**
- File: Agent heartbeat threshold logic
- Change: ic_health_monitor no longer FAIL; accept 2-signal dashboard
- Effect: Reduces anomaly count from 10/29 to 9/29

### Timeline

**Option A: Immediate (recommended)**
- Implement June 12 evening
- Effect: ic_health_monitor reverts to OK by next heartbeat (June 13)
- Testing: One heartbeat cycle validation
- Commit: Document with reference to Spec 111

**Option B: Deferred to Phase 2 lock (~June 17)**
- Implement after Phase 2 Day 1 lock-in confirmed
- Effect: Cleaner boundary between Phase 2 monitoring and Phase 3 setup
- Testing: Full 5-day observation period before lock
- Commit: Same, but post-lock

### Affected Code Paths

```
tools/ic_health_memory_hygiene.py      ← Dashboard generation
artifacts/ic_dashboard/*.json            ← Output files
agents/ic_health_monitor/memory/        ← Heartbeat logs
tools/agent_heartbeat_checks.py         ← Alerting logic
```

---

## Decision Options

### Option A: REMOVE (Spec 111 — Recommended)
- **Action:** Delete signal from pool
- **Risk:** Low
- **Rationale:** Demonstrably backwards; removes noise
- **Timeline:** Immediate or post-June 17 lock
- **Approval Path:** Governance standard
- **Fallback:** None needed; signal is strictly harmful

### Option B: INVERT (Spec 112 — Experimental)
- **Action:** Flip sign (low optionality → sell, high optionality → buy)
- **Risk:** High; speculative
- **Rationale:** Maybe market rewards earlier-stage therapies?
- **Timeline:** Test 10-20 days, then decide
- **Approval Path:** Conditional acceptance + monitoring gate
- **Fallback:** Revert to Spec 111 if inversion makes things worse

### Option C: DE-WEIGHT (Spec 113 — Cautious)
- **Action:** Multiply weight by 0.25-0.50
- **Risk:** Medium; still uses weak signal
- **Rationale:** Preserve optionality while muting negative IC
- **Timeline:** 20-30 day observation + re-eval
- **Approval Path:** Conditional acceptance + threshold gates
- **Fallback:** Either Spec 111 (remove) or Spec 112 (invert) if degradation continues

---

## Phase 2 Considerations

**Timing Window:**
- Decision: June 12-17 (pre-IC-observable)
- Implementation: Immediate or post-June 17
- Verification: 1 heartbeat cycle (next day)

**13F Jaccard Gate:** Unaffected (0.875, passing)

**IC Observable Gate:** Signal removal doesn't degrade baseline IC; it improves it by removing noise

**Drawdown Gate:** Unaffected (0.00pp, passing)

---

## Testing & Validation

### Pre-Commit Checklist
- [ ] Dashboard generation completes without signal
- [ ] Heartbeat check passes with 2-signal model
- [ ] ic_health_monitor heartbeat status reverts from FAIL to OK
- [ ] No impact to Phase 2 governance gates (13F, drawdown, IC)
- [ ] Operator briefing confirms decision path (A/B/C)

### Post-Commit Monitoring
- Heartbeat daily through June 17
- ic_health_monitor status tracked
- Shadow_monitor MAX_DRAWDOWN alert monitored (current 11.30%)
- IC observable window preparation (June 17)

---

## Documentation & Artifacts

**Decision Log:** This spec (Spec 111)

**Supporting:**
- `docs/phase2_hermes_update_2026_06_12.md` — Operator briefing
- `artifacts/ic_dashboard/2026-06-12_dashboard.json` — Current state
- `artifacts/heartbeat/2026-06-12_anomalies.md` — Anomaly summary
- `logs/agents_direct/ops_supervisor_20260612_*.json` — Escalation log

**Commit Message:** Reference this spec and justify signal removal with IC evidence

---

## Recommendation

**Implement Option A (REMOVE)** immediately.

**Justification:**
1. Signal is demonstrably backwards (mean_ic=-0.0338, hit rate 23.68%)
2. Removal is strictly positive (reduces noise, doesn't degrade other signals)
3. Timeline is clean (before Phase 2 lock-in)
4. No fallback needed; signal is purely harmful
5. Other signals (score_rank_pct, inst_delta_z) provide sufficient coverage

**Alternative:** If user prefers conservative approach, defer implementation to post-June 17 lock (Option B timing for Spec 111).

---

## Ownership

**Decision Authority:** Operator / Governance  
**Implementation:** Hermes workflow (Spec 111 automation task)  
**Verification:** Daily heartbeat + Phase 2 gate monitoring  
**Escalation:** ops_supervisor (ORANGE verdict until resolved)  

---

**Status:** AWAITING OPERATOR DECISION (A / B / C)
