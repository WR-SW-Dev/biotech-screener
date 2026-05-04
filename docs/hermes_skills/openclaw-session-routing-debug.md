---
name: openclaw-session-routing-debug
description: "Diagnose OpenClaw session, auth, task routing, and registry failures for the biotech screener fleet. Covers OAuth profile drift, stale_running zombie tasks, lost task warnings, and mass agent failures from shared credential expiry."
when_to_use: "Many agents failing with credential errors, openclaw tasks audit shows errors, stale_running entries appear, or a large cluster of tasks fail with identical error messages. Load alongside openclaw-fleet-triage when the receipt shows widespread task failures."
---

# OpenClaw Session / Routing Debugger

For the biotech screener at `/mnt/c/Projects/biotech_screener/biotech-screener`.
Diagnose-only. Never print live secrets. Schema-only credential inspection only.

---

## Hard rules

- NEVER cat/print auth-profiles.json, .credentials.json, or any file matching
  `*credential*`, `*secret*`, `*token*`. Schema-only inspection via JSON-load → keys/types.
- If a secret leaks into chat anyway, STOP and tell operator to rotate before continuing.
- Diagnose-only until operator approves a single remediation.

---

## Failure taxonomy

### Class A — Mass agent task failure from OAuth drift

**Signature:** `openclaw tasks list --json` shows a large cluster of `status: failed`
tasks across multiple agents with identical errors:
- `FailoverError: No credentials found for profile "anthropic:claude-cli"`
- `FailoverError: No API key found for provider "anthropic". Auth store: ...auth-profiles.json`

**Root cause (confirmed pattern):** OpenClaw per-agent
`~/.openclaw/agents/<name>/agent/auth-profiles.json` files do NOT auto-refresh from
the source-of-truth `~/.claude/.credentials.json`, even when both reference the same
`anthropic:claude-cli` profile. When the claude-cli refreshes its own token, OpenClaw's
per-agent caches go stale. Every agent fails identically at the same time.

**Do NOT conclude "every agent is broken." Conclude "shared credential is expired."**

**Diagnostic recipe (schema-only — never print token values):**

```python
import json, glob, os
from datetime import datetime, timezone

now = datetime.now(timezone.utc).timestamp()
for p in sorted(glob.glob(os.path.expanduser('~/.openclaw/agents/*/agent/auth-profiles.json'))):
    ag = p.split('/agents/')[1].split('/')[0]
    d = json.load(open(p))
    prof = d.get('profiles', {}).get('anthropic:claude-cli')
    if not prof:
        print(f'{ag:<25} NO anthropic:claude-cli profile')
        continue
    exp = prof.get('expires', 0) / 1000
    state = 'EXPIRED' if exp < now else 'ok'
    exp_str = datetime.fromtimestamp(exp, tz=timezone.utc).isoformat()[:16]
    print(f'{ag:<25} expires={exp_str} {state}')
    # DO NOT print access_token, refresh_token, or any token field
```

**Cluster the errors to confirm shared cause:**

```bash
openclaw tasks list --json > /tmp/oc_tasks.json
python3 -c "
import json
from collections import Counter
tasks = json.load(open('/tmp/oc_tasks.json'))
errs = [t.get('error','') for t in tasks if t.get('status') == 'failed']
for err, n in Counter(errs).most_common(5):
    print(n, repr(err[:120]))
"
```

**Resolution (operator-approved):**
1. Operator runs `claude /login` (or equivalent re-auth) in a separate terminal.
2. Fresh creds land in `~/.claude/.credentials.json`.
3. Run `~/.local/bin/openclaw-auth-sync` (idempotent, safe).
4. Re-run one failing task to confirm before mass-recovery.

**Prevention:** The `openclaw-auth-sync` 6-hourly Hermes cron job handles this
automatically. If it stalled (Class C in `openclaw-cron-scheduler-debug`), that
is why the profiles expired simultaneously.

---

### Class B — stale_running zombie tasks

**Signature:** `openclaw tasks audit` shows `code: stale_running` entries on
`runtime: cli` heartbeat rows. `openclaw status` Tasks bucket shows "audit N errors."

**Zombie heuristic (all four must hold before cancelling):**
1. `lastEventAt == startedAt` (or within seconds) — task never emitted an event
2. `endedAt: n/a` and `cleanupAfter: n/a`
3. Age in days, not minutes
4. Owning `:main` session NOT in the active session list from `openclaw status`

**Confirmed instance:** 2026-05-03 — 14 stale_running findings, 10 were zombies
(all `:main` session-owned CLI heartbeats frozen for days). 4 were legitimate.

**Diagnostic recipe:**

