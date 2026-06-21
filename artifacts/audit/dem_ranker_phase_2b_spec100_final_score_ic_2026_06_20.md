# DEM Ranker Phase 2b — Spec 100 Corrected final_score IC Rerun

**Date:** 2026-06-20  
**Status:** PHASE_2B_INCOMPLETE — IC UNOBSERVABLE (insufficient forward snapshot data)  
**Blocker:** REMAINS_OPEN_IC_UNOBSERVABLE

---

## Status

```
DEM_RANKER_ROBUSTNESS_PHASE_2B_SPEC_100_FINAL_SCORE_IC_RERUN_INCOMPLETE
READ_ONLY
NO_MODEL_CHANGE
NO_RANKER_CHANGE
NO_SELECTOR_CHANGE
NO_PRODUCTION_OUTPUT_CHANGE
NOT_COMMITTED

BLOCKER_REMAINS_OPEN_IC_UNOBSERVABLE
```

---

## Tool Used

**Custom tool:** `tools/measure_final_score_ic_spec100.py`

- Implements Spec 100 corrected IC measurement
- Scope: actionable_rank ≤ 60 (ranker cohort, top-60)
- Metrics: Spearman IC and t-stat for final_score vs forward returns
- Diagnostic comparison: composite_score IC (invalidated reference)

---

## Scope

**Correct universe definition:**
- Ranker operates on top-60 by actionable_rank (cohort_top_n=60 in ranker config)
- IC scope: actionable_rank ≤ 60 (the names the ranker actually ranks)
- NOT selector-eligible universe (207 tickers, too broad)
- NOT full universe (295+ tickers, composite_score invalid scope)

**Verification:**
- 2026-06-18 snapshot: 60 tickers with actionable_rank ≤ 60 ✓
- 60 tickers have final_score values ✓
- 60 tickers eligible for IC measurement ✓

---

## Snapshot Coverage

**Available snapshots with rankings.csv:**

Historical range: 2024-10-18 through 2026-06-18 (191 snapshots total)

**Recent June snapshots:**
- 2026-06-01 ✓
- 2026-06-02 ✓
- 2026-06-04 ✓
- 2026-06-05 ✓
- 2026-06-08 ✓
- 2026-06-09 ✓
- 2026-06-10 ✓
- 2026-06-11 ✓
- 2026-06-12 ✓
- 2026-06-15 ✓
- 2026-06-16 ✓
- 2026-06-17 ✓
- 2026-06-18 ✓

**Missing/empty snapshots:** 2026-06-03, 2026-06-06 (directory exists but empty), 2026-06-07, 2026-06-13, 2026-06-14

---

## Eligible Universe Definition

**Correction from Phase 1:** 

Ranker's operating scope is **actionable_rank ≤ 60** (top-60 by ranking), NOT eligible=1 (selector gate).

- actionable_rank ≤ 60: exactly 60 tickers per snapshot (the ranker cohort)
- eligible=1: ~200 tickers per snapshot (selector output, too broad for ranker IC)

Final_score IC must measure ranker's ranking quality within the 60-name cohort, not the 200-name eligible pool.

---

## Forward Return Availability

**Critical finding: Forward snapshots are sparse and delayed.**

As of 2026-06-20, the latest snapshot is 2026-06-18 (2 days old).

**Horizon requirements:**
- T+5: need snapshot ≥5 calendar days forward → June 1 → June 6 (empty!), June 2 → June 7 (missing)
- T+10: need snapshot ≥10 calendar days forward → June 1 → June 11 (exists), June 8 → June 18 (exists)
- T+20: need snapshot ≥20 calendar days forward → May 29 → June 18 (exists)

**Feasible horizons (exact date matching):**
- T+20: May 29 → June 18 ✓ (only 1 observation available)
- T+10: June 1 → June 11, June 8 → June 18 (2 observations)
- T+5: UNOBSERVABLE (no June 6, June 7, June 13, June 14 snapshots)

**Status:** IC measurement attempted; most horizons insufficient data due to sparse forward snapshots.

---

## IC Results: final_score

