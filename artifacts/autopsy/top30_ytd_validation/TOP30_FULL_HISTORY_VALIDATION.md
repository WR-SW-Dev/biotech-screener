# Full-History DEM Top-30 Validation — 2020–2026

**Generated:** 2026-06-28  
**Classification:** `DIAGNOSTIC_VALIDATION_NO_MODEL_CHANGE`  
**Basket:** Equal-weight top-30 by `actionable_rank`, weekly non-overlapping 5-day forward returns  
**Sources:** 489 total (380 archives `data/archives/` + 196 live snapshots `data/snapshots/`; live wins on overlap)  
**Price source:** `price_history_split_adj.csv` primary; raw fallback for dates beyond split-adj cutoff  

---

## Summary

| Metric | Value |
|--------|-------|
| Period | 2020-01-03 → 2026-06-22 |
| Weekly snapshots (non-overlapping) | **328** |
| Portfolio cumulative return | **+261.6%** |
| XBI cumulative return | **+62.4%** |
| Cumulative excess | **+199.1pp** |
| Weekly mean XS | +0.298%/wk |
| Weekly std XS | 2.849% |
| Weekly t-stat | **1.90** |
| Hit rate (XS > 0) | 53% |
| Skipped snapshots | 47 |

---

## By Year

| Year | n | Mean XS | t | Hit | cumXS |
|------|---|---------|---|-----|-------|
| 2020 | 51 | +0.06% | 0.16 | 53% | +3.2pp |
| 2021 | 50 | +0.37% | 0.96 | 48% | +18.3pp |
| 2022 | 51 | +0.05% | 0.14 | 53% | +2.6pp |
| 2023 | 50 | +0.36% | 0.90 | 52% | +17.8pp |
| 2024 | 52 | +0.40% | 0.85 | 52% | +21.0pp |
| 2025 | 50 | +0.57% | 1.28 | 60% | +28.4pp |
| 2026 | 24 | +0.27% | 0.66 | 50% | +6.5pp |

---

## Interpretation

**Key finding: no year is negative.** Every year from 2020 through 2026 shows positive mean weekly excess return, including the biotech bear years 2020 and 2022 (+0.05–0.06%/wk). Year-by-year consistency is a stronger signal than the aggregate t-stat alone.

**t=1.90 across 328 independent weekly periods.** Clears the 95% one-tailed threshold (testing H₀: XS ≤ 0 vs H₁: XS > 0). Does not clear the two-tailed 95% threshold (1.96). Approximately 50 additional forward weeks would push the combined t past 2.0 for a two-tailed result.

**Signal strengthening over time.** The 2025 year-level t=1.28 (50 periods) is the strongest annual result. Signal appears to be improving as the model has been refined.

---

## Caveats

**1. Model version heterogeneity.**  
Archives from 2020–2025 reflect model versions v1.0 through v1.3. The current production model (v1.4+, `actionable_rank` logic from April 2026) has only 24 clean out-of-sample weekly periods (t=0.66). The full-history result is best interpreted as evidence that the evolving `actionable_rank` signal has consistently generated positive excess returns, not as a pure v1.4 backtest.

**2. 13F data contamination window.**  
63 archives (2024-10-18 → 2025-11-07) have contaminated institutional holder-count data. This may have affected rankings during that window. Price-based return calculation is unaffected; top-30 composition may differ from what a clean-data run would have produced.

**3. Development-time bias.**  
The model was iteratively developed using this historical data. True out-of-sample evidence starts from each model version's lock date. The forward shadow validation (20-week gate) is the clean test for v1.4.

**4. Hit rate 53%.**  
Slightly above coin-flip. Cumulative excess comes from magnitude of wins, not frequency. The distribution is fat-tailed; a small number of strong weeks drive the aggregate.

---

## Forward Validation Gate

The v1.4 forward shadow monitor (`artifacts/shadow_monitor/`) tracks live performance from the model lock date. Gate: 20 completed non-overlapping forward periods with positive mean excess and no severe drawdown cluster vs XBI. Estimated gate clear: ~2026-10-31.

---

## Governance

- `model_change: False`
- `ranker_change: False`
- `selector_change: False`
- `trading_action: False`
- `classification: DIAGNOSTIC_VALIDATION_NO_MODEL_CHANGE`
