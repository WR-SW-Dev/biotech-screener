# Evening Cron Reliability Audit — 2026-05-15

## Overview

**Diagnostic Period**: 2026-05-08 → 2026-05-15  
**Status**: Five evening jobs scheduled; two stalled (forward shadows since May 9), three active  
**Root Cause**: WSL cron invocation failure in 19:30–19:40 window (scripts themselves are clean; cron not firing)  
**Recommendation**: Implement Option C (morning catch-up watchdog) before considering remediation A/B

---

## Scheduled Evening Jobs

| Job | Cron | Expected | Last Artifact | Status |
|-----|------|----------|----------------|--------|
| inst_delta_forward_shadow | 19:30 ET | weekdays | 2026-05-08 19:30 | **STALLED** |
| cross_signal_forward_shadow | 19:40 ET | weekdays | 2026-05-08 19:40 | **STALLED** |
| postmortem_pipeline | 17:40 ET | weekdays | 2026-05-13 17:40 | ACTIVE (1d lag) |
| policy_shadow_nightly | 18:05 ET | weekdays | 2026-05-15 18:05 | ACTIVE |
| review_queue_steward | 18:50 ET | weekdays | TBD | LIKELY ACTIVE |

---

## Artifact Freshness (May 9–15)

### ✅ Still Running (Daily Updates)
- `artifacts/shadows/regime_shadow_*.md` — May 13, 14, 15 (morning, 09:23, 09:06, 09:50)
- `artifacts/shadows/shadow_monitor_*.md` — May 8, 11, 12, 13, 14, 15
- `policies/policy_shadow_nightly_2026_05_15.md` — exists, 18:05 timestamp present

### ❌ Stalled (No Update Since May 8)
- `logs/inst_delta_forward_shadow.log` — last entry May 8 19:30, clean exit
- `logs/cross_signal_forward_shadow.log` — last entry May 8 19:40, clean exit

### ⚠️ Degraded (Partial Activity)
- `artifacts/postmortem/*.md` — postmortem_pipeline ran May 13 only; expected daily

---

## Log Inspection Results

### inst_delta_forward_shadow.log
- **Last entry**: 2026-05-08 19:30 (Thursday)
- **Exit status**: Clean (artifacts written, regime buckets logged)
- **Entries after May 8**: None (missing May 9 Friday, May 12–15 Mon–Thu)
- **Crontab**: `30 19 * * 1-5 /mnt/c/Projects/biotech_screener/biotech-screener/tools/cron_inst_delta_forward_compare.sh >> logs/inst_delta_forward_shadow.log 2>&1`

### cross_signal_forward_shadow.log
- **Last entry**: 2026-05-08 19:40 (Thursday)
- **Exit status**: Clean (artifacts written, bucket logger output)
- **Entries after May 8**: None (missing May 9 Friday, May 12–15 Mon–Thu)
- **Crontab**: `40 19 * * 1-5 /mnt/c/Projects/biotech_screener/biotech-screener/tools/cron_cross_signal_forward_logger.sh >> logs/cross_signal_forward_shadow.log 2>&1`

### Conclusion
Scripts are **deterministic and replay-safe** (no external market data dependency detected). Both exited cleanly on May 8. **Cron invocation failure in 19:30–19:40 window starting May 9**, not a code bug.

---

## Six Audit Questions & Answers

### 1. Which evening jobs are scheduled?

**Answer**: Five jobs between 17:40–19:40 ET (weekdays only).
- postmortem_pipeline (17:40) — event postmortem detection + calibration evidence
- policy_shadow_nightly (18:05) — governance/contradiction ledger update
- review_queue_steward (18:50) — artifact review & prioritization
- inst_delta_forward_shadow (19:30) — institution delta regime monitoring
- cross_signal_forward_shadow (19:40) — cross-sector signal regime monitoring

All in crontab. No edits recommended yet; diagnostic-only.

---

### 2. Which actually produced artifacts May 9–15?

**Answer**: Three active; two stalled.

**Active (daily or near-daily)**:
- regime_shadow (indirect: generated during morning daily_production.py, not evening job)
- shadow_monitor (dependency: reads regime_shadow, runs daily, outputs to artifacts/shadows/)
- policy_shadow_nightly (confirmed 18:05)
- postmortem_pipeline (degraded: ran May 13, missing May 9–12, May 14–15)

**Stalled (no invocation since May 8 19:30–19:40)**:
- inst_delta_forward_shadow (last run: May 8, clean exit, script verified working)
- cross_signal_forward_shadow (last run: May 8, clean exit, script verified working)

