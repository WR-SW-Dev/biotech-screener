# Bucket Drift Acceptance Memo — 2026-06-24

**Gate:** `bucket_drift_vs_policy`  
**Status:** FAIL — ACCEPTED AS LEGACY PATH C ARTIFACT  
**Observed drift:** 91–180d bucket 13.3% actual vs 55% policy (Δ41.7pp)  
**Decision:** Accept without remediation; no new trades; monitor for natural normalization.

---

## Current State

The weekly readiness scorecard flags `bucket_drift_vs_policy` as FAIL (threshold: ≥25pp deviation). The deviation is driven by the 91–180d catalyst bucket:

| Bucket | Policy Target | Actual | Deviation |
|--------|--------------|--------|-----------|
| 0–30d  | 10%          | ~43%   | +33pp     |
| 31–90d | 35%          | ~44%   | +9pp      |
| 91–180d | 55%         | 13.3%  | **–41.7pp** ← FAIL |

---

## Root Cause

The 91–180d shortfall is a direct consequence of the Path C governance override (approved 2026-05-28), which permitted the 0–30d bucket to reach 40–45% to capture concentrated institutional consensus in near-term catalyst names (COGT, RVMD, SYRE, PRAX at time of construction).

Path C is now **FORMALLY CLOSED** (2026-06-24, see `PATH_C_FORMAL_CLOSURE_2026_06_24.md`). No new near-term catalyst positions have been added since the HOLD was instated (2026-06-16).

---

## Why Acceptance Is Appropriate

1. **No new trades possible.** Portfolio is in HOLD. Bucket drift cannot worsen.
2. **Natural normalization underway.** Multiple 0–30d positions (DNTH, CMPS, TRVI, COGT, ALMS, PRAX) have binary catalysts clustering at Jun 30–Jul 1. As they resolve and roll off or are exited post-catalyst, the near-term bucket will shrink and the 91–180d bucket will recover.
3. **Scorecard FAIL is a trailing artifact, not forward risk.** The policy was intentionally overridden for Path C; the drift reflects authorized past positioning, not current model misbehavior.
4. **Emergency exits remain armed.** Hard drawdown exit (≤−5.0pp vs XBI) and CMPS breach watch (binary event risk) are unchanged.

---

## Monitoring Plan

- **Daily:** Catalyst expirations tracked via `daily_path_c_monitoring.sh`.
- **Weekly scorecard:** Expect `bucket_drift` FAIL to persist through ~Jul 1 catalyst cluster, then begin recovering.
- **Re-evaluate:** If bucket drift FAIL persists past 2026-07-15 (i.e., post–catalyst-cluster normalization), escalate to policy recalibration under Phase 3 design.

---

## Authorization

**Operator decision:** ACCEPT bucket drift FAIL as legacy Path C artifact.  
**Date:** 2026-06-24  
**Condition:** No new trades during HOLD; monitor normalization through catalyst cluster.  
**Escalation trigger:** FAIL persists past 2026-07-15 without improvement trend.
