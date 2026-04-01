# Wake Robin DEM — Model Documentation

**Version:** 1.12.0 (ruleset `69a0c7f8`)
**Last updated:** 2026-04-01
**Status:** Production — daily automated runs, shadow portfolio tracking

---

## 1. System Overview

Wake Robin is a systematic biotech screening and portfolio construction system.
It ranks ~294 biotech names by asymmetric event-driven upside potential, with
the goal of identifying names where clinical/regulatory catalysts create
favorable risk/reward ahead of binary outcomes.

### Architecture

```
Universe (M1) → Financial Health (M2) → Catalyst Events (M3) → Clinical Dev (M4)
→ Composite Scoring (M5) → Decision Engine (L0→L2→L4→L4b→L3) → Portfolio Construction
→ Shadow Portfolio → Performance Attribution → Governance Gates
```

### Core Invariants

1. **Deterministic**: Same inputs → byte-identical outputs. No randomness. Full hash verification.
2. **Point-in-Time (PIT) Safe**: All data access satisfies `source_date <= as_of_date - 1`. Enforced via `pit_enforcement.py`.
3. **Fail-Closed**: Gates default FAIL unless proven otherwise. Validate and stop on errors.
4. **Decimal Arithmetic**: All financials use `Decimal`, never floats.
5. **Stdlib-Only Core**: Modules 1–5 have zero external dependencies.

---

## 2. Decision Engine

The DEM (Decision Engine Model) takes composite-scored names and applies a
layered decision framework to produce a final ranked list with tier assignments
and size bands.

### Layer 0 — Eligibility (Hard Gates)

Determines whether a name is eligible for ranking. All gates must pass.

| Gate | Threshold | Mode |
|------|-----------|------|
| Drawdown | ≤ -0.40 | Hard (v1.12.0) |
| Drawdown hard floor | ≤ -0.75 | Always fail |
| Drawdown relative to XBI | ≥ -0.25 | AND with drawdown gate |
| Financials missing | cash_total ≤ 0 | Bypass for mega-cap |
| Survivability | Red flag severity | Configurable threshold |
| Liquidity | Dollar volume | Configurable threshold |

**Key pitfall:** `financials_missing` gate requires `cash_total <= 0`. Fields
`missing_cash` / `missing_burn_data` are misleading for profitable companies
with positive cash flow.

### Layer 2 — Risk Flags & Momentum

Overlay risk signals on eligible names. These inform sizing and reporting but
do not gate eligibility.

| Signal | Threshold | Effect |
|--------|-----------|--------|
| Volatility (60d) | > 1.20 | Risk flag |
| Beta (XBI, 60d) | > 1.80 | Risk flag |
| Drawdown | < -0.35 | Risk flag |
| RSI (14d) | > 70.0 | Overbought flag |
| Confidence | < 0.30 | Low confidence flag |

**Momentum classification:**
- `alpha_60d_z > +0.05` → tailwind
- `alpha_60d_z < -0.05` → headwind
- else → neutral

### Layer 4 — Development Tier (Drug Developers)

Assigns A/B/C/D tier based on clinical optionality and catalyst presence.

| Tier | Criteria |
|------|----------|
| **A** | optionality ≥ 0.60 AND actionable catalyst (within 120d) |
| **B** | optionality ≥ 0.60 (no actionable catalyst) OR optionality ≥ 0.30 + actionable catalyst |
| **C** | optionality ≥ 0.30 (no catalyst) OR optionality < 0.30 |
| **D** | Ineligible or no optionality data |

### Layer 4b — Commercial Tier (Non-Drug Developers)

Same structure as Layer 4, but uses `commercial_quality_pct` with floors 0.85 / 0.60.

### Layer 3 — Position Sizing

Size bands: XS (0.15), S (0.30), M (0.60), L (1.00).

**Active modifiers (v1.12.0):**
- Cost haircut: enabled (bid-ask spread penalty)
- Catalyst tilt: disabled
- Catalyst type tilt: disabled
- Momentum tilt: disabled

### Sort Key

12-element tuple determining final rank order:

