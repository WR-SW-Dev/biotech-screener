# Agent Registry Reference Table
Generated from AGENT_REGISTRY.json (auto-sync 2026-06-16; registry `as_of` 2026-06-12).

## Full Reference Table

| agent_id | cadence | status | artifact_paths |
|---|---|---|---|
| aact_trial_ingest | weekly | active | `data/aact/snapshots/`, `data/aact/linked/`, … |
| bioshort_watch | unknown | deprecated | `artifacts/bioshort_watch/`, `output/hedge_report/` |
| calibration | weekly | active | `artifacts/calibration_evidence/` |
| calibration_evidence | weekly | active | `artifacts/calibration_evidence/` |
| catalyst_delta | daily_after_production | active | `artifacts/catalyst_delta/` |
| crt_resolution_watcher | daily_after_production | active | `output/catalyst_ev/` |
| ctgov_poller | daily_premarket | active | `artifacts/ctgov_daily/` |
| data_auditor | daily_after_production | active | `artifacts/data_auditor/` |
| earnings_calendar_sync | daily_premarket | active | `artifacts/earnings_sync/` |
| event_analyst | weekly | active | `artifacts/event_analyst/` |
| fleet_steward | daily_after_production | active | `agents/fleet_steward/memory/`, `artifacts/fleet_steward/` |
| grok_biotech_watch | intraday | active | `artifacts/grok_watch/` |
| herald | daily_premarket | active | `data/press_releases/`, `artifacts/news_digest/` |
| hermes-contradiction-detector | on_demand | active | `artifacts/ops/contradiction_ledger/`, `artifacts/ops/knowledge_layer/` |
| hermes-first-fire-validator | on_demand | active | `artifacts/ops/first_fire_ledger/`, `artifacts/audit/first_fire_validations/` |
| hermes-held-spec-ledger | on_demand | active | `artifacts/ops/held_spec_ledger/` |
| hermes-ruleset-integrity | on_demand | active | `artifacts/audit/ruleset_integrity/` |
| ic_health_monitor | daily_after_production | active | `agents/ic_health_monitor/memory/` |
| intraday_mover_watch | intraday | active | `artifacts/intraday_mover_watch/` |
| ops | daily_after_production | active | `agents/ops/memory/`, `artifacts/ops_digest/` |
| ops_supervisor | daily_after_production | active | `artifacts/ops_supervisor/`, `agents/ops_supervisor/memory/` |
| options_watch | daily_after_production | active | `artifacts/options_watch/` |
| postmortem | daily_after_production | active | `artifacts/postmortem/` |
| price_action_watch | daily_after_production | active | `artifacts/price_action_watch/` |
| production_qa | daily_after_production | active | `artifacts/production_qa/`, `agents/production_qa/memory/` |
| qa | daily_after_production | active | `agents/qa/memory/` |
| review_queue_steward | daily_after_production | active | — |
| sentinel | daily_after_production | active | `agents/sentinel/memory/` |
| shadow_monitor | daily_after_production | active | `agents/shadow_monitor/memory/`, `artifacts/shadow_monitor/`, … |
| shadow_watch | unknown | deprecated | `artifacts/live_shadow/`, `agents/shadow_watch/` |
| universe_maintenance | weekly | active | `artifacts/universe_maintenance/` |

## Deprecated / absent overlapping agents

- `shadow_watch` — retained as a deprecated historical directory; active portfolio-risk monitoring is owned by `shadow_monitor`.
- `bioshort_watch` — retained as a deprecated historical directory; deterministic bioshort producer/status tooling is canonical and LLM reactivation requires a separate approved spec.
- `policy_shadow_watch`, `biotech_news_digest`, and `company_news_ingest` — absent from `agents/`; surfaces are owned by `shadow_monitor` (portfolio risk) and `herald` (news).

## Known overlaps (remaining)

- **calibration + calibration_evidence** — Both use `artifacts/calibration_evidence/`; boundary underspecified.
