# Snapshot Comparison

> **ANALYSIS ONLY** — This report is generated from production data for operator review. It does not represent trading recommendations or model changes.

**A:** `data/snapshots/2026-04-13/rankings.csv` (2026-04-13, 297 rows)
**B:** `data/snapshots/2026-04-27/rankings.csv` (2026-04-27, 297 rows)
**Generated:** 2026-04-27 21:08 UTC

## Top-N Overlap

- **N:** 30
- **Overlap:** 23 (76.7%)
- **Added:** 7 — ALKS, AXSM, BCRX, BLTE, ERAS, NRIX, SLN
- **Removed:** 7 — ACAD, CTNM, IRON, JBIO, NGNE, TARS, TSHA

## Schema Changes

- Common columns: 284
- Only in A: has_catalyst_signal.1
- Only in B: adv_20d, adv_60d, cohort_membership, cohort_membership_streak, conditional_base_rate, conditional_bucket, conditional_confidence, conditional_expected_move, conditional_expected_move_z, conditional_gap_score

## Largest Score Drifts (top 15)

| Ticker | Score | Before | After | Delta |
| --- | --- | --- | --- | --- |
| IMMP | financial_score | 14.0136 | 35.9973 | 21.9836 |
| SLN | financial_score | 41.9601 | 20.3611 | -21.599 |
| LEGN | financial_score | 76.25 | 59.375 | -16.875 |
| CLYM | financial_score | 31.6736 | 48.5069 | 16.8333 |
| OMER | financial_score | 50.1596 | 36.6049 | -13.5546 |
| RCUS | financial_score | 35.6076 | 23.3224 | -12.2852 |
| TSHA | financial_score | 64.234 | 54.3333 | -9.9007 |
| GHRS | financial_score | 51.5 | 41.9601 | -9.5399 |
| ANAB | financial_score | 28.1434 | 37.6531 | 9.5096 |
| TENX | financial_score | 69.5957 | 60.3333 | -9.2624 |
| AGIO | financial_score | 45.6867 | 54.6667 | 8.98 |
| CADL | financial_score | 67.9202 | 59.3333 | -8.5869 |
| TCRX | financial_score | 38.3334 | 46.6077 | 8.2743 |
| JBIO | financial_score | 76.7 | 69.5 | -7.2 |
| GERN | financial_score | 57.867 | 64.6667 | 6.7996 |
| JBIO | clinical_score_v2_z | -0.2971 | -1.4389 | -1.1418 |
| CADL | quality_overlay_score | -0.0 | -1.0 | -1.0 |
| TSHA | quality_overlay_score | -0.0221 | -1.0 | -0.9779 |
| SLN | quality_overlay_score | -0.0388 | -1.0 | -0.9612 |
| GERN | inst_delta_z | -0.4639 | 0.2573 | 0.7212 |

