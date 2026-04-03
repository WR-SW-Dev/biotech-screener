# Change Spec: Selector/Ranker Signal Backtest Framework

**Status**: DRAFT
**Author**: Research / DEM
**Date**: 2026-04-03
**Ruleset impact**: NO (research infrastructure — no production scoring changes)

---

## Objective

Establish a governed, PIT-safe framework that classifies every collected signal into one of five roles (gate, selector, ranker, regime-only, reject) and tests each signal against the correct evaluation target for its role. This replaces ad-hoc signal testing with a repeatable, stage-separated research stack.

The motivating fact: the corrected PIT benchmark moved Top-20 excess from +93.7pp to −28.2pp and Top-30 from +110.5pp to −25.1pp vs XBI. Rank IC remained negative at −0.051. That means informal weighting decisions can no longer lean on legacy evidence — stage-separated, PIT-safe signal cards are mandatory.

## PIT / Data Constraints

- [x] No lookahead — all signal tests use PIT-safe snapshots only
- [x] Data source: `data/snapshots_pit_v2/`, `production_data/`, rankings CSV, `pit_financials.py` outputs
- [x] Historical availability: 76 monthly snapshots in `data/snapshots_pit_v2/`
- [x] Known gaps: options coverage ~65% of top-60; AACT delta pipeline newly shipped (thin history); 13F freshness decays between filing windows

## Inputs

| Input | Source | Schema |
|-------|--------|--------|
| PIT snapshots | `data/snapshots_pit_v2/YYYY-MM/` | one rankings.csv per month |
| Component scores | rankings.csv columns | `momentum_score`, `catalyst_score`, `smart_money_score`, `valuation_score`, `clinical_score`, `financial_score`, `clinical_score_v2_z` |
| Composite | rankings.csv | `composite_score`, `composite_rank`, `score_z`, `score_rank_pct` |
| Clinical detail | rankings.csv | `lead_program_phase`, `program_count`, `program_diversification`, `readout_density_90`, `endpoint_strength_score`, `design_quality_score`, `execution_momentum` |
| Catalyst | rankings.csv + decision_engine | `catalyst_days`, `catalyst_mode`, `catalyst_bucket`, `catalyst_strength`, `catalyst_decay_w`, `cat_priority`, `catalyst_event_type` |
| Institutional | rankings.csv | `inst_delta_z`, `inst_delta_net`, `inst_delta_new`, `inst_delta_exit`, `coinvest_conviction`, `coinvest_filing_age_days` |
| Financial | rankings.csv + decision_engine | `severity`, `financial_score`, `cash_total`, `missing_components` |
| Options | options pipeline outputs | `opt_atm_iv`, `opt_rr_25d`, `actual_implied_move_pctile`, `opt_liquidity_state`, OVF fields |
| AACT deltas | `scripts/research/aact_*` outputs | `execution_score`, PCD deltas |
| Microstructure | rankings.csv | `total_volume_z` (pending validation) |
| Regime labels | XBI returns, VIX, macro feeds | XBI 20d/63d return sign, vol terciles |
| Forward returns | `selection_benchmark.py` / `build_selection_benchmark.py` | ticker-level returns at 20d, 63d vs XBI and vs eligible EW |

## Outputs

| Output | Destination | Schema |
|--------|-------------|--------|
| Research panel | `output/signals/research_panel.parquet` | one row per ticker × snapshot_date, all features + labels |
| Signal cards | `output/signals/<signal_name>/signal_card.json` | metrics per evaluation pass |
| Signal reports | `output/signals/<signal_name>/signal_card.md` | human-readable evidence card |
| Signal panels | `output/signals/<signal_name>/signal_panel.csv` | per-period raw data |
| Signal manifest | `output/signals/signal_manifest.json` | role classification for every signal |
| Selector bundle report | `output/signals/selector_bundle_report.md` | bundle comparison table |
| Ranker bundle report | `output/signals/ranker_bundle_report.md` | within-top-K comparison table |

## Invariants

1. **PIT-safe only.** No signal test may use data that was not available as of the snapshot date. Filing-date-gated financials, IPO-date survivorship, posting-date trial safety net, date-correct rankings. (Ref: SYSTEM_SPEC.md PIT invariants)
2. **Role separation.** A signal's evaluation target must match its intended role. Selector signals are tested on top-K membership quality. Ranker signals are tested on within-top-K ordering only. No cross-contamination.
3. **Coverage explicit.** Every signal card must report coverage %, missingness %, effective N, and live feasibility flag.
4. **Net-of-cost bar.** Ranker promotion requires cost-adjusted improvement over EW, not raw IC alone. Cost model from `selection_benchmark.py` (~65bps/yr).
5. **No mixed-era evidence.** Pre-PIT-correction results may be retained for history but cannot support promotion decisions.
6. **Deterministic.** Same snapshot inputs → same signal card outputs across runs.

