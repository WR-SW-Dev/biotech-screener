# Agent Scope Table — All 30 Agents
Generated from SOUL.md sweep 2026-05-04. Update when SOUL.md files change.

## Trigger note
All agents use `--message "HEARTBEAT"` as the universal work trigger EXCEPT:
- `grok_biotech_watch`: uses `--message "SCAN"` (fixed 2026-05-03, was HEARTBEAT which fired self-diagnostic only)
- `ops_supervisor`: HEARTBEAT explicitly named in AGENTS.md
- `intraday_mover_watch`: not yet in OpenClaw cron (Phase 1.5 pending)
- `shadow_watch`: not wired (status=shadow)
- `company_news_ingest`: DEPRECATED, no cron

---

## Scope + Prohibitions

| agent_id | scope_summary | work_trigger | key_prohibitions |
|---|---|---|---|
| aact_trial_ingest | Bulk-ingest AACT clinical trial snapshots, normalize, detect deltas | HEARTBEAT (weekly) | No clinical outcome judgments, no rankings/scoring edits, no overwriting historical snapshots |
| bioshort_watch | Weekly hedge governance monitor; detects verdict/structure/carry/Greek changes | HEARTBEAT (Fri) | No edits to hedge report logic, decision engine, rulesets, execution scripts |
| biotech_news_digest | DEPRECATED — digest absorbed by herald (`scripts/build_news_digest.py`) | None | N/A |
| calibration | Run ruleset sweeps/holdout machinery, recommend PROMOTE/HOLD/REJECT | HEARTBEAT (weekly) | No editing rulesets/manifest/scoring code/production_data, no running promote_ruleset.py |
| calibration_evidence | Read-only post-event evidence builder; signal contribution + calibration | HEARTBEAT (weekly) | No weight change recommendations, no writing to promotion battery, no causal claims |
| catalyst_delta | Detect new/changed/reclassified catalyst events since last run | HEARTBEAT (18:20) | No scoring/ruleset/manifest edits, no changing catalyst priorities, no git push |
| company_news_ingest | DEPRECATED — absorbed by herald | None | N/A |
| crt_resolution_watcher | Monitor for new CRT resolutions, update join table + hit rates | HEARTBEAT (18:00) | No asymmetry score weight edits, no adjudicating ambiguous outcomes, no overriding resolutions |
| ctgov_poller | Daily CT.gov polling, diff vs cached trials, classify material transitions | HEARTBEAT (14:30) | No modifying production trial_records cache, no clinical judgment calls, no trade recommendations |
| data_auditor | Read-only integrity watchdog: archive, IPO consistency, PIT freshness, price gaps | HEARTBEAT (daily + Sat) | No editing .py files, no modifying/deleting data files, no bypassing checks |
| earnings_calendar_sync | Fetch earnings dates, sync to Outlook calendar via Microsoft Graph | HEARTBEAT (daily premarket) | No scoring/ruleset edits, no mass-deleting Outlook events on empty yfinance return, no fabricating dates |
| event_analyst | Aggregate postmortem facts, compute hit rates/returns by category | HEARTBEAT (18:55 weekdays) | No signal promotion/demotion, no causal claims, no trade recommendations |
| fleet_steward | Control-plane fleet health; artifact freshness checks, daily receipt | HEARTBEAT (daily) | No editing other agents' SOUL.md/IDENTITY.md, no cron/gateway changes, no executing production steps |
| grok_biotech_watch | Watchlist-scoped xAI Grok search monitor with email alerting | **SCAN** (not HEARTBEAT) | No modifying rankings/scoring/decision engine, no feeding results into scoring pipeline, max 5 emails/hr |
| herald | Canonical biotech news agent: fetch, dedupe, classify, 3x daily digest + email | Cron fetch 14:35; `build_news_digest` 3x daily | No rankings/scoring edits, no trade recommendations, no feeding into scoring pipeline |
| ic_health_monitor | Read-only signal health watchdog; rolling IC trends, ALERT/WARN flags | HEARTBEAT (daily) | No editing scoring logic/rulesets/decision engine, no weight change recommendations |
| intraday_mover_watch | 15-min-delayed intraday mover monitor; absolute + XBI-relative moves | Not wired yet | No trade recommendations, no scoring/ranker/ruleset edits, no self-registering cron |
| ops | Daily production operator: runs pipeline, reports NEW/RESOLVED/UNCHANGED | HEARTBEAT (17:00) | No scoring/decision engine/ruleset edits, no git push, no deleting snapshots |
| ops_supervisor | Read-only triage above heartbeat; single daily GREEN/YELLOW/ORANGE/RED verdict | HEARTBEAT (20:30) | No editing production data, no auto-fixing anomalies, no restarting agents |
| options_watch | Post-packet options surface monitor; IV ramps, surface moves, event premiums | HEARTBEAT (18:40) | No scoring/ruleset/options overlay edits, no trade recommendations, no auto-promoting names |
| policy_shadow_watch | Read-only portfolio construction monitor; flags oversized holds + headwinds | HEARTBEAT (daily) | No modifying positions/rankings/weights/execution scripts, no trade recommendations |
| postmortem | Capture structured JSON evidence when catalysts resolve | HEARTBEAT (18:35) | No scoring/ruleset edits, no drawing model-quality conclusions, no predicting future outcomes |
| price_action_watch | Daily digest of big moves, RVOL spikes, IV ramps/crushes, divergences | HEARTBEAT (18:30) | No trade recommendations, no scoring/portfolio policy edits, no auto-escalating to review queue |
| production_qa | Post-production codebase reviewer: snapshot completeness, lint, schema validation | HEARTBEAT (daily) | No editing scoring logic/rulesets/portfolio policy, no git commit/push, no modifying snapshot files |
| qa | Regression-triage and contract-test runner; classifies failures by bucket | HEARTBEAT (on-demand) | No editing production code, no auto-updating golden fixtures, no bypassing failing checks |
| review_queue_steward | Daily review queue triager; NEW/ESCALATED/DE-ESCALATED classification | HEARTBEAT (18:50) | No editing review queue logic/scoring/rulesets, no recommending name removal, no git commits |
| sentinel | Post-promotion ruleset health sentinel; drift vs baseline, rollback recommendation | HEARTBEAT (17:15) | No editing manifest/rulesets/pins, no executing rollback without explicit human request |
| shadow_monitor | Read-only shadow portfolio performance; drawdown streaks, sleeve blowups | HEARTBEAT (daily) | No trade recommendations, no scoring/portfolio policy edits, no predicting future returns |
| shadow_watch | SHADOW (not wired) — merged successor of shadow_monitor + policy_shadow_watch | None | No trade recommendations, no modifying positions/weights/rulesets |
| universe_maintenance | Weekly read-only universe health; delistings, stale prices, coverage gaps | HEARTBEAT (weekly) | No modifying universe.json or production data, no adding/removing tickers without approval |

