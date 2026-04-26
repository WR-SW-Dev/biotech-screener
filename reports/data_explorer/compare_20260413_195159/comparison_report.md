# Snapshot Comparison

> **ANALYSIS ONLY** — This report is generated from production data for operator review. It does not represent trading recommendations or model changes.

**A:** `data/snapshots/2026-04-12/rankings.csv` (2026-04-12, 297 rows)
**B:** `data/snapshots/2026-04-13/rankings.csv` (2026-04-13, 297 rows)
**Generated:** 2026-04-13 19:51 UTC

## Top-N Overlap

- **N:** 30
- **Overlap:** 26 (86.7%)
- **Added:** 4 — ANNX, KYMR, SLDB, SRRK
- **Removed:** 4 — AXSM, RYTM, SION, ZYME

## Schema Changes

- Common columns: 272
- Schemas are identical.

## Largest Score Drifts (top 15)

| Ticker | Score | Before | After | Delta |
| --- | --- | --- | --- | --- |
| COGT | inst_delta_z | 0.0 | 3.6463 | 3.6463 |
| CMPX | inst_delta_z | 0.0 | 3.6463 | 3.6463 |
| EWTX | inst_delta_z | 0.0 | 3.0194 | 3.0194 |
| RNA | inst_delta_z | 0.0 | 2.706 | 2.706 |
| INSM | inst_delta_z | 0.0 | -2.3091 | -2.3091 |
| RCUS | inst_delta_z | 0.0 | 2.0791 | 2.0791 |
| TECX | inst_delta_z | 0.0 | 2.0791 | 2.0791 |
| BCRX | inst_delta_z | 0.0 | 2.0791 | 2.0791 |
| SLDB | inst_delta_z | 0.0 | 2.0791 | 2.0791 |
| ANNX | inst_delta_z | 0.0 | 2.0791 | 2.0791 |
| VRDN | inst_delta_z | 0.0 | 2.0791 | 2.0791 |
| ARVN | inst_delta_z | 0.0 | -1.9957 | -1.9957 |
| IONS | inst_delta_z | 0.0 | -1.9957 | -1.9957 |
| LRMR | inst_delta_z | 0.0 | -1.9957 | -1.9957 |
| LQDA | inst_delta_z | 0.0 | -1.9957 | -1.9957 |
| COGT | clinical_score_v2_z | -1.3288 | -0.3748 | 0.954 |
| VRDN | clinical_score_v2_z | -1.1633 | -0.2826 | 0.8807 |
| SLDB | final_score | 0.0001 | 0.641 | 0.641 |
| ANNX | final_score | 0.0001 | 0.6398 | 0.6398 |
| BCRX | clinical_score_v2_z | 0.2746 | 0.8119 | 0.5373 |