## Failure Modes

| Scenario | Expected behavior |
|----------|-------------------|
| Signal coverage < 30% in a period | Mark period as `insufficient_coverage`, exclude from aggregates, flag in card |
| PIT snapshot missing for a month | Skip month, report gap in panel |
| Forward return unavailable (delisted, halted) | Exclude ticker-month, report survivorship N |
| Signal is constant (zero variance) | IC = NaN, report as `degenerate`, auto-classify as REJECT |
| Regime label unavailable | Fall back to `unknown_regime`, report in regime section |

## Validation Plan

### Tests (write BEFORE implementation)

- [ ] `test_research_panel_pit_safe` — no future data leaks in any column
- [ ] `test_research_panel_coverage` — coverage fields match actual non-null counts
- [ ] `test_signal_card_schema` — every card has all required fields
- [ ] `test_signal_card_deterministic` — same inputs → same outputs
- [ ] `test_selector_labels_correct` — top-K membership labels match actual rankings
- [ ] `test_ranker_labels_within_topk` — ranker metrics computed only on top-K subset
- [ ] `test_regime_splits_exhaustive` — every period assigned exactly one regime label
- [ ] `test_promotion_bar_enforced` — card verdict respects promotion thresholds

### Evaluation (if signal/ranking change)

This spec is research infrastructure, not a direct scoring change. The evaluation framework itself is the deliverable:

- [ ] Every signal produces a card with selector metrics at 20d, 63d
- [ ] Every signal produces a card with ranker metrics at 20d, 63d
- [ ] Every signal has regime-split outputs
- [ ] Bundle tests compare against EW top-30 baseline

### Integration

- [ ] Full suite passes
- [ ] No pre-commit hook failures
- [ ] Signal manifest renders correctly

---

## Design

### 1. Architectural separation

The framework enforces three distinct signal roles:

**Gates** — hard eligibility filters. Not weighted. Keep names out.
- `drawdown`, `drawdown_rel_xbi`, `severity`, `financials_missing`, liquidity/ADV

**Selectors** — determine top-bucket membership. Slow-moving, broad-coverage, PIT-safe.
- Clinical optionality / program quality
- Catalyst architecture
- Financial survivability
- Institutional freshness

**Rankers** — improve ordering within the selected bucket only. May be narrow-coverage or event-driven.
- Options / event-premium
- AACT / timeline delta
- Microstructure / attention
- Catalyst-type nuance

This matches the existing DEM stack: M1–M5 → `decision_engine.py` (eligibility + overlays + tiers) → rankings → benchmarking.

### 2. Signal inventory

#### 2.1 Gate signals

| Signal | Source column(s) | Current status |
|--------|-----------------|----------------|
| Drawdown | `risk_flags.drawdown_*` | Active gate in decision_engine |
| Drawdown relative | `dd_rel_margin_rescued` | Active gate |
| Severity / red flags | `severity` | Active gate |
| Financials missing | `missing_components`, `financial_score` | Active gate (`financials_missing`) |
| Liquidity / ADV | `size_band`, `cost_bucket` | Active gate |

#### 2.2 Selector signals — Tier A (core candidates)

**Clinical optionality / program quality:**
- `clinical_score_v2_z` (current anchor)
- `lead_program_phase` / `stage_bucket`
- `program_count`, `program_diversification`
- `endpoint_strength_score`
- `design_quality_score`
- `readout_density_90`
- `clinical_score` (M5 component)
- `clinical_optionality_pct_dev`

**Catalyst architecture:**
- `catalyst_days`, `catalyst_bucket`
- `catalyst_mode` (specific / blended / missing)
- `catalyst_strength`, `catalyst_decay_w`
- `cat_priority`
- `catalyst_event_type` (regulatory vs clinical)

**Financial survivability:**
- `severity`
- `financial_score`
- runway (derived)
- `missing_components` count

**Institutional freshness:**
- `inst_delta_z` — only confirmed extra active sort signal
- `inst_delta_net`, `inst_delta_new`, `inst_delta_exit`
- `coinvest_filing_age_days`
- `coinvest_conviction`

#### 2.3 Ranker signals — Tier B (within-top-K only)