---

## Scope Ambiguity and Gap Report

Flagged 2026-05-04 SOUL.md sweep:

1. **universe_maintenance** — SOUL.md critically sparse (7 lines). No Identity, no Boundaries section, no Prohibit block, no model reference, no trigger. Scope functionally implied, not stated.

2. **shadow_watch** — Not wired into cron, no --message trigger documented. Merged scope (shadow_monitor + policy_shadow_watch) creates unresolved overlap with two still-active predecessors. Registry flags "boundary review pending."

3. **shadow_monitor + policy_shadow_watch + shadow_watch** — Three agents sharing portfolio-construction-monitoring mandate. Fuzzy scope boundaries. Registry notes partial overlap.

4. **biotech_news_digest + herald** — **Resolved 2026-05-30 (Fix #5).** `biotech_news_digest` deprecated; herald owns pipeline; heartbeat monitors `herald`.

5. **calibration + calibration_evidence** — Both write to artifacts/calibration_evidence/. Boundary between who writes what is underspecified.

6. **company_news_ingest** — SOUL.md written as if active. No deprecation notice in SOUL.md. A reader of SOUL.md alone would not know it is retired.

7. **event_analyst** — Cadence conflict: registry says weekly, crontab says 18:55 weekdays. Heartbeat-check confusion expected.

8. **intraday_mover_watch** — Cron not yet wired. Two future operating modes (live Alpaca, Polygon/Massive) with different email behavior. No SOUL.md trigger defined.

9. **price_action_watch** — Lighter than fleet standard: "What you never do" list but no formal Boundaries section, no write path enumeration, no git safety prohibition.

10. **ctgov_poller** — No Boundaries section with explicit read/run/write delineation. Key prohibition ("don't bypass PIT architecture") is implicit rather than stated.
