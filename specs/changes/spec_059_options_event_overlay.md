# Spec 059 — Options Event-Pricing & Greeks Overlay

**Status**: IMPLEMENTED
**Author**: Claude / arrenchulz
**Date**: 2026-04-06
**Ruleset impact**: NO (overlay/diagnostic only — no selector/ranker/construction changes)

---

## Objective

Wire options-implied pricing and Greeks into the event-EV engine as a **diagnostic and risk overlay**, not an alpha signal. The goal is to answer: *"What does the market already expect around this biotech catalyst, and how sensitive is the stock to different branches?"* — improving operator situational awareness and feeding the expectation layer with calibrated market-implied inputs.

## Policy Constraint (2026-04-06)

**Options are OVERLAY-ONLY.** This spec must NOT:
- Add options features to the selector or ranker
- Use options for position sizing
- Mine the surface for generic alpha signals

All outputs are diagnostic, informational, or risk-flagging. See `options_research_policy_2026_04_06.md`.

## Scope — Four Use Cases

### UC1: Market-Implied Move vs Realized Move

**Question**: How does the options-implied move around a catalyst compare to what actually happened on similar past catalysts?

**Existing infrastructure**:
- `event_premium_decomp.py` → `epd_implied_vs_realized_ratio` (compares current implied to historical realized)
- `build_crt_options_join.py` → joins CRT outcomes with pre-event options state (18 events, 14 fields)
- `options_diagnostics.py` → `implied_event_move` (ATM straddle %)

**New work**:
1. **Implied-vs-realized calibration table**: Build from CRT×options join. For each (event_family, phase_bucket), record: implied_move_p50, realized_move_p50, ratio, n. This replaces the hardcoded `event_move_table` in EPD.
2. **Wire into Event EV Layer 5 (Payoff Engine)**: Use calibration table to adjust `ScenarioPayoffs.upside_hit` and `downside_miss` when options data is liquid. Currently the payoff engine uses only static empirical move priors.
3. **Forward logging**: Each production run logs (ticker, event_type, implied_move, catalyst_days) so the calibration table grows automatically as CRT resolves events.

**Outputs**: `implied_realized_calibration.json` (research artifact), payoff engine gets `options_adjusted` flag.

### UC2: Greeks-Based Branch Sensitivity

**Question**: For a name near a catalyst, how does the P&L change across HIT/MISS/MIXED branches accounting for IV crush and time decay?

**Existing infrastructure**:
- `options_greeks.py` → `black_scholes_greeks()`, `iv_crush_stress_test()`
- `event_ev/payoff_engine.py` → `ScenarioPayoffs` with upside_hit, downside_miss, move_mixed

**New work**:
1. **Branch P&L calculator**: Given current ATM IV, DTE, and scenario moves from the payoff engine, compute post-event Greeks profile for each branch:
   - HIT branch: stock +X%, IV crushes to Y% → new delta, vega, theta
   - MISS branch: stock -X%, IV crushes to Y% → new delta, vega, theta
   - Use `iv_crush_stress_test()` to estimate post-event IV (already exists)
2. **Breakeven surface**: For each name, what realized move is needed to break even on an ATM straddle at current prices? This tells the operator whether the market is over- or under-pricing the event.
3. **Output as diagnostic fields** on the Event EV detail view (dashboard ticker detail page).

**Outputs**: `branch_sensitivity` dict on EventEV, breakeven move field, dashboard rendering.

### UC3: Term-Structure / Event-Premium Diagnostics

**Question**: Is the options surface telling us something unusual about how the market is pricing this catalyst window?

**Existing infrastructure**:
- `event_premium_decomp.py` → 6 decomposed features (event_premium_ratio, term_slope_z, skew_richness_z, implied_vs_realized_ratio, iv_momentum, surface_regime)
- `options_diagnostics.py` → front/back IV, term slope, RR 25d, event premium flag
- Dashboard EPD leaderboard already renders these

