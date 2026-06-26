# EES v3 Promotion Simulator — Results Memo

**Date:** 2026-06-25  
**Status:** DIAGNOSTIC_ONLY  
**Governance:** FREEZE_ACTIVE | NO_PRODUCTION_WIRING | EES_V3_PROMOTION_NOT_AUTHORIZED  
**Lead hypothesis:** `VETO_CORE` — exclude EES v3 bottom quintile from ranker selections  
**Data:** 76 PIT monthly snapshots, 2020-01-31 → 2026-04-16  
**Script:** `scripts/research/ees_v3_promotion_simulator.py`  
**Raw output:** `artifacts/shadow/ees_v3_promotion_simulator_2026-06-25.json` (gitignored)

---

## Method

Simulated 9 policies (8 candidate + 1 base) under strict PIT using production price history.
Top-quintile = top 20% by score per snapshot. Horizons: 21d / 42d / 63d.
IC = per-date Spearman; t-stat = Newey-West HAC. Excess return = vs XBI.

---

## 63d Primary Results

| Policy | IC | t_NW | Mean Excess Ret | vs Base | N avg | Turnover |
|--------|----|------|-----------------|---------|-------|----------|
| base (ranker top-Q) | 0.0205 | 1.62 | 2.42% | — | 32.8 | 0.398 |
| **veto_core** | **0.0288** | **3.11** | **3.62%** | **+1.20pp** | 25.4 | 0.424 |
| hc_overlay | 0.0301 | **4.44** | **8.02%** | **+5.60pp** | 4.2 | 0.558 |
| independent_sleeve | 0.0262 | 2.06 | 2.53% | +0.11pp | 9.8 | 0.578 |
| veto_misprice | 0.0213 | 1.74 | 2.56% | +0.14pp | 30.8 | 0.420 |
| lh_sleeve | 0.0061 | 0.46 | 7.04% | +4.62pp | 108.1 | 0.230 |
| confirmation | 0.0216 | 2.25 | 1.75% | −0.67pp | 10.5 | 0.496 |
| blend_90_10 | 0.0073 | 0.52 | 0.90% | −1.52pp | 51.3 | 0.394 |
| blend_80_20 | 0.0074 | 0.53 | 0.94% | −1.48pp | 51.3 | 0.401 |

---

## Key Findings

### 1. EES v3 is a veto, not a boost

`veto_core` (drop EES v3 bottom-quintile from ranker top selections) is the dominant practical
policy. IC improves from 0.0205→0.0288, t-stat from 1.62→3.11. Crucially, this is **improving
in the late regime**: EARLY excess 2.58% → LATE excess 6.87% at 63d. Mild drawdown: worst
period −11.1%, max 5 consecutive negative months.

### 2. Confirmation, blends, and veto_misprice rejected

Confirmation (both signals must be top-Q) underperforms base by −0.67pp at 63d. Blends
(90/10, 80/20) are −1.5pp vs base. Root cause: blending z(final_score) — which has near-zero
IC — into z(hc_coverage) dilutes the higher-quality signal and anchors top-quintile selection
on the noisier predictor.

`veto_misprice` (drop misprice-only bottom quintile) adds only +0.14pp — the misprice
component alone is too coverage-sparse in early PIT periods to veto reliably.

### 3. hc_overlay is exceptional but operationally thin

IC 0.0301, t_NW 4.44, mean excess 8.02% at 63d. But only **4.2 names average**, worst
period −25.1%, max 6-period drawdown streak, and 100% priced_move coverage required.
This is a **conviction-tier label**, not a portfolio rule. Use to tag the highest-conviction
overlap names on current rankings; do not use as standalone allocation.

Era split: EARLY 9.66% / 0.769 hit-rate; LATE 4.48% / 0.500 hit-rate. Still positive
in both eras but more concentrated in early history.

### 4. LH sleeve is not ready

Mean excess 7.04% at 63d looks compelling, but the IC is −0.003 (not rank-predictive),
the LATE hit-rate drops to **0.444** (below 50%), and the selected universe is 108 names —
far too broad for the signal. The disagreement bucket was profitable historically but the
signal has regime-degraded. Requires current-era forward return accumulation before
any interpretation.

### 5. independent_sleeve needs more observation

IC 0.0262, t=2.06 at 63d, but worst drawdown is 9 consecutive negative periods and −33.8%
worst single period. LATE performance is actually improving (6.77% excess vs 1.17% EARLY),
so this is a watch item, not a reject. But the early-period drawdown risk is too high for
a standalone allocation.

---

## Era Concentration Summary (63d)

| Policy | EARLY excess | EARLY hit_rate | LATE excess | LATE hit_rate |
|--------|-------------|----------------|-------------|---------------|
| veto_core | 2.58% | 0.661 | **6.87%** | 0.500 |
| hc_overlay | 9.66% | 0.769 | 4.48% | 0.500 |
| independent_sleeve | 1.17% | 0.554 | **6.77%** | 0.611 |
| lh_sleeve | 8.18% | 0.750 | 3.50% | **0.444** |

`veto_core` and `independent_sleeve` are late-regime improving. `hc_overlay` and `lh_sleeve`
are early-regime concentrated — interpret with caution.

---

## Operator Decisions

```
LEAD_EES_V3_INTEGRATION_HYPOTHESIS = VETO_CORE
STATUS = DIAGNOSTIC_ONLY
FREEZE = ACTIVE
PRODUCTION_PROMOTION = NOT_AUTHORIZED
```

**Do not promote anything.** Next step: veto autopsy — classify why the ranker-high/EES-v3-low
(HL bucket) names fail. If failure modes are repeatable and biologically grounded, `veto_core`
credibility increases substantially as a future production gate.

---

## Scripts Delivered (2026-06-25)

| Script | Purpose |
|--------|---------|
| `scripts/research/ees_v3_shadow_variants.py` | Daily variant tracker — 5 variants, 3 horizons |
| `scripts/research/ees_v3_disagreement_ledger.py` | Snapshot ranker/EES v3 bucket analysis |
| `scripts/research/ees_v3_regime_analysis.py` | Batch PIT early/late IC decomposition |
| `scripts/research/ees_v3_promotion_simulator.py` | 9-policy PIT promotion simulator |

All scripts: `DIAGNOSTIC_ONLY | NO_PRODUCTION_CHANGES | FREEZE_ACTIVE`.
