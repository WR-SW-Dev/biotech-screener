# Spec 100: True Ranker IC Tooling — Completion Status

**Date:** 2026-05-14  
**Commit:** `baf514b9` (partial: design + scaffold only)  
**Status:** DESIGN + SCAFFOLD SHIPPED; IMPLEMENTATION PENDING

---

## What's Shipped (baf514b9)

✓ **Design memo:** `artifacts/audit/spec_100_true_ranker_ic_tooling_design_2026_05_14.md`
  - Clarifies composite_score IC ≠ ranker IC (different universes)
  - Defines three measurement levels: baseline, selector-only, candidate
  - Specifies implementation architecture, outputs, test structure

✓ **Scaffold script:** `scripts/research/run_true_ranker_ic.py`
  - CLI argument parsing (--start-date, --end-date, --candidates, etc.)
  - Snapshot discovery and loading
  - Eligible-universe filtering logic
  - Output directory structure

---

## What's NOT Yet Complete

❌ **`load_forward_returns()` is a stub**
  - Currently returns empty dict
  - Needs to load forward return data (Morningstar or SEC filing returns)
  - Must support T+5, T+10, T+20, T+60 horizons

❌ **`measure_ranker_ic()` returns placeholder zeros**
  - Currently emits `{horizon: 0.0}` for all measurements
  - Needs to compute real Pearson correlations between ranks and returns
  - Must validate that composite_score IC and actionable_rank IC are on different universes

❌ **No real IC output**
  - CSV files are created but contain all-zero IC values
  - Tests cannot validate actual measurement quality

❌ **No forward-return integration tests**
  - Missing: test that composite_score IC ≠ actionable_rank IC
  - Missing: test that missing returns cause skip/warn, not fake zero IC
  - Missing: test that candidate IC is computed from actual returns

❌ **No closure artifact**
  - Needs at least one dry-run result showing real IC output
  - Should document which forward returns were used, how joins handled, etc.

---

## Required Follow-Up Commit

**Title:** `Complete Spec 100: true ranker IC forward-return wiring`

**Scope:**
1. Implement `load_forward_returns(snapshot_dir, horizons)` to join snapshot tickers with SEC/Morningstar forward returns
2. Implement real IC computation in `measure_ranker_ic()` (Pearson correlation on eligible universe)
3. Emit actual per-horizon IC values (not zeros) to CSV output
4. Add tests:
   - `test_composite_score_ic_vs_actionable_rank_ic_different_universes()`
   - `test_eligible_universe_filtering_applied()`
   - `test_missing_returns_cause_warn_not_fake_ic()`
   - `test_candidate_ic_from_real_returns()`
5. Create closure memo with sample dry-run artifact showing real IC output

**Expected timeline:** 1–2 days of work (after 2026-05-15 snapshot with forward returns available)

---

## Why Not Complete Yet

The current scaffold cannot be used for ranker promotion evidence because:

| Blocker | Why It Matters | Status |
|---------|---|---|
| No forward returns | IC requires actual returns; zeros are fake | ❌ Not wired |
| No real IC computation | Pearson correlation not implemented | ❌ Placeholder only |
| No validation tests | Cannot prove composite ≠ ranker IC | ❌ Missing |
| No closure artifact | No evidence tool actually works | ❌ Missing |

**Spec 096 states:** Ranker promotion requires "correct IC scope" (Spec 095) verified by "true ranker IC tooling" (this spec). The scaffold satisfies the design requirement but not the implementation requirement.

---

## How Spec 100 Fits in Ranker Promotion Path

```
Spec 072 D7/D8/D9 pass (2026-05-22)
    ↓
Spec 072 D1–D6 pass (2026-05-27)
    ↓
Run Spec 100 tool on candidate
    ├─ Requires: complete forward-return wiring + real IC outputs
    ├─ Measures: true ranker IC of candidate on eligible universe
    └─ Proves: Spec 094 (marginal value) + Spec 095 (correct scope)
    ↓
Candidate IC passes Spec 094/095/100
    ↓
Checklist v2 (orthogonality, LOSO, year stab, domain)
    ↓
Production ranker promotion authorized
```

**Current state:** Spec 100 tool cannot be used until forward-return wiring is complete.

---

## Not Blocking 2026-05-22 Review

Spec 072 verification (D7/D8/D9) does NOT require Spec 100 to be complete:
- D7/D8/D9 use existing snapshot data (scores, ranks, candidate features)
- Forward returns not needed until D1–D6 or Spec 100 tool use
- Can proceed with 2026-05-22 review on schedule

**Spec 100 completion needed for:** Post-review candidate IC measurement (2026-05-27+)

---

## References

- Design memo: `artifacts/audit/spec_100_true_ranker_ic_tooling_design_2026_05_14.md`
- Scaffold: `scripts/research/run_true_ranker_ic.py` (commit `baf514b9`)
- Blocker: Specs 094/095/100 required for ranker promotion (Spec 096)
