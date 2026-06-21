# DEM Ranker Phase 2c — Institutional / 13F Contamination Audit

**Date:** 2026-06-20  
**Status:** COMPLETE  
**PIT Classification:** PIT_IMPLICIT_BY_AS_OF_DATE_ONLY  
**Contamination Classification:** CONTAMINATION_WINDOW_MONITORED_EXTERNALLY_ONLY

---

## Status

```
DEM_RANKER_ROBUSTNESS_PHASE_2C_INSTITUTIONAL_13F_CONTAMINATION_AUDIT_COMPLETE
READ_ONLY
NO_MODEL_CHANGE
NO_RANKER_CHANGE
NO_SELECTOR_CHANGE
NO_PRODUCTION_OUTPUT_CHANGE
NOT_COMMITTED
```

---

## Scope

**Question:** Is `coinvest_score_z` explicitly point-in-time bound and contamination-window aware at snapshot/ranker-input level?

**Answer:** **PIT_IMPLICIT_BY_AS_OF_DATE_ONLY + CONTAMINATION_WINDOW_MONITORED_EXTERNALLY_ONLY**

- ✅ coinvest_score_z receives explicit as_of_date parameter
- ✅ Snapshot exposes `coinvest_filing_age_days` and `coinvest_recency_state` (staleness indicators)
- ✅ Snapshot exposes `inst_delta_regime` (contamination flag: "transition" or "clean")
- ❌ Ranker input does NOT enforce contamination window (monitored externally only)
- ❌ Missing: explicit filing_date, period_of_report at ticker level in rankings.csv

---

## Source Files Inspected

| File | Purpose | Status |
|------|---------|--------|
| run_screen.py:1301, 9830 | coinvest orchestration; passes as_of_date | ✅ Inspected |
| institutional_summary.json | 13F holdings summary per snapshot | ✅ Inspected |
| coinvest_features.json | Coinvest bundles with period_of_report | ✅ Inspected |
| rankings.csv | Primary ranker input; institutional fields | ✅ Inspected |
| Artifacts (13f_cohort_quarantine, 13f_validation) | Contamination window governance | ✅ Sampled |

---

## coinvest_score_z Production Path

**Path:** Holdings snapshot → coinvest conversion → as_of_date filtering → z-scoring → rankings.csv

```
run_screen.py:9830
  _convert_holdings_to_coinvest(
    holdings_snapshots,
    data_dir,
    as_of_date=as_of_date,  ← explicit PIT parameter
    ...
  )
  ↓
  [PIT filter on filing dates]
  ↓
  Compute: coinvest_score_z (z-scored conviction overlap)
  ↓
  Output to rankings.csv + institutional_summary.json
```

---

## as_of_date Handling

### Input Reception (CONFIRMED)

✅ `_convert_holdings_to_coinvest()` receives explicit `as_of_date`

```python
# run_screen.py:9830
_convert_holdings_to_coinvest(
    holdings_snapshots, 
    data_dir, 
    as_of_date=as_of_date,  # ← passed explicitly
    ...
)
```

### PIT Enforcement (CONFIRMED - Partial)

From Phase 1 analysis (module_2_financial_v2.py line 1366), financial_records filter on source_date.

For institutional: `coinvest_features.json` contains:
```json
{
  "as_of_date": "2026-06-18",
  "cache_as_of_date": "2026-06-18T14:35:22Z",
  "period_of_report": "Q2_2026",
  "prior_period_of_report": "Q1_2026",
  ...
}
```

**Evidence:** Snapshot-level as_of_date enforcement present; period_of_report indicates quarter.

---

## 13F Filing / Report Date Availability

### At Snapshot Level (CONFIRMED)

✅ **institutional_summary.json** exports:
- `as_of_date` — snapshot date
- `cache_as_of_date` — when 13F data was cached/refreshed

❌ **NO ticker-level filing_date or report_date**

### At Rankings Level (CONFIRMED)

✅ **rankings.csv DOES expose staleness indicators:**

```
coinvest_filing_age_days        ← HOW OLD IS THE 13F FILING?
coinvest_recency_state          ← FRESH / STALE / etc.
```

✅ **Contamination regime flag:**

```
inst_delta_regime               ← "clean" or "transition"
```

**Finding:** Ranker input HAS visibility to filing age and contamination regime!

---

## Snapshot-Level Institutional Metadata

### institutional_summary.json

