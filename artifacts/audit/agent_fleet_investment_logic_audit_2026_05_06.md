# Agent Fleet — Investment Logic Audit (2026-05-06)

Read-only. No code, cron, or memory changes performed. Evidence cited inline (paths, mtimes, registry fields). All paths absolute under `/mnt/c/Projects/biotech_screener/biotech-screener/`.

Source of truth for fleet inventory: `agents/AGENT_REGISTRY.json` (28 active + 1 deprecated + 1 untracked-but-real `ops_supervisor` = 30 dirs in `agents/`); cron schedule: `crontab -l`; freshness: artifact mtimes and `logs/agents_direct/*.json`; live operational state: `logs/heartbeat_checks.log` (latest run 2026-05-05 17:30 ET) and `artifacts/ops_supervisor/2026-05-05_*`.

---

## Closure note appended 2026-05-06 (Spec 085 disposition)

Several rows below describe `shadow_watch` as `NEEDS_HUMAN_REVIEW` / `RETIRE_CANDIDATE` / "merged-successor placeholder" / "half-merged". **Operator ruling 2026-05-06: `shadow_watch` is finalized as SUPPRESSED PLACEHOLDER (Spec 085).**

- NOT retired.
- NOT activated.
- No cron, no memory writes, no artifacts, no runtime obligations.
- Activation requires a separate spec.
- `shadow_monitor` and `policy_shadow_watch` remain the live agents covering the shadow-portfolio and policy-comparison surfaces.

Surfaces aligned to this disposition:
- `agents/AGENT_REGISTRY.json` — `notes` updated to `"SUPPRESSED PLACEHOLDER — not active. ... 2026-05-06: classified suppressed_placeholder in governance audit."`
- `agents/ops_supervisor/supervisor.py:118` — `SUPPRESSED_AGENTS` is now a per-agent reason dict; `shadow_watch` reason: `"suppressed placeholder (Spec 085 disposition 2026-05-06; not active, not wired; activation requires separate spec)"`.
- `agents/shadow_watch/SOUL.md` — top header carries SUPPRESSED PLACEHOLDER status; planning text below is preserved as design context only, NOT runtime obligation.
- `tools/agent_heartbeat_checks.py:654` — comment block clarified to reflect Spec 085 disposition (no heartbeat obligation; not "directory deleted").
- `specs/changes/spec_085_p0_shadow_watch_disposition_2026_05_06.md` — closure section appended.

The body of the audit below is preserved as the original 2026-05-06 read-only observation. **Where it says `NEEDS_HUMAN_REVIEW` for `shadow_watch`, the resolution is "SUPPRESSED PLACEHOLDER per Spec 085" — the description above this fold is authoritative.**

## P1 closure notes appended 2026-05-06

**P1 #1 — `ic_health_monitor` LLM escalation suppression (CLOSED, commit `8cf24340`):** `tools/agent_heartbeat_checks.py` now carries a date-bounded `IC_HEALTH_CARRIED_ALERTS` muffle. `inst_delta_z` ALERT through 2026-05-15 downgrades to WARN with `[CARRIED]` tag and skips LLM escalation when it's the only anomaly. Hard ALERT path preserved for any unmuffled signal and after the muffle's `expires_after`. IC math, thresholds, and dashboard JSON untouched.

**P1 #3 — `grok_biotech_watch` 12:00 cadence drop (CLOSED, prior commit `edb8ac5a` "ops: reduce grok biotech watch to one daily run"):** Grok actually went further than the audit's recommendation — reduced from 4×/day → 1×/day at 16:00 ET (ROI audit) rather than only dropping the 12:00 slot. Where the body below recommends "reduce 4×/day → 2×/day (drop 12:00)" or "drop 12:00", the resolution is **already implemented and exceeds scope** (only 16:00 ET remains; 22:00 also previously removed). `model_documentation.md` and `docs/MODEL_DOCUMENTATION.md` cadence rows updated 2026-05-06 to reflect the live 1×/day schedule.

**P1 #4 — `event_analyst` weekly cadence (CLOSED, this commit):** Both event_analyst cron entries (`55 18 * * 1-5` LLM agent and `10 19 * * 1-5` deterministic builder) reduced to Friday-only (`* * 5`); originals preserved as commented audit-trail lines. Watchdog (`tools/cron_watchdog.sh`) `PHASE2_AGENTS` list had `event_analyst` removed to prevent the daily auto-recovery path from undoing the cadence reduction on Mon-Thu. The `tools/cron_one_shot_2026_05_12.sh` verifier (scheduled to fire 2026-05-12) was updated: `EXPECTED_DATES` reduced from 6 weekdays to just Friday `2026-05-08`; pre-cadence-change historical artifacts (2026-05-04, 2026-05-05) tracked separately as informational. Registry note rewritten to record the new cadence accurately. HEARTBEAT.md and both MODEL_DOCUMENTATION.md cadence rows updated. Manual invocation paths (`tools/run_agent_direct.py --agent event_analyst`, `tools/build_event_analyst.py --as-of-date YYYY-MM-DD`) preserved. No selector / ranker / EV / sizing / Module 3 ingestion change.

**P1 #6 — `shadow_monitor` cadence (CLOSED, this commit):** LLM cron entry `25 18 * * 1-5 ... shadow_monitor --message "DAILY" --write-memory` retired (preserved as commented audit-trail line). Forward shadow accumulation continues unchanged via the deterministic build (`tools/build_shadow_monitor.py` invoked by `run_daily_production.py:5140`), which writes `artifacts/shadow_monitor/{date}_monitor.{json,md}` daily. Tier 2 heartbeat check (`agent_heartbeat_checks.py:check_shadow_monitor`) continues to supervise the deterministic artifact. The retired LLM path was redundant — the crontab comment "Tier 2 heartbeat checks (replaces qa, ic_health_monitor, calibration, fleet_steward, shadow_monitor, aact_trial_ingest)" already declared this consolidation; the cron entry had simply not been removed at that time. Manual LLM-narrative invocation preserved: `tools/run_agent_direct.py --agent shadow_monitor --message DAILY --write-memory`. Registry notes, HEARTBEAT.md, and both MODEL_DOCUMENTATION.md cadence rows updated. No shadow signal calculation, history-write semantics, or production scoring change.

