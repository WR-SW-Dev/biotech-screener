# DEM Ranker July 8 IC Remeasurement Runbook

**Date:** 2026-06-20 (created)  
**Effective:** 2026-07-08 (execution date)  
**Purpose:** Execute final IC gate; decide DEM unblocking or Phase 3 override

---

## Purpose

On 2026-07-08, measure IC on the 2026-06-18 base date at T+20 horizon for the DEM
ranker output AND a set of candidate/baseline signals.

**Scope expanded 2026-06-20 (Catalyst Validation Addendum).** Originally this gate
measured `final_score` only. It now also serves as the **forward out-of-sample test**
for `catalyst_decay_w` — the in-sample-only Phase 3 candidate that failed look-back OOS
(see Phase C memo addendum). Measure all of:

```
final_score        (the DEM ranker output — primary gate, unchanged)
catalyst_decay_w   (Phase 3 candidate — forward OOS confirmation)
catalyst_score     (raw catalyst, secondary)
coinvest_score_z   (institutional baseline — expected weak within cohort)
financial_score    (financial baseline — expected negative)
```

This is the **final confirmation gate** for DEM changes AND the decisive forward test
for the catalyst Phase 3 lane.

Decision (final_score):
- **IC >= 0.0200:** Unblock DEM (proceed with tuning or Phase 3)
- **IC < 0.0200:** Confirm blocker (await operator Phase 3 override or maintain freeze)
- **IC unobservable:** Extend measurement window; retry on 2026-07-15

Joint outcome logic (final_score × catalyst_decay_w) is in Step 4 below.

---

## Preconditions

Before executing this runbook, verify:

```
1. ✅ Date is 2026-07-08 or later
2. ✅ 2026-06-18 base snapshot exists (verified at: data/snapshots/2026-06-18/)
3. ✅ 2026-07-08 or later forward snapshot exists (at minimum)
4. ✅ Rank: Phase C decision memo locked (blocking in place)
5. ✅ No DEM changes have been made (ranker_v2_pairwise.py unchanged)
6. ✅ DEM is still LEVEL_0_BLOCKED
```

If any precondition fails, **do not proceed** — notify operator and troubleshoot.

---

## Required Inputs

### Snapshot Dates

```
Base date: 2026-06-18
Forward date: >= 2026-07-08 (20+ days forward)
Horizon: T+20 calendar days
```

### Tool

```
File: tools/measure_final_score_ic_spec100.py
Purpose: Compute Spearman IC between final_score and forward returns
Scope: eligible universe only (actionable_rank <= 60)
Verified: Yes (created 2026-06-20)
```

---

## Procedure

### Step 1: Verify Snapshot Existence

```bash
cd /mnt/c/Projects/biotech_screener/biotech-screener

# Check base snapshot
ls -lh data/snapshots/2026-06-18/rankings.csv
# Expected: File exists, >800 KB

# Check forward snapshots (minimum 2026-07-08)
ls data/snapshots/ | grep -E "2026-07-0[8-9]|2026-07-1[0-9]|2026-07-2[0-9]|2026-07-3[0-1]"
# Expected: At least one snapshot on or after 2026-07-08
```

**Stop if:** Base or forward snapshot missing. Notify operator.

### Step 2: Run IC Measurement (all five fields)

The tool now supports `--score-field` (added 2026-06-20, default `final_score`).
Run once per field. The measurement window MUST span base + horizon, or forward
returns silently drop to NaN (methodological catch found 2026-06-20) — set
`--end-date` to at least 2026-07-15 so the T+20 forward snapshot loads.

```bash
cd /mnt/c/Projects/biotech_screener/biotech-screener

for FLD in final_score catalyst_decay_w catalyst_score coinvest_score_z financial_score; do
  echo "=== $FLD ==="
  python3 tools/measure_final_score_ic_spec100.py \
    --score-field "$FLD" \
    --start-date 2026-06-18 --end-date 2026-07-15 \
    --horizons 20
done
```

- Default field (`final_score`) writes the original DEM-gate artifacts; non-default
  fields write `signal_ic_<field>_*` files (no clobbering).
- Primary universe: actionable_rank <= 60. Also run `--start-date`/`--end-date` on the
  full eligible set if a `--segment` option is later added (currently cohort-scoped).
- Forward snapshot: 2026-07-08 or nearest valid later snapshot within tolerance.

**Record for EACH field:**
- mean_ic, t-stat, observation count
- pass/fail vs 0.0200
- date of execution

### Step 3: Compare to Threshold

```
Threshold: 0.0200 (Spec 100 primary gate)

If final_score T+20 IC >= 0.0200:
  → PASS (proceed to Step 4a)

If final_score T+20 IC < 0.0200:
  → FAIL (proceed to Step 4b)

If IC is NaN or unobservable:
  → UNOBSERVABLE (proceed to Step 4c)
```

### Step 4a: IC Passes (>= 0.0200)

```
Status: DEM_IC_GATE_PASSED_PENDING_OPERATOR_REVIEW

Actions:
  1. Archive result to artifacts/audit/dem_ranker_july8_ic_pass_2026_07_08.md
  2. Email operator: "DEM IC gate passed. Ready for unblocking review."
  3. Unlock Phase 2 / Phase 3 decision
  4. Follow operator directive for next work (tuning vs redesign)
```

