# Snapshot Comparison

> **ANALYSIS ONLY** — This report is generated from production data for operator review. It does not represent trading recommendations or model changes.

**A:** `data/snapshots/2026-04-20/rankings.csv` (2026-04-20, 297 rows)
**B:** `data/snapshots/2026-04-27/rankings.csv` (2026-04-27, 297 rows)
**Generated:** 2026-04-27 21:07 UTC

## Top-N Overlap

- **N:** 30
- **Overlap:** 27 (90.0%)
- **Added:** 3 — NRIX, SLN, ZYME
- **Removed:** 3 — ARGX, NGNE, TSHA

## Schema Changes

- Common columns: 313
- Only in B: cohort_membership, cohort_membership_streak, development_stage, development_stage_source, insider_net_buy_value_90d, lead_program_phase_raw

## Largest Score Drifts (top 15)

| Ticker | Score | Before | After | Delta |
| --- | --- | --- | --- | --- |
| BCYC | financial_score | 29.3211 | 68.8571 | 39.536 |
| ZBIO | financial_score | 34.3976 | 72.0 | 37.6024 |
| CLYM | financial_score | 33.6684 | 48.5069 | 14.8385 |
| ANAB | financial_score | 50.0 | 37.6531 | -12.3469 |
| LEGN | financial_score | 70.625 | 59.375 | -11.25 |
| TENX | financial_score | 70.6011 | 60.3333 | -10.2677 |
| CLLS | financial_score | 18.9378 | 27.7778 | 8.84 |
| TYRA | financial_score | 39.8403 | 31.6736 | -8.1667 |
| OPCH | financial_score | 31.9378 | 24.2848 | -7.653 |
| RAPP | financial_score | 65.0 | 71.75 | 6.75 |
| GHRS | financial_score | 48.5069 | 41.9601 | -6.5469 |
| AGIO | financial_score | 48.3173 | 54.6667 | 6.3493 |
| PRQR | financial_score | 41.9601 | 35.6944 | -6.2656 |
| TCRX | financial_score | 40.6844 | 46.6077 | 5.9233 |
| IDYA | financial_score | 64.5691 | 70.3333 | 5.7642 |
| RAPP | quality_overlay_score | -0.0 | -0.789 | -0.789 |
| TYRA | inst_delta_z | -0.1937 | 0.5535 | 0.7472 |
| RAPP | final_score | 0.0001 | 0.6057 | 0.6057 |
| RAPP | ees_v2_score | -0.0013 | -0.3978 | -0.3965 |
| GHRS | clinical_score_v2_z | 0.3252 | 0.654 | 0.3288 |

