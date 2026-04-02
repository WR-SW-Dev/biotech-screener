# GOSS — Gossamer Bio, Inc. | DEM Dossier

**Snapshot:** 2026-04-02 | **DE version:** v1.3.0 | **Ruleset:** `69a0c7f8` (v1.12.0)

---

## Executive Summary

| | |
|-|-|
| **Eligible** | **NO** — `deep_drawdown` (-90.9% vs gate -40%) |
| **Tier** | D (ineligible) |
| **Rank** | Unranked (composite 131/294, 45th pctile) |
| **Composite** | 0.0649 (z=+0.14) |
| **Top 3 drivers** | smart_money +48.7 / momentum -29.1 / financial -28.2 |

**Confidence:** HIGH (0.822) | No missing components | No missingness penalty | No source reliability degradation

**What blocked eligibility:** Drawdown gate. Stock at $0.34 is -90.9% from 52w high ($3.79). Gate threshold is -40%, hard floor is -75%. Both breached. No bypass available.

**What would change the verdict:** Price recovery to ~$0.95 clears the hard floor; ~$2.27 clears the main gate. Most likely path is a positive Phase 3 readout (NCT05934526, completed Nov 2025, data pending). The options surface (EXTREME IV, event premium, `MARKET_SEES_SOONER` flag) is consistent with a near-term binary catalyst the model's 243-day calendar doesn't capture.

---

## Identity

| Field | Value | Source |
|-------|-------|--------|
| Ticker | GOSS | `universe.json` |
| Company | Gossamer Bio, Inc. | `universe.json` |
| Archetype | drug_developer | M1 classification |
| Industry | Biotechnology | M1 |
| Stage | late | M2 (lead Phase 3) |
| Market cap bucket | micro | M1 (~$79M implied) |
| Therapeutic area | oncology | M4 indication mapping |
| Crowding | highly_crowded (z=+0.67) | M4 competitive intensity |

---

## Layer 0 — Eligibility Gates

*Source: `decision_engine.py` L0, fields prefixed `de_`*

| Gate | Value | Threshold | Result |
|------|-------|-----------|--------|
| Drawdown | **-90.9%** | -40% (hard), -75% (floor) | **FAIL** |
| Drawdown vs XBI | -86.4% | -25% relative | FAIL |
| Fundamental red flag | NO | — | PASS |
| Financials missing | NO | cash_total > 0 | PASS |

**Red flag inputs** (raw, from `fundamental_red_flag_inputs`):

| Metric | Value |
|--------|-------|
| Cash total | $136.9M |
| Burn TTM | $171.3M |
| Runway months | 9.6 |
| Survivability score | -2.0 |
| Tier-1 sponsors | 6 |
| Stage | late |

---

## Layer 2 — Overlays

*Source: `decision_engine.py` L2, risk flags and momentum*

| Signal | Value | Flag? |
|--------|-------|-------|
| Momentum state | **headwind** | — |
| Alpha (60d) | -0.833 | — |
| Beta (XBI, 60d) | 1.86 | **high_beta** |
| RSI (14d) | 43.1 | neutral |
| Volatility (60d) | 0.865 | — |
| Drawdown | -90.9% | **deep_drawdown** |
| Drawdown relative to XBI | -86.4% | **deep_drawdown_rel_xbi** |
| Runway bucket | short | — |
| Severity | sev2 | — |

*Alpha source missing: `beta_missing:insufficient_overlap`*

---

## Layer 4 — Tier Assignment

*Source: `decision_engine.py` L4, tier logic*

| Field | Value | Context |
|-------|-------|---------|
| Clinical optionality pct | 0.545 | 54th percentile among 157 drug developers |
| Has clinical optionality | YES | — |
| Catalyst days | 243 | Far (>180d) |
| Catalyst in window (120d) | NO | — |
| Catalyst strength | far | decay_w = 0.30 |
| **Tier (if eligible)** | Would be **B** | optionality >= 0.30, no actionable catalyst |

---

## Layer 3 — Sizing

*Source: `decision_engine.py` L3, position sizing*

