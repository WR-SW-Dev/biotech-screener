# Wake Robin DEM — Model Documentation

**Version:** 1.6.0 (ruleset `2a3e79eb`, v1.13.0)
**Last updated:** 2026-04-13
**Status:** Production — A4 selector + pairwise_minimal ranker (2-feature, ordinal-only) + EW Top-30

---

## 1. System Overview

Wake Robin is a systematic biotech screening and portfolio construction system.
It ranks ~294 biotech names by asymmetric event-driven upside potential, with
the goal of identifying names where clinical/regulatory catalysts create
favorable risk/reward ahead of binary outcomes.

### Architecture

```
Universe (M1) → Financial Health (M2) → Catalyst Events (M3) → Clinical Dev (M4)
→ Composite Scoring (M5) → Decision Engine (L0→L2→L4→L4b→L3)
→ Selector Engine (B6: coinvest 65% + inst_delta 35%)
→ Ranker Engine (pairwise_minimal: 2 features, ordinal-only, top-60 cohort)
→ Sort by final_score → EW Top-30 → Portfolio Construction
→ Shadow Portfolio → Performance Attribution → Governance Gates
```

### Two-Stage Scoring (Spec 050, adopted 2026-04-03; QA revalidated 2026-04-04)

The model uses a **selector/ranker split**: one score to choose the shortlist, a different
score to rank within it. This was validated on true PIT data (67 monthly periods, Jun 2020 —
Apr 2026) at +2.34pp/mo net-of-cost, t=2.57.

> **Production mental model (2026-04-04):**
> coinvest selects, inst_delta ranks, financial penalizes "safe but less catalytic"
> names, and clinical is a weak/conditional feature under review.

**Stage 1 — Selector (B6 bundle):** Institutional sponsorship determines which 30 names
belong in the book. 65% coinvest_score_z + 35% inst_delta_z. Clinical quality was
destructive as a selector (-0.53pp). The B6 bundle was revalidated under Checklist v2
(2026-04-04): bootstrap mean +2.42pp/mo, 95% CI [1.25%, 3.70%], LOSO ROBUST across
all dimensions. Neither component survives as a standalone incremental signal
(coinvest FM NW-t = −0.18, inst_delta NW-t = +1.73), but the bundle's diversification
benefit is real and statistically significant.

**Stage 2 — Ranker (pairwise_minimal, ordinal-only):** A 2-feature Bradley-Terry pairwise
model ranks within the selected top-60 cohort. Promoted 2026-04-05 after feature audit
confirmed the prior 5-feature model added noise. The ranker is **ordinal-only** — raw scores
are not calibrated (ECE = 0.129, verdict: POOR). Do not rank-weight or confidence-size.

Production model (`production_data/ranker_v2_model.json`):
- `coinvest_score_z` (weight +0.061): selects high-coinvest names within cohort
- `financial_score` (weight −0.053): penalizes financially safe names — those with less
  catalytic upside. Negative weight is correct and informative. Persists across all
  cohort widths, both bull and bear regimes. Note: `financial_score` in CSV is Module 5
  rank-normalized (stage×size cohort), not raw Module 2 output.

Dead features (confirmed noise, removed 2026-04-05):
- `inst_delta_z`, `catalyst_decay_w`, `binary_quality_score`, `clinical_score_v2_z`
  all added noise to the pairwise model despite individual FM significance.
  Walk-forward: 2-feature spread +2.95%, IC +0.143 (t=2.98) — beats 5-feature on all metrics.

**Construction:** Equal-weight Top-30. Rank-weighting is not justified (RW-EW = -0.09pp,
t=-0.95). Pairwise calibration confirms: ordinal ranking only, no sizing from scores.

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

### Sort Key (v1.13.0)

12-element tuple determining final rank order. The sort anchor is now `selector_score`
which uses `final_score` (selector + ranker adjustment) when the ranker is active.

```
(eligible, is_dev, tier_ord, catalyst_priority, catalyst_mode,
 catalyst_days, missing_count, -final_score,
 -sponsor_count, momentum_ord, anchor, ticker)
```

**Sort anchor:** `selector_score` → reads `final_score` (selector + ranker bounded adjustment)

**Selector:** A4 config in `run_screen.py` → `selector_engine.py` (`compute_selector_scores()`)

