# Spec 104: Insider Diagnostic Stabilization

**Status:** Design  
**Priority:** P2 (QA/stabilization, not urgent)  
**Phase:** A (Measurement & Stabilization)  
**Owner:** [TBD]

---

## Summary

Insider form 4 filing data is currently wired as a **diagnostic pass-through only**, not as alpha signal. The field `insider_net_buy_value_90d` uses Form 4 filing dates, correctly distinguishes blank (not fetched / no coverage) from `0.0` (fetched, no activity), and explicitly keeps the scoring lane closed.

**Do not reopen insider as alpha.** This spec ensures:
1. Insider coverage stabilizes after 5+ snapshots
2. Coverage is measured and reported
3. The field remains diagnostic/tracked-nonblocking
4. Blank vs zero semantics are preserved
5. Alpha feature registry is not modified

---

## Current State

- `insider_net_buy_value_90d` is exported to `rankings.csv`
- Sourced from `production_data/insider_form4.json`
- Scoring lane is **closed** (not contributing to final ranks)
- Blank ≠ zero: blank = no data, zero = data available but no activity
- Used for: diagnostic tracking, researcher curiosity, future research

---

## Scope

### Measurement Phase (This Spec)

**Do NOT promote insider to alpha during this phase.**

1. **Coverage Measurement**
   - Track `insider_net_buy_value_90d` coverage (% non-null) across 5+ production snapshots
   - Measure separately:
     - Blank (not fetched)
     - Zero (fetched, no activity)
     - Positive/negative (activity detected)
   - Emit report: `artifacts/insider_diagnostics/coverage_2026_05_14.json`
   - Example:
     ```json
     {
       "snapshot_date": "2026-05-14",
       "total_tickers": 299,
       "coverage": {
         "blank": 45,  // not fetched
         "zero": 120,  // fetched, no activity
         "positive": 89,   // net buying
         "negative": 45,   // net selling
         "blank_pct": 15.05,
         "zero_pct": 40.13,
         "nonblank_pct": 84.95,
         "activity_pct": 44.82
       }
     }
     ```

2. **Stability Criterion**
   - After 5+ consecutive trading days:
     - Coverage pct should be consistent (±5% variance acceptable)
     - Blank/zero ratio should be stable
     - If coverage drops or becomes erratic, investigate data source
   - File: `tools/measure_insider_coverage.py`

3. **Blank vs Zero Enforcement**
   - Code review: verify no collapsing of blank and zero
   - Verify Form 4 fetch logic: missing ticker → blank, not zero
   - Verify zero-value records are actually sourced from Form 4, not default-filled
   - File: `common/insider_signal.py` (if exists)

4. **Alpha Feature Registry Check**
   - Verify insider NOT listed in `ALPHA_FEATURE_REGISTRY` or equivalent
   - Verify insider NOT contributing to selector or ranker scores
   - Verify insider NOT in `ACTIVE_SIGNALS` list
   - File: search `common/ranker_active_contract.py` for "insider"

---

## Acceptance Criteria

- [ ] Coverage measured for 5+ consecutive snapshots (2026-05-10 through 2026-05-15)
- [ ] Coverage reports generated and archived
- [ ] Coverage variance <5% across 5 days (stability criterion)
- [ ] Blank vs zero semantics verified in code
- [ ] No collapsing of blank and zero confirmed
- [ ] Insider NOT in alpha feature registry
- [ ] Insider NOT contributing to final scores
- [ ] Code review confirms: `insider_net_buy_value_90d` is NOT passed as input to `ExpectationErrorModel`
- [ ] Grep/test confirms `expectation_error_model.py` does not read `insider_net_buy_value_90d` in feature-fetch logic
- [ ] Report generated: "Insider signal ready for future research (diagnostic only)"

---

## Measurement Report Template

File: `artifacts/insider_diagnostics/stabilization_report_2026_05_15.md`

```markdown
# Insider Signal Stabilization Report

**Date:** 2026-05-15  
**Measurement Period:** 2026-05-10 through 2026-05-15 (6 trading days)

## Coverage Summary

| Date | Blank | Zero | Activity | Nonblank % | Stability |
|------|-------|------|----------|-----------|-----------|
| 2026-05-10 | 45 | 120 | 134 | 85.0% | — |
| 2026-05-11 | 46 | 119 | 134 | 84.6% | ±0.4% |
| 2026-05-12 | 45 | 121 | 133 | 84.9% | ±0.3% |
| 2026-05-13 | 44 | 122 | 133 | 85.3% | ±0.4% |
| 2026-05-14 | 45 | 120 | 134 | 85.0% | ±0.3% |
| 2026-05-15 | 44 | 121 | 134 | 85.3% | ±0.3% |

## Verdict

- [x] Coverage stable (variance <1%)
- [x] Blank/zero semantics preserved
- [x] Insider remains diagnostic-only (not in alpha registry)
- [x] Ready for future research promotion (if decided)

## Recommendation

Insider signal **stabilized and ready for research use**. Do not promote to alpha without explicit decision and new Checklist v2 evaluation.
```

---

## Non-Scope

- **Do NOT promote insider to alpha during this phase**
- Do NOT change insider computation or weighting
- Do NOT add to selector or ranker
- Do NOT backfill historical insider data beyond what already exists
- Do NOT create new signals based on insider data

---

## Future Decision Point

Once stabilization report is generated, if stakeholders decide to promote insider to alpha:
1. New spec required: "Insider Alpha Promotion Battery" (similar to prior signal promotions)
2. Must pass Checklist v2 (bootstrap, FDR, LOSO, year stability)
3. Forward-return testing required
4. Separate promotion spec; NOT part of this spec

---

## Implementation Notes

- Measurement is **read-only**: no code changes to scoring
- Leverage existing `production_qa.py` infrastructure for coverage reporting
- Store coverage reports in `artifacts/insider_diagnostics/` with timestamps
- Create summary dashboard or README tracking stability over time
- Estimated effort: 1-2 days (measurement script + report generation + manual review)
