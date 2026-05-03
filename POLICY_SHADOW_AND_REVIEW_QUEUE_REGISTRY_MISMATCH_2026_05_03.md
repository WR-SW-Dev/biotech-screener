# POLICY_SHADOW_WATCH + REVIEW_QUEUE_STEWARD — Registry Path Mismatch

**Status:** Diagnose-only. No file outside this memo was created or modified by this review.
**Author:** External operator (Hermes triage, 2026-05-03 read-only)
**Ruleset id at time of writing:** 2a3e79eb v1.13.0
**Trigger:** Fleet receipt `agents/fleet_steward/memory/2026-05-03_receipt.md`
flagged both agents `STALE — no_artifacts at any declared path`. Skill
`openclaw-fleet-triage` "known recurring conditions" section has carried
both as "chronic stale/dead, deprecate-vs-revive pending."

The "chronic dead" framing is wrong for both. Both agents run on schedule
and produce useful output, but the fleet receipt's freshness proxy looks
at declared artifact paths in `agents/AGENT_REGISTRY.json` that don't match
where the work actually lands. This memo isolates both findings (they
share the same root-cause class) and presents disposition options for each.

This memo is the second of three in the 2026-05-03 fleet-receipt cohort
follow-up; see `GROK_BIOTECH_WATCH_CRON_MISCONFIG_2026_05_03.md` for the
cohort context and the cron-prompt fix that landed earlier today.

---

## §1 FACTS

### 1.1 policy_shadow_watch — registry vs. actual artifact path

`agents/AGENT_REGISTRY.json` declares (verified 2026-05-03):

```json
"policy_shadow_watch": {
  "role": "hold-discipline and policy-comparison monitor",
  "category": "portfolio_risk",
  "cadence": "daily_after_production",
  "status": "active",
  "artifact_paths": [
    "agents/policy_shadow_watch/memory/",
    "artifacts/policy_shadow_watch/"
  ],
  ...
}
```

Both declared paths are empty / nonexistent:

```
agents/policy_shadow_watch/memory/   — empty dir (0 files), mtime 2026-03-29
artifacts/policy_shadow_watch/       — does not exist
```

Real artifacts live at a third path:

```
artifacts/policy_shadow/tier_weighted/
  2026-04-14_comparison.{json,md}
  2026-04-15_comparison.{json,md}
  2026-04-16_comparison.{json,md}
  2026-04-24_comparison.{json,md}
  candidate_eval.{json,md}
  history.jsonl                      (910,099 bytes, last write 2026-04-28 08:44)
```

`agents/policy_shadow_watch/TOOLS.md` lines 26-32 explicitly declare this
as the agent's output path:

```
| Daily comparison | artifacts/policy_shadow/tier_weighted/{date}_comparison.json |
| Daily markdown   | artifacts/policy_shadow/tier_weighted/{date}_comparison.md   |
| Rolling history  | artifacts/policy_shadow/tier_weighted/history.jsonl          |
```

Registry entry and TOOLS.md disagree on the canonical output path. The
fleet receipt reads the registry, so it sees zero artifacts.

### 1.2 policy_shadow_watch — agent is functional, not a cron primarily

`agents/policy_shadow_watch/TOOLS.md` line 13:
"Already wired into run_screen.py as a post-pipeline step."

Verified at `run_screen.py`:

```python
try:
    from tools.build_policy_shadow_compare import build_policy_shadow_compare
    _ps = build_policy_shadow_compare(as_of_date=args.as_of_date)
    if "error" not in _ps:
        _pnl = _ps.get("daily_pnl_pct", {})
        logger.info(...)
```

The agent's output is produced by the production pipeline, not by the
agent's cron heartbeat. Cron heartbeats (which DO run — last
`logs/agents_direct/policy_shadow_watch_20260430_180541.json` shows full
analysis succeeding, including real flags `RXDX/AVXL/SNDX oversized
low-tier`) reconstruct from `artifacts/live_shadow/` because the canonical
path was missing during that invocation.

### 1.3 policy_shadow_watch — last canonical artifact 2026-04-24, 9 days ago

