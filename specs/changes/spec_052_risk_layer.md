# Change Spec 052: Portfolio Risk Layer

**Status**: COMPLETE
**Author**: Claude / arrenchulz
**Date**: 2026-04-04
**Ruleset impact**: NO (infrastructure, not signal/ranking change)

---

## Objective

Add enforceable portfolio-level risk controls to the EW Top-30 construction. The book changed substantially (A4 selector, pairwise ranker, EW Top-30) and runs with no systematic guardrails beyond entry gates. This spec adds concentration enforcement, liquidity-aware sizing, drawdown monitoring, and therapeutic-area diversification — all as hard constraints applied at construction time, not advisory policy.

## Context

**Existing infrastructure (already built, not enforced):**
- `portfolio_policy.json` (v4): defines caps, bucket targets, regulatory ladder — but caps are advisory
- `risk_gates.py`: fail-closed entry gates (ADV, price, market cap, runway) — screening only
- `liquidity_scoring.py`: per-name liquidity score (0-100) — not used in construction
- `options_risk_controls.py`: 0-30d defensive controls — applied as multipliers, not hard caps
- `dilution_risk_engine.py`: forced-raise probability — scoring only
- `build_rebalance_plan.py`: generates EW plan with no cap enforcement

**What's missing:** a module that sits between ranking output and final portfolio weights, enforcing hard constraints from `portfolio_policy.json` and new risk rules.

## Design

### New module: `portfolio_risk_layer.py`

A deterministic, stateless function that takes ranked positions + policy → returns constrained weights.

```
apply_risk_layer(
    positions: List[Position],      # ranked, with metadata
    policy: PortfolioPolicy,        # from portfolio_policy.json
    market_data: MarketSnapshot,    # prices, ADV, XBI state
) -> RiskLayerResult:
    # Returns: constrained weights, flags, breach log
```

### Controls (ordered by application priority)

#### C1: Single-name concentration cap (ENFORCE)
- Hard cap: `global_name_cap.cap_pct` (currently 3.0%)
- After drift between rebalances, trim any name exceeding cap + buffer (0.5%)
- Trimmed weight redistributed EW across remaining names
- **Invariant**: no position > cap + buffer at any rebalance

#### C2: Therapeutic-area concentration limit (NEW)
- Max 40% of portfolio weight in any single `therapeutic_area`
- Coinvest herds into oncology; this prevents 60%+ single-area exposure
- If breached: drop lowest-ranked name(s) in the overweight area, replace with next eligible from underweight areas
- **Fallback**: if fewer than 3 areas represented, WARN but do not block

#### C3: Liquidity-aware position ceiling (NEW)
- For each name, compute `max_position_usd = ADV_20d * max_adv_pct` (default: 5% of ADV)
- If target position > max_position_usd, cap weight proportionally
- Redistributed weight goes EW to uncapped names
- Uses `liquidity_scoring.py` ADV extraction (already built)
- **Invariant**: no position requires > max_adv_pct of daily volume to enter/exit

#### C4: Drawdown circuit breaker (NEW)
- **Portfolio-level**: if portfolio drawdown from trailing 20d high > 15%, reduce all caps by 25% (multiplicative)
- **Single-name**: if any held name drops > 40% in trailing 20d, flag for forced review (WARN, not auto-sell)
- Uses price_history.csv trailing window
- `global_cap_shock` in policy already has the schema — this activates and extends it
- **Invariant**: circuit breaker is monotonic (only tightens, never loosens within a rebalance)

#### C5: Correlated-pair limit (NEW)
- Max 2 names sharing the same `primary_indication` + `lead_program_phase` combination
- Prevents doubling up on e.g. two Phase 3 NASH names where both fail on the same thesis
- If breached: keep higher-ranked, drop lower-ranked, replace with next eligible
- **Fallback**: if indication data missing, skip this check for that pair

### Application order

```
Raw EW weights (1/30 each)
  → C1: single-name cap
  → C2: therapeutic-area cap
  → C3: liquidity ceiling
  → C4: drawdown tightening
  → C5: correlated-pair limit
  → Renormalize to 100%
  → Output final weights + breach log
```

Each control is independent and composable. Controls run sequentially so earlier caps feed into later checks.

## PIT / Data Constraints

- [x] No lookahead — uses only data available at rebalance date
- [x] Data sources: `portfolio_policy.json`, `rankings.csv`, `price_history.csv`, `liquidity_scoring.py`
- [x] Historical availability: all inputs exist back to 2020
- [x] Known gaps: `therapeutic_area` may be missing for some names (fallback: skip C2/C5 for those names)

## Inputs

| Input | Source | Schema |
|-------|--------|--------|
| Ranked positions | `rankings.csv` | ticker, actionable_rank, therapeutic_area, primary_indication, lead_program_phase |
| Policy | `portfolio_policy.json` | v4 schema (see existing file) |
| Prices | `price_history.csv` | ticker, date, close |
| ADV | `rankings.csv` or `risk_gates.py` | avg_daily_volume_20d (float) |
| XBI state | `price_history.csv` | XBI trailing 20d high, current |

