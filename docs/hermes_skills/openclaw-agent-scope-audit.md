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

### Review/runtime patterns reference

For code-level review of OpenClaw agent launchers, heartbeat checks, post-snapshot supervisors, and ops_supervisor anomaly carry-forward, see `references/openclaw-agent-runtime-monitoring-patterns.md`. It captures regression-test shapes for: nonzero process exits on agent failure, collision-resistant direct logs, terminal-unsupervised agent handling, embedded-date parsing, CSV header handling, complete done predicates, and exact anomaly identity.

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

**SCAN fix is necessary but not sufficient for grok_biotech_watch.**
Confirmed 2026-05-04: after applying the SCAN fix to the crontab, the agent still
produced no artifacts. Root cause was a second, deeper issue: `run_agent_direct.py`
(the launcher used by the crontab) is a plain Anthropic SDK text call with NO tool
execution. The agent's bash commands in its response text never actually run, so
`env | grep XAI` returns nothing regardless of whether `XAI_API_KEY` is in `.env`.

The SCAN fix resolves the routing (agent now enters work path, not heartbeat path).
But for agents that need real bash/API execution (grok_biotech_watch calls the xAI
Grok API via curl/Python), the only real fixes are:
  A. Wire through OpenClaw gateway (provides real bash tooling)
  B. Replace the LLM agent with a dedicated wrapper script for the API call

See `openclaw-data-pipeline-debug` Class F for the full diagnostic and resolution options.

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
# 1. What does the registry say? (schema-tolerant: agents can be list[str], list[dict], or dict)
python3 - <<'PY'
import json
r = json.load(open('agents/AGENT_REGISTRY.json'))
raw = r.get('agents', [])
agent_id = '<agent_id>'

def normalize(raw_agents):
    out = []
    if isinstance(raw_agents, dict):
        for k, v in raw_agents.items():
            if isinstance(v, dict):
                d = dict(v)
                d.setdefault('id', k)
                out.append(d)
    elif isinstance(raw_agents, list):
        for item in raw_agents:
            if isinstance(item, dict):
                out.append(item)
            elif isinstance(item, str):
                out.append({'id': item})
    return out

agents = normalize(raw)
ag = next((a for a in agents if a.get('id') == agent_id), None)
print('Registry found:', ag is not None)
print('Registry artifact_paths:', (ag or {}).get('artifact_paths', []))
print('Registry memory_path:', (ag or {}).get('memory_path', ''))
PY

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
- `bioshort_watch`: confirmed 2026-06-17 — mem_age=45d (last memory 2026-05-03),
  art_age=1d (artifacts/bioshort_watch/latest_status.json fresh Jun 16). Gap=43d.
  Memory-write step broken; artifacts fresh via pipeline.
- `qa`: confirmed 2026-06-17 — memory frozen since 2026-05-05 (43d stale).
  QA artifact (artifacts/production_qa/<date>_report.md) fresh daily. Same pattern
  as event_analyst regression — memory-write step broken while artifact pipeline healthy.

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

### Class G — Dead schema field with phantom producers (spec-076 audit pattern)

**Signature:** A column present in `SNAPSHOT_COLUMNS` tuple and written in `run_screen.py`
always emits an empty string. No consumer reads it. No active Python file except the
definition pair references it.

**Confirmed instance (2026-05-06, commit `ff4b7c64`):** `catalyst_source_filed_at` in
`run_screen.py` + `run_screen_columns.py`. The field had no producer since Module 3 was
archived; the write site was always `""`. No downstream consumer. Safe to cut.

**Diagnostic recipe (safe read-only schema audit):**

```bash
# 1. Find all column-write sites in run_screen.py
grep -n 'catalyst_source_filed_at\|<field_name>' run_screen.py | head -20

# 2. Check if the write site always emits empty
grep -n '"<field_name>"' run_screen.py
# If it's row["field"] = "" with no conditional logic -> always empty

# 3. Confirm no consumer reads it
grep -rn '<field_name>' --include="*.py" . | grep -v 'run_screen_columns.py\|run_screen.py'
# If zero results -> no consumers; safe to list as dead

# 4. Confirm it's in the column spec (adds it to every output CSV)
grep '<field_name>' run_screen_columns.py
```

**Classification for the spec-076 audit (or equivalent):**
- `write_site_always_empty AND zero_python_consumers` → **SAFE TO CUT** immediately
- `write_site_sometimes_populated AND zero_python_consumers` → **VERIFY artifact consumers first** (CSV readers, dashboard, external tools)
- `any_python_consumer` → **DO NOT CUT** without a migration plan

**Governance note:** Dead schema field pruning is housekeeping, NOT a governance event.
No Spec rerun needed. Commit prefix: `chore:`. Always confirm with `grep -rn` before cutting —
the field may be referenced in downstream artifacts that parse raw CSV.

**Audit trigger:** Run this scan after any module archival or large refactor. Spec-076
was the first formal "safe-to-cut" audit for the biotech screener (2026-05-06);
the audit doc is at `specs/changes/spec_076_schema_prune_audit_2026_05_06.md`.

