# Forward Eval IC Monitoring — 2026-05-27 to 2026-06-03

**Decision Gate:** Spec 095/100 ranker model re-validation if IC remains below floor through window end.

---

## Window Summary

| Parameter | Value |
|-----------|-------|
| Window Start | 2026-05-27 |
| Window End | 2026-06-03 |
| Floor Threshold | 0.0200 |
| Current Status (2026-05-27) | BELOW_FLOOR |
| Current IC | -0.0064 |
| Gap to Floor | -0.0264 (-132 bps) |
| N Observations | 10 |
| Horizon | 20 days |

---

## Monitoring Rules

**ABOVE_FLOOR (≥0.0200):**
- IC has recovered above warning threshold
- Monitoring window closes
- Baseline resets; no escalation needed
- System continues normal operation

**BELOW_FLOOR (<0.0200):**
- If persists through 2026-06-03: escalates to ranker model re-validation
- Spec 95/100 remediation path activated
- Review forward evidence for signal leakage or data contamination
- Consider ranker architecture changes (currently frozen per policy_freeze_architecture_2026_04_19.md)

---

## Historical Context

**Prior IC Performance:**
- 2026-05-13 (coinvest_score_z): mean_ic = -0.031 (pooled, 28.6% hit rate)
- 2026-05-13 (pre-cohort clean): mean_ic = -0.051 (11.1% hit rate)
- 2026-05-13 (post-cohort contaminated): mean_ic = -0.008 (60.0% hit rate)
- Verdict at measurement: OBSERVE

**13F Refresh Impact:**
- Q1 2026 13F refresh (~2026-05-15) introduced 4 new managers
- inst_delta_z inflated following cohort change (byte-identical 2026-04-25 to 2026-05-27)
- Ranker IC UNMEASURED: Spec 095 scope gap (tool measured composite_score not final_score)
- Spec 100 correction deployed 2026-05-17; IC tooling fixed post-freeze

**Current Forward Shadow (as of 2026-05-27):**
- Accumulating since 2026-04-03
- ~50+ trading days as of 2026-05-27
- Prior evaluation at ~30d: preliminary positive on coinvest, ranker IC blocked by Spec 095 gap
- Current window: highest-confidence measurement yet (50d accumulation)

---

## Escalation Trigger

**If IC < 0.0200 on 2026-06-03:**

1. Automatically route ranker_ic_recovery_required FAIL event to Town (Phase B extension)
2. Activate Spec 95/100 remediation checklist:
   - Re-validate final_score IC (not composite_score) per Spec 100 correction
   - Profile signal contamination (inst_delta_z, coinvest_score_z, clinical scoring)
   - Compare pre/post 13F refresh IC decomposition
   - Consider ranker architecture freeze lift (policy governance review required)
3. Operator decision: model retrain vs. feature engineering vs. selector-only reversion (Spec 072 path)
4. Production ranker pinned to v1.14.0 until decision + approval

---

## Daily Check Procedure

```bash
# Check latest snapshot
LATEST=$(ls -td data/snapshots/*/ | head -1 | xargs basename)
# Extract IC from: data/snapshots/$LATEST/run_manifest.json
# Look for: gates[].forward_eval.metrics.mean_ic
# Record: date, IC value, gap vs floor, status (ABOVE/BELOW)
# Update: artifacts/readiness/forward_eval_ic_baseline.json
```

**Expected outputs:**
- Baseline JSON updated daily with new observations
- Markdown summary appended with weekly verdict
- Town operator notified if IC crosses threshold (Phase B extension)

---

## Related References

- Spec 095: IC Scope Gap (resolved via Spec 100)
- Spec 100: IC Tooling Correction (deployed 2026-05-17, commit 2faa88e6)
- Policy: Architecture Freeze (policy_freeze_architecture_2026_04_19.md)
- Forward Shadow: inst_delta_z (inst_delta_forward_shadow_T0_2026_04_28.md)
- Forward Shadow: cross_signal (cross_signal_forward_shadow_T0_2026_04_28.md)
- Interpretation Framework: forward_shadows (interp_framework_forward_shadows_2026_04_28.md)

---

## Status

**Monitoring Status:** ACTIVE  
**Last Updated:** 2026-05-27T21:25:00Z  
**Next Check:** 2026-05-28 post-snapshot (expected ~20:30 ET)  
**Final Verdict:** 2026-06-04 (after 2026-06-03 snapshot)
