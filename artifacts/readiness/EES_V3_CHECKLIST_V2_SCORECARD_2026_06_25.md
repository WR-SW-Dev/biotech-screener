# EES v3 Checklist v2 Scorecard — 2026-06-25

**Status:** `DIAGNOSTIC_WIRING_APPROVED` — Promotion to production BLOCKED until all gates pass  
**Freeze status:** ACTIVE  
**Operator decision:** `CHECKLIST_V2_DIAGNOSTIC_WIRING_APPROVED_WITH_REGIME_CONFOUNDED_EVIDENCE` (2026-06-25)

---

## Gate Summary

| Gate | Name | Status | Evidence |
|------|------|--------|---------|
| G1 | Signal card | **PASS** | IC > 0 at 21/42/63d; coverage 87.2% in production |
| G2 | PIT backtest (FM incremental) | **PASS** | POSITIVE_SIGNIFICANT across all horizons (updated 2026-06-25) |
| G3 | Bootstrap / FDR | **PASS** | Carried from original 4/5 scorecard |
| G4 | Forward evidence (WS4) | **PASS ✓** | t_adj=+4.17 > 1.65 on 26 native dates; n_eff=3.3 caveat noted |
| G5 | LOSO robustness | **PASS** | Positive in early sub-sample (2020-2023); late sub-sample weakens but consistent with all signals |

**Overall: 5/5 PASS — Checklist v2 gates all cleared (2026-06-25).**

⚠️ Gate clearance does NOT equal freeze lift. Two separate governance requirements remain unmet:
- **20d shadow gate: UNMET** (0 completed observations) — required before production promotion
- **Operator explicit approval** — required at freeze-lift review

---

## Gate Detail

### G1 — Signal Card

- `priced_move_pct` coverage: 87.2% in current production (up from 8–33% in historical PIT archive)
- `ees_v3_score` present in all rankings.csv as `ees_v3_score` column since 2026-04-14
- Correlation with `final_score`: +0.033 (diagnostic overlay, not in production path)
- Event filter: ~215 eligible tickers with `catalyst_days` in today's snapshot

**Status: PASS**

---

### G2 — PIT Backtest (updated 2026-06-25)

**Full-sample PIT (76 dates, 2020-01-31 → 2026-04-16):**

| Signal | 21d IC | 21d t | 42d IC | 42d t | 63d IC | 63d t | Verdict |
|--------|--------|-------|--------|-------|--------|-------|---------|
| **ees_v3_score** | +0.0247 | +2.07 | +0.0350 | +2.65 | +0.0371 | +2.36 | **POSITIVE_SIGNIFICANT ✓** |
| ees_v2_score | −0.0637 | −2.19 | −0.0806 | −2.97 | −0.0698 | −2.02 | NEGATIVE_SIGNIFICANT ✗ |
| conditional_expected_move | +0.0129 | +2.28 | +0.0167 | +2.52 | +0.0232 | +3.32 | POSITIVE_SIGNIFICANT ✓ |
| conditional_misprice_score | +0.0629 | +1.66 | +0.0942 | +2.34 | +0.1074 | +2.49 | POSITIVE_SIGNIFICANT ✓ |

Script: `scripts/research/pit_backtest_ees_v3.py` (commit `63cc68f5`)  
Output: `artifacts/research/ees_v3_pit_backtest_20260625.json` (gitignored)

**Coverage robustness test (2026-06-25):**

Operator requested supplementary test at priced_move_pct coverage ≥ 50%.  
Result: **STRUCTURALLY IMPOSSIBLE** — PIT archive max coverage is 33% (mean 15%).  
Available sub-samples (≥25%, ≥30%) collapse into the 2024-2026 recent era — indistinguishable from late-sub-sample regime shift.

Operator classification: `INCONCLUSIVE_REGIME_CONFOUNDED`

Operator decision: Accept INCONCLUSIVE as sufficient for G2/diagnostic wiring. Not sufficient for production promotion.

Key finding: `conditional_expected_move` holds in both full-sample and coverage-filtered samples (consistent positive IC across horizons). v3 composite weakens in recent era but does not reverse sign.

Script: `scripts/research/pit_backtest_ees_v3_coverage_filtered.py` (commit `40deabf9`)

**Status: PASS (for diagnostic wiring purposes) — with explicit INCONCLUSIVE_REGIME_CONFOUNDED label on coverage-filtered result**

---

### G3 — Bootstrap / FDR

Carried from original EES v3 4/5 PASS scorecard (2026-04-14).  
Not re-run in this session (no new data, no model changes).

**Status: PASS (carried)**

---

### G4 — Forward Evidence Gate (WS4) — THE ACTIVE BLOCKER

**Threshold:** dependence-adjusted t ≥ 1.65 on native production IC series