```bash
# Full audit
openclaw tasks audit

# Inspect one before cancelling
openclaw tasks show <taskId>
# Verify: lastEventAt == startedAt, no endedAt, no cleanupAfter, owning session absent

# Preview maintenance (does NOT help for stale_running CLI heartbeats, but confirm)
openclaw tasks maintenance
# If output shows "0 reconcile · 0 recovered · 0 cleanup stamp · 0 prune" → sweeper is a no-op
```

**Cancel loop (after operator approval, verify ONE probe first):**

```bash
# Step 1: verify the oldest is a zombie
openclaw tasks show <taskId>

# Step 2: cancel confirmed zombies
for tid in <token1> <token2> ...; do
  echo "=== $tid ==="
  openclaw tasks cancel "$tid" 2>&1
done

# Step 3: verify
openclaw tasks audit
```

**Pitfall:** `openclaw tasks maintenance --apply` is NOT the fix for stale_running
CLI heartbeats. It reconciles cron/subagent rows, not stuck CLI heartbeats.
Always run preview first to confirm it's a no-op.

---

### Class C — lost task warnings (self-evicting, benign)

**Signature:** `openclaw tasks audit` shows `severity: warn, status: lost` with
message "backing session missing." Tasks have real `endedAt` and `cleanupAfter`
~7 days out.

**Cause:** Post-completion drift. Cron task ran and finished, then its backing
session was GC'd before the task record was reconciled. Not an error.

**Confirmed instance:** 2026-05-04 — 4 lost warnings, all 4d2h old, all with
real endedAt and cleanupAfter dates. All self-evicting.

**Action:** None required. Let `cleanupAfter` sweep them. Only cancel if the
operator wants the audit clean immediately.

**Distinguishing from stale_running:**
- lost: `severity: warn`, real `endedAt`, populated `cleanupAfter`, `runtime: cron`
- stale_running: `severity: error`, no `endedAt`, no `cleanupAfter`, `runtime: cli`

---

### Class D — Session count bloat / 42+ active sessions

**Signature:** `openclaw status` shows 40+ active sessions. Most are "direct" sessions
from past runs that were never cleaned up.

**Observation (2026-05-04):** 42 active sessions, all heartbeating within 1h. This
is not necessarily a problem — OpenClaw maintains per-agent session state. Normal
for a 30-agent fleet.

**When to investigate:** If session count grows unbounded over weeks, or if specific
agents show session age > 7 days and those sessions are blocking new runs.

```bash
openclaw status
# Look at Sessions table — age column. Sessions >7d from non-active agents are candidates.
```

---

### Class E — Cron delivery "Channel is required" silent failure

**Signature:** Agent runs complete successfully (memory files written, artifacts generated),
but daily briefings/digests are never delivered. `openclaw tasks list --json` shows
`status: failed` with `error: "Channel is required (no configured channels detected)"`.
The agent LLM run and artifact write both succeed; the delivery hook fails silently.

**Confirmed instance:** 2026-05-03 runs.sqlite deep-dive — 14 cron failures cluster with
this error. ops: 13 failures in 6 days, sentinel: 8, qa: 4, grok_biotech_watch: 4,
bioshort_watch: active as of May 2. All agent outputs present; zero briefings delivered.

**Diagnostic recipe:**

```bash
# Check agent cron spec for delivery config
openclaw tasks list --json | python3 -c "
import json, sys
tasks = json.load(sys.stdin)
for t in tasks:
    if 'Channel is required' in (t.get('error') or ''):
        print(t.get('agentId'), t.get('taskId')[:8])
"

# Check openclaw.json for system-level delivery channel
cat ~/.openclaw/openclaw.json | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('delivery', 'NOT SET'))"
```

**Resolution:** Configure `delivery.channel` per agent cron spec, or set a system-level
default in openclaw.json. This failure is invisible from the data perspective — artifacts
are clean, agent ran correctly — but means 100% of briefings are silently undelivered.

---

### Class F — openclaw doctor --repair self-bricks on Distrod-WSL2 ARM64

**Signature:** `openclaw gateway status --deep` reports two warnings: (1) gateway PATH
includes nvm versioned path, (2) ExecStart uses nvm Node binary. Tool suggests
`openclaw doctor --repair`. Running --repair rewrites systemd unit to use
`/usr/local/bin/node` — which does NOT exist on this system — killing the gateway.

**Confirmed instance:** Multiple sessions 2026-05-03. System is Distrod-WSL2 ARM64
with stripped APT sources, no curl/wget, no system-wide Node. Operator chose "leave it"
each time. The warnings are cosmetic; the gateway functions normally.

**Safe diagnostic:**

```bash
# Check if /usr/local/bin/node exists BEFORE running --repair
ls /usr/local/bin/node 2>/dev/null || echo "MISSING — do NOT run --repair"

# Preview what --repair would do (dry-run first)
openclaw doctor --repair --dry-run

# Workaround if repair is needed: create symlink first
sudo ln -s ~/.nvm/versions/node/v22.22.1/bin/node /usr/local/bin/node
# THEN run --repair
```