**Options / event-premium:**
- `actual_implied_move_pctile`
- `opt_atm_iv`, `opt_rr_25d`
- event premium ratio
- IV regime
- implied vs realized ratio
- `opt_liquidity_state`
- OVF composite fields

**AACT / timeline delta:**
- PCD pull-ins / delays
- `execution_score`
- enrollment progress deltas
- status upgrades / downgrades

**Microstructure / attention:**
- `total_volume_z` (pending April 7 validation — currently NO_GO)
- unusual turnover shifts

#### 2.4 Low-priority modifiers — Tier C

- `competitive_intensity_z` / oncology crowding
- Dealability priors
- Commercial moat / Purple Book context
- `archetype` interactions

### 3. Evaluation passes

Every signal is evaluated four ways:

**Pass A — Gate utility**
Does this signal help exclude losers without removing winners?
- Conditional excess: pass group vs fail group
- Change in selector hit rate after gating
- False-negative audit on known strong names (e.g., would gating exclude names that subsequently returned >30%?)

**Pass B — Selector utility**
Does this signal improve candidate-set quality?
- Δ top-20 EW excess vs XBI
- Δ top-30 EW excess vs XBI
- Δ top-20 EW excess vs eligible EW
- Δ hit rate, IR, cumulative excess
- Δ turnover

**Pass C — Ranker utility**
Does this signal improve ordering inside the selected bucket?
- Within-top-K Spearman IC
- Pairwise win rate
- RW top-K minus EW top-K (gross and net of costs)
- Turnover delta
- Top-quintile vs bottom-quintile spread inside top-K

This aligns with the existing `ranker_evaluation_harness.py` which already computes IC, RW−EW spread, quintile analysis, and cost-adjusted net spread within top-30.

**Pass D — Stability / regime**
When does this work?
- XBI 20d return: < −2%, −2% to +2%, > +2%
- High-vol vs low-vol (VIX tercile or XBI realized vol)
- Regulatory vs clinical catalyst family
- Near (0–30d) vs mid (31–90d) vs far (91–180d) catalyst
- Liquid-options vs thin-options
- Fresh vs stale institutional state

Extends the existing bear/bull regime split in `selection_benchmark.py` (line ~364).

### 4. Research baseline weights

Starting hypotheses for bundle testing. **These are not production weights.**

**Selector baseline:**
| Family | Weight | Rationale |
|--------|--------|-----------|
| Clinical optionality / program quality | 45% | Current anchor; conceptually strongest |
| Catalyst architecture | 25% | Timing structure matters for biotech alpha |
| Financial survivability | 20% | Survival to catalyst is existential |
| Institutional freshness | 10% | Only confirmed extra active sort contributor |

**Ranker baseline (within top-K only):**
| Family | Weight | Rationale |
|--------|--------|-----------|
| Options / event-premium | 35% | Highest raw IC in prior work; coverage-limited |
| Institutional freshness | 25% | inst_delta_z sensitivity best at Top-20 |
| AACT / timeline delta | 20% | Trajectory > static quality |
| Catalyst-type nuance | 10% | Priority/type differentiation within bucket |
| Microstructure / attention | 10% | Research-grade; total_volume_z pending |

**Capital allocation default:** Equal-weight top-K until ranker beats EW net of costs. Prior work showed RW not ready (−46.2pp behind EW30).

### 5. Promotion bars

#### Gate promotion
- Selector quality improves materially
- False-negative rate acceptable (audit on known winners)
- Survives PIT-safe rerun
- Adequate coverage
- Regime behavior understandable

#### Selector signal promotion
- Top-20 or top-30 EW excess improves at longest horizon (63d)
- Survives corrected PIT-safe data
- Not concentrated in one short period
- Turnover and coverage acceptable
- No guardrail breach elsewhere
- Paired t-stat ≥ 2.0 for the bundle improvement

#### Ranker promotion
- Top-K IC positive and stable
- RW top-K beats EW top-K net of costs (~65bps/yr)
- Survives regime splits
- Live coverage sufficient (options ≥ 40%, inst ≥ 50% per `check_ranker_readiness.py`)
- Economically material (≥ +0.20pp/mo improvement)

#### Rejection rule
- PIT-safe evidence weak or negative
- Effect disappears in top-K even if full-universe looks positive
- Net-of-cost improvement absent
- Too narrow to matter operationally

### 6. Regime framework

**Status of prior regime claims:** The corrected PIT benchmark shows bear regime basically flat (+0.01pp, IR 0.00) and bull mildly positive (+1.21pp, IR 0.15). The old "strong in bear" story is not established after correction.

