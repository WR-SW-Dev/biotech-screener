# Spec 100 Multi-Field Early Monitor — 2026-06-24

**Status:** SPEC100_EARLY_MONITOR_ONLY  
**Governance force:** NONE — NOT_PRIMARY_GATE — NOT_PROMOTION_EVIDENCE  
**Horizon:** T+6 (2026-06-18 base → 2026-06-24), N=1 observation  
**Purpose:** Verify all five July 8 runbook fields execute cleanly before the primary gate

---

## Results (T+6, N=1 — not interpretable individually)

| Field | T+6 IC | t-stat | vs 0.02 |
|-------|--------|--------|---------|
| `final_score` | +0.0154 | +0.12 | BELOW |
| `catalyst_decay_w` | **−0.2036** | −1.57 | BELOW |
| `catalyst_score` | −0.0154 | −0.12 | BELOW |
| `coinvest_score_z` | **+0.1928** | +1.48 | BELOW |
| `financial_score` | +0.0771 | +0.58 | BELOW |

All T+5 ICs = 0.0000 across all fields — see data quality note below.

---

## Tool Execution

All five fields ran without errors. Non-default fields write `signal_ic_<field>_*`
output files (no clobbering of production DEM artifacts).

---

## T+5 Zero-IC Anomaly

T+5 IC = 0.0000 for every field (t=0.00, obs=59). This also appears on several
historical dates in the sweep (2026-05-15, 2026-06-02, 2026-06-04, 2026-06-05).

**Probable cause:** Zero-variance forward returns — the price_history.csv entry
for the forward snapshot date may be missing, causing all forward returns to
compute as 0.0 rather than NaN. The tool records obs>0 but Spearman of a constant
series is 0, not NaN.

**Action:** Investigate price_history.csv coverage for 2026-06-23 (T+5 forward).
Does not affect July 8 gate (T+20).

---

## Directional Notes (Monitor Only — N=1)

- `catalyst_decay_w` T+6 = −0.2036: directionally bad given in-sample +0.086
  (Phase C addendum). One observation, meaningless statistically.
- `coinvest_score_z` T+6 = +0.1928: positive within cohort at short horizon.
  Phase C found it weakens at T+20 (circularity). Watch trajectory.
- `financial_score` T+6 = +0.0771: positive directionally. Phase C says financial_score
  IC is robustly negative at T+20 — short-horizon positive is consistent
  (names with less financial stress outperform at T+6 but have other risks at T+20).

None of these observations change anything. July 8 T+20 remains the gate.

---

## Governance Status

```
PRIMARY_GATE_DATE:        2026-07-08
PRIMARY_GATE_HORIZON:     T+20 from 2026-06-18
DEM_AUTHORITY:            LEVEL_0_BLOCKED (unchanged)
MODEL_CHANGES_AUTHORIZED: NO
```
