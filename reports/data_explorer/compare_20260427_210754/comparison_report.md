# Snapshot Comparison

> **ANALYSIS ONLY** — This report is generated from production data for operator review. It does not represent trading recommendations or model changes.

**A:** `data/snapshots/2026-04-24/rankings.csv` (2026-04-24, 297 rows)
**B:** `data/snapshots/2026-04-27/rankings.csv` (2026-04-27, 297 rows)
**Generated:** 2026-04-27 21:07 UTC

## Top-N Overlap

- **N:** 30
- **Overlap:** 28 (93.3%)
- **Added:** 2 — NRIX, ZYME
- **Removed:** 2 — ARGX, TSHA

## Schema Changes

- Common columns: 313
- Only in B: cohort_membership, cohort_membership_streak, development_stage, development_stage_source, insider_net_buy_value_90d, lead_program_phase_raw

## Largest Score Drifts (top 15)

| Ticker | Score | Before | After | Delta |
| --- | --- | --- | --- | --- |
| BCYC | financial_score | 29.9887 | 68.8571 | 38.8685 |
| CLYM | financial_score | 31.6736 | 48.5069 | 16.8333 |
| MAZE | financial_score | 71.75 | 62.75 | -9.0 |
| ILMN | financial_score | 43.9932 | 37.0906 | -6.9027 |
| TRDA | financial_score | 71.4286 | 65.0 | -6.4286 |
| MRNA | financial_score | 26.6475 | 33.0 | 6.3525 |
| PRQR | financial_score | 41.9601 | 35.6944 | -6.2656 |
| EPRX | financial_score | 39.8403 | 33.6684 | -6.1719 |
| EDIT | financial_score | 21.39 | 15.3696 | -6.0204 |
| ANAB | financial_score | 31.8622 | 37.6531 | 5.7908 |
| TARA | financial_score | 72.6667 | 67.1667 | -5.5 |
| ALDX | financial_score | 69.0 | 63.5 | -5.5 |
| NTLA | financial_score | 46.0494 | 51.3333 | 5.284 |
| IMTX | financial_score | 64.6667 | 69.6667 | 5.0 |
| TCRX | financial_score | 41.6553 | 46.6077 | 4.9524 |
| ANAB | quality_overlay_score | -0.462 | -0.0 | 0.462 |
| TARA | trap_overlay_score | 0.0417 | -0.1788 | -0.2205 |
| BCYC | coinvest_score_z | -0.2374 | -0.0197 | 0.2177 |
| ANAB | inst_delta_z | -1.1218 | -0.9274 | 0.1944 |
| EPRX | inst_delta_z | 1.0437 | 0.8496 | -0.1941 |

