# Drawdown Gate — Operator Acceptance Decision
**Date**: 2026-06-24  
**Monitoring Day**: 12  
**Decision**: ACCEPT — market-driven; continue observation  
**Authority**: Operator approval 2026-06-24

---

## Gate Status

| Metric | Value | Threshold | Status |
|--------|-------|-----------|--------|
| Portfolio return (vs entry) | +7.16% | — | Positive |
| XBI return (vs entry) | +10.04% | — | Broad sector rally |
| Drawdown vs XBI | **-2.88pp** | -2.0pp TRIP / -5.0pp EXIT | **TRIPPED** |
| Consecutive breach | Day 1–12 (brief improvement Day 11) | — | Persistent |

## Drawdown Trend (pp vs XBI)

```
Jun-11: -6.70  ← Day 1
Jun-12: -5.84
Jun-15: -3.80
Jun-16: -2.56
Jun-17: -4.32
Jun-18: -5.34
Jun-19: -3.43
Jun-22: -3.43  (carried)
Jun-23: -2.51  ← narrowest
Jun-24: -2.88  ← Day 12
```

## Operator Assessment

The drawdown reflects a broad biotech sector rally (XBI +10.04% since entry) outpacing the screener's clinical-stage concentrated names. The portfolio has positive absolute return (+7.16%). The -2.88pp gap is above the -5.0pp emergency exit threshold.

**Decision: ACCEPT as market-driven.** The screener is designed for clinical-stage name selection, not for tracking XBI momentum. Underperformance during a broad sector rally is consistent with the model's risk profile.

## Conditions

- **Emergency exit trigger unchanged**: ≤ -5.0pp vs XBI → immediate exit, no further operator review required
- **Next review**: 2026-07-01 h20d gate; drawdown re-assessed at that checkpoint
- **DRUG position**: -24.69% does not independently trigger gate. Under separate review.
- **HOLD verdict**: Unchanged. Gate acceptance does not authorize new trades.

## Provenance

- `TRADING_AUTHORIZATION_2026-06-16.md` — Current HOLD authorization
- `artifacts/monitoring/daily_2026_06_24.json` — Day 12 gate data
- `PHASE2_IC_CHECKPOINT_EXTENSION_2026_06_24.md` — Companion extension decision