```
(eligible, is_dev, tier_ord, catalyst_priority, catalyst_mode,
 catalyst_days, missing_count, -optionality_pct + signal_adjustments,
 -sponsor_count, momentum_ord, anchor, ticker)
```

**Sort anchor:** `optionality_pct` (negated — higher optionality sorts first)

**Active sort signal:** `inst_delta_z` (weight 0.3, positive-only, clamped ±2.0)

**Disabled sort signals:** clinical, coinvest, calendar_alpha, catalyst_type, momentum

---

## 3. Signal Inventory

### Confirmed Signals

| Signal | IC | Horizon | Status | Notes |
|--------|-----|---------|--------|-------|
| **Optionality anchor** | Stable (IC ~0.14 at 20d) | Primary | **ACTIVE** — sort anchor | Drives tier assignment and ranking |
| **inst_delta_z** | +0.077 | 60d | **ACTIVE** — sort contributor w=0.3 | Only confirmed sort signal beyond anchor |
| **actual_implied_move_pctile** | +0.202 | — | Diagnostic only | Highest raw IC but narrow coverage (39.8%) |

### Rejected / Disabled Signals

| Signal | IC | Reason | Status |
|--------|-----|--------|--------|
| cal_alpha | ~0 | Confirmed noise at all horizons | REMOVED in v1.12.0 |
| clinical_sort | — | Insufficient IC | OFF |
| coinvest | — | IC below bar | REJECTED |
| oncology_crowding | +0.020pp | 10x below promotion bar | NEEDS_MORE |
| milestone_optionality | +0.026 at 84d | t=2.60, positive 77%, narrow | NEEDS_MORE |
| quality_tiebreaks (Specs 030/031) | — | Economically immaterial | Lane EXHAUSTED |

### Pending Validation

| Signal | Expected IC | Validation Date | Notes |
|--------|-------------|----------------|-------|
| total_volume_z | 0.134 | April 7, 2026 | Script queued |

---

## 4. Data Sources

### Production Pipeline Inputs

| Source | Coverage | Refresh | Path |
|--------|----------|---------|------|
| Price history | 341 tickers, daily | Daily | `production_data/price_history.csv` |
| Market data | 340 tickers (100%) | Every 2-3 days | `production_data/market_data.json` |
| Universe | 341 tickers | Manual | `production_data/universe.json` |
| 13F institutional | 29 managers, 58.2% ticker coverage | Quarterly (~May 15 next) | `production_data/institutional_summary.json` |
| ClinicalTrials.gov | 18,703 trials (PIT cached) | Daily | `cache/ctgov/trial_records_{date}.json` |
| FDA designations | 207 entries, 84 tickers, 58.3% top-60 | Manual | `production_data/fda_designations.json` |
| Catalyst calendar | Manual + CTgov + regulatory | Daily + manual | `production_data/regulatory_calendar.json` |
| Options surface | 65.6% coverage (193/294) | Daily | Via Tastytrade API |

### Supplementary Data Sources

| Source | Records | Tickers Linked | Status |
|--------|---------|---------------|--------|
| AACT clinical trials | 578,527 trials | 21,752 (49 tickers) | Live — `data/aact/snapshots/` |
| Purple Book biologics | 2,013 products | 530 (49 tickers) | Live — `production_data/purple_book.json` |
| Herald press releases | 3,312 classified | 336 tickers | Live — `data/press_releases/` |
| DealForma deal comps | — | — | Spec 046 ready, awaiting CSV export |

### Data Quality Summary

| Dimension | Coverage | Notes |
|-----------|----------|-------|
| Tier/momentum/archetype | 100% | Core fields always populated |
| Catalyst fields | ~85% | Some names lack dated catalysts |
| Options (ATM IV) | 65.6% | Weakest production lane; fix deployed (expanded request set) |
| RR 25d | 39.8% | Gated by options chain availability |
| Implied move | 38.8% | Same gate |
| clinical_lead_phase | 0% | Field not populated (use lead_program_phase) |

---

## 5. Portfolio Construction

### Current Architecture (v3 Policy)

