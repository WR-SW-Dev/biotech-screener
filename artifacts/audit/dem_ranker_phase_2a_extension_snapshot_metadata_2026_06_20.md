# DEM Ranker Phase 2a-extension — Snapshot Metadata Check

**Date:** 2026-06-20  
**Status:** COMPLETE  
**Classification:** SNAPSHOT_METADATA_PARTIAL

---

## Status

```
DEM_RANKER_ROBUSTNESS_PHASE_2A_EXTENSION_SNAPSHOT_METADATA_CHECK_COMPLETE
READ_ONLY
NO_MODEL_CHANGE
NO_RANKER_CHANGE
NO_SELECTOR_CHANGE
NO_PRODUCTION_OUTPUT_CHANGE
NOT_COMMITTED
```

---

## Scope

**Question:** Can a produced snapshot prove which financial source date, filing date, or cache timestamp produced each ticker's financial_score?

**Answer:** **SNAPSHOT_METADATA_PARTIAL**

- ✅ `screen_output.json` contains data quality metadata (financial_data_state, confidence, inputs_used)
- ❌ `rankings.csv` (main ranker input) contains only financial_score, no provenance
- ❌ No source_date, filing_date, or statement_date fields present
- ❌ No staleness indicators (days_since_update, cache_timestamp, etc.)

---

## Artifacts Inspected

| Artifact | Location | Status |
|----------|----------|--------|
| rankings.csv | data/snapshots/2026-06-18/rankings.csv | ✅ Readable |
| screen_output.json | data/snapshots/2026-06-18/screen_output.json | ✅ Readable |
| decision_portfolio.csv | data/snapshots/2026-06-18/decision_portfolio.csv | ✅ Readable |
| portfolio_positions.csv | data/snapshots/2026-06-18/portfolio_positions.csv | ✅ Readable |

---

## financial_score Fields Present

### In rankings.csv

**Column 232: financial_score** (only field present)

```
Header: ticker, company_name, ..., financial_score, ...
Sample value: 45.23
```

**No other financial fields.** Rankings.csv is the primary ranker input file; it contains only the score value, no metadata.

### In screen_output.json

**Module 2 financial output includes 22 fields per ticker:**

```python
# Present:
financial_score                    # ✓ main output
financial_data_state               # ✓ enum: COMPLETE, PARTIAL, SPARSE, NONE
has_financial_data                 # ✓ boolean
confidence                         # ✓ float 0.0-1.0
inputs_used                        # ✓ dict of field sources
missing_fields                     # ✓ list of missing fields

# Financial metadata derived from data quality:
burn_source                        # ✓ enum: CFO, NetIncome_quarterly, etc.
financial_data_state               # ✓ (data quality, not source date)
schema_version                     # ✓ "v2.0"

# NOT present:
financial_source_date              # ❌
financial_filing_date              # ❌
statement_date                     # ❌
cache_timestamp                    # ❌
cache_age_days                     # ❌
financial_provider                 # ❌ (implied: input financial_records)
financial_stale_flag               # ❌
days_since_financial_update        # ❌
financial_fallback_used            # ❌
```

---

## financial_score Provenance Fields Present

### Metadata Available (Indirect)

✅ `financial_data_state`: enum field indicating data completeness

```python
"financial_data_state": "COMPLETE"  # or "PARTIAL", "SPARSE", "NONE"
```

✅ `confidence`: float 0.0-1.0 indicating confidence in financial_score

```python
"confidence": 0.85
```

✅ `inputs_used`: dict showing which financial fields were available

```python
"inputs_used": {
    "Cash": True,
    "NetIncome": True,
    "MarketableSecurities": False,
    ...
}
```

✅ `burn_source`: enum showing which cash-burn calculation was used

```python
"burn_source": "CFO"  # or "NetIncome_quarterly", "estimated", etc.
```

### Metadata Missing (Direct)

❌ **source_date** — When the financial data was published/filed
❌ **filing_date** — When financial statement was filed with SEC
❌ **statement_date** — When financial statement period ended
❌ **cache_timestamp** — When financial data was cached/refreshed
❌ **days_since_update** — How old the financial data is relative to as_of_date
❌ **provider** — Which source (yfinance, Morningstar, SEC, etc.)

---

## Snapshot-Level PIT Auditability

### rankings.csv (Primary Ranker Input)

**PIT Auditability: ZERO**

```
Column: financial_score (232)
Value: 45.23 (example)
Metadata: NONE

Cannot determine:
  - When financial statement was filed
  - How old financial data is
  - Whether data is from same quarter/period across tickers
  - Whether data source changed mid-snapshot
```

### screen_output.json (Archive/Diagnostic)

**PIT Auditability: PARTIAL (data quality only)**

```
financial_score: 45.23
financial_data_state: "COMPLETE"
confidence: 0.85
burn_source: "CFO"
inputs_used: {...}

Can determine:
  ✓ Whether financial data was complete or sparse
  ✓ Confidence in score (0.0-1.0)
  ✓ Which calculation method was used (CFO vs. NetIncome)
  ✓ Which inputs were available

Cannot determine:
  ❌ When financial statement was filed
  ❌ How old data is relative to as_of_date
  ❌ Whether stale data was used (>30 days old?)
```

