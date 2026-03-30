# Change Spec: Options Monitor v1.1 — From Surveillance to Alpha

**Status**: PROPOSED
**Author**: dschulz
**Date**: 2026-03-30
**Ruleset impact**: NO (until outcome evaluation proves IC)
**Type**: Research / signal quality

---

## Problem Statement

The options monitoring stack is a solid surveillance system (4 lenses, fused
verdict, state tracking) but a weak alpha feature. Too much rule-based alert
logic, not enough calibrated outcome prediction. Overlapping alert codes,
no catalyst-type awareness, no cross-sectional context.

## Current State

- 4 lenses: options_watch post/pre, surface_delta, price_action_watch
- Fused verdict with 2-lens agreement escalation
- 8 ovf_* research features in rankings.csv (not in sort key)
- options_quality_composite as tiebreaker in one sleeve only
- options_verdict sort contribution wired but OFF

## Blunt Scorecard

- As ops monitor: GOOD
- As catalyst noise filter: PRETTY GOOD
- As production rank feature: NOT READY
- Best next step: calibrate on forward outcomes, compress alert taxonomy

---

## 10 Upgrades (Priority Order)

### 1. Outcome-Based Evaluation [NEEDS DATA]

For each alert/verdict, score against forward biotech outcomes:
- realized move vs implied move into catalyst
- post-event IV crush
- gap continuation vs fade
- T+1 / T+3 / T+5 abnormal return
- realized range expansion

Evaluate each alert code for precision, recall, lift, calibration by
catalyst type. **This is the single biggest upgrade.**

Buildable after: April catalyst resolutions + 20+ events with T+5 returns.

### 2. Collapse Alerts into 4 Orthogonal Buckets [BUILDABLE NOW]

Replace overlapping codes with independent dimensions:

| Bucket | Current Codes | New Feature |
|--------|--------------|-------------|
| Event premium | EVENT_PREMIUM, QUIET_BEFORE_CATALYST | event_premium_score (0-1) |
| Surface repricing | IV_RAMP_HIGH/MED, SURFACE_MOVE_HIGH/MED, iv_jump_* | surface_repricing_score (0-1) |
| Skew / tail stress | EXTREME_SKEW, SKEW_EXTREME, rr_flipped_*, skew_shift_* | skew_stress_score (0-1) |
| Stock-options divergence | STOCK_DOWN_IV_UP, STOCK_UP_IV_DOWN, REACTION_MISMATCH | divergence_score (0-1) |

Cap each bucket's contribution to the fused verdict. Prevents 3 IV-related
alerts from overwhelming one genuinely different signal.

### 3. Catalyst-Type Awareness [BUILDABLE NOW]

Fusion rules should depend on event class + days-to-event:

| Event Type | Expected Surface Behavior | Anomaly = |
|-----------|--------------------------|-----------|
| PDUFA / AdCom | IV build + event premium expected | Absence of build is the signal |
| Phase 3 topline | Moderate IV build | Aggressive build or extreme skew |
| Phase 1/2 safety | Minimal surface activity | Any premium = unusual |
| Financing / shelf | Vol spike, skew bearish | Context-dependent |

Add to verdict features:
- event_type
- catalyst_quality / confidence
- phase_bucket
- binary_event flag
- historical realized/implied ratio for event class

### 4. Cross-Sectional Context [BUILDABLE NOW]

For every options signal, compare to:
- stock's own 1yr history (per-name z-score)
- same-day biotech peer median
- XBI/IBB regime
- same catalyst cohort

SKEW_EXTREME already does per-name z-score in price_action_watch.
Extend to all signals.

### 5. Probability-Based Fusion [NEEDS DATA + #1]

Replace heuristic severity with calibrated probabilities:
- p_meaningful_move
- p_move_exceeds_implied
- p_post_event_iv_crush
- p_false_positive

Requires outcome evaluation (#1) to calibrate.

### 6. Granular Data-Quality Penalty [BUILDABLE NOW]

Beyond opt_liquidity_ok / opt_use_for_judgment, add:
- spread_quality (bid-ask width relative to mid)
- oi_concentration (top-3 strikes share of total OI)
- quote_staleness (hours since last trade)
- strike_continuity (gaps in the chain)
- surface_fit_quality (residual from parametric fit)

Feed into verdict confidence, not just a binary gate.

### 7. Separate Monitor Verdict from Trade Verdict [BUILDABLE NOW]

| Monitor Verdict | Trade Verdict |
|----------------|---------------|
| Something changed | Long gamma candidate |
| Check chain manually | Avoid long premium |
| Watch news | Consider debit vertical |
| Avoid entering ahead of overbid vol | Post-event premium sale |
| No action | Watch only |

### 8. False Positive Tracking [NEEDS ACCUMULATION]

Dashboard showing per alert code:
- fire frequency
- outcome prediction accuracy
- dead weight in NORMAL/ELEVATED/EXTREME regimes
- catalyst-only vs always-on performance

Kill weak codes aggressively.

### 9. Persistence and Acceleration Features [BUILDABLE NOW]

Replace point-in-time triggers with temporal features:
- 3-day IV acceleration
- 5-day skew trend
- event premium persistence (days held)
- sudden reversal after prolonged build

Biotech options tell the story in shape of change, not level.

### 10. Keep Sort Weight OFF Until Proven [ALREADY DONE]

ovf_* fields accumulating in snapshots. Options verdict tilt wired but OFF.
Correct posture until IC is proven across enough catalyst cycles.

---

## Implementation Order

### Phase 1 — Buildable Now (no outcome data needed)
- #2: Orthogonal bucket collapse
- #3: Catalyst-type fields in verdict
- #4: Cross-sectional z-scores for all signals
- #6: Granular data-quality penalty
- #7: Monitor vs trade verdict split
- #9: Persistence/acceleration features

### Phase 2 — After April Catalyst Resolutions (~20+ events)
- #1: Outcome-based evaluation
- #5: Probability-based fusion
- #8: False positive tracking dashboard

### Phase 3 — After Outcome Evaluation Proves IC
- Promote orthogonal bucket scores to sort contributions
- Calibrate per catalyst type
- Turn on options_verdict_tilt in candidate ruleset

---

## Non-Goals

- No change to current production ranking
- No new data sources (uses existing options infrastructure)
- No replacement of the 4-lens monitoring architecture (it works)
- No sentiment analysis or NLP on options flow