**P1 #2 — `catalyst_delta` LLM noise (PARTIAL CLOSURE — LLM-side only, this commit; artifact-level filtering deferred):** Per operator's Path-2 ruling (2026-05-06), narrowed the LLM elevation rule in the agent's prompt without touching deterministic outputs. Reason: the name `catalyst_delta` collides with `catalyst_delta_score` — a real Module 3 scoring field set by `module_3_scoring.py:764` / `module_3_scoring_v2.py:731` and consumed by `module_5_composite.py:477,487,492`. Strict pre-check rule "stop if catalyst_delta feeds scoring" triggered; user chose Path 2 (LLM-narrative-only) as the safest first pass. **What changed**: `agents/catalyst_delta/AGENTS.md` "Noise filter" section rewritten — narrative now elevates only deltas where ticker is in-universe AND `catalyst_days <= 60` AND change-code is HARD (`NEW_HARD_EVENT`, `HARD_EVENT_DATE_CHANGE`, `FDA_EVENT_NEW`, `SEC_EVENT_NEW`) OR family-changing (`SOURCE_FAMILY_CHANGE`, `TRIAL_STATUS_CHANGE`); suppressed deltas MUST be rollup-summarized (not erased). Prior elevation rule preserved inline as historical context. `agents/catalyst_delta/SOUL.md` Core Principles got a new principle #5 codifying "LLM elevation rule is narrative-only". Registry notes updated. **What did NOT change** (verified by diff): `tools/build_catalyst_delta.py` (deterministic artifact generation), `tools/build_options_watch.py` (artifact consumer), `module_3_schema*.py`, `module_3_scoring*.py`, `module_5_composite.py`, `common/ranker_active_contract.py`, `catalyst_delta_score` field anywhere, raw artifacts under `artifacts/catalyst_delta/`. **Status**: P1 #2 is PARTIALLY CLOSED. If artifact-level filtering is later desired, it requires a separate explicit change with before/after artifact diffs and a Module-5-composite output check.

**P1 #5 — `company_news_ingest` retire (CLOSED, this commit):** Preflight inspection confirmed the agent is **production-safe to retire**: cron entry was already commented out in a prior cleanup (header `# RETIRED: company_news_ingest (consolidated into herald)`); watchdog `PHASE2_AGENTS` does not include it; `ops_supervisor.SUPPRESSED_AGENTS` already carries reason "agent retired (replaced by tier-2 heartbeat checks)"; no production path consumes its output (empty grep against `run_daily*.py`, `run_daily_production.py`, `production_qa_check.py`, `module_3*.py`, `tools/classify_press_releases.py`, `tools/fetch_company_press_releases.py`, `tools/build_review_packet.py`). Cleanup landed in this commit: (a) `agents/AGENT_REGISTRY.json` `status: deprecated` → `status: retired` with explicit retirement notes; (b) `agents/company_news_ingest/SOUL.md` got a RETIRED header listing the surfaces that record the disposition; (c) `tools/agent_heartbeat_checks.py` `AGENTS` dict — herald alias removed (the existing comment directive flagged this cleanup as pending company_news_ingest retirement; the alias mapped `--agent herald` to `check_news_digest`, which actually returned `biotech_news_digest` results — misleading); (d) `model_documentation.md` and `docs/MODEL_DOCUMENTATION.md` cadence rows for company_news_ingest updated to "RETIRED 2026-05-06 (P1 #5)". `data/press_releases/` historical artifacts preserved (herald continues to write to the same path). `agents/company_news_ingest/` directory retained for git history + planning context. No code, scoring, classifier-feed, or Module-3 ingestion change. Reactivation requires a new spec.

Other items (bioshort upstream P2) remain HELD per operator direction.

---

## A. Executive summary

- Fleet size: **30 directories under `agents/`** (29 LLM-style + `ops_supervisor`); registry tracks 28 active, 1 shadow (`shadow_watch`), 1 deprecated (`company_news_ingest`); `ops_supervisor` is registered but `supervised_by_orchestrator=false` (terminus per no-recursive-supervision policy)
- Cron-scheduled / Hermes-triggered jobs invoking agent code: **~28 distinct cron entries** in `crontab -l` directly relevant to agents (counting active lines, excluding commented-out replaced entries; many are deterministic Python wrappers, e.g. `agent_heartbeat_checks.py`, `production_qa_check.py`, `build_event_feedback.py`, `cron_blast_radius_daily.sh`)
- Count by role (registry category, active only):
  - control_plane: 6 — `data_auditor`, `fleet_steward`, `ops`, `production_qa`, `qa`, `sentinel` (+ `ops_supervisor` outside category set)
  - signal_monitor: 7 — `biotech_news_digest`, `catalyst_delta`, `grok_biotech_watch`, `ic_health_monitor`, `intraday_mover_watch`, `options_watch`, `price_action_watch`, `review_queue_steward`
  - data_ingestion: 5 — `aact_trial_ingest`, `ctgov_poller`, `earnings_calendar_sync`, `herald`, `universe_maintenance` (+ deprecated `company_news_ingest`)
  - research: 4 — `calibration`, `calibration_evidence`, `crt_resolution_watcher`, `event_analyst`, `postmortem`
  - portfolio_risk: 3 — `bioshort_watch`, `policy_shadow_watch`, `shadow_monitor` (+ shadow `shadow_watch`)

### Top 5 risks (one-line evidence each)

1. **Ruleset drift / phantom ruleset** — `2026-05-05` rankings ran under `ruleset_id=8887576e v1.4.0` per snapshot, while production manifest still says `2a3e79eb v1.13.0` (per memory `scoring_model_identity_2026_04_06.md`); produced 100% blast on 2026-05-05 (`logs/blast_radius.log` "Tickers with any field change: 297/297"); ops, sentinel, and `catalyst_delta/SOUL.md` (line 36: `ID: 8887576e (v1.14.0)`) all reference the new ID independently — divergence between code-believed and registry-declared ruleset is unresolved.
2. **`bioshort_watch` operating on 5+ weeks-stale upstream** — `output/hedge_report/hedge_report_2026-03-26.json` is the latest hedge report (mtime Mar 26); today's "watch" artifacts are stamped `2026-01-15` / `2026-01-20` (written 2026-05-06 13:33 — date-stamping bug in the builder), the agent's own memory `agents/bioshort_watch/memory/2026-05-03_cron_misescalation_issue.md` documents the entry-point breakage; weekly Friday cron still fires; risk = false `HEDGE NOW` verdicts on stale carry data.
3. **`policy_shadow_watch` artifact-date corruption** — most recent files in `artifacts/policy_shadow/tier_weighted/` are `2026-01-15_comparison.md` / `2026-01-20_comparison.md` (built today 2026-05-06 13:33); only legitimately-named files (`2026-05-04`, `2026-05-01`) date to 2026-05-06 08:04; heartbeat flagged STALE on 2026-05-05 ("newest=2026-04-28 (7.4d)"); `history.jsonl` last 3 lines all dated 2026-01-15/20 — same producer date-bug as bioshort.
4. **No-consumer artifact farm** — `catalyst_delta` writes 729 changes/day (`artifacts/catalyst_delta/2026-05-06_delta.md`) but the only repo consumer is `tools/build_options_watch.py` and the agent's own files; no scoring/ranker/screener path reads it. Same for `news_digest`, `grok_watch`, `intraday_mover_watch` — they email a human only. Per `feedback_audit_to_tickets_prompt.md` and `feedback_no_recursive_supervision.md`, "writes nobody reads" is a maintenance-cost-only signal.
5. **`ic_health_monitor` SIGNAL_ALERT on `inst_delta_z` is an expected cohort artifact, but FAIL persists daily** — per memory `regime_post_cohort_change_distortion_2026_04_28.md` and confirmed in `artifacts/ops_supervisor/2026-05-05_supervisor.md` ("Expected: inst_delta_z byte-identical 04-25 → 04-28 due to 13F cohort rebuild; self-heal at next 13F refresh ~2026-05-15"); the daily heartbeat still escalates this to LLM (incurring cost) until self-heal — false-positive bias risk per `feedback_observation_bias_cron_monitoring.md`.

