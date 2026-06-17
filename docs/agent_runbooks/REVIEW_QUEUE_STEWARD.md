# review_queue_steward — Operational Runbook

**Agent**: review_queue_steward  
**Mode**: Chat-mode only (no persistent artifacts by design)  
**Cadence**: Daily post-production (18:50 ET)  
**Owner**: signal_lead

---

## Overview

review_queue_steward is a chat-mode agent that triages daily review queues. It analyzes signals flagged by monitoring agents and decides whether each should trigger immediate action or move to a "monitor" bucket for continued observation.

**Key characteristic**: No artifact files written. Freshness checked via `logs/agents_direct/review_queue_steward_*.json` (specialized check in `agent_heartbeat_checks.py`).

---

## Quick Start

### Interactive Invocation
```bash
python3 tools/run_agent_direct.py --agent review_queue_steward
```

### Expected Inputs
The agent consumes:
- Artifact summaries from Lane B signal monitors (price_action_watch, options_watch, ic_health_monitor, etc.)
- Current portfolio state (from `data/snapshots/{date}/portfolio_positions.csv`)
- Historical action outcomes (from postmortem artifacts)

### Expected Outputs
Chat-mode output:
- **Decision summary**: each alert → action vs monitor
- **Risk flags**: any alerts matching known fail patterns
- **Escalation**: alerts requiring immediate operator attention (via Slack/Town bridge)

---

## Operational Context

### Lane B Signal Monitors (Inputs)
These agents produce alerts that review_queue_steward triages:

| Agent | Produces | Triage Decision |
|---|---|---|
| `price_action_watch` | big-move alerts | Action if >3σ move + catalyst window |
| `options_watch` | IV-spike alerts | Monitor if OTM spreads; action if ATM |
| `ic_health_monitor` | signal health warnings | Action if IC trend reversed |
| `catalyst_delta` | new catalyst events | Action if near-term (≤30d) |
| `postmortem` | event resolutions | Monitor; update calibration |

### Triage Logic
For each alert, the agent asks:
1. Is this in my portfolio?
2. Is this near-term (≤30 days) or long-term?
3. Do I have an outstanding position size vs. risk?
4. Does this contradict my recent action on this ticker?

**Outcomes**:
- **Action**: Flag for immediate operator review (17:00–18:00 ET window)
- **Monitor**: Log for next week's review
- **Duplicate**: Merge with earlier alert on same ticker

---

## Dry-Run Mode

To preview triage output without committing:
```bash
# See expected inputs
python3 tools/run_agent_direct.py --agent review_queue_steward --dry-run

# This will:
# 1. Load current Lane B artifacts
# 2. Simulate triage decisions
# 3. Print summary (no Slack message, no Town bridge event)
```

---

## Chat Prompts

### Standard Triage
```
Triage today's Lane B alerts against current portfolio and constraints.
Inputs: price_action_watch, options_watch, ic_health_monitor, catalyst_delta.
For each: Action, Monitor, or Duplicate?
```

### Risk-Focused Triage
```
Which alerts represent the highest portfolio risk?
Focus on: overlap (multiple alerts on same ticker),
near-term catalysts, implied-vs-realized misalignment.
```

### Calibration Review
```
Compare today's triage decisions to last month's.
Are we over-actioning? Under-actioning? Calibration drift?
```

---

## Monitoring & Health Checks

### Heartbeat
Freshness is checked via:
```bash
agents/review_queue_steward/HEARTBEAT.md
logs/agents_direct/review_queue_steward_*.json (latest run timestamp)
```

### Stale Threshold
If no run in past 24 hours (and today is trading day), flag as WARN.

### Common Issues

| Issue | Root Cause | Fix |
|---|---|---|
| No recent log | Agent not invoked at 18:50 ET | Check Hermes cron job `openclaw-fleet-triage daily` |
| Stale artifact refs | Lane B monitors not running | Check `price_action_watch`, `options_watch` logs |
| Empty triage | No alerts produced | Check Lane B coverage; may be a quiet day |

---

## Escalation

If triage output indicates:
- **P0 risk** (overlapping alerts on same ticket + catalyst <7d): Immediate Slack alert to signal_lead
- **Data inconsistency** (alert contradicts rankings): Flag for data_auditor review
- **Calibration drift** (systematic over/under-action): Route to `ops` for review

---

## Support

- **Questions about triage logic**: Contact signal_lead
- **Input artifact issues**: File with data_lead (Lane A owner)
- **Escalation routing**: File with ops (duty_officer)

---

**Last updated**: 2026-06-17