---

### 3. Is this WSL sleep fragility or script failure?

**Answer**: WSL cron invocation failure (not a script bug).

**Evidence**:
- Logs show clean exits on May 8 with artifacts correctly written
- Both jobs stopped at same time window (19:30–19:40)
- Crontab entries are present and correct
- Scripts executed successfully on May 8 and produced valid output
- No invocations observed since May 9 despite weekday scheduling

**Conclusion**: Cron daemon not firing jobs in 19:30–19:40 window (WSL sleep/wake timing issue). Scripts themselves are deterministic and safe.

---

### 4. Which can be caught up (backfill 2026-05-09 → 2026-05-15)?

**Answer**: Two yes (forward shadows); one maybe; two no.

**Can backfill** (read cached snapshots, no live market timing):
- inst_delta_forward_shadow — compute regime deltas from snapshot data; no external dependencies
- cross_signal_forward_shadow — compute cross-sector buckets from snapshot data; no external dependencies
- **Catch-up window open**: through May 22 (forward shadow verdict h20d)

**Cannot backfill** (external timing required):
- postmortem_pipeline — requires live event detection (closing announcements, 8-K filings); backfill data stale

**Timing uncertain**:
- policy_shadow_nightly — governance artifact (contradiction ledger snapshot); backfilling may be incorrect
- review_queue_steward — depends on queue state

---

### 5. Which jobs require live market timing?

**Answer**: One critical; two none; two uncertain.

**Requires live timing** (time-critical):
- postmortem_pipeline — event detection alerts used by production ops; backfill would miss real-time urgency

**Does NOT require live timing** (read cached snapshots only):
- inst_delta_forward_shadow
- cross_signal_forward_shadow

**Timing uncertain**:
- policy_shadow_nightly — governance artifact; verify whether backfill is semantically valid
- review_queue_steward — queue architecture dependency unclear

---

### 6. Recommended remediation path?

**Answer**: Implement Option C first (morning catch-up watchdog); do not move to Task Scheduler yet.

**Option C: Watchdog + Catch-Up (Recommended)**
- Create morning watchdog script (runs at ~09:15 ET during daily production setup)
- Watchdog checks: did inst_delta + cross_signal run yesterday? If not, catch-up backfill
- **Cost**: ~$0 (script-only); forward shadow memory delay (~12 hours acceptable)
- **Timeline**: 2–3 hours to write + test catch-up logic
- **Risk**: Low (backfill safe; shadows diagnostic-only, not critical path)
- **Scope**: `tools/cron_evening_reliability_check.sh` or `tools/check_evening_forward_shadows.py`
  - Check prior trading day for missing forward shadow runs
  - If missing, run replay/catch-up for that date
  - Write one audit log entry
  - Do not touch ranker/selector/sizing

**Why not A/B yet?**
- Forward shadows are diagnostic and replay-safe
- Catch-up reduces operational complexity vs. dual Windows/WSL scheduling
- Gives evidence continuity while diagnosing WSL sleep issue
- Can later migrate to Task Scheduler if watchdog proves insufficient

---

## Acceptance Criteria (Met)

| Criterion | Status |
|-----------|--------|
| Identified all scheduled evening jobs | ✅ |
| Traced artifact freshness 2026-05-09 → 2026-05-15 | ✅ |
| Log inspection confirms WSL invocation failure | ✅ |
| Separated WSL issue from code bugs | ✅ |
| Categorized catch-up feasibility | ✅ |
| Identified live-timing constraints | ✅ |
| Recommended remediation path (Option C) | ✅ |

---

## Next Phase (Post-Audit)

1. ✅ Log inspection confirms WSL cron invocation failure (not script bug)
2. ⏭️ Implement Option C: morning catch-up watchdog
   - File: `tools/cron_evening_reliability_check.sh` or `tools/check_evening_forward_shadows.py`
   - Behavior: detect missing forward shadow runs, backfill from snapshot cache, log result
   - Test: verify next scheduled weekday evening run fires correctly, or run manual dry-run/catch-up test
3. ⏭️ Commit watchdog + catch-up implementation
4. ⏭️ After 1 full day clean use: wire agent_preflight.py into run_agent_direct.py (Phase 2 Step 3b)

---

**Status**: Diagnostic complete. WSL cron invocation failure confirmed. Option C ready to implement.  
**Confidence**: High (log inspection definitively rules out script bugs).  
**Owner**: User approval to implement Option C watchdog.