**Ranker:** clinical_50 config in `ranker_engine.py` → `compute_ranker_adjustments()`
- Activates for names with catalyst ≤ 120d in selector top-60
- Bounded at ±15% of selector_score
- Does NOT require options data (analyst rank model)

**Legacy sort signals:** Still computed but superseded by selector/ranker. The tier system
(A/B/C/D) is still emitted for backward compatibility but no longer drives ordering.

---

## 3. Signal Inventory

### Production Signals (Spec 050 + Checklist v2 revalidation 2026-04-04)

**Selector (B6 bundle) — validated under full Checklist v2:**

| Signal | Role | Weight | Checklist v2 Evidence |
|--------|------|--------|----------------------|
| **coinvest_score_z** | Selector (B6) | 65% | Standalone 3/5 gates (FM incr NW-t=−0.18 FAIL, FDR q=0.86 FAIL). Bundle is stronger than parts. |
| **inst_delta_z** | Selector (B6) | 35% | Standalone 2/5 gates (FM NW-t=+1.73 FAIL, LOSO unstable in core bucket). Essential as complement. |
| **B6 bundle** | Selector | 65/35 blend | Bootstrap +2.42pp/mo, CI [1.25%, 3.70%], LOSO ROBUST. **Bundle validated.** |

**Ranker (pairwise_minimal) — 2 features, ordinal-only (ECE=0.129):**

| Signal | Role | Weight | Walk-Forward | Interpretation |
|--------|------|--------|-------------|----------------|
| **coinvest_score_z** | Ranker (positive) | +0.061 | Spread +2.95%, IC +0.143 (t=2.98) | Selects high-coinvest names within top-60 |
| **financial_score** | Ranker (negative) | −0.053 | Same walk-forward | TRUE PENALTY — safe names have less catalytic upside |

**Overlay signals (not in selector/ranker weights):**

| Signal | Role | Checklist v2 | Status |
|--------|------|-------------|--------|
| **event_type_score** | Diagnostic/filter/sizer | **5/5 PASS** (FM incr NW-t=+2.34, FDR q=0.096) | Overlay only — does NOT improve B6 bundle |

### Shadow / Under Review

| Signal | Checklist v2 | Status |
|--------|-------------|--------|
| insider_exec_buy_value_90d | 1/5 (FRAGILE robustness, bootstrap CI includes 0) | Shadow only — downgraded |
| aact_execution_score | 1/5 (bear-unstable −1.86pp, bootstrap CI includes 0) | Shadow only — downgraded |
| clinical_score_v2_z (as ranker) | Negative within top-30, collider-amplified | Quarterly review — drop if drifts to zero |

### Rejected / Disabled Signals

| Signal | Reason | Status |
|--------|--------|--------|
| **clinical_score_v2_z as selector** | Δ=-0.68pp, negative IC, universally destructive (Spec 055) | REJECTED |
| **DEFAULT selector weights** | -0.53pp as selector | REJECTED (clinical 35%/catalyst 25% mix) |
| **clinical composites as ranker** | Negative across ALL robustness slices (Spec 055) | CLOSED |
| cal_alpha | Confirmed noise at all horizons | REMOVED in v1.12.0 |
| optionality as sort anchor | Underwater on PIT data | SUPERSEDED by B6 selector |
| coinvest_binary | Δ=+0.25pp, t=1.25 | WORTHLESS — count granularity matters |
| total_volume_z | IC=-0.10 on PIT-native data | DEAD |
| quality_tiebreaks (Specs 030/031) | Economically immaterial | Lane EXHAUSTED |
| rank-weighting (any signal) | RW-EW = -0.09pp, t=-0.95; pairwise ECE=0.129 | NOT JUSTIFIED |
| options-as-alpha (Spec 053) | 37 signals tested, ALL fail as selector/ranker | CLOSED |
| static execution features (Spec 054) | PCD overdue, update recency, pipeline velocity all noise | CLOSED |

---

## 4. Data Sources & Architecture

### Data Architecture Overview

