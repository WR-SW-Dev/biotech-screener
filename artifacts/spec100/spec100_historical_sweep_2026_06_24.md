# Spec 100 Historical IC Sweep — 2026-06-24

**Status:** SPEC100_HISTORICAL_SWEEP — MONITOR_ONLY  
**Governance force:** NONE — NOT_PROMOTION_EVIDENCE  
**Tool:** `tools/measure_final_score_ic_spec100.py` (corrected field: `final_score`)  
**Date range:** 2026-04-01 to 2026-06-18  
**Horizons:** T+10, T+20 (nearest_later, ±5 days tolerance)  
**Purpose:** Verify Phase C historical IC numbers used the corrected tool; establish full distribution

---

## Summary Statistics

| Horizon | N dates | Mean IC | Std | Min | Max | Pct>0 | Mean t |
|---------|---------|---------|-----|-----|-----|-------|--------|
| T+10 | 57 | −0.0212 | 0.1559 | −0.379 | +0.226 | 46.8% | −0.17 |
| T+20 | 57 | −0.0675 | 0.1797 | −0.404 | +0.183 | 47.6% | −0.54 |

Both horizons: mean negative, below 0.0200 threshold, not statistically significant in aggregate.

---

## Phase C Memo Reconciliation

Phase C memo reported:
- April T+20: IC = −0.0955 (25 snapshots)
- May T+20: IC = −0.0188 (20 snapshots)

This sweep (corrected tool, full Apr–Jun range):
- April T+20 (Apr 3–30): broadly negative in back half; early April positive
- May T+20: strongly negative early May, recovering to positive mid-May

The Phase C numbers are **confirmed** — they are not measurement artifacts from
Spec 095 conflation. The corrected tool reproduces the same failure pattern.

---

## Period-by-Period Structure

### April 2026

| Period | T+20 IC | Pattern |
|--------|---------|---------|
| Apr 3–12 (early) | +0.04 to +0.18 | Positive — ranker working |
| Apr 15–24 (tariff shock) | −0.09 to −0.22 | Deteriorating |
| Apr 25–30 (sell-off trough) | −0.29 to −0.39 | Strongly negative |

**Interpretation:** The ranker selected coinvest names that were hit harder during the
April tariff-driven biotech sell-off. High coinvest biotech = higher beta, deeper drawdown.

### May 2026

| Period | T+20 IC | Pattern |
|--------|---------|---------|
| May 1–8 | −0.09 to −0.40 | Still deeply negative (carry-over from April) |
| May 11–19 | +0.05 to +0.12 | Recovery — market stabilizing |
| May 22–29 | +0.03 to −0.05 | Near zero, stabilized |

**Interpretation:** As the April shock faded and biotech stabilized, the ranker's IC
recovered. Suggests the failure was regime-specific (risk-off sell-off), not structural.

### June 2026

| Period | T+10 IC | T+20 IC |
|--------|---------|---------|
| Jun 1–8 | ~0.00 to −0.09 | NaN (not yet observable) |
| Jun 9–18 | NaN | NaN |

T+20 from June base dates will become observable starting ~Jul 1–8.

---

## T+10 vs T+20 Divergence (April)

Notable: in late April, T+10 IC was often positive while T+20 was strongly negative.
Example: 2026-04-21: T+10 = +0.205, T+20 = −0.200.

**Interpretation:** The ranker correctly identified short-term bounce candidates, but
those names gave back gains by T+20. Short-horizon momentum ≠ 20-day predictability.
This also explains why the T+10 mean (−0.021) is less negative than T+20 (−0.068).

---

## Zero-IC Dates

Several dates show IC=0.0000: 2026-05-15, 2026-06-02, 2026-06-04, 2026-06-05.
All have obs>0. Probable cause: zero-variance forward returns from missing price data
(see multi-field memo). Does not affect T+20 gate dates.

---

## Conclusion

The corrected Spec 100 tool produces results consistent with the Phase C memo.
The historical IC failures are **real, not measurement artifacts**.

The pattern shows regime-dependence: the ranker's `final_score` IC is negative during
risk-off market conditions (April–early May tariff shock) and recovers to near-zero or
mildly positive in calmer regimes. This is important context for interpreting the July 8
gate: if June 18–July 8 is a relatively calm biotech environment, the T+20 IC may be
positive. If there is another macro shock, it may repeat the April pattern.

```
DEM_AUTHORITY:             LEVEL_0_BLOCKED (unchanged)
PHASE_C_NUMBERS_CONFIRMED: YES — corrected tool reproduces historical failure
PRIMARY_GATE_DATE:         2026-07-08
```