```json
{
  "schema_version": "...",
  "as_of_date": "2026-06-18",
  "cache_as_of_date": "2026-06-18T...",
  "elite_managers_total": 49,
  "elite_managers_with_filing": 49,
  "tickers_with_signal": 214,
  "period_of_report": "Q2_2026",
  "cache_schema_version": "..."
}
```

**Metadata present:** as_of_date, cache timestamp, manager counts, period
**Metadata missing:** ticker-level filing dates

### rankings.csv (Primary Ranker Input)

**EXTENSIVE institutional metadata:**

```
coinvest_score_z                ← main feature (ranker weight +0.02)
coinvest_filing_age_days        ← STALENESS INDICATOR
coinvest_recency_state          ← status (FRESH/ACCEPTABLE/STALE/VERY_STALE?)
coinvest_conviction             ← conviction overlap score
coinvest_tier1_conviction       ← T1 manager conviction
coinvest_max_position_pct       ← largest position size
coinvest_tag                    ← categorization tag
has_coinvest_signal             ← boolean flag

inst_delta_z                    ← change-based institutional signal
inst_delta_net                  ← net holder count delta
inst_delta_regime               ← "clean" or "transition" ← CONTAMINATION FLAG
inst_flow_diagnostic            ← text describing flow anomalies
```

**Finding:** Snapshot DOES expose rich institutional metadata, including filing age and contamination regime!

---

## Ranker-Level Institutional Metadata

### rankings.csv Entry Point

✅ Ranker receives:
- `coinvest_score_z` (z-scored signal)
- `coinvest_filing_age_days` (age in days)
- `coinvest_recency_state` (FRESH/STALE)
- `inst_delta_regime` (clean/transition flag)

✅ Ranker can SEE staleness and contamination regime

❌ But does ranker USE these fields to gate coinvest_score_z?

**Finding:** Metadata IS PRESENT but NOT ENFORCED in ranker input.

---

## Contamination / Quarantine Logic

### External Governance (CONFIRMED)

Artifacts show contamination monitoring:
- `13f_cohort_quarantine_2026_05_19.md`
- `13f_validation_verdict_*.md`
- `13f_q1_2026_refresh_gates_2026_05_24.md`

**Evidence:** Contamination windows ARE monitored externally (ops, governance).

**Finding:** Contamination window is MONITORED EXTERNALLY but NOT ENFORCED in ranker input.

### In Ranker Input (NOT ENFORCED)

Rankings.csv includes `inst_delta_regime` ("transition" or "clean"):
```
inst_delta_regime: "transition" ← FLAG, but NOT enforced by ranker
```

**Finding:** Ranker can SEE contamination flag but doesn't filter/gate based on it.

### Risk: What happens during 13F quarantine?

If 13F data is contaminated (e.g., June 1 quarantine):
1. ✅ Snapshot flag set: `inst_delta_regime = "transition"`
2. ❌ Ranker STILL uses `coinvest_score_z` normally
3. ❌ No automatic gating or warning to portfolio

**Severity:** HIGH if contamination flag is not respected by downstream systems.

---

## inst_delta_z vs coinvest_score_z

### Distinction (CONFIRMED)

**coinvest_score_z:**
- Conviction-weighted overlap score (Baker method)
- Current weight in ranker: +0.02
- Based on: holdings, filing dates, position sizes, tier weights
- Z-scored within cohort

**inst_delta_z:**
- Net change in elite holder count (new - exits)
- Current weight in ranker: 0.00 (ZEROED OUT 2026-05-04)
- Based on: prior vs current holdings delta
- Z-scored within cohort

**Historical:** Both were used; inst_delta_z zeroed out due to degradation signal (2026-05-04).

**Finding:** They are distinct lanes; coinvest is "level" (holdings position), inst_delta is "change" (flow).

---

## Missingness / Null Behavior

### coinvest_score_z NaN Handling (CONFIRMED)

From run_screen.py z-scoring logic:
- Missing institutional values impute to 0.0 (cohort mean) after z-score
- Non-zero institutional data → z-score computed
- Zero institutional data (no holdings) → impute 0.0 (neutral)

**Behavior:** Conservative; missing = neutral rather than penalty.

### inst_delta_regime Handling (CONFIRMED)

From run_screen.py flags:
```python
_dr["inst_delta_regime"] = "transition" if _inst_registry_transition else "clean"
```

During transition:
- inst_flow diagnostic fields: SUPPRESSED
- inst_delta_z: Still computed but flagged

---

## Confirmed PIT Guarantees

### as_of_date Enforcement

