# SPEC 040 — Options Monitor v1.1

**Status:** IN_PROGRESS (Sprint 1 complete)
**Owner:** Biotech Screener / Options Monitoring
**Created:** 2026-03-30
**Depends on:** SPEC 038 (options tightening), SPEC 039 (options anchor shadow)
**Related modules:** `build_options_verdict.py`, `common/options_verdict_features.py`, `common/options_monitor_v11_features.py`, `run_screen.py`, `tools/run_daily_production.py`
**Related artifacts:** `artifacts/options_watch/{date}_watch.json`, `artifacts/options_watch/{date}_premarket_watch.json`, `data/snapshots/{date}/surface_delta.json`, `artifacts/price_action_watch/{date}_watch.json`, `artifacts/options_verdict/{date}_verdict.json`

---

## 1. Summary

Upgrade the current options monitor from a multi-lens alert stack into a
catalyst-aware, PIT-safe, research-grade factor model that produces:

- orthogonal options factors instead of overlapping alert counts
- calibrated forward-outcome probabilities
- separate monitoring verdict and trade verdict
- research fields in rankings.csv
- a formal promotion path from artifact to research feature to shadow sort
  contribution to limited production weight

This spec does not replace the current four-lens system. It keeps the
existing plumbing and re-expresses it in a more testable, less redundant form.

## 2. Current State

The existing stack is already structurally strong:

- four options lenses feed one fused verdict
- build_options_verdict.py fuses cross-lens alerts into a ticker-level verdict
- escalation is rules-based: 2+ lenses agree = HIGH, 1 HIGH on near-catalyst = HIGH
- options_quality_composite is a tiebreaker in the 91-180d regulatory sleeve
- ovf_* fields already flow into rankings.csv for signal evidence evaluation
- sort contribution for options_verdict is wired but OFF by default
- shadow candidate 96d21667 exists for hybrid options anchoring

## 3. Problem Statement

### Main Weaknesses

1. Too much overlap — IV ramp, surface move, skew, event premium often
   describe the same repricing event
2. Rule-heavy escalation — lens agreement != probability of meaningful outcome
3. Insufficient catalyst conditioning — biotech options differ materially
   across PDUFA/AdCom, clinical topline, safety, financing, earnings
4. Weak data-quality awareness — low-quality chains generate fake intelligence
5. No clean promotion path — good monitor, not yet justified sort contributor

## 4. Design

### 4 Orthogonal Factor Buckets

F_EP (Event Premium):
  0.40*normz(z_event_premium_ts) + 0.25*normz(z_event_premium_xs) +
  0.20*normz(z_term_slope_ts) + 0.15*iv_ramp_persist_3

F_SR (Surface Repricing):
  0.35*normz(z_iv_change_3d_ts) + 0.20*normz(z_iv_change_3d_xs) +
  0.25*normz(z_surface_move_ts) + 0.20*normz(iv_accel_3)

F_SK (Skew/Tail Stress):
  0.45*normz(z_skew_ts) + 0.25*normz(z_skew_change_ts) +
  0.15*skew_persist_3 + 0.15*backwardation_flag

F_DV (Divergence):
  0.30*stock_down_iv_up + 0.20*stock_up_iv_down +
  0.30*quiet_before_catalyst + 0.20*interaction_term

normz(z) = clip01((z + 2) / 4) maps robust z from [-2, +2] to [0, 1]
Robust z uses median/MAD (not mean/std) with 252d lookback, 21d exclusion

### Chain Quality Score (Q)
0.30*(1-spread/0.20) + 0.20*log(1+OI)/8 + 0.15*log(1+vol)/7 +
0.15*strike_coverage + 0.10*surface_fit_r2 + 0.10*(1-stale_pct)

### Confidence Modifier (C)
Q * (0.7 + 0.3*event_window) * (0.8 + 0.2*hard_catalyst)

### Catalyst-Aware Weighting

| catalyst_class   | w_EP | w_SR | w_SK | w_DV |
|------------------|------|------|------|------|
| regulatory       | 0.35 | 0.25 | 0.25 | 0.15 |
| clinical_topline | 0.25 | 0.35 | 0.20 | 0.20 |
| clinical_safety  | 0.20 | 0.25 | 0.30 | 0.25 |
| earnings         | 0.40 | 0.25 | 0.15 | 0.20 |
| financing        | 0.10 | 0.20 | 0.35 | 0.35 |
| other            | 0.25 | 0.25 | 0.25 | 0.25 |

### Composite
S_raw = weighted factor sum (weights by catalyst_class)
S_adj = S_raw * C
S_final = 0.85*S_adj + 0.15*max(F_EP, F_SR, F_SK, F_DV)

### Probability Outputs (Sprint 2)
- p_move_gt_implied: logistic + isotonic calibration
- p_post_event_iv_crush: same
- p_false_positive: same

### Verdicts
Monitor: HIGH (>=0.70) / WATCH (>=0.50) / NONE
Trade: LONG_GAMMA / SHORT_PREMIUM_AVOID / POST_EVENT_SHORT_VOL / NO_ACTION

## 5. New Input Fields