The most recent `*_comparison.{json,md}` is dated 2026-04-24. Last
modification on the directory was 2026-04-28 08:44 (touched
`2026-01-20_comparison.md` for some reason). Production has run on
2026-04-29, 4-30, 5-01 since then without writing new comparison files.

Possible explanations (NOT verified — out of scope for read-only audit):
- Build tool conditionally skips on certain dates
- Recent production runs hit the `"error" in _ps` branch and silently fell through
- Build tool has a bug introduced after 2026-04-24

The receipt cannot distinguish among these because it only watches the
wrong path.

### 1.4 review_queue_steward — registry declares one path, memory only

`agents/AGENT_REGISTRY.json`:

```json
"review_queue_steward": {
  "role": "triage daily review queue into immediate vs monitor",
  "category": "signal_monitor",
  "cadence": "daily_after_production",
  "status": "active",
  "artifact_paths": [
    "agents/review_queue_steward/memory/"
  ],
  ...
  "notes": "Crontab: 18:50."
}
```

`agents/review_queue_steward/memory/` is empty (0 files, mtime 2026-03-26).

### 1.5 review_queue_steward — agent is designed not to write artifacts

`agents/review_queue_steward/SOUL.md` § Boundaries:

```
- Read: review_queue.csv, review_queue.md, coverage_quality.json,
  rankings.csv, prior snapshot queue, shadow positions, trade plan
- Write: only to agents/review_queue_steward/memory/
- Never: edit review queue logic, scoring, rulesets, manifest, or code
```

`TOOLS.md` confirms: "This is a read-only agent: no write scope, no artifact output."

The agent's deliverable per AGENTS.md § Step 5 is a one-screen report
formatted into the chat / log:

```
1. Header: date, total queue size, must-look count, monitor count
2. Must Look Now table: ticker | tier | days | action | change_type | reason
3. Notable Changes (new entries, escalations, resolutions)
4. Monitor count only
```

That report exists — verified in
`logs/agents_direct/review_queue_steward_20260430_223043.json` (full triage
including PTGX escalation, CABA new-to-coverage, FATE/ALLO/HALO monitor
classification).

The agent never writes to memory/ because it is explicitly designed not
to. The registry's `artifact_paths: ['agents/review_queue_steward/memory/']`
declares a path that the agent's own SOUL.md and TOOLS.md says it doesn't
produce.

### 1.6 Cron is firing for both

```
crontab -l | grep -E "policy_shadow_watch|review_queue_steward"
5 18 * * 1-5  ... policy_shadow_watch ... HEARTBEAT
50 18 * * 1-5 ... review_queue_steward ... HEARTBEAT
```

Both run weekday evenings. Logs in `logs/agents_direct/` confirm successful
invocations through 2026-04-30 (last weekday before today's Saturday
triage).

### 1.7 The receipt's STALE_ARTIFACT proxy is the same code path for both

`tools/agent_heartbeat_checks.py:605-642` — `check_generic_freshness`
walks each `artifact_paths` entry in the registry, finds newest mtime,
compares to `STALENESS_DAYS_BY_CADENCE[cadence]`. If no path resolves to
a file or non-empty directory, returns `STALE: no artifacts at any
declared path`. Both agents fall through the generic freshness check
because no specialised `check_<name>` exists.

The check is correct given the registry. The registry is wrong given
the agents.

### 1.8 The skill memorialised the wrong cause for both

`openclaw-fleet-triage` SKILL.md § "Known recurring conditions":

> production_qa, review_queue_steward, policy_shadow_watch, grok_biotech_watch
> — chronic stale/dead. Operator decision pending on deprecate-vs-revive.

For grok this was wrong (cron-prompt issue, fixed at
`GROK_BIOTECH_WATCH_CRON_MISCONFIG_2026_05_03.md`).

For review_queue_steward and policy_shadow_watch this is also wrong, but
in different ways:

- **review_queue_steward** does not need a fix — it is working as designed.
  The registry declaration is what's wrong: declaring an artifact path the
  agent's own SOUL.md says it doesn't produce. The fix is on the registry,
  not the agent.
- **policy_shadow_watch** has TWO separate problems entangled in one
  receipt finding: (a) registry path doesn't match TOOLS.md's declared path
  (registry-config); (b) build_policy_shadow_compare may not be running
  cleanly on every production day (no comparison since 4-24 despite three
  weekday production runs since). Fixing (a) reveals the actual size of (b).

