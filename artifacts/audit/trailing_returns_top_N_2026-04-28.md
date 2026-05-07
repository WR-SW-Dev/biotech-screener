# Trailing returns of TODAY's top-N — daily-rebalanced + buy-and-hold vs XBI (2026-04-28)

**Descriptive only.** TODAY's top-N (`actionable_rank` <= N) back-cast over trailing windows. Heavy survivor + look-ahead bias; bias scales with window length. **Both methods reported** so the reader can choose the right interpretation.

## Methods
- **`daily_rebalanced_ew`**: each day, equal-weight mean of single-day simple returns; compound. Implicit daily rebalancing to equal weight. Standard for EW-index comparisons.
- **`buy_and_hold_ew`**: equal $ per ticker at window start; no rebalancing; portfolio value = mean of (price_t / price_0). Closer to what an actual investor would experience.

## Survivorship signal (NEW — quantifies the bias)
Per window, the fraction of today's top-N with **continuous price coverage across the entire window** (every trading day, both boundaries). 100% means every name was listed and trading the whole period. A random biotech basket would typically be 80–95%.

| Window | top-30 continuous coverage |
|---|---:|
| 1m | **100.0%** (30/30) |
| 3m | **100.0%** (30/30) |
| 6m | **100.0%** (30/30) |
| 1y | **100.0%** (30/30) |
| YTD | **100.0%** (30/30) |

100% across every window. Today's top-30 contains zero names that joined the universe mid-period, were halted, or delisted. The +249pp 1y excess vs XBI is the price tag on that filter, not alpha.

## 1m (2026-03-27 → 2026-04-28, 21 trading days)

XBI: total **+11.88%**, ann +284.71%, vol 33.60%, Sharpe +8.47, maxDD -4.14%

### Daily-rebalanced EW
| Cutoff | Total | vs XBI | Ann | Vol | Sharpe | MaxDD | β | IR | Hit |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| top-10 | +7.76% | -4.12% | +145.27% | 41.50% | +3.50 | -6.01% | +1.12 | -2.34 | 0.43 |
| top-20 | +18.85% | +6.97% | +694.26% | 36.74% | +18.90 | -3.83% | +1.05 | +6.82 | 0.76 |
| top-30 | +17.21% | +5.33% | +572.33% | 34.88% | +16.41 | -3.59% | +0.99 | +5.57 | 0.62 |
| top-40 | +17.27% | +5.38% | +576.18% | 32.39% | +17.79 | -3.81% | +0.92 | +5.94 | 0.57 |
| top-50 | +15.26% | +3.38% | +449.83% | 33.42% | +13.46 | -4.31% | +0.96 | +4.08 | 0.57 |
| top-60 | +14.21% | +2.33% | +392.49% | 33.58% | +11.69 | -4.63% | +0.97 | +2.96 | 0.57 |

### Buy-and-hold EW (no rebalancing)
| Cutoff | Total | vs XBI | Ann | Vol | Sharpe | MaxDD | β | IR | Hit |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| top-10 | +7.24% | -4.64% | +131.33% | 41.15% | +3.19 | -6.15% | +1.11 | -2.74 | 0.43 |
| top-20 | +19.34% | +7.46% | +734.89% | 36.61% | +20.07 | -3.86% | +1.04 | +7.03 | 0.71 |
| top-30 | +17.62% | +5.74% | +600.93% | 34.96% | +17.19 | -3.60% | +0.99 | +5.71 | 0.67 |
| top-40 | +18.01% | +6.13% | +629.63% | 32.37% | +19.45 | -3.63% | +0.92 | +6.43 | 0.57 |
| top-50 | +15.82% | +3.94% | +482.50% | 33.30% | +14.49 | -4.15% | +0.95 | +4.57 | 0.57 |
| top-60 | +14.64% | +2.76% | +415.51% | 33.46% | +12.42 | -4.51% | +0.96 | +3.40 | 0.57 |

