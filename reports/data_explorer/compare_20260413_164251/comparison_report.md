# Snapshot Comparison

> **ANALYSIS ONLY** — This report is generated from production data for operator review. It does not represent trading recommendations or model changes.

**A:** `data/snapshots/2026-04-12/rankings.csv` (2026-04-12, 297 rows)
**B:** `data/snapshots/2026-04-13/rankings.csv` (2026-04-13, 297 rows)
**Generated:** 2026-04-13 16:42 UTC

## Top-N Overlap

- **N:** 30
- **Overlap:** 23 (76.7%)
- **Added:** 7 — ALKS, ANNX, BCRX, JAZZ, KYMR, SLDB, SRRK
- **Removed:** 7 — ABVX, AMLX, AXSM, NGNE, RYTM, SION, ZYME

## Schema Changes

- Common columns: 272
- Schemas are identical.

## Largest Score Drifts (top 15)

| Ticker | Score | Before | After | Delta |
| --- | --- | --- | --- | --- |
| COGT | inst_delta_z | 0.0 | 3.4247 | 3.4247 |
| CMPX | inst_delta_z | 0.0 | 3.4247 | 3.4247 |
| EWTX | inst_delta_z | 0.0 | 3.1078 | 3.1078 |
| RNA | inst_delta_z | 0.0 | 2.791 | 2.791 |
| PEPG | inst_delta_z | 0.0 | -2.5957 | -2.5957 |
| INSM | inst_delta_z | 0.0 | -2.2789 | -2.2789 |
| RCUS | inst_delta_z | 0.0 | 2.1572 | 2.1572 |
| TECX | inst_delta_z | 0.0 | 2.1572 | 2.1572 |
| BCRX | inst_delta_z | 0.0 | 2.1572 | 2.1572 |
| VRDN | inst_delta_z | 0.0 | 2.1572 | 2.1572 |
| AMLX | inst_delta_z | 0.0 | -1.962 | -1.962 |
| ARVN | inst_delta_z | 0.0 | -1.962 | -1.962 |
| IONS | inst_delta_z | 0.0 | -1.962 | -1.962 |
| LRMR | inst_delta_z | 0.0 | -1.962 | -1.962 |
| LQDA | inst_delta_z | 0.0 | -1.962 | -1.962 |
| COGT | clinical_score_v2_z | -1.3288 | -0.3748 | 0.954 |
| VRDN | clinical_score_v2_z | -1.1633 | -0.2826 | 0.8807 |
| AMLX | final_score | 0.6232 | 0.0001 | -0.6231 |
| BCRX | clinical_score_v2_z | 0.2746 | 0.8119 | 0.5373 |
| LRMR | clinical_score_v2_z | 0.7669 | 1.2616 | 0.4947 |

