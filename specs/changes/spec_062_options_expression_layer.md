# Spec 062 — Options Expression Layer

**Status**: DRAFT
**Author**: Claude / arrenchulz
**Date**: 2026-04-13
**Ruleset impact**: NO (overlay/diagnostic only)
**Alpha stack impact**: NO — all changes are diagnostic/shadow; production selector,
ranker (pairwise_minimal), and construction are untouched.
**Depends on**: Spec 057 (Event EV Engine), Spec 059 (Options Event Overlay)

---

## Objective

Translate existing Event EV mispricing diagnostics into a structured options
expression recommendation. The system already knows *where* the market may be
wrong (EES sub-scores, crowd belief, payoff asymmetry, surface shape). It does
not yet answer: *"Given this mispricing shape, what is the right options
structure to express the view?"*

This spec fills that gap as a **diagnostic-only** layer. It does NOT reopen
options-as-alpha (Spec 053, CLOSED), does not touch selector/ranker/construction,
and does not auto-trade. Outputs are operator recommendations with full
governance metadata.

## Policy Constraints

1. **OVERLAY-ONLY.** Zero changes to `selector_engine.py`, `ranker_engine.py`,
   `decision_engine.py`, or any construction logic.
2. **Not alpha.** This is structure selection, not signal mining. No new features
   enter the scoring stack.
3. **Spec 053 remains CLOSED.** Options surface features are not used for
   systematic equity ranking. This spec uses existing EV sub-scores to recommend
   *how* to express a view that the equity pipeline already identified.
4. **Alpha stack freeze respected.** No new promotions, no Checklist v2 bypass.
5. **All outputs gated on `opt_liquidity_state == "liquid"`.** Thin/absent
   options → `NO_TRADE` with reason.
6. **No threshold fitting.** All thresholds are policy-chosen. If future
   evidence suggests tuning, that requires a new spec with Checklist v2.

---

## Surface Validity Gate (pre-classification)

Before any mispricing classification runs, the options surface itself must
pass a validity check. Invalid surfaces produce garbage classifications.

**`surface_quality_score`** (computed per-name, 0-100):

```
surface_quality_score = mean(
    liquidity_component,     # opt_liquidity_state == "liquid" → 100, else 0
    freshness_component,     # quote age < 1 trading day → 100, stale → 0
    spread_component,        # 100 - min(100, bid_ask_spread_pct * 10)
    depth_component,         # from opt_liquidity_state internals (already computed)
)
```

**Hard gate:** `surface_quality_score >= 50` required to proceed. Below 50,
the entire expression layer outputs `NO_TRADE` with
`gate_failures=["invalid_surface"]`.

**Soft penalty:** `surface_quality_score` feeds into `mispricing_confidence`
as a multiplier (score/100). A surface scoring 60 reduces confidence by 40%.

**What this prevents:**
- Wide-spread quotes producing phantom skew signals
- Stale EOD quotes on names that halted or went ex-dividend
- Thin chains where a single trade distorts the entire surface

---

## Execution Constraints

Options structures have execution friction that equity orders do not.
These constraints are hard gates — if violated, the structure is demoted
to a simpler alternative or NO_TRADE.

### Spread width gate

| Structure | Max acceptable bid-ask spread (mid-to-mid) | On violation |
|-----------|---------------------------------------------|--------------|
| Single-leg (LONG_STRADDLE) | 8% of premium | Demote to NO_TRADE |
| Two-leg (BULL_CALL_SPREAD, PUT_SPREAD, RISK_REVERSAL) | 6% per leg | Demote to NO_TRADE |
| Four-leg (SHORT_IRON_CONDOR) | 4% per leg | Demote to NO_TRADE |
| CALENDAR_SPREAD | 8% per leg | Demote to NO_TRADE |

Rationale: More legs = more slippage. A four-leg structure with 4% spread
per leg is ~16% round-trip friction — already aggressive. Wider spreads
make the trade negative-EV before it starts.

### Legging risk acknowledgment

Multi-leg structures cannot be filled atomically in thin biotech options.
The `ExpressionRecommendation` output includes:

```python
execution_risk: str  # "low" | "moderate" | "high"
leg_count: int       # 1, 2, or 4
```

Rules:
- 1 leg → `"low"`
- 2 legs → `"moderate"`
- 4 legs → `"high"`
- If `execution_risk == "high"` AND `surface_quality_score < 70`,
  demote to simpler structure or NO_TRADE.

### Fill probability estimate

Not modeled (no historical fill data). Instead, a conservative policy:
all sizing assumes worst-case fill at the **ask** (buys) / **bid** (sells).
The `max_premium_pct_nav` already accounts for this by being conservative.

---

## Inputs

All inputs are existing typed objects. No new data dependencies.

