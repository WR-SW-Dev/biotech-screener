# Spec 102: Historical Backfill for Expectation Research

**Status:** Design  
**Priority:** P1 (Research enablement, not production-critical)  
**Phase:** A (Design & Backfill)  
**Owner:** [TBD]

---

## Summary

Tomorrow-forward production is fine without historical expectation fields. But historical expectation-gap research is starved unless recent snapshots are backfilled with:
- `short_interest_pct`
- `close_price`
- `market_cap_mm`
- `priced_move_pct`
- Optionally: `insider_net_buy_value_90d`

**Not required for production**, but necessary for research workflows (e.g., analyzing whether expectation gaps existed in April snapshots).

---

## Scope

### Snapshots to Backfill
- Date range: 2026-04-20 through 2026-05-13 (recent, representative)
- Total: ~15 trading days (~15 snapshots)
- Preserve original ranks/actions unless explicitly recomputing

### Fields to Backfill
1. `short_interest_pct` (from production data)
2. `close_price` (from market data)
3. `market_cap_mm` (derived from price × shares)
4. `priced_move_pct` (from options market or historical returns)
5. `insider_net_buy_value_90d` (optional; Form 4 backfill)

### Implementation Strategy

1. **Backfill Script**
   - Input: snapshot date
   - Output: updated CSV with fields added
   - Logic:
     - Load original `rankings.csv`
     - Fetch field values from production data sources (short interest, market data)
     - Inject into CSV at correct columns
     - Preserve all other columns, ranks, actions unchanged
   - File: `tools/backfill_expectation_fields.py`

2. **Coverage & Manifest**
   - For each backfilled snapshot, emit manifest:
     - Snapshot date
     - Fields added
     - Coverage before/after (% non-null per field)
     - Whether actions were recomputed (none; preserve original)
   - Example:
     ```
     snapshot: 2026-05-13
     fields_added: short_interest_pct, close_price, market_cap_mm, priced_move_pct
     coverage_before: short_interest_pct=0% | close_price=0% | market_cap_mm=0% | ...
     coverage_after: short_interest_pct=92% | close_price=100% | market_cap_mm=100% | ...
     actions_recomputed: false
     ```
   - Emit to: `artifacts/backfill_manifest/backfill_expectation_fields_YYYY-MM-DD.json`

3. **Pre/Post Backfill Guard**
   - Add metadata field to snapshot JSON or CSV comment:
     ```
     # backfill_expectation_fields: true
     # backfill_date: 2026-05-14T10:30:00Z
     ```
   - Research scripts can check this flag: if not present, fields are not reliable for analysis
   - Artifact: `data/snapshots/YYYY-MM-DD/.backfill_metadata.json`

### Data Sources

| Field | Source | Fallback |
|-------|--------|----------|
| `short_interest_pct` | `production_data/short_interest.json` | Yahoo Finance (if not available) |
| `close_price` | `production_data/daily_prices.json` | yfinance |
| `market_cap_mm` | Derived: price × shares from universe | Yahoo Finance |
| `priced_move_pct` | `production_data/options/` or historical returns | Skip if not available |
| `insider_net_buy_value_90d` | `production_data/insider_form4.json` | Leave blank if not available |

---

## Tests

1. **Backfill Completeness**
   - Run backfill on 2026-05-13 snapshot
   - Verify all 4 core fields added
   - Verify no other columns changed
   - File: `tests/test_backfill_expectation.py`

2. **Coverage Validation**
   - Backfilled snapshot has ≥85% non-null for `short_interest_pct`, `close_price`, `market_cap_mm`
   - `priced_move_pct` may be lower (optional, data-dependent)
   - File: `tests/test_backfill_coverage.py`

3. **Manifest Generation**
   - Backfill emits JSON manifest with correct structure
   - Manifest includes coverage before/after
   - File: `tests/test_backfill_manifest.py`

4. **Guard Flag**
   - Metadata file created with `backfill_expectation_fields: true`
   - Metadata readable by downstream research scripts
   - File: `tests/test_backfill_metadata.py`

5. **Regression: Rank Preservation**
   - Load backfilled 2026-05-13 snapshot
   - Compare ranks vs original: should be identical
   - Compare actions vs original: should be identical
   - File: `tests/test_backfill_preservation.py`

---

## Acceptance Criteria

- [ ] Backfill script runs without errors on 2026-05-13
- [ ] All 4 core fields added to snapshot
- [ ] Coverage ≥85% for `short_interest_pct`, `close_price`, `market_cap_mm`
- [ ] Original ranks/actions preserved (no recomputation)
- [ ] Manifest JSON created with correct metadata
- [ ] Guard flag (`.backfill_metadata.json`) created
- [ ] All 15 snapshots (2026-04-20 through 2026-05-13) backfilled
- [ ] Research scripts can detect backfilled snapshots via metadata flag
- [ ] No data corruption or parse errors

---

## Non-Scope

- Backfilling snapshots older than 2026-04-20
- Recomputing ranks/actions (preserve originals)
- Changing expectation model logic
- Production-critical gating (research-only)

---

## Timeline

- **Design**: 1 day (this spec)
- **Implementation**: 2-3 days (backfill script + tests + 15 runs)
- **Validation**: 1 day (coverage review, manifest audit)
- **Total**: 4-5 days

---

## Implementation Notes

- Backfill is idempotent: re-running on same snapshot should produce same result
- Preserve CSV column order (don't reorder)
- Handle missing tickers gracefully (leave field blank, don't error)
- Log each backfill run to audit trail
- Keep original CSVs as reference (don't overwrite; create `_backfilled.csv` variant or archive originals)
- Research scripts should check `.backfill_metadata.json` before using expectation fields