---

## §2 INFERENCE

### 2.1 Both findings are registry-vs-reality drift, not agent failures

Facts 1.1-1.7 jointly establish that both agents are running and producing
their actual deliverables (canonical artifacts for policy_shadow_watch
through 4-24; chat-mode reports for review_queue_steward through 4-30).
The fleet receipt's STALE finding measures registry-declared paths, not
agent deliverables. It's a measurement-tool bug, not a measured-agent bug.

This is the third agent today (alongside grok_biotech_watch and
postmortem) where the receipt flagged STALE/FAIL while the underlying
agent was demonstrably healthy. The pattern is consistent: the
deterministic check function reads ONE proxy (path + mtime) and the
actual agent surface area is broader.

### 2.2 The two agents have different right-answers

**policy_shadow_watch** has a real artifact at a real path. The fix is to
align the registry to TOOLS.md. After that alignment:
- The receipt would find `artifacts/policy_shadow/tier_weighted/` newest
  mtime = 2026-04-28 (~5d ago).
- That would still trigger STALE under `cadence=daily_after_production`
  (threshold ~2d), correctly surfacing fact 1.3 as a real freshness issue.
- So registry alignment promotes a hidden, stale, real problem to a
  visible, fixable one. Fixing (a) is a precondition for diagnosing (b).

**review_queue_steward** has no artifact by design. Two valid dispositions:
- Reclassify in the registry as having no artifact_paths and no expected
  freshness check (analogous to `ic_health_monitor` per the skill, which
  the receipt routes to a custom `check_ic_health` rather than generic).
