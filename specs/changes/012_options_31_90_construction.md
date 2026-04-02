# Spec 12: 31-90d Options Construction Overlay

**Status**: DEFERRED — modules upgraded (2026-04-01), A/B blocked on options window depth

## What Exists

- `common/options_construction_overlay.py` — `compute_31_90_weight_multiplier()` (upgraded 2026-04-01 with liquidity-state gating, implied-pctile fallback, EXTREME+thin penalty)
- `common/options_risk_controls.py` — `compute_0_30_risk_controls()` (upgraded with cheap surface flag, liquidity-state gating)
- `tests/test_options_construction_overlay.py` — 17 tests
- `tests/test_options_risk_controls.py` — 17 tests
- Wiring in `live_shadow_portfolio.py` — complete (try/except import path)
- Policy field `options_overlay.enabled` — exists, currently `false`
- A/B harness — `scripts/research/eval_options_overlay_policy_ab.py` — exists

## Weight Multiplier Logic (updated 2026-04-01)

| Condition | Multiplier | Reason | Chain gate |
|-----------|-----------|--------|------------|
| OQC > 0 + NORMAL IV + cheap vol | ×1.20 | Options confirm setup | liquid only |
| OQC > 0 + low disagreement | ×1.10 | Model and market agree | liquid only |
| RICH vol + near-term (≤75d) | ×0.80 | Straddle overpriced | liquid + thin |
| High disagreement + near-term | ×0.75 | Model-market gap | liquid + thin |
| EXTREME IV + thin chain | ×0.70 | Penalize extreme + poor quality | thin (even stale) |
| Absent data | ×1.00 | Never adjust on missing data | — |

Multipliers compound, hard-bounded [0.60, 1.40].

## Why Deferred

EW Top-30 promoted as active construction (2026-04-01). The overlay was designed for the legacy sleeve construction path. With EW Top-30:
- All positions are equal-weight (no within-bucket sizing to adjust)
- The overlay's value would be in penalizing specific names, which is a ranking function — not a construction function
- The ranker-ready window has only 8/30 usable dates — too thin for A/B

## Resolution Path

1. If the ranker is built and uses options features, the overlay may be superseded
2. If EW construction is augmented with a penalty layer (e.g., cap adjustments for extreme names), the overlay logic can be reactivated
3. The A/B harness is ready to run whenever the window is deep enough — enable `options_overlay.enabled: true` in policy and run `eval_options_overlay_policy_ab.py`