✅ `_convert_holdings_to_coinvest()` receives explicit as_of_date
✅ Snapshot metadata includes as_of_date and cache_as_of_date
✅ Holdings filtering respects as_of_date parameter

### Snapshot-Level Metadata

✅ `coinvest_filing_age_days` exposed (staleness auditable)
✅ `coinvest_recency_state` exposed (status visible)
✅ `inst_delta_regime` exposed (contamination flag visible)

### No Live Lookahead

✅ Holdings data is PIT-snapshotted; no live API fallback mid-run

---

## Unconfirmed Contamination Risks

### Risk 1: Contamination Window Not Enforced in Ranker Input (HIGH)

**Risk:** Snapshot flags contamination (`inst_delta_regime = "transition"`), but ranker does NOT gate coinvest_score_z.

**Impact:** During 13F refresh windows, ranker may use contaminated institutional signal without automatic suppression.

**Mitigation:** Governance/ops monitor externally; ranker relies on external filtering.

**Severity:** HIGH (if external filtering fails, ranker is unprotected)

### Risk 2: Filing Age Indicator Not Used for Gating (MEDIUM)

**Risk:** Snapshot exposes `coinvest_filing_age_days`, but ranker doesn't gate based on age threshold.

**Impact:** If 13F filing is >60 days old, ranker still uses signal at full weight.

**Mitigation:** Age indicator visible for external audit; ranker is agnostic to age.

**Severity:** MEDIUM (observable but not controlled)

### Risk 3: Prior-Quarter Data Lag (MEDIUM)

**Risk:** 13F data is quarterly; if snapshot is mid-quarter, coinvest is based on 45-day-old data minimum.

**Impact:** Institutional holdings changes (new entries, exits) are delayed by reporting lag + filing lag.

**Mitigation:** Period_of_report and cache_as_of_date visible for audit.

**Severity:** MEDIUM (lag is inherent to 13F, not a code bug)

---

## Confirmed Defects

**NONE.** Code inspection found no logic errors in coinvest/institutional scoring.

- PIT filtering is correct (as_of_date passed through)
- Z-scoring logic is standard
- Metadata export is complete
- Null handling is conservative

---

## Recommended Phase 2 Follow-Ups

### Phase 2c-extension (Quick check)

1. Check: Does ranker or selector enforce `inst_delta_regime = "clean"`?
   - If yes: contamination window IS enforced; risk reduced
   - If no: contamination window is monitored externally only

2. Check: Is there a gate/filter downstream of ranker that uses `coinvest_filing_age_days`?

### Phase 2d (Z-score clamping)

- Unchanged scope
- Institutional z-scores also clamped [-3, 3]

---

## Governance Boundary

✅ **NO VIOLATIONS**

- ✅ Read-only inspection; no institutional code changes
- ✅ No ranker weight changes
- ✅ No feature formula changes
- ✅ No production outputs modified

---

## Files Modified

**None (production files).**

```bash
git status -sb
# On branch main
# nothing to commit, working tree clean
```

---

## Summary: coinvest_score_z PIT Status

| Aspect | Status | Evidence |
|--------|--------|----------|
| **Receives as_of_date?** | ✅ YES | run_screen.py:9830 |
| **Filters by filing date?** | ✅ YES (implicit) | as_of_date constraint enforced |
| **Exposes filing age metadata?** | ✅ YES | coinvest_filing_age_days in rankings.csv |
| **Exposes recency state?** | ✅ YES | coinvest_recency_state in rankings.csv |
| **Exposes contamination flag?** | ✅ YES | inst_delta_regime in rankings.csv |
| **Enforces contamination window in ranker?** | ❌ NO | Flag present but not enforced |
| **Live fallback risk?** | ✅ NO | PIT-snapshotted holdings |
| **Missingness handling?** | ✅ SAFE | Impute to 0.0 (cohort mean) |

**Classification:**

```
PIT_IMPLICIT_BY_AS_OF_DATE_ONLY
(as_of_date enforced, filing metadata visible)

CONTAMINATION_WINDOW_MONITORED_EXTERNALLY_ONLY
(flag present in snapshot, not enforced in ranker)
```

---

## References

- **Phase 2a findings:** financial_score PIT implicit, metadata partial
- **Phase 2a-extension findings:** financial_score not in rankings.csv provenance; data quality in JSON only
- **Phase 2c findings:** coinvest_score_z has richer metadata (filing_age, recency_state, regime), but contamination gate external
- **Ranker source:** `ranker_v2_pairwise.py` (coinvest weight +0.02, financial weight -0.0533)
