# DEM Robustness Battery — 2026-04-28

Read-only diagnostic. No production state modified. Methodology fixed in `tools/inst_delta_robustness_battery.py` before measurement.

**Universe rankable**: 221 tickers.

## User pre-registered expectation

```
- DEM grades "mixed/fragile," not fully broken.
- Top-10 is least robust because overlap between CURRENT and CF is only 4/10.
- Top-30 will show material contamination, but not all 13 artifact entrants are equally bad.
- Structurally defensible cutoff is likely top-40 or top-60 for monitoring, not top-10.
- Production action should remain: none; observe until h20d and post-13F refresh.
```

---

## Final Verdict

**DEM robustness grade**: `mixed`

**Test distribution**: robust=4, borderline=0, fragile=2

**Structurally defensible cutoff today**: `top-50`

**Contaminated names (high-confidence artifact + counterfactual exits)**: ['ABVX', 'COGT', 'MIRM', 'NRIX', 'ORKA', 'ZYME']

**Durable despite cohort shock**: ['BCRX', 'PHVS']

**Production action recommended**: none — observe until h20d (2026-05-26) and post-13F refresh (~2026-05-15).

---

## Test 1 — Perturbation sensitivity

**Verdict**: `robust (top-30 overlap ≥25/30 under reduced-inst)`

### B: 0.80×coinvest + 0.20×inst_delta
- Spearman ρ vs baseline selector_score: **0.9655**
- Top-30 overlap: **28/30**  |  Top-10: 8/10  |  Top-20: 16/20  |  Top-60: 50/60
- Names with rank moves ≥10 slots: 109  |  ≥20 slots: 55
- Top-30 entrants (2): DNTH, ORKA
- Top-30 exits (2): ABVX, MIRM

### C: coinvest_score_z only
- Spearman ρ vs baseline selector_score: **0.8934**
- Top-30 overlap: **18/30**  |  Top-10: 6/10  |  Top-20: 11/20  |  Top-60: 47/60
- Names with rank moves ≥10 slots: 154  |  ≥20 slots: 105
- Top-30 entrants (12): ACAD, AMLX, AXSM, DNTH, MBX, OCUL, ORKA, PCVX, RYTM, SION, TARS, ZYME
- Top-30 exits (12): ANNX, BCRX, CGEM, KALV, KYMR, MIRM, MLTX, ORIC, RCUS, SLDB, TECX, VERA

---

## Test 2 — Cutoff score-quality curve

**Verdict**: `robust (smooth monotonic decay)`

### Per-cutoff stats
| Cutoff | n | median | mean | min |
|---|---:|---:|---:|---:|
| top-10 | 10 | 0.8886 | 0.8905 | 0.7364 |
| top-20 | 20 | 0.8886 | 0.8839 | 0.7364 |
| top-30 | 30 | 0.8841 | 0.8782 | 0.7318 |
| top-40 | 40 | 0.8795 | 0.8727 | 0.7318 |
| top-50 | 50 | 0.8705 | 0.8665 | 0.7318 |
| top-60 | 60 | 0.8659 | 0.8659 | 0.7318 |

### Incremental bucket medians + drops
| Bucket | Median | Drop from prior |
|---|---:|---:|
| ranks_1_10 | 0.8886 | — |
| ranks_11_20 | 0.9068 | -0.0182 |
| ranks_21_30 | 0.8682 | 0.0386 |
| ranks_31_40 | 0.8205 | 0.0477 |
| ranks_41_50 | 0.8386 | -0.0181 |
| ranks_51_60 | 0.8409 | -0.0023 |

- Median bucket drop: -0.0023; cliff threshold (2×): —
- Largest drop: bucket=ranks_31_40, value=0.0477
- Cliff detected: False

---

## Test 3 — Feature dominance

**Verdict**: `robust (majority mixed or coinvest-dominated)`

- Counts among top-30: inst-dominated=9, coinvest-dominated=15, mixed=6, undefined=0
- Inst-dominated AND known artifact: ['COGT']

