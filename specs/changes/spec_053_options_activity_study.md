# Spec 053 — Unusual Options Activity Predictive Study

**Status**: COMPLETE — CLOSED (all options signals fail as systematic alpha; keep as diagnostic overlay only)
**Date**: 2026-04-04
**Predecessor**: Specs 049 (signal framework), 050 (selector-ranker engine), 051 (pairwise ranker)

## Hypothesis

Unusual options activity predicts future biotech stock performance and provides
incremental value beyond the current institutional + risk production baseline.

## Research Questions

1. Does unusual options activity predict future returns in biotech at all?
2. Which options signals work: volume-based, OI-based, skew/term-structure, implied-vs-realized, asymmetry/EV?
3. Best use: standalone selector, within-cohort ranker, catalyst-window diagnostic, or position-sizing modifier?
4. Does predictive power depend on: liquidity, market cap, catalyst proximity, catalyst family, regime?
5. Is any options signal incremental to incumbent (B6 coinvest+inst selector, pairwise_minimal ranker)?

## Signal Inventory (from existing panel)

### Available in research panel (30+ signals)

**IV / Surface (10)**:
- `opt_atm_iv`, `opt_front_iv`, `opt_back_iv`, `opt_term_slope`, `opt_put_call_skew`
- `opt_rr_25d`, `actual_implied_move_pctile`, `implied_event_move`
- `atm_iv_change_5d`, `cheap_vol_score`

**Verdict / Composite (8)**:
- `ovf_composite`, `ovf_agreement_count`, `ovf_severity_score`
- `ovf11_score`, `ovf11_confidence`, `ovf11_quality`
- `options_quality_composite`, `surface_signal_quality`

**Event Premium / Positioning (5)**:
- `opt_event_premium` (YES/NO), `opt_iv_regime` (NORMAL/ELEVATED/EXTREME)
- `pos_divergence`, `market_model_disagreement`
- `iv_crush_breakeven_pct`, `crush_adjusted_implied_move`

**Activity (2)**:
- `pre_event_put_call_ratio`
- `vol_classification` (CHEAP/SLIGHTLY_CHEAP/RICH)

**Quality / Liquidity Gates (4)**:
- `opt_liquidity_state`, `opt_liquidity_ok`, `opt_has_data`, `opt_use_for_judgment`
- `surface_move_extreme`, `iv_ramp_flag`, `rr_25d_trend_7d`, `rr_trend_flag`

### Derived signals (computed from existing columns)

- `event_premium_ratio` = front_iv / back_iv
- `iv_richness` = atm_iv z-scored per snapshot
- `term_slope_z` = opt_term_slope z-scored per snapshot
- `skew_z` = opt_put_call_skew z-scored per snapshot
- `rr_25d_z` = opt_rr_25d z-scored per snapshot
- `surface_conviction` = composite of multiple surface signals
- `options_bull_composite` = call-skew + cheap vol + positive term slope
- `options_bear_composite` = put-skew + rich vol + inverted term structure
- `options_event_composite` = event premium + implied move + IV ramp
- `options_liquid_conviction` = conviction signals restricted to liquid names

### Not available (data gap)

- Raw option volume, OI levels, volume z-scores, volume/OI ratio
- Per-strike flow data, unusual activity scanners
- Historical intraday options flow

This is an honest constraint. The study tests what the data supports.

## PIT Safety Rules

1. All signals from rankings.csv as-of snapshot date (PIT by construction)
2. Forward returns computed from price_history.csv anchored to snapshot date
3. No future catalyst resolution dates used in pre-event analysis
4. Regime labels based on XBI forward returns (not look-ahead; regime_63d is outcome-based for slicing only)
5. Options signals reflect chain state at snapshot time, not future chains
6. Liquidity classification as-of snapshot date
7. Catalyst proximity (catalyst_days) as known at snapshot time

## Evaluation Plan

### Track A — Univariate Signal Cards

For each of 30+ options signals, compute:
- Gate utility (above/below median spread)
- Selector utility (top-K improvement vs baseline, t-stat, IR)
- Ranker utility (within-top-K IC, RW vs EW, quintile spread)
- Regime stability (bear/neutral/bull splits)
- Horizons: 20d, 63d
- Subsample: liquid-only, catalyst-window, size splits

Verdict scale: NO_GO / HOLD / SHADOW / PROMOTE_CANDIDATE

### Track B — Bundle Tests

**Selector bundles** (vs B6 incumbent):
- Incumbent alone
- Incumbent + best IV/surface signal
- Incumbent + best event premium signal
- Incumbent + best composite signal
- Incumbent + best liquid-only signal
- Options-only bundles (no institutional)

**Ranker bundles** (vs pairwise_minimal baseline):
- Current baseline alone
- Baseline + best options feature
- Baseline + compact options block
- Baseline + liquid-only options block
- Options-only ranker

### Track C — Diagnostic / Overlay

- Tie-breaker among near-catalyst names
- Sizing tilt for high event-premium names
- Risk-off for illiquid/one-sided chains
- Catalyst-window watchlist signal

### Track D — Robustness

For every promising signal/bundle:
- By year, regime, market-cap, liquidity, catalyst family, catalyst proximity
- Winsorized vs raw, liquid-only vs all
- Correlation with coinvest_score_z, inst_delta_z
- Incremental value after controlling for institutional signals

### Track E — Momentum / Drift

- IV momentum (atm_iv_change_5d as predictor)
- Pre-event IV ramp interaction with returns
- Options-confirmed price drift (not standalone equity momentum)

## Acceptance Criteria

Promotion requires ALL of:
- PIT-safe (by construction via panel)
- Coverage >= 40% of eligible names (signal present and numeric)
- IC t-stat >= 1.6 OR selector improvement t-stat >= 1.6
- Positive across >= 2 of 3 regimes
- Improves portfolio-level outcomes (not just raw IC)
- Adds value beyond coinvest_score_z + inst_delta_z (incremental test)

## Deliverables

1. This spec document
2. `scripts/research/options_activity_study.py` — main analysis script
3. `output/options_activity_study/` — all artifacts:
   - `master_results.json`
   - `signal_ranking_table.md`
   - `selector_bundle_comparison.md`
   - `ranker_bundle_comparison.md`
   - `robustness_tables.md`
   - `final_recommendation.md`
