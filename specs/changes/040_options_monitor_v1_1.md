# Change Spec: Options Monitor v1.1 — From Surveillance to Alpha

**Status**: IN_PROGRESS (Sprint 1: feature plumbing)
**Author**: dschulz
**Date**: 2026-03-30
**Ruleset impact**: NO (research-only until promotion gates pass)
**Type**: Research / signal quality / feature engineering

---

## Objective

Upgrade the current options monitor from a rule-heavy alert stack into a
PIT-safe, catalyst-aware research layer with orthogonal factors, calibrated
probabilities, separate monitor/trade verdicts, and a formal promotion path.

## Non-Goals

- No replacement of the 4-lens architecture (it works)
- No standalone ranker on day one
- No hard production weight without evidence
- No discretionary chart reading

## Architecture

### 4 Orthogonal Factor Buckets

| Bucket | Formula | Weight varies by catalyst_class |
|--------|---------|-------------------------------|
| Event Premium (F_EP) | 0.40*z_ep_ts + 0.25*z_ep_xs + 0.20*z_term_slope_ts + 0.15*persist | regulatory=0.35, clinical=0.25, financing=0.10 |
| Surface Repricing (F_SR) | 0.35*z_iv3d_ts + 0.20*z_iv3d_xs + 0.25*z_surface_ts + 0.20*accel | clinical=0.35, regulatory=0.25 |
| Skew/Tail Stress (F_SK) | 0.45*z_skew_ts + 0.25*z_skew_chg_ts + 0.15*persist + 0.15*backwd | financing=0.35, safety=0.30 |
| Divergence (F_DV) | 0.30*stock_dn_iv_up + 0.20*stock_up_iv_dn + 0.30*quiet_before + 0.20*interaction | safety=0.25, financing=0.35 |

### Chain Quality Score (Q)
0.30*(1-spread/0.20) + 0.20*log(1+OI)/8 + 0.15*log(1+vol)/7 +
0.15*strike_coverage + 0.10*surface_fit_r2 + 0.10*(1-stale_pct)

### Confidence Modifier (C)
Q * (0.7 + 0.3*event_window) * (0.8 + 0.2*hard_catalyst)

### Composite
S_raw = weighted factor sum (weights by catalyst_class)
S_adj = S_raw * C
S_final = 0.85*S_adj + 0.15*max(F_EP, F_SR, F_SK, F_DV)

### Probability Outputs (Phase 2, after outcome data)
- p_move_gt_implied: logistic + isotonic calibration
- p_post_event_iv_crush: same
- p_false_positive: same

### Verdicts
Monitor: NONE / WATCH / HIGH (based on S_final thresholds)
Trade: LONG_GAMMA / SHORT_PREMIUM_AVOID / POST_EVENT_SHORT_VOL / NO_ACTION

## Implementation Sprints

### Sprint 1: Feature Plumbing [CURRENT]
- Raw inputs (chain/surface, liquidity/quality, stock/realized, catalyst, cross-sectional)
- Time-series z-scores (robust median/MAD, 252d lookback, 21d exclusion)
- Cross-sectional z-scores (peer cohort)
- Persistence and acceleration features
- Divergence features
- Factor scores (F_EP, F_SR, F_SK, F_DV)
- Chain quality score (Q) and confidence (C)
- Composite (S_final)
- New artifact: options_verdict/{date}_verdict_v11.json

### Sprint 2: Labeling + Backtest Harness
- Event-window label generator (move_gt_implied, iv_crush, false_positive)
- PIT walk-forward runner (6mo train, 2mo validate, monthly roll)
- Cohort evaluation (by catalyst_class, cap size, liquidity, vol regime)
- Ablation tests (each factor solo, all combined, vs v1.0)

### Sprint 3: Verdict Separation
- Monitor verdict (NONE/WATCH/HIGH)
- Trade verdict (LONG_GAMMA/SHORT_PREMIUM_AVOID/POST_EVENT_SHORT_VOL/NO_ACTION)
- Primary factor explanation
- State transitions (NEW/ONGOING/RESOLVED)

### Sprint 4: Shadow Production
- ovf11_* fields into rankings.csv
- Evidence collection manifests
- Shadow candidate registration
- Promotion gates: Brier improvement, top-decile lift >= 1.20x, IC positive 4/6 folds

## Promotion Gates (all must pass)

- Brier improvement vs v1.0 baseline
- Top-decile p_move_gt_implied lift >= 1.20x
- Positive IC in 4+ of 6 monthly walk-forward folds
- HIGH verdict false-positive rate below v1.0
- Alert count not more than 20% above v1.0 unless precision improves

## Files

- `common/options_monitor_v11_features.py` — factor computation
- `common/options_monitor_v11_model.py` — probability model (Sprint 2)
- `tools/backtest_options_monitor_v11.py` — backtest harness (Sprint 2)
- `artifacts/options_verdict/{date}_verdict_v11.json` — daily artifact