| Input | Source | Fields consumed |
|-------|--------|-----------------|
| `ScenarioPayoffs` | `event_ev/payoff_engine.py` | `upside_hit`, `downside_miss`, `move_mixed`, `scenario_ev`, `asymmetry_ratio`, `downside_adjusted_ev`, `kelly_fraction`, `analog_confidence` |
| `CrowdBelief` | `event_ev/expectation_model.py` | `implied_p_hit`, `belief_direction`, `belief_intensity`, `priced_move_pct`, `mispricing_score` |
| `OutcomeProbabilities` | `event_ev/outcome_model.py` | `p_hit`, `p_miss`, `p_mixed`, `confidence` |
| `ExpectationErrorScore` | `event_ev/expectation_error_model.py` | `base_rate_gap_score`, `conditional_misprice_score`, `divergence_score`, `crowding_bias_score`, `timing_decay_risk_score`, `expectation_confidence` |
| `TimingEstimate` | `event_ev/timing_hazard.py` | `prob_on_time`, `prob_slip`, `expected_delay_days`, `median_arrival_days` |
| `CatalystNode` | `event_ev/data_contracts.py` | `event_family`, `phase`, `date_precision`, `days_to_event()` |
| Surface diagnostics | `event_ev/surface_diagnostics.py` | `classify_term_structure()` output, `detect_surface_anomalies()` flags, `compute_belief_intensity_modifier()` |
| Options fields (from snapshot row) | `run_screen.py` CSV row | `opt_liquidity_state`, `opt_atm_iv`, `opt_front_iv`, `opt_back_iv`, `implied_event_move`, `opt_rr_25d`, `bid_ask_spread_pct` (if available) |

---

## Output Ontology

The expression layer uses a **two-level ontology** to prevent semantic drift
toward becoming an open-ended strategy recommender.

### Level 1: Expression class (closed enum, 6 values)

These are the only values the `overlay_class` field can take. The enum is
deliberately narrow. Adding a new class requires a spec amendment.

| `overlay_class` | Meaning | Risk profile |
|-----------------|---------|--------------|
| `NO_TRADE` | No actionable mispricing or failed gates | None |
| `DIRECTIONAL_DEBIT` | Directional view, defined-risk debit structure | Premium at risk |
| `VARIANCE_DEBIT` | Volatility underpriced, long gamma | Premium at risk |
| `DEFINED_RISK_CREDIT` | Volatility overpriced, sell premium with wings | Capped loss |
| `TIMING_CALENDAR` | Timing mismatch, sell near / buy far | Calendar spread risk |
| `MANUAL_REVIEW` | Signal exists but no clean structure fits; operator decides | N/A |

### Level 2: Example structure (informational, not binding)

Each expression class maps to one or more concrete structures. These are
**suggestions for the operator**, not trade orders. The operator can choose
any structure within the class.

