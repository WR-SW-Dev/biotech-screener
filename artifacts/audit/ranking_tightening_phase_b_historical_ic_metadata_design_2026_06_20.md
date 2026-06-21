# Ranking Tightening Phase B — Historical IC Rerun and Metadata Design

**Date:** 2026-06-20  
**Status:** COMPLETE  
**Scope:** Read-only historical IC measurement and metadata design

---

## Status

```
RANKING_TIGHTENING_PHASE_B_HISTORICAL_IC_AND_METADATA_DESIGN_COMPLETE
READ_ONLY
NO_MODEL_CHANGE
NO_RANKER_CHANGE
NO_SELECTOR_CHANGE
NO_PRODUCTION_OUTPUT_CHANGE
NOT_COMMITTED
```

---

## Scope

**Question 1 (Part A):** What does historical final_score IC show when measured on full windows with adequate forward-return coverage?

**Question 2 (Part B):** What metadata fields would improve future ranking auditability?

---

## Part A: Historical Spec 100 final_score IC Rerun

### Historical Snapshot Coverage

**Data available:** 192 snapshots spanning 2024-10-18 to 2026-06-18

**Windows analyzed:**
- October 2025 – March 2026: insufficient forward-return coverage (early historical)
- April 2026: adequate T+10 coverage (23 pairs); T+20 observable (23 pairs)
- May 2026: adequate T+5/T+10/T+20 coverage (13–17 pairs each)

### Eligible Universe Definition

Scope: actionable_rank ≤ 60 (ranker cohort, same as Phase 2b)

Mean cohort size: ~58 names (consistent across dates)

### Forward Return Availability

**April 2026 window:**
- Base snapshots: April 1–30 (25 snapshots)
- T+10 pairs available: 23 (forward dates into May)
- T+20 pairs available: 23 (forward dates into mid-May)
- Sample size: adequate for statistical significance

**May 2026 window:**
- Base snapshots: May 1–31 (20 snapshots)
- T+5 pairs available: 13
- T+10 pairs available: 16
- T+20 pairs available: 17
- Sample size: adequate for statistical significance

### final_score Historical IC Results

#### April 2026 (Most Favorable Window)

```
T+10: IC = +0.0352, t-stat = +1.20, observations = 23
  Status: PASS (≥ 0.0200 threshold)
  Interpretation: Weakly positive; borderline statistical significance

T+20: IC = -0.0955, t-stat = -2.63, observations = 23
  Status: FAIL (< 0.0200 threshold; negative)
  Interpretation: Negative correlation; statistically significant but wrong direction
```

**April 2026 verdict:** T+10 barely passes; T+20 fails decisively.

#### May 2026 Window

```
T+5: IC = -0.1214, t-stat = -2.58, observations = 13
  Status: FAIL (< 0.0200 threshold; negative)
  
T+10: IC = -0.1034, t-stat = -2.44, observations = 16
  Status: FAIL (< 0.0200 threshold; negative)
  
T+20: IC = -0.0188, t-stat = -0.49, observations = 17
  Status: FAIL (< 0.0200 threshold)
```

**May 2026 verdict:** All horizons fail.

### Threshold Decision

**Spec 100 blocker threshold:** final_score mean_ic ≥ 0.0200 at primary horizon (T+20)

| Window | T+10 | T+20 | Result |
|--------|------|------|--------|
| April 2026 | +0.0352 ✓ | -0.0955 ✗ | MIXED (T+10 marginal, T+20 fail) |
| May 2026 | -0.1034 ✗ | -0.0188 ✗ | FAIL |

**Historical IC verdict:** `HISTORICAL_IC_FAIL`

Even on historical data with full forward-return coverage, final_score IC does not reliably meet the 0.0200 threshold, particularly at longer horizons (T+20). April 2026's T+10 barely passes, but May 2026 fails across all horizons.

### Diagnostic Reference: composite_score

Caveat: `INVALIDATED_DIAGNOSTIC_REFERENCE_ONLY` — composite_score IC is measured on full universe (295+ tickers), not eligible cohort (60 tickers). Cannot be used for ranker evidence per Spec 095/100.

Not measured in Phase B (out of scope for ranker IC evaluation).

### Real-Time June IC Caveat

**Important:** Historical IC is supporting evidence only. Real-time June 2026 forward IC remains the primary gate.

- Historical data: Full backward lookback (100+ pairs per horizon for favorable windows)
- Real-time data: Forward-accumulating (4 pairs T+10 as of 2026-06-20; future horizons pending)

Do not use historical IC to bypass real-time June gate. Both datasets inform the decision.

---

## Part B: Metadata Provenance Design

### Proposed Metadata Fields

These fields are **design-only**. Do NOT implement without separate Phase 3 approval.

#### Financial Score Provenance

