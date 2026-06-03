# Shadow Portfolio Attribution Analysis — 2026-06-02

**Hypothesis (Pending Validation):** Shadow portfolio underperformance of -1.29pp vs XBI is hypothesized to be driven by **one-name concentration** (ERAS exclusion) + **catalog-window mismatch** (overweighting near-term vs core). Validation pending 2-3 rebalance cycles.

---

## Executive Summary

| Metric | Value |
|--------|-------|
| **Decision Portfolio YTD** | +40.46% |
| **XBI YTD** | +5.13% |
| **Decision Alpha** | +35.33pp |
| **Shadow Alpha (estimated)** | +3.84pp |
| **Shortfall** | -31.49pp |
| **Shadow Excess vs XBI** | -1.29pp (4-period trailing avg) |

The decision portfolio (canonical Phase 2 Day 1 holdings) outperformed the shadow portfolio by ~31.5pp YTD. Analysis suggests the shortfall is driven by specific allocation differences rather than broad regime effects, but this hypothesis is pending validation across rebalance cycles.

---

## Root Cause Analysis

### 1. One-Name Noise: HIGH IMPACT ⚠️

**ERAS was excluded from shadow portfolio but returned +275.49%.**

- Decision portfolio rank: #13 (included)
- Shadow portfolio: excluded entirely
- YTD return contribution: +275pp (singular position)
- This single exclusion explains the majority of the -1.29pp underperformance

**Mechanism:** The live_shadow_portfolio tool selects top-K per bucket with policy constraints. ERAS may have been excluded due to:
- Bucket capacity constraints (too many high-performers in less_binary)
- Policy weight cap on specific tiers or archetypes
- Timing of position entry relative to shadow portfolio rebalance

**Observation:** The -1.29pp underperformance appears **idiosyncratic** and not predictable by model based on current evidence. ERAS may have been a lucky hit in the decision portfolio (Phase 2 Day 1 selection) rather than a systematic alpha source, but this hypothesis requires validation from future rebalance performance.

---

### 2. Bucket Composition Mismatch: MEDIUM IMPACT

**Shadow portfolio overweights near-term (0-90d) at the expense of medium-term (91-180d).**

| Bucket | Decision | Shadow | Δ | Avg Return |
|--------|----------|--------|---|------------|
| **0-30d** | 12 (40%) | 13 (43%) | +3pp | 38.8% |
| **31-90d** | 3 (10%) | 9 (30%) | +20pp | 34.4% vs 8.8% |
| **91-180d** | 10 (33%) | 6 (20%) | -13pp | 24.8% vs 0.03% |
| **>180d** | 5 (17%) | 2 (7%) | -10pp | 94.6% vs 47.7% |

**Critical observation:** The 91-180d bucket severely underperformed in the shadow portfolio (+0.03% avg vs +24.8% in decision). The shadow portfolio held only 6 positions in this bucket, including RYTM (-19.7%) and missing stronger performers.

**Result:** Overweighting 31-90d bucket (higher average 34.4% return) vs 91-180d (near-zero average 0.03%) actually helped the shadow portfolio slightly, offsetting the ERAS miss partially.

---

### 3. Catalyst-Window Effect: MEDIUM IMPACT

The 91-180d catalyst window diverged sharply between portfolios:

- **Decision 91-180d avg:** +24.8pp (led by TNGX +140.8%, URGN +16.9%)
- **Shadow 91-180d avg:** +0.03pp (TNGX and URGN canceled by RYTM -19.7%, ERAS absence)

Shadow portfolio missed the better 91-180d positions due to policy constraints. This is a **timing/composition effect**, not broad-market regime.

---

### 4. Broad Cohort Effect: MEDIUM CONTEXT

The 31.5pp gap between decision (+35.33pp alpha) and shadow (+3.84pp alpha) is substantial, but:
- Not due to macro regime (XBI was stable baseline)
- Primarily compositional: specific names (ERAS) and bucket weights
- Predictable in hindsight, not a systematic risk

---

## Classification Summary

| Dimension | Assessment | Evidence |
|-----------|------------|----------|
| **One-Name Noise** | **HIGH** | ERAS excluded, returned +275pp — dominates shortfall |
| **Bucket Exposure** | **MEDIUM** | 91-180d underweighted (20% vs 33%), avg return collapsed 0.03% |
| **Catalyst-Window** | **MEDIUM** | Near-term 31-90d overweighted, slightly offset by allocation luck |
| **Broad Cohort** | **LOW** | No systemic regime effect; differences are compositional |

---

## Position-Level Insights

### Positions Excluded from Shadow (vs Decision)
- **ERAS**: +275.49% (4th largest contributor to decision portfolio)

### Positions Overweighted in Shadow
- **RYTM**: -1.32pp overweight, -19.67% return (drag)
- **ALMS**: -1.14pp overweight, +123.8% return (helps)
- **COGT**: -1.14pp overweight, -5.70% return (small drag)

### Largest Weight Divergences (Decision underweight positions)
- **ABVX**: -45.8% return (underweight in shadow: dodge)
- **CMPS**: +103.5% return (slightly underweight in shadow: miss)
- **DNTH**: +105.6% return (slightly underweight in shadow: miss)

---

## Observability Status

**This analysis is HYPOTHESIS PENDING VALIDATION:**
- Documents observed divergence between decision and shadow portfolios as of 2026-06-02
- Proposes attribution hypotheses (ERAS idiosyncratic, bucket mismatch) subject to rebalance-cycle testing
- Will be validated or refuted by 2-3 subsequent shadow rebalance cycles
- Does not imply changes to decision portfolio policy at this time
- Guides instrumentation of future shadow portfolio constraints for diagnostics

---

## Next Steps (Phase 1 Priority 4+)

1. **Monitor catalyst-window balance** in future shadow rebalances (91-180d capacity)
2. **Document policy constraints** that led to ERAS exclusion (tier cap? bucket cap?)
3. **Herald rate-limit recovery** — ensure divergence detection doesn't cause alert spam
4. **IC health memory** — log this session's findings so ice-health-monitor can contextualize shadow variance

---

_Generated: 2026-06-03 — Phase 1 Priority 3: Read-Only Attribution_