### Top 5 highest-value agents

1. **`postmortem`** — produces the only ground-truth labels for `event_ev`, `calibration_evidence`, and `event_analyst`; consumed by `tools/build_calibration_evidence.py:89` and `tools/build_event_analyst.py`. Wired through to research feedback loop. Latest write `artifacts/postmortem/2026-04-30/` 2026-05-05 17:40.
2. **`crt_resolution_watcher`** — writes `output/catalyst_ev/crt_options_join.json` (mtime 2026-05-05 18:00 per heartbeat), the join table for catalyst-EV evidence; `mutate_data` authority. Critical wiring per CRT memory (101 res, 52 HIT/17 MISS).
3. **`herald`** — sole news ingest path after `company_news_ingest` retirement; output `data/press_releases/` consumed by digest, downstream reconcile, and trap-detection logic.
4. **`production_qa`** (deterministic `tools/production_qa_check.py`) — RED/YELLOW/GREEN gate runs daily 18:55; latest `artifacts/production_qa/2026-05-06_report.md` flagged YELLOW (10/11 pass; classifier_escalation_pool other_share 56.1%>50). Real quality gate.
5. **`data_auditor`** (deterministic `agents/data_auditor/run_audit.py`) — 5/5 PASS on 2026-05-05 (`artifacts/data_auditor/integrity_report_2026-05-05.json`); checks archive, IPO consistency, PIT-financials freshness, financial divergence, price gaps. Read-only judge with concrete fail criteria — exactly the role per `feedback_agent_governance.md`.

### Top 5 cleanup / consolidation candidates

1. **`policy_shadow_watch` + `shadow_monitor` + `shadow_watch`** — registry already notes `shadow_watch` is the "merged successor" (status=shadow, supervised=false, no `memory/` subdir despite registry claiming `agents/shadow_watch/memory/`); finish the merge OR retire `shadow_watch` directory.
2. **`bioshort_watch`** — fix the date-stamp bug or downgrade to monthly until upstream `hedge_report` is being refreshed; current state burns weekly LLM calls on stale data.
3. **`company_news_ingest`** — registry status=deprecated, retired in cron, but directory still exists (`agents/company_news_ingest/` with SOUL.md, etc.); registry note "Directory pending removal in a future cleanup fix" — still pending.
4. **`catalyst_delta`** — 729 changes/day → no production consumer beyond `build_options_watch.py`. Either reduce surface noise (suppress `CTGOV_NEW_TRIAL` floods — 374/day mostly automated CT.gov churn) or downgrade to weekly, or wire it into `review_queue_steward` priority list.
5. **`ic_health_monitor`** daily LLM escalation while `inst_delta_z` self-heal is expected (~2026-05-15) — suppress this single-anomaly path until 13F refresh closes the cohort window; saves Sonnet calls.

---

## B. Agent role map table

