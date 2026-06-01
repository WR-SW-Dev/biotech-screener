# Phase 2 Relock: Decision Portfolio as Canonical Day 1
**Date:** 2026-06-01  
**Decision:** Use `decision_portfolio.csv` / `decision_portfolio.json` as authoritative Phase 2 Day 1 artifact  
**Status:** RELOCKED — Phase 2 ACTIVE

---

## Relock Approval

**Operator Decision:** Use the fresh canonical decision portfolio (generated via `run_production_screen.py` after Module 5 fix) as the authoritative Phase 2 Day 1 holdings baseline.

**Module 5 Fix:** Commit `01f9aeda` (weakest-link aggregation collapse fixed)

---

## Authoritative Day 1 Artifact

| Item | Location | Status |
|------|----------|--------|
| **Day 1 Portfolio** | `data/snapshots/2026-06-01/decision_portfolio.csv` | ✅ Canonical |
| **Day 1 Metadata** | `data/snapshots/2026-06-01/decision_portfolio.json` | ✅ Canonical |
| **Holdings Count** | 297 tickers | ✅ Valid |
| **Snapshot Generated** | 2026-06-01 (post-fix) | ✅ Fresh |
| **Total Artifacts** | 53 files | ✅ Complete |

---

## What Changed from Quarantine

**Previous Day 1 (Quarantined):**
- Raw composite ranking artifact (broken aggregation)
- Status: INVALID_FOR_PHASE2

**New Day 1 (Relocked):**
- Decision portfolio artifact (decision engine output)
- Module 5 fix active
- Generated through canonical `run_production_screen.py`
- Status: AUTHORITATIVE

---

## Quarantine Status

| Artifact | Status | Disposition |
|----------|--------|-------------|
| `data/snapshots/2026-06-01_QUARANTINED_BACKUP/` | QUARANTINED | Keep for audit trail; do not use |
| Raw composite rankings | INVALID | Replaced by decision portfolio |
| Diagnostic candidate artifacts | Not promoted | Archived for evidence |

---

## Governance Checkpoints

✅ **Phase 2 Relock Checkpoints:**
- [x] Module 5 fix verified (commit `01f9aeda`)
- [x] Fresh canonical snapshot generated
- [x] Decision portfolio exists (decision_portfolio.csv/json)
- [x] 297 holdings present
- [x] 53 standard artifacts complete
- [x] Portfolio differs meaningfully from quarantined (12/30 overlap in top-30)
- [x] Broken composite ranking artifact quarantined

✅ **Day 1 Locked:** 2026-06-01 canonical decision portfolio  
✅ **Phase 2 Status:** ACTIVE — manual daily tracking authorized  
✅ **Daily Runs:** Use `data/snapshots/YYYY-MM-DD/decision_portfolio.csv` as source

---

## Phase 2 Resume

**Manual Daily Tracking:**
```bash
python3 scripts/run_phase2_forward_paper_test.py \
  --test-length 1 \
  --output-dir artifacts/portfolio_policy_forward_test/ \
  --paper-only
```

**Paper-Only:** All results marked `"paper_only": true`  
**No Cron:** Manual runs only  
**Snapshot Source:** Latest available `data/snapshots/YYYY-MM-DD/decision_portfolio.csv`

---

## Next Governance Gates

| Trading Day | Target | Action |
|-------------|--------|--------|
| **~Day 30** | ~2026-06-28 | 30-day review checkpoint |
| **~Day 60** | ~2026-07-28 | 60-day review checkpoint |
| **~Day 90** | ~2026-08-27 | 90-day final review |

---

## References

- **Module 5 fix:** Commit `01f9aeda`
- **Fresh canonical:** `data/snapshots/2026-06-01/`
- **Quarantine memo:** `SNAPSHOT_QUARANTINE_2026_06_01.md`
- **Recovery Option C:** `PHASE2_RECOVERY_OPTION_C_2026_06_01.md`
- **Execution log:** `artifacts/portfolio_policy_forward_test/PHASE2_EXECUTION_LOG.md`

---

## Summary

✅ Phase 2 relocked using decision portfolio as canonical Day 1  
✅ Module 5 fix verified and active  
✅ Fresh canonical snapshot with 53 artifacts  
✅ Broken composite artifact quarantined  
✅ Manual daily tracking authorized  

**Phase 2 is ACTIVE from 2026-06-01 decision portfolio.**
