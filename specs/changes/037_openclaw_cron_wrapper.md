# Change Spec: Use OpenClaw Cron as Wrapper Around Claude Jobs

**Status**: IMPLEMENTED (Phase 1 + Phase 2)
**Author**: dschulz
**Date**: 2026-03-30
**Ruleset impact**: NO
**Type**: Operator workflow / delivery refinement
**Scope**: Scheduling, execution mode, and delivery only

---

## Objective

Refactor the three existing scheduled Claude/OpenClaw jobs so each is an
OpenClaw Cron-managed, delivery-first job that runs in an isolated session
with light context, returns a compact verdict instead of a full transcript,
retries automatically on transient failures, and deep-links the operator to
the dashboard or artifact for follow-up.

## Current Jobs

| Job | Schedule | Role |
|-----|----------|------|
| daily-production-run | 5:30 PM ET weekdays | Full pipeline summary |
| weekly-bioshort-and-hedge | Saturday | Hedge/watch summary |
| weekly-policy-shadow-review | Friday | Governance review of Spec 035 |

## Design Principles

1. **Cron owns scheduling and delivery** — schedule, retry, isolation, delivery channel
2. **Claude owns reasoning** — interprets artifacts, summarizes, issues verdicts
3. **Isolated + light-context by default** — no full workspace bootstrap for artifact-only jobs
4. **Delivery-first** — `--announce` mode, compact verdict, not raw transcript

## Delivery Contract

Every cron job produces:

1. Short verdict (one line)
2. 2-5 supporting metrics
3. One deep link / artifact pointer
4. Status class: `OK` | `WARN` | `ACTION REQUIRED` | `NO DATA` | `FAIL`

Content cap: subject line verdict + max 5 bullets + 1 link.

## Job Definitions

### A. Daily Production Brief

```bash
openclaw cron add \
  --name "daily-production-brief" \
  --cron "37 17 * * 1-5" \
  --session isolated \
  --light-context \
  --announce \
  --message "Summarize the latest daily production artifacts. Return only status, top metrics, and dashboard link."
```

**Template**: `DAILY RUN: OK/WARN/FAIL` + snapshot date + ruleset health +
policy candidate verdict + bioshort alert level + notable alert count + link

### B. Weekly Bioshort Brief

```bash
openclaw cron add \
  --name "weekly-bioshort-brief" \
  --cron "13 18 * * 6" \
  --session isolated \
  --light-context \
  --announce \
  --message "Summarize the latest bioshort watch and hedge status. Return verdict, key changes, and report link."
```

**Template**: `BIOSHORT: HEDGE NOW/HOLD/NO ACTION` + carry + DTE winner +
source quality + changed since last week + link

### C. Weekly Policy Review

```bash
openclaw cron add \
  --name "weekly-policy-review" \
  --cron "43 18 * * 5" \
  --session isolated \
  --light-context \
  --announce \
  --message "Review the latest policy shadow and candidate evaluation. Return verdict, four gates, and governance recommendation."
```

**Template**: `POLICY CANDIDATE: PROMISING/NEEDS_MORE/REJECT` + net return
delta + win rate + overlap stability + excluded names count + governance note

## Error Behavior

- OpenClaw retry backoff: 30s -> 1m -> 5m -> 15m -> 60m
- Degraded messages: `FAIL: production run could not summarize` /
  `NO DATA: artifact missing` / `WARN: stale artifact`

## Rollout Plan

**Phase 1**: Normalize the three live jobs (daily production, weekly bioshort, weekly policy)
**Phase 2**: Add wrapper to Grok biotech watch digest, dashboard validation ping, ops digest
**Phase 3**: Channel-specific formatting once primary delivery channel is chosen

## Non-Goals

- No change to model logic, ranking, scoring, or rulesets
- No new signal-source work
- No dashboard rewrite
- No replacement of existing local scripts
- No migration away from Claude as the main reasoning layer

## Acceptance Criteria

1. Each scheduled job sends a compact verdict-first message, not a transcript
2. Artifact-only jobs run as isolated + light-context
3. Retry is OpenClaw Cron-managed, not custom script loops
4. Delivery is stable across success, missing artifact, stale artifact, and transient failure
5. Manual log inspection becomes optional