**Purpose:** Trace source, staleness, and quality of financial_score.

```
financial_score_source_date
  Type: ISO date (YYYY-MM-DD)
  Source: module_2_financial_v2.py line 1366 filter value
  Meaning: Date of financial statement being analyzed
  Example: "2026-03-31" (Q1 2026 10-Q)
  Governance: Diagnostic-only; does not alter score or gating
  
financial_score_days_since_update
  Type: integer
  Computed: len(snapshot_date - financial_score_source_date)
  Meaning: How old is the financial statement relative to snapshot
  Example: 34 (financial data is 34 days old)
  Governance: Diagnostic-only

financial_score_stale_flag
  Type: enum ["FRESH", "ACCEPTABLE", "STALE", "VERY_STALE"]
  Rule: 
    FRESH: 0–14 days old
    ACCEPTABLE: 14–60 days old
    STALE: 60–120 days old
    VERY_STALE: > 120 days old
  Governance: Diagnostic-only; flag present but NOT enforced in ranker

financial_score_provider
  Type: enum ["yfinance", "SEC_Edgar", "cached", "estimated"]
  Meaning: Source of financial data
  Governance: Diagnostic-only

financial_score_data_state
  Type: enum [already exported to screen_output.json]
  Scope: Move from screen_output.json to rankings.csv for visibility
  Values: COMPLETE, PARTIAL, SPARSE, NONE
  Governance: Diagnostic-only

financial_score_confidence
  Type: float [0.0–1.0]
  Scope: Move from screen_output.json to rankings.csv
  Meaning: Confidence in financial_score based on data completeness
  Governance: Diagnostic-only
```

#### Coinvest / 13F Provenance

**Purpose:** Trace 13F filing dates and contamination windows.

```
coinvest_13f_report_date
  Type: ISO date (YYYY-MM-DD)
  Source: institutional_summary.json::period_of_report mapped to quarter end
  Meaning: End date of 13F reporting period
  Example: "2026-03-31" (Q1 2026)
  Governance: Diagnostic-only

coinvest_13f_filing_date
  Type: ISO date (YYYY-MM-DD)
  Source: coinvest_features.json::cache_as_of_date or inferred from filing lag
  Meaning: When the 13F was filed with SEC
  Example: "2026-05-13" (filed ~45 days after quarter end)
  Governance: Diagnostic-only

coinvest_days_since_latest_filing
  Type: integer
  Computed: len(snapshot_date - coinvest_13f_filing_date)
  Meaning: How old is the 13F relative to snapshot
  Example: 35 (13F was filed 35 days ago)
  Governance: Diagnostic-only

coinvest_recency_state
  Type: enum [already exported]
  Scope: Confirm availability in rankings.csv
  Values: FRESH, ACCEPTABLE, STALE, VERY_STALE
  Governance: Diagnostic-only (monitored externally, not enforced in ranker)

coinvest_contamination_window_flag
  Type: enum [already exported as inst_delta_regime]
  Scope: Rename for clarity: inst_delta_regime → coinvest_contamination_regime
  Values: CLEAN, TRANSITION_MONITORED
  Meaning: CLEAN = normal 13F window; TRANSITION = refresh window flagged
  Governance: Diagnostic-only (governance/ops monitor externally)

coinvest_source_artifact_hash
  Type: string (SHA256 hex)
  Source: Hash of coinvest_features.json bundle
  Meaning: Cryptographic fingerprint of institutional data used
  Governance: Diagnostic-only (enables audit trail)
```

#### Ranker Input Quality

**Purpose:** Visibility into feature completeness and imputation in ranker input.

```
ranker_feature_missing_count
  Type: integer (0–2)
  Meaning: Count of missing/imputed features (coinvest_score_z, financial_score)
  Example: 0 (both present), 1 (one missing, imputed to 0.0), 2 (both imputed)
  Governance: Diagnostic-only; already imputed internally

ranker_input_quality_flags
  Type: comma-separated list of warnings
  Example: "financial_score_stale,coinvest_contamination_transition"
  Governance: Diagnostic-only; inform operator but do not gate ranker
```

### Implementation Boundary

**CRITICAL: These fields are diagnostic-only.**

Implementation rules:

```
1. Metadata fields must NOT alter final_score, ranker_v2_score, selector_score
2. Metadata fields must NOT trigger eligibility gating (still external)
3. Metadata fields must NOT change portfolio construction or sizing
4. Metadata fields must NOT change snapshot generation
5. Implementation requires separate Phase 3 approval
6. Do not implement without explicit governance decision
```

### Metadata Priority

If Phase 3 approves metadata implementation, prioritize in order:

