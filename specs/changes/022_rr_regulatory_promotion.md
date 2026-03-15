# Spec 22: RR Regulatory Directional Overlay

**Status**: PENDING APRIL VALIDATION
**Date**: 2026-03-15
**Depends on**: Spec 019, Spec 020, FDA historical catalog, approach-window study

## Evidence Base

Event-anchored study on 934 FDA regulatory events (2022-2026):
- mean_rr IC=0.133 vs signed_gap (T-210 to T-91 window, n=792)
- mean_rr IC=0.114 vs signed_gap (T-90 to T-31, n=808)
- mean_implied_move IC=0.320 vs abs_gap (magnitude, all windows)
- IV trend IC~0 (dead signal)

This is the first statistically robust directional regulatory-options signal.

## April Pre-Event Predictions (recorded 2026-03-15)

| Ticker | Event ~Date | Mean RR | Direction Prediction |
|--------|-----------|---------|---------------------|
| BIIB | Apr 3 (PDUFA) | -0.048 | BEARISH | pending |
| CELC | Apr 1 (data) | -0.072 | BEARISH | pending |
| PVLA | Apr 1 (data) | -0.019 | MIXED (flipping) | pending |
| TBPH | Q1 2026 (data) | +0.326 | BULLISH | **WRONG** — resolved Mar 3, -26.3% gap |
| ESPR | ~Mar 30 (data) | -0.017 | NEUTRAL | pending (priority 8 in queue) |

### TBPH Post-Mortem (2026-03-15)
TBPH "topline data Q1 2026" resolved on 2026-03-03 with a -26.3% gap.
Pre-event RR was extremely bullish (+1.66 latest, +0.33 mean).
The bullish prediction was WRONG. Scorecard starts at 0/1.

Data quality issue: catalyst_days=657 in today's snapshot because the
Q1 2026 date resolved to 2026-01-01 (past), causing the pipeline to
fall through to a far-future CTGov date. The SEC 8-K event was correct
but dropped as stale.

### ESPR (added to scorecard)
Highest queue priority (8). Event ~Mar 30 (catalyst_days=15). RR is
nearly flat (-0.017), so this is more of a magnitude/disagreement test
than a directional RR test.

## Validation Gate (revised)

Do NOT execute any production changes until:
1. At least 3/5 tracked events have resolved outcomes
2. RR directional prediction matches signed_gap direction on >= 3/5
3. Event-anchored study rerun with new events still shows IC > 0.05
4. Subgroup splits (priority vs standard) don't show regime dependence

Current scorecard: 0/1 (TBPH wrong). Need 3/4 remaining correct to pass.

If 2 or fewer of remaining events confirm: PAUSE and reassess.

## Proposed Changes (post-validation only)

### A. Step-10 Window Extension
- Current: 91-180d
- Proposed: 91-210d
- Rationale: study shows signal strongest in T-210 to T-91 window

### B. RR Regulatory Overlay Candidate
Compare three formulations before choosing:
1. Current OQC (baseline)
2. RR-only (opt_rr_25d trailing average for 91-210d window)
3. OQC + RR overlay (current composite + RR as additional term)

Do NOT hard-code RR weight at 0.45 before this comparison.

Current OQC components:
- opt_event_premium: +0.40
- opt_liquidity_ok: +0.20
- opt_iv_regime == EXTREME: -0.20
- negative opt_term_slope: up to +0.20
- positive opt_put_call_skew: up to +0.20

Note: OQC uses opt_put_call_skew, not rr_25d. These are related but
not identical (skew = put_iv-call_iv normalized; RR = call_iv-put_iv raw).
Promotion requires deciding whether to replace skew with RR or add RR.

### C. Implied Move as Sizing Input
- actual_implied_move IC=0.32 vs abs_gap (magnitude, not direction)
- Use for position sizing guidance, not ranking
- Names with large implied_move: favor defined-risk options structures
- Names with small implied_move + bullish RR: favor equity size

### D. Review Queue Enhancement
Add rr_directional_prediction field for 91-210d regulatory names:
- computed from trailing mean_rr in the appropriate window
- informational only, no queue priority boost until A/B confirms

## Non-goals
- Do not change OQC for 0-90d names
- Do not promote volume as directional signal (confirmed magnitude-only)
- Do not use IV trend (confirmed dead)
- Do not bypass the existing promotion governance (top60 overlap, etc.)

## Success Definition
After April: RR overlay produces measurably better directional call on
regulatory events vs current OQC, with rank stability within repo gates.