When the agent-scope-table or agent-registry-reference files are >2 weeks old,
or after a batch of agent additions/retirements, run the 3-subagent parallel
indexing recipe in `references/bulk-indexing-recipe.md`. Produces fresh versions
of both reference files in one ~9-minute parallel run.

---

### Class F — Stale ruleset ID in SOUL.md (scope drift from promotions)

**Signature:** Agent's SOUL.md contains a hardcoded `Active ruleset:` line referencing
an old ruleset ID. This is cosmetic (agents don't enforce the ruleset), but it means
every future session reading the SOUL.md gets a wrong mental model of production state.

**Confirmed instance (2026-05-04):** After promoting ruleset 2a3e79eb → 622edb77
(v1.14.0), `grok_biotech_watch/SOUL.md` still contained:
```
## Active ruleset
ID: `2a3e79eb` (v1.13.0). Read-only reference — do not modify.
```

**Detection:** After any ruleset promotion, run:
```bash
grep -r "ruleset\|2a3e79eb\|v1\.1[0-9]" agents/*/SOUL.md | grep -v "^#" | head -20
```
Any match not pointing to the current active ID is stale.

**Remediation:** Update the SOUL.md Active ruleset section to the new ID.
Not production-critical — agents don't read their own SOUL.md at runtime —
but creates confusion in triage and audit sessions. Fix in the same commit
series as the ruleset promotion.

**Add to ruleset promotion checklist:**
- [ ] grep agents/*/SOUL.md for old ruleset ID, update any found

**Safe edit method for batch SOUL.md updates (prevents diff blowups):**
- Avoid round-tripping files through readers that inject line-number prefixes.
- Preserve file newline behavior when writing (no implicit normalization).
- After insertion, run `git diff --stat` immediately.
  - Expected for this class of doc-only change: small `+`-only deltas (for this ruleset block, ~`+5` per file).
  - If you see large insert/delete churn, abort and restore files before retrying with newline-preserving direct file I/O.
- Re-validate after patch:
  1. every registry agent still has `AGENTS.md` + `SOUL.md`
  2. no registry agent is missing `## Active ruleset` + current ID

---

### Class H — Cron task ruleset ID mismatch (cron parameter layer, not SOUL.md)

**Signature:** Agent's SOUL.md correctly references the current active ruleset ID, but
the CRON TASK that triggers the agent's heartbeat or diagnostic run passes a DIFFERENT
(stale) ruleset ID as a command-line parameter. The agent's LLM-driven runs use the
correct ID from SOUL.md, but the cron-triggered automated checks compare against the
wrong baseline.

**Confirmed instance (2026-06-17):** Sentinel's SOUL.md correctly references
`8887576e` (v1.14.0). However, the sentinel heartbeat cron task passes `2a3e79eb`
(v1.13.0, retired 2026-05-04) as its ruleset parameter. This means sentinel's
cron-triggered drift checks anchor against the old ruleset, while the LLM-driven
sentinel memory notes (which read SOUL.md) use the correct ID. Day 9+ of mismatch.

**How this differs from Class F:** Class F covers stale ruleset IDs in SOUL.md itself.
This class covers the case where SOUL.md is CORRECT but a separate cron task parameter
is WRONG. The re-anchor procedure (updating SOUL.md in sentinel, catalyst_delta,
shadow_monitor) does not catch this because it only patches the SOUL.md files, not the
cron task parameters.

**Diagnostic recipe:**

```bash
# 1. Verify SOUL.md is correct (this will show the RIGHT ID)
grep -n 'ID:' agents/<name>/SOUL.md | head -3

# 2. Check the cron task parameters (this is where the mismatch hides)
# For Hermes cron jobs, use mcp_cronjob action='list' and inspect the prompt
# For Linux crontab:
crontab -l | grep <agent_name>
# Look for --ruleset or similar parameter in the command

# 3. Check the agent's memory for notes about the mismatch
grep -r 'ruleset.*mismatch\|cron.*reference\|wrong.*ruleset' agents/<name>/memory/ | head -5

# 4. Compare: SOUL.md ID vs cron parameter ID vs manifest active ID
grep -A4 '"status": "active"' production_data/decision_rulesets/manifest.json | grep '"id"'
```

**Resolution:**
1. Identify the cron task (Hermes or Linux) that passes the stale ruleset ID.
2. Update the parameter to the current active ruleset ID from the manifest.
3. For Hermes cron jobs: `mcp_cronjob action='update'` with corrected prompt.
4. For Linux crontab: use the preview-then-apply contract.
5. Verify on next scheduled run that the agent uses the correct ID.

**Add to ruleset promotion checklist:**
- [ ] grep agents/*/SOUL.md for old ruleset ID, update any found (existing step)
- [ ] grep crontab -l AND mcp_cronjob list for old ruleset ID in task parameters (NEW step)

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

## All-agent code review expansion

When the user asks to review "all OpenClaw agents" or the fleet's agent code,
expand beyond one agent's SOUL/AGENTS files. Review contracts, shared runtime
launchers, heartbeat/supervisor code, and data-producing scripts referenced by
TOOLS.md. Use `references/openclaw-all-agent-code-review.md` for the checklist
and session-derived pitfalls.

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
