# Stressed Optionality Confirmation Shadow Test

> Classification: `STRESSED_OPTIONALITY_CONFIRMATION_SHADOW_TEST_NO_MODEL_CHANGE`
> Date: 2026-06-26
> Scope: Shadow guardrail only. No model, ranker, selector, or production change.

---

## Rule Definition

```
If financial_stress is primary rank driver (|fi_contrib| >= |ci_contrib|):

  Path 1 — EES-flagged suppression:
    if ees_v3_score <= -0.75
    → SUPPRESSED_EES_FLAGGED

  Path 2 — Extreme stress unconfirmed:
    if fi_z <= -1.0
    AND NOT (ees_v3 > 0 AND momentum >= 60.0)
    → SUPPRESSED_EXTREME_STRESS_UNCONFIRMED

Otherwise: ELIGIBLE
```

---

## Phase 3 Results

| Metric | Value |
|--------|------:|
| Dates tested | 16 |
| Dates with ≥1 suppression | 16 |
| Mean suppressions per date | 9.75 |
| Actual mean basket ret | -0.0033 |
| Shadow mean basket ret | +0.0044 |
| **Improvement** | **+0.0078** |
| Pass-through violations | 0 |

### Phase 3 Target Suppression

| Ticker | Role | Appearances | Suppressed | Rate | Expected |
|--------|------|------------:|-----------:|-----:|---------|
| ABVX | loser | 15 | 8 | 53% | SUPPRESSED |
| ALKS | winner | 16 | 0 | 0% | ELIGIBLE |
| CELC | loser | 16 | 11 | 69% | SUPPRESSED |
| DRUG | loser | 13 | 13 | 100% | SUPPRESSED |
| SYRE | winner | 15 | 0 | 0% | ELIGIBLE |
| TNGX | winner | 16 | 0 | 0% | ELIGIBLE |

---

## Non-Phase-3 (YTD Clean) Results

| Metric | Value |
|--------|------:|
| Dates tested | 104 |
| Dates with ≥1 suppression | 103 |
| Mean suppressions per date | 6.08 |
| Actual mean basket ret | +0.0065 |
| Shadow mean basket ret | +0.0090 |
| Basket improvement | +0.0025 |
| Pass-through violations (TNGX/ALKS/SYRE) | **0** |

---

## YTD Summary

| Window | Mean actual ret | Mean shadow ret | Improvement |
|--------|----------------:|----------------:|------------:|
| Phase 3 | -0.0033 | +0.0044 | +0.0078 |
| Non-Phase-3 | +0.0065 | +0.0090 | +0.0025 |
| YTD | +0.0051 | +0.0084 | +0.0033 |

---

## Verdict

**`SHADOW_GUARDRAIL_IMPROVES_PHASE3_WITHOUT_WINNER_DEGRADATION`**

---

## Governance Verdict

```
Classification:     STRESSED_OPTIONALITY_CONFIRMATION_SHADOW_TEST_NO_MODEL_CHANGE
Model change:       NO
Ranker change:      NO
Production wiring:  NO (shadow-only output)

Rule parameters:    EES_SUPPRESS=-0.75
                    EXTREME_STRESS_FI_Z=-1.0
                    MOMENTUM_CONFIRM=60.0
```