| Field | Value |
|-------|-------|
| Size band | XS (ineligible) |
| Cost bucket | <=2000bps |
| Est cost (round-trip) | 1,398 bps |
| Cost multiplier | 0.70 |
| Cost haircut applied | YES |

---

## Module Scores (M1-M5)

*Source: `run_screen.py` modules 1-5, `composite_score` from M5*

| Module | Score | Pctile | Notes |
|--------|-------|--------|-------|
| Momentum (M1) | 7.25 | — | headwind |
| Catalyst (M3) | 45.35 | — | specific_days, 243d, far |
| Clinical (M4) | 35.84 | — | Phase 3 lead, 7 programs |
| Clinical v2 | 34.90 (z=-0.37) | — | Below average |
| Financial (M2) | 8.14 | — | sev2, short runway |
| Valuation | 90.00 | — | — |
| Smart money | **85.00** | **86th pctile** | elite_6 coinvest, 6 tier-1 |
| **Composite** | **0.0649** | 45th pctile | Rank 131/294 |

---

## Sort Key Contributions

*Source: `de_sort_contrib_*` fields. All zero — name is ineligible, sort is not computed.*

---

## Rank Context

| Dimension | Value |
|-----------|-------|
| Composite rank | 131 / 294 (45th percentile) |
| Among drug developers | ~mid-pack of 157 |
| Among Tier D (ineligible) | 1 of 54 |
| Eligible universe size | 186 names |
| Distance to -75% floor | needs +$0.61 (~+179%) |
| Distance to -40% gate | needs +$1.93 (~+568%) |
| Price to clear floor | ~$0.95 |
| Price to clear gate | ~$2.27 |

---

## Catalyst Detail

*Source: Module 3 catalyst detection, `catalyst_events_2026-04-02.json`*

### Raw fields

| Field | Value |
|-------|-------|
| Catalyst source | CTGOV_CALENDAR |
| Catalyst event type | CT_PRIMARY_COMPLETION |
| Catalyst family | CLINICAL |
| Is hard catalyst | NO |
| Catalyst days | 243 |
| Catalyst bucket | core (>180d) |
| Catalyst priority | 3 |
| M3 events detected | 0 near-term |
| Next earnings | 2026-05-14 |

### Derived

| Field | Value |
|-------|-------|
| Alpha cohort key | `late\|near_181_270\|nonpos` |
| Alpha cohort pct | 0.444 |
| Regulatory event | none |
| Has regulatory upcoming 180d | NO |

### Policy interpretation

**TS flag:** `MARKET_SEES_SOONER` — term_slope=-0.383 (front elevated) but catalyst_days=243 (>90d). Market may see a nearer event than the model detects. Completed Phase 3 (NCT05934526, Nov 2025) should have data available — likely the real near-term catalyst.

*Provenance: CTgov calendar, current-state. As-of 2026-04-02. PIT status: current-state (not date-gated). No degradation.*

---

## Clinical Development (M4)

*Source: Module 4, `cache/clinical/`, `trial_records.json`*

### Raw fields

| Field | Value |
|-------|-------|
| Lead program phase | 3.0 |
| Lead program readout days | 243 |
| Program count | 7 |
| Program diversification | 1.0 |
| Readout density (90d) | 0 |
| Late-stage readouts (180d) | 0 |
| Execution momentum | 0.0 |
| AACT execution score | — (not populated) |

### Derived quality scores

| Dimension | Score |
|-----------|-------|
| Binary quality composite | 0.673 |
| Clinical quality | 0.775 |
| Clinical quality composite | 0.892 |
| Clinical design quality | 0.780 |
| Clinical program depth | 1.0 |
| Endpoint strength | 0.95 |
| Readout curve score | 0.205 |
| Regulatory quality | 0.000 |

### Policy interpretation

| Field | Value |
|-------|-------|
| Clinical score z | -0.174 |
| Clinical alpha z | +0.508 |
| Clinical date confidence | 0.95 |
| Clinical days precision | DAY |
| Single asset risk | NO |
| Clinical coverage flag | YES |

