---
name: openclaw-cron-scheduler-debug
description: "Diagnose cron and scheduler failures for the OpenClaw biotech screener fleet. Encodes real failure patterns from production: crontab REPLACE silent death, WSL2 sleep cliff, Hermes scheduler stall, watchdog idempotency loops."
when_to_use: "User says 'cron didn't fire', 'production missed', 'agents not running', 'watchdog looping', or fleet receipt shows broad STALE across many agents with no obvious code cause."
---

# OpenClaw Cron / Scheduler Debugger

Covers the biotech screener at `/mnt/c/Projects/biotech_screener/biotech-screener`.
Production is Mon-Fri only. Sleep cliff is ~17:30 ET on weeknights.

## Hard rules

- Diagnose-only by default. Never edit crontab without operator approval + preview diff.
- Always diff before apply. Never `sed -i` without a preview step.
- One remediation at a time.

---

## Failure taxonomy

### Class A — Crontab REPLACE silent death

**Signature:** Root cron daemon alive (root hourly fires in syslog), but zero user
CMD entries for all arrenchulz jobs from a specific timestamp forward. No syslog
error. Only clue is a `REPLACE` event near the gap.

**Cause:** A crontab edit wrote a file the daemon could not parse. On bad parse,
the daemon reloads and silently drops ALL user jobs with no stderr, no email, no alert.

**Confirmed instance:** 2026-05-02T12:43+12:46 ET — two REPLACE ops during a triage
session. All jobs from 12:46 forward were silent: data_refresh, data_extras,
production (16:30), agents (17:00-18:55), heartbeat_checks, data_auditor all missed.

**Diagnostic recipe:**

```bash
# 1. Find the REPLACE events
grep "arrenchulz.*REPLACE\|arrenchulz.*RELOAD" /var/log/syslog | tail -20

# 2. Confirm absence of user CMD entries after the REPLACE
grep "2026-MM-DD" /var/log/syslog | grep "CRON\[" | grep "CMD" | grep -v "root\|hourly\|e2scrub" | tail -20
# Empty despite root cron firing = Class A confirmed

# 3. Confirm current crontab parses
crontab -l > /tmp/cron_test.txt && echo "PARSE OK" || echo "PARSE FAIL"
```

**Resolution:**
1. Verify current crontab is parseable.
2. Determine what was missed — check `data/snapshots/<date>` for weekday gaps.
3. Manual production backfill for a missed weekday:
   `bash tools/cron_daily_production.sh <YYYY-MM-DD>`
   (script guards against weekends — no need to check manually)

**Pitfall:** `data/snapshots/YYYY-MM-DD` absence on a weekend date is NORMAL.
Never try to backfill Saturday/Sunday production.

---

### Class B — WSL2 host-sleep cliff

**Signature:** Multiple STALE findings in fleet receipt, all with last-write ≤ 17:30
ET on a weeknight. Everything after ~17:30 ET is sleep-roulette.

**Confirmed schedule:** Production (16:30) and heartbeat_checks (17:30) are the last
reliable slots. Phase-2 agents (18:00-18:55), data_auditor (18:00), bellringer
results (18:30), evening catchup (22:00) all at risk.

**Diagnostic recipe:**

```bash
# 1. Cron daemon uptime
service cron status | grep "Active:"
# If "active since" predates missing run, daemon was down

# 2. Last production entry
tail -5 logs/cron.log

# 3. Which logs stopped at ~17:30?
for log in logs/*.log; do
  mt=$(stat -c '%Y' "$log")
  printf '%s  %s\n' "$(date -d @$mt '+%F %H:%M')" "$(basename $log)"
done | sort
```

**Mitigations already in place:**
- Tier-1: critical jobs scheduled ≤ 17:30 ET (patched 2026-05-02)
- Tier-2: `tools/cron_evening_catchup.sh` at 22:00 + @reboot
- Tier-3: weekend calibration catchup (Sat/Sun 09:00 ET)

---

### Class C — Hermes scheduler stall

