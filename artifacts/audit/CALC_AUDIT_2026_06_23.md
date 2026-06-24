# Biotech Model — Full Calculation Audit
**Date:** 2026-06-23  
**Ruleset:** 8887576e (v1.14.0)  
**Freeze status:** IN EFFECT (2026-06-20, INC-2026-06-20-AUTOPUSH)  
**Sort anchor:** selector_score  
**Files reviewed:** 11  
**Result:** 2 FAIL · 5 WARN · 8 PASS · 3 INFO

---

## FAIL — Critical (pre-freeze defects)

### FAIL-1: `module_2_financial_v2.py:545–546` — R&D burn overstated 4×

**Finding:** The production financial module (v2, active) always divides the R&D field by 3 to approximate monthly burn, hard-coding a quarterly reporting assumption. SEC financials are typically annual (10-K). When an annual R&D figure is supplied, the burn rate is overstated by 4× and cash runway is understated by a corresponding 4×.

```python
# line 545-546 — always assumes R&D is quarterly
monthly_rd = total_rd / Decimal("3")   # BUG: 3 if quarterly, 12 if annual

# v1 corrected this via:
ytd_months = get_ytd_months_from_date(as_of_date, fiscal_period)
monthly_rd = total_rd / Decimal(str(ytd_months))
```

**Impact:** `runway_score` systematically depressed for companies reporting annual R&D figures. Affects ranking order. v1 handled this correctly; regression introduced in v2 rewrite.

---

### FAIL-2: `module_2_financial_v2.py:524` — NetIncome fallback carries the same 4× quarterly assumption

**Finding:** When the R&D field is absent, v2 falls back to using net income as a burn proxy — but again hard-divides by 3. An annual net loss figure becomes a 3-month slice, overstating monthly burn by 4×. The two bugs compound: a company missing the R&D field gets penalized twice.

```python
# line 524 — NetIncome fallback
monthly_burn = abs(net_income) / Decimal("3")   # same quarterly assumption
```

**Impact:** Identical to FAIL-1 but applies to the fallback path. Affects all tickers where R&D is null but net income is available — common for development-stage biotechs.

---

## WARN

### WARN-1: `module_2_financial_v2.py` — Revenue component silently dropped

v1 computes a 4-component financial composite (Runway 45%, Dilution 25%, Liquidity 15%, Revenue 15%). The production v2 module has a 3-component composite only — revenue scoring was removed entirely.

```
# v1 (deprecated):  runway×0.45 + dilution×0.25 + liquidity×0.15 + revenue×0.15
# v2 (production):  runway×0.50 + dilution×0.30 + liquidity×0.20
#                   revenue_score = 0.0 always in production
```

No governance record of the revenue removal decision. Appears to be an unintentional omission during the v2 rewrite. Commercial-stage biotechs receive no revenue differentiation in the current production path.

---

### WARN-2: `module_2_financial.py:727` — Stale comment declares 50% runway weight; actual code uses 45%

Line 727 reads `# Cash Runway (50%)` but the composite at line 746 applies `0.45`. v1 is deprecated but the stale comment creates a 5pp misread for any historical-PIT replay referencing v1 behavior.

---

### WARN-3: `module_5_composite_v3.py` — Docstring weight declarations don't match `V3_ENHANCED_WEIGHTS` constants

```
# docstring claims:
Clinical 28%  Financial 25%  Catalyst 17%  PoS 15%  Momentum 10%  Valuation 5%

# V3_ENHANCED_WEIGHTS actual:
clinical=0.26  financial=0.24  catalyst=0.16  pos=0.14
momentum=0.09  valuation=0.05  short_interest=0.06

# Δ: short_interest 6pp term entirely absent from documented formula
```

Any Sharpe-contribution audit using the docstring as reference will be wrong.

---

### WARN-4: `module_3_scoring.py` — Deprecated import remains active dependency

`module_3_scoring.py` is marked `DEPRECATED` in its own header but is still imported by `module_3_catalyst.py`. Two proximity scoring functions coexist in the active path: exponential decay (scale=2.0) in v1 and Michaelis-Menten in v2. No immediate scoring impact if routing is correct, but creates a maintenance trap.

---

### WARN-5: `run_screen.py:5647` — Non-cohort names in `pairwise_minimal` mode receive `selector_score × 0.0001`