**Native v3 epoch:** 2026-04-14 (first snapshot with `ees_v3_score` natively populated)

**Current state (as of 2026-06-25):** `artifacts/ees_v3_monitor_native_20260625.json`

| Signal | IC | rho1 | n_eff | t_adj | Gate |
|--------|-----|------|-------|-------|------|
| `ees_v3_score` | **+0.1581** | 0.774 | **3.3** | **+4.17** | **PASS ✓** |
| `conditional_misprice_score` | +0.1620 | 0.818 | 3.0 | +3.76 | PASS ✓ |
| `conditional_expected_move` | +0.0150 | 0.479 | 8.1 | +1.11 | WAIT |

Scored dates: 26 (out of 50 native; remainder lack 21d completed returns)  
Re-scored contaminated dates: 0 (native-only mode)

**Critical caveats:**
- n_eff=3.3 — rho1=0.774 autocorrelation collapses 26 raw observations to ~3 effective independent periods
- IC=+0.158 is >4× the PIT backtest estimate (+0.025–+0.037) — unusually high; may reflect favorable early conditions
- `ees_v3_score` distribution: WARN (24% at ceiling, spread=3.392) — z-score normalization hitting limits
- `conditional_expected_move` has NOT cleared WS4 (t_adj=+1.11, gap=+0.54)

Prior contaminated reading (from model_documentation, 433 snapshots including re-scored):
- `ees_v3_score`: t_adj=−1.23 (contaminated by pre-fix unit mismatch in re-scored data)
- `conditional_expected_move`: t_adj=+0.99

The native-only run reverses this: `ees_v3_score` and `conditional_misprice_score` clear the gate; `conditional_expected_move` has not yet cleared.

**20d shadow gate:** 0 completed observations as of 2026-06-23. Clock-dependent. Separate from WS4.

**Status: PASS ✓ — WS4 cleared 2026-06-25 (n_eff caveat noted; freeze still blocked by shadow gate)**

---

### G5 — LOSO Robustness

Early sub-sample (2020-01-31 → ~2023-02): IC=+0.047, t=+2.78 at 42d — POSITIVE_SIGNIFICANT  
Late sub-sample (2023-03 → 2026-04): IC=+0.023, t=+1.17 at 42d — weakens but positive

Same weakening pattern present in all signals (conditional_misprice, conditional_gap, conditional_base_rate). Regime shift interpretation, not model failure.

`conditional_expected_move` is the exception — remains marginal-to-significant in late sub-sample at 63d.

**Status: PASS (full-sample LOSO is positive; late-era weakening is not a disqualifier)**

---

## Freeze-Lift Remaining Blockers (as of 2026-06-25)

| Requirement | Status | Notes |
|-------------|--------|-------|
| Checklist v2 all 5 gates | **CLEARED ✓** | G4 cleared 2026-06-25 with n_eff caveat |
| 20d shadow gate (20 completed obs) | **UNMET** | 0 observations; clock-dependent (~3-4 more weeks) |
| Operator explicit approval | **REQUIRED** | Not granted automatically by gate clearance |

---

## What Is and Is Not Approved

### Approved now (diagnostic wiring only)
- Running `tools/ees_v3_forward_monitor.py --native-only` to track WS4 progress
- Non-production shadow reporting
- Additional monitoring and artifact generation
- Governance readiness evidence accumulation

### Blocked until G4 clears AND operator explicitly approves
- Freeze lift
- `final_score` integration
- Selector or ranker weight changes
- Sizing changes
- Production gate changes
- Trading or portfolio behavior changes

---

## Production Coverage Gap — Explicit Label

The historical PIT archive has never had priced_move_pct coverage > 33%.  
Current production has 87.2% coverage.  
**There is no PIT-safe analog to the current production data regime.**

The shadow monitor and the WS4 forward gate are the only valid production-coverage tests. This gap must remain explicitly labeled in all future governance memos.

Governance classification: `COVERAGE_GAP_NOTED | NO_HISTORICAL_PIT_ANALOG_FOR_87pct_COVERAGE`

---

## Next Action Required

Monitor WS4 progress daily via:
```
python3 -m tools.ees_v3_forward_monitor --native-only \
    --output artifacts/ees_v3_monitor_native_$(date +%Y%m%d).json
```

Forward gate clears when `t_adj >= 1.65` for `ees_v3_score` (or `conditional_expected_move` as the leading candidate). Bring back to operator for freeze-lift review.

---

*Governance: DIAGNOSTIC_ONLY | NO_PRODUCTION_CHANGES | FREEZE_ACTIVE*  
*Scripts: `scripts/research/pit_backtest_ees_v3.py`, `scripts/research/pit_backtest_ees_v3_coverage_filtered.py`, `tools/ees_v3_forward_monitor.py`*
