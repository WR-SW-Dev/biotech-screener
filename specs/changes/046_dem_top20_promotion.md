# Spec 046: Promote EW DEM Top-20 as Active Construction

**Status:** READY FOR PROMOTION
**Author:** D. Schulz
**Date:** 2026-04-02
**Supersedes:** Spec 045 regime-aware pruner (revised: concentration is the driver, not IDZ)

---

## Summary

DEM's selection alpha peaks at 20 names. Every name beyond 20 dilutes returns.
The right product of the selector is EW Top-20, not Top-30.

No stage-2 pruner signal is needed. DEM's own ranking order is already the
best ordering within the top-30. The `inst_delta_z` pruner was getting credit
for concentration, not stock-picking.

## Old Interpretation

> DEM picks 30, then inst_delta_z prunes to 20. The pruner adds +127pp.

## Revised Interpretation

> DEM picks 20 directly. The +139pp improvement comes from concentration.
> inst_delta_z adds nothing (-0.12pp/mo) over DEM's own top-20.

## Evidence

### Optimal portfolio size (63d, 72 monthly observations)

| Top-N | Excess/mo | Cumulative | IR | Hit |
|-------|-----------|------------|-----|-----|
| 10 | +3.32pp | +239pp | 0.19 | 50% |
| 15 | +3.48pp | +250pp | 0.25 | 57% |
| **20** | **+3.84pp** | **+277pp** | **0.32** | **60%** |
| 25 | +2.60pp | +188pp | 0.26 | 58% |
| 30 | +1.91pp | +138pp | 0.19 | 53% |

### Decomposition: why the pruner seemed to work

| Component | Effect | Share |
|-----------|--------|-------|
| Concentration (20 vs 30) | +1.93pp/mo | 106% |
| IDZ stock picking | -0.12pp/mo | -6% |
| Overlap DEM-20 vs IDZ-20 | 94% same names | — |

### Net of costs confirmation

- Top-20 vs Top-30 spread: **+1.88pp/mo net, +135pp cumulative**
- Cost differential: 57 bps/yr (negligible vs alpha)
- Hit rate: **64%** (Top-20 beats Top-30 in 64% of months)

### By regime

| Regime | Top-20 | Top-30 | Spread |
|--------|--------|--------|--------|
| Bear | -1.40pp | -1.22pp | -0.18pp (flat) |
| Neutral | +3.64pp | +2.02pp | +1.62pp |
| Bull | +8.66pp | +4.60pp | +4.06pp |

No regime where Top-30 meaningfully beats Top-20.

### Recent window (2025-2026)

- Top-20: +0.14pp/mo
- Top-30: -0.30pp/mo
- Still positive in the most recent period

## Promotion Recommendation

**Promote EW DEM Top-20 as the active construction default.**

- Replace EW Top-30 as baseline
- No regime gating needed (Top-20 wins or ties in all regimes)
- No pruner signal needed (DEM's ranking is sufficient)
- Retain risk monitor and rebalance plan for execution controls

## What Was Retired

| Idea | Status | Why |
|------|--------|-----|
| IDZ pruner | Tested, not additive | Concentration was the driver, not inst_delta_z |
| Options ranker | Dead | IC negative at all horizons (50 months) |
| total_volume_z | Dead | IC -0.10 on PIT-native (look-ahead bias) |
| Rank-weighting | Dead | IC doesn't monetize via weights |
| Fixed sleeve budgets | Retired Apr 1 | +153% construction drag |

## What Remains Active

- DEM selector (frozen)
- EW Top-20 construction
- Risk monitor + rebalance plan + earnings flags (execution layer)
- AACT accumulation (research only — bar is now: beat DEM Top-20)
- Options outlier flags (diagnostic only)
- Asymmetry score (shadow diagnostic)

## Committee Narrative

> "We tested multiple monetization layers — rank-weighting, pruner signals,
> options-based rankers — and found the simplest answer wins: hold fewer,
> better names. DEM's selection alpha peaks at 20 names. Every name beyond
> 20 dilutes returns. The right portfolio is EW Top-20, directly from DEM's
> ranking, with execution and risk controls."
