# AGENTS.md — Catalyst Delta Agent

## Session startup

1. Read `SOUL.md` — your identity and boundaries
2. Read `TOOLS.md` — commands and data sources
3. Read `memory/YYYY-MM-DD.md` (today + yesterday) if they exist

## Daily sequence

1. Identify today's date and the latest snapshot date
2. Load prior delta: `artifacts/catalyst_delta/{prior_date}_delta.json`
3. Compare current event artifacts against prior:
   - `data/snapshots/{date}/catalyst_source_mix.json`
   - `data/snapshots/{date}/catalyst_shadow_metrics.json`
   - Cache state in `cache/ctgov/`, `cache/sec_8k/`
4. For each changed event, join to model context:
   - `data/snapshots/{date}/rankings.csv` → tier, rank, catalyst_days, is_hard
   - `artifacts/live_shadow/positions/{date}.json` → in shadow?
   - `artifacts/live_shadow/trade_plan/{date}/trade_plan.csv` → in trade plan?
5. Classify each change with a structured code
6. Write delta to `artifacts/catalyst_delta/{date}_delta.json` and `.md`
7. Report: count of changes by code, top 5 most impactful (A/B tier or <=30d)

## Noise filter

Only surface names that meet at least one:
- A or B tier in current rankings
- Catalyst <=30 days away
- Source family changed (hard→soft or soft→hard)
- In the active shadow portfolio or trade plan

## Memory

Write daily notes to `memory/YYYY-MM-DD.md`. Keep it concise:
- Number of changes detected, by code
- Names that crossed the noise filter
- Any source-level anomalies (e.g., SEC feed went dark)

## Red lines

- Do not edit `.py` files, scoring logic, rulesets, or manifest
- Do not `git push`, `git commit`, or modify tracked files
- Do not change event classifications or source priorities
- When in doubt, report the event change and wait for human decision
