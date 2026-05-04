---
name: openclaw-agent-scope-audit
description: "Validate SOUL.md/AGENTS.md boundaries, prompt-string configuration, and scope drift for OpenClaw biotech agents. Detects hallucinated-scope risks, cron prompt misconfigs, and registry path drift. Diagnose-only by default."
when_to_use: "Agent behaves unexpectedly, fires its self-diagnostic path instead of its work path, produces outputs outside its stated scope, or fleet triage flags an agent as chronic dead when AGENTS.md/SOUL.md suggest it should be working. Also use when adding a new agent or reviewing a SOUL.md update."
---

# OpenClaw Agent Scope Auditor

For the biotech screener at `/mnt/c/Projects/biotech_screener/biotech-screener`.
Diagnose-only by default.

---

## Hard rules

- Read AGENTS.md and SOUL.md before any analysis. Never claim an agent "should" do X
  without citing the specific file and line that establishes X.
- FACT vs INFERENCE must be separated explicitly.
- Never edit SOUL.md, AGENTS.md, or prompt strings without operator approval.

---

## Failure taxonomy

### Class A — Cron prompt-string misconfig (HEARTBEAT vs SCAN)

**Signature:** An agent that should be doing active work is instead running its
self-diagnostic / heartbeat path. Output looks like status-checking, not actual work.
Agent appears "healthy" in heartbeat checks but produces no real artifacts.

**Confirmed instance:** `grok_biotech_watch` was chronic dead for 34+ days (2026-03-30
to 2026-05-03). Root cause: crontab entries sent `--message "HEARTBEAT"` instead of
`--message "SCAN"`. The agent's router interpreted HEARTBEAT as a self-check and
returned immediately without doing any biotech scanning work.

**Diagnostic recipe:**

```bash
# 1. What message string does the crontab send?
crontab -l | grep <agent_name>
# Look for --message "..." — HEARTBEAT triggers self-check, SCAN triggers work

# 2. What does the agent's AGENTS.md say its work trigger should be?
cat agents/<name>/AGENTS.md | grep -i "message\|trigger\|scan\|heartbeat\|SOUL"

# 3. Check SOUL.md for the routing table
cat agents/<name>/SOUL.md | grep -A 5 -i "HEARTBEAT\|SCAN\|route\|dispatch"

# 4. When did artifacts last write?
ls -lt artifacts/<name>/ | head -5
# If mtime stopped at the same time HEARTBEAT was introduced, timing is causal
```

**Remediation (after operator approval):**
1. Backup crontab first.
2. Change `--message "HEARTBEAT"` to `--message "SCAN"` (or whatever the work trigger is).
3. Preview diff before applying (preview-then-apply contract).
4. Verify at next scheduled run that artifacts are produced.

---

### Class B — Registry path drift (NO_ARTIFACTS false alarm)

**Signature:** Fleet receipt flags agent as `NO_ARTIFACTS` at its declared paths,
but the agent is actually running and writing elsewhere.

**Confirmed instances (2026-05-03):**
- `policy_shadow_watch`: registry declared `artifacts/policy_shadow_watch/` but
  agent writes to `artifacts/policy_shadow/tier_weighted/`
- `review_queue_steward`: registry declared `agents/review_queue_steward/memory/`
  but agent is chat-mode only with no artifact contract (by design per SOUL.md/TOOLS.md)

**Diagnostic recipe:**

```bash
# 1. What does the registry say?
python3 -c "
import json
r = json.load(open('agents/AGENT_REGISTRY.json'))
ag = [a for a in r['agents'] if a['id'] == '<agent_id>'][0]
print('Registry artifact_paths:', ag.get('artifact_paths', []))
print('Registry memory_path:', ag.get('memory_path', ''))
"

# 2. What does AGENTS.md actually say?
cat agents/<name>/AGENTS.md | grep -E "Write|Output|Produce|artifact|memory"

# 3. Where does the agent actually write?
find artifacts/ -maxdepth 3 -name "*<agent_keyword>*" | head -10
find agents/<name>/ -name "*.md" -o -name "*.json" | head -10

# 4. Read the actual check function in agent_heartbeat_checks.py
grep -A 20 "def check_<agent>" tools/agent_heartbeat_checks.py
```

**Resolution:** Update `AGENT_REGISTRY.json` artifact_paths to match actual output
paths. This is a registry bug, not an agent bug.

---

### Class C — Memory-write code bug (STALE_LEDGER proxy error)

**Signature:** Fleet receipt shows `STALE_LEDGER` (memory mtime old) but:
- Artifacts directory has fresh entries
- Invocation logs show recent runs
- The gap between memory mtime and artifact mtime is days or weeks

