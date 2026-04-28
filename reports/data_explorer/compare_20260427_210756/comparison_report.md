# Snapshot Comparison

> **ANALYSIS ONLY** — This report is generated from production data for operator review. It does not represent trading recommendations or model changes.

**A:** `data/snapshots/2026-03-27/rankings.csv` (2026-03-27, 294 rows)
**B:** `data/snapshots/2026-04-27/rankings.csv` (2026-04-27, 297 rows)
**Generated:** 2026-04-27 21:07 UTC

## Top-N Overlap

- **N:** 30
- **Overlap:** 0 (0.0%)
- **Added:** 30 — ABVX, ALKS, ANNX, AXSM, BCRX, BLTE, CELC, CMPX, COGT, DNTH
- **Removed:** 0 — (none)

## Schema Changes

- Common columns: 218
- Only in B: actual_implied_move_pctile, adv_20d, adv_60d, atm_iv_change_5d, calendar_confidence, catalyst_date_lower, catalyst_date_precision, catalyst_date_upper, catalyst_source_filed_at, cohort_membership

## Largest Score Drifts (top 15)

| Ticker | Score | Before | After | Delta |
| --- | --- | --- | --- | --- |
| ABCL | financial_score | 5.0 | 78.6667 | 73.6667 |
| CCCC | financial_score | 9.2802 | 74.0 | 64.7198 |
| RARE | financial_score | 15.4133 | 79.85 | 64.4367 |
| TRDA | financial_score | 5.0 | 65.0 | 60.0 |
| GERN | financial_score | 5.0 | 64.6667 | 59.6667 |
| HRTX | financial_score | 12.574 | 67.1667 | 54.5926 |
| FHTX | financial_score | 6.141 | 58.5714 | 52.4305 |
| AURA | financial_score | 5.0 | 56.3333 | 51.3333 |
| KYTX | financial_score | 27.1895 | 72.875 | 45.6855 |
| VOR | financial_score | 34.3857 | 79.5 | 45.1143 |
| ENTA | financial_score | 23.9119 | 67.25 | 43.3381 |
| ELDN | financial_score | 23.2678 | 65.0 | 41.7322 |
| DNTH | financial_score | 45.5369 | 5.2003 | -40.3366 |
| ARWR | financial_score | 58.9474 | 20.096 | -38.8513 |
| GLUE | financial_score | 25.0144 | 63.7143 | 38.6999 |
| GERN | inst_delta_z | -1.3114 | 0.2573 | 1.5687 |
| DNTH | coinvest_score_z | 1.914 | 1.0142 | -0.8998 |
| ENTA | inst_delta_z | 0.7772 | -0.0389 | -0.8161 |
| ENTA | coinvest_score_z | -0.8044 | -0.0386 | 0.7658 |
| AURA | clinical_score_v2_z | -1.1827 | -0.4468 | 0.7359 |

