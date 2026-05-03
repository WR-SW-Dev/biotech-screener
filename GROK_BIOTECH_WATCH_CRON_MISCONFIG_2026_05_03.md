# GROK_BIOTECH_WATCH — Cron Message Misconfiguration

**Status:** Diagnose-only. No file outside this memo was created or modified by this review.
**Author:** External operator (Hermes triage, 2026-05-03 read-only)
**Ruleset id at time of writing:** 2a3e79eb v1.13.0
**Trigger:** Fleet receipt `agents/fleet_steward/memory/2026-05-03_receipt.md`
flagged `grok_biotech_watch — newest=2026-03-30 (34.0d > 1d for cadence=intraday)
STALE_ARTIFACT`. Skill `openclaw-fleet-triage` "known recurring conditions"
section has carried this entry as "chronic stale/dead, deprecate-vs-revive
pending."

The "chronic dead" framing is wrong. The agent is not dead. Its scheduled
invocations succeed, but they run the wrong code path because the cron
message is `HEARTBEAT`, not `SCAN`. This memo isolates the finding and
presents disposition options for the operator.

---

## §1 FACTS

### 1.1 Cron registration

`crontab -l | grep grok_biotech_watch` returns three entries (verified 2026-05-03):

```
0 7  * * 1-5 cd <repo> && source .env 2>/dev/null && python3 tools/run_agent_direct.py --agent grok_biotech_watch --message "HEARTBEAT" >> logs/agents.log 2>&1
0 12 * * 1-5 cd <repo> && source .env 2>/dev/null && python3 tools/run_agent_direct.py --agent grok_biotech_watch --message "HEARTBEAT" >> logs/agents.log 2>&1
0 15 * * 1-5 cd <repo> && source .env 2>/dev/null && python3 tools/run_agent_direct.py --agent grok_biotech_watch --message "HEARTBEAT" >> logs/agents.log 2>&1
```

All three message arguments are the literal string `HEARTBEAT`.

### 1.2 Cron is firing on schedule

`logs/agents_direct/grok_biotech_watch_*.json` contains 3 invocations on
each weekday since at least 2026-04-30, including:

```
logs/agents_direct/grok_biotech_watch_20260501_150523.json   (Fri 15:05 ET)
logs/agents_direct/grok_biotech_watch_20260501_120019.json   (Fri 12:00 ET)
logs/agents_direct/grok_biotech_watch_20260430_150026.json   (Thu 15:00 ET)
```

All three log records: `"status": "success"`. The cron daemon, the agent
runner (`tools/run_agent_direct.py`), and the agent itself are all healthy.

### 1.3 The agent does NOT scan when invoked with HEARTBEAT

The 2026-05-01 15:05 invocation log
(`logs/agents_direct/grok_biotech_watch_20260501_150523.json`) shows the
agent's full response. Verbatim tail:

```
W1 — No artifact written yet for 2026-05-01.
     Market is open. A scan cycle should run soon
     or has not run today.
W2 — No email credentials found (...)
     Alerts will write to artifacts/grok_watch/ but
     will NOT be delivered to dschulz@wakerobin.co.

RECOMMENDATION
  • Trigger a manual scan cycle to produce today's artifact.
  • Set email credentials to re-enable delivery.
  • No xAI or dedup issues — core watch loop is healthy.

Ready for a `SCAN` if you want to kick off the first watch cycle of the day.
```

The agent's HEARTBEAT path is a self-diagnostic: it verifies xAI creds, dedup
state, and email creds, then waits for an explicit `SCAN` message to actually
run a watch cycle. None of the three cron entries ever sends `SCAN`.

### 1.4 The SCAN path works (historical evidence)

`artifacts/grok_watch/` contains:

```
2026-03-31_alerts.md           (10,140 bytes, written 2026-03-30 16:52)
2026-03-31_alerts.json         (126,806 bytes, same time)
dedup_state.json               (10,720 bytes, same time)
```

These are real watch-cycle outputs. The agent's `AGENTS.md` describes the
canonical 7-step daily sequence (build watchlist → query xAI → filter →
classify → enrich → email if HIGH → write artifacts), and the existing
artifacts demonstrate the full path executed at least once. Whatever produced
the 2026-03-30 artifacts was a SCAN-mode invocation, not HEARTBEAT.

### 1.5 Fleet receipt flags this as chronic stale

`agents/fleet_steward/memory/2026-05-03_receipt.md:35-36`:

```
- grok_biotech_watch — newest=2026-03-30 (34.0d > 1d for cadence=intraday)
  - STALE_ARTIFACT: 34.0d since last write (threshold 1d)
```

