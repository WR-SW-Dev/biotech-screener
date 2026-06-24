# Spec 101: Runway Severity v1.1 Export Contract

**Status:** COMPLETE (2026-06-24)  
**Priority:** P0 (Schema correctness)  
**Phase:** SHIPPED  
**Owner:** Operator

---

## Summary

The runway severity computation now has two internal paths:
- **Truth gate severity**: "Can they survive to catalyst?"
- **EV/sizing severity** (`ev_severity_score`): "What financing damage even if they survive?"

The model computes `ev_severity_score` internally but **does not export it** to `rankings.csv`. This creates a contract gap: the field exists in memory but is not observable in production artifacts.

**Build:** Export `ev_severity_score` to CSV and establish the export contract.

---

## Scope

### Current State
`RUNWAY_SEVERITY_CSV_COLUMNS` exports:
- `runway_severity_score`
- `runway_buffer_months`
- `financing_truth_gate`
- `dilution_haircut`
- `size_multiplier`
- `severity_bucket`
- `severity_notes`

**Missing:** `ev_severity_score` (computed but not exported)

### Build

1. **CSV Export Wiring**
   - Add `ev_severity_score` to `RUNWAY_SEVERITY_CSV_COLUMNS`
   - Add line: `row["ev_severity_score"] = ov.ev_severity_score`
   - Verify column appears in fresh `rankings.csv`

2. **Schema Registration**
   - Add `ev_severity_score` to `SNAPSHOT_COLUMNS`
   - Add type: `float`, range: `[0.0, 1.0]`
   - Add description: "EV-impact severity (0=no financing damage, 1=extreme)"

3. **Data Type & Bounds**
   - Type: float
   - Expected range: [0.0, 1.0] (clamped in computation)
   - Semantics: higher = worse (more dilution/cap raise risk)

4. **QA Coverage**
   - Add to production_qa schema validator
   - Assert all non-null values in [0.0, 1.0]
   - Assert no NaN/Inf
   - Alert if >50% of records are 0.0 (possible upstream issue)

---

## Regression Tests

### Test 1: Dilution Haircut Formula
```
ev_severity_score = X
dilution_haircut = 0.35 * X
```
- Load 10 recent snapshots
- For each record: verify `dilution_haircut ≈ 0.35 * ev_severity_score` (±0.001)
- File: `tests/test_runway_severity_v1_1.py`

### Test 2: Size Multiplier Formula
```
ev_severity_score = X
size_multiplier = max(0.40, 1 - 0.60 * X)
```
- Load 10 recent snapshots
- For each record: verify `size_multiplier ≈ max(0.40, 1 - 0.60 * ev_severity_score)` (±0.001)
- Boundary test: X=0 → size_multiplier=1.0; X=1 → size_multiplier=0.4
- File: `tests/test_runway_severity_v1_1.py`

### Test 3: Schema Presence
- Fresh snapshot contains `ev_severity_score` column
- No parse errors
- 299 records populated
- File: `tests/test_expectation_schema.py`

### Test 4: Regression on 2026-05-14
- Load `data/snapshots/2026-05-14/rankings.csv`
- Verify all 299 records have `ev_severity_score`
- Verify all in [0.0, 1.0]
- Verify dilution_haircut/size_multiplier formulas hold

---

## Acceptance Criteria

- [ ] `ev_severity_score` exported to CSV
- [ ] Column appears in `SNAPSHOT_COLUMNS`
- [ ] Fresh snapshot (2026-05-14 or later) contains field
- [ ] All 299 records have valid float value in [0.0, 1.0]
- [ ] Dilution haircut formula verified: `dilution_haircut ≈ 0.35 * ev_severity_score`
- [ ] Size multiplier formula verified: `size_multiplier ≈ max(0.40, 1 - 0.60 * ev_severity_score)`
- [ ] Production QA flags low coverage (<10% non-zero values) if observed
- [ ] All regression tests pass

---

## Non-Scope

- Changing ev_severity_score computation logic
- Historical backfill (Spec 102: Historical Backfill for Expectation Research)
- Expectation model wiring (Spec 105: Expectation Layer Coverage Verification)
- Insider signal promotion (Spec 104: Insider Diagnostic Stabilization)

---

## Implementation Notes

- This is pure export plumbing; no model logic changes
- Formulas (`dilution_haircut = 0.35 * X`, etc.) should be documented in code comments
- Add to existing runway severity module, not new module
- Estimated effort: 2-3 hours (plumbing + tests)