```
                              EXTERNAL APIS
   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
   │  SEC EDGAR    │  │ClinicalTrials│  │  Tastytrade   │  │  Yahoo/MS    │
   │  (XBRL,13F,  │  │    .gov      │  │ Options API   │  │  Prices &    │
   │   8-K)        │  │  + AACT DB   │  │  (OAuth2)     │  │  Fundamentals│
   └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘
          │                 │                  │                  │
          ▼                 ▼                  ▼                  ▼
   ┌──────────────────────────────────────────────────────────────────────┐
   │                    DATA COLLECTION LAYER                             │
   │  sec_collector    trials_collector   options_diagnostics  yahoo_coll │
   │  sec_8k_catalyst  poll_ctgov_daily   options_history      warm_price │
   │  warm_13f_cache   fetch_aact_snap    massive_api          refresh_ms │
   │  build_pit_fin    fda_adcom_coll     event_quality        macro_coll │
   └──────────────────────────┬──────────────────────────────────────────┘
                              │
                              ▼
   ┌──────────────────────────────────────────────────────────────────────┐
   │                    PERSISTENCE LAYER                                 │
   │                                                                      │
   │  production_data/          cache/                data/                │
   │  ├── universe.json         ├── ctgov/            ├── snapshots/       │
   │  ├── market_data.json      ├── sec/              ├── snapshots_pit_v2/│
   │  ├── financial_records.json├── fda/              ├── pit_archives/    │
   │  ├── price_history.csv     ├── morningstar_data/ ├── aact/snapshots/  │
   │  ├── pit_financials/       ├── press/            ├── press_releases/  │
   │  ├── ipo_dates.json        ├── market_data/      ├── 13f_cache/       │
   │  ├── institutional_*.json  └── clinical/         ├── short_interest/  │
   │  ├── fda_designations.json                       └── condition_aliases│
   │  ├── regulatory_calendar*.json                                       │
   │  ├── purple_book.json                                                │
   │  ├── manager_registry.json                                           │
   │  └── adcom_outcomes.json                                             │
   └──────────────────────────┬──────────────────────────────────────────┘
                              │
                              ▼
   ┌──────────────────────────────────────────────────────────────────────┐
   │                    SCREENING PIPELINE (run_screen.py)                │
   │                                                                      │
   │  M1 Universe ─► M2 Financial ─► M3 Catalyst ─► M4 Clinical          │
   │       │              │               │              │                │
   │       ▼              ▼               ▼              ▼                │
   │                M5 Composite Scoring                                  │
   │                       │                                              │
   │                       ▼                                              │
   │          Decision Engine (L0→L2→L4→L4b→L3)                          │
   │                       │                                              │
   │                       ▼                                              │
   │              rankings.csv + metadata.json                            │
   └──────────────────────────┬──────────────────────────────────────────┘
                              │
                              ▼
   ┌──────────────────────────────────────────────────────────────────────┐
   │                    CONSUMPTION LAYER                                  │
   │                                                                      │
   │  Portfolio Construction    Benchmarking        Dashboard (React)     │
   │  Shadow Portfolio          CRT Calibration     Agent Fleet (22)      │
   │  Bioshort Hedge Report     Signal Research     Email Alerts          │
   │  Expression Overlay (062)  Data Explorer       Ops Digest            │
   └──────────────────────────────────────────────────────────────────────┘
```

### External API Sources

| Source | Data Provided | Auth | Refresh | Pipeline Entry |
|--------|--------------|------|---------|----------------|
| **SEC EDGAR** (data.sec.gov) | XBRL company facts, 13F-HR filings, 8-K filings | Public (rate-limited 10 req/s) | Daily (8-K, XBRL) / Quarterly (13F) | M2 financials, institutional signal |
| **ClinicalTrials.gov** | Trial registry (status, phases, dates, endpoints) | Public | Daily | M4 clinical development |
| **AACT** (ctti-clinicaltrials.org) | Bulk clinical trial mirror (578K trials) | Public (pipe files) | Daily | M4 enrichment, AACT delta features |
| **Tastytrade** | Options IV, Greeks, skew, term structure | OAuth2 (`TT_SECRET`, `TT_REFRESH`) | Daily (intraday capable) | Options diagnostics, EPD |
| **Massive** | Historical options chains, quotes | API key (`MASSIVE_API_KEY`) + S3 | Daily | Options history backfill |
| **Yahoo Finance** | Stock prices, balance sheets, income statements | Public (rate-limited) | Daily | Price history, market data |
| **Morningstar Direct** | Fundamental data, volatility, star ratings | JWT (`MD_AUTH_TOKEN`) | Daily | M2 enhancements, vol enrichment |
| **FRED** (St. Louis Fed) | VIX, TNX, IRX, fed rate, HYG, SPY | API key (`FRED_API_KEY`) | Daily | Regime classifier (7 feeds) |
| **OpenFDA** | Drug approvals, recalls, labels | Public | Weekly | Regulatory enrichment |
| **EMA** | European drug approvals (CHMP decisions) | Public | Monthly | Regulatory tracking |
| **xAI (Grok)** | LLM biotech news analysis, X Search | API key (`XAI_API_KEY`) | Ad-hoc | Event alerts, news triage |

