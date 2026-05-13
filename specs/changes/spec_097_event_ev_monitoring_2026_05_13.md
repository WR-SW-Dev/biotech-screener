# Spec 097 — Event-EV Prospective Monitoring Gate

**Status**: SPEC ONLY (governance monitoring, no code changes)  
**Date**: 2026-05-13  
**Priority**: 2 (unblocks EV-based ranker decisions once calibration threshold met)  
**Investment**: ~1–2 hours (setup forward-tracking dashboard, define verdict gate)

---

## Problem Statement

Event-EV (expectation value for catalyst/approval events) has been collected and partially validated via Spec 077 binder implementation (forward-only node_id matching + fallback to ticker±7d window). However, **promotion to ranker alpha requires calibration evidence**:

- **Current state**: 7 post-PIT HIT/MISS outcomes resolved (n=7, from postmortems where `event_ev_p_hit` was available and outcome occurred)
- **Promotion threshold**: ≥30 resolved post-PIT outcomes (HIT/MISS both represented) to estimate P(HIT) fidelity
- **Uncertainty**: Unknown whether `event_ev_p_hit` predictions are well-calibrated; possible reasons for misses:
  - Incorrect binder join (Spec 077 fallback may have false-positive matches)
  - Overconfident P(HIT) estimates (underestimating event failure rate)
  - Signal leakage (EV may be correlated with composite_score rather than independent)
  - Clinical-outcome causality (EV may drive portfolio composition rather than drive returns)

**Consequence**: Cannot yet rank-weight by `event_ev_p_hit` or condition clinically on EV probability. Can shadow-monitor and accumulate evidence.

---

## Investment Logic

- Event-EV is a prospective, high-signal-value metric (P(approval) is directly observable outcome)
- Calibration is fast-path vs IC/return validation (outcomes resolve within weeks, not months)
- Governance gate is low-touch: passive tracking + threshold check, no algorithmic changes
- High-priority for portfolio expressiveness: if P(HIT) is well-calibrated, allows sizing by event probability

---

## Exact Evidence & Analysis Needed

### 1. Define Forward-Tracking Infrastructure

**Input**: Postmortem records with `event_ev_p_hit` field populated (Spec 077 binder output)

**Tracking dashboard** (shadow-only initially):
- Per postmortem: node_id, ticker, event_date, snapshot_date, predicted_p_hit, event_outcome (HIT/MISS/DELAYED/NEEDS_REVIEW)
- Aggregates:
  - n_total (all postmortems with event_ev_p_hit populated)
  - n_hit (postmortems where outcome = HIT)
  - n_miss (postmortems where outcome = MISS)
  - n_resolved (n_hit + n_miss; excludes DELAYED/NEEDS_REVIEW)
  - mean_p_hit_among_hits (median/mean predicted_p_hit for HIT outcomes)
  - mean_p_hit_among_misses (median/mean predicted_p_hit for MISS outcomes)
  - calibration_curve (binned by predicted_p_hit: [0–0.2], [0.2–0.4], ..., [0.8–1.0]; compute empirical hit rate per bin)

**Location**: `artifacts/postmortem/event_ev_calibration_tracking.json` (append-only, updated daily by cron)

### 2. Calibration Threshold Conditions

**Promotion-eligible when ALL of the following are true**:
- ✅ n_resolved ≥ 30 (at least 30 HIT/MISS outcomes)
- ✅ n_hit ≥ 10 AND n_miss ≥ 10 (both classes represented)
- ✅ Calibration curve: No bin shows empirical hit rate > 2× predicted_p_hit (gross overconfidence check; e.g., if bin [0.4–0.6] predicts 50%, observed should be ≤100%)
- ✅ Brier score (mean squared error of P(HIT) vs actual outcome) ≤ 0.08 (reasonable fidelity; better calibration tools will lower this bar)

**Monitoring-only when**:
- n_resolved < 30 (insufficient sample)
- Calibration curve shows bins with >2× overconfidence
- Brier > 0.08 (poor fidelity)

**Promotion blocked if**:
- mean_p_hit_among_misses > mean_p_hit_among_hits (inverse correlation; model is systematically wrong)
- >30% of resolved outcomes are DELAYED or NEEDS_REVIEW (join/outcome-determination unreliability)

### 3. Data Sources