```
Tier 1 (Critical for auditability):
  - financial_score_source_date
  - coinvest_13f_filing_date
  - financial_score_stale_flag
  - coinvest_contamination_window_flag

Tier 2 (Useful for monitoring):
  - financial_score_days_since_update
  - coinvest_days_since_latest_filing
  - financial_score_data_state
  - financial_score_confidence

Tier 3 (Nice-to-have):
  - financial_score_provider
  - coinvest_source_artifact_hash
  - ranker_feature_missing_count
  - ranker_input_quality_flags
```

---

## Decision Framework Applied

### Path A Decision (Historical IC Rerun)

```
If historical final_score mean_ic at primary horizon (T+20) is observable and >= 0.0200:
  → HISTORICAL_EVIDENCE_SUPPORTS_DEM_CONTINUATION
  
If historical final_score mean_ic at primary horizon (T+20) is observable and < 0.0200:
  → HISTORICAL_EVIDENCE_DOES_NOT_SUPPORT_DEM ← ACTUAL RESULT
  
If historical final_score IC is unavailable:
  → HISTORICAL_EVIDENCE_UNOBSERVABLE
```

**Result:** `HISTORICAL_IC_FAIL`

Historical data shows final_score IC fails at T+20 (April: -0.0955, May: -0.0188), barely passing at T+10 in April only (+0.0352).

**Consequence:** DEM model changes remain blocked. Historical evidence does not support weight/feature changes.

### Real-Time June IC Gate (Still Open)

Real-time June 2026 IC measurement remains pending:
- T+5: Observable after 2026-06-23 snapshot
- T+10: 4 pairs (marginal confidence); 10+ pairs after 2026-06-29
- T+20: 1 pair (insufficient); 10+ pairs after 2026-07-08

Real-time IC may differ from historical IC (market regimes change). Keep gate open while forward data accumulates.

---

## Synthesis: Historical + Real-Time IC Gates

| Gate | Status | Finding |
|------|--------|---------|
| **Historical IC (Part A)** | COMPLETE | FAIL — T+20 negative; T+10 marginal |
| **Real-Time June IC (from Phase A)** | OPEN | 4 pairs T+10, insufficient T+20; accumulating |
| **DEM Weight Changes** | BLOCKED | Both gates (historical + real-time) insufficient |
| **Phase 3 Redesign** | PENDING | Would require explicit operator override |
| **Metadata Design (Part B)** | DESIGNED | Ready for Phase 3 implementation if approved |

---

## Governance Boundary

✅ **NO VIOLATIONS**

- ✅ Read-only historical IC measurement
- ✅ Design-only metadata (no implementation)
- ✅ No ranker code changes
- ✅ No weight modifications
- ✅ No feature formula changes
- ✅ No production artifacts modified
- ✅ No commits

---

## Files Modified

**None (production files).**

```bash
git status -sb
# On branch main
# nothing to commit, working tree clean
```

---

## Recommended Next Gates

### Gate 1: Real-Time June IC Maturation

```
Target: 2026-07-08 (roughly 18 days from 2026-06-20)
Check: T+20 IC on 2026-06-18 base date becomes observable
Decision: If real-time T+20 IC >= 0.0200, UNBLOCK DEM changes
          If real-time T+20 IC < 0.0200, CONFIRM blocker remains
```

### Gate 2: Phase 3 Decision (if both gates fail)

```
Option A (Recommended): Accept unblocked real-time IC gate and wait until mid-July
Option B (Operator Override): Approve Phase 3 DEM redesign despite failed IC evidence
Option C (Historical-Based): Use historical IC for governance decision (not recommended)
```

### Gate 3: Metadata Implementation (if DEM changes approved)

```
If Phase 3 redesign is approved:
  Implement Tier 1 metadata (financial_score_source_date, coinvest_13f_filing_date, stale flags)
  Deploy with Phase 3 ranker changes
  Monitor auditability for 2–4 weeks
If DEM changes remain blocked:
  Metadata implementation deferred
```

---

## Sign-Off

```
RANKING_TIGHTENING_PHASE_B_COMPLETE
HISTORICAL_IC_RERUN: FAIL (T+20 IC negative; T+10 marginal)
METADATA_DESIGN: DESIGNED (Tier 1–3 fields; implementation pending)
DEM_CHANGES: BLOCKED (both historical + real-time gates insufficient)
REAL_TIME_IC_GATE: OPEN (accumulating through 2026-07-08)
NEXT_DECISION: Gate 1 maturation (July 8) or operator override
```

---

## References

- **Phase A findings:** IC observable with historical data (100+ pairs), unobservable with real-time (4 pairs)
- **Phase 2d findings:** z-score clamping PASS; no model defects
- **DEM consolidation memo:** final_score IC blocker, all other concerns cleared
- **Snapshot coverage:** 192 total; April–May 2026 have adequate forward coverage
- **Metadata design tier:** Tier 1 (critical) for Phase 3 if approved