**Account:** $500,000 notional
**Rebalance:** Weekly (Friday)

**Sleeve budget allocation:**

| Sleeve | Target | Top-K | Per-Name Cap |
|--------|--------|-------|-------------|
| binary_91_180 (91-180d catalyst) | 55% | 20 | 3.0% |
| binary_31_90 (31-90d catalyst) | 25% | 15 | 2.0% |
| binary_0_30 (0-30d catalyst) | 10% | 10 | 1.0% |
| less_binary (no dated catalyst) | 10% | 15 | 2.0% |

**Additional rules:**
- Family splits (REGULATORY / CLINICAL) within sleeves
- Regulatory time-ladder sub-buckets (0-14d, 15-45d, 46-90d, 91-180d)
- Quality tilt within regulatory sub-buckets
- Gap risk cap (≤ 7 days to catalyst → 0.5% cap)
- Rebalance buffer: 30 ranks
- Global per-name cap: 3.0%

### Construction Diagnosis (2026-04-01)

**Finding: The selection layer generates real alpha. The construction layer destroys it.**

#### Selection-Only Benchmark (EW Top-20, PIT, 2020-2026)

| Metric | Value |
|--------|-------|
| Cumulative return | +151.1% |
| Cumulative excess vs XBI | **+95.2%** |
| Win rate (daily excess > 0) | 53.1% |
| Information ratio | 1.41 |
| Positive excess years | 6 of 7 |

#### Drag Decomposition

| Construction Layer | Excess vs XBI | Drag from Prior |
|-------------------|---------------|-----------------|
| EW Top-20 (pure selection) | +95.2% | — |
| EW Bucketed (sleeves, EW within) | +19.3% | -75.95% (50% of total drag) |
| Policy-Weighted (55/25/10/10) | -28.4% | -47.62% (31%) |
| Full Shadow (all rules) | -58.4% | -30.01% (19%) |
| **Total construction drag** | | **+153.6%** |

**Root cause:** Fixed sleeve budget allocation, not per-name caps or other rules.
Sleeve labels as metadata are harmless (loose sleeves = EW). The damage comes
from forcing capital into the 91-180d bucket at 55%.

#### Regime Asymmetry

| Regime | EW Top-20 Excess | IR |
|--------|-----------------|-----|
| Bear XBI (daily return ≤ 0) | **+102.8%** | **3.35** |
| Bull XBI (daily return > 0) | -7.6% | -0.21 |

The selector's edge is a **bear-market phenomenon**. Optionality-anchored names
hold value during selloffs because their catalyst-driven upside is less correlated
with sector beta. The model is a **downside-protection engine**, not an all-weather
momentum strategy.

#### Construction v2 Candidates

| Candidate | Full-History IR | 2024-2026 IR | 2026 YTD IR | Mean Turnover |
|-----------|----------------|-------------|-------------|---------------|
| **EW Top-30** | **1.51** | **2.70** | **2.64** | **12.8%** |
| EW Top-20 | 1.41 | 1.99 | 1.37 | 20.6% |
| Rank-Weighted Top-20 | 0.86 | 1.06 | 1.08 | 20.6% |

**EW Top-30 is the leading candidate** for construction v2: higher IR, lower
turnover, strong across all recent windows.

#### Transaction Cost Analysis

Estimated cost drag by candidate across full history (390 periods), assuming
conservative round-trip costs for small/mid-cap biotech:

| Candidate | Gross Excess | Drag (30 bps) | Drag (50 bps) | Drag (80 bps) | Net Excess (50 bps) |
|-----------|-------------|--------------|--------------|--------------|-------------------|
| **EW Top-30** | +95.8% | -6.0% | **-10.0%** | -16.0% | **+85.8%** |
| EW Top-20 | +95.2% | -9.6% | -16.0% | -25.7% | +79.2% |
| Rank-Weighted Top-20 | +59.8% | -9.6% | -16.0% | -25.7% | +43.8% |

**EW Top-30 wins net of costs.** Its lower turnover (12.8% vs 20.6%) saves ~6%
over full history at 50 bps. The advantage *widens* after transaction costs.