*Provenance: trial_records.json (current-state, PIT safety-net filtered). As-of 2026-04-02. 13 trials linked.*

---

## Institutional Signal

*Source: 13F institutional pipeline, `institutional_summary.json`*

### Raw fields

| Field | Value |
|-------|-------|
| Tier-1 sponsors | 6 |
| Sponsor overlap | 6 |
| Net buying | buying |
| Max position % | 2.66% |
| Filing age (days) | 139 |
| inst_delta_net | 0 |
| inst_delta_new | 0 |
| inst_delta_exit | 0 |
| inst_delta_nonzero_pct | 2.72% |

### Derived signals

| Field | Value |
|-------|-------|
| Coinvest score (z) | +1.137 |
| Coinvest tag | **elite_6** |
| Coinvest conviction | 5.308 |
| inst_delta_z | 0.0 |
| Recency state | **stale** |

### Policy interpretation

6 tier-1 biotech specialists holding with net buying. Conviction is high (5.3, elite tag). Filing age is 139 days (stale) and inst_delta is flat — no recent position changes. The institutional signal reflects a legacy position, not fresh activity.

*Provenance: 13F filings (Q4 2025, filed ~Feb 2026). Quarterly-lagged by design. Next refresh ~May 15 (Q1 2026 filings).*

---

## Options Surface

*Source: Tastytrade API via `common/options_diagnostics.py`*

### Raw fields

| Field | Value |
|-------|-------|
| Has data | YES |
| Quote timestamp | 2026-04-02T13:19:26Z |
| Nearest expiry | 2026-04-17 |
| DTE | 15 |
| ATM IV | **213.6%** |
| Front IV | 293.4% |
| Back IV | 181.0% |
| Term slope | -0.383 |
| Put/call skew | -0.078 |
| RR 25d | — (missing) |
| Straddle price | $1.743 |
| ATM IV change (5d) | +0.550 |

### Derived signals

| Field | Value |
|-------|-------|
| IV regime | **EXTREME** |
| Event premium | YES |
| Liquidity state | liquid |
| Vol classification | **RICH** |
| Cheap vol score | 0.010 |
| IV ramp flag | **rising** |
| Post-event drift risk | **high** |
| Options quality composite | 0.600 |
| Surface signal quality | partial |

### OVF11 (Options Verdict Framework)

| Component | Score |
|-----------|-------|
| Event premium (ep) | 0.000 |
| Skew/RR (sr) | 0.500 |
| Skew trend (sk) | 0.000 |
| Divergence (dv) | 0.100 |
| Quality | 0.400 |
| Confidence | 0.224 |
| **OVF11 score** | **0.104** |
| Primary factor | SR (skew/reversal) |
| Monitor verdict | NONE |
| Trade bias | NO_ACTION |

### Policy interpretation

IV is extreme at 214%. Steep backwardation (front 293% vs back 181%) means the market prices near-term resolution risk. Straddle at $1.74 on a $0.34 stock implies >500% move to breakeven. OVF11 gives NO_ACTION (low confidence, no strong directional signal). Vol is rich, not cheap.

*Provenance: Tastytrade live quote 2026-04-02T13:19Z. Chain is liquid. RR 25d missing (insufficient strike coverage). Real-time.*

---

## Financials

*Source: EDGAR XBRL via `pit_financials.py`, `production_data/pit_financials/GOSS.json`*

### Raw fields (10-K, filed 2026-03-17, period ending 2025-12-31)

| Metric | Value | Form | Filed |
|--------|-------|------|-------|
| Cash | $37.7M | 10-K | 2026-03-17 |
| Revenue (TTM) | $48.5M | 10-K | 2026-03-17 |
| Operating expenses (TTM) | $219.2M | 10-K | 2026-03-17 |
| Net income (TTM) | -$170.4M | 10-K | 2026-03-17 |
| Operating cash flow (TTM) | -$171.3M | 10-K | 2026-03-17 |
| Shares outstanding | 233.7M | 10-K | 2026-03-17 |

### Derived