| agent | role | authority | outputs | downstream consumer | thesis link | status | recommended action |
|---|---|---|---|---|---|---|---|
| aact_trial_ingest | DATA_INGEST | observe_only | `data/aact/snapshots/`, `data/aact/linked/` | `tools/build_event_analyst.py`, screener clinical features | data correctness (HINT alignment) | OK 2026-05-04 | KEEP_INFRA |
| bioshort_watch | RESEARCH_SHADOW | observe_only | `artifacts/bioshort_watch/*_watch.{json,md}` | none (email-only verdict) | hedge sizing (portfolio risk) | upstream stale 5+ weeks | FIX_WIRING — fix `tools/biotech_hedge_report.py` default-portfolio-csv per agent's own memory note 2026-05-03 |
| biotech_news_digest | REPORTING_DIGEST | write_artifacts | `artifacts/news_digest/biotech_news_digest_*.{json,txt,html}` | email send only | catalyst awareness (human) | OK 6 digests/day | KEEP_INFRA — reduce to 2/day if cost-relevant |
| calibration | RESEARCH_SHADOW | observe_and_propose | `artifacts/calibration_evidence/` | manual review | promotion gate | OK | KEEP_SHADOW |
| calibration_evidence | RESEARCH_SHADOW | observe_only | `artifacts/calibration_evidence/2026-05-03_evidence.{json,md}`, `ledger.jsonl` | manual review, calibration | EV calibration evidence | OK | KEEP_CORE |
| catalyst_delta | SIGNAL_MONITOR | write_artifacts | `artifacts/catalyst_delta/2026-05-06_delta.{json,md}` | `tools/build_options_watch.py` only | catalyst timing context | OK but 729 deltas/day | REDUCE_FREQUENCY or filter — see Section D group 2 |
| company_news_ingest | DATA_INGEST | write_artifacts (deprecated) | `data/press_releases/` (now herald) | herald | n/a | DEPRECATED, dir still present | RETIRE_CANDIDATE — delete directory |
| crt_resolution_watcher | EVENT_EV_or_CATALYST | mutate_data | `output/catalyst_ev/crt_options_join.json`, `crt_cohort_analysis.json` | `tools/build_event_feedback.py`, EV layer | catalyst EV truth source | OK 18:00 daily | KEEP_CORE |
| ctgov_poller | DATA_INGEST | write_artifacts | `artifacts/ctgov_daily/` | snapshot pipeline (clinical features) | clinical (shadow), catalyst_delta | OK 14:30 daily | KEEP_INFRA |
| data_auditor | QA_VALIDATION | observe_only | `artifacts/data_auditor/integrity_report_*.json` | `agent_heartbeat_checks.py:check_data_auditor` | data correctness gate | PASS 5/5 | KEEP_CORE |
| earnings_calendar_sync | DATA_INGEST | write_artifacts | `artifacts/earnings_sync/biotech_earnings.ics`, `earnings_normalized_*.json` | `bellringer` cron, fleet_steward freshness check | catalyst timing (binary) | OK 14:14 daily | KEEP_INFRA |
| event_analyst | RESEARCH_SHADOW | observe_only | `artifacts/event_analyst/*_summary.{json,md}` | manual review | event-resolution patterns (EES research) | OK weekly cadence | KEEP_SHADOW |
| fleet_steward | OPS_WATCHDOG | observe_and_propose | `agents/fleet_steward/memory/2026-05-05_receipt.md` | `agent_heartbeat_checks.py:check_fleet_steward` writes here | fleet health | OK 2026-05-05 | KEEP_INFRA |
| grok_biotech_watch | SIGNAL_MONITOR | write_artifacts | `artifacts/grok_watch/*_alerts.{json,md}`, email | email only | exploratory news watch | last alerts file 2026-05-04 23:28 (email path live) | REDUCE_FREQUENCY — 4×/day is heavy; 2×/day would suffice (post-close 22:00 already removed) |
| herald | DATA_INGEST | write_artifacts | `data/press_releases/`, `artifacts/news_digest/` | snapshot pipeline, news_digest builder | news truth source | OK 14:35 daily | KEEP_CORE |
| ic_health_monitor | SIGNAL_MONITOR | observe_only | `artifacts/ic_dashboard/*_dashboard.{json,md}` (via `tools/build_ic_dashboard.py` invoked by `run_daily_production.py:5167`) | `agent_heartbeat_checks.py:check_ic_health` | signal-degradation watchdog | FAIL daily (expected cohort artifact) | REDUCE_FREQUENCY of LLM escalation until 2026-05-15 13F refresh — see risk 5 |
| intraday_mover_watch | SIGNAL_MONITOR | write_artifacts | `artifacts/intraday_mover_watch/*_poll.json`, `sent_alerts.json` | email + dedupe state only | exploratory price-IV watch (Spec 063 shadow) | OK polling (15:30 EDT today) | KEEP_SHADOW — Spec 062-related; first review 30d post-emission, on schedule |
| ops | OPS_WATCHDOG | observe_and_propose | `agents/ops/memory/2026-05-05.md`, `artifacts/ops_digest/` | `ops_supervisor` reads, human consumes | duty officer | OK 17:00, 17:30 daily | KEEP_INFRA |
| ops_supervisor | OPS_WATCHDOG | observe_only | `artifacts/ops_supervisor/2026-05-05_supervisor.{json,md}`, `_sentinel.{json,md}` | terminal | severity verdict | OK YELLOW (watch) | KEEP_CORE — DO NOT TOUCH; per `feedback_no_recursive_supervision.md` |
| options_watch | SIGNAL_MONITOR | write_artifacts | `artifacts/options_watch/2026-05-06_watch.{json,md}`, `_premarket_watch.{json,md}` | `scripts/research/eval_preopen_watch.py:66,95` | options surface (Spec 062) | OK 09:52 daily | KEEP_INFRA |
| policy_shadow_watch | SIGNAL_MONITOR | observe_only | `artifacts/policy_shadow/tier_weighted/{date}_comparison.{json,md}`, `history.jsonl` | manual review | hold-discipline policy comparison | DATE-STAMP CORRUPTED (2026-01-15/20 written today) | FIX_WIRING — see risk 3, then merge with `shadow_watch` |
| postmortem | EVENT_EV_or_CATALYST | write_artifacts | `artifacts/postmortem/{date}/{TICKER}.json` (schema v1) | `tools/build_calibration_evidence.py:89`, `build_event_analyst.py` | event resolution truth | OK 17:40 daily | KEEP_CORE |
| price_action_watch | SIGNAL_MONITOR | write_artifacts | `artifacts/price_action_watch/2026-05-06_watch.{json,md}` | manual review | post-packet movers | OK 09:52 daily | KEEP_SHADOW — current consumer is human; consider wiring into `review_queue_steward` urgency |
| production_qa | QA_VALIDATION | observe_and_propose | `artifacts/production_qa/{date}_report.{json,md}`, `hard_collisions_*.json` | `agent_heartbeat_checks.py:check_production_qa`, human | production-readiness gate | YELLOW 2026-05-06 (classifier escalation FAIL) | KEEP_CORE |
| qa | QA_VALIDATION | observe_only | `agents/qa/memory/` | `agent_heartbeat_checks.py:check_qa` | snapshot integrity | OK | KEEP_INFRA |
| review_queue_steward | REVIEW_QUEUE_GOVERNANCE | observe_only | `logs/agents_direct/review_queue_steward_*.json`, `artifacts/review/review_priority_{date}.json` | `tools/build_review_packet.py`, `event_quality_shadow_sizer.py`, `common/options_review_queue.py` | review triage | OK 2026-05-06 09:53 | KEEP_CORE |
| sentinel | OPS_WATCHDOG | observe_and_propose | `agents/sentinel/memory/2026-05-05.md` | human + ops_supervisor inputs (`heartbeat_anomalies_md`) | post-promotion drift | OK 17:15 daily | KEEP_CORE — DO NOT TOUCH (per memory `feedback_verify_sentinel_verdict_directly.md`) |
| shadow_monitor | SIGNAL_MONITOR | observe_only | `artifacts/shadow_monitor/{date}_monitor.{json,md}` | `agent_heartbeat_checks.py:check_shadow_monitor` | shadow performance | WARN MAX_DRAWDOWN 11.30%→PERSISTENT | KEEP_SHADOW |
| shadow_watch | RESEARCH_SHADOW | observe_only | `agents/shadow_watch/` (no `memory/` subdir, registry path missing) | none — not yet wired | merged-successor placeholder | not in cron, status=shadow | RETIRE_CANDIDATE or finish-merge — see Section D group 1 |
| universe_maintenance | DATA_INGEST | observe_only | `artifacts/universe_maintenance/{date}_diff.{json,md}` | `tools/cron_data_refresh.sh` calls `tools/build_universe_maintenance.py` | universe health | OK 2026-05-06 09:30 | KEEP_INFRA |

Note: `intraday_mover_watch` registry says "Doc gap: memory/ directory missing per 2026-04-24 audit." — confirmed; agent is stateless poller-and-emailer.

---

## C. Investment thesis alignment table