Cost drag is real (~10-16% over 6 years) but small relative to the 153.6%
construction drag from sleeve budgets. Transaction costs are not the primary
problem — fixed budget allocation is.

Rebalance cost model: `common/rebalance_cost_model.py` (17 tests).
Components: spread estimation by market-cap bucket, impact by ADV, portfolio
cost aggregation, rebalance threshold gate (only trade if expected alpha >
2× estimated cost).

#### Standing Benchmarks (established 2026-04-01)

| Benchmark | Role | Status |
|-----------|------|--------|
| **EW Top-30** | New default control | Active |
| Rank-Weighted Top-30 | Shadow overlay (regime-dependent, not always-on) | Shadow |
| Current shadow (sleeve-budget) | Legacy comparator to beat | Legacy |

#### Operating Conclusion

> The DEM is a good stock picker being badly monetized by the portfolio
> construction layer. The main failure is not "risk controls are too tight."
> It is that the portfolio is organized around fixed sleeve budgets that
> destroy concentration in the best ideas.

> Fixed sleeve budgeting is the leak. Bucket labels are fine as metadata.
> Top-30 equal weight is the strongest simple replacement candidate.
> The selector's edge is regime-dependent, strongest in bear biotech.

#### Construction v2 Shadow (live since 2026-04-01)

Construction v2 runs daily as Step 5o in the production pipeline, tracking two
variants alongside the legacy shadow:

| Variant | Rule | Status |
|---------|------|--------|
| **EW Top-30** | Equal-weight top-30 by DEM rank | **New default control** |
| **Regime-Conditioned** | Bear: top-20, Bull: top-30 (XBI 20d + hysteresis) | Shadow overlay |
| Legacy shadow | Full sleeve-budget construction | Legacy comparator |

**Regime classifier:** XBI 20-day return, bear < -2%, bull > +2%, min 5-day duration.

**Backfill (March 1 - April 1, 17 periods):**
- EW Top-30: -6.97%, +2.15% excess vs XBI
- Legacy shadow: -5.54%, -4.86% excess vs XBI

**Do not carry forward:** fixed sleeve budgets, dynamic caps, always-on rank-weighting.

#### Options Signal Work (built 2026-04-01)

**Event premium decomposition** (`common/event_premium_decomp.py`, 26 tests):
Decomposes the options surface into 8 within-top-30 ranking features:
`epd_event_premium_ratio`, `epd_term_slope_z`, `epd_skew_richness_z`,
`epd_iv_momentum`, `epd_implied_vs_realized_ratio`, `epd_iv_per_catalyst_day`,
`epd_surface_regime`, `epd_quality`. Runs daily as Step 5l.4b. 28/30 top names
at full quality using 254K rows of historical IV features.

**Options cohort diagnostics** (`scripts/research/options_cohort_diagnostics.py`):
Cuts by hard/soft, regulatory/clinical, near/mid/far, liquid/thin, surface type.
Key finding: eligible-name options coverage is 96% (not 65.6%), liquidity (42%)
is the real gate. Highest-dispersion cohort: hard catalyst + regulatory + liquid.

**CRT × options join** (`scripts/research/build_crt_options_join.py`):
27 resolutions joined with prediction-time options state. Foundation for the
catalyst EV model. Realized-return backfill needed.

**Options EV pilot** (`scripts/research/options_ev_pilot.py`):
First directional results on 905 observations (5 dates, h5 horizon):
- EPR signal is inverted across full universe (high EPR = overpriced) but
  **positive inside top-30** (event-loaded +4.4% vs flat +2.9%)
- IV regime: NORMAL +1.3%, ELEVATED +0.7%, EXTREME -1.1%
- Hard catalysts outperform soft by +59bps
- Caveat: 5 dates only, directional not conclusive

**Next:** h20/h63 returns mature mid-April; rerun EV pilot and ranker with
options-populated window.

#### Next Construction Experiments

1. **Correlation/concentration penalty** — lightweight risk overlay on EW Top-30
2. **Regime classifier stability testing** — monitor flip frequency, turnover on transitions
3. All candidates must survive transaction-cost gate before promotion