| `overlay_class` | `example_structures` |
|-----------------|----------------------|
| `DIRECTIONAL_DEBIT` | bull call spread, put spread, risk reversal |
| `VARIANCE_DEBIT` | long straddle, long strangle |
| `DEFINED_RISK_CREDIT` | iron condor, iron butterfly |
| `TIMING_CALENDAR` | calendar spread, diagonal spread |
| `MANUAL_REVIEW` | (none — operator's judgment) |
| `NO_TRADE` | (none) |

The Level 1 class is the **contract**. Level 2 is documentation.

### Anti-drift rule

The output field is named `overlay_class`, never `trade_signal`,
`trade_recommendation`, or `alpha_signal`. This is a naming discipline:
the word "overlay" anchors the object's role in the system.

**Hard invariant:** `ExpressionRecommendation` outputs must NEVER be consumed
by `selector_engine.py`, `ranker_engine.py`, `decision_engine.py`, or any
scoring/ranking/selection code path. This is not just policy — it should be
enforced by import structure (the expression layer imports from event_ev;
selector/ranker do not import from expression layer).

---

## Outputs

### Primary: `ExpressionRecommendation` (new frozen dataclass)

```python
@dataclass(frozen=True)
class ExpressionRecommendation:
    ticker: str
    node_id: str
    as_of_date: str

    # Classification
    mispricing_type: str         # DIRECTIONAL | VARIANCE | SKEW | TIMING | MIXED | NONE
    mispricing_subtype: str      # e.g., "bullish_underpriced", "vol_overpriced", "put_skew_rich"

    # Belief vs permission (two distinct concepts)
    belief_strength: float       # [0, 1] — how strong the model thinks the mispricing is
                                 # Derived from EV sub-scores and outcome model confidence.
                                 # Independent of market/execution context.
    permission_to_express: float # [0, 1] — whether execution context allows any structure
                                 # Derived from surface_quality, spread width, liquidity,
                                 # execution risk. Independent of mispricing diagnosis.
    mispricing_confidence: float # [0, 1] — min(belief_strength, permission_to_express)
                                 # Both must be high for a tradeable recommendation.

    # Recommendation (Level 1 = contract, Level 2 = informational)
    overlay_class: str           # NO_TRADE | DIRECTIONAL_DEBIT | VARIANCE_DEBIT |
                                 # DEFINED_RISK_CREDIT | TIMING_CALENDAR | MANUAL_REVIEW
    example_structures: list     # Informational: ["bull_call_spread", "risk_reversal"]
    overlay_rationale: str       # Human-readable 1-2 sentence explanation

    # Sizing guidance (conservative, policy-based)
    max_premium_pct_nav: float   # Upper bound on premium as % of portfolio NAV
    sizing_basis: str            # "kelly_capped" | "fixed_notional" | "no_size"

    # Execution constraints
    surface_quality_score: float # [0, 100] — surface validity score
    execution_risk: str          # "low" | "moderate" | "high"
    leg_count: int               # 1, 2, or 4 (based on primary example structure)
    max_spread_pct: float        # Hard gate for bid-ask spread per leg

    # Tradeability gates
    is_tradeable: bool           # All gates pass
    gate_failures: list          # Which gates failed (empty if tradeable)

    # Governance
    governance_class: str        # "overlay_only" — always
    policy_flags: list           # ["not_alpha", "not_ranking", "operator_review_required"]

    # Provenance
    inputs_used: dict            # Which EV sub-scores drove the classification
    model_version: str           # "expression_v0.1"
```

### Secondary outputs

| Output | Destination | Format |
|--------|-------------|--------|
| `overlay_recommendations.json` | snapshot sidecar | List of `ExpressionRecommendation.to_dict()` |
| `overlay_decision_log.json` | snapshot sidecar | **All** evaluated names: tradeable, rejected, demoted (see Logging) |
| Dashboard endpoint | `GET /api/expression_overlay/{date}` | Same JSON, filtered to tradeable |
| Ticker detail enrichment | `GET /api/ticker/{ticker}` | `expression_overlay` field |

---

## Mispricing Classification

Maps existing EV sub-scores to a mispricing type. Each rule uses fields that
already exist on `ExpectationErrorScore`, `ScenarioPayoffs`, `CrowdBelief`,
`TimingEstimate`, and surface diagnostics.

### Type: DIRECTIONAL

The model's probability assessment disagrees with the crowd's implied
probability, creating a directional edge.

**Trigger conditions** (ALL must hold):
- `|CrowdBelief.mispricing_score| >= 0.15` (model vs market P(HIT) gap)
- `|ScenarioPayoffs.scenario_ev| >= 3.0` (meaningful expected move)
- `OutcomeProbabilities.confidence >= 0.50`
- `ExpectationErrorScore.conditional_misprice_score` sign aligns with
  `mispricing_score` sign (model and scenario EV agree on direction)

**Subtypes:**
- `bullish_underpriced`: mispricing_score > 0, scenario_ev > 0
- `bearish_underpriced`: mispricing_score < 0, scenario_ev < 0

### Type: VARIANCE

The market-implied move magnitude is wrong relative to the model's expected
absolute move, regardless of direction.

**Why this is the most dangerous type:** Implied-vs-realized comparison is
inherently noisy. Base-rate tables are small-sample. Vol surface distortions
are common in biotech (post-halt, corporate action, index rebalance). A
wrong variance call leads to short gamma into a binary event or long gamma
with no payoff — both expensive mistakes. Extra gates required.

**Trigger conditions** (ALL must hold):
- `|EES.base_rate_gap_score| >= 0.30` (implied move ≠ historical base rate)
- `EES.divergence_score` sign agrees with base_rate_gap sign (surface confirms)
- `priced_move_pct` available (options data exists)
- Directional mispricing IS NOT the primary signal (mispricing_score < 0.15)
- **`variance_confidence >= 0.55`** (additional gate, see below)

**`variance_confidence` formula:**

```
variance_confidence = min(
    EES.expectation_confidence,
    surface_quality_score / 100,      # from Surface Validity Gate
    analog_confidence_numeric,         # "ok"→1.0, "low"→0.5, "insufficient"→0.0
) * base_rate_sample_factor
```

Where `base_rate_sample_factor`:
- 1.0 if base-rate table bucket has n >= 30
- 0.7 if n >= 10
- 0.4 if n < 10 (effectively disables variance trades for rare event types)

**If `variance_confidence < 0.55`:** VARIANCE classification is suppressed.
The name falls through to DIRECTIONAL (if it qualifies) or NONE. This
prevents variance trades on weak evidence.

**Subtypes:**
- `vol_underpriced`: base_rate_gap < -0.30 (market implies smaller move than
  history suggests)
- `vol_overpriced`: base_rate_gap > 0.30 (market implies larger move than
  history suggests)

### Type: SKEW

The options skew is misaligned with the outcome probability distribution.
Put skew is rich relative to actual downside probability, or call skew is
rich relative to upside probability.

**Trigger conditions** (ALL must hold):
- `opt_rr_25d` available (liquid options with skew data)
- `|EES.crowding_bias_score| >= 0.30`
- Directional and variance mispricing below their thresholds

**Subtypes:**
- `put_skew_rich`: crowding_bias_score > 0.30 AND p_hit > p_miss (crowd is
  bearishly positioned but model says upside more likely)
- `call_skew_rich`: crowding_bias_score < -0.30 AND p_miss > p_hit (crowd
  is bullishly positioned but model says downside more likely) — rare

### Type: TIMING

The market is pricing event resolution in the near-term expiry, but the
timing model assigns meaningful delay probability.

**Why this needs extra caution:** Timing is the weakest validated component
in the system. Timing IC is negative as a signal — it works only as a gate,
not a predictor. Calendar spreads have real theta bleed if the timing model
is wrong. This type requires the highest confidence bar.

**Trigger conditions** (ALL must hold):
- `TimingEstimate.prob_slip >= 0.25`
- `EES.timing_decay_risk_score >= 0.40`
- `classify_term_structure()` returns `backwardation` or `backwardation_extreme`
  (market is loading premium into front month)
- `CatalystNode.date_precision` is MONTH or coarser
- **`timing_confidence >= 0.60`** (highest bar of any type)

**`timing_confidence` formula:**

```
timing_confidence = min(
    TimingEstimate confidence proxy,   # prob_on_time + prob_slip should sum
                                       # near 1.0; if they don't → low confidence
    surface_quality_score / 100,       # need reliable term structure data
    date_precision_factor,             # DAY→0.3, WEEK→0.4, MONTH→0.6,
                                       # QUARTER→0.8, HALF_YEAR→1.0
                                       # (coarser = more room for delay = more
                                       # confident the delay thesis is valid)
)
```

**If `timing_confidence < 0.60`:** TIMING classification is suppressed.
Falls through to other types or NONE. This prevents calendar spreads
based on weak timing signals.

**Subtype:** `near_term_overpriced` (always — this type has one shape)

### Type: MIXED

Multiple mispricing types trigger simultaneously at moderate strength.

**Trigger:** Two or more types meet their conditions at reduced thresholds
(0.7x of primary thresholds). Classification picks the highest-confidence
component as `mispricing_subtype`.

### Type: NONE

No mispricing detected above threshold, or insufficient data.

---

## Expression Mapping

Deterministic mapping from (mispricing_type, mispricing_subtype, context)
to overlay class. No optimization, no fitting.

| Mispricing | Subtype | `overlay_class` | `example_structures` | Rationale |
|------------|---------|-----------------|----------------------|-----------|
| DIRECTIONAL | bullish_underpriced | DIRECTIONAL_DEBIT | bull call spread, risk reversal | Defined risk bullish; spread limits premium |
| DIRECTIONAL | bearish_underpriced | DIRECTIONAL_DEBIT | put spread | Defined risk bearish |
| VARIANCE | vol_underpriced | VARIANCE_DEBIT | long straddle, long strangle | Long gamma to capture underpriced move |
| VARIANCE | vol_overpriced | DEFINED_RISK_CREDIT | iron condor | Short gamma with wings; harvest overpriced premium |
| SKEW | put_skew_rich | DIRECTIONAL_DEBIT | risk reversal | Sell rich puts, buy cheap calls |
| SKEW | call_skew_rich | DIRECTIONAL_DEBIT | put spread | Bearish + harvest rich call skew |
| TIMING | near_term_overpriced | TIMING_CALENDAR | calendar spread, diagonal | Sell decaying near-term, own far-dated |
| MIXED | (any) | MANUAL_REVIEW | (depends on components) | Multiple signals; operator judgment needed |
| NONE | — | NO_TRADE | (none) | Insufficient mispricing or data |

### Context overrides

The base mapping is overridden by context gates. These can change the
`overlay_class` or demote to `NO_TRADE` / `MANUAL_REVIEW`.

1. **Asymmetry gate:** If `ScenarioPayoffs.asymmetry_ratio > 2.5` (large
   upside/downside skew) AND mispricing_type is VARIANCE/vol_underpriced,
   reclassify to DIRECTIONAL_DEBIT (directional asymmetry dominates the
   variance trade).

2. **Binary gate:** If `p_hit + p_miss > 0.90` (highly binary outcome),
   DEFINED_RISK_CREDIT is forbidden — binary events have fat tails that kill
   short gamma. Demote to MANUAL_REVIEW with `gate_failures=["binary_event"]`.

3. **Timing uncertainty gate:** If `date_precision` is QUARTER or coarser,
   VARIANCE_DEBIT is demoted (theta burn too uncertain). Reclassify to
   TIMING_CALENDAR if TIMING also triggers, otherwise MANUAL_REVIEW.

4. **Belief-permission split gate:** If `belief_strength >= 0.60` but
   `permission_to_express < 0.40`, classify as MANUAL_REVIEW (strong thesis,
   bad execution context — operator should watch but not act). This prevents
   strong beliefs leaking into recommendations despite poor tradability.

---

## Tradeability Gates

All gates must pass for `is_tradeable = True`. If any fail, the recommendation
is still emitted (for diagnostic value) but marked non-tradeable with reasons.

| Gate | Condition | Failure reason |
|------|-----------|----------------|
| Liquidity | `opt_liquidity_state == "liquid"` | `"illiquid_options"` |
| Surface validity | `surface_quality_score >= 50` | `"invalid_surface"` |
| Days to event | `3 <= days_to_event <= 60` | `"event_too_far"` or `"event_too_near"` |
| Analog confidence | `ScenarioPayoffs.analog_confidence != "insufficient"` | `"insufficient_analogs"` |
| Model confidence | `OutcomeProbabilities.confidence >= 0.40` | `"low_model_confidence"` |
| Expectation confidence | `ExpectationErrorScore.expectation_confidence >= 0.50` | `"low_ees_confidence"` |
| Priced move present | `priced_move_pct is not None and > 0` | `"no_priced_move"` |
| Mispricing detected | `mispricing_type != "NONE"` | `"no_mispricing"` |
| Spread width | Per-leg bid-ask within structure limit (see Execution Constraints) | `"spread_too_wide"` |

### Structure-specific gates

| Structure | Additional gate | Failure reason |
|-----------|----------------|----------------|
| RISK_REVERSAL | `opt_rr_25d` available | `"no_skew_data"` |
| SHORT_IRON_CONDOR | `p_hit + p_miss <= 0.90` | `"binary_event"` |
| SHORT_IRON_CONDOR | `surface_quality_score >= 70` | `"surface_too_weak_for_short_gamma"` |
| CALENDAR_SPREAD | `prob_slip >= 0.20` | `"low_delay_probability"` |
| CALENDAR_SPREAD | `timing_confidence >= 0.60` | `"low_timing_confidence"` |
| LONG_STRADDLE | `variance_confidence >= 0.55` | `"low_variance_confidence"` |
| All 4-leg | `execution_risk != "high"` OR `surface_quality_score >= 70` | `"high_execution_risk"` |

---

## Sizing Policy

Conservative, policy-based. NOT empirical-alpha-based.

Three tiers based on `mispricing_confidence`:

| Confidence range | `max_premium_pct_nav` | `sizing_basis` |
|------------------|-----------------------|----------------|
| >= 0.70 | 0.50% | `kelly_capped` (Kelly fraction capped at 0.50%) |
| 0.50 - 0.70 | 0.30% | `fixed_notional` |
| < 0.50 | 0.00% | `no_size` (diagnostic only) |

**Kelly cap rationale:** Even when Kelly suggests larger, the overlay is
speculative relative to the core equity book. 0.50% of NAV per name is the
hard ceiling. At a $5M book, that's $25K premium per position — consistent
with thin biotech option books.

**`belief_strength` formula** (how strong is the mispricing diagnosis):

```
belief_strength = min(
    OutcomeProbabilities.confidence,
    ExpectationErrorScore.expectation_confidence,
    belief_intensity_modifier * 0.8 + 0.2,  # surface conviction
) * data_completeness_factor
```

Where `data_completeness_factor`:
- 1.0 if all inputs present
- 0.8 if surface diagnostics missing
- 0.6 if priced_move_pct is imputed rather than observed

**`permission_to_express` formula** (can the market context support a trade):

```
permission_to_express = min(
    surface_quality_score / 100,    # surface validity
    spread_quality,                  # 1.0 - (actual_spread / max_spread_for_structure)
    liquidity_factor,                # 1.0 if liquid, 0.0 if not
    execution_risk_factor,           # "low"→1.0, "moderate"→0.7, "high"→0.4
)
```

**`mispricing_confidence`** is the binding constraint for sizing:

```
mispricing_confidence = min(belief_strength, permission_to_express)
```

Both must be high. A strong thesis with bad execution context → low confidence
→ no size. Good execution context with weak thesis → also low confidence.
This prevents the most common overlay failure: acting on a strong view in
an untradeable market.

---

## Attribution Loop

Without tracking outcomes, the overlay cannot be evaluated. This section
specifies the minimum forward-monitoring infrastructure required **before
any operator acts on recommendations**.

### What gets logged

**Two logs**, not one. The attribution log tracks outcomes. The decision
log tracks the governance layer itself.

#### 1. Attribution log (`expression_attribution_log.json`)

Every `ExpressionRecommendation` with `is_tradeable == True`:

```python
{
    "ticker": str,
    "node_id": str,
    "as_of_date": str,
    "mispricing_type": str,
    "overlay_class": str,
    "belief_strength": float,
    "permission_to_express": float,
    "mispricing_confidence": float,
    "surface_quality_score": float,

    # Snapshot at recommendation time
    "priced_move_pct": float,
    "scenario_ev": float,
    "opt_atm_iv": float,

    # Filled in after event resolution (from CRT + price data)
    "resolved_date": str | null,
    "outcome": str | null,          # HIT / MISS / MIXED
    "realized_1d_move_pct": float | null,
    "realized_5d_move_pct": float | null,
    "post_event_iv": float | null,

    # Hypothetical P&L (not actual — overlay is diagnostic)
    "hypothetical_pnl_pct": float | null,  # based on structure + realized move
    "attribution_status": str,       # "pending" | "resolved" | "expired"
}
```

#### 2. Decision log (`overlay_decision_log.json`)

**Every** evaluated name — tradeable, rejected, demoted, kill-switched.
This logs the behavior of the governance layer itself.

```python
{
    "ticker": str,
    "node_id": str,
    "as_of_date": str,

    # What happened
    "decision": str,                # "tradeable" | "rejected" | "demoted" | "kill_switched"
    "mispricing_type": str,
    "overlay_class": str,           # final class after any demotion

    # What was considered but rejected (demotion trail)
    "original_overlay_class": str | null,  # pre-demotion class, if demoted
    "demotion_reason": str | null,         # e.g., "binary_event", "spread_too_wide"

    # Gate details
    "gate_failures": list,          # all gates that failed
    "belief_strength": float,
    "permission_to_express": float,
    "surface_quality_score": float,

    # Kill switch state at time of evaluation
    "kill_switch_active": bool,
    "kill_switch_reason": str | null,
}
```

**Why log rejections and demotions:** The postmortem needs to see what the
governance layer *prevented*, not just what it *allowed*. If attribution shows
poor performance, the decision log reveals whether tightening gates would
have helped (rejected names that went on to be right = gates too tight) or
whether the underlying classification is wrong (tradeable names that lost
money, but rejected names also would have lost = classification is broken,
not gates).

### Attribution metrics (computed on resolved entries)

Once enough entries resolve (minimum 20), compute:

1. **By mispricing type:**
   - Mean hypothetical P&L
   - Win rate (% positive)
   - n (sample size)

2. **By expression:**
   - Mean hypothetical P&L
   - Win rate
   - n

3. **By confidence bucket** (0.50-0.60, 0.60-0.70, 0.70+):
   - Mean hypothetical P&L — should be monotonically increasing with confidence

4. **Aggregate:**
   - Total hypothetical P&L (sum across all resolved)
   - Sharpe of hypothetical returns
   - Correlation with equity book returns (should be low — diversification)

### Kill switches

If attribution data shows clear failure, the overlay should be disabled:

| Condition (on 20+ resolved entries) | Action |
|--------------------------------------|--------|
| Aggregate win rate < 40% | Disable all tradeable recommendations (diagnostic-only mode) |
| Any mispricing type win rate < 30% | Disable that type specifically |
| Confidence monotonicity violated (high confidence performs worst) | Disable sizing; revert all to `no_size` |
| Hypothetical Sharpe < -0.50 | Disable entire overlay |

These are **automatic**. The operator can override with explicit governance
sign-off, but the default is: bad evidence → shut down.

### Dashboard

Attribution summary renders on the expression overlay dashboard tab:
- Running scoreboard by type and structure
- Confidence calibration chart
- Kill switch status (green/yellow/red)

### What this is NOT

- Not a backtest. There is no historical options order data to test against.
- Not a live trading log. No trades are executed.
- Hypothetical P&L uses mid-price at recommendation time and realized
  underlying move — it is an upper bound on what a perfect fill would yield.
- Attribution accumulates forward only. First useful evaluation at ~20
  resolved events (likely 2-3 months of accumulation).

---

## Invariants

1. **No production selector/ranker impact.** Zero code changes to
   `selector_engine.py`, `ranker_engine.py`, `decision_engine.py`.
2. **Import barrier.** `selector_engine.py`, `ranker_engine.py`, and
   `decision_engine.py` must NEVER import from `expression_layer.py` or
   `expression_attribution.py`. The expression layer imports *from* event_ev;
   nothing in the scoring stack imports *from* the expression layer. This is
   enforced structurally, not just by policy.
3. **Liquidity gate absolute.** No recommendation for illiquid names.
4. **PIT-safe.** All inputs come from existing PIT-validated layers.
5. **Deterministic.** Same EventEV + EES + surface state → same recommendation.
6. **Governance metadata mandatory.** Every output carries `governance_class`
   and `policy_flags`. No silent promotions.
7. **Output naming.** The primary output field is `overlay_class`, never
   `trade_signal`, `trade_recommendation`, or `alpha_signal`. Naming
   discipline anchors the object's role in the system.
8. **Ontology closed.** The six `overlay_class` values are a closed enum.
   Adding a new class requires a spec amendment with governance review.
9. **Decision log exhaustive.** Every evaluated name is logged — tradeable,
   rejected, demoted, kill-switched. The log covers governance behavior,
   not just recommendations.
10. **Graceful degradation.** Missing inputs → narrower classification
    (fewer types considered) → more NO_TRADE. Never crash.

---

## Failure Modes

| Scenario | Expected behavior |
|----------|-------------------|
| EventEV not computed for ticker | `mispricing_type=NONE`, `expression=NO_TRADE` |
| EES scores all zero (no priced_move_pct) | VARIANCE/TIMING cannot trigger; only DIRECTIONAL possible |
| Surface diagnostics unavailable | TIMING cannot trigger; SKEW degrades; `surface_quality_score=0` |
| Options data absent | All gates fail → `is_tradeable=False`, `gate_failures=["illiquid_options"]` |
| Surface quality < 50 | All gates fail → `is_tradeable=False`, `gate_failures=["invalid_surface"]` |
| Wide bid-ask spread | Structure-specific gate fails → demote or NO_TRADE |
| All mispricing types below threshold | `mispricing_type=NONE`, `expression=NO_TRADE` |
| Multiple types at equal confidence | MIXED type, highest absolute sub-score wins |
| Variance confidence < 0.55 | VARIANCE suppressed, falls through to other types |
| Timing confidence < 0.60 | TIMING suppressed, falls through to other types |
| Attribution kill switch triggered | `is_tradeable=False` for affected type/all, `gate_failures=["kill_switch"]` |
| 4-leg structure on weak surface | Demote to 2-leg or NO_TRADE |

---

## Validation Plan

### Tests (write BEFORE implementation)

- [ ] `test_directional_bullish_classification` — high mispricing_score + positive scenario_ev → DIRECTIONAL/bullish_underpriced
- [ ] `test_directional_bearish_classification` — negative mispricing + negative EV → DIRECTIONAL/bearish_underpriced
- [ ] `test_variance_underpriced` — base_rate_gap < -0.30, low directional → VARIANCE/vol_underpriced
- [ ] `test_variance_overpriced` — base_rate_gap > 0.30 → VARIANCE/vol_overpriced
- [ ] `test_skew_put_rich` — crowding + p_hit > p_miss → SKEW/put_skew_rich
- [ ] `test_timing_near_term` — high prob_slip + timing_decay + backwardation → TIMING
- [ ] `test_mixed_classification` — two types at reduced threshold → MIXED
- [ ] `test_none_when_below_threshold` — all sub-scores low → NONE/NO_TRADE
- [ ] `test_expression_mapping_directional_bull` — DIRECTIONAL/bullish → BULL_CALL_SPREAD
- [ ] `test_expression_mapping_variance_under` — VARIANCE/vol_underpriced → LONG_STRADDLE
- [ ] `test_asymmetry_override` — high asymmetry_ratio overrides LONG_STRADDLE to BULL_CALL_SPREAD
- [ ] `test_binary_gate_blocks_iron_condor` — p_hit + p_miss > 0.90 → SHORT_IRON_CONDOR forbidden
- [ ] `test_timing_uncertainty_demotes_straddle` — coarse date_precision demotes LONG_STRADDLE
- [ ] `test_liquidity_gate` — illiquid → is_tradeable=False
- [ ] `test_days_to_event_gate` — outside [3, 60] → gate failure
- [ ] `test_confidence_gate` — low model confidence → gate failure
- [ ] `test_sizing_tiers` — confidence → correct max_premium_pct_nav
- [ ] `test_sizing_kelly_cap` — high kelly_fraction still capped at 0.50%
- [ ] `test_graceful_degradation_no_options` — missing options → NO_TRADE, no crash
- [ ] `test_graceful_degradation_no_ees` — missing EES → restricted classification
- [ ] `test_deterministic` — same inputs → identical output
- [ ] `test_governance_metadata_always_present` — every output has governance fields
- [ ] `test_to_dict_serialization` — round-trip through to_dict/JSON
- [ ] `test_surface_quality_gate` — surface_quality < 50 → NO_TRADE, is_tradeable=False
- [ ] `test_surface_quality_confidence_penalty` — surface_quality=60 reduces mispricing_confidence
- [ ] `test_spread_width_gate_single_leg` — spread > 8% → gate failure for straddle
- [ ] `test_spread_width_gate_multi_leg` — spread > 6%/leg → gate failure for spreads
- [ ] `test_spread_width_gate_four_leg` — spread > 4%/leg → gate failure for iron condor
- [ ] `test_execution_risk_high_demotes` — 4-leg + weak surface → demoted
- [ ] `test_variance_confidence_suppression` — variance_confidence < 0.55 → VARIANCE suppressed
- [ ] `test_variance_small_sample_penalty` — base_rate n < 10 → variance_confidence penalized
- [ ] `test_timing_confidence_suppression` — timing_confidence < 0.60 → TIMING suppressed
- [ ] `test_attribution_log_schema` — log entry has all required fields
- [ ] `test_attribution_kill_switch_win_rate` — win rate < 40% → disable tradeable
- [ ] `test_attribution_kill_switch_type` — type win rate < 30% → disable that type
- [ ] `test_attribution_kill_switch_confidence` — monotonicity violated → disable sizing
- [ ] `test_leg_count_mapping` — each overlay_class maps to correct leg_count
- [ ] `test_overlay_class_closed_enum` — only 6 valid values accepted
- [ ] `test_belief_permission_split` — high belief + low permission → MANUAL_REVIEW
- [ ] `test_belief_permission_both_high` — both high → tradeable
- [ ] `test_belief_low_permission_high` — low belief + high permission → no_size
- [ ] `test_mispricing_confidence_is_min` — confidence = min(belief, permission)
- [ ] `test_decision_log_records_rejection` — gate failure logged with reason
- [ ] `test_decision_log_records_demotion` — demotion logged with original + final class
- [ ] `test_decision_log_records_kill_switch` — kill switch logged
- [ ] `test_decision_log_records_tradeable` — tradeable recommendation logged
- [ ] `test_import_barrier` — expression_layer not importable from selector/ranker/decision
- [ ] `test_mixed_routes_to_manual_review` — MIXED type → MANUAL_REVIEW overlay_class

### Integration
- [ ] Full test suite passes (existing 11,200+ tests unaffected)
- [ ] No changes to selector/ranker/decision engine tests
- [ ] Dashboard renders new endpoint without breaking existing tabs
- [ ] Attribution log writes correctly to snapshot sidecar

---

## Expected Effect Size

**No direct IC or alpha impact.** This is a diagnostic translation layer.

Expected benefits:
- Operator can see *how* to express the view the EV engine already identifies
- Structure selection is deterministic and auditable (vs ad-hoc operator judgment)
- Governance metadata prevents silent scope creep
- Foundation for future options overlay execution (if/when evidence justifies)

---

## Non-Goals

- Reopening options-as-alpha (Spec 053 CLOSED)
- Modifying selector, ranker, or construction
- Auto-execution of options trades
- Greeks-based P&L simulation (already in Spec 059 Phase B)
- New data feeds or external dependencies
- Backtesting the expression layer (no historical options order data)
- Fitting thresholds to data (all thresholds are policy-chosen, not optimized)
- Modeling actual fill probability or order routing
- Building a market-maker or vol-arb system
- Tuning structures based on attribution P&L (kill switches disable, not optimize)

---

## Scope Boundaries — What This Spec Changes and Does Not Change

### Production alpha path: UNTOUCHED

The production scoring pipeline is:

```
selector_engine (A4 config)
  → selector_score
  → pairwise v2 model (ranker_v2_model.json, 2 features: coinvest_score_z + financial_score)
  → final_score
  → Top-30 by final_score → EW construction
```

**None of these components are modified by this spec.** The pairwise v2 model
is loaded from `production_data/ranker_v2_model.json` and scored via
`ranker_v2_pairwise.py`. It does not consult `RankerConfig` block weights,
`ranker_engine.py` signal specs, or any of the clinical quality features
modified here.

### What IS changed (all diagnostic/shadow)

| File | Change | Production impact |
|------|--------|-------------------|
| `common/massive_chain_analytics.py` | Catalyst-aligned straddle computation | **None** — enriches CSV row fields consumed by Event EV overlay, not selector/ranker |
| `common/options_diagnostics.py` | Nearby event premium detection (sub-7-DTE) | **None** — adds `NEARBY` flag to `opt_event_premium` diagnostic field |
| `common/event_quality_features.py` | PCD overdue + soft catalyst penalties on `clinical_date_confidence` | **None** — output goes to CSV columns and shadow ranker V2 only. NOT consumed by production selector or ranker (verified: `selector_engine.py` uses `clinical_optionality_pct_dev` etc., not `clinical_date_confidence`) |
| `ranker_engine.py` | Block weights updated to clinical_50 blend | **None** — `RankerConfig` is shadow/fallback only. Production uses `ranker_mode="pairwise_minimal"` which bypasses `compute_ranker_adjustments()` entirely (dispatch at `run_screen.py:4743`) |
| `run_screen.py` | Wire catalyst-aligned straddle, prefer `catalyst_straddle_price` | **None** — affects `_chain_straddle_price` row field (diagnostic), not any scoring feature |

### Alpha stack freeze compliance

Per `policy_alpha_freeze_2026_04_04.md`:
- No new promotions: ✅ (no features enter scoring stack)
- Pairwise = ordinal only: ✅ (pairwise model untouched)
- Ranker frozen at 2 features: ✅ (ranker_v2_model.json unchanged)
- No Checklist v2 bypass: ✅ (no signal promotion)

---

## PIT Safety

All inputs consumed by this spec are PIT-safe by construction:

| Input source | PIT mechanism |
|-------------|---------------|
| Options chain data (Massive API) | Live market data — no historical leakage possible |
| `catalyst_days` | Derived from catalyst calendar, which is PIT-validated (Spec 048) |
| EventEV sub-scores | Built on PIT-validated layers (outcome model, timing hazard, payoff engine) |
| `clinical_date_confidence` | Computed from catalyst metadata (precision, source) — no price data |
| CRT resolution outcomes (attribution) | Only consumed AFTER resolution date — strictly forward-looking |

**No new historical data dependencies.** The expression layer does not introduce
any data source that could create look-ahead bias.

---

## Rollback Conditions

### When to rollback

1. **Catalyst-aligned straddle produces garbage** — straddle prices are
   nonsensical (negative, > 100% of underlying) for >10% of names
2. **Nearby event premium false positives** — NEARBY classification fires
   on non-event names (e.g., dividend dates, index rebalances)
3. **PCD overdue penalty too aggressive** — names with legitimate date
   uncertainty get their clinical_date_confidence crushed (affects shadow
   ranker V2 comparison, not production, but still diagnostic noise)
4. **clinical_50 shadow shows degradation** — shadow comparison vs production
   pairwise shows meaningful divergence in wrong direction
5. **Any production scoring path contamination** — if any of these changes
   unexpectedly feed into selector/ranker/construction (should be impossible
   per code review, but defense in depth)

### How to rollback

```bash
# Full revert: restore all 6 files from main
git checkout main -- \
  common/massive_chain_analytics.py \
  common/options_diagnostics.py \
  common/event_quality_features.py \
  run_screen.py \
  ranker_engine.py

# Partial: revert individual components
git checkout main -- common/massive_chain_analytics.py  # catalyst straddle only
git checkout main -- common/options_diagnostics.py      # nearby premium only
git checkout main -- common/event_quality_features.py   # PCD penalty only
git checkout main -- ranker_engine.py                   # clinical_50 weights only
```

**No data migration required.** All changes are code-only. Snapshot sidecar
files (`overlay_recommendations.json`, `overlay_decision_log.json`) are
additive and can be safely deleted if the spec is reverted.

**No downstream dependency.** No other spec, agent, or pipeline step depends
on outputs introduced by this spec. Revert is clean.

---

## Implementation Plan

### Phase 1 — Data contract + classification engine

1. Add `ExpressionRecommendation` dataclass to `event_ev/data_contracts.py`
   (with `overlay_class` enum, `belief_strength`, `permission_to_express`)
2. Build `event_ev/expression_layer.py`:
   - `compute_surface_quality()` — surface validity scoring
   - `compute_belief_strength()` — thesis confidence independent of market
   - `compute_permission_to_express()` — execution/market context viability
   - `compute_variance_confidence()` — variance-specific confidence
   - `compute_timing_confidence()` — timing-specific confidence
   - `classify_mispricing()` — takes EV layer outputs, returns (type, subtype)
   - `select_overlay_class()` — deterministic mapping with context overrides
   - `check_tradeability_gates()` — all gates including surface, spread, execution
   - `compute_sizing()` — policy-based tiers from mispricing_confidence
   - `build_recommendation()` — orchestrator, returns `ExpressionRecommendation`
3. Tests for all classification rules, overlay class mappings, gates, sizing,
   surface validity, variance/timing confidence suppression, belief/permission split
4. Import barrier test: verify selector/ranker/decision cannot import expression_layer

### Phase 2 — Pipeline wiring + logging + attribution

1. Wire into `ev_calculator.py` → optional `ExpressionRecommendation` on EventEV
2. Wire into `run_screen.py`:
   - Write `overlay_recommendations.json` sidecar (tradeable only)
   - Write `overlay_decision_log.json` sidecar (ALL decisions: tradeable + rejected + demoted + kill-switched)
3. Build `event_ev/expression_attribution.py`:
   - `log_recommendation()` — append to attribution log (tradeable)
   - `log_decision()` — append to decision log (ALL evaluated names)
   - `resolve_attribution()` — join with CRT outcomes + price data
   - `compute_attribution_metrics()` — by type, overlay_class, confidence
   - `check_kill_switches()` — automatic disable on bad evidence
4. Add to daily snapshot artifact set

### Phase 3 — Dashboard

1. `GET /api/expression_overlay/{date}` endpoint
2. Ticker detail enrichment with expression_overlay field
3. Render overlay_class, confidence, rationale, gate status
4. Attribution scoreboard tab (running P&L by type/overlay_class)
5. Kill switch status indicator (green/yellow/red)
6. Decision log viewer (rejections, demotions, suppressions)

---

## Implementation Log

*(empty — spec is DRAFT)*

---

*Template version: 1.0.0 — see specs/SYSTEM_SPEC.md for system invariants*
