# Shadow Metric Safeguards — Data Integrity Protection

**Status:** Implemented 2026-06-16  
**Impact:** Prevents stale/incomplete metrics from blocking trading gates  
**Test Coverage:** 5 unit tests in `test_shadow_metric_integrity.py`

---

## Problem Statement

**Historical Issue (2026-06-15):**
- Scorecard blocked trading on `shadow_excess_vs_xbi = -2.2315pp` (FAIL at -2.0pp)
- Root cause: Metric included 2026-05-20 with 30/30 missing prices → 0% return was data-loss artifact
- Impact: Incorrect trading gate based on incomplete metrics

**Root Cause:**
1. Performance metrics were replayed from historical CSV without data-quality validation
2. Periods with complete price data loss (n_missing_price > 0) were included in averages
3. No validation that recent data was complete before using metric for gating

---

## Solution: Multi-Layer Safeguards

### Layer 1: Metric-Level Filtering (check_shadow_excess)

**Code Location:** `tools/weekly_readiness_scorecard.py:check_shadow_excess()`

**What It Does:**
```python
# CRITICAL - Rows with complete price coverage (data integrity gate)
complete_data = [
    r for r in has_excess
    if int(r.get("n_missing_price", 0)) == 0
]
```

**Rules:**
- ✅ **Include:** Periods with 0 missing prices (complete portfolio coverage)
- ❌ **Exclude:** Any period with n_missing_price > 0 (data gaps)
- ⚠️ **Alert:** Log when periods are excluded due to data quality

**Example:**

| Date | Excess | Missing Prices | Included? | Reason |
|------|--------|-----------------|-----------|--------|
| 2026-05-20 | -3.88pp | 30/30 | ❌ No | Complete data loss |
| 2026-05-27 | -1.32pp | 1/30 | ❌ No | Incomplete coverage |
| 2026-05-29 | -0.64pp | 0/30 | ✅ Yes | Complete data |
| 2026-06-04 | -3.09pp | 0/30 | ✅ Yes | Complete data |

**Result:** -1.86pp average (only valid periods) → **PASSES** -2.0pp threshold

### Layer 2: Data Integrity Validation (validate_metric_data_integrity)

**Code Location:** `tools/weekly_readiness_scorecard.py:validate_metric_data_integrity()`

**What It Does:**
Validates that performance dataset is suitable for gating decisions

**Checks:**
```
✓ Recent 4-period data completeness (alert if >50% missing prices)
✓ Dataset size (alert if <4 periods available)
✓ Stale metric detection (alert if last perf date is old)
```

**Triggers:**
- 🚨 **ALERT** if max missing prices in recent 4 periods > 50%
- 🚨 **ALERT** if fewer than 4 periods in performance dataset
- ℹ️ **WARNING** logged if any integrity issue detected

**Example Output:**
```
⚠️  DATA INTEGRITY WARNING: Recent performance has 67% missing price data. 
    Metrics may reflect data gaps, not portfolio quality.
```

### Layer 3: Scorecard Context Transparency

**Code Location:** `tools/weekly_readiness_scorecard.py:build_scorecard()`

**What It Does:**
Includes data integrity warnings in scorecard JSON/markdown output

**Fields Added:**
```json
{
  "context": {
    "data_integrity_warning": "⚠️ Recent performance has X% missing prices...",
    "n_performance_rows": 104,
    "latest_perf_date": "2026-06-12"
  }
}
```

**Display in Markdown:**
```markdown
### Data Integrity Note
[Shows any warnings flagged during validation]
```

---

## Operational Behavior

### When Safeguards Trigger

**Scenario 1: Period with >50% missing prices**
```
Input:  perf_rows with n_missing_price: 20/30 in recent 4-period tail
Output: Data integrity warning logged
        Check detail includes "complete data only" annotation
        Operator can see metric is based on incomplete information
```

**Scenario 2: Insufficient complete periods**
```
Input:  Only 1 period with 0 missing prices (need 2+)
Output: Check status → HOLD
        Detail: "Insufficient complete-data periods: 1 (need 2)"
        Trading gate remains CLOSED until more valid data available
```

**Scenario 3: Fresh complete data**
```
Input:  All recent 4 periods have n_missing_price = 0
Output: No warning; normal metric calculation proceeds
        Metric used for gating with full integrity
```

---

## Test Coverage

**File:** `tests/test_shadow_metric_integrity.py`  
**Status:** 5/5 tests passing

| Test | Purpose | Pass |
|------|---------|------|
| `test_excludes_missing_price_periods` | Verify missing-price exclusion filter | ✅ |
| `test_holds_on_insufficient_complete_periods` | Verify HOLD on <2 complete periods | ✅ |
| `test_detects_excessive_missing_prices` | Verify integrity warning on 67% missing | ✅ |
| `test_passes_on_complete_recent_data` | Verify no warning on complete data | ✅ |
| `test_insufficient_data_warning` | Verify alert on <4 periods | ✅ |

---

## Governance Rules (Permanent)

### Rule G1: Data Completeness Requirement
> Any performance period used for gating must have n_missing_price = 0 (complete portfolio coverage). Periods with missing prices are automatically excluded from metric averages.

### Rule G2: Minimum History Threshold
> Metrics require a minimum of 2 complete-data periods before they can gate trading decisions. If fewer than 2 valid periods exist, the check returns HOLD status.

### Rule G3: Data Integrity Flagging
> Any scorecard computation that encounters data quality issues (>50% missing prices, <4 total periods) must include a warning in the output. Operators must review warnings before trading.

### Rule G4: Detail Transparency
> Check detail fields must explicitly state how many periods were excluded and why (e.g., "Trailing 2-period avg (complete data only). Excluded 2 rows with missing prices.").

---

## Metrics Updated

The following metrics now have built-in safeguards:

| Metric | Safeguard | Trigger |
|--------|-----------|---------|
| `shadow_excess_vs_xbi` | Exclude n_missing_price > 0 | Metric calculation |
| `turnover_stability` | Exclude blank turnover | Metric calculation |
| (Others: standard filters in place) | - | - |

---

## Future Enhancements

1. **Automated stale metric detection:** Flag metrics not updated within N days
2. **Per-check data quality scoring:** Each check reports % valid vs total periods
3. **Configurable thresholds:** Allow operators to tune missing-price exclusion threshold (currently 0)
4. **Performance data validation step:** Pre-validate entire CSV on load

---

## References

- **Root Cause Analysis:** `/artifacts/readiness/CORRECTION_LOG_2026-06-16.md`
- **Fixed Scorecard:** `/artifacts/readiness/scorecard_2026-06-15.json` (June 16 rebuild)
- **Implementation:** `tools/weekly_readiness_scorecard.py` (lines 554-620, 644-661)
- **Tests:** `tests/test_shadow_metric_integrity.py`
