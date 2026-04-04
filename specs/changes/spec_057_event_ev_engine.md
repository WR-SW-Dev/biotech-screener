# Spec 057 — Bayesian Biotech Event EV Engine

**Status:** RESEARCH  
**Created:** 2026-04-04  
**Phase:** A (Design) + B (Catalyst graph + timing) + C (Outcome/expectation/payoff) + D (Eval harness)

## Motivation

The current model is a cross-sectional factor/ranker: institutional is the dominant signal,
risk is second, clinical is destructive, and the options-as-alpha lane is closed. Every recent
study converges on the same ceiling — the next order-of-magnitude leap requires modeling
**biotech catalysts as probabilistic events with scenario EV**, not ranking names by another
factor.

This spec builds a parallel research engine that estimates, for each actionable catalyst:

1. **Timing distribution** — when it will really happen
2. **Outcome probabilities** — HIT / MISS / MIXED branch odds
3. **Market expectation** — what the crowd already prices
4. **Scenario payoffs** — branch-conditional stock moves
5. **Expected value** — probability-weighted, downside-adjusted EV
6. **Risk-adjusted sizing** — subject to production risk layer

## Architecture

Six explicit layers, each a separate module in `event_ev/`:

```
Layer 1: Catalyst Graph    → CatalystNode (unified event object)
Layer 2: Timing Hazard     → TimingEstimate (on-time prob, slip prob, distribution)
Layer 3: Outcome Model     → OutcomeProbabilities (HIT/MISS/MIXED + calibration)
Layer 4: Expectation Model → CrowdBelief (what market is pricing)
Layer 5: Payoff Engine     → ScenarioPayoffs (branch moves, EV, asymmetry)
Layer 6: Portfolio Layer   → PositionRecommendation (size, hold/trim, risk constraints)

EV Calculator ties layers 1-6 into a single EventEV per catalyst.
```

## Layer 1 — Catalyst Graph (`catalyst_graph.py`)

### CatalystNode schema

```python
@dataclass
class CatalystNode:
    node_id: str              # deterministic hash
    ticker: str
    event_family: str         # REGULATORY, CLINICAL, SAFETY
    event_type: str           # PDUFA, DATA_READOUT, PHASE_3_READOUT, etc.
    event_subtype: str        # specific (e.g. "TOPLINE", "INTERIM", "ADCOM")
    
    # Timing
    expected_date: date | None
    date_range_start: date | None
    date_range_end: date | None
    date_precision: str       # DAY, WEEK, MONTH, QUARTER, HALF_YEAR, UNKNOWN
    date_confidence: float    # [0, 1]
    
    # Provenance
    source: str               # CTGOV, SEC_8K, PDUFA_MANUAL, HERALD, FDA_FEDREG
    source_uid: str
    disclosed_at: date        # PIT anchor
    
    # Context
    phase: str
    indication: str
    modality: str | None
    sponsor_quality: float | None   # [0, 1] from execution priors
    nct_id: str | None
    
    # Graph
    depends_on: list[str]     # node_ids of prerequisite events
    blocks: list[str]         # node_ids this event gates
    
    # Status
    status: str               # PENDING, ACTIVE, RESOLVED, WITHDRAWN, DELAYED
    resolution: str | None    # HIT, MISS, MIXED, DELAYED (from CRT)
    resolved_date: date | None
    
    # Revision history
    revisions: list[dict]     # [{date, field, old_value, new_value, source}]
```

### Integration with existing infrastructure

- Consumes: `LedgerEntry` (event_ledger.py), `CatalystEvent` (event_detector.py),
  `ResolutionRecord` (CRT), `NewsEvent` (herald), PDUFA dates, clinical_pos_priors
- Produces: Unified `CatalystNode` objects with dependency graph

### PIT rules

- Only nodes with `disclosed_at <= as_of_date` are visible
- Revisions are filtered to `revision.date <= as_of_date`
- Resolution data only populated after `resolved_date <= as_of_date`

## Layer 2 — Timing Hazard (`timing_hazard.py`)

### Purpose

Estimate the probability distribution of when a catalyst actually occurs,
given what is known as of the evaluation date.

### Output: TimingEstimate

```python
@dataclass
class TimingEstimate:
    node_id: str
    as_of_date: date
    prob_on_time: float       # P(event in expected window)
    prob_slip: float          # P(event slips beyond window)
    prob_early: float         # P(event arrives early)
    expected_delay_days: float
    median_arrival_days: float
    hazard_rate: float        # instantaneous event-arrival rate
    features_used: dict       # explainability
    model_version: str
```

### Modeling approach

**Primary:** Discrete-time logistic event-in-window model

For each catalyst, estimate P(arrives in window W | features):

Features:
- `days_to_expected` — calendar distance
- `date_precision` — DAY/WEEK/MONTH/QUARTER (lower precision → higher slip risk)
- `phase` — early phases slip more
- `event_family` — REGULATORY has hard dates, CLINICAL is soft
- `n_prior_revisions` — more revisions → higher slip risk
- `last_revision_direction` — pushout vs pullin momentum
- `sponsor_quality` — execution track record
- `ctgov_status` — RECRUITING vs ACTIVE_NOT_RECRUITING vs COMPLETED
- `amendment_count` — protocol churn
- `enrollment_progress` — if available from AACT

