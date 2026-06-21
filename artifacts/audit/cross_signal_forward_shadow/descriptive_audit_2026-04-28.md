# Cross-signal × DEM bucket audit — schema-era descriptive (2026-04-03 → 2026-04-28)

**Labeling**: SCHEMA-ERA DESCRIPTIVE BEHAVIOR — **not historical alpha evidence**.

**Snapshots used**: 21 (first 2026-04-03, last 2026-04-28).
**Horizons**: [5, 10] trading days. **20d/60d not computable in this window.**

## Bucket definitions
- **DEM-high** = top 20% by `selector_score`
- **DEM-low** = bottom 20% by `selector_score`
- **cross-signal-high** = `agreement_score >= 0.5`
- **cross-signal-low** = `agreement_score <= 0.1`
- Independent signals exclude B6 components (`coinvest_score_z`, `inst_delta_z`) and institutional block.

## Bucket aggregates

### 5d forward returns

| Bucket | n_obs | unique tickers | snapshots | mean | median | hit | mean − XBI |
|---|---:|---:|---:|---:|---:|---:|---:|
| HH | 64 | 14 | 12 | -0.0161 | -0.0156 | 0.33 | -0.0266 |
| HL | 227 | 35 | 12 | +0.0081 | +0.0017 | 0.51 | -0.0067 |
| LH | 86 | 13 | 12 | +0.0103 | -0.0016 | 0.48 | -0.0061 |
| LL | 222 | 37 | 12 | +0.0226 | +0.0165 | 0.58 | +0.0101 |
| MIDDLE | 2094 | 218 | 12 | +0.0221 | +0.0070 | 0.55 | +0.0080 |

### 10d forward returns

| Bucket | n_obs | unique tickers | snapshots | mean | median | hit | mean − XBI |
|---|---:|---:|---:|---:|---:|---:|---:|
| HH | 33 | 9 | 7 | -0.0207 | -0.0097 | 0.36 | -0.0502 |
| HL | 136 | 33 | 7 | +0.0328 | +0.0130 | 0.55 | +0.0004 |
| LH | 53 | 13 | 7 | +0.0199 | -0.0020 | 0.45 | -0.0125 |
| LL | 123 | 32 | 7 | +0.0644 | +0.0444 | 0.66 | +0.0333 |
| MIDDLE | 1213 | 208 | 7 | +0.0468 | +0.0165 | 0.60 | +0.0159 |

## Caveats

- Only 21 snapshots over ~26 days. Observations are heavily overlapping (same tickers reappear in adjacent snapshots).
- Effective independent N is far smaller than face n_obs; do not interpret as a population mean.
- Standing policy: 'Forward monitoring is the only valid evidence for alpha validation' (memory: historical_backtest_invalidated_2026_04_17).
- 20d/60d horizons not computable in this window.
- Snapshots include the post-2026-04-25 cohort-rebuild contamination period (04-25 to 04-28). inst_delta_z is excluded from agreement_score so cohort effect on the bucket assignment is small, but DEM_high tickers in those snapshots may still be cohort-influenced.
- Conclusion language: descriptive only. No alpha conclusion drawn.

## Conclusion

**No historical alpha conclusion drawn.** Forward shadows (`inst_delta_forward_shadow`, `cross_signal_forward_shadow`) are the only valid validators. Re-evaluate at h20d (2026-05-26) and h60d (2026-07-21).