### Top-30 decomposition (sorted by inst_share_abs desc)
| Rank | Ticker | coinvest×0.65 | inst×0.35 | inst_share | dominant | artifact? |
|---:|---|---:|---:|---:|---|---|
| 22 | BLTE | 0.0211 | 0.5047 | 0.9599 | inst_dominated |  |
| 12 | SRRK | 0.0348 | 0.5047 | 0.9355 | inst_dominated |  |
| 29 | KRYS | -0.1503 | 0.5047 | 0.7705 | inst_dominated |  |
| 28 | BCRX | 0.4189 | 0.9193 | 0.687 | inst_dominated |  |
| 8 | ORIC | 0.3299 | 0.712 | 0.6834 | inst_dominated |  |
| 14 | RCUS | 0.3875 | 0.8157 | 0.6779 | inst_dominated |  |
| 5 | ANNX | 0.3477 | 0.712 | 0.6719 | inst_dominated |  |
| 4 | SLDB | 0.3651 | 0.712 | 0.661 | inst_dominated |  |
| 1 | COGT | 0.9315 | 1.5413 | 0.6233 | inst_dominated | ★ |
| 17 | SLN | 0.132 | 0.1937 | 0.5948 | mixed |  |
| 24 | EWTX | 0.8363 | 1.1266 | 0.574 | mixed |  |
| 10 | KYMR | 0.3171 | 0.401 | 0.5585 | mixed |  |
| 11 | AXSM | 0.4396 | -0.4283 | 0.4935 | mixed |  |
| 30 | TSHA | 0.7409 | 0.6083 | 0.4509 | mixed |  |
| 2 | INSM | 1.0941 | -0.7392 | 0.4032 | mixed |  |
| 6 | NRIX | 0.2926 | 0.1937 | 0.3983 | coinvest_dominated | ★ |
| 18 | TNGX | 0.8281 | 0.2974 | 0.2642 | coinvest_dominated |  |
| 27 | ALKS | 0.3374 | -0.1173 | 0.258 | coinvest_dominated |  |
| 9 | PRAX | 0.8928 | 0.2974 | 0.2499 | coinvest_dominated |  |
| 20 | RVMD | 0.6419 | 0.1937 | 0.2318 | coinvest_dominated |  |
| 25 | NBIX | 0.4122 | -0.1173 | 0.2215 | coinvest_dominated |  |
| 26 | ZYME | 0.4266 | -0.1173 | 0.2156 | coinvest_dominated | ★ |
| 23 | MIRM | 0.3369 | 0.0901 | 0.2109 | coinvest_dominated | ★ |
| 19 | XENE | 0.795 | 0.1937 | 0.1959 | coinvest_dominated |  |
| 16 | ABVX | 0.4438 | 0.0901 | 0.1687 | coinvest_dominated | ★ |
| 21 | CELC | 0.4839 | 0.0901 | 0.1569 | coinvest_dominated |  |
| 3 | DNTH | 0.6542 | -0.1173 | 0.152 | coinvest_dominated |  |
| 15 | ORKA | 0.5317 | 0.0901 | 0.1448 | coinvest_dominated | ★ |
| 7 | STOK | 0.5813 | 0.0901 | 0.1341 | coinvest_dominated |  |
| 13 | PHVS | 1.0419 | -0.0136 | 0.0129 | coinvest_dominated |  |

---

## Test 4 — Marginal cutoff sensitivity

**Verdict**: `fragile (26 names within 0.10 of cutoff)`

- top-30 cutoff selector_score: **0.9864**
- Names within 0.05 of cutoff: **14**
- Names within 0.10 of cutoff: **26**

### Window 25_35 (selector_score)
- cumulative gap: 0.1182
- adjacent gaps: [0.0727, 0.0091, -0.2, 0.2455, -0.2545, 0.1909, -0.1409, -0.0455, 0.1773, 0.0636]
### Window 35_45 (selector_score)
- cumulative gap: -0.0591
- adjacent gaps: [-0.0727, -0.0909, 0.0773, -0.1636, 0.2227, -0.0682, 0.0636, 0.0273, -0.0364, -0.0182]
### Window 55_65 (selector_score)
- cumulative gap: 0.25
- adjacent gaps: [0.1091, 0.0591, -0.0318, -0.0091, -0.0636, 0.1682, 0.0045, 0.0045, 0.0045, 0.0045]

---

## Test 5 — Cheap bootstrap (drop-5%, n=1000)

**Verdict**: `robust (median overlap 29.0/30, 0 names <80% inclusion)`

- mean overlap: 28.473/30
- median overlap: 29.0/30
- p10 / p90 overlap: 27 / 30
- Unstable names (<80% inclusion) (0): (none)

