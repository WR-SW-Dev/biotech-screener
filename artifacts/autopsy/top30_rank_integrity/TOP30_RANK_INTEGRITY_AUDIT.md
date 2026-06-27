# Top-30 Rank Integrity Audit

> Classification: `TOP30_RANK_INTEGRITY_AUDIT_DIAGNOSTIC_NO_MODEL_CHANGE`  
> Date: 2026-06-26  
> Scope: Diagnostic only. No model, ranker, selector, or production change.

---

## Overall Verdict

**`TOP30_ACCURATE_COVERAGE_GAPS_ARE_DATA_LIMITATION_NOT_BUG`**

---

## 1. Basket Match — rankings.csv vs decision_portfolio.json

| Metric | Value |
|--------|------:|
| Dates audited | 57 |
| Name match (rankings vs portfolio) | 57/57 |
| Order match | 57/57 |
| All match | YES |

No mismatches detected across all audited dates.

---

## 2. Sorting Key Verification

| Metric | Value |
|--------|------:|
| Key used | `actionable_rank` |
| Dates with backtest return verified | 46/46 |
| All verified | YES |

Verification: recomputed `top20_ret_5d` from `actionable_rank` top-20 names and `price_history.csv`. Tolerance = 1e-6.

---

## 3. PIT Date Alignment

| Metric | Value |
|--------|------:|
| fwd_date matches backtest CSV | 53/57 |
| Future price violations | 0 |
| Clean | YES |

---

## 4. Return Coverage

| Metric | Value |
|--------|------:|
| Mean coverage (verifiable dates) | 99.4% |
| Data-gap dates (non-trading / sparse fwd) | 11 |
| Dates with <90% coverage (excl. data gaps) | 0 |
| Clean (≥90% on verifiable dates) | NO |

### Low-coverage dates

| Date | Coverage |
|------|--------:|
| 2026-04-03 | 0.0% |
| 2026-04-11 | 0.0% |
| 2026-04-12 | 0.0% |
| 2026-04-25 | 0.0% |
| 2026-06-04 | 0.0% |
| 2026-06-05 | 0.0% |
| 2026-06-11 | 0.0% |
| 2026-06-12 | 0.0% |
| 2026-06-16 | 0.0% |
| 2026-06-17 | 0.0% |
| 2026-06-18 | 0.0% |

---

## 5. Bucket Monotonicity

| Metric | Value |
|--------|------:|
| Dates where top-10 outperformed ranks 31-60 | 14/57 |
| Phase 3 mean IC (all eligible) | 0.050099 |

---

## 6. Rank Perturbation

| Metric | Value |
|--------|------:|
| `actionable_rank` sort = `final_score` sort | 57/57 |

---

## 7. Phase 3 Attribution

| Metric | Value |
|--------|------:|
| Dates | 16 |
| Mean top-30 5d return | -0.003345 |
| Mean residual vs XBI | -0.015206 |

---

## Governance Verdict

```
Classification: TOP30_RANK_INTEGRITY_AUDIT_DIAGNOSTIC_NO_MODEL_CHANGE
Model change:      NO
Ranker change:     NO
Snapshot write:    NO (output to artifacts/autopsy/ only)
Production wiring: NO

Basket match:       CLEAN — rankings.csv top-30 matches decision_portfolio.json
Sorting key:        VERIFIED — actionable_rank matches backtest
PIT alignment:      CLEAN
Return coverage:    POOR (<90%)

Overall: TOP30_ACCURATE_COVERAGE_GAPS_ARE_DATA_LIMITATION_NOT_BUG
```
