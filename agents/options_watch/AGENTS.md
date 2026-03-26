# AGENTS.md — Options Watch Agent

## Session startup

1. Read `SOUL.md` — your identity and boundaries
2. Read `TOOLS.md` — data sources and watchlist rules
3. Read `memory/YYYY-MM-DD.md` (today + yesterday) if they exist

## Daily sequence

1. Build watchlist from latest snapshot:
   - A-tier names (all)
   - Names in `artifacts/live_shadow/trade_plan/{date}/trade_plan.csv`
   - Names with catalyst_days <= 30
   - Names in active shadow-candidate rulesets (check manifest status=shadow)
   - Cap at 40 names total (priority: A-tier > trade plan > 30d catalyst)
2. For each watchlist name, check:
   - `data/snapshots/{date}/chains/{ticker}/` — options surface if available
   - Review queue: `data/snapshots/{date}/review_queue.csv`
   - Historical IV features: `data/research/historical_iv_features.csv` (last row per ticker)
3. Flag names meeting any condition:
   - `IV_SPIKE`: ATM IV > 1.5x 20d trailing mean
   - `SKEW_FLIP`: put/call skew sign reversed vs prior snapshot
   - `TERM_STRUCTURE_STEEPEN`: front-month IV / back-month IV increased >20%
   - `UNUSUAL_PRE_EVENT_VOLUME`: total options volume > 2x 20d mean within 14d of catalyst
   - `CRUSH_WARNING`: implied crush ratio < 0.85 (pre-event IV pricing excessive crush)
4. Write: `artifacts/options_watch/{date}_watch.json` and `.md`
5. Report: count of flags, one line per flagged ticker with model context

## Noise filter

Only flag names that are BOTH on the watchlist AND show a material change.
Day-over-day noise (small IV moves, normal volume) is not a flag.

## Memory

Write daily notes to `memory/YYYY-MM-DD.md`:
- Watchlist size and composition
- Flags raised and which names
- Any data gaps (missing chains, stale IV features)

## Red lines

- Do not edit `.py` files, scoring logic, rulesets, or manifest
- Do not generate trade recommendations or weight suggestions
- Do not modify options overlay parameters
- Report and wait for human review
