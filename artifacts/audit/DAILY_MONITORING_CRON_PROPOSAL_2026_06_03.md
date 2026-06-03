# Daily Monitoring Automation — Implementation Proposal
## Phase 2 Priority 4 Cron Integration (NOT YET APPROVED)

**Prepared:** 2026-06-03  
**Status:** PROPOSAL (awaiting explicit operator approval)  
**Decision Required:** Yes

---

## Executive Summary

This proposal outlines how to automate Phase 2 Priority 4 (daily monitoring evidence pack) via cron without violating governance constraints.

**Current State:** Evidence pack is manually run, read-only, no destructive behavior.

**Proposed Change:** Wire cron job to collect evidence daily, alert operator on state changes, do NOT auto-remediate.

**Cost:** One integration commit (proof-of-wiring, first-fire validation, rollback command).

**Risk Level:** LOW (read-only, alert-only, reversible).

---

## Exact Implementation Spec

### Script to Wire

**Path:** `tools/daily_path_c_monitoring.sh` (already exists, already invoked manually)

**Purpose:** Collect Path C / IC / shadow validation / primitive health / workspace hygiene evidence, log to file, alert operator on state changes.

**Current Status:** Works manually; not yet scheduled.

---

### Cron Call Site

**Schedule:** 08:00 AM ET daily (after market open, before operator review window)

**Cron entry:**
```bash
0 8 * * * /home/arrenchulz/.bashrc && cd /mnt/c/Projects/biotech_screener/biotech-screener && bash tools/daily_path_c_monitoring.sh >> /var/log/biotech_daily_monitoring.log 2>&1
```

**Rationale:** 08:00 AM ET gives operator time to review before morning decision windows (~08:30 AM IC updates, ~09:15 AM shadow artifacts).

---

### Log Path

**Output:** `/var/log/biotech_daily_monitoring.log`

**Format:** Append-only JSONL (one entry per run)

**Rotation:** Managed by `logrotate` (separate cron config, size-based 100MB + 7-day retention)

**Access:** Operator can `tail -f /var/log/biotech_daily_monitoring.log` for live monitoring

---

### First-Fire Validation Command

**Before wiring cron, run this manually:**
```bash
bash tools/daily_path_c_monitoring.sh 2>&1 | head -100
```

**Expected output:**
- Path C / IC status (observable/unobservable, mean_ic if available)
- Hard exits (Jaccard, drawdown, triggered?)
- Shadow rebalance artifacts (count post-lock)
- Phase 1b primitives (callable? firedhappy?)
- Workspace hygiene (untracked files same as baseline)

**Success criteria:**
- Script runs without errors
- All sections populated
- No state changes detected (expected for first run)

---

### Failure Behavior

**Scenario 1: Script fails (exception)**
- Cron logs error to `/var/log/biotech_daily_monitoring.log`
- Operator alerted via stderr (if cron has mail configured)
- **No auto-remediation.** Operator investigates manually.

**Scenario 2: State change detected (e.g., IC becomes observable)**
- Script detects via `if mean_ic != prior_value` check
- Alerts with `[ALERT] Path C / IC status changed: was UNOBSERVABLE, now OBSERVABLE`
- Operator must review and make decision (no auto action)

**Scenario 3: Hard exit triggered (e.g., Jaccard < 0.70)**
- Script detects via `if jaccard < 0.70` check
- Alerts with `[CRITICAL] Hard exit condition triggered: Jaccard 0.68 < 0.70`
- Operator must make emergency decision immediately

**No silent failures.** All states logged; all changes alerted.

---

### Proof Script is Alert-Only / Non-Blocking

**Script does NOT:**
- ✓ Modify portfolio
- ✓ Change ranker/selector/scoring
- ✓ Delete files
- ✓ Revert portfolio on hard exits (operator decides)
- ✓ Extend Path C window (operator decides)
- ✓ Close any governance gates

**Script DOES:**
- ✓ Read artifacts (read-only)
- ✓ Compare to baseline (no state mutation)
- ✓ Log findings (append-only)
- ✓ Alert operator (stdout to log, not auto-action)

**Verification:** Code review of `daily_path_c_monitoring.sh` will show all file I/O is read-only except logging.

---

### Rollback Command