---

## 6. Catalyst Resolution Tracker (CRT)

Prediction → resolution → calibration loop for hard catalysts.

**Status:** All 4 phases shipped (Spec 042)
**Resolutions:** 14 seeded (6 HIT, 8 MISS)
**Calibration:** Monotonic hit rate by DEM rank (100% → 67% → 33% → 0%)

### CRT Architecture

```
Watchlist Builder → Source Adapters (8-K, CTgov, PDUFA, Manual)
→ Outcome Classification → Price Direction → Resolution Record
→ Calibration Rollup → Governance Triggers
```

### Resolution Record Schema

- `ticker`, `catalyst_date`, `catalyst_type`, `prediction_dem_rank`, `prediction_tier`
- `outcome`: HIT / MISS / EXOGENOUS / INFORMATIONAL
- `price_direction`: up / down / flat
- `event_outcome`: scored against event result, not price

### RR Adjudication Policy

Score `event_outcome`, not `price_direction`. BIIB excluded as EXOGENOUS (M&A).
Current scorable: 1/3 (PVLA correct, CELC+TBPH wrong). Gate: BIIB PDUFA May 24.

---

## 7. Shadow Portfolio Performance

**Period:** 2026-03-03 to 2026-04-01 (25 trading days)
**Status:** HOLD (readiness verdict)

| Metric | Value |
|--------|-------|
| Cumulative return | -5.54% |
| Excess vs XBI | -4.86% |
| Max drawdown | 7.52% |
| Sharpe | -2.047 |
| Win rate | 24% |
| PnL | -$26,310 |

**Sleeve attribution:**
- binary_0_30: -$1,335
- binary_31_90: -$83
- binary_91_180: **-$24,132** (92% of total loss)
- less_binary: -$760

---

## 8. Governance Stack

### Ruleset Governance

- Active ruleset pinned in `run_screen.py` with hash verification
- Promotion requires: evidence packet, replay comparison, canary regression
- Promotion bars: +0.20pp at longest horizon, guardrail -0.05pp
- Rollback: any candidate can be disabled via ruleset toggle

### Production Gates (29 checks)

| Category | Gates | Current Status |
|----------|-------|---------------|
| Core | ruleset, trading_day, inputs | PASS |
| Data freshness | XBI staleness, market data, CTgov, 13F | PASS |
| Schema | market_data, DE schema, sort contrib | PASS |
| Drift | top-20/60 overlap, Spearman, migrations | WARN (66.7% top-20) |
| Risk | concentration, exposure, portfolio weights | PASS |
| Forward eval | rolling IC | WARN (IC -0.021 < floor 0.02) |
| Canary | 3 historical dates | PASS (INFO) |

### Signal Governance

All new signals follow: research → evidence packet → shadow → governed promotion.
Minimum bars: IC > 0.03 at 60d (sort signals), +0.20pp at longest horizon (ranking).

---

## 9. OpenClaw Agent Fleet

18 agents on gateway ws://127.0.0.1:18789, Sonnet 4.6.

### Production Monitors (cron-scheduled)

| Agent | Schedule | Role |
|-------|----------|------|
| ops | 5:00 PM ET weekdays | Packet interpreter, reads digest |
| sentinel | 5:15 PM ET | Drift monitor, rollback advisor |
| qa | 5:30 PM ET | Artifact validation, regression check |
| calibration | Fri 6:00 PM ET | Weekly candidate review |

### Data Warehouse

| Agent | Role | Status |
|-------|------|--------|
| aact_trial_ingest (Archivist) | Bulk AACT clinical trial warehouse | Phase 1 live, 578K trials |
| company_news_ingest (Herald) | Deterministic PR collection | Live, 336 tickers |

### Alpha-Adjacent

| Agent | Role | Status |
|-------|------|--------|
| catalyst_delta | Event-change detection | Trial graduated |
| options_watch | Options surface flags | Builder live |
| shadow_monitor | Performance triage | Live (read-only) |
| postmortem | Event resolution evidence | Starts after April catalysts |

