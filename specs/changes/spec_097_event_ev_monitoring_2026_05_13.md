# Spec 097 — Event-EV p_hit Prospective Monitoring Gate

**Status**: SPEC ONLY (monitoring framework, no binder change)  
**Date**: 2026-05-13  
**Priority**: 5 (blocked on postmortem calibration volume)  
**Investment**: ~1–2 hours (monthly dashboard setup)

---

## Problem Statement

Spec 077 shipped the `event_ev_p_hit` binder **forward-only** (no unsafe backfill). The blocker for any future promotion is: **accumulation of prospective bound HIT/MISS records with non-null event_ev_p_hit**.

Spec 097 defines the monitoring gate: track the count of resolved postmortems with event_ev_p_hit calibration data; do not attempt promotion until ≥30 records exist.

---

## Investment Logic

- Event EV is promising but requires prospective evidence, not backfill
- Monitoring prevents premature promotion decisions
- No binder changes or unsafe joins
- Pure observational tracking until calibration threshold is reached

---

## Exact Evidence Needed

### 1. Prospective Sample Accumulation

Track monthly: count of postmortem records where:
- `verdict ∈ {HIT, MISS}` (resolved outcome)
- `event_ev_p_hit ≠ null` (binder produced a p_hit estimate)
- `event_name ≠ null` (event is non-missing)

Expected source: `artifacts/postmortem/postmortem_observations.csv`

### 2. Calibration Data Quality

Document:
- Are event_ev_p_hit estimates stable (not changing retroactively)?
- Are HIT/MISS labels ground-truth (not provisional)?
- Percentage of resolved postmortems with non-null event_ev_p_hit (coverage %)?

### 3. Threshold for Promotion Evaluation

Define: once ≥30 bound HIT/MISS records with event_ev_p_hit exist, Spec 099 (calibration audit) can run.

### 4. Escalation Criterion

If monthly accumulation rate is <2 per month, event_ev_p_hit will not reach calibration threshold until ~2027. Document this blocker.

---

## Data Constraints

- Forward-only; no backfill allowed
- Use existing postmortem observations (no new data collection)
- Spec 077 binder must be active (no changes to binder logic)

---

## Out-of-Scope

- ❌ Retrain event_ev model
- ❌ Unsafe backfill of historical event_ev_p_hit
- ❌ Promote event_ev_p_hit until ≥30 calibration samples exist
- ❌ Change binder logic (Spec 077 forward-only stands)

---

## Tests / Analysis Commands

```bash
# Check postmortem calibration status
python3 << 'EOF'
import pandas as pd
pm = pd.read_csv('artifacts/postmortem/postmortem_observations.csv')

# Count resolved postmortems with event_ev_p_hit
calibrated = pm[
    (pm['verdict'].isin(['HIT', 'MISS'])) &
    (pm['event_ev_p_hit'].notna())
]
print(f"Resolved postmortems: {pm['verdict'].isin(['HIT', 'MISS']).sum()}")
print(f"With event_ev_p_hit: {len(calibrated)}")
print(f"Coverage: {len(calibrated) / pm['verdict'].isin(['HIT', 'MISS']).sum() * 100:.1f}%")

# Group by month to estimate accumulation rate
pm['date'] = pd.to_datetime(pm['as_of_date'])
pm['month'] = pm['date'].dt.to_period('M')
monthly = calibrated.groupby('month').size()
print(f"\nMonthly accumulation:\n{monthly}")
EOF

# Monitor postmortem freshness
ls -lh artifacts/postmortem/ | tail -5
```

---

## Pass/Fail Criteria

**PASS:**
- ✅ Calibration sample count tracked (current count documented)
- ✅ Monthly accumulation rate estimated
- ✅ Escalation criterion defined (≥30 for promotion evaluation)
- ✅ Binder data quality confirmed (coverage % documented)

**FAIL:**
- ❌ Cannot determine sample count from postmortem data
- ❌ Binder is retroactively modifying past event_ev_p_hit (safety violation)

---

## Expected Timeline

- **Now (2026-05-13)**: Establish baseline sample count
- **2026-06-13**: First monthly check (estimate 2–4 new calibrated samples)
- **2026-07-13**: Second monthly check (estimate 4–8 cumulative)
- **~2026-09**: Potential 30-sample threshold if accumulation rate holds
- **2026-10**: Spec 099 calibration audit eligible

---

## Rollback / No-Op Statement

Monitoring documentation only. No binder changes. If accumulation stalls (monthly rate <1), escalate to ops: event_ev_p_hit may not reach calibration threshold until 2027. No-op outcome: continue forward-only collection until threshold is reached or explicit decision to stop monitoring.

---

## Related Specs

- **Depends on:** Spec 077 (binder must be forward-only)
- **Unblocks:** Spec 099 (calibration audit, when ≥30 samples exist)
