# Institutional Signal Health & Outlier Audit

**Date:** 2026-06-20  
**Status:** COMPLETE  
**Classification:** INSTITUTIONAL_CONCENTRATION_GOVERNANCE_RISK (signal health currently good)

---

## Status

```
INSTITUTIONAL_SIGNAL_HEALTH_AND_OUTLIER_AUDIT_COMPLETE
READ_ONLY
NO_SELECTOR_CHANGE
NO_RANKER_CHANGE
NO_MODEL_CHANGE
NO_PRODUCTION_OUTPUT_CHANGE
NOT_COMMITTED
```

---

## Scope

Quantify whether institutional signal dependency creates concentration, stale-signal risk, or outlier-driven ranking across (1) selector cohort entry and (2) DEM within-cohort ranking via coinvest_score_z.

---

## Background

The Selector Boundary audit found cohort entry is 65% institutionally-weighted and the DEM ranker also uses coinvest_score_z. This audit quantifies the joint dependency.

---

## Artifacts Inspected

| Artifact | Purpose | Status |
|----------|---------|--------|
| data/snapshots/{06-01,06-08,06-15,06-18}/rankings.csv | Bucket + outlier + churn | ✅ |
| production_data/ranker_v2_model.json | Confirm ranker features | ✅ |
| Institutional columns (coinvest_*, inst_delta_*, selector_institutional_block) | Signal decomposition | ✅ |

---

## Institutional Exposure by Rank Bucket (2026-06-18)

```
bucket        n   inst_block_mean   coinvest_z_mean   filing_age_median
top10        10        0.8771            2.4009              4 days
top30        20        0.7292            1.4610              7 days
rank31-60    30        0.6316            0.8559              7 days
non-cohort  147        0.4160           -0.4808              7 days
```

Monotone gradient: institutional exposure rises cleanly with rank. coinvest_score_z tracks identically.

---

## Selector Institutional Block Analysis

**The institutional block is the SOLE rank discriminator.** Block means by bucket:

```
bucket        institutional   catalyst   survivability   market
top10            0.877          0.571        0.591         0.486
top30            0.729          0.577        0.619         0.467
rank31-60        0.632          0.532        0.593         0.513
non-cohort       0.416          0.486        0.600         0.501
```

Only the institutional block separates buckets. Catalyst, survivability, and market are **flat** across the entire universe — they carry weight (15/10/10%) but barely move names up or down.

**Spearman |correlation| of each block vs selector rank:**

```
institutional   0.979   ← near-perfect determinant of rank
catalyst        0.333
survivability   0.151
market          0.159
```

**Interpretation:** Despite institutional being weighted 65% (not 100%), the other three active blocks are near-constant cross-sectionally, so institutional signal effectively determines ~98% of rank discrimination. The 65% weight understates the real dominance.

---

## coinvest_score_z Analysis

coinvest_score_z (the live DEM feature) rises monotonically with rank (top10=2.40 → non-cohort=−0.48).

**Selector institutional_block vs coinvest_score_z correlation: 1.000.**

The selector's institutional block and the DEM ranker's coinvest_score_z are the **same signal**. There is no diversification between "what selects a name into the cohort" and "what ranks it within the cohort" — both are the same 13F holdings-conviction signal.

---

## Joint Institutional Dependency

A name's entire journey is governed by one signal family:

```
eligible  →  cohort entry (inst block, 0.979 rank corr)  →  within-cohort DEM rank (coinvest_score_z, 1.000 corr with inst block)  →  top-30
            └──────────────────── same 13F holdings signal throughout ────────────────────┘
```

The catalyst, survivability, and market blocks provide weight but not discrimination. The financial_score DEM feature (weight −0.0533) provides the only genuine non-institutional differentiation in the ranking — and Phase 2d showed financial_score never even reaches its z-score bounds.

**Net:** Institutional 13F holdings conviction is the dominant driver of selection AND ranking, end to end.

---

## Top-30 Institutional Concentration

- top-30 mean institutional block: 0.729 vs non-cohort 0.416 (+75%)
- top-30 mean coinvest_score_z: 1.461 vs non-cohort −0.481
- All 30 top-30 names have fresh institutional filings (recency=fresh, filing_age median 7 days, max 7)