**Postmortem records**: `data/postmortems/{snapshot_date}/postmortem_*.json`
- Field: `event_ev_p_hit` (populated by Spec 077 binder, forward-only as of 2026-05-06)
- Field: `resolved_outcome` (HIT/MISS/DELAYED/NEEDS_REVIEW as of postmortem record write)
- Field: `event_date`, `node_id`, `ticker`

**Outcome linkage**: Event occurs → postmortem record written with resolved_outcome field → binder joins `event_ev_p_hit` → calibration tracking reads both

**Backfill status**: No backfill (forward-only per Spec 077); first tracking snapshot 2026-05-06+

---

## Current Calibration Status (Baseline)

As of 2026-05-13:
- **n_resolved**: 7 post-PIT postmortems with event_ev_p_hit + outcome
- **n_hit**: 4 (unknown if representative)
- **n_miss**: 3 (unknown if representative)
- **Brier**: Unknown (not yet computed; requires aggregation)
- **Status**: OBSERVATION_PHASE, well below 30-outcome threshold

**Expected timeline to promotion-eligible**:
- Events from 2026-04-20 onward will have T+5 or T+20 outcomes by ~2026-05-27 and ~2026-06-10
- If event rate is ~0.3 events/day across eligible tickers, expect ~9–15 resolved outcomes per week post-PIT
- Projected 30-outcome milestone: **2026-06-03 ± 7 days** (contingent on join rate and outcome classification quality)

---

## Validation Checklist

Before promotion decision (once n_resolved ≥ 30):

- ✅ Calibration tracking dashboard exists and is updated daily
- ✅ n_hit ≥ 10, n_miss ≥ 10 (both classes represented)
- ✅ Brier ≤ 0.08 (fidelity check)
- ✅ Calibration curve: no bin >2× overconfident
- ✅ mean_p_hit_among_hits > mean_p_hit_among_misses (directional correctness)
- ✅ <30% DELAYED/NEEDS_REVIEW (outcome reliability)
- ✅ Spec 077 binder is wired and functioning (spot-check 10 postmortems for non-null event_ev_p_hit)

---

## Tests / Analysis Commands

```bash
# 1. Audit current postmortem coverage
find data/postmortems/ -name "*.json" -exec grep -l "event_ev_p_hit" {} \; | wc -l

# 2. Spot-check binder join quality
python3 << 'EOF'
import json
import glob

postmortems = glob.glob("data/postmortems/**/postmortem_*.json", recursive=True)
with_ev = [p for p in postmortems if json.load(open(p)).get("event_ev_p_hit") is not None]
print(f"Postmortems with event_ev_p_hit: {len(with_ev)} / {len(postmortems)}")
print(f"Join rate: {100*len(with_ev)/len(postmortems):.1f}%")

# Sample 5 with outcome
outcomes = [json.load(open(p)).get("resolved_outcome") for p in with_ev[:5]]
print(f"Outcome sample: {outcomes}")
EOF

# 3. Pre-compute calibration once n ≥ 30
python3 << 'EOF'
import json
import glob
import numpy as np

postmortems = glob.glob("data/postmortems/**/postmortem_*.json", recursive=True)
records = []
for p in postmortems:
    pm = json.load(open(p))
    if pm.get("event_ev_p_hit") and pm.get("resolved_outcome") in ["HIT", "MISS"]:
        records.append({
            "p_hit": pm["event_ev_p_hit"],
            "outcome": 1 if pm["resolved_outcome"] == "HIT" else 0,
            "ticker": pm.get("ticker"),
            "event_date": pm.get("event_date"),
        })

if len(records) >= 30:
    outcomes = np.array([r["outcome"] for r in records])
    p_hits = np.array([r["p_hit"] for r in records])
    
    brier = np.mean((p_hits - outcomes)**2)
    hit_rate = np.mean(outcomes)
    n_hit = np.sum(outcomes)
    n_miss = len(outcomes) - n_hit
    
    print(f"n_resolved: {len(records)}")
    print(f"n_hit: {n_hit}, n_miss: {n_miss}")
    print(f"Brier: {brier:.4f}")
    print(f"Overall hit rate: {hit_rate:.2%}")
    print(f"Mean P(HIT) among HITs: {p_hits[outcomes==1].mean():.3f}")
    print(f"Mean P(HIT) among MISSes: {p_hits[outcomes==0].mean():.3f}")
    
    # Calibration curve
    bins = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0)]
    for lo, hi in bins:
        mask = (p_hits >= lo) & (p_hits < hi)
        if mask.sum() > 0:
            emp_hit_rate = outcomes[mask].mean()
            mid = (lo + hi) / 2
            print(f"Bin [{lo:.1f}, {hi:.1f}): predicted {mid:.2f}, empirical {emp_hit_rate:.2%} (n={mask.sum()})")
EOF
```

