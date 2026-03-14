# Spec 12: 31-90d Options Construction Overlay

**Status**: MODULE BUILT, AWAITING CONSTRUCTION WIRING + A/B

## What Exists

- `common/options_construction_overlay.py` — `compute_31_90_weight_multiplier()`
- `tests/test_options_construction_overlay.py` — 10 tests

## Weight Multiplier Logic

| Condition | Multiplier | Reason |
|-----------|-----------|--------|
| OQC > 0 + NORMAL IV + CHEAP/SLIGHTLY_CHEAP vol | ×1.20 | Options confirm setup, vol not overpriced |
| OQC > 0 + low disagreement | ×1.10 | Model and market agree |
| RICH vol + catalyst_days <= 75 | ×0.80 | Straddle overpriced, size down |
| High disagreement + catalyst_days <= 75 | ×0.75 | Sharp model-market disagreement |
| Stale options data | ×1.00 | Never adjust on stale data |

Multipliers compound, hard-bounded [0.60, 1.40].

## Next Steps

1. Wire into `_allocate_sub_bucket_quality()` in `tools/live_shadow_portfolio.py` for binary_31_90 bucket
2. Add `options_overlay_multiplier` and `options_overlay_reasons` to construction output
3. Run through A/B harness before live activation