**Operating rule:** Regime dependence is a valid reason to hold a signal in `shadow_only` or `regime_overlay`. It is NOT sufficient for broad production promotion unless live regime detection is stable and the economic effect survives costs.

The rich regime engine is already running as a shadow comparator (7/7 feeds live, switching policy FROZEN). Signal regime interactions should use the same regime labels for consistency.

### 7. Signal card schema

```json
{
  "signal_name": "string",
  "signal_family": "string",
  "intended_role": "gate | selector | ranker | modifier",
  "pit_safe": true,
  "source_columns": ["string"],
  "coverage_pct": 0.0,
  "missing_pct": 0.0,
  "effective_n": 0,
  "live_feasibility": true,
  "selector_metrics": {
    "h20": {"delta_top20_ew_excess": 0.0, "delta_top30_ew_excess": 0.0, "delta_hit_rate": 0.0, "delta_ir": 0.0},
    "h63": {"delta_top20_ew_excess": 0.0, "delta_top30_ew_excess": 0.0, "delta_hit_rate": 0.0, "delta_ir": 0.0}
  },
  "ranker_metrics": {
    "h20": {"ic": 0.0, "ic_tstat": 0.0, "ic_hit_rate": 0.0, "rw_minus_ew_gross": 0.0, "rw_minus_ew_net": 0.0},
    "h63": {"ic": 0.0, "ic_tstat": 0.0, "ic_hit_rate": 0.0, "rw_minus_ew_gross": 0.0, "rw_minus_ew_net": 0.0}
  },
  "regime_metrics": {
    "bear": {"mean_excess": 0.0, "hit_rate": 0.0, "ir": 0.0, "n": 0},
    "neutral": {"mean_excess": 0.0, "hit_rate": 0.0, "ir": 0.0, "n": 0},
    "bull": {"mean_excess": 0.0, "hit_rate": 0.0, "ir": 0.0, "n": 0}
  },
  "decision": "REJECT | HOLD | SHADOW | PROMOTE",
  "failure_mode": "string",
  "notes": "string"
}
```

---

## Expected Effect Size

This spec is research infrastructure. It does not directly change scoring or alpha. The expected outcome is:

- Classification of ~30–40 signals into role categories
- Identification of 0–3 signals worth promoting (pessimistic given corrected PIT results)
- Confirmation that EW top-K remains the right capital allocation default
- Possible identification of regime-conditional signals worth shadowing

Be honest: after the PIT correction, the prior for finding strong new signals is modest. The primary value is governance — preventing false-positive promotions.

## Non-Goals

- No production construction changes from this spec alone
- No automatic promotion of any signal
- No revival of pre-correction contaminated evidence
- No sleeve budget optimization
- No regime-switching policy changes
- No new data collection (uses existing pipeline outputs only)

---

## Implementation Plan

### Phase 1 — Research panel construction
Build `output/signals/research_panel.parquet`:
- Join PIT snapshots × forward returns × regime labels
- Include all gate, selector, ranker, modifier columns
- Validate PIT safety and coverage
- **Script:** `scripts/research/build_signal_research_panel.py`

### Phase 2 — Univariate signal cards
Run single-signal evaluation for every candidate:
- All four passes (gate, selector, ranker, regime)
- Write signal_card.json + signal_card.md + signal_panel.csv
- Write signal_manifest.json with role classification
- **Script:** `scripts/research/run_signal_cards.py`

### Phase 3 — Selector bundle tests
Test interpretable bundles against EW top-30 baseline:
1. Optionality only (clinical_score_v2_z)
2. Optionality + catalyst
3. Optionality + catalyst + survivability
4. Optionality + catalyst + survivability + inst freshness
- **Script:** `scripts/research/test_selector_bundles.py`

### Phase 4 — Ranker bundle tests (within top-30 only)
Leverage existing `ranker_evaluation_harness.py`:
1. Options bundle
2. AACT bundle
3. Institutional freshness bundle
4. Combined ranker bundle
- **Script:** `scripts/research/test_ranker_bundles.py`

### Phase 5 — Governed recommendation
Produce:
- Gate recommendations (keep/add/remove)
- Selector factor recommendations (retain/add/reject)
- Ranker shadow recommendations (shadow/promote/reject)
- Permanent reject list with evidence

---

## Implementation Log

### 2026-04-03 — Spec drafted
- Spec created from square-one signal audit
- Grounded in corrected PIT benchmark results and existing infrastructure
- Aligned with `ranker_evaluation_harness.py`, `selection_benchmark.py`, `check_ranker_readiness.py`

---

*Template version: 1.0.0 — see specs/SYSTEM_SPEC.md for system invariants*
