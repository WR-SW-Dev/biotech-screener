# EES v3 Raw Veto Shadow Status — 2026-06-25

**Governance:** FREEZE_ACTIVE | DIAGNOSTIC_ONLY | NO_PRODUCTION_DECISIONING | NO_PORTFOLIO_ACTION
**Lead policy:** raw_veto_core
**Snapshot date:** 2026-06-25
**Shadow gate (20d observations):** MET

---

## Today's Veto Card

| Metric | Value |
|--------|-------|
| Eligible names | 290 |
| Ranker top-Q | 43 |
| **Vetoed by EES v3** | **8** |
| Surviving selection | 35 |

**Vetoed tickers:** STOK, TNGX, CMPS, XENE, ORIC, ABVX, IRON, TSHA

**Failure mode breakdown:**

- `no_options_coverage`: 0
- `dilution_overhang`: 0
- `market_already_priced`: 6
- `catalyst_too_far`: 1
- `stale_proxy`: 0
- `other`: 2

| Ticker | Final Score | EES v3 | Failure Modes | Catalyst Days |
|--------|------------|--------|---------------|---------------|
| STOK | 0.639 | -1.137 | market_already_priced | 97d |
| TNGX | 0.638 | -0.623 | market_already_priced | 68d |
| CMPS | 0.642 | -0.531 | other | 5d |
| XENE | 0.631 | -0.780 | other | 37d |
| ORIC | 0.645 | -0.735 | market_already_priced | 68d |
| ABVX | 0.634 | -1.238 | market_already_priced | 68d |
| IRON | 0.614 | -0.945 | market_already_priced | 68d |
| TSHA | 0.616 | -1.359 | catalyst_too_far, market_already_priced | 260d |

---

## Cumulative Shadow Performance

Positive veto alpha = selected names outperforming vetoed names (veto correct).

| Horizon | N Settled | Mean Veto Alpha | Selected Excess | Vetoed Excess | Alpha+ Rate |
|---------|-----------|-----------------|-----------------|---------------|-------------|
| 5d | 50 | +2.3% | +0.2% | -2.1% | 61.7% |
| 10d | 45 | +4.2% | +0.2% | -4.0% | 78.6% |
| 20d | 35 | +7.4% | +0.0% | -7.4% | 81.2% |

---

## Shadow Gate Progress

Gate: 20 completed 20d observations required before freeze-lift review.

| Gate | Required | Complete | Remaining | Status |
|------|----------|----------|-----------|--------|
| 20d obs | 20 | 35 | 0 | **MET** ✓ |

## Historical PIT Baseline (raw_veto_core)

From `ees_v3_promotion_simulator_2026_06_25.py` across 76 PIT snapshots 2020-2026.

| Metric | PIT Value |
|--------|-----------|
| IC | 0.0639 |
| NW t-stat | 2.36 |
| Mean excess 63d | +3.53% |
| Mean excess LATE | +7.1% |
| Veto freq (avg/snap) | 7.0 |

---

## Governance

```
FREEZE_ACTIVE
DIAGNOSTIC_ONLY
RAW_VETO_CORE_LEAD_CANDIDATE
NO_PRODUCTION_DECISIONING
NO_PORTFOLIO_ACTION
PRODUCTION_PROMOTION = NOT_AUTHORIZED (pending 20d gate + operator approval)
```

