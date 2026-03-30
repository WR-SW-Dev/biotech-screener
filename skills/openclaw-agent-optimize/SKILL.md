# OpenClaw Agent Optimization

Tune OpenClaw workspaces for cost-aware routing, parallel-first delegation,
and lean context. Source: clawhub.ai/phenomenoner/openclaw-agent-optimize

## Default Posture

This skill is **advisory first**. It produces:
- audit → options → recommended plan → exact patch → rollback → verification
- No persistent mutations without explicit approval.

## Quick Start

### 1) Full audit (safe, no changes)
> Audit my OpenClaw setup for cost, reliability, and context bloat. Output a
> prioritized plan with rollback notes. Do NOT apply changes.

### 2) Context bloat / transcript noise
> My OpenClaw context is bloating. Identify the top offenders (tools, crons,
> bootstrap files, skills) and propose the smallest reversible fixes first.

### 3) Model routing / delegation posture
> Propose a model routing plan for (a) coding/engineering, (b) short
> notifications, (c) reasoning-heavy research. Include config patch + rollback.

## What Good Output Looks Like

- Executive summary
- Top drivers (cost, context, reliability, operator friction)
- Options A/B/C with tradeoffs
- Recommended plan (smallest safe change first)
- Exact proposals + rollback + verify

## Safety Contract

- Do not mutate persistent settings without explicit approval.
- Do not create/update/remove cron jobs without explicit approval.
- If optimization reduces monitoring coverage, present options and require choice.
- Before any approved change, show:
  1. Exact change
  2. Expected impact
  3. Rollback plan
  4. Post-change verification

## High-ROI Optimization Levers

### 1) Output discipline for automation
Make maintenance loops truly silent on success. Only surface errors and
state changes. Suppress verbose success output from crons/heartbeats.

### 2) Separate work from notification
Do the work quietly; notify out-of-band with a short human receipt.
Keep interactive context lean.

### 3) Bootstrap discipline
Keep always-injected files short and load-bearing only. Move long runbooks
into `references/` or adjacent notes. SKILL.md should be concise; detail
goes in reference files.

### 4) Ambient specialist surface reduction
A common hidden tax is too many always-visible specialist skills.
- Prefer on-demand worker/subagent usage
- Do not keep specialists permanently ambient in main-chat prompt surface
- Trim ambient skills before touching tool surface

### 5) Measure optimizations authoritatively
Prefer fresh-session `/context json` or equivalent receipts over "feels better."
High-signal fields:
- `eligible skills` / `skills.promptChars`
- `projectContextChars`
- `systemPrompt.chars`
- `promptTokens`

### 6) Verification-first ops hygiene
After any approved optimization, verify:
- Core chat still works
- Recall/behavior did not degrade
- New session actually picks up the change
- Rollback path is proven, not theoretical

## Audit Workflow

1. Audit rules + memory: keep restart-critical facts only
2. Audit skill surface: trim ambient specialists before touching tool surface
3. Audit transcripts/noise: silence cron and heartbeat success paths
4. Audit model routing and delegation posture
5. Recommend the smallest viable change first
6. Verify on a new session when skill/bootstrap snapshotting exists

## Notes

- Some runtimes snapshot skills/config per session — start new session after changes
- Prefer short `SKILL.md` + `references/` for long runbooks
- If context bloat is the main complaint, audit ambient skills first
