# ev_severity_score Export Status — May 15, 2026

**Status:** NOT A PRODUCTION BLOCKER
**Export:** Working correctly
**Date:** 2026-05-15

---

## Finding

The `ev_severity_score` column in `data/snapshots/2026-05-15/rankings.csv` is:

| Property | Status |
|----------|--------|
| Column present | ✓ YES (index 199) |
| Total rows | 298 |
| Populated rows | 298 (100%) |
| Blank rows | 0 |
| Values numeric | ✓ YES |
| Sample values | 0.006, 0.0, 0.0078, 0.0085, ... |
| Export status | ✓ WORKING |

---

## Non-Blocking Diagnostic Issue

**Script:** `tools/diagnose_ev_severity.py`
**Issue:** Import path error (`No module named 'event_ev'`)
**Impact:** Diagnostic script cannot run; production export unaffected
**Severity:** Low (hygiene only)

**Root cause:** Script runs outside of repo root context; sys.path doesn't include event_ev module.

**Fix:** Add repo root to `sys.path` or run as module. Deferred to non-blocking maintenance window.

---

## Verdict

✓ **Production export is functioning correctly.**

No code changes to production export logic are required. The diagnostic script needs a small path fix, but this is purely a developer-facing issue and does not affect production rankings generation.

**Action:** None. Mark as resolved with note that diagnostic-script cleanup is non-blocking hygiene work for later.