**If cron behaves unexpectedly, operator runs:**
```bash
# 1. Remove cron entry
crontab -e  # delete the daily monitoring line

# 2. Verify removed
crontab -l | grep -v "daily_path_c_monitoring"

# 3. (Optional) Archive current log
mv /var/log/biotech_daily_monitoring.log /var/log/biotech_daily_monitoring.log.archive-$(date +%Y%m%d)

# 4. Resume manual evidence pack (Phase 2 Priority 4 still runs manually)
bash tools/daily_path_c_monitoring.sh  # one-off run
```

**Time to rollback:** < 2 minutes.

**Reversibility:** Complete (no persistent state changes; log files archived).

---

## One Commit, Proof-of-Wiring

### Scope
- Add cron entry to operator's crontab (or document it for operator to add manually)
- Confirm `daily_path_c_monitoring.sh` is executable and tested
- Commit message: "Phase 2 Priority 4: Daily monitoring cron wired (alert-only, operator-reviewed)"

### Files Modified
- `crontab` (operator's schedule) — not in git; documented in commit message with exact entry
- `tools/daily_path_c_monitoring.sh` — verify executable, no changes needed
- `artifacts/readiness/DAILY_MONITORING_CRON_PROPOSAL_2026_06_03.md` — this file, for record

### Proof-of-Wiring
```bash
# After cron is wired, verify:
crontab -l | grep "daily_path_c_monitoring"
# Expected output:
# 0 8 * * * /home/arrenchulz/.bashrc && cd /mnt/c/Projects/biotech_screener/biotech-screener && bash tools/daily_path_c_monitoring.sh >> /var/log/biotech_daily_monitoring.log 2>&1
```

### First-Fire Test
```bash
# Manually run the first-fire validation command above
# Verify output matches expected format
# Commit with this output in commit message as proof
```

---

## Implementation Checklist

### Pre-Approval (This Proposal)
- [x] Exact cron call site specified
- [x] Schedule justified (08:00 AM ET)
- [x] Log path documented
- [x] First-fire validation command provided
- [x] Failure behavior defined (alert-only, no auto-action)
- [x] Proof of alert-only nature provided
- [x] Rollback command documented (< 2 min)
- [x] One-commit integration plan defined

### Approval Required
- [ ] Operator reviews this proposal
- [ ] Operator selects: **APPROVE**, **DEFER**, or **REJECT**
- [ ] If **APPROVE**: proceed to implementation phase below

### Implementation Phase (If Approved)
- [ ] Run first-fire validation command manually
- [ ] Verify output format and no errors
- [ ] Operator adds cron entry: `crontab -e`
- [ ] Paste exact cron entry from proposal
- [ ] Verify: `crontab -l | grep "daily_path_c_monitoring"`
- [ ] Create commit with proof (crontab output + script executable status)
- [ ] Run daily monitoring once manually to populate log
- [ ] Verify log file at `/var/log/biotech_daily_monitoring.log`
- [ ] Confirm no operational impact on Phase 2

---

## Risk Assessment

| Risk | Likelihood | Mitigation |
|---|---|---|
| Cron fails silently | LOW | Stderr to log; operator alerts on missing entry |
| Script has exception | LOW | First-fire validation catches before approval |
| Log fills disk | LOW | logrotate manages rotation (100MB threshold) |
| Operator misses alert | MEDIUM | Operator reviews log daily; no auto-action |
| Hard exit triggers; operator doesn't respond | MEDIUM | Not cron's fault; operator decision gate |

---

## Conditions for Approval

**This proposal is approved for implementation IF:**
1. Operator explicitly approves in writing (or via git commit log message)
2. First-fire validation passes (script runs, output correct, no errors)
3. Rollback command is tested (crontab -e works, removal is clean)
4. Log file can be created and written (permissions OK)
5. No changes to ranker/selector/scoring/portfolio logic

**Conditions NOT met if:**
- Cron job auto-remediates (violates governance)
- Script modifies state (violates read-only constraint)
- Rollback takes >5 minutes (violates reversibility)
- Script is not alert-only (violates non-blocking constraint)

---

## Related Documents

- `tools/daily_path_c_monitoring.sh` — The script to be scheduled
- `PHASE_3_CONDITIONAL_ROADMAP_2026_06_03.md` — Decision framework this cron supports
- `Path C...decisions/alerts documented (2026-06-03)` — Baseline evidence

---

**Status: PROPOSAL READY FOR OPERATOR REVIEW**

**No cron entry has been wired. Awaiting explicit operator approval before implementation.**

**Next: Operator decision (APPROVE / DEFER / REJECT) on this proposal.**
