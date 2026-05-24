---
name: financial-health
triggers:
  - financial scoring
  - runway
  - burn rate
  - dilution risk
  - liquidity scoring
  - short interest
  - cash burn
  - severity classification
  - financial health
  - Module 2
description: >
  10-step financial health scoring for Wake Robin biotech screener. Covers burn
  rate source priority hierarchy, cash runway computation and severity (SEV1-SEV3),
  burn acceleration analysis, dilution risk engine (forced-raise probability),
  liquidity assessment by market-cap tier, revenue scoring, short interest signal,
  composite financial score weights (v1/v2), and severity penalty application.
  All arithmetic must use Decimal. SEV3 (< 6 months runway) is a hard exclusion gate.
---

# Financial Health Scoring Skill

## Purpose

Score a biotech company's financial survivability to produce a normalized 0-100 financial health score. Encodes exact rules from Module 2 pipeline (v1 + v2), the Dilution Risk Engine, Liquidity Scoring, and Short Interest Engine.

## Preconditions

- All arithmetic MUST use `Decimal` (never `float`). Initialize from strings: `Decimal("500000000")`.
- All dates MUST be ISO 8601. Never call `datetime.now()`.
- PIT safety: only use data where `source_date <= as_of_date - 1`.
- Rounding: `ROUND_HALF_UP`. Scores to 2dp, rates to 4dp.

---

## Step 1: Determine Cash Burn Rate

Stop at the first available source:

| Priority | Source | Confidence |
|----------|--------|-----------|
| 1 | CFO quarterly (explicitly quarterly) | HIGH |
| 2 | CFO YTD (with quarter differencing) | HIGH |
| 3 | CFO annual (divide by months in period) | HIGH |
| 4 | Trailing 4Q average | HIGH |
| 5 | FCF quarterly/annual (same hierarchy) | HIGH |
| 6 | Net Income (if negative, divide by 3) | MEDIUM |
| 7 | R&D * 1.5 / months_in_period | LOW |

### YTD Period Detection (by filing month)

| Filing Month | Period | Months |
|-------------|--------|--------|
| Jan-Mar | Q1 | 3 |
| Apr-Jun | Q2 | 6 |
| Jul-Sep | Q3 | 9 |
| Oct-Dec | Q4/Annual | 12 |

---

## Step 2: Compute Cash Runway

```
runway_months = current_cash / abs(quarterly_burn) * 3
```

If burn rate is zero or positive: `runway_months = 1200` (effectively infinite).

### Runway Severity Classification

| Runway | Severity | Consequence |
|--------|----------|-------------|
| < 6 months | SEV3 | **Hard gate** — exclude from screening |
| 6-12 months | SEV2 | 50% penalty (soft gate) |
| 12-18 months | SEV1 | 10% penalty (caution) |
| >= 18 months | NONE | No penalty |

### Dual Severity Paths (v1.1, Spec 101 — RESOLVED)

Two distinct runway severity signals are co-computed:

1. **Truth-gate severity** (`runway_severity_score`): "Can they survive to the catalyst?" Used by financing truth gate.
2. **EV/sizing severity** (`ev_severity_score`): "What financing damage even if they do?" Used by EV stack.

**Derived field contracts (must hold for all non-null rows):**
```
dilution_haircut == 0.35 * ev_severity_score       (tolerance 1e-6)
size_multiplier == max(0.40, 1.0 - 0.60 * ev_severity_score)  (tolerance 1e-6)
```

`check_severity_formulas()` QA validation runs every snapshot.

### Runway Score

**V1 (tier-based):**

| Runway | Score |
|--------|-------|
| >= 24 months | 100.0 |
| 18-24 months | 90.0 |
| 12-18 months | 70.0 |
| 6-12 months | 40.0 |
| < 6 months | 10.0 |

**V2 (piecewise linear):** Breakpoints at 0→5, 6→40, 12→70, 18→90, 24+→100. Linear interpolation between.

---

## Step 3: Burn Acceleration Analysis (v2 only)

| Condition | Threshold | Action |
|----------|-----------|--------|
| Accelerating burn | QoQ >= +10% | Penalty up to 30% |
| Decelerating burn | QoQ <= -10% | Bonus up to +10% |
| Stable | -10% to +10% | No adjustment |

```
penalty_pct = min(0.30, avg_qoq_change / 100 * 0.5)
adjusted_runway_score = runway_score * (1.0 - penalty_pct)
```

---

## Step 4: Dilution Risk Scoring

### Cash-to-Market-Cap Sigmoid (v1)

```
sigmoid = 100 / (1 + exp(-15 * (cash_to_mcap - 0.15)))
```

Inflection point: 15% cash/mcap. Clamp exp input to [-50, 50].

### Runway-Based Penalty (v1, if runway < 12 months)

```
penalty_factor = clamp(0.5 + (runway_months / 24), 0.5, 1.0)
dilution_score = dilution_score * penalty_factor
```

### Dilution Risk Buckets (v2)

| Cash/Market Cap | Risk Level |
|----------------|-----------|
| >= 30% | LOW |
| 15-30% | MODERATE |
| 5-15% | HIGH |
| < 5% | SEVERE |

### Financing Pressure Score (v2, 0-100)