### Ranker Input Chain

```
Module 2 output (with data_state, confidence, inputs_used)
  ↓
screen_output.json (PRESERVED)
  ↓
rankings.csv (ONLY financial_score exported)
  ↓
Ranker input (NO provenance metadata)
```

**Gap:** Data quality metadata in screen_output.json is **not exported to rankings.csv**, so ranker has zero visibility to staleness or data quality.

---

## Missing Metadata

### Critical (Would Enable Auditability)

```
financial_source_date      # When financial statement was filed
days_since_financial_update # How old is the data relative to snapshot date
financial_data_lag_days     # Indicator of staleness (> 60 days = warning?)
financial_provider          # Source: yfinance, SEC Edgar, Morningstar, etc.
```

### Useful (Would Improve Confidence)

```
financial_statement_period_end   # Q1 2026, H1 2025, FY2025, etc.
financial_statement_type         # "10-Q", "10-K", form type
financial_cached_at              # Timestamp when financial data was retrieved
financial_fallback_used          # True if live API used, False if cached
financial_confidence_by_field    # Per-field confidence (Cash=0.95, NetIncome=0.60)
```

---

## Current Risk Classification

### On the Ranker Input (rankings.csv)

```
PIT_UNCLEAR_METADATA_MISSING

- financial_score present ✓
- Provenance metadata: ABSENT ✗
- Data quality indicator: ABSENT ✗ (not in rankings.csv)
- Staleness flag: ABSENT ✗
- Source date: ABSENT ✗

Ranker cannot audit PIT safety from rankings.csv alone.
```

### On the Archive (screen_output.json)

```
PIT_IMPLICIT_PARTIAL

- financial_score present ✓
- Data quality metadata present (partial) ✓
  - financial_data_state: COMPLETE/PARTIAL/SPARSE/NONE
  - confidence: 0.0-1.0
  - inputs_used: dict of available fields
- Source date: ABSENT ✗
- Staleness indicator: ABSENT ✗

Diagnostics can infer data quality but not absolute freshness.
```

---

## Minimal Metadata Proposal

To enable future PIT auditability without changing ranker behavior, add these diagnostic-only fields to rankings.csv and screen_output.json:

### Tier 1 (Critical for PIT auditability)

```
financial_source_date
  Description: ISO date when financial statement was filed
  Type: string (YYYY-MM-DD)
  Example: "2026-03-15" (Q1 2026 10-Q filing date)
  
days_since_financial_update
  Description: Calendar days between snapshot date and financial_source_date
  Type: integer
  Example: 34 (financial data is 34 days old)
  
financial_data_lag_staleness_flag
  Description: "FRESH" (<14d), "ACCEPTABLE" (14-60d), "STALE" (60-120d), "VERY_STALE" (>120d)
  Type: string enum
  Example: "ACCEPTABLE"
```

### Tier 2 (Useful for diagnostics)

```
financial_statement_period_end
  Description: End date of financial statement period
  Type: string (YYYY-MM-DD) or string (e.g., "Q1_2026")
  Example: "2026-03-31" or "Q1_2026"
  
financial_provider
  Description: Data source (yfinance, Morningstar, SEC, cached, etc.)
  Type: string enum
  Example: "SEC_Edgar"
  
financial_cached_at
  Description: Timestamp when financial data was fetched/cached
  Type: string (ISO 8601)
  Example: "2026-06-18T14:35:22Z"
```

### Implementation

**Do NOT implement.** These are diagnostic-only, do NOT change ranker behavior or feature computation.

---

## Governance Boundary

✅ **NO VIOLATIONS**

- ✅ Read-only inspection of snapshots
- ✅ No Module 2 changes
- ✅ No ranker modifications
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

## Summary

| Aspect | Status | Detail |
|--------|--------|--------|
| **financial_score in rankings.csv?** | ✅ YES | Column 232 |
| **Provenance metadata in rankings.csv?** | ❌ NO | No source_date, filing_date |
| **Data quality metadata in screen_output.json?** | ✅ PARTIAL | financial_data_state, confidence, inputs_used |
| **Ranker can audit PIT from rankings.csv?** | ❌ NO | No metadata exported |
| **Snapshot is PIT-safe by design?** | ✅ YES | Module 2 enforces source_date <= as_of_date internally |
| **Snapshot auditability?** | ⚠️ PARTIAL | Archive (JSON) has data quality; ranker input (CSV) has none |

---

## Classification

```
SNAPSHOT_METADATA_PARTIAL

Data quality metadata IS present in screen_output.json (financial_data_state, confidence, inputs_used).
But PIT provenance metadata (source_date, filing_date, days_since_update) is MISSING from both 
rankings.csv and screen_output.json.

Result: PIT-safe by design, but not auditable from snapshot artifacts.
```

---

## References

- **Phase 2a findings:** Module 2 enforces PIT filtering (source_date <= as_of_date) but does not export source_date
- **Phase 2a-extension findings:** Snapshot exports financial_score but no provenance metadata
- **Ranker input:** rankings.csv contains only financial_score (column 232), no staleness indicators
- **Archive:** screen_output.json contains data quality metadata but no source dates
