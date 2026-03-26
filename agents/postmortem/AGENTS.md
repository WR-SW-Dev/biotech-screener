# AGENTS.md — Postmortem Agent

## Session startup

1. Read `SOUL.md` — your identity and boundaries
2. Read `TOOLS.md` — data sources and resolution criteria
3. Read `memory/YYYY-MM-DD.md` (today + yesterday) if they exist

## Daily sequence

1. Identify resolved catalysts:
   - Read latest rankings.csv: find names where catalyst_days <= 0 or catalyst_days was <= 3 in prior snapshot
   - Cross-reference with prior snapshot to detect events that just passed
   - Only process names not already captured in `artifacts/postmortem/`
2. For each resolved name, capture:
   - **Pre-event state** (from the snapshot closest to but before the event):
     - ticker, actionable_rank, tier_dev, size_band, target_weight_pct
     - catalyst_days, catalyst_mode, catalyst_family, catalyst_event_type, catalyst_source
     - is_hard_catalyst, confidence_overall, mom_state
   - **Model context**:
     - ruleset_id (from metadata.json)
     - in_shadow_portfolio (bool)
     - in_trade_plan (bool)
     - readiness_verdict at the time
   - **Post-event outcome** (from price history, T+1 through T+5 if available):
     - return_t1, return_t3, return_t5 (vs prior close)
     - excess_vs_xbi_t1, excess_vs_xbi_t3, excess_vs_xbi_t5
     - abs_gap (if available from event_move_table.json)
3. Write: `artifacts/postmortem/{date}/{ticker}.json` and `{ticker}.md`
4. Report: count of new postmortems, ticker list, any data gaps

## Resolution criteria

A catalyst is "resolved" when:
- Its event date has passed (catalyst_days went from positive to zero/negative)
- At least T+3 trading days of price data are available
- It has not already been captured in artifacts/postmortem/

## Memory

Write daily notes to `memory/YYYY-MM-DD.md`:
- Names resolved today
- Data gaps (missing price data, missing pre-event snapshot)
- Running count of total postmortems captured

## Red lines

- Do not edit `.py` files, scoring logic, rulesets, or manifest
- Do not modify signal evidence or promotion battery inputs
- Do not judge model quality — only record facts
- Do not extrapolate or predict future outcomes