Average of: Runway component (>= 24m: 0, 12-24m: 30, 6-12m: 60, < 6m: 90) + Cash/Mcap component (> 30%: 10, 15-30%: 30, 5-15%: 60, <= 5%: 90) + Share Dilution component (if available; <= 5%: 10, 5-10%: 30, 10-20%: 50, > 20%: 80).

---

## Step 5: Dilution Risk Engine (Forced-Raise Probability)

Probability that a company must raise capital before its next catalyst.

### Cash Gap Calculation

```
monthly_burn = abs(quarterly_burn) / 3
months_to_catalyst = days_to_catalyst / 30.44
cash_needed = monthly_burn * months_to_catalyst
usable_capacity = (shelf_capacity + atm_remaining) * 0.70  # USABLE_CAPACITY_FACTOR
total_available = current_cash + usable_capacity
cash_gap = cash_needed - total_available
```

### Raise Feasibility

```
dilution_pct_mcap = cash_gap / market_cap
days_to_raise = cash_gap / (avg_daily_volume * share_price * 0.10)
cap_penalty = min(1.0, dilution_pct_mcap / 0.20)
volume_penalty = min(1.0, days_to_raise / 30)
raise_feasibility = clamp(1.0 - ((cap_penalty + volume_penalty) / 2), 0.0, 1.0)
```

### Risk Bucketing

| Condition | Bucket |
|----------|--------|
| cash_gap <= 0 | NO_RISK (0.0) |
| raise_feasibility > 0.70 | LOW_RISK (<= 0.40) |
| raise_feasibility 0.40-0.70 | MEDIUM_RISK |
| raise_feasibility <= 0.40 | HIGH_RISK |

---

## Step 6: Liquidity Assessment

### ADV Thresholds by Market Cap Tier

| Tier | Cap Range | ADV Threshold |
|------|-----------|--------------|
| MICRO | < $300M | $750K |
| SMALL | $300M - $2B | $2M |
| MID | $2B - $10B | $5M |
| LARGE | >= $10B | $10M |

### ADV Scoring (0-70 pts)

```
ratio = adv / (2 * tier_threshold)
adv_score = clamp(int(ratio * 70), 0, 70)
```

### Spread Scoring (0-30 pts)

<= 50 bps: 30. >= 400 bps: 0. Between: linear interpolation.

### Liquidity Hard Gates

| Gate | Threshold | Action |
|------|-----------|--------|
| ADV FAIL | < $100K/day | Hard exclusion |
| ADV WARN | $100K-500K | Warning flag |
| ADV PASS | >= $500K | Green light |

Risk flags: `FLAG_WIDE_SPREAD` (>= 400 bps), `FLAG_LOW_LIQUIDITY` (< tier threshold), `FLAG_PENNY_STOCK` (< $2.00 price, caps score at 10).

---

## Step 7: Revenue Scoring (v1)

Pre-revenue baseline: 50 pts.

| Component | Rule |
|----------|------|
| Presence Bonus | Revenue >= $10M: +40; else 0 |
| Scale Bonus | >= $1B: 40, $100M-1B: 30, $10M-100M: 15, < $10M: 0 |
| Coverage Penalty | < 0.25 coverage: -20; 0.25-0.5: -10; >= 0.5: 0 |

Maximum: 80 pts.

---

## Step 8: Short Interest Signal

### Squeeze Potential

| Level | SI % of Float | Days-to-Cover |
|-------|--------------|---------------|
| EXTREME | >= 40% | >= 10 |
| HIGH | >= 20% | >= 7 |
| MODERATE | >= 10% | >= 5 |
| LOW | < 10% | < 5 |

### Signal Components (base = 50)

| Component | Weight |
|----------|--------|
| Squeeze Potential | 40% |
| Trend (SI change) | 30% |
| Institutional Support | 20% |
| Days-to-Cover | 10% |

Direction: >= 60 = BULLISH, 40-60 = NEUTRAL, <= 40 = BEARISH.

Crowding Risk: >= 30% SI = HIGH, >= 15% = MEDIUM, < 15% = LOW.

---

## Step 9: Compute Composite Financial Score

### V1 Weights

| Component | Weight |
|----------|--------|
| Runway | 45% |
| Dilution | 25% |
| Liquidity | 15% |
| Revenue | 15% |

### V2 Weights

| Component | Weight |
|----------|--------|
| Runway | 50% |
| Dilution | 30% |
| Liquidity | 20% |

```
financial_score = clamp(sum(component_score * weight), 0, 100)
```

---

## Step 10: Apply Severity Penalties

| Severity | Multiplier |
|----------|-----------|
| NONE | 1.0 |
| SEV1 | 0.90 |
| SEV2 | 0.50 |
| SEV3 | 0.00 (excluded) |

---

## Composite Integration

| Weight Set | Financial Weight |
|-----------|-----------------|
| V3 Enhanced | 24% |
| V3 Default | 35% |
| V3 Partial | 28% |
| Baker-Style | 22% |

---

## Source Files

| Component | File |
|----------|------|
| Financial Scoring (v1) | `module_2_financial.py` |
| Financial Scoring (v2) | `module_2_financial_v2.py` |
| Dilution Risk Engine | `dilution_risk_engine.py` |
| Liquidity Scoring | `liquidity_scoring.py` |
| Short Interest Engine | `short_interest_engine.py` |