**Verdict:** Top-30 membership is institutionally over-determined. A name reaches the top-30 primarily by having strong 13F holdings conviction, not by clinical/catalyst/financial differentiation.

---

## Rank-60 Boundary Institutional Exposure

From the Selector Boundary audit: the rank-60 cutoff sits in a near-tie band. Because institutional block is the sole discriminator, the boundary names differ almost entirely on small institutional-signal differences. Boundary churn = small institutional-conviction reshuffles among marginal names. Limited portfolio impact (bottom of cohort), but confirms institutional signal even governs the cohort margin.

---

## Filing Recency and Contamination Window Review

```
Full eligible universe (207 names):
  recency_state:  fresh=181, blank=26
  filing_age_days: min=2, median=7, max=9
  inst_delta_regime: transition=207 (ALL)

Top-30:
  recency: fresh=30 (ALL)
  regime:  transition=30 (ALL)
  filing_age: min=2, median=7, max=7
```

### Critical disambiguation: which institutional signal is "in transition"?

The universe-wide `inst_delta_regime = transition` flag applies to the **flow delta** signal (`inst_delta_z` — net holder change), **NOT** the holdings-level `coinvest_score_z`.

**Evidence:**
- `inst_delta_z` is the flow signal (e.g., DNTH inst_delta_z=2.06, inst_delta_net=5)
- `coinvest_score_z` is the holdings-conviction signal (the actual live DEM feature)
- Ranker features confirmed: `["coinvest_score_z", "financial_score"]` — **inst_delta_z is NOT a ranker feature** (it was zeroed 2026-05-04)
- The dominant signal (coinvest_score_z holdings) is **FRESH**: filing_age 2–9 days, all recency=fresh

**Conclusion:** The contamination/transition flag is on a **non-load-bearing sub-signal** (flow delta, already zeroed in the ranker). The load-bearing signal (coinvest holdings conviction) is currently fresh and uncontaminated. This is the expected Q1→Q2 2026 13F registry-transition guard, consistent with Phase 2c — not acute contamination of the dominant signal.

**This significantly de-escalates the staleness concern.** The dominant signal is fresh; only the zeroed flow sub-signal is flagged.

---

## Persistent Institutional Outliers

Top-5 coinvest_score_z is stable and fresh across all 4 snapshots:

```
2026-06-01: RVMD(3.39) COGT(3.00) IRON(2.62) GPCR(2.60) XENE(2.48)  — all fresh
2026-06-08: RVMD(3.40) COGT(3.00) IRON(2.61) GPCR(2.61) XENE(2.48)  — all fresh
2026-06-15: RVMD(3.40) COGT(3.00) IRON(2.61) GPCR(2.61) XENE(2.48)  — all fresh
2026-06-18: RVMD(3.37) COGT(2.98) IRON(2.60) GPCR(2.56) XENE(2.46)  — all fresh
```

### RVMD — the persistent +3.0 clamped outlier (full universe)

- coinvest_score_z ≈ 3.37–3.40 every snapshot → clamped to +3.0 in ranker z-scoring (Phase 2d)
- Fresh filing (age 7), recency=fresh
- Cross-reference: RVMD is a de-risked clinical leader (P3 OS readout hit 2026-04-13) — a genuine high-conviction institutional name. The outlier is **thesis-supported**, not a data artifact.

### COGT — quarterly-static institutional anchor

```
date        coinvest_z   conviction   tier1_conv   max_pos
2026-06-01    2.9991       40.5624      40.5624      15.3%
2026-06-08    2.9986       40.5624      40.5624      15.3%
2026-06-15    2.9986       40.5624      40.5624      15.3%
2026-06-18    2.9791       40.5624      40.5624      15.3%
```

Conviction, tier-1 conviction, and max position are **identical** across all four snapshots — because 13F holdings update only quarterly. coinvest_score_z barely moves between refreshes.