---

## Pass/Fail Criteria

**PASS** (promotion-eligible):
- ✅ n_resolved ≥ 30
- ✅ n_hit ≥ 10, n_miss ≥ 10
- ✅ Brier ≤ 0.08
- ✅ No calibration bin >2× overconfident
- ✅ mean_p_hit_among_hits > mean_p_hit_among_misses
- ✅ <30% outcomes DELAYED/NEEDS_REVIEW

**FAIL** (remain observation-only):
- ❌ n_resolved < 30
- ❌ Brier > 0.08 (poor fidelity)
- ❌ Calibration curve shows >2× overconfidence in any bin
- ❌ mean_p_hit_among_misses ≥ mean_p_hit_among_hits (sign reversal)
- ❌ >30% DELAYED/NEEDS_REVIEW (unreliable outcome determination)

---

## Expected Outcome

After Spec 097 implementation:

1. **Daily calibration tracking**: Dashboard auto-updates with latest postmortems + binder results
2. **Monitoring verdict**: Once 30 outcomes accumulated, compute Brier + calibration curve + verdict gate
3. **Promotion path clear**: If all conditions pass, EV-based ranker weighting becomes Checklist v2 eligible (conditional on Spec 099 orthogonality proof)
4. **Non-promotion clarity**: If Brier > 0.08 or curves show overconfidence, EV remains shadow-only (no promotion); root-cause investigation needed (binder join issues vs. model overconfidence vs. outcome leakage)

---

## Data Constraints

- Forward-only: No backfill before 2026-05-06 (Spec 077 implementation date)
- Limited sample rate: ~0.3 events/day across eligible tickers; slow accumulation
- Outcome delay: T+5 to T+20 resolution; expect 30-outcome milestone ~2026-06-03
- Join reliability: Spec 077 fallback (ticker±7d) may introduce false positives; requires manual spot-check

---

## Out-of-Scope

- ❌ Backfill event-EV P(HIT) before 2026-05-06
- ❌ Change Spec 077 binder join logic (fallback is documented; if unreliable, that's Spec 077 follow-up)
- ❌ Model recalibration (if Brier > 0.08, investigate root cause; do not retrain model)
- ❌ Promote EV to selector (Spec 072 clinical IC conditional; EV is ranker-only candidate)
- ❌ Size by P(HIT) directly (use as conditioning gate only until Spec 099 orthogonality passes)

---

## Timeline

- **2026-05-13**: Spec created
- **2026-05-20**: Calibration tracking dashboard scaffolded; begin daily observation
- **2026-05-27**: Audit postmortem coverage, compute preliminary Brier + calibration curve (if n ≥ 20)
- **2026-06-03**: Target 30-outcome milestone; full verdict gate computed
- **2026-06-10**: Promotion decision gate (if all conditions pass)

---

## Rollback / No-Op Statement

Spec is pure monitoring infrastructure (no scoring changes). If deferred, manual tracking remains: weekly SQL/JSON grep of postmortems + manual calibration computation. If promotion is blocked (Brier > 0.08), mark EV as "requires investigation" and remain shadow-only indefinitely.

---

## Related Specs

- **Depends on**: Spec 077 (event_p_hit binder implementation; forward-only)
- **Blocks**: Spec 072 ranker expansion (EV-conditioned clinical); any EV-based sizing
- **Related to**: Spec 099 (clinical orthogonality audit; must confirm EV is independent of coinvest + clinical)

---

## Priority Note

**MEDIUM-HIGH**: Event-EV is a high-information-value metric once calibration is validated. Accumulation timeline is predictable (~3 weeks to 30-outcome milestone). Once threshold met, unlocks Spec 072 clinical conditional and EV-weighted ranker variants (contingent on Spec 099 orthogonality pass).

Monitor weekly for accumulation progress; promote to Checklist v2 review queue once n_resolved ≥ 30 and all gate conditions pass.
