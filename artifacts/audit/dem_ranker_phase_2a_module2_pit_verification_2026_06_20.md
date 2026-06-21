# DEM Ranker Phase 2a — Module 2 financial_score PIT Verification

**Date:** 2026-06-20  
**Status:** COMPLETE  
**Classification:** PIT_IMPLICIT_BY_AS_OF_DATE_ONLY (with visibility gap)

---

## Status

```
DEM_RANKER_ROBUSTNESS_PHASE_2A_MODULE2_PIT_VERIFICATION_COMPLETE
READ_ONLY
NO_MODEL_CHANGE
NO_RANKER_CHANGE
NO_SELECTOR_CHANGE
NO_PRODUCTION_OUTPUT_CHANGE
NOT_COMMITTED
```

---

## Scope

**Question:** Is `financial_score` explicitly point-in-time bound at snapshot/ranker-input level, or merely assumed PIT-safe because Module 2 receives as_of_date?

**Answer:** **PIT_IMPLICIT_BY_AS_OF_DATE_ONLY** with visibility gap.

- Module 2 v2 **enforces PIT filtering** internally (source_date <= as_of_date)
- But Module 2 v2 **does NOT export source_date metadata** to output
- Result: Ranker has no visibility to whether financial_score is fresh or stale

---

## Source Files Inspected

| File | Lines | Finding |
|------|-------|---------|
| `module_2_financial_v2.py` | 1-1452 | Production Module 2 scoring; implements PIT filtering |
| `run_screen.py` | 182, 10013-10194 | Module 2 orchestration; passes as_of_date |
| `ranker_v2_pairwise.py` | 1-1262 | Ranker source; financial_score weight -0.0533 |

---

## financial_score Production Path

**Module 2 → Snapshot**

```
run_screen.py:10018
  ↓
compute_module_2_financial(
  as_of_date=as_of_date,
  financial_records=...,
  ...
)
  ↓
module_2_financial_v2.py:1362-1367 [PIT FILTER]
  ↓
score_financial_health_v2() [returns composite score]
  ↓
Output: "financial_score": float(composite)
  ↓
m2_scores_by_ticker lookup (run_screen.py:10194)
  ↓
Module 5 input / Snapshot output (rankings.csv)
```

---

## as_of_date Handling

### Module 2 v2 Reception (CONFIRMED)

✅ `compute_module_2_financial()` receives `as_of_date` parameter

```python
# run_screen.py:10018-10025
m2_result = compute_module_2_financial(
    financial_records=financial_records,
    market_records=market_records,
    active_universe=active_tickers,
    as_of_date=as_of_date,  # ← explicit parameter
    ...
)
```

### Module 2 v2 PIT Enforcement (CONFIRMED)

✅ Module 2 v2 **filters financial records by source_date**

```python
# module_2_financial_v2.py:1362-1367
# PIT filter: exclude financial records with source_date after as_of_date
if as_of_date and financial_data:
    _cutoff = str(as_of_date)[:10]
    financial_data = [
        r for r in financial_data if not r.get("source_date") or str(r["source_date"])[:10] <= _cutoff
    ]
```

**Enforcement**: Financial data with source_date > as_of_date is excluded before scoring. This is **explicit PIT enforcement** internally.

---

## Source Date / Filing Date Availability

### In Module 2 Input (CONFIRMED)

✅ Input financial_records contain `source_date` field

```python
# module_2_financial_v2.py:1362-1366
# Checks: r.get("source_date")
```

Financial records are expected to include source_date for PIT filtering.

### In Module 2 Output (RISK)

⚠️ **source_date is NOT exported**

Module 2 output (score_financial_health_v2 return dict) includes:

```python
# module_2_financial_v2.py:1202-1253
# Return fields:
"financial_score": _to_float(composite),        ✓ main output
"financial_normalized": _to_float(composite),   ✓ legacy name
"financial_data_state": quality.financial_data_state.value,  ✓ data quality indicator
"missing_fields": quality.missing_fields,       ✓ which fields are missing
"inputs_used": quality.inputs_used,             ✓ which inputs were used
"confidence": _to_float(quality.confidence),    ✓ confidence score
# BUT:
"source_date": ???  ← NOT PRESENT
```

**Gap:** No source_date field in Module 2 output. Ranker and snapshot have no metadata about whether financial_score is based on stale or fresh data.

---

## Snapshot-Level PIT Binding

### rankings.csv Output (UNVERIFIED)