### Step 4b: IC Fails (< 0.0200)

```
Status: DEM_IC_GATE_FAILED_BLOCKER_CONFIRMED

Actions:
  1. Archive result to artifacts/audit/dem_ranker_july8_ic_fail_2026_07_08.md
  2. Email operator: "DEM IC gate failed (IC = [value]). Phase C blocker confirmed."
  3. Await operator Phase 3 redesign override memo (if desired)
  4. Maintain DEM freeze if no override memo received by 2026-07-15
```

### Step 4c: IC Unobservable

```
Status: DEM_IC_GATE_UNOBSERVABLE_RETRY_REQUIRED

Actions:
  1. Archive partial result
  2. Identify missing forward snapshot(s)
  3. Notify operator: "Forward snapshot gap prevents IC measurement. Retry on [date]."
  4. Retry on 2026-07-15 (one week later)
```

---

## Step 5: Joint Outcome Logic (final_score × catalyst_decay_w)

Added 2026-06-20. After recording all five fields, apply the joint outcome.
This is the **forward out-of-sample test** for the catalyst Phase 3 candidate.

```
If final_score PASSES (>= 0.0200) and catalyst_decay_w PASSES:
  DEM_IC_GATE_PASSED_WITH_CATALYST_SUPPORT
  → Operator review may consider Phase 3 design (current ranker viable AND
     catalyst confirmed forward — strongest case for a Phase 3 lane).

If final_score FAILS and catalyst_decay_w PASSES:
  DEM_CURRENT_RANKER_BLOCKED_BUT_CATALYST_PHASE3_CANDIDATE_REOPENED
  → Current ranker stays blocked. catalyst_decay_w cleared its forward OOS test;
     operator may approve a DESIGN-ONLY Phase 3 catalyst lane. Still no implementation
     without a separate operator-approved Phase 3 memo.

If final_score FAILS and catalyst_decay_w FAILS:
  DEM_BLOCKER_CONFIRMED_AND_CATALYST_LANE_CLOSED_PENDING_MORE_DATA
  → Maintain freeze. catalyst_decay_w is then 0/2 out-of-sample (look-back failed,
     forward failed) — treat as a Feb–May artifact, not a candidate. Revisit only
     with materially more data.

If catalyst_decay_w is UNOBSERVABLE (forward snapshot gap):
  CATALYST_FORWARD_OOS_UNOBSERVABLE
  → Do NOT infer predictive value either way. Retry when forward data exists.
```

**Reference expectations (from validation, so results are interpretable):**
- coinvest_score_z: expected WEAK within cohort (circularity) — not a candidate regardless.
- financial_score: expected NEGATIVE — confirms baseline behavior; negative weight is coherent.
- catalyst_score (raw): secondary; decayed variant is the lead.

### Hard rule

```
No July 8 result automatically changes ranker behavior.
All implementation still requires a separate operator-approved Phase 3 memo.
A passing forward OOS REOPENS the design conversation; it does not authorize code.
```

---

## Metrics to Record

Archive the following in a new audit artifact (one row per field):

```
Execution Date: [YYYY-MM-DD]
Base Snapshot: 2026-06-18
Forward Snapshot: [YYYY-MM-DD]
Horizon: T+20 days
Cohort Universe: [count] tickers (actionable_rank <= 60)

field               mean_IC      t-stat   obs   threshold   status
final_score         [+/-0.xxxx]  [+/-x.x] [n]   >=0.0200    PASS|FAIL|UNOBS
catalyst_decay_w    [+/-0.xxxx]  [+/-x.x] [n]   >=0.0200    PASS|FAIL|UNOBS
catalyst_score      [+/-0.xxxx]  [+/-x.x] [n]   >=0.0200    PASS|FAIL|UNOBS
coinvest_score_z    [+/-0.xxxx]  [+/-x.x] [n]   >=0.0200    PASS|FAIL|UNOBS
financial_score     [+/-0.xxxx]  [+/-x.x] [n]   >=0.0200    PASS|FAIL|UNOBS

Joint outcome (Step 5): [DEM_IC_GATE_PASSED_WITH_CATALYST_SUPPORT |
  DEM_CURRENT_RANKER_BLOCKED_BUT_CATALYST_PHASE3_CANDIDATE_REOPENED |
  DEM_BLOCKER_CONFIRMED_AND_CATALYST_LANE_CLOSED_PENDING_MORE_DATA |
  CATALYST_FORWARD_OOS_UNOBSERVABLE]

Result: [narrative summary]
```

**Caveat to record:** a single forward date is one observation. Note the limited
sample; meaningful significance still requires accumulating June+ snapshots
(block-bootstrap as in the validation artifact), not just the 2026-07-08 point.

---

## Decision Threshold

### Spec 100 Threshold: >= 0.0200

This is the primary gate for DEM authority.