| thesis component | supporting agents | missing coverage | duplicated coverage | risk |
|---|---|---|---|---|
| coinvest = quality FILTER (not alpha) | (none directly; enforced via `common/ranker_active_contract.py`); agents only attribute | none — coinvest is a static gate, not an agent task | n/a | none |
| financial = stress / upside discriminator | `data_auditor` (PIT-fresh check), `production_qa` (feature_coverage); ops digest summarizes | no dedicated runway-burn alert agent (memory `runway_severity_architecture.md` flags this gap) | n/a | runway-severity diagnostic still cross-layer not agent-owned |
| catalyst timing = release valve | `catalyst_delta` (changes), `ctgov_poller` (status), `crt_resolution_watcher` (resolutions), `earnings_calendar_sync` (dates), `event_analyst` (patterns) | none — well covered | `catalyst_delta` ↔ `ctgov_poller` overlap (catalyst_delta consumes ctgov diffs); `earnings_calendar_sync` ↔ `bellringer` cron | redundancy is intentional (ingest vs delta-classify); see Section D group 2 |
| Event EV / catalyst outcome calibration = SHADOW research | `postmortem` → `calibration_evidence` → `event_analyst` → `calibration` | none — `event_ev_p_hit` binder (Spec 077) is implemented forward-only and shipped; the wrong-field reading of `prediction_composite_score` is superseded; remaining blocker is calibration sample size (n=7 post-PIT HIT/MISS as of 2026-05-06; need ≥30, estimated arrival ~2026-07-01 per Spec 079) | n/a | not blocked architecturally; sample-size-bound only |
| clinical, Polymarket, exploratory = SHADOW unless promoted | `event_analyst`, `intraday_mover_watch`, `grok_biotech_watch`, `bioshort_watch`, `policy_shadow_watch`, `shadow_monitor` | Polymarket collector (`tools/poll_polymarket_biotech.py`) is NOT wired as an agent (per memory `polymarket_alpha_verdict_2026_05_05.md`, anecdotal_shadow only — correct per thesis) | shadow_watch (proposed merger of shadow_monitor+policy_shadow_watch) NOT YET wired; status duplicate-in-flight | merge half-done; see Section D group 1 |
| ranker FROZEN | `sentinel` (drift), `ic_health_monitor` (signal health), `production_qa` (rankings sanity) | none | sentinel ↔ ic_health overlap intentional (sentinel = ruleset health, ic_health = per-signal); both feed ops_supervisor | low — they answer different questions |
| infrastructure | `qa`, `data_auditor`, `production_qa`, `fleet_steward`, `ops`, `ops_supervisor`, `aact_trial_ingest`, `ctgov_poller`, `herald`, `earnings_calendar_sync`, `universe_maintenance` | none material; gaps documented in MEMORY.md (e.g., no archived `output/hedge_report/` watcher) | `qa` ↔ `production_qa` overlap (qa = snapshot existence, prod_qa = full gates); `fleet_steward` ↔ `ops_supervisor` overlap (fleet receipt vs anomaly verdict) | low — boundaries documented in registry; some doc gaps flagged |

---

## D. Duplication / overlap map