The receipt's STALE_ARTIFACT proxy reads `artifacts/grok_watch/` mtimes
(latest 2026-03-31). It does not inspect `logs/agents_direct/` invocation
logs, so it can't distinguish "agent never ran" from "agent ran but produced
no artifact this cycle." Both surface as STALE_ARTIFACT.

### 1.6 The skill memorialised the wrong cause

`openclaw-fleet-triage` SKILL.md § "Known recurring conditions":

> production_qa, review_queue_steward, policy_shadow_watch, grok_biotech_watch
> — chronic stale/dead. Operator decision pending on deprecate-vs-revive.

The framing "chronic stale/dead, deprecate-vs-revive" presupposes that
reviving the agent requires a code or schedule restoration. For grok the
restoration is a cron-prompt change. The skill's text would benefit from a
correction once disposition lands.

---

## §2 INFERENCE

### 2.1 Root cause is the cron message string

Facts 1.1, 1.2, 1.3 jointly establish that scheduled invocations succeed
deterministically and the agent's HEARTBEAT path runs as designed. The
agent is not broken. The cron prompt does not invoke the agent's
production work-unit.

### 2.2 The 34-day window matches a HEARTBEAT-only deployment

Last real artifact: 2026-03-30 (Sun) and 2026-03-31 (Mon). Today: 2026-05-03
(Sat). Roughly 34 days of HEARTBEAT-only invocations would account for the
cliff. There is no evidence that anyone reverted a working SCAN cron — more
likely the cron was authored as HEARTBEAT from the start, with the
expectation that an external trigger would fire SCAN messages, and that
external trigger never materialized.

### 2.3 The receipt's "chronic dead" classification is fragile

This is the third agent in 2026-05-03 alone where a fleet-receipt proxy
flagged STALE/FAIL while the underlying agent was demonstrably healthy.
(See triage notes for `bioshort_watch`, `data_auditor` archive_verification,
and `postmortem` memory-write — same shape, different mechanisms.) The
deprecate-vs-revive question presumes the agent is broken; the actual
question for grok is "do you want intraday Grok-based watch alerts or not?"

### 2.4 Email credential gap is real but downstream

Fact 1.3 also surfaces W2: missing `SENDGRID_API_KEY` / `SMTP_PASSWORD` /
`EMAIL_API_KEY`. Even if SCAN cron lands, HIGH alerts will write to disk
but not deliver to `dschulz@wakerobin.co`. This is a separate decision
(provision creds vs. accept disk-only delivery) and should NOT block the
cron-prompt fix.

---

## §3 OPTIONS

### Option A — Replace `HEARTBEAT` with `SCAN` in all three cron entries

Operator edits crontab so all three entries pass `--message "SCAN"`.
Existing schedule preserved (Mon-Fri 7am, 12pm, 3pm ET).

✅ Smallest production touch. Three string changes. No agent code, no
   AGENTS.md, no AGENT_REGISTRY.json, no schema. Reversible by `crontab -e`.
✅ Agent's existing 7-step SCAN flow is documented in `agents/grok_biotech_watch/AGENTS.md`
   and proven by the 2026-03-30 artifacts.
✅ Restores "intraday" cadence the registry already declares
   (`agents/AGENT_REGISTRY.json` shows `cadence: intraday`).
❌ Will produce 3 artifacts/day going forward, growing
   `artifacts/grok_watch/` indefinitely. No retention policy currently exists.
❌ HIGH alerts won't email until 2.4 is also addressed.
❌ xAI API spend resumes (was $0 for 34 days). Unknown whether watchlist size
   changed since last scan.

### Option B — One HEARTBEAT cron + one SCAN cron, midday only

Replace the 7am and 3pm `HEARTBEAT` entries with a single 12pm `SCAN`. Keep
a 7am or end-of-day HEARTBEAT for the credential / dedup self-check.

✅ Restores meaningful watch coverage at one mid-session checkpoint.
✅ Lower xAI spend than Option A (1 scan vs 3).
✅ Preserves the diagnostic value of the HEARTBEAT path.
❌ "Intraday" cadence in registry no longer matches reality (1/day, not 3/day).
   Either downgrade registry cadence or accept the mismatch.
❌ Misses morning-open and afternoon-fade alert windows.

### Option C — Deprecate via AGENT_REGISTRY.json and remove cron entries

Set `agents.grok_biotech_watch.status = "deprecated"`, remove the three cron
lines, leave `artifacts/grok_watch/` for archival.

✅ Eliminates the chronic STALE_ARTIFACT flag from fleet receipts permanently.
✅ Avoids ongoing xAI spend.
✅ Honours the user's stated workflow if Grok-based watch alerts are no longer
   part of the trade plan.