---

## 10. Dashboard

React + Vite 6 + Tailwind v3 + Recharts frontend with FastAPI backend.

### Endpoints

| Endpoint | Purpose |
|----------|---------|
| `/api/rankings/{date}` | Full rankings table |
| `/api/ticker/{ticker}` | Merged ticker detail |
| `/api/aact/{ticker}` | AACT trial records for ticker |
| `/api/deal_comps/{ticker}` | DealForma deal comp context |
| `/api/purple_book/{ticker}` | Biologics competition context |
| `/api/crt/resolutions` | CRT resolution records |
| `/api/crt/calibration` | CRT calibration summary |
| `/api/shadow_performance` | Shadow portfolio timeseries |
| `/api/bioshort/verdict` | Hedge report verdict |
| `/api/herald/health` | Press release collection health |
| `/api/aact/health` | AACT ingest health |

### TickerDetail Tabs

Overview | Options | Portfolio | Trials | Deals | Bio | CRT

---

## 11. Roadmap (April-May 2026)

### Phase 1: This Week (April 1-7)

- [x] Selection-only benchmark → **DONE**: +95.2% excess, IR 1.41
- [x] Construction drag decomposition → **DONE**: 50/31/19 split identified
- [x] Construction v2 candidate pack → **DONE**: EW Top-30 leads (IR 2.64-2.81)
- [x] Transaction-cost / rebalance threshold model → **DONE**: EW Top-30 wins net of costs (+85.8% at 50 bps)
- [x] Monthly IC decomposition → **DONE**: see below
- [ ] total_volume_z validation (April 7)

#### Monthly IC Decomposition Results

| Scope | Mean IC (h20) | % Positive | Interpretation |
|-------|--------------|-----------|----------------|
| Full universe | -0.044 | 34.4% | Ranking is poor at ordering middle/bottom |
| **Top-30 only** | **-0.004** | **50.4%** | Within-top-30 ordering does not predict |

**Interpretation:** The DEM is a **filter/selector**, not a **ranker**. It identifies
a good bucket of ~30 names (EW Top-30 generates +95% excess) but does not
meaningfully distinguish rank #1 from rank #30 within that bucket. This explains
why EW outperforms rank-weighting and why top-20 and top-30 produce similar excess.

**Monthly pattern:** IC is episodic. Strong positive months (2023-04: +0.224,
2024-01: +0.171) interspersed with negative months. Last 6 months (2024 H2)
show deeply negative IC (-0.137 mean) driven by overall biotech selloff.

**Implication for construction:** EW is the correct weighting scheme. Rank-based
concentration would only help if within-top-30 IC were reliably positive, which
it is not. This further validates the EW Top-30 construction choice.

### Architectural Decision: Two-Stage Model

The monthly IC decomposition revealed that DEM is a **filter/selector**, not a
**ranker**. Full-universe IC is negative (-0.044), top-30-only IC is zero. The
model says "these 30 are interesting" but not "this one is better than that one."

**Architecture:**
1. **Stage 1 — Selector (DEM, proven):** Identifies the top-30 candidate set.
   Keep fixed. EW Top-30 is the correct construction because within-bucket
   ordering doesn't predict.
2. **Stage 2 — Ranker (new, shadow-first):** A dedicated within-top-30 model
   that answers "among names DEM already likes, which should get more capital?"

**Ranker features** (vary meaningfully inside the top bucket):
- Options mispricing: `actual_implied_move_pctile`, event premium, skew/RR
- AACT timeline deltas: PCD shifts, enrollment changes, results posted
- `inst_delta_z` (only confirmed sort contributor)
- `total_volume_z` (if validated)
- Catalyst type differentiation (regulatory vs pivotal vs mid-stage)
- DealForma dealability priors (slow-moving)

**Promotion bar for ranker:**
- Top-30-only IC meaningfully positive and stable
- Rank-weighted-by-ranker Top-30 beats EW Top-30 net of costs
- Survives by regime
- Until then: selector = active, ranker = shadow

### Phase 2: April