### Production Data Files

Core inputs loaded by `run_screen.py` every run:

| File | Contents | Records | Refresh | Module |
|------|----------|---------|---------|--------|
| `production_data/universe.json` | Tracked biotech universe | 341 tickers | Manual (universe changes) | M1 |
| `production_data/price_history.csv` | Daily OHLCV prices | ~1,571 dates × 355 tickers | Daily | M2 (drawdown, beta, RSI), benchmarks |
| `production_data/market_data.json` | Market caps, volume, sector | 340 tickers | Daily | M1 filters, M2 sizing |
| `production_data/financial_records.json` | Balance sheet, income, cash flow | 340 tickers | Every 2-3 days | M2 (current-state fallback) |
| `production_data/pit_financials/{TICKER}.json` | EDGAR XBRL facts with filing dates | 339 tickers, all historical filings | Daily rebuild | M2 (PIT mode) |
| `production_data/ipo_dates.json` | First/last price dates per ticker | 355 tickers | From price_history.csv | PIT survivorship filter |
| `production_data/institutional_summary.json` | 13F holdings, delta signals | 29 managers, 58.2% coverage | Quarterly (~May 15 next) | inst_delta_z sort signal |
| `production_data/manager_registry.json` | Institutional manager metadata | ~100 managers | Quarterly | 13F processing |
| `production_data/fda_designations.json` | Fast Track, Breakthrough, Orphan, Priority | 207 entries, 84 tickers | Manual | M4 regulatory scoring |
| `production_data/regulatory_calendar_manual.json` | Hand-curated PDUFA/ADCOM dates | 20-50 events | Manual | M3 catalyst detection |
| `production_data/adcom_outcomes.json` | FDA advisory committee voting history | 100+ decisions | Ad-hoc | M4 adcom vote scoring |
| `production_data/purple_book.json` | Biologics competition/exclusivity | 2,013 products, 49 tickers | Manual | Commercial-stage context |
| `production_data/portfolio_policy.json` | Construction rules (v3) | — | Manual | Portfolio construction |
| `production_data/decision_rulesets/v1.12.0_*.json` | Active decision engine config | — | Governed promotion | Decision engine |

### Cache Layer

Date-stamped caches for PIT-safe historical reruns:

| Cache | Contents | Path Pattern | Refresh | Size |
|-------|----------|-------------|---------|------|
| CTgov trial records | PIT-filtered clinical trials | `cache/ctgov/trial_records_{date}.json` | Daily | ~15 MB each |
| SEC 8-K catalysts | Corporate event filings | `cache/sec/8k_catalysts_{date}*.json` | Daily | ~2 MB each |
| FDA ADCOM calendar | Advisory committee schedule | `cache/fda/adcom_calendar_{date}.json` | Monthly | ~1 MB |
| Morningstar data | Fundamentals, vol, ratings | `cache/morningstar_data/` | Daily | ~40 MB total |
| Clinical features | Pre-computed M4 features | `cache/clinical/clinical_features_{date}.json` | Daily | ~5 MB each |
| Press releases | Company PR text + classification | `cache/press/` | Daily | ~50 MB total |
| Market data | Price/volume warm cache | `cache/market_data/` | Daily | ~30 MB total |

### Supplementary Data Sources

| Source | Records | Tickers Linked | Path | Status |
|--------|---------|---------------|------|--------|
| AACT clinical trials | 578,527 trials | 21,752 (49 tickers) | `data/aact/snapshots/` | Live — daily ingest |
| Purple Book biologics | 2,013 products | 530 (49 tickers) | `production_data/purple_book.json` | Live |
| Herald press releases | 3,312 classified | 336 tickers | `data/press_releases/` | Live — daily collection |
| Short interest (FINRA) | 300+ tickers | 300+ | `data/short_interest.json` | Weekly |
| DealForma deal comps | — | — | Spec 046 ready | Awaiting CSV export |
| Conference programs | ASCO, AACR, etc. | — | `cache/conferences/` | Quarterly scrape |
| EU trial registries | EUCTR, CTIS, ISRCTN | — | `cache/ema/` | Monthly |

