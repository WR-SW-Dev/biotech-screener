# ⚠️ CONTAMINATED — DO NOT USE FOR RESEARCH

This cache contains hash-named market data files that are **overwritten
on each refresh**. They contain CURRENT market data, not historical.

**Using these files for any historical or PIT-safe analysis will
produce look-ahead bias.**

The slippage penalty was originally built on this contaminated data
(IC went from +0.106 to -0.088 when fixed). See PIT audit 2026-04-12.

Use instead:
- `production_data/price_history.csv` for historical prices (PIT-safe)
- `production_data/pit_financials/` for historical financials (PIT-safe)