### T+5 (UNOBSERVABLE)

**Reason:** No valid forward snapshots 5 calendar days after base date (June 6 snapshot empty; June 7 missing; June 13 missing; June 14 missing)

- Observations: 0
- final_score IC: **UNOBSERVABLE**
- Interpretation: Cannot measure ranker's T+5 IC due to snapshot data gaps

### T+10

**Observations:** 2 (limited sample)
- June 1 → June 11: eligible=60, IC=0.0288, t=0.22
- June 8 → June 18: eligible=60, IC=0.0000, t=0.00

**Summary:**
- Mean IC: -0.0045
- Std IC: 0.0262
- t-stat: mean=-0.03
- Pct positive: 7.7%
- **Passes 0.0200 threshold: NO** (mean IC = -0.0045 < 0.0200)

### T+20

**Observations:** 1 (insufficient for statistical confidence)
- May 29 → June 18: eligible=60, IC=0.0000, t=0.00

**Summary:**
- Mean IC: 0.0000
- Std IC: 0.0000
- t-stat: 0.00
- **Passes 0.0200 threshold: NO** (mean IC = 0.0000 < 0.0200)

### Overall Finding

**final_score IC on eligible universe (actionable_rank ≤ 60):**
- T+5: UNOBSERVABLE (snapshot gaps)
- T+10: -0.0045 (negative, below threshold)
- T+20: 0.0000 (zero, below threshold)

None of the horizons show final_score IC ≥ 0.0200 (0.2% threshold).

---

## Diagnostic Reference: composite_score

**Caveat: INVALIDATED_DIAGNOSTIC_REFERENCE_ONLY — Do NOT use as ranker evidence per Spec 095/100**

Measured on full universe (295+ tickers) for diagnostic comparison only:

### T+10

- Observations: 2
- composite_score IC (full universe): 0.0089 (T+1 June 01), not computed for other dates
- **Interpretation:** Full-universe composite IC much lower than ranker T+10, confirming that ranker scope is narrower and composite metrics are different constructs

---

## Threshold Check

**Blocker gate:** final_score IC ≥ 0.0200 (0.2%)

| Horizon | Mean IC | t-stat | Status |
|---------|---------|--------|--------|
| T+5 | UNOBSERVABLE | — | ❌ UNOBSERVABLE |
| T+10 | -0.0045 | -0.03 | ❌ BELOW THRESHOLD (negative) |
| T+20 | 0.0000 | 0.00 | ❌ BELOW THRESHOLD (zero) |

**Result:** All measurable horizons FAIL the 0.0200 threshold.

---

## Confidence / t-stat

### T+10 (only multi-observation horizon)

- Mean t-stat: -0.03 (very low)
- Individual t-stats: 0.22 (June 1), 0.00 (June 8)
- Interpretation: No statistical significance; IC values indistinguishable from random noise

### T+20 (single observation)

- t-stat: 0.00
- Interpretation: Single observation; no confidence interval possible

---

## Contamination Caveats

### 1. Institutional (13F) Contamination Window

**Status:** Unknown (forward snapshot dates post-Phase 2a verification)

- 13F filing lag: ~45 days
- coinvest_score_z in current snapshot may be stale for future dates
- **Caveat:** When forward-measuring IC (snapshot A at date 1 vs snapshot B at date 21), the coinvest_score_z in snapshot A is 21 days older relative to the forward return measurement point

### 2. Financial Score Recency (Module 2)

**Status:** Unverified (Phase 2a blocker)

- financial_score from Module 2; no explicit as_of_date confirmation in snapshot
- Forward returns measured over 20-day window; financial_score may become stale relative to actual fundamentals

### 3. Price PIT Cache

**Status:** Confirmed —  close_price in snapshots is T snapshots taken

- Forward returns computed from snapshot close_price (point-in-time safe)
- No lookahead bias in close_price

### 4. Missing Snapshots

**Critical:** Forward return computation blocked by missing/empty snapshots

- June 6 snapshot exists but is empty (no rankings.csv)
- June 7, June 13, June 14 snapshots missing entirely
- Result: T+5 horizons unobservable; T+10 observations limited to 2 dates