- OR: change the agent design to write a daily summary file that the
  receipt can watch. This is a real product change (the agent deliberately
  doesn't write because the chat-mode report IS the deliverable).

The first preserves the agent-as-designed; the second changes the
contract.

### 2.3 Operator-decision separation

Each disposition involves separate ownership:
- Aligning policy_shadow_watch registry path: data-pipeline owner
  (registry is mechanical; alignment is uncontroversial).
- Diagnosing why build_policy_shadow_compare didn't run since 4-24:
  pipeline owner (separate audit, possibly post-mortem-grade if it's a
  silent-fall-through).
- review_queue_steward registry approach: governance — does the operator
  want a daily summary artifact the screener can audit, or accept
  diagnostic-only chat output as the contract?

These should land as separate commits, NOT bundled.

---

## §3 OPTIONS

### policy_shadow_watch — Option A1: Align registry to TOOLS.md (recommended substrate)

Change `agents/AGENT_REGISTRY.json`:
```json
"policy_shadow_watch": {
  ...
  "artifact_paths": [
    "artifacts/policy_shadow/tier_weighted/"
  ],
  ...
}
```

✅ One-line registry edit. Mechanical, reversible.
✅ Aligns receipt with the agent's own TOOLS.md declaration.
✅ Surfaces the real (currently hidden) freshness issue at fact 1.3.
✅ No change to agent logic, build tool, or run_screen.py wiring.
❌ Will then trigger a real STALE finding on next receipt (last canonical
   artifact is 9 days old). That's a feature, not a bug — but creates
   downstream investigation work.
❌ Doesn't answer why build_policy_shadow_compare hasn't written since 4-24.

### policy_shadow_watch — Option A2: Align registry AND open separate audit

A1 plus: file `POLICY_SHADOW_COMPARE_FRESHNESS_AUDIT_2026_05_03.md`
asking the data-pipeline owner to investigate why no comparison ran
4-25 / 4-29 / 4-30 / 5-01 despite production cycles. Stop after filing.

✅ Same as A1, plus surfaces the second-order problem with explicit
   ownership and traceability.
✅ Doesn't presume the answer.
❌ More overhead than A1.
❌ Diagnose-and-defer; no immediate code change.

### policy_shadow_watch — Option A3: Defer entirely

Leave registry as-is. Continue carrying as STALE in receipt.

✅ Zero touch.
❌ Continues to mask the real freshness issue at 1.3.
❌ Adds noise to fleet receipts indefinitely.

### review_queue_steward — Option B1: Mark in registry as having no artifact, custom check

Edit `agents/AGENT_REGISTRY.json`:
```json
"review_queue_steward": {
  ...
  "artifact_paths": [],
  "no_artifact_check": true,        // NEW field; or use existing skip path
  "freshness_check": "log_invocation",
  ...
  "notes": "..."
}
```

Add a `check_review_queue_steward` function in
`tools/agent_heartbeat_checks.py` that reads `logs/agents_direct/` for
the most recent `review_queue_steward_*.json` invocation log instead of
artifact path mtime.

✅ Receipt becomes correct: the agent's actual signal of liveness is the
   invocation log, and the check would now read it.
✅ Preserves the agent-as-designed contract.
✅ Pattern matches existing `check_ic_health` pattern in the same file.
❌ Code change in `tools/agent_heartbeat_checks.py` — non-trivial.
❌ Adds a new schema field to the registry (`no_artifact_check`) — needs
   a schema_version bump or a different approach.
❌ Sets a precedent: any agent that runs by chat-only output now needs
   a custom check.

### review_queue_steward — Option B2: Change the agent to write a daily summary file

Modify the agent's prompt/AGENTS.md so step 5 (Report) also writes a
machine-readable summary to `agents/review_queue_steward/memory/{date}_triage.json`.
No registry change.

✅ Receipt's existing generic freshness check now finds something.
✅ Provides a long-term audit trail of triage decisions, not just
   chat-bound reports.
❌ Changes the agent's design contract from "diagnostic chat" to
   "diagnostic chat + persisted artifact". That's a product decision,
   not just a config one.
❌ Triage memory accumulates indefinitely; needs retention policy.
❌ Bigger production touch than B1.

### review_queue_steward — Option B3: Mark deprecated

Edit `agents/AGENT_REGISTRY.json` to set `status: "deprecated"`. Remove
or comment the 18:50 cron line.

✅ Fleet receipt drops the agent permanently from STALE.
✅ Zero spend.
❌ The agent IS doing useful triage work (verified by 4-30 invocation log
   showing PTGX escalation + CABA new-to-coverage). Deprecating loses
   that intelligence.
❌ Operator would need to re-run triage manually each day.

### (Operator considerations — not a recommendation)

- The two agents have different right-answers; do NOT bundle.
- For policy_shadow_watch the choice is essentially "fix the measurement,
  then see if the underlying signal is healthy" (A1 or A2) vs "carry the
  noise" (A3). A1 is the cheapest first step and reveals the second-order
  problem cleanly.
- For review_queue_steward the choice is "preserve chat-mode contract"
  (B1) vs "evolve to persisted-artifact contract" (B2) vs "retire the
  agent" (B3). This is a workflow question only the operator can answer:
  do you read the daily review queue triage, do you want a record
  of past triages searchable, is the chat-mode report sufficient.

---

## §4 WHAT THIS MEMO DOES NOT ANSWER

- Why `build_policy_shadow_compare` hasn't written a comparison file since
  2026-04-24 despite production cycles on 4-29, 4-30, 5-01. The
  fall-through clause `if "error" not in _ps` may be silently swallowing
  real errors. This is a separate audit (Option A2 captures the handoff).
- Whether other agents in `AGENT_REGISTRY.json` have analogous registry
  vs. actual-output mismatches. The two studied here may be the tip; a
  registry sweep would surface others.
- Whether `STALENESS_DAYS_BY_CADENCE[daily_after_production]` is set to a
  value that distinguishes Mon-Fri-only production from continuous-cadence
  agents. (Today's RED-on-Saturday triage is partly attributable to that.)
- Whether the proposed Option B1 schema field `no_artifact_check` is
  consistent with the registry's existing `schema_version` and convention.
  May need a different mechanism (e.g. an explicit `check_function` field).

---

## §5 NEXT STEP (operator-approved follow-ups, each a separate decision)

1. **Pick disposition for policy_shadow_watch (A1 / A2 / A3).** Each is a
   separate edit; A1 is the prerequisite for A2.
2. **Pick disposition for review_queue_steward (B1 / B2 / B3).**
3. After A1 or A2 lands: **draft the `agents/AGENT_REGISTRY.json` edit as
   a 5-step preview-then-apply block** (backup → preview diff → STOP →
   apply → verify) per skill's state-changing-commands contract.
4. After B1/B2/B3 lands: **draft the corresponding edit** in the same
   pattern.
5. (Independent) **Update `openclaw-fleet-triage` skill** § "Known recurring
   conditions" to reflect actual disposition for both agents. The "chronic
   dead" framing has now been disproven for three of the four agents in
   that list (grok, policy_shadow_watch, review_queue_steward); only
   `production_qa` remains under that label.
6. (Optional) **Audit `STALENESS_DAYS_BY_CADENCE`** in
   `tools/agent_heartbeat_checks.py` for Mon-Fri-only-production
   agents. The daily_after_production cadence is currently triggering
   STALE on weekends, contributing to today's spurious RED.
7. (Optional) **Sweep `AGENT_REGISTRY.json`** for other path mismatches.
   Prioritise agents that have ever appeared in fleet-receipt STALE/FAIL
   lists.

---

## §6 PROVENANCE

**Source artifact:** `agents/fleet_steward/memory/2026-05-03_receipt.md` (lines 42-43, 46-47)

**Cross-checks:**

For policy_shadow_watch:
- `agents/AGENT_REGISTRY.json` (artifact_paths declaration)
- `agents/policy_shadow_watch/TOOLS.md:26-32` (canonical artifact path)
- `agents/policy_shadow_watch/SOUL.md` (write-scope declaration)
- `artifacts/policy_shadow/tier_weighted/` ls (4-14 / 4-15 / 4-16 / 4-24
  comparisons; history.jsonl 910K, last write 4-28 08:44)
- `agents/policy_shadow_watch/memory/` ls — empty
- `artifacts/policy_shadow_watch/` — does not exist
- `run_screen.py` (`build_policy_shadow_compare` import + call)
- `logs/agents_direct/policy_shadow_watch_20260430_180541.json` (status=success,
  full RXDX/AVXL/SNDX flag analysis)

For review_queue_steward:
- `agents/AGENT_REGISTRY.json` (artifact_paths declaration, single path)
- `agents/review_queue_steward/AGENTS.md` (canonical step 5 report shape)
- `agents/review_queue_steward/SOUL.md` § Boundaries (write-scope)
- `agents/review_queue_steward/TOOLS.md` ("This is a read-only agent:
  no write scope, no artifact output")
- `agents/review_queue_steward/memory/` ls — empty
- `logs/agents_direct/review_queue_steward_20260430_223043.json`
  (status=success, full triage including PTGX escalation, CABA new-to-coverage,
  FATE/ALLO/HALO monitor classification)

For check function:
- `tools/agent_heartbeat_checks.py:605-642` (`check_generic_freshness`)
- `tools/agent_heartbeat_checks.py:69-541` (specialised check_<name>
  functions; review_queue_steward and policy_shadow_watch fall through
  to generic)

**Path:line citations for code claims:**
- `tools/agent_heartbeat_checks.py:628` — `STALE: no_artifacts at any declared path`
- `tools/agent_heartbeat_checks.py:609` — `paths = entry.get("artifact_paths", [])`

**Context memos:**
- `GROK_BIOTECH_WATCH_CRON_MISCONFIG_2026_05_03.md` (sister memo, same
  fleet-receipt cohort, different mechanism)
- `agents/bioshort_watch/memory/2026-05-03_cron_misescalation_issue.md`
  (analogous registry-vs-reality drift in a 4th agent)
- skill `openclaw-fleet-triage` SKILL.md (§ "Receipt readings are proxies",
  § "Receipt mtime ≠ agent health", § "Memory-mtime false-stale is COMMON")

**Author:** External operator via Hermes session, 2026-05-03 read-only triage.

**Touched / not touched:**
- This memo file is the only artifact created.
- No edits to `agents/AGENT_REGISTRY.json`, any `agents/*/SOUL.md`,
  `AGENTS.md`, `TOOLS.md`, `tools/agent_heartbeat_checks.py`,
  `tools/build_policy_shadow_compare.py`, `run_screen.py`, `crontab`,
  or any other repo file.
- No cron edits, no build-tool invocations, no agent invocations.
- No credential touch.