**Signature:** Linux cron alive and user CMD entries firing, but Hermes cron jobs
show `last_run_at: null` and `next_run_at` in the past. These are SEPARATE systems.

**Confirmed instance:** 2026-05-03 00:33 ET — Linux cron last logged 17:30 on 05-01,
Hermes scheduler had 3 of 4 jobs with `last_run_at: null` overdue by 27h+.
The `openclaw-auth-sync` 6-hourly job never fired → 9 agent profiles expired simultaneously.

**Diagnostic:** Use `mcp_cronjob action='list'`. Red flags: `last_run_at: null` with
`next_run_at` in the past, or daily job last ran 36h+ ago.

**Resolution order:**
1. Re-trigger Hermes scheduler (cronjob run or recreate).
2. Run `~/.local/bin/openclaw-auth-sync` manually if auth drift suspected.
3. Re-trigger `tools/agent_heartbeat_checks.py` manually.
4. Confirm both schedulers caught their next slot.

---

### Class D — Watchdog idempotency loop

**Signature:** `logs/watchdog.log` shows the same phase-2 agents "recovered" every
30 minutes, with "Phase-2 agent recovery complete" each cycle, yet next cycle still
sees them as MISSED.

**Cause:** The "already recovered for <date>" marker is not being written, written
to the wrong path, or checking the wrong date key.

**Confirmed instance:** 2026-05-04 14:00 + 14:30 ET — same 5 agents recovered twice.

**Diagnostic:**

```bash
# What does the watchdog use as its "already ran" check?
grep -n "PROD_RAN\|already.ran\|skip\|rankings\|snapshot" tools/cron_watchdog.sh | head -20

# Check the production ran marker
ls -la data/snapshots/$(date +%Y-%m-%d)/rankings.csv 2>/dev/null || echo "MISSING"
ls -la logs/.daily_production.lock 2>/dev/null || echo "NO LOCK"
```

**Note:** On weekends this loop is benign (Mon-Fri jobs, harmless recovery calls).

---

### Class E — data_auditor weekend false-positive

**Signature:** `integrity_report_<YYYY-MM-DD>.json` on Saturday or Sunday shows
`verdict: FAIL` with `archive_verification: FAIL` ("Archive missing for <Sat> AND <Fri>")
and cascade ERRORs on universe_ipo, pit_financials, financial_consistency, price_data_gaps.

**Cause:** `run_audit.py --daily-only` doesn't guard against weekend execution.
Expects same-day rankings.csv that will never exist for Sat/Sun.

**Known behavior. Disregard entirely unless the FAIL date is a weekday.**

```python
import json, datetime
report = json.load(open('artifacts/data_auditor/integrity_report_YYYY-MM-DD.json'))
date = datetime.date.fromisoformat(report['as_of_date'])
if date.weekday() >= 5:
    print("WEEKEND FALSE-POSITIVE — disregard")
```

---

## Quick-reference triage

```
Broad STALE (≥3 agents, last write ~17:30 ET)?
  → Class B. Run the log-mtime sweep first.

Broad STALE but syslog has user CMDs all day?
  → Class A. Find the REPLACE event in syslog.

Fleet receipt itself is >24h old?
  → fleet_steward's own cron slot missed (17:30 ET).
  → Also check Hermes scheduler (Class C).

data_auditor FAIL on a weekend date?
  → Class E. Known false-positive. Disregard.

Watchdog recovering same agents every 30 min?
  → Class D. Check the idempotency marker.

Hermes jobs show last_run_at null despite Linux cron alive?
  → Class C. Separate scheduler.
```

---

## Preview-then-apply contract for crontab edits

```bash
# 1. Backup (timestamped)
crontab -l > "$HOME/crontab.bak.$(date +%Y%m%d_%H%M%S)"

# 2. PREVIEW — process substitution, no side effects
diff <(crontab -l) <(crontab -l | sed -E '...')
# STOP — show operator the diff. Wait for "apply" confirmation.

# 3. APPLY — identical pipeline from step 2 (only after explicit approval)

# 4. VERIFY
crontab -l | grep '<changed entry>'
```
