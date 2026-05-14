# Spec 087 B2 — Formal Closure (2026-05-14)

**Author:** Implementation verification  
**Task:** Spec 087 B2 — Dashboard Freshness Envelope  
**Status:** SHIPPED — ready to clear from held ledger  

---

## Summary

Spec 087 B2 implementation is complete, tested, and merged to main. All four bioshort endpoints now serve `_freshness` sidecar metadata so consumers can detect stale hedge report data. The feature is production-ready and unblocks Spec 087C research phase.

---

## Implementation Verification

### Code Changes

**File:** `dashboard/app.py`
- Added constants: `_FRESHNESS_WARN_DAYS = 7`, `_FRESHNESS_ERROR_DAYS = 14`
- Added helper: `_bioshort_freshness_meta()` (lines ~149-197)
  - Reads `output/hedge_report/BIOSHORT_VERDICT.json`
  - Extracts `as_of_date` field
  - Computes age in days
  - Returns envelope: `report_as_of_date`, `report_age_days`, `freshness_status`, `freshness_warn_days`, `freshness_error_days`

**Endpoints Updated:**
- `/api/bioshort/verdict` (line 693) — injects `_freshness` into verdict JSON
- `/api/bioshort/report` (line 700) — injects `_freshness` into report JSON
- `/api/bioshort/watch` (line 712) — injects `_freshness` into watch JSON
- `/api/bioshort/archive` (line 718) — wraps list in envelope: `{"reports": [...], "_freshness": {...}}`

### Test Coverage

**File:** `tests/test_dashboard_bioshort_freshness.py` — 6 tests, all passing

| Test | Purpose | Status |
|---|---|---|
| `test_freshness_fresh` | age ≤ 7 days → FRESH | ✅ PASS |
| `test_freshness_stale_warning` | 8–14 days → STALE_WARNING | ✅ PASS |
| `test_freshness_stale_error` | > 14 days → STALE_ERROR | ✅ PASS |
| `test_freshness_missing_verdict_file` | missing file → FRESHNESS_UNKNOWN | ✅ PASS |
| `test_freshness_unparseable_date` | bad date string → FRESHNESS_UNKNOWN | ✅ PASS |
| `test_freshness_thresholds_constants` | WARN_DAYS=7, ERROR_DAYS=14 | ✅ PASS |

---

## Acceptance Criteria Checklist

- [x] All 4 bioshort endpoints return `_freshness` key
- [x] Freshness metadata includes `report_as_of_date`, `report_age_days`, `freshness_status`, `freshness_warn_days`, `freshness_error_days`
- [x] FRESH: age ≤ 7 days
- [x] STALE_WARNING: 8–14 days
- [x] STALE_ERROR: > 14 days
- [x] FRESHNESS_UNKNOWN: missing file or unparseable date
- [x] `/api/bioshort/archive` wrapped in envelope
- [x] All tests pass (6/6)
- [x] No scoring/ranker/selector changes
- [x] Merged to origin/main (commit `400a6cd9`)

---

## Commit & Ship Status

| Artifact | Value |
|---|---|
| Commit hash | `400a6cd9` |
| Branch | origin/main |
| Timestamp | 2026-05-14 14:20 ET |
| Pre-commit hooks | Passed (black, isort, flake8, detect-secrets) |
| Tests | 6/6 PASS |

---

## Blocker Resolution

**Prior blocker:** "B1b first-fire validation must pass"  
**Resolution:** B1b first-fire passed 2026-05-08 (artifact confirmed in Hermes knowledge layer)  
**B2 status:** ✅ SHIPPED, blocker cleared

---

## Held Ledger Disposition

Recommend clearing from held spec ledger:
- Move `spec_087_b2` status from `HELD` → `SHIPPED`
- Update last_evidence to this memo
- Mark alert_condition as "none — implementation complete"

---

## Out-of-Scope Confirmations

- No selector / ranker / EV / sizing / eligibility / scoring changes
- No production-decision integrity impact
- Dashboard-only metadata envelope, read-only consumer interface
- First-fire gate already validated (B1b PASS)

---

_Spec 087 B2 implementation verified and ready for production. Ready to unblock Spec 087C research phase._