### PIT (Point-in-Time) Data Architecture

Historical backtests require data as-known-on each snapshot date. The PIT stack:

```
Current-state files          PIT-corrected path
─────────────────           ──────────────────
financial_records.json  ──►  pit_financials/{TICKER}.json (filed <= as_of_date)
universe.json           ──►  ipo_dates.json filter (first_price_date <= as_of_date)
trial_records.json      ──►  cache/ctgov/trial_records_{date}.json + posting filter
catalyst_events.json    ──►  CTgov fallback PIT safety net (posting_date <= as_of_date)
```

| PIT Component | Status | Notes |
|---------------|--------|-------|
| Survivorship filter (ipo_dates.json) | **Shipped** | 8,556 violations fixed |
| EDGAR PIT financials (filing-date gated) | **Shipped** | 339 tickers, all historical filings |
| CTgov PIT safety net | **Shipped** | Runtime filter on posting dates |
| Production data archiver | **Shipped** | SHA-256 manifests in `data/pit_archives/` |
| PIT v2 snapshot regeneration | **In progress** | 76 monthly dates via `regenerate_pit_v2_snapshots.py` |
| Catalyst look-ahead audit | Inconclusive | Retroactive generation makes this hard to clean |

### Data Refresh Pipeline

Daily production run (`tools/run_daily_production.py`, cron 5:30 PM ET):

```
Step 1: Archive production inputs (SHA-256 manifest)
Step 2: Refresh prices (Yahoo/Morningstar → price_history.csv)
Step 3: Refresh market data (→ market_data.json)
Step 4: Poll CTgov (→ cache/ctgov/trial_records_{date}.json)
Step 5: Run full screen (run_screen.py → data/snapshots/{date}/)
        ├── 5a-5d: Modules 1-4
        ├── 5e: Module 5 composite
        ├── 5f: Decision engine
        ├── 5g: Institutional momentum
        ├── 5h: Options diagnostics (Tastytrade)
        ├── 5i: Event premium decomposition
        ├── 5j: AACT delta pipeline
        ├── 5k: Construction overlays
        ├── 5l: Shadow portfolio
        ├── 5m: CRT pipeline
        └── 5o: Construction v2 shadow
Step 6: Gate validation (29 production checks)
Step 7: Agent fleet dispatch (ops → sentinel → qa → calibration)
```

### Data Quality Summary

| Dimension | Coverage | Notes |
|-----------|----------|-------|
| Tier/momentum/archetype | 100% | Core fields always populated |
| Catalyst fields | ~85% | Some names lack dated catalysts |
| Options (ATM IV) | 96% eligible | Liquidity (~42% liquid chains) is the real gate |
| RR 25d / implied move | ~39% | Gated by options chain liquidity |
| 13F institutional | 58.2% ticker coverage | Next refresh ~May 15 (Q1 2026 filings) |
| FDA designations | 58.3% top-60 | 207 entries, 84 tickers |
| PIT financials | 99.4% universe | 339/341 tickers with EDGAR facts |
| AACT trial linkage | 49 tickers | Expanding via NPI/company name matching |

### Environment Variables

| Variable | Service | Purpose |
|----------|---------|---------|
| `TT_SECRET`, `TT_REFRESH` | Tastytrade | Options surface data (OAuth2) |
| `MASSIVE_API_KEY`, `MASSIVE_S3_*` | Massive | Historical options chains |
| `MD_AUTH_TOKEN` | Morningstar Direct | Fundamentals, vol, ratings |
| `FRED_API_KEY` | FRED (St. Louis Fed) | Macro regime feeds (VIX, rates) |
| `XAI_API_KEY` | xAI (Grok) | News analysis, X Search |
| `SMTP_USER`, `SMTP_PASSWORD` | Email | Alert delivery |

---

## 5. Portfolio Construction

### Current Architecture (Spec 050, adopted 2026-04-03)

