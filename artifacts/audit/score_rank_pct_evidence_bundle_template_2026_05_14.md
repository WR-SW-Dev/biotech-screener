# Spec 091: score_rank_pct Evidence Bundle Template

**Status:** TEMPLATE (do not populate until post-13F-refresh + post-cohort-window + sufficient forward-return window)

**Purpose:** Spec 091 says no ranker/selector/sizing changes are justified by `score_rank_pct` WARN streak alone. This template structures the evidence required to consider action.

---

## Governance Rule (Spec 091)

**The WARN signal:**
- `score_rank_pct` IC dashboard entered WARN streak (date unknown; check artifacts/alerts/ for exact entry date)

**What is NOT authorized:**
- ❌ Selector weight changes (0.65/0.35 coinvest/inst_delta)
- ❌ Ranker feature additions or reweighting
- ❌ Sizing logic edits
- ❌ Composite construction
- ❌ Signal suppression or filtering
- ❌ IC threshold adjustments

**What IS required before any action:**
- ✓ Full evidence bundle (CRT + multi-horizon IC + PIT audit + Checklist v2)

---

## CRT: Cohort Regime Test

**Definition:** Is the WARN streak explained by the cohort-distortion regime (2026-04-25 through ~2026-05-15)?

**Method:**
1. Partition ic_health_monitor data into pre-cohort (2026-04-01 through 2026-04-24) and post-cohort (2026-04-25 onward)
2. Compute `score_rank_pct` IC before and after cohort expansion
3. Test if WARN streak coincides with cohort expansion

**Expected findings (if cohort-driven):**
```
Pre-cohort IC: stable or healthy (if any)
Post-cohort IC: drops to WARN level
Self-heal expected post-13F-refresh (~2026-05-15): IC normalizes without model changes
```

**Pass threshold:**
- If WARN streak is coincident with cohort expansion AND ic_health recovers post-13F-refresh without model changes → cohort distortion was likely cause; no ranker action needed
- If WARN predates cohort expansion OR persists post-refresh → true degradation signal; proceed to Multi-Horizon IC

**Interpret cautiously:**
- Cohort regime also contaminates `inst_delta_z` (confirmed locked at 0.743 mean since 04-25)
- If WARN involves inst_delta-dependent signals, cohort distortion is likely confounding variable

---

## Multi-Horizon IC Validation

**Definition:** Does `score_rank_pct` show independent predictive power across multiple forward-return horizons?

**Method:**
```
Compute IC on:
- T+5 forward returns (short-term)
- T+20 forward returns (medium-term)
- T+60 forward returns (long-term, if data available)
- T+1Y forward returns (if 1-year returns available, typically post-2026-05-01 for 2026-04-data)
```

**Required sample:** >= 50 snapshots per horizon (to support t-test)

**Pass threshold:**
```
At least 2 of {T+5, T+20, T+60} show IC >= +0.04 (t > 1.5)
OR
At least 1 horizon shows IC >= +0.06 (t > 2.0)
AND
No horizon shows IC < -0.02 (consistent anti-predictivity)
```

**Interpretation:**
- If pass: `score_rank_pct` has real predictive power despite WARN streak → investigate why IC degraded (data quality? signal saturation? regime change?)
- If fail: `score_rank_pct` shows no independent IC across horizons → WARN streak is justified; no model action recommended; may retire signal

---

## PIT Integrity Audit

**Definition:** Are the input fields feeding `score_rank_pct` computation accurate and non-contaminated?

**Fields in `score_rank_pct`:** (check exact formula in production code)
- Typically includes: ranking score, rank percentile, optionally: coinvest_score or other inputs

**Audit steps:**
1. Confirm `score_rank_pct` definition and input fields (read production code)
2. Check for missing/NaN values in input fields (should be <5% across universe)
3. Validate rank computation logic (is rank consistent with score ordering?)
4. Check for data freshness issues (is ranking based on stale scores?)
5. Confirm no double-counting (is coinvest or inst_delta used twice in formula?)

**Pass threshold:**
- Missing values < 5% across all dates in window
- Rank computation is deterministic (same score → same rank always)
- No obvious stale-data artifacts
- No double-counted signals

**Fail examples:**
- Ranking uses stale coinvest_score → inflates apparent IC during distortion window
- Formula has double-counted coinvest (selector uses 0.65 × coinvest, ranking also uses coinvest directly) → inflated IC
- Missing values > 10% in certain tickers → survivorship bias

---

## Checklist v2 Readiness

**Definition:** If `score_rank_pct` shows real IC (passes Multi-Horizon test) and data is clean (passes PIT audit), is it eligible for promotion to production input?