- [ ] Lightweight risk layer (correlation penalty, vol targeting)
- [ ] Options coverage push to 80% + event-premium decomposition
- [ ] Herald precision audit
- [ ] Dashboard integration pass (AACT index optimization)

### Phase 3: May — Two-Stage Ranker

- [x] Build top-30 rank dataset → **DONE**: 7,157 feature rows, 86,759 pairwise rows
- [x] First ranker training → **DONE**: null result — correct (features empty in test window)
- [x] Ranker readiness gate → **DONE**: 8/30 eligible dates, blocked on options accumulation
- [ ] Accumulate ranker-ready snapshots (target: late April, ~30 eligible dates)
- [ ] AACT delta features for within-top-30 ranking
- [ ] Options event-premium decomposition for within-top-30 ranking
- [ ] Retrain ranker on ranker-ready window
- [ ] Validate: top-30-only IC, rank-weighted vs EW, pairwise accuracy
- [ ] DealForma dealability prior as slow-moving ranker feature
- [ ] Governed shadow review / promote-reject gates

**Ranker status:** Paused. First training produced a correct null result — all
models at coin-flip accuracy because test window (2023-2024) had zero options
coverage and sparse inst_delta_z. The ranker concept is not falsified; it is
currently untestable on the available historical data. Readiness gate at
`output/ranker/ranker_data_readiness.json` tracks when training becomes viable.

### Operating Thesis

> DEM is a proven selector, not a ranker. Selection generates +95% excess.
> Within-top-30 ordering does not predict (IC ≈ 0). EW Top-30 is correct
> until a dedicated second-stage ranker proves it can improve on equal weight.
> Fixed sleeve budgets are retired. Bucket labels survive as metadata only.
> The selector's edge is regime-dependent, strongest in bear biotech.

---

## 12. Key Files

| File | Purpose |
|------|---------|
| `decision_engine.py` | DEM core — L0→L2→L4→L4b→L3 |
| `run_screen.py` | Production pipeline orchestrator |
| `tools/run_daily_production.py` | Daily cron pipeline (Steps 1-6) |
| `tools/live_shadow_portfolio.py` | Shadow portfolio construction + PnL |
| `tools/catalyst_resolution_tracker.py` | CRT core |
| `tools/crt_calibration.py` | CRT calibration rollup |
| `tools/fetch_aact_snapshot.py` | AACT trial warehouse ingest |
| `common/options_diagnostics.py` | Options surface data (Tastytrade) |
| `common/milestone_optionality.py` | Spec 041 milestone features |
| `common/dealforma_features.py` | Spec 046 deal comp features |
| `common/purple_book_features.py` | Spec 047 biologics competition |
| `common/options_quality.py` | Spec 045 options quality layer |
| `dashboard/app.py` | FastAPI backend |
| `frontend/dashboard/` | React frontend |
| `specs/SYSTEM_SPEC.md` | System invariants |
| `production_data/portfolio_policy.json` | Portfolio construction policy (v3) |
| `production_data/decision_rulesets/v1.12.0_cal_alpha_off_candidate.json` | Active ruleset |

---

## 13. Test Coverage

~230+ tests across the system:

| Suite | Tests | Focus |
|-------|-------|-------|
| test_decision_engine | 112+ | DEM layers, sort keys, eligibility |
| test_catalyst_resolution_tracker | 28 | CRT watchlist, classification, resolution |
| test_crt_calibration | 8 | Calibration rollup, governance triggers |
| test_crt_real_record_fixtures | 19 | Real resolution records |
| test_milestone_optionality | 19 | Spec 041 feature builder |
| test_price_action_watch | 25 | Alert classification, confidence |
| test_dealforma_features | 24 | Spec 046 deal comps |
| test_purple_book_features | 16 | Spec 047 biologics competition |
| test_aact_ingest | 28 | AACT normalization, linkage, deltas |
| test_news_feed | 24 | Spec 044 news schema |
| test_options_quality | 16 | Spec 045 quality layer |

---

*Document generated 2026-04-01. Active ruleset: 69a0c7f8 (v1.12.0).*