**Cause:** The agent's memory-write step is broken while its work step is healthy.
The receipt reads memory mtime as the freshness proxy — two different problems
with one symptom in the receipt.

**Confirmed instances:**
- `postmortem`: memory stale 28d (2026-04-03), artifacts fresh through 2026-04-27,
  6 invocations on Apr 30 alone. Memory-write broke at commit `2f45c6a7`.
- `calibration_evidence`: STALE_LEDGER 14d, but artifact files written 2026-05-02
  via weekend catch-up. Memory directory stayed empty.

**Diagnostic recipe:**

```bash
# What does AGENTS.md say the agent WRITES (memory vs artifact)?
grep -E "Write|memory|artifact" agents/<name>/AGENTS.md

# Memory freshness (what receipt sees)
ls -t agents/<name>/memory/*.md | head -3

# Artifact freshness (what the agent actually produces)
ls -lt artifacts/<name>/ | head -5

# Invocation log freshness (did cron fire?)
ls -lt logs/agents_direct/<name>_*.json | head -5

# Three-axis verdict:
# memory-stale + artifacts-fresh + invocations-fresh → code bug in memory-write step
# memory-stale + artifacts-stale + invocations-fresh → agent crashes mid-run
# memory-stale + artifacts-stale + no-invocations  → schedule problem (cliff/crontab)
```

**Resolution:** This is a CODE bug (agent's memory-write step), not infrastructure.
Escalate as a spec ticket / code review, not a cron fix.

---

### Class D — ic_health_monitor path decoupling

**Special case:** `ic_health_monitor` has an empty `agents/ic_health_monitor/memory/`
by design. Its actual deliverable is:
`artifacts/ic_dashboard/<date>_dashboard.json`

Any triage of this agent MUST go to the dashboard artifact, never memory/.
Receipt proxy is misleading for this agent by design.

```bash
ls -lt artifacts/ic_dashboard/ | head -5
```

---

### Class E — Scope drift / hallucinated wet-lab assumptions

**Signature:** An agent produces outputs that reference data, conclusions, or actions
outside its SOUL.md scope boundary. In the biotech context this includes:
- An ops/data agent making clinical efficacy claims
- A fleet monitoring agent proposing portfolio changes
- Any agent inferring wet-lab results from market data

**Diagnostic recipe:**

```bash
# 1. Read SOUL.md scope section
cat agents/<name>/SOUL.md | grep -A 20 -i "scope\|boundary\|NOT\|never\|prohibit"

# 2. Read the agent's most recent output
cat agents/<name>/memory/$(ls -t agents/<name>/memory/ | head -1)

# 3. Flag any claim that references something outside the scope section
# Especially: causation claims, data-layer crossings (e.g. market→clinical),
# or recommendations outside the agent's stated decision surface
```

**Red flags for biotech specifically:**
- Clinical efficacy/safety claims from price/volume data
- Mechanistic drug action claims from catalog/pipeline data
- Patient population inference from trial registry data (AACT/CTGov)
- Regulatory outcome prediction from filing timestamps alone

**Escalation:** Scope violations are HIGH severity. Surface to operator immediately.
Do not attempt auto-remediation.

---

## Pre-audit checklist (run before any agent analysis)

```bash
# 1. Read AGENTS.md — establishes the contract
cat agents/<name>/AGENTS.md

# 2. Read SOUL.md — establishes the scope and routing
cat agents/<name>/SOUL.md

# 3. Read the registry entry
python3 -c "
import json
r = json.load(open('agents/AGENT_REGISTRY.json'))
ag = next((a for a in r['agents'] if a['id'] == '<name>'), None)
print(json.dumps(ag, indent=2))
"

# 4. Check latest memory entry (if any)
ls -t agents/<name>/memory/ | head -3

# 5. Check latest artifact
find artifacts/<name> -maxdepth 2 -type f | head -5
```

---

## Report format

```
AGENT SCOPE AUDIT — <agent_name> — <date>

SCOPE (from SOUL.md:<line>)
  <verbatim scope statement>

FACTS (from files, verbatim)
  ARTIFACT STATE: <fresh/stale/absent — path:mtime>
  MEMORY STATE:   <fresh/stale/absent — path:mtime>
  INVOCATIONS:    <recent/absent — logs/agents_direct/<name>_*.json>
  REGISTRY:       <declared paths vs actual paths — match/mismatch>
  CRON TRIGGER:   <--message "..." value — correct/wrong>

INFERENCE (my reading)
  <class A/B/C/D/E + reasoning>

FINDING
  <HIGH/MEDIUM/LOW severity + specific trigger line if applicable>

RECOMMENDED ACTION
  <single specific action — operator must approve before execution>
```