**Model:** B6 selector + pairwise_minimal ranker (ordinal-only)
**Construction:** Equal-weight Top-30
**Account:** $500,000 notional
**Rebalance:** Weekly (Friday)
**Cost budget:** 25 bps round-trip per turnover event

| Parameter | Value | Evidence |
|-----------|-------|----------|
| K (portfolio size) | **30** | K-sweep peak: +2.34pp net, t=2.60, stable K=25-35 |
| Weighting | **Equal-weight** | RW-EW = -0.09pp, t=-0.95 — do not rank-weight |
| Turnover | **~22%** monthly | Lower than old baseline (29%) |
| Rebalance buffer | 30 ranks | Existing, reduces churn |

**Sleeve budgets are RETIRED.** The fixed 55/25/10/10 allocation was the primary
construction damage mechanism (+153.6pp drag). Bucket labels survive as metadata only.

### Construction Diagnosis (2026-04-01, updated 2026-04-03)

**Original finding (2026-04-01):** The selection layer generates alpha but fixed sleeve
budgets destroy it. This remains true for the old optionality selector.

**Updated finding (2026-04-03):** The A4 institutional selector generates statistically
significant alpha on true PIT data, and EW Top-30 construction preserves it.

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

#### Operating Conclusion (updated 2026-04-04)

> The DEM uses a two-stage scoring architecture: **coinvest selects** (B6 bundle),
> **inst_delta ranks** (pairwise_minimal), **financial penalizes** safe-but-uncatalytic
> names, and the portfolio is held equal-weight. The B6 selector was revalidated
> under Checklist v2 (bootstrap +2.42pp/mo, CI [1.25%, 3.70%], LOSO ROBUST).
> The pairwise ranker is ordinal-only (ECE = 0.129) — no rank-weighting or sizing.

> The model is a **bear/neutral alpha engine**: strong in distress and consolidation
> (+3.37pp bear, +6.23pp neutral), with bounded underperformance in sharp biotech
> rallies (-0.37pp bull). This is structural — institutional sponsorship is a quality
> signal, and quality lags beta in risk-on environments.

> Fixed sleeve budgeting has been retired. Rank-weighting is not justified.
> The correct construction is EW Top-30.

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

### Operating Thesis (updated 2026-04-04)

> **coinvest selects, inst_delta ranks, financial penalizes "safe but less catalytic"
> names, and clinical is a weak/conditional feature under review.**
>
> B6 selector (coinvest 65% + inst_delta 35%) is validated under full Checklist v2:
> bootstrap +2.42pp/mo, 95% CI excludes zero, LOSO ROBUST. Neither component survives
> standalone, but the bundle's diversification benefit is real.
>
> Pairwise_minimal ranker is ordinal-only (ECE = 0.129). Within the top-30 cohort,
> inst_delta is the dominant positive signal, financial_score is a true negative penalty
> (safe names underperform), and coinvest washes out (its job is done at selection).
>
> EW Top-30 is the correct construction. Rank-weighting and confidence sizing are
> not justified — pairwise scores are not calibrated.
>
> The selector's edge is regime-dependent, strongest in bear biotech.
> Fixed sleeve budgets are retired. Bucket labels survive as metadata only.

---

## 12. Key Files

| File | Purpose |
|------|---------|
| `decision_engine.py` | DEM core — L0→L2→L4→L4b→L3 |
| `selector_engine.py` | B6 selector (5 blocks, coinvest+inst dominant) |
| `ranker_engine.py` | clinical_50 ranker (legacy bounded ±15%) |
| `ranker_v2_pairwise.py` | pairwise_minimal ranker (Bradley-Terry, 6 features) |
| `run_screen.py` | Production pipeline orchestrator |
| `tools/run_daily_production.py` | Daily cron pipeline (Steps 1-6) |
| `tools/live_shadow_portfolio.py` | Shadow portfolio construction + PnL |
| `tools/catalyst_resolution_tracker.py` | CRT core |
| `tools/crt_calibration.py` | CRT calibration rollup |
| `tools/fetch_aact_snapshot.py` | AACT trial warehouse ingest |
| `common/stats/` | Statistical QA package (FM, bootstrap, FDR, LOSO, calibration) |
| `common/options_diagnostics.py` | Options surface data (Tastytrade) |
| `dashboard/app.py` | FastAPI backend |
| `frontend/dashboard/` | React frontend |
| `specs/SYSTEM_SPEC.md` | System invariants |
| `production_data/portfolio_policy.json` | Portfolio construction policy (v3) |
| `production_data/ranker_v2_model.json` | Pairwise minimal model weights |
| `production_data/decision_rulesets/v1.13.0_a4_selector_ranker.json` | Active ruleset |
| `scripts/research/checklist_v2_rerun.py` | Promotion Checklist v2 battery runner |
| `scripts/research/pairwise_feature_audit.py` | Within-cohort feature diagnostic |