**Group 1 — shadow / policy / hedge governance (the merger that didn't finish):**
- `shadow_monitor` (active, daily, deterministic via `tools/build_shadow_monitor.py`) — shadow portfolio P&L vs XBI, drawdown, attention level
- `policy_shadow_watch` (active, daily, deterministic via `tools/build_policy_shadow_compare.py`) — current vs tiered policy P&L, headwind streaks
- `shadow_watch` (status=shadow, NOT in cron) — registry says "Merged successor of shadow_monitor + policy_shadow_watch. SOUL.md filled out 2026-04-28; not yet wired into cron." Directory exists but `memory/` subdir absent.
- `bioshort_watch` (active, weekly Friday) — IBB hedge sizing; reads `output/hedge_report/`
- **Recommendation:** finish the `shadow_watch` cutover OR retire it. Either (a) wire `shadow_watch` into cron and retire predecessors per registry note, or (b) delete `shadow_watch/` and update registry to remove the merged-successor row. Half-merged is the worst state. Risk if executed: false alarms for ~2 days on heartbeat coverage gap until specialized check is updated.

**Group 2 — catalyst layer (intentional redundancy, audit boundary):**
- `ctgov_poller` (data_ingestion) — CT.gov status snapshot diff
- `catalyst_delta` (signal_monitor) — classifies CT.gov diff into `CTGOV_NEW_TRIAL` etc. + cross-source change codes
- `crt_resolution_watcher` (research, mutate_data) — resolves catalyst events (HIT/MISS) into `output/catalyst_ev/crt_options_join.json`
- `event_analyst` (research) — aggregates resolved events into hit-rate slices
- `postmortem` (research) — captures pre-event state + T+1/T+3/T+5 returns
- **Recommendation:** **KEEP — boundary is correct.** Each layer has distinct input/output. The only fix is reducing `catalyst_delta` noise: 729 changes/day with 374 `CTGOV_NEW_TRIAL` events is mostly CT.gov auto-registration churn that does not change scoring. Filter to (in-universe) ∧ (catalyst_days ≤ 60) ∧ (hard or family-changing codes); leave the rest as a digest tail.

**Group 3 — options/price action overlap:**
- `options_watch` (signal_monitor) — post-packet options surface, daily 18:40
- `price_action_watch` (signal_monitor) — stock + options big-move monitor, daily 18:30
- `intraday_mover_watch` (signal_monitor) — real-time intraday movers, polls every 30 min
- **Recommendation:** **KEEP_INFRA — different time-windows, different consumers.** options_watch consumed by `eval_preopen_watch.py`; price_action_watch consumes options_watch outputs (per `tools/build_price_action_watch.py` grep result); intraday_mover is real-time email channel. Boundary is sound. No merge.

**Group 4 — calibration: 2 agents, 1 artifact path:**
- `calibration` (research, observe_and_propose) — promotion recommender
- `calibration_evidence` (research, observe_only) — ledger builder
- Both write to `artifacts/calibration_evidence/`
- **Recommendation:** **KEEP — separation of concerns is correct.** `calibration_evidence` writes the ledger; `calibration` consumes it. Naming is poor (registry note: "Shares artifact path with calibration; downstream consumer."). Optional rename `calibration` → `promotion_recommender` for clarity but no functional change.

**Group 5 — news / digest / Grok / Hermes:**
- `herald` — biotech press release ingest (canonical)
- `biotech_news_digest` — 3×/day digest email (consumes herald)
- `grok_biotech_watch` — xAI/Grok-based watchlist scout (4×/day email)
- `company_news_ingest` — DEPRECATED, dir still present
- **Recommendation:** RETIRE `company_news_ingest` directory; reduce `grok_biotech_watch` from 4×/day to 2×/day (07:00 + 15:00 — drop 12:00); consider drying up `biotech_news_digest` 3rd window if redundant with herald digest. Risk: minor — grok findings are exploratory only.

**Group 6 — qa / production_qa / data_auditor:**
- `qa` — snapshot existence + rankings.csv + metadata + phase2 (cheap)
- `production_qa` — full readiness/gates/feature-coverage/lint/tests (heavy, ~21:00 ET)
- `data_auditor` — PIT/IPO/financial/price integrity (early evening)
- **Recommendation:** **KEEP — all three answer different questions.** They are not duplicative; they form the "ingredients-OK / build-OK / output-OK" triad.

---

## E. Broken or weak wiring map

| agent | produced field/artifact | expected consumer | current issue | recommended fix |
|---|---|---|---|---|
| policy_shadow_watch | `artifacts/policy_shadow/tier_weighted/{date}_comparison.{json,md}` and `history.jsonl` | `agent_heartbeat_checks.py` STALE check; manual review | Files written today (2026-05-06 13:33) bear stamp `2026-01-15` and `2026-01-20`; `history.jsonl` last 3 entries dated 2026-01-15/20 — CSV/date-arg pipeline appears to be re-running historical loops and overwriting today's intended output | Investigate `tools/build_policy_shadow_compare.py` invocation path (cron `5 18 * * 1-5` passes `--as-of-date $(date +%Y-%m-%d)`; the corruption looks like it comes from a separate backfill loop, possibly via `tools/cron_evening_catchup.sh` or one-shot job re-running history); confirm and stop the back-loop |
| bioshort_watch | `artifacts/bioshort_watch/{date}_watch.{json,md}` | `bioshort_watch` LLM agent reads its own latest artifact | Latest written 2026-05-06 13:33 stamped `2026-01-15` / `2026-01-20`; legitimate latest by content date is `2026-03-26` (date inside file body); same date-stamp bug + upstream `output/hedge_report/` is March 26 | Two-part fix per agent's own memory: (a) stop date-stamp loop, (b) fix `tools/biotech_hedge_report.py` `--portfolio-csv` default per memo Option A |
| catalyst_delta | `artifacts/catalyst_delta/{date}_delta.{json,md}` | `tools/build_options_watch.py` only | 729 changes/day, no scoring/ranking consumer; SOUL.md ruleset `8887576e v1.14.0` ≠ memory-of-record `2a3e79eb v1.13.0` — symptom of the live ruleset drift | Reduce noise filter; reconcile ruleset reference (line 36 of `agents/catalyst_delta/SOUL.md` vs `production_data/decision_ruleset.json` — read-only check first, do not edit ruleset) |
| ic_health_monitor | `artifacts/ic_dashboard/{date}_dashboard.{json,md}` (built by `tools/build_ic_dashboard.py` from `run_daily_production.py:5167`) | `agent_heartbeat_checks.py:check_ic_health` | Daily SIGNAL_ALERT on `inst_delta_z` is byte-identical artifact (cohort lock per memory) — escalates LLM every weekday for an expected window | Suppress single-anomaly LLM escalation when only finding is `inst_delta_z` ALERT until 2026-05-15 13F refresh resolves the cohort window |
| shadow_monitor | `artifacts/shadow_monitor/{date}_monitor.{json,md}` | `agent_heartbeat_checks.py:check_shadow_monitor` | WARN MAX_DRAWDOWN persistent — by design (HOLD covers it), but adds noise to ops_supervisor every day | Suppress as carried-not-new in `agent_heartbeat_checks.py` (already classified "carried" by `ops_supervisor.py` per `2026-05-05_supervisor.md`); the dedup is downstream, not upstream — minor |
| company_news_ingest | `data/press_releases/` | herald has absorbed | Directory still present (`agents/company_news_ingest/SOUL.md` etc.); registry status=deprecated | Delete `agents/company_news_ingest/`; update registry "agents" map; rerun `tests/test_agent_registry.py` |
| `prediction_composite_score` field in postmortem records | `event_ev` calibration | EV layer | The wrong-field reading is historical — Spec 077 `event_ev_p_hit` binder is shipped forward-only; remaining blocker is calibration sample size (n=7 post-PIT HIT/MISS, need ≥30 by ~2026-07-01 per Spec 079) | No code change. Track via Spec 079 sample-size gate; do NOT backfill (30% join rate per `catalyst_phase_a_verdict_2026_05_04.md`) |
| shadow_watch | (none yet — directory exists, no artifacts, no cron) | merged successor | Half-built merger | Either wire it (then retire `shadow_monitor` + `policy_shadow_watch`) or remove the directory |
| `output/hedge_report/hedge_report_*.json` | bioshort_watch | upstream producer | Last write 2026-03-26 (stale 5+ weeks); NOT an agent — a manual or other-cron pipeline | Out of scope for fleet audit, but is the root cause of bioshort_watch issue. Producer needs identification (no obvious cron entry creates new hedge_reports) |

---

## F. Stale / low-value / retire-candidate list

Inclusion rule: artifact mtime stale OR no consumer found OR registry-flagged deprecation. **Memory-file recency is NOT used as the only basis for retirement** — many agents are stateless. All entries cite hard evidence.

1. **`company_news_ingest`** — registry `status=deprecated`, RETIRED in cron (commented out at line "RETIRED: company_news_ingest (consolidated into herald)"), but `agents/company_news_ingest/` directory still present. Evidence: registry note "Directory pending removal in a future cleanup fix." → **RETIRE** (delete directory, update registry).

2. **`shadow_watch`** — `agents/shadow_watch/` directory exists; registry `supervised_by_orchestrator=false`, `status=shadow`, `notes` say "Merged successor of shadow_monitor + policy_shadow_watch. SOUL.md filled out 2026-04-28; not yet wired into cron." `agents/shadow_watch/memory/` does not exist. No artifact path produces output. → **NEEDS_HUMAN_REVIEW** — if the merger is still intended, finish it; if abandoned, retire.

3. **`bioshort_watch` (current behavior, NOT the directory)** — produces wrong-dated artifacts on stale upstream. Last legitimate-content `_watch.md` body dates 2026-03-26 — that's >40 days old. → **FIX_WIRING** (see Section E); if fix not feasible, REDUCE_FREQUENCY to monthly until upstream is restored.

4. **`policy_shadow_watch` (current behavior)** — date-stamp corruption produces 2026-01-XX files daily. → **FIX_WIRING** required before further use; do NOT retire (artifact has a real consumer — `tools/eval_policy_candidate.py`, history.jsonl).

5. **`bioshort_watch` 2026-04-X memory directory** — only one memory file `2026-05-03_cron_misescalation_issue.md` (an issue write-up, not a live receipt); the agent's intended weekly write cadence has not produced a normal receipt since at least 2026-04-28. → Evidence of staleness, not retirement candidate by itself; ties into item 3.

6. **`catalyst_delta` raw noise** — produces 729 deltas/day with only one downstream consumer (`tools/build_options_watch.py`) that filters tightly. → **REDUCE_FREQUENCY** of human-readable digest (or filter), not retirement; the underlying CT.gov change-detection has real value if filtered to in-universe + near-term.

7. **`grok_biotech_watch` mid-day 12:00 run** — 22:00 already removed (per crontab comment "REMOVED: 22:00 grok run (post-close, no signal value)"); 12:00 is mid-trading-day duplicate of 15:00. → **REDUCE_FREQUENCY** to 2×/day (07:00 + 15:00).

Items NOT recommended for retirement despite missing-memory: `aact_trial_ingest`, `ctgov_poller`, `earnings_calendar_sync`, `herald`, `intraday_mover_watch`, `universe_maintenance` — all stateless artifact-writers, all with fresh outputs and downstream consumers verified.

---

## G. Schedule / frequency review

| job | current cadence | value | risk | recommendation |
|---|---|---|---|---|
| `cron_daily_production.sh` 16:30 M-F | daily | CRITICAL — DEM run | none | KEEP |
| `agent_heartbeat_checks.py` 17:30 M-F | daily | HIGH — replaces 6 LLM heartbeat agents | low | KEEP (savings 2026-04-25 onward) |
| `ops` HEARTBEAT 17:00 + 17:30 (LLM) | 2×/day | HIGH — duty officer | LLM cost | KEEP — but ops_supervisor 20:30 covers, the 17:00 quick HEARTBEAT may be redundant with 17:30 — confirm |
| `sentinel` HEARTBEAT 17:15 | daily | HIGH — ruleset drift | low | KEEP |
| `crt_resolution_watcher` 18:00 | daily | HIGH — EV truth | low | KEEP |
| `catalyst_delta` 18:20 | daily | MEDIUM (no consumer beyond options_watch) | LLM cost | KEEP_DAILY but FILTER before LLM step |
| `shadow_monitor` DAILY (LLM, --write-memory) 18:25 | daily | MEDIUM | LLM cost | REDUCE_FREQUENCY — deterministic build_shadow_monitor already produces the artifact; LLM agent run is supplementary |
| `price_action_watch` HEARTBEAT 18:30 | daily | MEDIUM | low | KEEP |
| `postmortem` script 17:40 + agent HEARTBEAT 17:42 | daily | HIGH | low | KEEP |
| `options_watch` HEARTBEAT 18:40 | daily | MEDIUM | low | KEEP |
| `review_queue_steward` 18:50 | daily | HIGH (real downstream consumers) | low | KEEP |
| `event_analyst` DAILY 18:55 | daily (registry says weekly) | MEDIUM | LLM cost | REDUCE_FREQUENCY to weekly (Friday only); registry already documents intended weekly cadence |
| `bioshort_watch` Friday 18:10 | weekly | LOW (stale upstream) | medium (false verdicts) | PAUSE until `output/hedge_report/` is being refreshed; OR fix per Section E |
| `ctgov_poller` 14:30 | daily premarket | HIGH | low | KEEP |
| `herald` 14:35 | daily | HIGH | low | KEEP |
| `universe_maintenance` Mon 14:00 | weekly | MEDIUM | low | KEEP |
| `data_auditor --daily-only` 18:00 M-F + `--weekly-only` Sat 06:00 | daily+weekly | HIGH | low | KEEP |
| `production_qa_check.py` 17:35 | daily | HIGH | low | KEEP (but timing: it's actually 17:35 per crontab line; Section A note says report mtime 18:55 — review) |
| `build_event_feedback.py` 17:45 | daily | HIGH (CRT pipeline) | low | KEEP |
| `build_calibration_evidence.py` Fri 14:00 | weekly | HIGH (research feedback) | low | KEEP |
| `cron_blast_radius_daily.sh` 19:15 | daily | MEDIUM (audit trail) | low | KEEP |
| `build_rank_change_monitor.py` 17:00 | daily | MEDIUM (calibration audit 2026-05-11) | low | KEEP |
| `cron_inst_delta_forward_compare.sh` 19:30 + `cron_cross_signal_forward_logger.sh` 19:40 | daily | HIGH (research shadow, verdict h20d=2026-05-26) | low | KEEP |
| `ops_supervisor` 20:30 + `agent_supervisor_sentinel.py` 20:40 | daily | HIGH (last interpretive layer + terminus) | low | KEEP — DO NOT TOUCH |
| `build_grok_biotech_watch.py` 07/12/15 | 3×/day | MEDIUM (exploratory) | none | REDUCE_FREQUENCY drop 12:00 |
| `build_news_digest.py` 08/15/18 | 3×/day | MEDIUM | none | KEEP |
| `cron_intraday_mover.sh` 09:35/09:50 + 10:00..15:30 :00,:30 + 16:15 digest | intraday | MEDIUM (Spec 063 shadow) | low | KEEP for first-week observation; spec calls for upgrade to 15-min after one clean week |
| `cron_bellringer.sh` 06:30 + 18:30 | daily | MEDIUM (earnings alerts) | none | KEEP |
| `cron_data_extras.sh` form4/short/pit_fin/fin_records/burn 13:30 | daily | HIGH | none | KEEP |
| `cron_evening_catchup.sh` 22:00 | daily | MEDIUM (host-sleep recovery) | low | KEEP |
| One-shot 2026-05-08, 2026-05-11, 2026-05-12 | one-time | scheduled checks (postmortem verification, calibration audit, event_analyst builder verification) | none | KEEP — already calendared in MEMORY.md |

---

## H. "Do not touch" list (production / governance critical)

These agents and jobs should NOT be modified, paused, or merged without explicit human direction. Each has a documented governance role per memory.

1. **`ops_supervisor` (`agents/ops_supervisor/supervisor.py`, cron 20:30)** — last interpretive layer per `feedback_no_recursive_supervision.md`. Outputs `artifacts/ops_supervisor/{date}_supervisor.{json,md}`. Verified by `tools/agent_supervisor_sentinel.py` (cron 20:40), which writes `_sentinel.md` and is the TERMINUS — nothing supervises it. Per memory: "no further layer above this."
2. **`tools/agent_supervisor_sentinel.py` (cron 20:40)** — sentinel-of-supervisor; reads `2026-05-05_sentinel.md`-style verdict; per `feedback_verify_sentinel_verdict_directly.md`, **read this file directly before acting on rollback recommendations** — downstream monitors can invert trend direction.
3. **`sentinel` agent (`agents/sentinel/`, cron 17:15)** — ruleset health watchdog; consumed by ops_supervisor as one of its inputs.
4. **`postmortem` (cron `agents/postmortem/scripts/run_postmortem.py` 17:40)** — only ground-truth event-resolution writer. Schema `postmortem.v1`. Consumed by calibration_evidence + event_analyst. Critical research feedback.
5. **`crt_resolution_watcher` 18:00** — `mutate_data` authority on `output/catalyst_ev/crt_options_join.json`; the EV layer's truth source. Per CRT memory (101 records, 52 HIT/17 MISS).
6. **`production_qa_check.py` 17:35** + **`data_auditor` 18:00** — daily integrity gates; `production_qa` already YELLOW today (classifier_escalation_pool 56.1%); these are the two checks that fail-stop downstream interpretation.
7. **`cron_daily_production.sh` 16:30** — the actual production run. Out of agent-fleet scope but explicitly a "do not touch" anchor.
8. **`tools/build_calibration_evidence.py` Fri 14:00** + **`tools/build_event_feedback_metrics.py` Fri 14:30** — weekly research-feedback chain; downstream of postmortem.
9. **`policy_alpha_freeze_2026_04_04.md` + `policy_freeze_architecture_2026_04_19.md` regime** — no promotion gates triggered by any agent in this fleet without Checklist v2; agents may PROPOSE only.

---

## I. Final prioritized backlog

### P0 — broken wiring or thesis-conflict (act first)

1. **Fix `policy_shadow_watch` and `bioshort_watch` date-stamp corruption** (Section E rows 1, 2). Both producers are writing today's data with January date stamps, contaminating `history.jsonl` and giving `agent_heartbeat_checks.py` and human reviewers wrong-dated context. Read-only audit cannot fix; recommend a one-shot diagnostic to identify whether the back-loop comes from `cron_evening_catchup.sh:109 run_agent policy_shadow_watch 1805`, the builder's `--as-of-date` resolution, or a separate backfill cron. Risk if executed: low (read-only).
2. **Reconcile production ruleset ID** (`2a3e79eb v1.13.0` per memory of record vs `8887576e v1.14.0` in today's snapshot vs `bebe73f8 v1.10.0` in some other artifacts per `agents/sentinel/memory/2026-05-05.md` line 5). **THIS IS NOT A FLEET ACTION** but a model-control-plane action; agents are correctly flagging it (sentinel WATCH, ops ANOMALY). Per `feedback_pause_between_control_plane_changes.md`, do not stack changes; resolve before accepting any new evidence as load-bearing. **NEEDS_HUMAN_REVIEW.**
3. **Decide `shadow_watch` cutover or retire** (Section D group 1). Half-merged is the worst state.

### P1 — consolidation / merges / reductions

1. **Suppress `ic_health_monitor` LLM escalation when only `inst_delta_z` is anomalous**, until 2026-05-15 13F refresh closes the cohort window (memory `regime_post_cohort_change_distortion_2026_04_28.md`). Saves ~5 daily Sonnet calls.
2. **Reduce `catalyst_delta` surface noise**: filter to (in-universe ∧ catalyst_days ≤ 60) ∧ (HARD events or family-changing codes); current 374 `CTGOV_NEW_TRIAL`/day is mostly registration churn. Keep raw stream as cold archive.
3. **Reduce `grok_biotech_watch` from 4×/day to 2×/day** (drop 12:00; 22:00 already removed).
4. **Move `event_analyst` from daily 18:55 LLM trigger to weekly Friday only** — registry already documents weekly cadence; current daily fire-and-archive wastes Sonnet tokens.
5. **Retire `agents/company_news_ingest/` directory** (registry status=deprecated, cron RETIRED).
6. **Reduce `shadow_monitor` LLM agent step to weekly** — the deterministic `build_shadow_monitor.py` already writes the artifact; the daily LLM `--write-memory` adds little.

### P2 — monitoring improvements

1. **`bioshort_watch` upstream producer needs to be identified or revived**. `output/hedge_report/hedge_report_2026-03-26.json` is the latest; no obvious cron writes new ones. Out of fleet scope but a hedge-discipline gap.
2. **Wire `price_action_watch` outputs into `review_queue_steward` urgency** — currently price_action is human-eyes-only; integrating it would tighten the trap-detection loop without altering scoring.
3. **Add a memory-file write to `shadow_monitor` LLM agent path so `agent_heartbeat_checks.py` can detect missing runs distinctly from missing artifacts** (per registry "Supervised directly by SPECIALIZED_CHECKS['shadow_monitor']"; today only the deterministic path is checked).
4. **Rename `calibration` agent → `promotion_recommender`** for clarity vs `calibration_evidence` (cosmetic; reduces team confusion).
5. **Document `intraday_mover_watch` `memory/` directory state** — registry flags doc gap; either create the empty memory dir (signal for stateless intent) or remove the registry note.

### P3 — retire / reduce-frequency candidates

1. **`bioshort_watch` weekly Friday cron** — PAUSE until upstream `hedge_report` is being refreshed, OR fix per Section E and resume.
2. **`grok_biotech_watch` 12:00 run** — drop.
3. **`event_analyst` daily 18:55 cron** — change to Friday-only.
4. **`shadow_watch` directory** — finish-merge OR delete.
5. **`company_news_ingest` directory** — delete.

---

## Notes on audit method

- **Sources verified directly**: `agents/AGENT_REGISTRY.json`, `crontab -l`, `logs/heartbeat_checks.log` (last entry 2026-05-05 17:30), `logs/agents_direct/` (most recent receipts 2026-05-06 14:35 herald, 2026-05-06 14:30 ctgov_poller), `artifacts/ops_supervisor/2026-05-05_supervisor.md` (live YELLOW verdict), `artifacts/data_auditor/integrity_report_2026-05-05.json` (5/5 PASS), per-agent memory most-recent files.
- **No agents were run** during this audit. No code, cron, or memory edits performed.
- **Consumer verification**: `grep -rln` against `scripts/`, `tools/`, `common/`, `agents/` for each artifact path. Excluded self-references, registries, and test files. Where no consumer was found, the agent is flagged as artifact-without-consumer (`feedback_audit_to_tickets_prompt.md`).
- **Trimmed sections**: B, C, D, E retain all-row coverage; G is full. F was trimmed of low-signal stale-memory-only candidates per the rule "an agent without memory files is not automatically stale."
- **Memory references cited**: `MEMORY.md`, `openclaw_fleet.md`, `feedback_no_recursive_supervision.md`, `feedback_verify_sentinel_verdict_directly.md`, `feedback_observation_bias_cron_monitoring.md`, `feedback_audit_to_tickets_prompt.md`, `feedback_pause_between_control_plane_changes.md`, `regime_post_cohort_change_distortion_2026_04_28.md`, `policy_alpha_freeze_2026_04_04.md`, `policy_freeze_architecture_2026_04_19.md`, `policy_coinvest_context_layer_2026_04_25.md`, `feedback_coinvest_not_alpha.md`, `catalyst_phase_a_verdict_2026_05_04.md`, `runway_severity_architecture.md`, `polymarket_alpha_verdict_2026_05_05.md`, `feedback_runway_severity_architecture.md`, `feedback_agent_governance.md`, `scoring_model_identity_2026_04_06.md`.
- **Today's date**: 2026-05-06.
