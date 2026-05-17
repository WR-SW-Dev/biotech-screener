# Spec 100 Pre-Clearance Baseline Artifact — 2026-05-17

**Purpose:** Establish Spec 100 corrected IC measurement baseline before post-freeze validation runs.

**Date:** 2026-05-17 (pre h20d checkpoint ~2026-05-26)

---

## Spec 100 Correction Summary

| Component | Change | Status |
|-----------|--------|--------|
| **IC Measurement Signal** | `composite_score` → `final_score` (production ranker) | ✓ CORRECTED (Commit 2faa88e6) |
| **Tooling** | run_rank_ic_backtest.py default signal | ✓ Updated (Spec 100) |
| **Metadata Labels** | `spec_100_status: "CORRECTED"` in output | ✓ Added |
| **Prior IC Claims** | `composite_score` IC backtest results | ❌ INVALIDATED (Spec 095 finding) |

---

## Artifact Status

**Baseline Artifact:** `output/spec_100_smoke_baseline_2026_05_17.json`

**State:** Dry run (no usable snapshots with sufficient forward-return data)
- Tool: Ready ✓
- Signal field: `final_score` (correct) ✓
- Metadata labels: `spec_100_status: "CORRECTED..."` (correct) ✓
- Return data limitation: Last return date = 2026-05-05; snapshots range 2026-05-08 through 2026-05-15 (insufficient 60d forward horizon)

**Interpretation:** DEFERRED until post-freeze when return data matures.

---

## Decision Tree for Post-Freeze Validation (Awaits May 26+)

When h20d checkpoint lifts (~2026-05-26):

1. **If return data through 2026-06-15+ is available:**
   - Re-run with full snapshot date range (2026-05-01+)
   - Measure ranker IC using corrected `final_score` signal
   - Apply full Checklist v2 battery (FM + bootstrap + FDR + LOSO + year stab)
   - Decision: Promotion eligible vs. remains frozen

2. **If return data still insufficient:**
   - Defer IC evaluation further
   - Continue architecture freeze pending fuller return data

---

## Governance Record

- **Spec 100 corrected:** Commit 2faa88e6 (rebased on origin/main)
- **Baseline artifact:** Pre-clearance, read-only, labels correct
- **13F quarantine:** Still active (blocks ranker changes until ~2026-05-23+)
- **Architecture freeze:** Lifts ~2026-05-26; full validation post-lift
- **No interpretation yet:** Artifact serves as tooling verification only

**Enforcement:** Do NOT promote ranker or make selector/sizing changes until post-freeze Checklist v2 battery passes AND 13F cohort clears.