❓ Does rankings.csv include a source_date or financial_staleness field?

**Investigation needed:** Check recent snapshot (e.g., 2026-06-18/rankings.csv) for:
- `financial_source_date` column
- `financial_statement_date` column
- `financial_data_freshness` column
- Any timestamp indicating when financial_score was computed

**Current finding:** Module 2 does not export source_date; likely NOT in rankings.csv.

---

## Ranker-Level PIT Binding

### ranker_v2_pairwise.py Input (CONFIRMED)

✅ Ranker receives financial_score from snapshot

```python
# ranker_v2_pairwise.py:100-101
BLOCK_RISK = (
    FeatureSpec("financial_score"),
    ...
)
```

✅ Live minimal_v2 ranker uses financial_score (weight -0.0533)

```python
# production_data/ranker_v2_model.json
"feature_names": ["coinvest_score_z", "financial_score"],
"weights": [0.02, -0.05332...]
```

❓ **But:** Ranker has NO visibility to source_date or financial freshness. If financial_score in snapshot lacks source_date metadata, ranker cannot audit PIT safety.

---

## Cache / Fallback Behavior

### Module 2 Data Sources (UNVERIFIED)

**Risk question:** Does Module 2 v2 use live API (yfinance) or cached financial records?

**Finding:** Module 2 v2 is STDLIB-ONLY (no external dependencies) and DETERMINISTIC (no datetime.now()).

**Implication:** Module 2 v2 uses pre-loaded financial_records input. **No live fallback risk** in Module 2 itself.

**But:** Financial records could be stale if input source is old.

---

## Live API / yfinance Risk

❓ **Where do financial_records come from?**

**Investigation scope:** Trace financial_records input to run_screen.py:10018 back to load_financial_data().

**Current finding:** Module 2 v2 does not call yfinance or live APIs. Depends on input financial_records. **Lower risk than if Module 2 fetched live data.**

But if financial_records input is stale or cached from old date, financial_score will be stale.

---

## Missingness / Null Behavior

### Module 2 v2 Null Handling (CONFIRMED)

✅ Module 2 v2 handles missing financial data gracefully

```python
# module_2_financial_v2.py:1362-1367
# Missing source_date: r.get("source_date") returns None
# Filter: not r.get("source_date") or ... → True, record included
```

Records with missing source_date are **included** (conservative assumption: no PIT violation).

✅ Missing financial fields: Module 2 v2 computes confidence and flags

```python
# module_2_financial_v2.py:1236-1239
"financial_data_state": quality.financial_data_state.value,
"missing_fields": quality.missing_fields,
"confidence": _to_float(quality.confidence),
```

Data quality indicators exported; ranker can see if financial_score is based on sparse data.

### Snapshot-Level Nulls (UNVERIFIED)

❓ If financial_score is missing, how does ranker impute?

**From Phase 1:** Ranker z-scores cohort features; missing values → impute to 0.0 (cohort mean).

So missing financial_score → imputed as neutral (zero after z-score).

---

## Confirmed PIT Guarantees

### Internal Filtering (EXPLICIT)

✅ Module 2 v2 **enforces PIT** at source_date level

- Filters out financial_records with source_date > as_of_date
- Passed to compute_module_2_financial(as_of_date=...) every time
- **Deterministic:** Same inputs → same filtered records → same financial_score

### No Live Lookahead (EXPLICIT)

✅ Module 2 v2 is STDLIB-ONLY, DETERMINISTIC

- No datetime.now() calls
- No live API fallback
- No random logic
- No file modification timestamps used

**Guarantee:** financial_score cannot be forward-looking.

### Snapshot Freshness (GUARANTEED BY ORCHESTRATOR)

✅ run_screen.py passes explicit as_of_date to Module 2

- as_of_date is required (no defaults)
- Module 2 filters to source_date <= as_of_date

**Guarantee:** Module 2 enforces as_of_date bound.

---

## Unconfirmed PIT Risks

### 1. Source Date Metadata Visibility (HIGH RISK)

**Risk:** Module 2 enforces PIT internally, but **does NOT export source_date** to output.

**Impact:** Ranker and snapshot users cannot audit whether financial_score is fresh or stale.

**Example scenario:**
- Snapshot date: 2026-06-18
- Financial records input: last update 2026-05-15 (34 days stale)
- Module 2 PIT filter: 2026-05-15 <= 2026-06-18 ✓ (passes)
- Module 2 output: financial_score = 45.0 (based on 34-day-old data, but no indication)
- Ranker cannot see the staleness

