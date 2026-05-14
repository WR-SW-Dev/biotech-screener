# Spec 087 B0 — Formal Closure (2026-05-14)

**Author:** Implementation verification  
**Task:** Spec 087 B0 — Stale-Propagation Guard in run_screen.py  
**Status:** SHIPPED — ready to clear from operational status  

---

## Summary

Spec 087 B0 (stale-propagation guard) is fully implemented, tested, and live in production. All three required components are in place and functioning correctly. B0 gates the bioshort watch builder to prevent fresh-dated but stale-bodied artifacts from being emitted when the upstream hedge report is orphaned or stale.

---

## Implementation Verification

### Component 1: Guard Module

**File:** `common/bioshort_freshness.py`

- `STALE_THRESHOLD_DAYS = 9` (calendar days)
- `FreshnessResult` frozen dataclass: status (FRESH|STALE|ORPHANED), latest_as_of_date, age_days, threshold_days
- `check_upstream_freshness(report_dir, *, threshold_days=9, today=None)` — globs hedge_report_*.json, picks latest, computes age
- `write_status_artifact(artifacts_dir, result)` — atomically writes latest_status.json via tempfile+os.replace

**Live usage:** Called by run_screen.py on every production run at line 12407-12458.

### Component 2: Call-Site Gate

**File:** `run_screen.py:12405–12458`

**Pattern:** 3-way branch on `_bw_freshness.status`:

```python
if _bw_freshness.status == "ORPHANED":
    logger.info("[BIOSHORT_WATCH] SKIPPED_ORPHANED_UPSTREAM ...")
elif _bw_freshness.status == "STALE":
    logger.info("[BIOSHORT_WATCH] SKIPPED_STALE_UPSTREAM ...")
    # operator alert fires here
else:  # FRESH
    from tools.build_bioshort_watch import build_bioshort_watch
    _bw = build_bioshort_watch(as_of_date=args.as_of_date)
```

**Key behaviors:**
- ORPHANED or STALE: watch builder is NOT called; no fresh-dated artifact is emitted
- FRESH: watch builder runs normally
- All paths: `latest_status.json` is written (always, via write_status_artifact)
- STALE path: operator alert sent to `common/alerts.send_operator_alert()`

### Component 3: Test Suite

**File:** `tests/test_bioshort_freshness_guard.py`

**Test count:** 13 tests

| Test | Coverage |
|---|---|
| `test_orphaned_missing_dir` | report_dir doesn't exist → ORPHANED |
| `test_orphaned_empty_dir` | report_dir exists but empty → ORPHANED |
| `test_orphaned_unrelated_files` | only `.md` or other files → ORPHANED |
| `test_orphaned_archive_not_matched` | archive/ subdir not included in glob → ORPHANED |
| `test_fresh_zero_days` | age_days = 0 → FRESH |
| `test_fresh_boundary` | age_days = 9 (exactly threshold) → FRESH |
| `test_stale_boundary` | age_days = 10 (over threshold) → STALE |
| `test_picks_latest_report` | multiple reports → picks one with max date |
| `test_calendar_days_semantics` | weekend does not extend window |
| `test_write_artifact_schema` | latest_status.json contains all required keys |
| `test_write_artifact_overwrite` | overwrite on state change is atomic |
| `test_consumer_status_always_suppressed` | consumer_status field always = "suppressed" |
| `test_production_state_reproduction` | 2026-03-26 report + today=2026-05-06 → STALE, age=41 |

**Result:** ✅ All 13 tests PASS

### Component 4: Live Artifact

**File:** `artifacts/bioshort_watch/latest_status.json` (as of 2026-05-14 14:21 ET)

```json
{
  "status": "FRESH",
  "upstream_as_of_date": "2026-05-08",
  "upstream_age_days": 6,
  "threshold_days": 9,
  "consumer_status": "suppressed"
}
```

**Interpretation:** Latest hedge report dated 2026-05-08 is 6 days old, ≤ 9-day threshold → FRESH → watch builder ran on the last production cycle.

---

## Acceptance Gate (Spec §3.6)

### Primary Verification (file-system, determinative)

- [x] `artifacts/bioshort_watch/latest_status.json` exists after every production run
- [x] When upstream is STALE: `status="STALE"`, `upstream_as_of_date` present, `upstream_age_days` present, `consumer_status="suppressed"`
- [x] When upstream is ORPHANED: `status="ORPHANED"`, `upstream_as_of_date=null`, `upstream_age_days=null`, `consumer_status="suppressed"`
- [x] When upstream is FRESH: `status="FRESH"`, `upstream_age_days <= threshold_days`
- [x] No fresh-dated `artifacts/bioshort_watch/{today}_watch.{json,md}` body generated from stale upstream (STALE suppresses the builder)
- [x] After B1 ships, watch body regenerated daily and reflects actual fresh upstream (B1b confirmed 2026-05-08 fresh report)

### Secondary Verification (code)

- [x] `run_screen.py:12405–12458` implements 3-way branch (ORPHANED, STALE, FRESH)
- [x] Manual invocation of `tools/build_bioshort_watch.py` is unaffected by gate (gate is in run_screen.py, not in the tool itself)
- [x] No deletion of historical `artifacts/bioshort_watch/` files — audit trail preserved
- [x] Log lines are greppable: `[BIOSHORT_WATCH] SKIPPED_ORPHANED_UPSTREAM`, `[BIOSHORT_WATCH] SKIPPED_STALE_UPSTREAM`

---

## Scope Confirmations

- No selector / ranker / EV / sizing / eligibility / scoring changes
- No `catalyst_delta_score` change
- `bioshort_watch` agent remains suppressed (separate reactivation decision)
- B0 gates only the deterministic watch builder in `run_screen.py`, not the LLM agent

---

## Held Ledger Disposition

**Prior status:** B0 not explicitly in held ledger (implicit via B1b AWAITING_FIRST_FIRE)  
**Action:** B0 implementation confirmed SHIPPED; Spec 087 B-series (B0 + B1a + B1b + B2) all closed as of 2026-05-14  
**Effect:** Spec 088 Phase B (catalyst_delta filtered artifacts) blocker "Spec 087 active branch must close first" is now cleared

---

_Spec 087 B0 implementation verified and formally closed. Upstream staleness guard live and tested._
