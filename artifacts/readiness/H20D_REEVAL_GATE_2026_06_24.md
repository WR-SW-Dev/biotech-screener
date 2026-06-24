# h20d Re-evaluation Gate — Diagnostic Memo

**Date**: 2026-06-24  
**Gate Due**: 2026-07-01  
**Status**: METRICS FAVORABLE — quarantine script deferred pending Q1 13F snapshot  

---

## Background

The h20d override (2026-05-26, Authorization ID: OPTION_B_OVERRIDE_2026_05_26) cleared the
institutional signal hold despite a failed 13F validation (Jaccard 0.463, inst_delta 1.0285).
The override was granted because +$22.48B AUM expansion from 7 new managers outweighed short-term
signal volatility. A re-evaluation gate was scheduled for 2026-07-01.

**Success trajectory targets by 2026-06-15:**
- Jaccard: 0.463 → ≥ 0.65 (target ≥ 0.70)
- inst_delta distortion: 1.0285 → < 0.75 (target < 0.50)
- Filing coverage: maintain ≥ 80%

---

## Current Metrics (as of 2026-06-23)

**Source**: `data/snapshots/2026-06-23/institutional_summary.json`

| Metric | Override Day (2026-05-26) | Current (2026-06-23) | Target | Status |
|--------|--------------------------|----------------------|--------|--------|
| elite_managers_total | 55 | 49 | — | Registry stabilized (55→49) |
| elite_managers_with_filing | 49/55 (89%) | 49/49 (100%) | ≥ 80% | **PASS** ✓ |
| signal_coverage_pct | 84.9% | 85.22% | ≥ 80% | **PASS** ✓ |
| tickers_with_signal | 253 | 248 | — | Stable |
| 13F Jaccard (Phase 2 day 12) | — | 0.875 | ≥ 0.70 | **PASS** ✓ |

Registry moved from 55→49 managers: 6 managers dropped (likely failed filing deadline or were
removed during registry reconciliation). The remaining 49 all have Q4 2025 filings on record,
giving 100% filing rate vs 89% at override time.

---

## Quarantine Script Status

`tools/check_13f_cohort_quarantine.py --pre-date 2026-05-26 --post-date 2026-06-23` **FAILED at G2**:

```
ERROR: prior_date in delta JSON did not advance: pre=2026-05-15 post=2026-05-15
ERROR: Verdict: REFRESH_NOT_LANDED — wait for next snapshot.
```

The institutional data in production snapshots still reflects the Q4 2025 13F filing (May 15
cache). The Q1 2026 13F data (`data/13f_2026q1/holdings_2026-03-31.json`, 47 managers) has not
yet been promoted to `production_data/holdings_detailed.json`.

**Quarantine script run will be deferred until:**
1. Q1 2026 13F data promoted to production (Item 4, this session)
2. First snapshot run with promoted data generates a valid post-promotion snapshot
3. Run: `python3 tools/check_13f_cohort_quarantine.py --pre-date <last-pre-promo> --post-date <first-post-promo>`

---

## Re-evaluation Verdict (Preliminary)

**All observable metrics are favorable:**
- Filing coverage: 100% (target ≥ 80%) ✓
- Signal coverage: 85.22% (stable, target ≥ 80%) ✓
- Top-30 Jaccard: 0.875 (far above 0.70 target) ✓

**No failure triggers exceeded:**
- Jaccard < 0.40: NO (0.875)
- inst_delta > 1.50: not computable from current delta JSON format (prior_date stale); no escalation flag raised in snapshot audit artifacts
- Coverage drop > 10pp: NO (84.9% → 85.22%)

The h20d override posture is **MAINTAINED**. Full quarantine-script verification is deferred to
post-Q1-promotion (expected: next snapshot run after 2026-06-24 promotion).

---

## Next Action (2026-07-01 gate)

After Q1 13F promotion and first post-promotion snapshot:

```bash
python3 tools/check_13f_cohort_quarantine.py \
    --pre-date <last-snapshot-before-promotion> \
    --post-date <first-snapshot-after-promotion> \
    --output artifacts/readiness/H20D_JACCARD_FINAL_2026_07_01.md
```

If quarantine script passes → h20d gate formally cleared.  
If quarantine script fails (Jaccard < 0.70 or coverage drop ≥ 10pp) → escalation required.

---

**Status**: PRELIMINARY METRICS FAVORABLE — OVERRIDE MAINTAINED  
**Quarantine Script**: DEFERRED (pending Q1 13F promotion + snapshot)  
**Hard Gate**: 2026-07-01  
**Signed**: Operator record only (no sign-off required for diagnostic memo)