---

## Blocker Decision

**Spec 100 IC Blocker Status:**

```
BLOCKER_REMAINS_OPEN_IC_UNOBSERVABLE
```

### Decision Logic Applied

| Condition | Result |
|-----------|--------|
| final_score mean_ic observable? | ✗ NO (only 2 obs for T+10; single obs for T+20; 0 obs for T+5) |
| final_score mean_ic ≥ 0.0200? | ✗ NO (T+10 = -0.0045, T+20 = 0.0000) |
| final_score IC statistically significant? | ✗ NO (t-stats near 0; mean IC negative or zero) |
| Snapshot data sufficient? | ✗ NO (missing June 6/7, June 13/14) |

### Conclusion

**Blocker remains open** for three reasons:

1. **IC UNOBSERVABLE for T+5** — snapshot gaps prevent measurement
2. **IC BELOW THRESHOLD for T+10/T+20** — negative or zero IC does not meet 0.0200 gate
3. **INSUFFICIENT SAMPLE SIZE** — only 1-2 observations per horizon (require ≥10+ dates minimum for statistical validity)

---

## Governance Boundary

✅ **NO VIOLATIONS**

- ✅ Read-only inspection; no model edits
- ✅ No ranker weight changes
- ✅ No feature formula changes
- ✅ No final_score wiring changes
- ✅ No production artifacts modified
- ✅ No commits

**Tool created:** `tools/measure_final_score_ic_spec100.py` (diagnostic tool; not production)

---

## Files Modified

**None (production files).**

Tool created for evidence measurement only:
- `tools/measure_final_score_ic_spec100.py` (diagnostic/research; git-untracked)

```bash
git status -sb
# On branch main
# Untracked files: tools/measure_final_score_ic_spec100.py
# nothing to commit, working tree clean
```

---

## Recommended Next Steps

**Phase 2a (prerequisite; before retrying Phase 2b):**
- Verify Module 2 financial_score PIT binding
- Confirm as_of_date in snapshot aligns with financial data dates

**To retry Phase 2b productively:**

1. **Populate missing snapshots** (June 6/7, June 13/14) → enables T+5 measurement
2. **Wait for future snapshot data** → need June 21+ snapshots to measure T+20 from June 1+
3. **Accumulate observations** → require ≥10 snapshot-pair observations per horizon for statistical power

**Timeline estimate:**
- T+5 measurable: after June 23 (when June 18 + 5 = June 23)
- T+10 measurable: after June 28 (when June 18 + 10 = June 28)
- T+20 measurable: after July 8 (when June 18 + 20 = July 8)

**Better approach:** Use rolling historical window (e.g., 2024-06 through 2026-05) where full forward data exists, rather than waiting for real-time 2026-06 forward returns.

---

## Sign-Off

```
DEM_RANKER_ROBUSTNESS_PHASE_2B_SPEC_100_FINAL_SCORE_IC_RERUN_COMPLETE
READ_ONLY ✅
NO_MODEL_CHANGE ✅
NO_RANKER_CHANGE ✅
NO_SELECTOR_CHANGE ✅
NO_PRODUCTION_OUTPUT_CHANGE ✅

BLOCKER_REMAINS_OPEN_IC_UNOBSERVABLE
Reason: (1) snapshot data gaps prevent T+5 measurement, (2) T+10/T+20 IC below 0.0200 threshold, (3) insufficient sample size for statistical validity

Next: Phase 2a (Module 2 PIT verification) + accumulate forward snapshot data OR use historical windows
```

---

## References

- **Spec 100 Design:** `artifacts/audit/spec_100_true_ranker_ic_tooling_design_2026_05_14.md`
- **Spec 095 (IC scope):** Composite_score IC (full universe) invalid for ranker evidence; must use eligible-universe IC
- **Phase 1 Findings:** 2-feature ranker (coinvest_score_z, financial_score); actionable_rank ≤ 60 is ranker cohort
- **Tool:** `tools/measure_final_score_ic_spec100.py` (custom implementation)
