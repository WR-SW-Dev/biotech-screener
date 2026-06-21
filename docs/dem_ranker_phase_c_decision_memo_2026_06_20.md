# DEM Ranker Phase C — Decision Memo

**Date:** 2026-06-20  
**Status:** GOVERNANCE DECISION RECORD  
**Authority Level:** BLOCKED_LEVEL_0

---

## Current DEM State

```
Live Ranker: minimal_v2
Features: coinvest_score_z, financial_score
Deployed: production_data/ranker_v2_model.json
Status: FROZEN (no changes authorized)
```

---

## Audit Summary (Phases 1–2d)

| Phase | Finding | Status |
|-------|---------|--------|
| **Phase 1** | 2-feature ranker confirmed | ✅ CLEARED |
| **Phase 2a** | financial_score PIT-safe by design | ✅ CLEARED |
| **Phase 2c** | coinvest_score_z PIT-safe by design | ✅ CLEARED |
| **Phase 2d** | z-score clamping 1.7% overall, 5% top-20 | ✅ CLEARED |
| **IC Blocker** | final_score IC insufficient (Spec 100 gate) | ❌ OPEN |

---

## Historical IC Evidence (Phase B)

**Window:** April 2026 (25 snapshots, 100+ pairs available)

```
T+10: IC = +0.0352, t = +1.20, obs = 23
  Status: Marginal pass (barely >= 0.0200 threshold)

T+20: IC = -0.0955, t = -2.63, obs = 23
  Status: FAIL (below threshold, negative correlation)
```

**Window:** May 2026 (20 snapshots, 100+ pairs available)

```
T+5:  IC = -0.1214, t = -2.58, obs = 13
T+10: IC = -0.1034, t = -2.44, obs = 16
T+20: IC = -0.0188, t = -0.49, obs = 17
  Status: ALL FAIL (below threshold)
```

**Verdict:** `HISTORICAL_IC_FAIL` — Ranker does not meet Spec 100 threshold (>= 0.0200) at primary horizon (T+20) even on ideal historical data with full backward-looking coverage.

---

## Authority Decision

```
DEM_MINIMAL_V2: BLOCKED_LEVEL_0
```

### Prohibited

```
❌ Weight tuning (coinvest_score_z, financial_score)
❌ New features (maintain 2-feature set only)
❌ Formula changes (keep z-scoring, clamping, null handling as-is)
❌ Ranker code refactoring (read-only)
❌ Selector gate changes
❌ Portfolio sizing changes
```

### Allowed

```
✅ Read-only monitoring (top-30 stability, IC tracking)
✅ Metadata design (Tier 1–3 fields approved, not implemented)
✅ Phase 3 planning (design-only, no code until override approved)
✅ Data quality audits
✅ Documentation
```

---

## Unblocking Criteria

DEM changes require **at least one** of the following:

### Criterion A: Real-Time IC Passes (Preferred)

```
Date: 2026-07-08 (or later)
Test: Rerun Spec 100 final_score IC on 2026-06-18 base date
Horizon: T+20 (primary)
Success: T+20 final_score IC >= 0.0200
Consequence: UNBLOCK DEM (proceed with tuning or Phase 3)
```

### Criterion B: Operator Override (Alternative)

```
Date: 2026-07-09 or later (after July 8 gate)
Approval: Explicit operator memo approving Phase 3 redesign despite failed IC
Scope: New features, new cohort, new ranker type, or downgraded IC threshold
Consequence: UNBLOCK Phase 3 (architectural redesign, not weight tuning)
Requirement: Operator accepts risk that redesign IC may also fail
```

### Criterion C: No Override (Conservative)

```
Date: 2026-07-09+ (if neither A nor B occurs)
Decision: MAINTAIN DEM FREEZE
Timeline: Reassess in Q3 2026 after more data accumulation
Path: Focus on data quality, portfolio risk management, other improvements
```

---

## Governance Boundary

```
✅ Read-only audit (Phases 1–2d, Phase A, Phase B)
✅ Documentation (this memo, July 8 runbook)
✅ Design-only (metadata, Phase 3 planning)

❌ No ranker code changes
❌ No weight modifications
❌ No feature formula changes
❌ No production output changes
❌ No commits
```

---

## Timeline

| Date | Event | Gate | Decision |
|------|-------|------|----------|
| 2026-06-20 | Phase C decision memo | — | DEM_BLOCKED_LEVEL_0 |
| 2026-06-23 | T+5 observable (2026-06-18 + 5d) | Pending | Monitor only |
| 2026-06-29 | T+10 reaches 10+ pairs | Pending | Monitor only |
| **2026-07-08** | **T+20 observable (2026-06-18 + 20d)** | **PRIMARY_GATE** | **UNBLOCK OR OVERRIDE** |
| 2026-07-09+ | Operator decision | Override memo | Phase 3 or freeze |

---

## What Changed (Phase B Evidence)

### Before

```
"final_score IC unobservable due to data gaps. Waiting on forward snapshots.
 Blocker may clear when data is sufficient."
```

### After

```
"final_score IC fails on historical data with full backward coverage.
 Historical evidence does NOT support DEM continuation.
 Real-time July 8 IC is final confirmation gate.
 If real-time also fails, Phase 3 requires operator override."
```

---

## Summary

DEM minimal_v2 is operationally sound (PIT-safe, contamination-visible, clamping-safe) but scientifically unproven (IC fails at primary horizon). 

Changes are blocked until real-time IC is measured (July 8) or operator explicitly approves redesign despite failed evidence.

Metadata design is ready for Phase 3 (if approved) but implementation is deferred.

---

**For more detail:** See Phase C decision memo audit artifact.