**Calibration:** Evaluated on historical ledger entries where we know actual vs expected dates.

### PIT safety

- Feature computation uses only revisions known at `as_of_date`
- Actual arrival date is never used in feature computation (only in evaluation)

## Layer 3 — Outcome Model (`outcome_model.py`)

### Purpose

Estimate branch probabilities for each catalyst outcome.

### Output: OutcomeProbabilities

```python
@dataclass
class OutcomeProbabilities:
    node_id: str
    as_of_date: date
    p_hit: float
    p_miss: float
    p_mixed: float
    confidence: float         # model confidence in these estimates
    prior_source: str         # "wong_et_al", "v2_empirical", "indication_phase"
    features_used: dict
    calibration_check: dict   # Brier, ECE from training
    model_version: str
```

### Modeling approach

**Bayesian prior-posterior framework:**

1. **Prior:** Clinical PoS from `clinical_pos_prior.py` (Wong et al. + v2 empirical)
   - Keyed by (phase, indication, endpoint_class)
   - This gives base P(HIT) by phase/indication

2. **Likelihood updates** (features that shift away from prior):
   - `endpoint_strength_score` — hard endpoint → higher P(HIT)
   - `design_quality_score` — better design → higher P(HIT)
   - `sponsor_quality` — track record adjustment
   - `indication_difficulty` — some indications are harder
   - `modality_prior` — gene therapy vs small molecule vs antibody
   - `competitive_landscape` — crowded indication → lower marginal value even if HIT
   - `execution_momentum` — on-track execution → slight positive update

3. **P(MIXED):** Allocated from residual — starts at fixed fraction (e.g., 15%),
   adjusted by endpoint ambiguity and trial complexity

4. **Constraint:** p_hit + p_miss + p_mixed = 1.0

### Calibration

- Evaluated against CRT resolution records (HIT/MISS/MIXED outcomes)
- Brier score, ECE, reliability curve
- Stratified by phase, indication, event_family

### PIT safety

- PoS priors are versioned and dated
- Feature scores use only data available at `as_of_date`
- No future resolution leakage

## Layer 4 — Market Expectation (`expectation_model.py`)

### Purpose

Estimate what the market already believes about the catalyst outcome.

### Output: CrowdBelief

```python
@dataclass
class CrowdBelief:
    node_id: str
    as_of_date: date
    implied_p_hit: float      # market's implied P(positive outcome)
    belief_direction: str     # BULLISH, BEARISH, NEUTRAL, UNCERTAIN
    belief_intensity: float   # [0, 1] how strongly positioned
    priced_move_pct: float    # options-implied move if available
    mispricing_score: float   # gap between model P(HIT) and market implied
    features_used: dict
    model_version: str
```

### Modeling approach

**Cross-sectional belief proxy model:**

Inputs (all PIT-safe, all available in production):
- `coinvest_score_z` — institutional co-investment (dominant signal)
- `inst_delta_z` — institutional accumulation delta
- `insider_net_buy_value_90d` — Form 4 insider context
- `alpha_60d` — pre-event price drift
- `de_rsi_14d` — momentum/sentiment
- `short_interest_pct` — bearish positioning proxy
- `opt_event_premium` — options-implied event premium (diagnostic only)
- `priced_move_pct` — options-implied move (diagnostic only)

**Method:** Percentile-rank each feature cross-sectionally, then compute
weighted average as "crowd belief score." Convert to implied P(HIT) via
sigmoid mapping calibrated against historical outcomes.

This is NOT trying to predict the outcome. It is trying to estimate
what the market already believes, so we can identify mispricing.

### PIT safety

- All features are PIT-native (13F filing dates, Form 4 filing dates, price data)
- Options data uses most recent available before `as_of_date`

## Layer 5 — Scenario Payoff (`payoff_engine.py`)

### Purpose

Estimate branch-conditional stock moves and compute scenario EV.

### Output: ScenarioPayoffs

```python
@dataclass
class ScenarioPayoffs:
    node_id: str
    as_of_date: date
    # Branch payoffs (percentage moves)
    upside_hit: float         # expected % move if HIT
    downside_miss: float      # expected % move if MISS (negative)
    move_mixed: float         # expected % move if MIXED
    # Derived
    scenario_ev: float        # probability-weighted expected move
    asymmetry_ratio: float    # |upside_hit| / |downside_miss|
    downside_adjusted_ev: float  # EV with downside penalty
    kelly_fraction: float     # Kelly-optimal fraction (theoretical)
    # Diagnostics
    analog_count: int         # how many historical analogs
    analog_confidence: str    # ok / low / insufficient
    features_used: dict
    model_version: str
```

### Modeling approach

**Analog-based empirical distributions:**

1. Look up historical move distributions from `event_move_lookup.py`
   keyed by (catalyst_family, phase_bucket, indication_bucket)