---

## Test 6 — Cross-signal agreement

**Verdict**: `fragile (leaders depend mostly on DEM/institutional layer; weak cross-signal corroboration)`

- Independent signals available: ['clinical_score_v2_z', 'financial_score', 'selector_clinical_block', 'selector_catalyst_block', 'selector_survivability_block', 'selector_market_block']
- Mean agreement_score: top-10=0.05, top-20=0.075, top-30=0.1
- Tickers with agreement ≥0.50: ['AXSM', 'NBIX']
- Tickers with agreement = 0: ['ABVX', 'ALKS', 'ANNX', 'BLTE', 'COGT', 'INSM', 'NRIX', 'ORKA', 'PHVS', 'PRAX', 'RCUS', 'SLDB', 'SRRK', 'STOK', 'TNGX', 'ZYME']
- **Known artifact entrants with low agreement (<0.50)**: ['ABVX', 'COGT', 'MIRM', 'NRIX', 'ORKA', 'ZYME']

---

## Test 7 — Artifact isolation extension

- Classification counts: {'C_artifact_driven': 13, 'A_clean_durable': 10, 'D_underweighted': 5, 'B_durable_but_cohort_moved': 2}

| Rank | Ticker | Δinst_z | Agreement | Classification | Artifact? |
|---:|---|---:|---:|---|---|
| 1 | COGT | 0.5759 | 0.0 | C_artifact_driven | ★ |
| 2 | INSM | 0.2471 | 0.0 | C_artifact_driven |  |
| 3 | DNTH | 0.168 | 0.1667 | C_artifact_driven |  |
| 4 | SLDB | 0.0626 | 0.0 | A_clean_durable |  |
| 5 | ANNX | -0.2468 | 0.0 | D_underweighted |  |
| 6 | NRIX | 0.7472 | 0.0 | C_artifact_driven | ★ |
| 7 | STOK | -0.1677 | 0.0 | D_underweighted |  |
| 8 | ORIC | -0.2468 | 0.1667 | D_underweighted |  |
| 9 | PRAX | 0.1153 | 0.0 | A_clean_durable |  |
| 10 | KYMR | -0.2072 | 0.1667 | D_underweighted |  |
| 11 | AXSM | 0.2075 | 0.5 | C_artifact_driven |  |
| 12 | SRRK | 0.089 | 0.0 | C_artifact_driven |  |
| 13 | PHVS | 0.4642 | 0.0 | B_durable_but_cohort_moved |  |
| 14 | RCUS | 0.0494 | 0.0 | A_clean_durable |  |
| 15 | ORKA | 0.451 | 0.0 | C_artifact_driven | ★ |
| 16 | ABVX | 0.451 | 0.0 | C_artifact_driven | ★ |
| 17 | SLN | -0.1808 | 0.1667 | D_underweighted |  |
| 18 | TNGX | 0.1153 | 0.0 | A_clean_durable |  |
| 19 | XENE | 0.1285 | 0.1667 | A_clean_durable |  |
| 20 | RVMD | 0.1285 | 0.1667 | A_clean_durable |  |
| 21 | CELC | 0.1417 | 0.1667 | A_clean_durable |  |
| 22 | BLTE | 0.089 | 0.0 | C_artifact_driven |  |
| 23 | MIRM | 0.451 | 0.1667 | C_artifact_driven | ★ |
| 24 | EWTX | 0.0099 | 0.1667 | A_clean_durable |  |
| 25 | NBIX | 0.168 | 0.5 | A_clean_durable |  |
| 26 | ZYME | 0.4773 | 0.0 | C_artifact_driven | ★ |
| 27 | ALKS | 0.168 | 0.0 | C_artifact_driven |  |
| 28 | BCRX | 0.3455 | 0.1667 | B_durable_but_cohort_moved |  |
| 29 | KRYS | 0.089 | 0.1667 | C_artifact_driven |  |
| 30 | TSHA | 0.0757 | 0.1667 | A_clean_durable |  |

---

## Methodology constraints

- All scores read from `data/snapshots/2026-04-28/rankings.csv`. No model rerun.
- No production data mutated. All artifacts in `artifacts/audit/`.
- Companion: `inst_delta_attribution_2026-04-28.{md,json}`, `inst_delta_forward_shadow/T0_2026-04-28_lock.json`.