| Metric | Value |
|--------|-------|
| Cash total (incl. securities) | $136.9M |
| Implied market cap | ~$79M (at $0.34) |
| Burn rate (TTM) | ~$171M |
| Runway months | 9.6 |
| Runway bucket | short |

*CIK: 0001728117. Filing-date-gated (filed <= as_of_date). True PIT.*

---

## Price Action

*Source: `production_data/price_history.csv` (Morningstar/Yahoo)*

| Metric | Value |
|--------|-------|
| Current price | $0.34 |
| 52-week high | $3.79 |
| 52-week low | $0.32 |
| Drawdown from 52w high | -91.0% |

*Historical prices are immutable. True PIT.*

---

## Data Confidence

| Field | Value |
|-------|-------|
| Confidence overall | **0.822 (HIGH)** |
| Missing components | none |
| Missingness penalty | 0 |
| Source reliability action | none |
| Source reliability penalty | none |
| Clinical coverage flag | YES |

### Freshness by section

| Section | Source | As-of | PIT status | Degraded? |
|---------|--------|-------|------------|-----------|
| Financials | EDGAR 10-K | 2025-12-31 (filed 2026-03-17) | True PIT | NO |
| Clinical trials | CTgov trial_records | 2026-04-02 | Safety-net filtered | NO |
| Institutional | 13F Q4 2025 | ~2025-12-31 (filed ~Feb 2026) | Quarterly lag | **STALE** (139d) |
| Options | Tastytrade live | 2026-04-02T13:19Z | Real-time | NO |
| Catalyst | CTgov calendar | 2026-04-02 | Current-state | NO |
| Price | Morningstar | 2026-04-02 | True PIT | NO |

---

## Clinical Trials (13 via CTgov + AACT)

*Source: `trial_records.json`, AACT linkage via `sponsor_alias_map.json`*

### Active Phase 3

| NCT ID | Phase | Status | Indication | Drug | PCD |
|--------|-------|--------|-----------|------|-----|
| NCT05934526 | 3 | **COMPLETED** | PAH | Seralutinib (inhaled) | 2025-11-27 |
| NCT06274801 | 3 | Active, not recruiting | PAH | Seralutinib | 2026-12-01 |
| NCT07181382 | 3 | **SUSPENDED** | PH-ILD | Seralutinib | 2028-12-01 |

### Phase 2 / OLE

| NCT ID | Phase | Status | Indication | Drug | PCD |
|--------|-------|--------|-----------|------|-----|
| NCT04816604 | 2 | Active, not recruiting | PAH (OLE) | Seralutinib | 2027-12-01 |
| NCT04456998 | 2 | Completed | PAH | Seralutinib | 2022-10-17 |

### Discontinued

| NCT ID | Phase | Status | Indication | Drug |
|--------|-------|--------|-----------|------|
| NCT04556383 | 2 | Terminated | Ulcerative colitis | GB004 |
| NCT03683576 | 2 | Completed | Asthma | GB001 |
| NCT03956862 | 2 | Completed | CRS (nasal polyps) | GB001 |
| NCT05242146 | 1 | Terminated | — | — |
| NCT03860896 | 1 | Completed | — | — |

---

## Counterfactuals

**What blocked eligibility?**
Drawdown gate only. -90.9% vs -40% threshold (and -75% floor). No other gate failed. If drawdown were removed, GOSS would be Tier B, ranked somewhere in the mid-pack of eligible names (optionality 0.545, no near-term catalyst, strong smart money).

**What would change tier/rank materially?**

| Scenario | Effect |
|----------|--------|
| Price to $0.95 | Clears -75% floor. Still fails -40% gate. |
| Price to $2.27 | Clears -40% gate. Eligible. Tier B (optionality + no catalyst). |
| Phase 3 data positive | Likely gaps through gate levels. Tier A if market treats as near-term catalyst. |
| Phase 3 data negative | Stock approaches zero. Remains Tier D. |
| M3 detects near-term readout | If <120d, tier upgrades B → A (optionality 0.545 + actionable catalyst). |
| Financing/dilution | Increases shares, worsens financial score, no tier impact. |

---

*Pseudo-PIT v1 snapshot. DEM production output, not investment advice.*