**Checklist v2 modules:**
1. **FM (Feature Marginality):** D7/D8/D9 equivalent — is it orthogonal to selector signals?
2. **Bootstrap:** Does IC estimate have stable confidence intervals across subsamples?
3. **FDR (False Discovery Rate):** Is this the only signal being tested, or are others also under review? (Multiple comparison adjustment)
4. **LOSO (Leave-One-Snapshot-Out):** Does IC hold when each snapshot's data is excluded?
5. **Year Stability:** Does IC persist across calendar years / regimes?
6. **Domain Audit:** Is the signal's interpretation consistent with domain knowledge?

**Ready-to-assess?** Only if CRT + Multi-Horizon + PIT audit all pass AND decision tree branch (below) permits.

---

## Decision Tree: When to Run the Bundle

### Branch 1: WARN Clears Post-13F-Refresh (Most Likely)

**Condition:** CRT test shows WARN streak coincides with cohort expansion; post-13F-refresh snapshot shows ic_health recovery and WARN clears.

**Action:** Close Spec 091 with no model change. Document that cohort distortion was confounding variable.

**Timeline:** By 2026-05-20 (post-13F-refresh).

### Branch 2: WARN Persists Post-13F-Refresh

**Condition:** CRT test shows WARN predates cohort expansion OR persists after refresh.

**Action:** Run Multi-Horizon IC validation.

**Timeline:** 2026-05-22 onward (wait for sufficient forward-return window post-refresh).

### Branch 2a: Multi-Horizon IC Passes

**Condition:** Multi-Horizon test shows real predictive power (IC >= +0.04 on at least 2 horizons).

**Action:** Run PIT Integrity Audit to understand why IC is real despite WARN.

**Timeline:** 1–2 days (code review + data validation).

### Branch 2b: Multi-Horizon IC Fails

**Condition:** Multi-Horizon test shows no significant IC or consistent anti-predictivity.

**Action:** Retire `score_rank_pct` from IC dashboards; close Spec 091 with no model change (WARN was accurate signal of degradation; confirmed via evidence).

**Timeline:** Immediate; no further action needed.

### Branch 2c: PIT Audit Finds Data Issue

**Condition:** PIT Integrity Audit reveals missing values, stale data, or double-counting.

**Action:** Fix the data/formula issue; re-run Multi-Horizon IC on corrected data.

**Timeline:** Depends on fix complexity; typically 1–3 days.

### Branch 2d: PIT Audit Clean + Multi-Horizon Passes

**Condition:** Data is clean and IC is real; both CRT and Multi-Horizon pass.

**Action:** Run Checklist v2 battery (FM, bootstrap, FDR, LOSO, year stab, domain audit) before considering any production change.

**Timeline:** 3–5 days (Checklist v2 is extensive).

---

## Required Outputs (If Running)

1. `score_rank_pct_crt_analysis_2026_XX_XX.md` (CRT test results + narrative)
2. `score_rank_pct_multi_horizon_ic_2026_XX_XX.csv` (IC by horizon + t-stats)
3. `score_rank_pct_pit_audit_2026_XX_XX.md` (data quality findings)
4. `score_rank_pct_checklist_v2_2026_XX_XX.md` (if proceeding past PIT audit)
5. `spec_091_evidence_bundle_verdict_2026_XX_XX.md` (decision + action)

---

## Guardrails

❌ Do NOT change selector/ranker/sizing before completing evidence bundle  
❌ Do NOT suppress WARN from dashboards (alert is correct behavior until evidence disproves it)  
❌ Do NOT use WARN streak as sole justification for edits  
❌ Do NOT skip CRT test; it directly addresses whether cohort distortion is confounding  
❌ Do NOT interpret T+5 IC in isolation; require multi-horizon consistency  

---

## Timeline Estimate

```
2026-05-15: Post-13F-refresh snapshot available
2026-05-20: CRT test complete (most cases branch to "close"; no further action)
2026-05-22: If WARN persists, Multi-Horizon IC test begins
2026-05-24: PIT Audit (if needed)
2026-05-26: Checklist v2 (only if all prior gates pass)
2026-05-29: Final verdict
```

**Best case:** Branch 1 triggers; Spec 091 closes by 2026-05-20 with no model change.

**Worst case:** All branches trigger; evidence bundle complete by 2026-05-29; decision then depends on Checklist v2 results + operator judgment.

---

## References

- **Spec 091:** Governance memo (no code; no weights; evidence-only)
- **Cohort regime:** `memory/regime_post_cohort_change_distortion_2026_04_28.md`
- **13F refresh preflight:** `artifacts/audit/13f_q1_2026_refresh_preflight_2026_05_14.md`
- **Checklist v2:** `common/stats/` (FM, bootstrap, FDR, LOSO, year stab, domain modules)