**This is the structural explanation for top-30 stability:** the dominant signal is anchored to quarterly-static 13F data. The top-30 is stable because its driving signal is essentially frozen between filing cycles — not because of cross-signal robustness.

---

## Names Requiring Review

**None requiring outlier review.** The persistent outliers (RVMD, COGT, IRON, GPCR, XENE) are:
- Supported by fresh filings (age 2–7 days)
- Backed by real, large tier-1 conviction positions (COGT: 40.56 conviction, 15.3% max position)
- Consistent with known clinical theses (RVMD P3 readout)

No stale-filing-driven outliers. No phantom conviction. No data-error signatures.

---

## Defects

**NONE.** No logic or data errors found.

- Institutional block computation is correct
- coinvest_score_z is fresh and well-formed
- Outliers are real and thesis-supported
- The transition flag correctly applies to the flow signal (which is appropriately zeroed)
- Quarterly-static behavior is the expected nature of 13F data

---

## Governance Risks

### Risk 1: Single-Signal Concentration / Single Point of Failure (HIGH)

The model's entire discrimination — eligibility survivors → cohort entry (0.979) → within-cohort rank (1.000 corr) → top-30 → portfolio — collapses to **one quarterly-updated data source** (13F holdings conviction). The other selector blocks and the financial_score feature provide weight but minimal discrimination.

**Implication:** If 13F data degrades (bad refresh, registry error, manager misattribution, coverage gap), the error propagates through the entire funnel with **no internal circuit breaker** — contamination is monitored externally only (Phase 2c). There is no cross-signal redundancy to catch a 13F fault.

**Severity:** HIGH (structural single-point-of-failure), though currently dormant because the signal is healthy.

### Risk 2: Top-30 Stability Is Anchored, Not Robust (MEDIUM)

Top-30 stability (observed in Phase A) is a consequence of quarterly-static 13F data, not cross-signal agreement. The stability is real but fragile in a specific way: it will hold steady between 13F refreshes and then **step-change at each quarterly refresh**. The next Q2→Q3 2026 13F refresh is a concentrated risk event where the whole top-30 could reshuffle at once.

**Severity:** MEDIUM (predictable, tied to filing calendar)

### Risk 3: Concentration Compounds the DEM IC Blocker (MEDIUM)

The DEM final_score IC failure (Phase B) is harder to fix precisely because the ranker's discriminating feature (coinvest_score_z) is the same signal that already selected the cohort. Within a cohort pre-filtered for high institutional conviction, coinvest_score_z has little residual discriminating power — which may partly explain the weak/negative IC. Re-ranking on the same axis that selected the names is close to circular.

**Severity:** MEDIUM (analytical insight for Phase 3 design, not a current defect)

---

## Classification

```
PRIMARY:   INSTITUTIONAL_CONCENTRATION_GOVERNANCE_RISK
SECONDARY: INSTITUTIONAL_CONCENTRATION_HIGH_BUT_EXPECTED (signal health currently good)

NOT:  INSTITUTIONAL_SIGNAL_DEFECT_FOUND     (no logic/data error)
NOT:  INSTITUTIONAL_SIGNAL_STALENESS_RISK    (dominant signal is fresh; transition flag is on zeroed flow sub-signal)
NOT:  INSTITUTIONAL_OUTLIER_REVIEW_REQUIRED  (outliers are real and thesis-supported)
```

**Why governance risk, not merely "expected":** The concentration is so total (0.979 selection + 1.000 ranking correlation, single quarterly data source, external-only contamination monitoring) that it constitutes a single-point-of-failure for the entire model, not just a design preference. Signal health is good *today*, but the structure has no internal redundancy.

---

## Answers to Required Questions