2. Condition on outcome:
   - HIT analogs → upside distribution
   - MISS analogs → downside distribution  
   - MIXED analogs → mixed distribution

3. Use median (p50) as point estimate, with p25/p75 for range

4. Adjustments:
   - `market_cap_bucket` — smaller names move more
   - `liquidity_score` — illiquid names have wider distributions
   - `vol_60d` — current volatility context
   - `gap_risk` — overnight gap risk for binary events

### Scenario EV computation

```
scenario_ev = p_hit * upside_hit + p_miss * downside_miss + p_mixed * move_mixed
```

### Asymmetry and downside-adjusted EV

```
asymmetry_ratio = |upside_hit| / |downside_miss|
downside_adjusted_ev = scenario_ev - lambda * p_miss * |downside_miss|
```

where lambda is a risk-aversion parameter (default 0.5).

### PIT safety

- Analog lookup uses only events resolved before `as_of_date`
- Price data for analogs uses only realized moves up to that date

## Layer 6 — Portfolio Translation (`portfolio_translator.py`)

### Purpose

Convert event EV into tradeable position recommendations subject to risk constraints.

### Output: PositionRecommendation

```python
@dataclass
class PositionRecommendation:
    ticker: str
    node_id: str
    action: str               # HOLD, ADD, TRIM, EXIT, NO_ACTION
    target_weight_pct: float
    max_weight_pct: float     # risk cap
    ev_rank: int              # rank within event cohort
    risk_flags: list[str]
    reasoning: dict
    model_version: str
```

### Constraints

Respects current production risk layer:
- Concentration caps (per-name, per-indication)
- Liquidity caps
- Event clustering (multiple catalysts in same week)
- Drawdown rules
- Correlation/overlap from `clustering.py`

### Sizing approaches

1. **EV-proportional:** weight ∝ max(0, downside_adjusted_ev)
2. **Kelly-capped:** theoretical Kelly fraction with half-Kelly cap
3. **Equal-weight with EV filter:** EW among names with positive EV
4. **Hybrid:** production weight * EV multiplier (bounded ±30%)

## EV Calculator (`ev_calculator.py`)

Ties all six layers together:

```python
@dataclass
class EventEV:
    node: CatalystNode           # Layer 1
    timing: TimingEstimate       # Layer 2
    outcome: OutcomeProbabilities # Layer 3
    expectation: CrowdBelief     # Layer 4
    payoff: ScenarioPayoffs      # Layer 5
    position: PositionRecommendation | None  # Layer 6
    
    # Summary
    scenario_ev: float
    mispricing_score: float
    actionable: bool
    ev_rank: int | None
```

## Evaluation Plan

### Timing layer

- Binary accuracy: did the event land in the predicted window?
- Calibration: are P(on_time) estimates well-calibrated?
- Feature importance: which features drive timing accuracy?
- Comparison: timing model vs naive "always on time" baseline

### Outcome layer

- Brier score vs clinical PoS prior alone
- ECE and reliability curves
- Stratified by phase, indication, event_family
- Comparison: Bayesian model vs raw PoS prior vs random

### Expectation layer

- Does mispricing_score predict post-event returns?
- IC of mispricing_score vs raw institutional signals
- Cross-sectional rank correlation

### Payoff / EV layer

- Does scenario_ev rank names better than production model?
- IC of scenario_ev at 30d/60d/90d horizons
- Hit rate: % of positive-EV names that outperform

### Portfolio comparison

Six baselines:
1. Current production book
2. Current production + risk layer
3. Current production + EV overlay (tie-breaker)
4. Pure EV-ranked event cohort
5. Hybrid: baseline selector, EV sizing
6. Hybrid: baseline selector, EV tie-breaker

Metrics: excess return, Sharpe, IR, max drawdown, turnover, hit rate

## Risks and Limitations

1. **Small N problem:** CRT has ~12 seeded resolutions. Outcome model calibration
   will be underpowered until resolution count grows. Timing model has more data
   (ledger history) but still limited for rare event types.

2. **Analog sparsity:** Some (family, phase, indication) cells have <5 analogs.
   Fallback hierarchy handles this but confidence will be low.

3. **Market expectation is a proxy:** We are inferring crowd belief from
   institutional positioning, not observing it directly. This layer is inherently
   approximate.

4. **Not a production replacement yet.** This is research infrastructure.
   First practical use is likely EV tie-breaker or sizing overlay.

5. **Herald quality:** Outcome model quality depends on Herald precision,
   which is still being audited (Spec 053/056).

## File Layout

```
event_ev/
  __init__.py
  data_contracts.py       # All dataclasses/schemas
  catalyst_graph.py       # Layer 1
  timing_hazard.py        # Layer 2
  outcome_model.py        # Layer 3
  expectation_model.py    # Layer 4
  payoff_engine.py        # Layer 5
  portfolio_translator.py # Layer 6
  ev_calculator.py        # Orchestrator
  
scripts/research/
  run_event_ev_study.py   # Research harness
  
tests/
  test_event_ev_engine.py # Unit + integration tests
```