### Method diff (daily-reb minus buy-and-hold, pp of total return)
| Cutoff | diff_pp |
|---|---:|
| top-10 | +0.52 |
| top-20 | -0.50 |
| top-30 | -0.41 |
| top-40 | -0.75 |
| top-50 | -0.56 |
| top-60 | -0.44 |

## 3m (2026-01-27 → 2026-04-28, 63 trading days)

XBI: total **+4.10%**, ann +17.44%, vol 30.61%, Sharpe +0.57, maxDD -8.04%

### Daily-rebalanced EW
| Cutoff | Total | vs XBI | Ann | Vol | Sharpe | MaxDD | β | IR | Hit |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| top-10 | +9.46% | +5.36% | +43.57% | 40.40% | +1.08 | -10.60% | +1.20 | +1.32 | 0.56 |
| top-20 | +24.20% | +20.10% | +137.98% | 36.14% | +3.82 | -7.04% | +1.11 | +5.85 | 0.67 |
| top-30 | +19.84% | +15.74% | +106.23% | 32.93% | +3.23 | -6.13% | +1.03 | +6.17 | 0.64 |
| top-40 | +18.32% | +14.22% | +95.99% | 31.40% | +3.06 | -5.88% | +0.99 | +5.97 | 0.64 |
| top-50 | +16.00% | +11.90% | +81.06% | 32.21% | +2.52 | -6.31% | +1.02 | +5.29 | 0.64 |
| top-60 | +13.94% | +9.84% | +68.54% | 32.37% | +2.12 | -7.34% | +1.02 | +4.40 | 0.59 |

### Buy-and-hold EW (no rebalancing)
| Cutoff | Total | vs XBI | Ann | Vol | Sharpe | MaxDD | β | IR | Hit |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| top-10 | +8.52% | +4.42% | +38.68% | 40.03% | +0.97 | -11.01% | +1.19 | +1.12 | 0.54 |
| top-20 | +24.68% | +20.58% | +141.64% | 36.08% | +3.93 | -7.20% | +1.11 | +5.86 | 0.62 |
| top-30 | +19.82% | +15.72% | +106.13% | 32.86% | +3.23 | -6.22% | +1.03 | +5.98 | 0.65 |
| top-40 | +18.04% | +13.94% | +94.14% | 31.33% | +3.00 | -5.98% | +0.98 | +5.65 | 0.65 |
| top-50 | +15.66% | +11.56% | +78.97% | 32.12% | +2.46 | -6.34% | +1.01 | +5.05 | 0.62 |
| top-60 | +13.48% | +9.38% | +65.82% | 32.31% | +2.04 | -7.56% | +1.02 | +4.14 | 0.57 |

### Method diff (daily-reb minus buy-and-hold, pp of total return)
| Cutoff | diff_pp |
|---|---:|
| top-10 | +0.94 |
| top-20 | -0.48 |
| top-30 | +0.01 |
| top-40 | +0.28 |
| top-50 | +0.34 |
| top-60 | +0.46 |

## 6m (2025-10-24 → 2026-04-28, 126 trading days)

XBI: total **+23.85%**, ann +53.39%, vol 27.82%, Sharpe +1.92, maxDD -9.72%

### Daily-rebalanced EW
| Cutoff | Total | vs XBI | Ann | Vol | Sharpe | MaxDD | β | IR | Hit |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| top-10 | +67.24% | +43.38% | +179.68% | 45.18% | +3.98 | -10.60% | +1.27 | +2.29 | 0.53 |
| top-20 | +77.83% | +53.98% | +216.25% | 37.64% | +5.75 | -9.38% | +1.20 | +4.17 | 0.60 |
| top-30 | +69.08% | +45.23% | +185.88% | 33.56% | +5.54 | -7.52% | +1.11 | +4.76 | 0.60 |
| top-40 | +63.19% | +39.34% | +166.32% | 31.79% | +5.23 | -6.86% | +1.06 | +4.68 | 0.61 |
| top-50 | +55.38% | +31.53% | +141.44% | 32.28% | +4.38 | -7.86% | +1.09 | +4.05 | 0.61 |
| top-60 | +50.29% | +26.44% | +125.88% | 32.36% | +3.89 | -7.99% | +1.09 | +3.50 | 0.58 |