```
1. Top-30 institutional dependency?
   ~98% of rank discrimination. inst_block 0.979 Spearman vs rank; coinvest_z monotone.

2. High inst-selector + high coinvest_z names?
   RVMD, COGT, IRON, GPCR, XENE — and by construction nearly all top-30
   (selector inst_block ↔ coinvest_z correlation = 1.000).

3. Top-30 institutionally over-determined?
   YES. Institutional signal is the sole discriminator; other blocks/financial are flat.

4. Persistent outliers supported by fresh filings?
   YES. RVMD/COGT fresh (age 2-7), real tier-1 conviction, thesis-backed.

5. High-ranking names in stale/transition regimes?
   The 'transition' regime flags the FLOW signal (zeroed in ranker), not the holdings
   signal (which is fresh). Dominant signal is NOT stale.

6. Concentration explains stability or creates fragility?
   BOTH. Stability is real but anchored to quarterly-static 13F. Fragility = step-change
   at each quarterly refresh + single-point-of-failure if 13F degrades.

7. Defect, design characteristic, or governance risk?
   GOVERNANCE RISK (single-signal SPOF), built on a design characteristic
   (institutional-heavy weighting). No defect.
```

---

## Recommended Next Step

**Diagnosis only — no weight change.** The institutional-heavy design is deliberate and the signal is currently healthy. Recommendations:

1. **Feed this into the July 8 / Phase 3 decision.** Risk 3 (circularity: re-ranking on the selection axis) is a strong candidate explanation for the DEM IC failure. Phase 3 design should consider whether the ranker needs a feature *orthogonal* to the selection signal — not more institutional signal.

2. **Quarterly-refresh watch (design-only).** Flag the next 13F refresh (Q2→Q3 2026) as a concentrated top-30 reshuffle risk event. Diagnostic monitoring, not gating.

3. **Do NOT reduce institutional weight or add an internal contamination gate** based on this audit alone. Those are design decisions requiring IC evidence and operator approval. DEM is blocked pending July 8.

**Natural next audits in roadmap:** CATALYST_TIMING_AND_SOURCE_QUALITY_AUDIT and FINAL_SCORE_HANDOFF_AND_CUTOFF_AUDIT — both now more interesting given that catalyst/financial signals are confirmed near-flat discriminators.

---

## Governance Boundary

✅ **NO VIOLATIONS**

- ✅ Read-only inspection
- ✅ No selector/ranker/model/weight changes
- ✅ No gate or cutoff changes
- ✅ No production outputs modified
- ✅ No commits

---

## Files Modified

**None (production files).**

Pre-existing unrelated working-tree changes (NOT from this audit): `web/app.py`, `web/data_loader.py`, `web/routes/atlas.py`, `web/routes/network.py`, `data/regulatory/drugsfda.zip`. These predate this session and are unrelated to institutional/selector/ranker code.

This audit added only: `artifacts/audit/institutional_signal_health_outlier_audit_2026_06_20.md` (untracked).

---

## Summary

| Aspect | Finding | Verdict |
|--------|---------|---------|
| **Institutional rank determinism** | 0.979 Spearman (sole discriminator) | ⚠️ Total concentration |
| **Selector inst_block ↔ coinvest_z** | 1.000 correlation (same signal) | ⚠️ No diversification |
| **Top-30 dependency** | Over-determined by institutional | ⚠️ Single-axis |
| **Filing freshness (dominant signal)** | Fresh (age 2-9, all recency=fresh) | ✅ Healthy |
| **Transition flag** | On zeroed flow sub-signal, not holdings | ✅ Not load-bearing |
| **Persistent outliers** | RVMD/COGT real, thesis-backed | ✅ No review needed |
| **Top-30 stability source** | Quarterly-static 13F anchor | ⚠️ Step-change at refresh |
| **Defects** | None | ✅ |
| **DEM IC failure link** | Likely circularity (re-rank on selection axis) | 🔑 Phase 3 insight |

**Classification:** `INSTITUTIONAL_CONCENTRATION_GOVERNANCE_RISK` (signal health good today; structural single-point-of-failure)

---

## References

- **Selector Boundary audit:** institutional 65% weight; rank-60 near-tie band
- **Phase 2c:** 13F contamination monitored externally only
- **Phase 2d:** RVMD/COGT persistent clamped outlier
- **Phase B:** DEM final_score IC fails — possibly due to circularity surfaced here
- **Phase A:** Top-30 stability — now explained as quarterly-static institutional anchor
- **Ranker:** coinvest_score_z (+0.02), financial_score (−0.0533); inst_delta_z zeroed