In `pairwise_minimal` mode (production ranker), tickers without a `ranker_v2_score` are assigned `final_score = selector_score × 0.0001`. Deliberate design to sort non-cohort below cohort, but the multiplier is not documented in the ruleset manifest or decision engine governance. Any `final_score` distribution analysis that doesn't account for this will see a bimodal artifact.

---

## Weight Verification — PASS

All weight sets verified to sum to exactly 1.000:

| Set | Components | Sum |
|---|---|---|
| A4 Selector block weights | clinical=0.00, catalyst=0.15, survivability=0.10, institutional=0.65, market_structure=0.10 | **1.000** ✓ |
| A4 Institutional signals | coinvest_score_z=1.00, inst_delta_z=0.00, coinvest_recency_state=0.00 | **1.000** ✓ |
| Ranker block weights | options=0.05, institutional=0.10, aact=0.50, catalyst_nuance=0.20, microstructure=0.15 | **1.000** ✓ |
| M2 v2 financial composite | runway=0.50, dilution=0.30, liquidity=0.20 | **1.000** ✓ |
| M5 v3 Enhanced | clinical=0.26, financial=0.24, catalyst=0.16, pos=0.14, momentum=0.09, si=0.06, val=0.05 | **1.000** ✓ |
| M5 v3 Default | clinical=0.40, financial=0.35, catalyst=0.25 | **1.000** ✓ |
| M5 v3 Baker-style | clinical=0.35, financial=0.22, pos=0.18, valuation=0.15, catalyst=0.07, momentum=0.02, si=0.01 | **1.000** ✓ |
| M5 v3 Partial | clinical=0.33, financial=0.28, catalyst=0.18, momentum=0.09, valuation=0.05, si=0.07 | **1.000** ✓ |

---

## Additional PASS items

- No `datetime.now()` or `date.today()` in production pipeline (PIT-safe)
- Ranker adjustment bounded ±15% of `selector_score`; z-clamp=2.0 (tighter than selector's 3.0)
- M5 v3: stage/size tilt clamped [0.55, 1.60]; SEV3=0.0 correctly zeroes composite
- `pos_engine.py`: `as_of_date` required; no PIT violations in engine itself
- `ees_v2_phase3_shadow_monitor.py`: Spearman IC chain PIT-safe; uses `pit_archives`; no `datetime.now()`
- `decision_engine.py`: drawdown_gate=-0.40, vol_high=1.20, beta_high=1.80; all thresholds validated in `__post_init__`
- Ruleset manifest 8887576e confirmed: `sort_anchor=selector_score`, `inst_delta_z_selector_weight=0.0`, `coinvest_score_z_selector_weight=1.0`
- Ranker activation gate: only fires when `catalyst_days ∈ [1, 120]`

---

## INFO

- **`pos_model_v2.py:957,1034`** — `datetime.now()` present (audit timestamp field), but this file is not imported in `run_screen.py`. No production PIT impact. Flag for cleanup on freeze lift.
- **`inst_delta_z`** zeroed in selector (2026-05-04, IC ALERT mean=-0.097) but remains active in ranker. Reinstatement in selector requires IC recovery evidence per operational-state.md.
- **Missing tickers** in M2 v1 wrapper receive `financial_score=0.0` (severity=sev2) rather than a neutral 50 penalty. v2 behavior differs. Low impact given v2 is production.

---

## Production Module Path

```
Universe
  → module_2_financial_v2          ← FAIL-1 / FAIL-2 live here
  → module_3_catalyst              ← WARN-4 (deprecated v1 import)
  → module_4_clinical
  → module_5_composite_with_defensive → module_5_composite_v3   ← WARN-3 docstring drift
  → selector_engine [A4_SELECTOR_CONFIG, sort_anchor=selector_score]
  → ranker_engine [pairwise_minimal / clinical_50 fallback]      ← WARN-5
  → decision_engine → final_score → snapshot

pos_engine / pos_model_v2  (NOT in production path — diagnostic only)
```

---

## Scope

**Covered:** Formula correctness, weight sums, PIT compliance, null handling, normalization, composite aggregation.  
**Not covered:** Data ingestion quality, 13F cache freshness, EES IC gate status, ranker_v2 model internals.

Fix authorization: each remediation step (design → script → test → commit → PR) requires separate explicit operator instruction.