```
IC >= 0.0200:  Unblock (historically rare; strong evidence)
IC in [0.0100, 0.0200):  Below threshold (typical fail)
IC < 0.0100:  Well below threshold (strong evidence against DEM)
IC < 0.0000:  Negative IC (ranker is anti-predictive)
```

### Hard Rule

```
Passing the July 8 IC gate does NOT automatically authorize code changes.
It authorizes operator review.

Failing the gate DOES confirm the blocker remains in place.
```

---

## Decision Outcomes

### Outcome A: IC >= 0.0200

```
DEM_IC_GATE_PASSED_PENDING_OPERATOR_REVIEW

DEM authority moves to LEVEL_1_TESTING (design + test environment).

Operator may authorize:
  - Phase 3 DEM tuning (weight adjustments on historical test set)
  - Phase 3 redesign (new features, new cohort, new ranker)
  - Metadata implementation (Tier 1 fields)

No live production changes until separate approval.
```

### Outcome B: IC < 0.0200

```
DEM_IC_GATE_FAILED_BLOCKER_CONFIRMED

DEM authority remains LEVEL_0_BLOCKED.

Options:
  1. Maintain freeze (conservative; reassess Q3 2026)
  2. Operator approves Phase 3 redesign override (explicit memo required)
  3. Operator approves metadata-only improvements (non-DEM work)
```

### Outcome C: IC Unobservable

```
DEM_IC_GATE_UNOBSERVABLE_RETRY_REQUIRED

DEM authority remains LEVEL_0_BLOCKED.

Actions:
  1. Identify snapshot gaps
  2. Retry on 2026-07-15 or when forward data available
  3. If still unobservable by 2026-07-22: escalate to operator
```

---

## Failure Modes

### Failure Mode 1: Missing Base Snapshot

```
Error: data/snapshots/2026-06-18/ does not exist

Action:
  - Verify snapshot generation for 2026-06-18
  - Check data/snapshots/ directory
  - Notify operator if snapshot is genuinely missing
```

### Failure Mode 2: Missing Forward Snapshot

```
Error: No snapshot >= 2026-07-08 found

Action:
  - Check snapshot generation calendar
  - Identify gap dates (e.g., 2026-07-08 generated? 2026-07-09?)
  - Retry on next available snapshot date
```

### Failure Mode 3: Tooling Crashes

```
Error: tools/measure_final_score_ic_spec100.py fails

Action:
  1. Check error message
  2. Verify tool exists and is unmodified (compare to 2026-06-20 version)
  3. If modified: restore original from git
  4. Retry
  5. If persistent: notify operator (may need tool repair)
```

### Failure Mode 4: IC Measurement Returns NaN

```
Error: IC computation yields NaN (insufficient variance, constant scores, etc.)

Action:
  1. Check forward snapshot integrity
  2. Verify eligible universe has >=10 tickers
  3. Verify final_score is populated for cohort
  4. Archive the NaN result as "unobservable" (Failure Mode C)
  5. Retry on next snapshot
```

---

## Archive Requirements

After execution, create a new audit artifact:

```
artifacts/audit/dem_ranker_july8_ic_measurement_2026_07_08.md
```

Contents:

```
# DEM Ranker July 8 IC Measurement Result

**Execution Date:** 2026-07-08  
**Status:** [PASS | FAIL | UNOBSERVABLE]

## Metrics
- Base snapshot: 2026-06-18
- Forward snapshot: [YYYY-MM-DD]
- Horizon: T+20
- Eligible universe: [count]
- final_score T+20 IC: [value]
- t-stat: [value]
- Observations: [count]

## Decision
[Summarize outcome A, B, or C]

## Next Steps
[Recommend action per outcome]
```

---

## Governance Boundary

```
✅ This runbook is READ_ONLY diagnostic execution
✅ No ranker code changes permitted
✅ No weight modifications
✅ No feature formula changes
✅ No production output changes
✅ Only measurement, archiving, reporting

❌ Do not approve Phase 3 or unblock without operator memo
❌ Do not implement metadata without separate approval
❌ Do not change DEM configuration during measurement
```

---

## Operator Checklist

If Phase C memo is locked and July 8 arrives:

```
□ Verify date is 2026-07-08 or later
□ Verify snapshots exist (base 2026-06-18, forward >=2026-07-08)
□ Run IC measurement (tools/measure_final_score_ic_spec100.py)
□ Record final_score T+20 IC value
□ Compare to 0.0200 threshold
□ Follow outcome A, B, or C procedure
□ Archive result to artifacts/audit/
□ Notify operator of gate outcome
□ Do not make DEM changes until operator approves next step
```

---

## Key Reminders

```
1. This is a GATE, not an approval mechanism.
   Passing the gate unblocks review; it doesn't approve changes.

2. If IC < 0.0200, the Phase C blocker remains in place.
   Operator may override with explicit memo, or freeze DEM.

3. If IC is unobservable, retry on next available snapshot.
   Do not wait indefinitely; escalate if still blocked by 2026-07-22.

4. The historical IC already failed (April T+20 = -0.0955, May = -0.0188).
   Real-time July 8 IC is the final confirmation gate.
```

---

**Runbook Ready for 2026-07-08 Execution**