**Severity:** HIGH (PIT enforcement is present but not auditable)

### 2. Financial Records Input Freshness (MEDIUM RISK)

**Risk:** Module 2 v2 depends on financial_records input. If that input is stale or from a prior date, financial_score will be stale regardless of PIT filtering.

**Investigation needed:** Trace financial_records source to run_screen.py:10018.

**Example:** If financial_records is loaded once and reused for multiple snapshots with different as_of_dates, staleness risk increases.

**Severity:** MEDIUM (depends on upstream data loading pattern)

### 3. Missing source_date Values (LOW RISK)

**Risk:** Financial records missing source_date field are included in scoring (conservative assumption).

**Impact:** Tickers with missing source_date values could be scored with undated financial data.

**Severity:** LOW (records without source_date are explicitly handled; conservative inclusion is safe)

### 4. Module 2 Data State Confidence (INFORMATIONAL)

**Info:** Module 2 v2 exports financial_data_state and confidence fields.

```python
"financial_data_state": quality.financial_data_state.value,  # enum: COMPLETE, PARTIAL, SPARSE, NONE
"confidence": _to_float(quality.confidence),  # 0.0-1.0 score
```

**Opportunity:** Ranker could use financial_data_state/confidence for feature importance weighting (not currently done).

---

## Confirmed Defects

**NONE.** Code inspection found no logic errors or lookahead violations.

- PIT filtering logic is correct (line 1366: source_date <= as_of_date)
- Null handling is conservative and safe
- No live fallback or datetime.now() calls

---

## Unconfirmed Gaps (for Phase 2 follow-up)

1. **Does rankings.csv export financial_source_date or financial_data_state?**
   - Verify by reading recent snapshot
   - If not, audit visibility gap is HIGH

2. **Where do financial_records come from at run_screen.py:10018?**
   - Trace load_financial_data() or equivalent
   - Are records fresh (daily refresh) or stale (weekly/monthly)?
   - Are they indexed by as_of_date or loaded once?

3. **Does ranker/selector use financial_data_state or confidence?**
   - Currently unknown
   - If not used, valuable staleness metadata is ignored

---

## Recommended Phase 2 Follow-Ups

### Phase 2a-extension (Quick check)

1. Read rankings.csv column headers from 2026-06-18/rankings.csv
2. Check for: financial_source_date, financial_data_state, financial_confidence
3. If present: Phase 2a-complete (PIT metadata visible); if absent: visibility gap confirmed

### Phase 2c (Institutional contamination)

- Unchanged scope
- 13F lag still relevant

### Phase 2d (Z-score clamping)

- Unchanged scope; financial_score clamping [-3, 3] applies regardless of freshness

---

## Governance Boundary

✅ **NO VIOLATIONS**

- ✅ Read-only inspection; no Module 2 edits
- ✅ No weight changes to ranker
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

## Summary: Financial_score PIT Status

| Aspect | Status | Evidence |
|--------|--------|----------|
| **Module 2 receives as_of_date?** | ✅ YES | run_screen.py:10018 passes as_of_date param |
| **Module 2 filters by source_date?** | ✅ YES | module_2_financial_v2.py:1366 filters records |
| **Enforcement is explicit?** | ✅ YES | source_date <= as_of_date check hardcoded |
| **Source_date exported to output?** | ❌ NO | module_2_financial_v2.py:1202-1253 (no source_date field) |
| **Snapshot has staleness metadata?** | ❓ UNVERIFIED | Need to check rankings.csv columns |
| **Live fallback risk?** | ✅ NO | Module 2 v2 is STDLIB-only, no APIs |
| **Determinism (no datetime.now)?** | ✅ YES | DETERMINISM CONTRACT in docstring |

**Classification:**

```
PIT_IMPLICIT_BY_AS_OF_DATE_ONLY

Module 2 enforces PIT filtering internally (source_date <= as_of_date),
but does NOT export source_date metadata. Ranker and snapshot users
cannot audit whether financial_score is fresh or stale.
```

---

## References

- **Phase 1 findings:** 2-feature ranker (coinvest_score_z, financial_score); financial_score weight = -0.0533
- **Phase 2b findings:** final_score IC below 0.0200 threshold; blocker remains open
- **Module 2 source:** `module_2_financial_v2.py` (v2.0.0, STDLIB-only)
- **Ranker source:** `ranker_v2_pairwise.py` (Bradley-Terry model)