**DO NOT run `openclaw doctor --repair` without first confirming `/usr/local/bin/node` exists.**

---

### Class G — Retired agent zombie in fleet (deregistration pending)

**Signature:** `openclaw status` shows an agent with sessions but "unknown/200k" context.
Fleet receipt lists it as STALE/NO_ARTIFACTS. Crontab shows the agent's entry commented
out with a RETIRED note. Memory directory is completely empty.

**Confirmed instance:** `shadow_watch` — crontab has `# RETIRED: shadow_watch
(consolidated into shadow_monitor via heartbeat_checks.py)`. Memory empty. Still
generating orphan session records and polluting fleet receipt counts.

**Distinguishing retired (shadow_watch) from silently-broken (grok_biotech_watch):**

```
shadow_watch (confirmed retired):
  - crontab entry has explicit RETIRED comment
  - memory/ is empty (zero files, never wrote)
  - no XAI/API credential required
  - safe to deregister immediately

grok_biotech_watch (status uncertain):
  - crontab entry WAS missing (now fixed to SCAN)
  - last artifact 34 days ago
  - requires XAI_API_KEY
  - may be auth-broken or intentionally paused — confirm before deregistering
```

**Resolution:** `openclaw agent deregister shadow_watch` (or equivalent). Safe because:
crontab already commented out, memory empty, functionality consolidated into shadow_monitor.
Until deregistered, it inflates STALE count and generates misleading openclaw status output.

---

## Quick-reference triage

```
Many tasks failed with identical FailoverError about credentials?
  → Class A. Run the expires-check script. Don't conclude "every agent broken."

openclaw tasks audit shows "N errors"?
  → Check: are they stale_running (Class B) or lost (Class C)?
  → lost + real endedAt + cleanupAfter = benign, self-evicting
  → stale_running + no endedAt + no cleanupAfter = zombie, needs cancel

openclaw status shows "audit N errors" but tasks audit shows only warnings?
  → Class C. The status counter inflates. Benign.

Single agent failing, not a cluster?
  → Not an auth/routing issue. Check the agent's own AGENTS.md and artifact paths.
  → Use openclaw-agent-scope-audit instead.

Agent runs succeed but briefings never arrive?
  → Class E. Delivery channel not configured. Check cron spec + openclaw.json.

openclaw doctor --repair warning about nvm PATH?
  → Class F. Check /usr/local/bin/node exists FIRST. If missing, do NOT run --repair.

Fleet receipt shows agent STALE with crontab entry commented out RETIRED?
  → Class G. Zombie retired agent. Safe to deregister if memory empty + no API key needed.
```

---

## Reading openclaw status output

Key fields to check immediately:

```
Tasks: 0 active · 0 queued · 0 running · N issues · audit M warn · P tracked
```
- `N issues` = total anomalies (includes stale_running + lost combined)
- `audit M warn` = from `tasks audit`, usually `lost` type (benign)
- If N issues >> audit M warn: stale_running zombies present (Class B)

```
Heartbeat: Xh (agent_name), ...
```
- All agents should show ≤ 1h heartbeat for a live fleet
- An agent showing 2h+ heartbeat during expected-active hours = session stalled

```
Sessions: N active · default model · P stores
```
- Normal range for this fleet: 30-50 active sessions
- Spike above 60+ may indicate session leak

---

## Safe credential inspection template

Use this exact pattern. Never deviate to print token values.

```python
import json, os, glob
from datetime import datetime, timezone

def inspect_auth_profiles(glob_pattern='~/.openclaw/agents/*/agent/auth-profiles.json'):
    now = datetime.now(timezone.utc).timestamp()
    for p in sorted(glob.glob(os.path.expanduser(glob_pattern))):
        ag = p.split('/agents/')[1].split('/')[0]
        d = json.load(open(p))
        # Schema-only: show profile names and which fields exist
        schema = {k: list(v.keys()) for k, v in d.get('profiles', {}).items()}
        print(f'{ag}: profile keys = {schema}')
        # Only safe scalar: expires timestamp
        for prof_name, prof in d.get('profiles', {}).items():
            if 'expires' in prof:
                exp = prof['expires'] / 1000
                state = 'EXPIRED' if exp < now else 'ok'
                print(f'  {prof_name}: expires {datetime.fromtimestamp(exp, tz=timezone.utc).isoformat()[:16]} [{state}]')

inspect_auth_profiles()
```

If you accidentally read a token value, STOP IMMEDIATELY.
Tell the operator: "A credential value was loaded into context. Rotate before continuing."
