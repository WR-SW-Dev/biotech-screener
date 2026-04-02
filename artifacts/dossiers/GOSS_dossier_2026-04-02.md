# GOSS — Gossamer Bio, Inc. | DEM Dossier

**Snapshot:** 2026-04-02 | **DE version:** v1.3.0 | **Ruleset:** `69a0c7f8` (v1.12.0)

---

## Identity

| Field | Value |
|-------|-------|
| Ticker | GOSS |
| Company | Gossamer Bio, Inc. |
| Archetype | drug_developer |
| Industry | Biotechnology |
| Stage | late |
| Market cap bucket | micro |
| Therapeutic area | oncology |
| Crowding | highly_crowded (z=+0.67) |

---

## DEM Verdict

| Field | Value |
|-------|-------|
| **Eligible** | **NO** |
| Ineligible reasons | `deep_drawdown` |
| Tier (dev) | D |
| Tier reason | ineligible |
| Actionable rank | — (unranked) |
| Target weight | — |
| Size band | XS |
| Composite rank (M5) | 131 / ~294 |
| Composite score | 0.0649 |
| Score z | +0.14 |

---

## Layer 0 — Eligibility Gates

| Gate | Value | Threshold | Result |
|------|-------|-----------|--------|
| Drawdown | **-90.9%** | -40% (hard), -75% (floor) | **FAIL** |
| Drawdown vs XBI | -86.4% | -25% | FAIL |
| Drawdown (XBI) | -4.5% | — | — |
| Fundamental red flag | NO | — | PASS |
| Financials missing | NO | cash_total > 0 | PASS |
| DD rel margin rescued | NO | — | — |

**Red flag inputs** (from `fundamental_red_flag_inputs`):

| Metric | Value |
|--------|-------|
| Cash total | $136.9M |
| Burn TTM | $171.3M |
| Runway months | 9.6 |
| Survivability score | -2.0 |
| Tier-1 sponsors | 6 |
| Stage | late |
| Has revenue | — |

---

## Layer 2 — Overlays

| Signal | Value |
|--------|-------|
| Momentum state | **headwind** |
| Alpha (60d) | -0.833 |
| Alpha source | — (missing: `beta_missing:insufficient_overlap`) |
| Beta (XBI, 60d) | 1.86 |
| RSI (14d) | 43.1 |
| Volatility (60d) | 0.865 |
| Risk flags | `high_beta` \| `deep_drawdown` \| `deep_drawdown_rel_xbi` |
| Runway bucket | short |
| Severity | sev2 |

---

## Layer 4 — Tier Assignment

| Field | Value |
|-------|-------|
| Clinical optionality pct | 0.545 (54th percentile) |
| Has clinical optionality | YES |
| Catalyst days | 243 |
| Catalyst in window (120d) | NO |
| Catalyst strength | far |
| Catalyst decay weight | 0.30 |
| **Tier (if eligible)** | Would be **B** (optionality >= 0.30, no actionable catalyst) |

---

## Layer 3 — Sizing

| Field | Value |
|-------|-------|
| Size band | XS |
| Size reasons | ineligible |
| Cost bucket | <=2000bps |
| Est cost (round-trip) | 1,398 bps |
| Cost multiplier | 0.70 |
| Cost haircut applied | YES |

---

## Module Scores (M1-M5)

| Module | Score | Notes |
|--------|-------|-------|
| Momentum (M1) | 7.25 | headwind |
| Catalyst (M3) | 45.35 | specific_days, 243d, far |
| Clinical (M4) | 35.84 | Phase 3 lead, 7 programs |
| Clinical v2 | 34.90 (z=-0.37) | Below average |
| Financial (M2) | 8.14 | sev2, short runway |
| Valuation | 90.00 | — |
| Smart money | **85.00** | elite_6 coinvest, 6 tier-1 |
| **Composite** | **0.0649** | Rank 131 |

**Top 3 drivers:** `smart_money_score:+48.7; momentum_score:-29.1; financial_score:-28.2`

---

## Sort Key Contributions

All zero — name is ineligible, sort contributions are not computed.

| Contributor | Value |
|-------------|-------|
| de_sort_total_adj | 0.000 |
| institutional (inst_delta_z) | 0.000 |
| clinical | 0.000 |
| catalyst_bonus | 0.000 |
| binary_quality | 0.000 |
| oncology_crowding | 0.000 |

---

## Catalyst Detail

| Field | Value |
|-------|-------|
| Catalyst source | CTGOV_CALENDAR |
| Catalyst event type | CT_PRIMARY_COMPLETION |
| Catalyst family | CLINICAL |
| Is hard catalyst | NO |
| Catalyst days | 243 |
| Catalyst bucket | core (>180d) |
| Catalyst priority | 3 |
| Alpha cohort key | `late\|near_181_270\|nonpos` |
| Alpha cohort pct | 0.444 |
| Regulatory event | — |
| Regulatory days | — |
| Has regulatory upcoming 180d | NO |
| Next earnings | 2026-05-14 |

**TS flag:** `MARKET_SEES_SOONER` — term_slope=-0.383 (front elevated) but catalyst_days=243 (model says >90d). Market may see a nearer event.