### Chain/Surface
atm_iv_30/60/90/180, iv_term_slope_30_90/30_180, iv_change_1d/3d/5d_30,
iv_change_1d_90, skew_25d_30/60, skew_change_1d/3d,
event_premium_30/60, surface_move_score_raw, backwardation/forwardation_flag

### Liquidity/Quality
opt_bid_ask_pct_median, opt_open_interest_total/front, opt_volume_total,
opt_strike_coverage_score, opt_surface_fit_r2, opt_stale_quote_pct

### Stock/Realized
stock_ret_1d/3d, stock_range_5d, realized_vol_10/20/60, gap_pct_1d

### Catalyst Context
catalyst_type, catalyst_class, days_to_catalyst, event_window_flag,
binary_event_flag, trial_phase_bucket, hard_catalyst_flag

### Cross-Sectional
xbi_ret_1d, peer_group_median_atm_iv_30/iv_change_3d/skew_25d_30

## 6. Output Fields

### Artifact (options_verdict/{date}_verdict_v11.json)
om11_factor_event_premium, om11_factor_surface_repricing,
om11_factor_skew_tail, om11_factor_divergence, om11_chain_quality,
om11_confidence, om11_score_raw, om11_score_final, om11_primary_factor,
om11_monitor_verdict, om11_trade_bias, om11_p_move_gt_implied,
om11_p_post_event_iv_crush, om11_p_false_positive, om11_catalyst_class,
om11_days_to_catalyst, om11_event_window_flag, om11_binary_event_flag,
om11_state

### rankings.csv Research Fields (ovf11_* prefix)
ovf11_ep, ovf11_sr, ovf11_sk, ovf11_dv, ovf11_quality, ovf11_confidence,
ovf11_score, ovf11_p_move_gt_implied, ovf11_p_iv_crush,
ovf11_p_false_positive, ovf11_primary_factor, ovf11_monitor_verdict,
ovf11_trade_bias, ovf11_event_window_flag, ovf11_catalyst_class

## 7. Backtest Plan

### Labels
- Y_move_gt_implied: |R_{t:t+1}| > IV30/sqrt(252)*k (k=1.0 initial)
- Y_iv_crush: atm_iv_30_{t+1} - atm_iv_30_{t-1} < -0.15
- Y_fp: S_final > 0.65 AND |R_{t:t+3}| < threshold AND no IV outcome

### Validation
Walk-forward: train 6mo, validate 2mo, roll monthly. No random splits.

### Ablations
1. F_EP only  2. F_SR only  3. F_SK only  4. F_DV only
5. All factors, no catalyst  6. All + catalyst  7. All + catalyst + confidence
8. Current v1.0 only  9. v1.0 + v1.1 combined

### Baselines
v1.0 fused verdict, catalyst-only, options_quality_composite, naive IV-ramp

### Metrics
AUC, PR-AUC, Brier, calibration, decile lift, Spearman IC on abs_ret_t1/t3,
top-decile hit rate, alerts/day, false-positive rate

## 8. Promotion Gates (all must pass)

1. Brier improvement vs v1.0
2. Top-decile p_move_gt_implied lift >= 1.20x catalyst baseline
3. Positive IC in 4+ of 6 monthly walk-forward folds
4. HIGH verdict false-positive rate below v1.0
5. Alert count not >20% above v1.0 unless precision improves

## 9. Rollout Plan

Phase 1 — Artifact only (no rankings.csv change)
Phase 2 — ovf11_* research fields into rankings.csv
Phase 3 — Shadow sort contribution (manifest candidate)
Phase 4 — Limited tiebreaker weight in catalyst sleeve (kill switch)

## 10. Implementation Status

### Sprint 1: Feature Plumbing [COMPLETE]
- common/options_monitor_v11_features.py — 4 factors + quality + confidence + composite
- 35 tests in tests/test_options_monitor_v11.py
- robust_z (median/MAD), cross_sectional_z, persistence, acceleration
- Catalyst-aware weights (6 classes, all sum to 1.0)
- Monitor verdict (HIGH/WATCH/NONE) + primary factor identification

### Sprint 2: Labeling + Backtest [BLOCKED: needs April outcome data]
- Event-window label generator
- PIT walk-forward runner
- Cohort evaluation + ablation tables

### Sprint 3: Verdict Separation [AFTER Sprint 2]
- Trade verdict (LONG_GAMMA / SHORT_PREMIUM_AVOID / etc.)
- Probability calibration

### Sprint 4: Shadow Production [AFTER Sprint 3 proves IC]
- ovf11_* fields into rankings.csv
- Shadow candidate registration

## 11. Open Questions

1. Should options_quality_composite become an input to Q?
2. Should EXTREME vol regime get its own model?
3. Should trade verdicts be deterministic or model-based in v1.1?
4. Should event labels use T+1 only, or also T+3/T+5 by catalyst class?

## 12. Files

- common/options_monitor_v11_features.py [EXISTS]
- common/options_monitor_v11_model.py [Sprint 2]
- tools/backtest_options_monitor_v11.py [Sprint 2]
- artifacts/options_verdict/{date}_verdict_v11.json [Sprint 1 schema ready]
- tests/test_options_monitor_v11.py [EXISTS, 35 tests]
