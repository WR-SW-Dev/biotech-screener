# Spec 105: Expectation Layer Coverage Verification

**Status:** Design  
**Priority:** P0 (Production gating)  
**Phase:** A (Design & Verification)  
**Owner:** [TBD]

---

## Summary

Verify that the expectation model's market-expectation fields are actually flowing into production `rankings.csv`, not just added to the schema. The diagnosis indicates feature coverage improved from ~80% to ~95% after wiring `short_interest_pct`, `close_price`, `market_cap_mm`, and `priced_move_pct`, with `insider_net_buy_value_90d` as the remaining gap.

This spec ensures the wiring is real, coverage is measurable, and production fails loudly if required fields are missing or below threshold.

---

## Scope

### Build / Verify

1. **Field Presence in rankings.csv**
   - Fresh production `rankings.csv` contains all expectation-model input fields:
     - `short_interest_pct`
     - `close_price`
     - `market_cap_mm`
     - `priced_move_pct`
     - `insider_net_buy_value_90d` (if present, allow blank/0.0 distinction)
   - Artifact: production snapshot from 2026-05-14 (or later)

2. **Coverage Gate Validation**
   - Measure % of universe with non-null values for each field
   - Apply field-specific thresholds per `tools/production_qa_check.py` FEATURE_COVERAGE_REQUIREMENTS:
     - `short_interest_pct`: ≥0.90 (required)
     - `close_price`: ≥0.99 (required)
     - `market_cap_mm`: ≥0.95 (required)
     - `priced_move_pct`: ≥0.80 (required)
     - `insider_net_buy_value_90d`: ≥0.30 (tracked_nonblocking)
   - Gate passes if all required fields meet floor; track non-required fields without failing
   - Emit coverage report: field → coverage % → threshold → pass/fail

3. **Expectation Model Consumption**
   - Verify expectation model actually reads these columns, not just exports them
   - Trace: `module_X.py` (expectation module) → `rankings.csv` column reads
   - Confirm no dead fields (e.g., added to CSV but not read)
   - Artifact: code review + trace log

4. **Failure Mode: Missing/Below-Threshold Fields**
   - Implement loudly-failing guard in production pipeline
   - If any required field missing → halt with explicit error message
   - If any field <floor coverage → emit WARN, allow run but flag snapshot as degraded
   - Log to `production_qa.log` for ops visibility

---

## Tests

1. **Coverage Report Test**
   - Load recent `rankings.csv`
   - Compute coverage % for each field
   - Assert required fields meet thresholds: short_interest ≥90%, close_price ≥99%, market_cap ≥95%, priced_move ≥80%
   - Assert insider ≥30% (non-failing report)
   - Test file: `tests/test_expectation_coverage.py`

2. **Schema Presence Test**
   - Assert `short_interest_pct`, `close_price`, `market_cap_mm`, `priced_move_pct` exist in CSV header
   - Assert no parse errors on those columns
   - Test file: `tests/test_expectation_schema.py`

3. **Model Consumption Trace Test**
   - Mock expectation module, verify it reads target columns
   - Verify no warnings about missing columns
   - Test file: `tests/test_expectation_module_integration.py`

4. **Regression: Coverage on 05-14 Production**
   - Load `data/snapshots/2026-05-14/rankings.csv`
   - Verify 299 records with required-field coverage: short_interest ≥90%, close_price ≥99%, market_cap ≥95%, priced_move ≥80%
   - Artifact: regression report

---

## Acceptance Criteria

- [ ] Fresh production snapshot contains all 4 core expectation fields
- [ ] Coverage report shows required thresholds met: short_interest ≥90%, close_price ≥99%, market_cap ≥95%, priced_move ≥80%
- [ ] Code trace confirms expectation module reads these fields (not dead)
- [ ] Production pipeline has explicit gate: missing/low-coverage fields → fail loudly
- [ ] Ops can see coverage report in production_qa output
- [ ] All regression tests pass on 2026-05-14 snapshot
- [ ] `insider_net_buy_value_90d` coverage measured and reported (no gate requirement; diagnostic)

---

## Non-Scope

- Backfilling historical snapshots (Spec 102: Historical Backfill for Expectation Research)
- Adding new expectation fields beyond the 4 core
- Changing expectation model logic
- Insider promotion to alpha (Spec 104: Insider Diagnostic Stabilization)

---

## Implementation Notes

- Leverage existing `production_qa.py` framework for coverage reporting
- Reuse schema validation infrastructure
- Coverage thresholds should be configurable (not hardcoded)
- Allow future easy addition of more fields