---

## Clinical Development (M4)

| Field | Value |
|-------|-------|
| Lead program phase | 3.0 |
| Lead program readout days | 243 |
| Program count | 7 |
| Program diversification | 1.0 |
| Readout curve score | 0.205 |
| Readout density (90d) | 0 |
| Late-stage readouts (180d) | 0 |
| Execution momentum | 0.0 |
| Design quality score | 0.40 |
| Endpoint strength score | 0.95 |
| Clinical score z | -0.174 |
| Clinical alpha z | +0.508 |
| Clinical date confidence | 0.95 |
| Clinical days precision | DAY |
| Single asset risk | NO |

**Quality scores:**

| Dimension | Score |
|-----------|-------|
| Binary quality composite | 0.673 |
| Clinical quality | 0.775 |
| Regulatory quality | 0.000 |
| Clinical quality composite | 0.892 |
| Clinical design quality | 0.780 |
| Clinical program depth | 1.0 |
| Endpoint strength | 0.95 |

---

## Institutional Signal

| Field | Value |
|-------|-------|
| Tier-1 sponsors | 6 |
| Sponsor overlap | 6 |
| Net buying | buying |
| Coinvest score (z) | +1.137 |
| Coinvest tag | **elite_6** |
| Coinvest conviction | 5.308 |
| Tier-1 conviction | 5.308 |
| Max position % | 2.66% |
| Filing age (days) | 139 |
| Recency state | **stale** |
| inst_delta_z | 0.0 |
| inst_delta_net | 0 |
| inst_delta_new | 0 |
| inst_delta_exit | 0 |
| inst_delta_nonzero_pct | 2.72% |

---

## Options Surface

| Field | Value |
|-------|-------|
| Has data | YES |
| Quote timestamp | 2026-04-02T13:19:26Z |
| Nearest expiry | 2026-04-17 |
| DTE | 15 |
| **ATM IV** | **213.6%** |
| Front IV | 293.4% |
| Back IV | 181.0% |
| Term slope | -0.383 |
| Put/call skew | -0.078 |
| RR 25d | — |
| **IV regime** | **EXTREME** |
| Event premium | YES |
| Liquidity state | liquid |
| Use for judgment | YES |
| Options quality composite | 0.600 |
| Vol classification | **RICH** |
| Cheap vol score | 0.010 |
| Straddle price | $1.743 |
| ATM IV change (5d) | +0.550 |
| IV ramp flag | **rising** |
| Post-event drift risk | **high** |
| Surface signal quality | partial |
| Implied event move | — |
| Crush-adjusted implied move | — |

**OVF11 (Options Verdict Framework):**

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
| Event window flag | NO |
| Catalyst class | clinical |

---

## Financials (PIT, 10-K filed 2026-03-17, period 2025-12-31)

| Metric | Value |
|--------|-------|
| Cash | $37.7M |
| Revenue (TTM) | $48.5M |
| Operating expenses (TTM) | $219.2M |
| Net income (TTM) | -$170.4M |
| Operating cash flow (TTM) | -$171.3M |
| Shares outstanding | 233.7M |
| CIK | 0001728117 |

**Derived (from red flag inputs):**

| Metric | Value |
|--------|-------|
| Cash total (incl. securities) | $136.9M |
| Burn TTM | $171.3M |
| Runway months | 9.6 |
| Survivability score | -2.0 |

---

## Price Action

| Metric | Value |
|--------|-------|
| Current price | $0.34 |
| 52-week high | $3.79 |
| 52-week low | $0.32 |
| Drawdown from 52w high | -91.0% |
| Returns source | morningstar |

---

## Data Confidence

| Field | Value |
|-------|-------|
| Confidence overall | 0.822 |
| Missing components | — (none) |
| Missingness penalty | 0 |
| Source reliability action | — |
| Source reliability penalty | — |
| Clinical coverage flag | YES |

---

## Clinical Trials (13 trials via CTgov + AACT)

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

---

## Interpretation

**Gate status:** Hard-gated by -91% drawdown (gate at -40%, floor at -75%). No pathway to eligibility without price recovery.

**What would change:** Stock recovery above ~$1.50 (drawdown improves to -60% range), most likely on positive Phase 3 data readout from completed NCT05934526.

**Notable signals:**
- Smart money is the strongest module score (85/100) — 6 tier-1 biotech specialists holding, elite coinvest tag
- Options surface confirms binary risk: EXTREME IV (214%), steep backwardation, event premium detected, rising IV ramp
- **TS flag warns:** market sees a nearer event than the 243-day catalyst the model detects — consistent with pending Phase 3 data from the completed trial
- Clinical quality is high (0.892 composite) with strong endpoint strength (0.95) — the trial is well-designed
- Financial distress is real: $137M cash vs $171M burn, ~9.6 months runway

**DEM is correct to gate this name.** A -91% drawdown with pending binary data and short runway is exactly what the eligibility gates are designed to filter from systematic allocation. The institutional signal (elite_6) and options surface (EXTREME, event premium) are informative for discretionary monitoring but do not override the systematic gate.

---

*Pseudo-PIT v1 snapshot. DEM production output, not investment advice.*