## Outputs

| Output | Destination | Schema |
|--------|-------------|--------|
| Constrained weights | `RiskLayerResult.weights` | `{ticker: float}` summing to 1.0 |
| Breach log | `RiskLayerResult.breaches` | `List[{control, ticker, detail, action}]` |
| Risk flags | `RiskLayerResult.flags` | `List[{flag_type, ticker, severity, detail}]` |
| Summary | `artifacts/risk_layer/{date}.json` | Full result + policy snapshot |

## Invariants

1. **Weight conservation**: sum of output weights == 1.0 (±0.001)
2. **Deterministic**: same inputs → same outputs across runs
3. **Monotonic tightening**: drawdown breaker only reduces caps, never increases
4. **No phantom positions**: output tickers are a subset of input ranked positions
5. **Cap compliance**: after application, no single name exceeds its effective cap
6. **Fail-open on missing data**: if a control's required data is missing, skip that control with WARN (don't block the portfolio)

## Failure Modes

| Scenario | Expected behavior |
|----------|-------------------|
| Missing therapeutic_area | Skip C2 for that name, WARN in breach log |
| Missing ADV | Skip C3 for that name (no liquidity cap), WARN |
| Missing price history | Skip C4 entirely, WARN |
| All names breach C2 | WARN "cannot diversify", apply remaining controls |
| Policy file missing | FAIL — risk layer refuses to produce unconstrained weights |

## Validation Plan

### Tests (write BEFORE implementation)
- [x] `test_risk_layer_ew_passthrough` — with no breaches, output == input EW weights
- [x] `test_risk_layer_single_name_cap` — drift scenario triggers trim + redistribution
- [x] `test_risk_layer_therapeutic_area_cap` — 5 oncology names, cap at 40%
- [x] `test_risk_layer_liquidity_ceiling` — micro-cap with low ADV gets capped
- [x] `test_risk_layer_drawdown_breaker` — 20% drawdown triggers 25% cap reduction
- [x] `test_risk_layer_correlated_pair` — two Phase 3 NASH names, one dropped
- [x] `test_risk_layer_deterministic` — same inputs → same outputs (10 runs)
- [x] `test_risk_layer_weight_conservation` — sum == 1.0 after all controls
- [x] `test_risk_layer_missing_data_fallback` — missing therapeutic_area → skip C2, WARN
- [x] `test_risk_layer_composition` — all 5 controls applied in sequence
- [x] `test_risk_layer_policy_missing_fails` — no policy file → hard failure

### Integration
- [x] Wire into `build_rebalance_plan.py` between ranking and trade generation
- [x] Wire into `run_daily_production.py` as post-ranking step
- [x] Breach log written to `artifacts/risk_layer/{date}.json`
- [x] Full test suite passes (16/16)
- [x] No pre-commit hook failures

## Expected Effect Size

Structural risk improvement, no direct alpha impact. May reduce realized volatility and max drawdown. The primary value is preventing concentration-driven blowups, not improving expected returns.

## Non-Goals

- Not a signal or ranking change — does not affect which names are selected
- Not a regime-switching mechanism — drawdown breaker is mechanical, not predictive
- Not a dynamic allocation optimizer — controls are rule-based caps, not optimization
- Not replacing existing entry gates (risk_gates.py) — this layer acts post-selection
- Not implementing VaR or portfolio optimization — that's a future spec if ever needed

## Policy Changes Required

Update `portfolio_policy.json` to v5 with new fields:

```json
{
  "risk_layer_enabled": true,
  "therapeutic_area_cap_pct": 0.40,
  "liquidity_max_adv_pct": 0.05,
  "drawdown_breaker": {
    "enabled": true,
    "portfolio_dd_threshold": 0.15,
    "portfolio_dd_cap_multiplier": 0.75,
    "single_name_dd_threshold": 0.40,
    "single_name_action": "WARN"
  },
  "correlated_pair_limit": {
    "enabled": true,
    "max_same_indication_phase": 2
  }
}
```

---

## Implementation Log

- **2026-04-04**: Module `portfolio_risk_layer.py` complete — 5 controls (C1–C5), 300 LOC
- **2026-04-04**: 16 tests in `tests/test_portfolio_risk_layer.py`, all passing
- **2026-04-04**: Wired into `build_rebalance_plan.py` — risk_layer output in rebalance plan JSON
- **2026-04-04**: Wired into `run_daily_production.py` — standalone artifact at `artifacts/risk_layer/{date}.json`
- **2026-04-04**: `portfolio_policy.json` updated to v5 with risk_layer fields
- **2026-04-04**: All validation checklist items complete

---

*Template version: 1.0.0 — see specs/SYSTEM_SPEC.md for system invariants*