❌ Loses an existing piece of working infrastructure (the SCAN path is real and
   was useful enough to be authored once). Restoring later is non-trivial.
❌ Other agents reference grok signal indirectly via shared dedup_state.json
   — verify no consumers before deprecating.

### (Operator considerations — not a recommendation)

Option A and B both restore function; Option C closes the agent. The choice
between A and B is a rate-of-spend / coverage trade-off. The choice between
[A or B] vs C is a workflow question only the operator can answer (do you
read intraday Grok alerts; do you want them in your day).

---

## §4 WHAT THIS MEMO DOES NOT ANSWER

- Whether the SCAN-mode artifacts being produced today would still be useful;
  the watchlist composition and Grok-API behaviour have shifted in 34 days.
- The exact xAI/Grok API cost per SCAN cycle (no recent invocation to measure).
- Whether `tools/run_agent_direct.py` accepts `SCAN` as a literal message or
  whether the agent's prompt-router expects a different keyword. The 2026-03-30
  artifact existence implies SOME message worked; the exact string is not
  archived in this memo.
- Whether `policy_shadow_watch` and `review_queue_steward` (same fleet-receipt
  cohort, same triage discovery) have analogous cron-prompt issues or genuine
  agent-prompt persistence bugs. Out of scope for this memo. They each need
  their own diagnosis.
- Whether the email-delivery gap (2.4 / W2) is intentional (alerts disabled)
  or an unintentional gap.

---

## §5 NEXT STEP (operator-approved follow-ups, each a separate decision)

1. **Pick disposition (A / B / C).** None of these touches production until
   the operator says so.
2. After A or B is chosen: **draft the crontab change as a 5-step preview-then-apply
   block** per the openclaw-fleet-triage skill's
   "State-changing commands: preview-then-apply contract" (backup → preview
   diff → STOP for review → apply → verify). Operator approves the diff,
   then approves the apply.
3. (Independent) **Decide email-credential disposition** — provision creds
   or accept disk-only delivery. Either is fine; surface the choice in the
   ops digest if not addressed.
4. (Independent) **Decide retention policy** for `artifacts/grok_watch/`
   if Option A or B lands. Currently no rotation; will grow ~2MB/day.
5. (Independent) **Update `openclaw-fleet-triage` skill** § "Known recurring
   conditions" to reflect actual disposition. The "chronic dead" framing
   misled today's triage.
6. (Optional) **Run analogous diagnosis for `policy_shadow_watch` and
   `review_queue_steward`** — same fleet-receipt cohort, but the failure
   shape is different (agent runs full analysis, doesn't persist artifacts).
   Each needs a separate memo if the operator wants them resolved.

---

## §6 PROVENANCE

**Source artifact:** `agents/fleet_steward/memory/2026-05-03_receipt.md` (lines 35-36)

**Cross-checks:**
- `crontab -l` (verified 2026-05-03 ~16:00 ET) — three `--message "HEARTBEAT"` entries
- `logs/agents_direct/grok_biotech_watch_20260501_150523.json` (status=success, full response captured)
- `logs/agents_direct/grok_biotech_watch_20260501_120019.json`, `20260430_150026.json` (analogous)
- `artifacts/grok_watch/` ls — 3 files, all dated 2026-03-30 16:52
- `agents/grok_biotech_watch/AGENTS.md` (lines 1-20) — canonical 7-step SCAN sequence
- `agents/AGENT_REGISTRY.json` — `grok_biotech_watch.status = "active"`, `cadence = "intraday"`
- `service cron status` — Active since 2026-04-30 (daemon healthy)

**Path:line citations for code claims:** none — this memo is a configuration
diagnostic, not a code-bug diagnosis.

**Context memos:**
- `agents/bioshort_watch/memory/2026-05-03_cron_misescalation_issue.md` (similar shape: cron-prompt misconfiguration on the bioshort_watch weekly-brief, fixed today via `openclaw cron edit`)
- skill `openclaw-fleet-triage` SKILL.md (§ "Receipt readings are proxies",
  § "Known recurring conditions", § "Escalate-to-remediation handoff",
  § references/escalate-to-remediation-handoff.md)

**Author:** External operator via Hermes session, 2026-05-03 read-only triage.

**Touched / not touched:**
- This memo file is the only artifact created.
- No edits to `crontab`, `agents/AGENT_REGISTRY.json`, `agents/grok_biotech_watch/*`,
  `tools/run_agent_direct.py`, `tools/agent_heartbeat_checks.py`, `.env`, or any
  other repo file.
- No cron edits, no agent invocations triggered manually, no artifact directories
  created or rotated, no env vars set.
- `~/.openclaw/agents/*/auth-profiles.json` — not read, not inspected; no
  credential touch.
