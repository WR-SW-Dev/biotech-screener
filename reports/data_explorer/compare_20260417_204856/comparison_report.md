# Snapshot Comparison

> **ANALYSIS ONLY** — This report is generated from production data for operator review. It does not represent trading recommendations or model changes.

**A:** `data/snapshots/2026-04-16/rankings.csv` (2026-04-16, 297 rows)
**B:** `data/snapshots/2026-04-17/rankings.csv` (2026-04-17, 297 rows)
**Generated:** 2026-04-17 20:48 UTC

## Top-N Overlap

- **N:** 30
- **Overlap:** 29 (96.7%)
- **Added:** 1 — TARS
- **Removed:** 1 — BCRX

## Schema Changes

- Common columns: 313
- Only in B: ees_v3_misprice_available

## Largest Score Drifts (top 15)

| Ticker | Score | Before | After | Delta |
| --- | --- | --- | --- | --- |
| IMMP | financial_score | 14.0136 | 36.2167 | 22.2031 |
| SLN | financial_score | 41.9601 | 24.0069 | -17.9531 |
| TSHA | financial_score | 64.234 | 55.8564 | -8.3777 |
| LEGN | financial_score | 76.25 | 68.375 | -7.875 |
| CDNA | financial_score | 55.4255 | 48.0964 | -7.3291 |
| IOVA | financial_score | 18.6225 | 12.0373 | -6.5852 |
| CMPX | financial_score | 56.0 | 50.375 | -5.625 |
| ANAB | financial_score | 28.1434 | 33.7642 | 5.6207 |
| QSI | financial_score | 62.391 | 67.7527 | 5.3617 |
| OMER | financial_score | 50.1596 | 45.0359 | -5.1236 |
| PACB | financial_score | 74.18 | 79.22 | 5.04 |
| TENX | financial_score | 69.5957 | 64.5691 | -5.0266 |
| TNGX | financial_score | 47.9728 | 43.0747 | -4.8981 |
| LCTX | financial_score | 33.7488 | 29.3211 | -4.4277 |
| ZLAB | financial_score | 74.9574 | 70.6011 | -4.3564 |
| CDNA | trap_overlay_score | -0.2789 | 0.0355 | 0.3144 |
| CDNA | ees_v2_score | -0.1395 | 0.0177 | 0.1572 |
| LEGN | trap_overlay_score | -0.1435 | 0.0086 | 0.1521 |
| IMMP | coinvest_score_z | -0.3758 | -0.5066 | -0.1308 |
| QSI | trap_overlay_score | -0.0951 | -0.1721 | -0.077 |