---

## 13. Statistical QA Layer (Spec 055, 2026-04-04)

### Promotion Checklist v2

Any signal promotion now requires passing all 5 gates:

1. **Signal card**: Coverage ≥40%, selector Δ > 0, ranker IC > 0
2. **Fama-MacBeth incremental**: NW-t ≥ 1.96 with controls (coinvest, inst, financial)
3. **Block bootstrap**: 95% CI on portfolio delta excludes zero (6-month blocks, n=10,000)
4. **BH FDR**: q-value < 0.10 within testing family
5. **LOSO robustness**: Worst-slice delta positive across year/regime/cap/catalyst/stage

### Checklist v2 Rerun Results (2026-04-04)

| Signal | G1 Card | G2 FM | G3 Boot | G4 FDR | G5 LOSO | Total | Verdict |
|--------|---------|-------|---------|--------|---------|-------|---------|
| coinvest_score_z | PASS | FAIL | PASS | FAIL | PASS | 3/5 | SHADOW |
| inst_delta_z | PASS | FAIL | PASS | FAIL | FAIL | 2/5 | NO_GO standalone |
| event_type_score | PASS | PASS | PASS | PASS | PASS | 5/5 | **PROMOTE (overlay)** |
| insider_exec_buy_value_90d | FAIL | PASS | FAIL | FAIL | FAIL | 1/5 | NO_GO |
| aact_execution_score | PASS | FAIL | FAIL | FAIL | FAIL | 1/5 | NO_GO |
| **B6 bundle** | — | — | **PASS** | — | **PASS** | — | **VALIDATED** |

### Pairwise Calibration Assessment

- Pairs evaluated: 33,093 (67 snapshots)
- Brier score: 0.2755
- ECE: 0.129 → **POOR — ordinal ranking only**
- Pairwise accuracy: 53.0%
- Platt-calibrated ECE: 0.013 (but raw scores are uncalibrated)

**Policy**: No rank-weighting, no confidence sizing. Pairwise scores determine ordering
only. Equal-weight construction is the correct response to ordinal-only ranking.

### Within-Cohort Feature Audit (2026-04-04)

| Feature | Within-Top-30 NW-t | Mechanism | Action |
|---------|-------------------|-----------|--------|
| financial_score | −3.41 | TRUE PENALTY — persists all cohorts, all regimes | Keep negative weight |
| inst_delta_z | +3.32 | Dominant positive discriminator | Keep, primary ranker signal |
| clinical_score_v2_z | −2.38 | COLLIDER + weak penalty — vanishes in high-coinvest stratum | Quarterly review |
| coinvest_score_z | +0.49 | Washes out (job done at selector) | Keep but low-impact |

**Key insight**: The selector and ranker learn different structure. Coinvest gets names
into the room; within the room, inst_delta discriminates and financial_score penalizes
the "safe but less catalytic" names. This is not a bug — it reflects real within-cohort
economics of biotech investing.

### Infrastructure

| Script | Purpose |
|--------|---------|
| `common/stats/` | 6 modules: cross_sectional, bootstrap, multiple_testing, calibration, robustness, survival |
| `scripts/research/checklist_v2_rerun.py` | Targeted battery: Queue A (signals), B (calibration), C (B6 bundle) |
| `scripts/research/pairwise_feature_audit.py` | 6 diagnostic tests for within-cohort feature behavior |
| `scripts/research/statistical_methods_upgrade.py` | Full Spec 055 battery (broad, all signals) |
| `scripts/research/herald_precision_study.py` | Spec 056 — first Checklist v2 pass (event_type_score) |

---

## 14. Test Coverage

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

*Document updated 2026-04-04. Active ruleset: dd1e608c (v1.13.0). QA baseline: Checklist v2 rerun.*
