# Stressed Optionality Weekly Calibration — 2026-05-22

> Classification: `STRESSED_OPTIONALITY_FORWARD_MONITOR_NO_MODEL_CHANGE`
> Gate status: **DEGRADED**
> Window: 2026-05-18 → 2026-05-22 (5 dates)

## Suppression Activity

| Metric | Value |
|--------|------:|
| Mean suppressed per date | 8.6 |
| Max suppressed in a day | 10 |
| Dates with REVIEW_REQUIRED | 4 |

**Reason codes:**
- EXTREME_STRESS_UNCONFIRMED: 36
- EES_FLAGGED: 7

## Forward Return (T+5 outcomes)

| Metric | Value |
|--------|------:|
| Dates observed | 5 / 5 |
| Dates pending | 0 |
| Mean original top-30 ret | +0.0273 |
| Mean shadow top-30 ret | +0.0125 |
| **Mean delta (shadow − actual)** | **-0.0148** |

## Gate Status: DEGRADED

```
PROMISING:            mean_delta > 0 with >= 3 observed outcomes
NEUTRAL:              mean_delta near zero
DEGRADED:             mean_delta < -0.001 with >= 3 outcomes
INSUFFICIENT_DATA:    < 3 observed T+5 outcomes
```

**Note:** Do not tune rule parameters based on this memo. Parameters are locked.
