# Agent Registry Reference Table
Generated from AGENT_REGISTRY.json sweep 2026-05-04 (schema v1.0, as_of 2026-04-28).

## Full Reference Table

| agent_id | cadence | artifact_paths | memory_path | status |
|---|---|---|---|---|
| aact_trial_ingest | weekly | data/aact/snapshots/, data/aact/linked/ | agents/aact_trial_ingest/memory/ | active |
| bioshort_watch | weekly | artifacts/bioshort_watch/ | — | active |
| biotech_news_digest | daily_after_production | artifacts/news_digest/ | — | active |
| calibration | weekly | artifacts/calibration_evidence/ | — | active |
| calibration_evidence | weekly | artifacts/calibration_evidence/ | — | active |
| catalyst_delta | daily_after_production | artifacts/catalyst_delta/ | — | active |
| company_news_ingest | daily_premarket | data/press_releases/ | — | **deprecated** |
| crt_resolution_watcher | daily_after_production | output/catalyst_ev/ | — | active |
| ctgov_poller | daily_premarket | artifacts/ctgov_daily/ | — | active |
| data_auditor | daily_after_production | artifacts/data_auditor/ | — | active |
| earnings_calendar_sync | daily_premarket | artifacts/earnings_sync/ | — | active |
| event_analyst | weekly | artifacts/event_analyst/ | — | active |
| fleet_steward | daily_after_production | agents/fleet_steward/memory/, artifacts/fleet_steward/ | agents/fleet_steward/memory/ | active |
| grok_biotech_watch | intraday | artifacts/grok_watch/ | — | active |
| herald | daily_premarket | data/press_releases/, artifacts/news_digest/ | — | active |
| ic_health_monitor | daily_after_production | agents/ic_health_monitor/memory/ | agents/ic_health_monitor/memory/ | active |
| intraday_mover_watch | intraday | artifacts/intraday_mover_watch/ | — | active |
| ops | daily_after_production | agents/ops/memory/, artifacts/ops_digest/ | agents/ops/memory/ | active |
| ops_supervisor | daily_after_production | artifacts/ops_supervisor/, agents/ops_supervisor/memory/ | agents/ops_supervisor/memory/ | active |
| options_watch | daily_after_production | artifacts/options_watch/ | — | active |
| policy_shadow_watch | daily_after_production | artifacts/policy_shadow/tier_weighted/ | — | active |
| postmortem | daily_after_production | artifacts/postmortem/ | — | active |
| price_action_watch | daily_after_production | artifacts/price_action_watch/ | — | active |
| production_qa | daily_after_production | artifacts/production_qa/, agents/production_qa/memory/ | agents/production_qa/memory/ | active |
| qa | daily_after_production | agents/qa/memory/ | agents/qa/memory/ | active |
| review_queue_steward | daily_after_production | agents/review_queue_steward/memory/ | agents/review_queue_steward/memory/ | active |
| sentinel | daily_after_production | agents/sentinel/memory/ | agents/sentinel/memory/ | active |
| shadow_monitor | daily_after_production | agents/shadow_monitor/memory/, artifacts/shadow_monitor/ | agents/shadow_monitor/memory/ | active |
| shadow_watch | daily_after_production | agents/shadow_watch/memory/, artifacts/shadow_watch/ | agents/shadow_watch/memory/ | **shadow** |
| universe_maintenance | weekly | artifacts/universe_maintenance/ | — | active |

---

## Path Mismatch List

### Hard mismatches — declared path does not exist on disk

1. **aact_trial_ingest** — `data/aact/linked/` declared, directory MISSING
2. **fleet_steward** — `artifacts/fleet_steward/` declared, directory MISSING (memory/ path exists)
3. **shadow_watch** — `agents/shadow_watch/memory/` declared, directory MISSING (expected; status=shadow, not wired)
4. **shadow_watch** — `artifacts/shadow_watch/` declared, directory MISSING (same)

### Behavioral mismatches — path exists but registry is wrong

5. **ic_health_monitor** — Real output is `artifacts/ic_dashboard/<date>_dashboard.json` (NOT in registry). Registry only lists memory/ which is empty by design. ANY triage of this agent must go to artifacts/ic_dashboard/, never memory/.

6. **policy_shadow_watch** — Old declared path `artifacts/policy_shadow_watch/` never existed. Registry corrected 2026-05-03 (commit 2fd2e7d9) to `artifacts/policy_shadow/tier_weighted/`. Old path confirmed absent.

7. **review_queue_steward** — Chat-mode only with no artifact contract per SOUL.md/TOOLS.md. The `agents/review_queue_steward/memory/` declaration is misleading — no output artifacts are generated. Registry mismatch flagged 2026-05-03, operator decision pending on B1/B2/B3.

---

## Known dual-active overlaps (scope boundary review pending)

- **herald + biotech_news_digest** — Both write to artifacts/news_digest/. Herald absorbed biotech_news_digest scope but biotech_news_digest still active in registry.
- **shadow_monitor + policy_shadow_watch + shadow_watch** — Three agents sharing portfolio construction monitoring. shadow_watch is the shadow successor but predecessors remain active.
- **calibration + calibration_evidence** — Both write to artifacts/calibration_evidence/. Boundary underspecified.
