# Evening Reliability Watchdog — Test Plan (2026-05-15)

**Purpose**: Verify that the morning catch-up watchdog (Option C) correctly detects and backfills missing evening forward-shadow jobs.

**Crontab Entry**: Added 2026-05-15
```
15 09 * * 1-5 /mnt/c/Projects/biotech_screener/biotech-screener/tools/cron_evening_reliability_check.sh >> logs/evening_reliability_check.log 2>&1
```

**Test Window**: 2026-05-16 (Friday) and 2026-05-19 (Monday)

---

## Pre-Test Verification ✅

### Script Status
- **File**: `tools/cron_evening_reliability_check.sh` — 84 lines, executable
- **Dependencies**:
  - `tools/inst_delta_forward_compare.py --as-of YYYY-MM-DD` ✅
  - `tools/cross_signal_forward_logger.py --as-of YYYY-MM-DD` ✅
- **Log Directory**: `artifacts/audit/evening_reliability_checks/` — auto-created ✅
- **Output Log**: `logs/evening_reliability_check.log` (via crontab)

### Backfill Status
- **May 14**: Both artifacts present (backfilled 2026-05-15)
  - inst_delta checkpoint: 23K
  - cross_signal buckets: 64K
- **May 12–13**: Both artifacts present (backfilled 2026-05-15)
- **May 9**: inst_delta ✅, cross_signal ❌ (snapshot not available — expected)

### Manual Test ✅
- Ran watchdog manually on May 15 at 16:14 — detected May 14 artifacts missing, backfilled successfully
- Re-ran immediately — detected artifacts present, skipped backfill (idempotent)

---

## Test Execution Plan

### Scenario A: Normal Evening Run (May 16 Friday 19:30–19:40)

**Expected Behavior**:
- 19:30 ET: inst_delta_forward_compare.sh runs, produces checkpoint_2026-05-16.json
- 19:40 ET: cross_signal_forward_logger.sh runs, produces buckets_2026-05-16.json
- Both complete successfully without WSL invocation failure

**Verification Steps**:
1. Check logs/inst_delta_forward_shadow.log for entry at 19:30–19:35
2. Check logs/cross_signal_forward_shadow.log for entry at 19:40–19:45
3. Verify artifacts exist:
   - artifacts/audit/inst_delta_forward_shadow/checkpoint_2026-05-16.json
   - artifacts/audit/cross_signal_forward_shadow/buckets_2026-05-16.json
4. Watchdog runs May 19 09:15 ET: detects artifacts, skips backfill (idempotent)

**Success Criteria**: All four steps pass (evening jobs fire normally, watchdog detects presence)

---

### Scenario B: Evening Job Failure (May 16 19:30–19:40)

**If** WSL sleep issue recurs and evening jobs do NOT fire:

**Expected Behavior**:
1. No entry in logs/inst_delta_forward_shadow.log after May 15
2. No entry in logs/cross_signal_forward_shadow.log after May 15
3. Watchdog runs May 19 09:15 ET (morning after weekend), detects missing May 16–19 artifacts
4. Watchdog backfills May 19 artifacts (prior trading day before weekend)
5. log entry: "⚠️ Missing inst_delta checkpoint for 2026-05-19; running backfill..."

**Verification Steps**:
1. Check artifacts/audit/evening_reliability_checks/watchdog_2026-05-19.log
2. Verify backfill succeeded (artifacts created and valid)
3. Verify log shows "✅ inst_delta backfill completed" and "✅ cross_signal backfill completed"

**Success Criteria**: Watchdog successfully detects and backfills missing runs

---

## Decision Tree

| Evening Jobs Fire? | Watchdog Detects | Backfill Runs | Decision |
|--------------------|------------------|---------------|----------|
| ✅ Yes | ✅ (skips backfill) | No | WSL issue resolved; proceed to Phase 2 Step 3b completion |
| ❌ No | ✅ (detects missing) | Yes | Watchdog working; consider Task Scheduler if pattern repeats |
| ❌ No | ❌ (detects nothing) | No | Script bug; investigate watchdog logic |

---

## Timeline

| Date | Event | Action |
|------|-------|--------|
| 2026-05-15 | Watchdog crontab entry added | Monitor evening jobs |
| 2026-05-16 (Fri) | 19:30–19:40 ET evening forward shadows | Check logs for normal execution |
| 2026-05-16 (Fri) | Snapshot available | Watchdog backfill safe for May 15–16 |
| 2026-05-19 (Mon) | 09:15 ET morning watchdog | Check artifacts/audit/evening_reliability_checks/watchdog_2026-05-19.log |
| Post-May-19 | 1 full weekday clean run verified | Proceed to Phase 2 Step 3b (wire agent_preflight.py) |

---

## Exit Criteria

**Phase 2 Step 3 COMPLETE** when:
1. ✅ Evening reliability audit memo committed (1712111d)
2. ✅ Watchdog script committed (1c12b6b4)
3. ✅ Crontab entry added (verified 09:15 ET, weekdays)
4. ✅ May 12–15 backfill successful (artifacts present)
5. ✅ Manual watchdog test passed (idempotent)
6. ⏳ One weekday clean run verified (May 16 or May 19)

**Next Phase**: Phase 2 Step 3b (wire agent_preflight.py into run_agent_direct.py; do NOT proceed until May 19 verification)

---

## Monitoring

### Daily Checks (May 16–May 19)
```bash
# Check evening job logs
tail -5 logs/inst_delta_forward_shadow.log
tail -5 logs/cross_signal_forward_shadow.log

# Check for artifacts (date varies)
ls -lh artifacts/audit/inst_delta_forward_shadow/checkpoint_*.json | tail -3
ls -lh artifacts/audit/cross_signal_forward_shadow/buckets_*.json | tail -3

# Check watchdog log (after 09:15 ET on weekday)
ls -lh artifacts/audit/evening_reliability_checks/watchdog_*.log | tail -3
cat artifacts/audit/evening_reliability_checks/watchdog_*.log | tail -10
```

### Expected Log Output (Watchdog Success)
```
[2026-05-19T09:15:XX-04:00] Evening reliability check for prior trading day: 2026-05-16
[2026-05-19T09:15:XX-04:00] ✅ inst_delta checkpoint exists: 2026-05-16
[2026-05-19T09:15:XX-04:00] ✅ cross_signal buckets exist: 2026-05-16
[2026-05-19T09:15:XX-04:00] Evening reliability check complete
```

---

## Notes

- Watchdog is **diagnostic-only** — does not modify production state
- Backfill is **deterministic** (snapshot-based reads) — safe to replay any date
- Idempotent by design — safe to run multiple times per day
- Next phase decision depends on whether evening jobs fire correctly May 16 or stall again (which would trigger watchdog backfill on May 19)