### Buy-and-hold EW (no rebalancing)
| Cutoff | Total | vs XBI | Ann | Vol | Sharpe | MaxDD | β | IR | Hit |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| top-10 | +61.21% | +37.36% | +159.89% | 44.67% | +3.58 | -10.80% | +1.26 | +2.05 | 0.51 |
| top-20 | +73.88% | +50.03% | +202.34% | 37.45% | +5.40 | -9.83% | +1.19 | +3.92 | 0.59 |
| top-30 | +65.04% | +41.18% | +172.37% | 33.52% | +5.14 | -7.77% | +1.10 | +4.33 | 0.63 |
| top-40 | +59.80% | +35.95% | +155.36% | 31.98% | +4.86 | -7.39% | +1.06 | +4.29 | 0.59 |
| top-50 | +52.38% | +28.52% | +132.18% | 32.23% | +4.10 | -8.16% | +1.08 | +3.69 | 0.57 |
| top-60 | +47.01% | +23.16% | +116.12% | 32.23% | +3.60 | -8.20% | +1.09 | +3.13 | 0.56 |

### Method diff (daily-reb minus buy-and-hold, pp of total return)
| Cutoff | diff_pp |
|---|---:|
| top-10 | +6.02 |
| top-20 | +3.95 |
| top-30 | +4.04 |
| top-40 | +3.39 |
| top-50 | +3.01 |
| top-60 | +3.28 |

## 1y (2025-04-25 → 2026-04-28, 252 trading days)

XBI: total **+67.34%**, ann +67.34%, vol 25.94%, Sharpe +2.60, maxDD -9.72%

### Daily-rebalanced EW
| Cutoff | Total | vs XBI | Ann | Vol | Sharpe | MaxDD | β | IR | Hit |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| top-10 | +320.72% | +253.38% | +320.72% | 46.70% | +6.87 | -15.66% | +1.33 | +3.07 | 0.56 |
| top-20 | +405.73% | +338.38% | +405.73% | 48.78% | +8.32 | -12.57% | +1.31 | +3.31 | 0.60 |
| top-30 | +316.32% | +248.98% | +316.32% | 39.43% | +8.02 | -10.66% | +1.18 | +3.77 | 0.60 |
| top-40 | +264.65% | +197.31% | +264.65% | 35.98% | +7.36 | -11.38% | +1.14 | +3.90 | 0.61 |
| top-50 | +218.63% | +151.29% | +218.63% | 35.17% | +6.22 | -11.93% | +1.17 | +3.66 | 0.61 |
| top-60 | +197.50% | +130.16% | +197.50% | 34.45% | +5.73 | -11.65% | +1.16 | +3.49 | 0.57 |

### Buy-and-hold EW (no rebalancing)
| Cutoff | Total | vs XBI | Ann | Vol | Sharpe | MaxDD | β | IR | Hit |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| top-10 | +287.64% | +220.30% | +287.64% | 46.24% | +6.22 | -16.14% | +1.30 | +2.81 | 0.56 |
| top-20 | +385.08% | +317.74% | +385.08% | 47.46% | +8.11 | -12.77% | +1.26 | +3.24 | 0.55 |
| top-30 | +323.63% | +256.28% | +323.63% | 40.47% | +8.00 | -10.92% | +1.17 | +3.61 | 0.59 |
| top-40 | +267.09% | +199.75% | +267.09% | 37.86% | +7.05 | -11.32% | +1.15 | +3.50 | 0.58 |
| top-50 | +222.72% | +155.38% | +222.72% | 36.62% | +6.08 | -11.85% | +1.17 | +3.29 | 0.56 |
| top-60 | +199.29% | +131.95% | +199.29% | 35.60% | +5.60 | -11.65% | +1.16 | +3.15 | 0.57 |