**New work**:
1. **Event-premium anomaly detector**: Flag names where the event premium ratio is >2σ from the cross-sectional mean (within event_family). These are "the market is pricing something unusual" alerts.
2. **Term-structure shape classification**: Extend `surface_regime` with finer states: `backwardation_extreme` (front >> back, catalyst fully loaded), `contango_near_event` (unusual — market doesn't believe the date), `flat_high` (broad uncertainty).
3. **Historical comparison**: For a given name approaching a catalyst, show where its current term slope / event premium ratio sits relative to its own history and the cross-sectional distribution.
4. **Wire anomalies into Event EV expectation model** as a belief intensity modifier (not a feature weight change): if the surface is in `backwardation_extreme`, the market conviction is higher — this tightens the belief confidence band.

**Outputs**: `surface_anomaly_flags` list on EventEV, enhanced surface_regime enum, history comparison on dashboard detail.

### UC4: Risk Overlays / Hedge Awareness

**Question**: For names already in the book, what is the options-implied risk profile, and are there obvious hedge/protection signals?

**Existing infrastructure**:
- `options_construction_overlay.py` → weight multiplier based on IV/liquidity
- `options_risk_controls.py` → EXTREME IV penalty, thin liquidity penalty
- `options_review_queue.py` → operator review flags

**New work**:
1. **Catalyst proximity risk matrix**: For all book names within 30d of a catalyst, compute: implied move, breakeven straddle cost, IV crush estimate, max 1d VaR from Greeks. Render as a table on the dashboard.
2. **Hedge cost indicator**: For the top-5 highest-EV names, what does a 1-month ATM put cost as % of position? This is informational only — no automated hedging.
3. **Risk flag escalation**: When a book name has EXTREME IV + catalyst < 7d + implied move > 20%, escalate to a distinct risk alert (above normal EXTREME flag). This feeds into the operator review queue.

**Outputs**: Risk matrix table, hedge cost field, escalated risk alerts.

---

## PIT / Data Constraints

- [x] No lookahead — all options data from Tastytrade is live/real-time, historical from internal series
- [x] Data source: Tastytrade (live), `historical_iv_features.csv` (history), CRT resolutions
- [x] Historical availability: Options history varies by ticker; CRT has 18 resolved events
- [x] Known gaps: ~42% of chains are thin/absent liquidity — all outputs gated on `opt_liquidity_state`

## Inputs

| Input | Source | Schema |
|-------|--------|--------|
| opt_atm_iv, opt_front_iv, opt_back_iv | options_diagnostics.py | float, annualized IV |
| opt_term_slope, opt_rr_25d | options_diagnostics.py | float |
| opt_event_premium | options_diagnostics.py | float [0, 2+] |
| opt_liquidity_state | options_diagnostics.py | enum: liquid/thin/absent |
| implied_event_move | options_diagnostics.py | float, % move |
| epd_* features (6) | event_premium_decomp.py | float |
| CRT resolutions | catalyst_resolution_tracker | resolution, realized_move_1d/5d |
| EventEV layers 1-5 | event_ev/ | CatalystNode, OutcomeProbabilities, ScenarioPayoffs |
| Greeks | options_greeks.py | delta, gamma, vega, theta |

## Outputs

| Output | Destination | Schema |
|--------|-------------|--------|
| implied_realized_calibration.json | production_data/ | {family: {phase: {implied_p50, realized_p50, ratio, n}}} |
| branch_sensitivity | EventEV detail | {hit: {move, iv_post, delta, vega}, miss: {...}, breakeven_move} |
| surface_anomaly_flags | EventEV + dashboard | list[str]: backwardation_extreme, contango_near_event, etc. |
| catalyst_risk_matrix | dashboard /api/risk_matrix | [{ticker, implied_move, breakeven, iv_crush_est, var_1d}] |
| hedge_cost_pct | EventEV detail | float, ATM put cost as % of position |
| escalated_risk_alerts | operator review queue | list[{ticker, reason, severity}] |

## Invariants

1. **No production selector/ranker impact** — all outputs are diagnostic/overlay. Zero code changes to `selector_engine.py`, `ranker_engine.py`, or `decision_engine.py`.
2. **Liquidity gate** — every output gated on `opt_liquidity_state == "liquid"`. Thin/absent → null/skip.
3. **PIT-safe** — options data is real-time or from dated snapshots. No future data leaks.
4. **Graceful degradation** — missing options data → null fields, not errors. CRT calibration table works with n >= 5 per bucket; below that, fall back to static priors.

## Failure Modes

| Scenario | Expected behavior |
|----------|-------------------|
| Options data missing (absent liquidity) | All overlay fields null, no flags raised |
| CRT calibration bucket n < 5 | Fall back to static empirical move priors |
| Tastytrade API down | Use last cached snapshot, flag staleness |
| Greeks computation fails (bad inputs) | Return NaN fields, log warning |
| Event EV engine not run (no actionable catalysts) | Overlay fields empty, risk matrix empty |

## Validation Plan

### Tests (write BEFORE implementation)
- [ ] `test_implied_realized_calibration_build` — builds table from CRT fixtures, correct ratios
- [ ] `test_implied_realized_fallback_small_n` — n<5 falls back to static priors
- [ ] `test_branch_sensitivity_hit_miss` — Greeks computed correctly for HIT/MISS scenarios
- [ ] `test_breakeven_straddle` — breakeven move matches manual BS calculation
- [ ] `test_surface_anomaly_flags` — backwardation_extreme fires when front/back ratio > 2σ
- [ ] `test_term_shape_classification` — correct states for known surface shapes
- [ ] `test_risk_matrix_liquidity_gate` — thin/absent names excluded from matrix
- [ ] `test_hedge_cost_calculation` — ATM put cost matches BS pricing
- [ ] `test_escalated_risk_alert` — fires on EXTREME IV + <7d + >20% implied
- [ ] `test_all_outputs_null_on_missing_options` — graceful degradation

### Integration
- [ ] Full suite passes
- [ ] No changes to selector/ranker/decision engine tests
- [ ] Dashboard renders new fields without breaking existing tabs

## Expected Effect Size

**No direct IC or alpha impact** — this is explicitly not a signal study. Expected benefits:
- Better operator awareness of what the market prices around catalysts
- Calibrated move expectations in the payoff engine (replacing static priors)
- Risk alerts that prevent surprise IV crush losses on book names
- Foundation for future event-EV layers that need market-implied inputs

## Non-Goals

- Options as selector/ranker features (CLOSED — Spec 053)
- Market-making or vol-arb strategies
- Automated hedging or position sizing from options
- Generic surface-alpha mining
- Replacing the existing construction overlay (which already works)

---

## Implementation Plan

### Phase A — Calibration & Payoff Upgrade (UC1)
1. Build `implied_realized_calibration.py` from CRT×options join
2. Wire calibration table into `payoff_engine.py` as optional adjustment
3. Add forward logging to production pipeline
4. Tests for calibration build + fallback

### Phase B — Branch Sensitivity & Greeks (UC2)
1. Build `branch_sensitivity.py` using existing `options_greeks.py`
2. Breakeven straddle calculator
3. Wire into EventEV detail output
4. Dashboard rendering on ticker detail page

### Phase C — Surface Diagnostics (UC3)
1. Extend `surface_regime` with finer classifications
2. Build cross-sectional anomaly detector
3. Historical comparison helper
4. Wire anomaly flags into ExpectationModel as belief intensity modifier
5. Dashboard rendering

### Phase D — Risk Overlay (UC4)
1. Catalyst proximity risk matrix builder
2. Hedge cost calculator
3. Escalated risk alert logic
4. Dashboard risk matrix endpoint + rendering

---

## Implementation Log

### 2026-04-06 — All four phases implemented

**Phase A — Calibration & Payoff Upgrade (UC1)**
- `event_ev/implied_realized_calibration.py`: calibration table builder, CalibrationLookup, forward log helper
- `event_ev/payoff_engine.py`: options_calibration parameter, blend logic (50/50 default), liquidity gate
- Tests: `tests/test_implied_realized_calibration.py` (19 tests)

**Phase B — Branch Sensitivity & Greeks (UC2)**
- `event_ev/branch_sensitivity.py`: compute_branch_sensitivity(), compute_breakeven_straddle()
- `event_ev/data_contracts.py`: branch_sensitivity field on EventEV
- Tests: `tests/test_branch_sensitivity.py` (15 tests)

**Phase C — Surface Diagnostics (UC3)**
- `event_ev/surface_diagnostics.py`: classify_term_structure() (7 states), detect_surface_anomalies(), compare_to_history(), compute_belief_intensity_modifier()
- Tests: `tests/test_surface_diagnostics.py` (19 tests)

**Phase D — Risk Overlay (UC4)**
- `event_ev/catalyst_risk_overlay.py`: build_catalyst_risk_matrix(), compute_hedge_cost(), check_escalated_risk(), collect_escalated_alerts()
- Tests: `tests/test_catalyst_risk_overlay.py` (14 tests)

**Total: 67 new tests, all passing. 117 total (incl. 50 existing event_ev tests).**
**Zero changes to selector_engine.py, ranker_engine.py, or decision_engine.py.**

### 2026-04-06 — Production wiring complete

**EV Calculator wiring** (`event_ev/ev_calculator.py`):
- `_process_single()` now computes branch_sensitivity, breakeven straddle, term structure shape, and belief modifier for each catalyst when liquid options data is available
- All Spec 059 modules imported and wired: `branch_sensitivity`, `surface_diagnostics`
- Graceful degradation: any failure → branch_sensitivity=None, no impact on other layers

**Production pipeline** (`run_screen.py`):
- Forward logging: records implied_event_move for liquid names within 90d of catalyst → `options_forward_log.json`
- Surface anomaly detection: cross-sectional EPR z-scores → `surface_anomalies.json`
- Catalyst risk matrix + escalated alerts for top-30 book names → `catalyst_risk_overlay.json`
- All artifacts written as JSON sidecars in snapshot directory, wrapped in try/except

**Dashboard** (`dashboard/app.py`):
- `GET /api/catalyst_risk_matrix/{date}` — risk matrix + escalated alerts
- `GET /api/surface_anomalies/{date}` — surface anomaly flags
- `GET /api/options_forward_log/{date}` — forward log entries
- `GET /api/ticker/{ticker}` — enriched with risk_overlay (risk_matrix row, escalated_alert, surface_anomaly)