### Method diff (daily-reb minus buy-and-hold, pp of total return)
| Cutoff | diff_pp |
|---|---:|
| top-10 | +33.08 |
| top-20 | +20.64 |
| top-30 | -7.30 |
| top-40 | -2.43 |
| top-50 | -4.09 |
| top-60 | -1.79 |

## YTD (2026-01-02 → 2026-04-28, 79 trading days)

XBI: total **+10.11%**, ann +35.95%, vol 30.15%, Sharpe +1.19, maxDD -9.72%

### Daily-rebalanced EW
| Cutoff | Total | vs XBI | Ann | Vol | Sharpe | MaxDD | β | IR | Hit |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| top-10 | +25.74% | +15.64% | +107.65% | 40.38% | +2.67 | -10.60% | +1.20 | +2.42 | 0.57 |
| top-20 | +37.34% | +27.23% | +175.13% | 37.20% | +4.71 | -9.38% | +1.15 | +5.10 | 0.65 |
| top-30 | +30.85% | +20.75% | +135.79% | 33.59% | +4.04 | -7.52% | +1.06 | +5.24 | 0.62 |
| top-40 | +29.26% | +19.15% | +126.73% | 32.64% | +3.88 | -6.86% | +1.02 | +4.83 | 0.62 |
| top-50 | +26.49% | +16.39% | +111.64% | 33.02% | +3.38 | -7.86% | +1.05 | +4.58 | 0.62 |
| top-60 | +22.97% | +12.86% | +93.38% | 32.75% | +2.85 | -7.99% | +1.04 | +3.74 | 0.58 |

### Buy-and-hold EW (no rebalancing)
| Cutoff | Total | vs XBI | Ann | Vol | Sharpe | MaxDD | β | IR | Hit |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| top-10 | +24.94% | +14.84% | +103.47% | 40.86% | +2.53 | -10.96% | +1.20 | +2.21 | 0.56 |
| top-20 | +39.55% | +29.44% | +189.50% | 37.59% | +5.04 | -9.96% | +1.15 | +5.20 | 0.63 |
| top-30 | +31.68% | +21.57% | +140.57% | 33.91% | +4.15 | -7.92% | +1.06 | +5.19 | 0.65 |
| top-40 | +29.31% | +19.21% | +127.04% | 32.93% | +3.86 | -7.31% | +1.03 | +4.72 | 0.65 |
| top-50 | +26.14% | +16.04% | +109.78% | 33.28% | +3.30 | -8.22% | +1.05 | +4.38 | 0.63 |
| top-60 | +22.56% | +12.46% | +91.37% | 33.02% | +2.77 | -8.33% | +1.05 | +3.57 | 0.58 |

### Method diff (daily-reb minus buy-and-hold, pp of total return)
| Cutoff | diff_pp |
|---|---:|
| top-10 | +0.80 |
| top-20 | -2.21 |
| top-30 | -0.83 |
| top-40 | -0.06 |
| top-50 | +0.35 |
| top-60 | +0.40 |

## Validation summary (passed)
- XBI math: matches direct close ratio to 4 decimals across all windows.
- Individual ticker spot-checks: COGT 1y +703.6%, DNTH 1y +305.0%, etc. — reconcile correctly.
- Missing-price audit: 0/7,590 cells missing in 1y top-30 window.
- Universe availability: **30/30 of today's top-30 has continuous price coverage** across the 1y window. Survivorship bias is fully present and quantified.

## What these numbers do NOT tell you
- They do **not** validate the model.
- They do **not** measure forward alpha.
- They do **not** account for the cohort-rebuild contamination affecting the latest snapshot.
- The forward shadows (`inst_delta_forward_shadow`, `cross_signal_forward_shadow`) are the only honest validators. Re-evaluate at h20d (2026-05-26) and h60d (2026-07-21).

Per standing policy: **no historical alpha conclusion drawn.**