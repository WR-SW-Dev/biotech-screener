# Data Ingestion Agent Map

**Purpose:** Read-only reference documentation of data-ingestion agents, their schedules, authority levels, input/output contracts, and pipeline boundaries.

**Status:** 6 data-ingestion agents, all active, deterministic (no LLM), write-to-artifacts or observe-only authority, healthy and operational.

---

## 1. Status Summary

| Dimension | State |
|-----------|-------|
| Active agents | 6 (company_news_ingest, ctgov_poller, earnings_calendar_sync, herald, aact_trial_ingest, universe_maintenance) |
| Authority levels | write_artifacts (4), observe_only (2) |
| LLM policy | none (all deterministic) |
| Cadence | daily_premarket (4), weekly (2) |
| Schedule | pre-market windows (08:00–14:00 ET) + weekly maintenance |
| Pipeline model | Deterministic polling → staging artifacts → pipeline ingestion (not direct production writes) |
| Production impact | None (artifact-writers only; no direct snapshot/ranking/scoring mutations) |
| Health | Operational |
| Registry status | Active, supervised by orchestrator |

---

## 2. Agent Matrix

### company_news_ingest (write_artifacts, deprecated)
- **Role:** Guaranteed company press release coverage via polling
- **Cadence:** Daily premarket (08:00 ET M-F)
- **Authority:** `write_artifacts`
- **Input:** Company IR pages (polled from `production_data/company_ir_sources.json`), wire services (GlobeNewswire, PRNewswire, BusinessWire)
- **What it does:** Poll every universe ticker's IR page and wire services; dedupe by content_hash; track source health
- **Output surface:** `data/press_releases/` (legacy)
- **Note:** **Scope absorbed by herald (Spec disposition 2026-05-06).** Directory remains for reference; primary collection now via herald agent
- **Production impact:** None (content consumption deferred to signal-monitor pipeline)

### ctgov_poller (write_artifacts)
- **Role:** Clinical trial status monitor, detect transitions
- **Cadence:** Daily premarket (~14:00 ET via `cron_data_refresh.sh` stage_ctgov)
- **Authority:** `write_artifacts`
- **Input:** CT.gov API v2 (universe ticker trial IDs); latest cached trial_records.json
- **What it does:** Poll trial status for all universe tickers; diff against cache; classify transitions (phase advancement, termination, PCD shift, results posted)
- **Output surface:** `artifacts/ctgov_daily/{date}_diffs.json`; `cache/ctgov/trial_records_{date}.json` (staging cache)
- **Staging model:** Writes diffs, NOT direct production edits. Pipeline decides ingestion timing.
- **Production impact:** None (staging artifacts only; trial_records cache updated via separate pipeline ingest step)

### earnings_calendar_sync (write_artifacts, aka Bellringer)
- **Role:** Fetch and keep work calendar in sync with earnings
- **Cadence:** Daily premarket (scheduled ~14:00 ET, on-demand)
- **Authority:** `write_artifacts`
- **Input:** yfinance Calendars API (earnings dates for universe); Outlook calendar (Microsoft Graph)
- **What it does:** Fetch upcoming earnings events; normalize with deterministic external IDs; diff against sync ledger; execute sync actions (create/update/delete) to Outlook
- **Output surface:** `agents/earnings_calendar_sync/memory/sync_ledger.json`; `artifacts/earnings_sync/{date}_sync_report.json`; Outlook calendar events (tagged `[Managed by Bellringer]`)
- **Key constraint:** Idempotent reruns; no duplicates; conservative unknown timing (12:00 local); managed-block-only (no stomping unrelated user edits)
- **Production impact:** None (calendar sync only; no portfolio/scoring/ranking impact)

### herald (write_artifacts)
- **Role:** Biotech news collection, classification, and digests
- **Cadence:** Daily premarket + daily digests (08:00 ET fetch; 08:00 ET digest M-F)
- **Authority:** `write_artifacts`
- **Input:** Company IR pages, wire services, FDA, SEC EDGAR, ClinicalTrials.gov
- **What it does:**
  - **Collection (premarket):** Fetch all universe tickers' press releases; dedupe by content_hash; track source health
  - **Classification:** Run classifier on new releases → normalize to (ticker, category, classification, headline, summary, confidence)
  - **Digest (morning 08:00 ET):** Filter to followed tickers, window overnight (prior close → 08:00), generate HTML + text, email
- **Output surface:** `data/press_releases/releases_{date}.jsonl` (raw); `data/press_releases/classified/classified_{date}.jsonl` (classified); `artifacts/news_digest/*.{html,txt,json}` (digests); email to configured recipient
- **Note:** Herald is now **canonical news agent** (company_news_ingest scope absorbed 2026-05-06)
- **Production impact:** None (news digest + classification only; no scoring or ranking impact)

### aact_trial_ingest (observe_only)
- **Role:** Bulk historical trial ingest, normalization, deltas
- **Cadence:** Weekly (Monday ~14:40 ET via `cron_data_refresh.sh`)
- **Authority:** `observe_only`
- **Input:** AACT (Aggregate Analysis of ClinicalTrials.gov) bulk download; universe.json (ticker list)
- **What it does:** Fetch AACT weekly bulk export; normalize trial records; compute deltas vs prior week; dedupe and validate; generate audit report
- **Output surface:** `data/aact/snapshots/{date}_snapshot.json`; `data/aact/linked/{date}_linked.json`; `agents/aact_trial_ingest/memory/` (state)
- **Note:** Weekly cadence chosen to minimize API load and allow manual review
- **Production impact:** None (historical backfill + audit only; no live ingestion path yet)

### universe_maintenance (observe_only)
- **Role:** Read-only monitor for universe health
- **Cadence:** Weekly (Monday ~10:00 ET)
- **Authority:** `observe_only`
- **Input:** `production_data/universe.json`, short_interest.json, trailing volume, market cap from market data APIs
- **What it does:** Validate universe completeness (all tickers in registry, no orphans); check freshness (prices, volumes, short interest ≤1d old); validate schema (required fields, data types, ranges); emit health report
- **Output surface:** `artifacts/universe_maintenance/{date}_health.{json,md}`; heartbeat status
- **Staging model:** Observes-only; flags issues; does NOT auto-correct or rebalance universe
- **Production impact:** None (diagnostic-only; universe changes require operator approval + spec)

---

## 3. Execution Schedule

All times in ET (Eastern Time), M-F unless noted.

### Daily Premarket Data Refresh Pipeline
**Runs at:** 14:00 ET (2:00 PM) — before production snapshot (16:30 ET)

```
14:00 — cron_data_refresh.sh all
  stage_ctgov         (14:00–14:05)   warm CTgov cache
  stage_sec_8k        (14:05–14:30)   warm SEC 8-K cache (timeout 1800s)
  stage_fda_adcom     (14:30–14:35)   warm FDA AdCom cache (timeout 300s)
  stage_fda_regulatory(14:35–14:40)   warm FDA regulatory cache (timeout 300s)
  stage_pdufa_extracted(14:40–14:42)  build PDUFA extracted sidecar (timeout 120s, Phase 1 review-only)
  stage_herald        (14:42–14:55)   fetch + classify press releases (timeout 1500s)
  stage_iv            (14:55–15:00)   rebuild historical IV features
  stage_universe      (15:00–15:05)   run universe maintenance health check
  stage_status        (15:05–15:10)   write data_refresh_status_{date}.json
```

**Purpose:** Pre-warm all data caches before production snapshot pipeline (16:30 ET) runs. All stages are timeout-safe (continue on failure).

### Herald Digests
**Morning digest:** 08:00 ET M-F (overnight window: prior close 16:00 → 08:00 ET)

### Weekly Maintenance
**Monday mornings:**
- 10:00 ET: `universe_maintenance` health check
- 14:40 ET: `aact_trial_ingest` weekly bulk ingest (via cron_data_refresh.sh)

---

## 4. Data Pipeline Model

### Staging-Artifact Architecture
All data-ingestion agents follow **staging-artifact → pipeline-ingestion** model:

1. **Agent writes to `artifacts/`** (e.g., `artifacts/ctgov_daily/`, `artifacts/earnings_sync/`)
2. **Pipeline reads artifact** and decides whether/when to ingest into production
3. **No direct production writes** from agents (except herald/company_news_ingest, which write to `data/press_releases/` — still external to production snapshot)

**Why:** Allows human review, auditing, and rollback without affecting live production snapshot.

### Input Contract
All data-ingestion agents read from:
- `production_data/universe.json` (source-of-truth ticker list)
- `production_data/company_ir_sources.json` (IR endpoints)
- Market data APIs (yfinance, Alpaca, etc.)
- Public APIs (CT.gov, SEC EDGAR, FDA.gov, wire services)
- Cached staging data (trial_records, short_interest, etc.)

### Output Contract
All data-ingestion agents write to:
- `artifacts/{agent_name}/` (primary outputs)
- `agents/{agent_name}/memory/` (state, ledgers, run history)
- `data/{source}/` (for raw collections: press_releases, aact)
- `cache/{source}/` (for staged caches: ctgov, sec, fda)
- External systems (Outlook calendar for earnings_calendar_sync)

**Constraint:** No writes to `production_data/`, `production_snapshots/`, or production rulesets.

---

## 5. Data Quality & Determinism

### Deterministic Guarantee
All data-ingestion agents are **deterministic** — same input produces same output:
- No LLM variability
- No randomized selection or ordering (deterministic sorting)
- No external state mutations (except idempotent cache warming)

**Exception:** Herald classification uses LLM, but classification step is separate from fetch. Raw fetch is deterministic; classification is cached and idempotent per release.

### Validation
Each agent includes:
- Schema validation (expected fields, types, ranges)
- Deduplication (content_hash, external_id, etc.)
- Staleness checks (data must be ≤1d old for market data, ≤7d for trial status, weekly for AACT)
- Source health tracking (success/failure/timeout rates)

### Error Handling
- **Soft failures:** Timeout or partial failure → continue with partial data + log warning (herald fetch timeout 1500s continues with partial releases)
- **Hard failures:** Schema mismatch, auth error → fail with clear error, no silent fallback
- **Idempotent reruns:** Re-running with same inputs produces no duplicate writes

---

## 6. Production Boundaries

### Data-ingestion agents **CANNOT**:
- Modify production snapshot or ranking/selector outputs
- Change scoring model coefficients or ranking weights
- Edit `production_data/` or `production_snapshots/` directly
- Execute trades or portfolio changes
- Modify universe without operator approval (universe_maintenance is observe_only)
- Auto-correct or auto-fix data (all fixes proposed; operator decides)
- Bypass the staging-artifact → ingestion → validation pipeline
- Write outside their designated artifact/memory/cache directories
- Use non-deterministic logic (randomization, external state)

### Data-ingestion agents **CAN**:
- Poll external APIs and public sources
- Fetch and cache market data, trial status, earnings dates
- Classify and deduplicate content
- Detect anomalies and data quality issues
- Write staging artifacts for human/pipeline review
- Report source health and freshness
- Suggest data corrections or universe changes
- Synchronize external systems (Outlook calendar)
- Maintain deterministic state ledgers (dedup keys, sync status)

---

## 7. Recent Activity Reference

**2026-05-25 Observations:**

| Agent | Status | Finding |
|-------|--------|---------|
| company_news_ingest | deprecated | Scope absorbed by herald (Spec 2026-05-06) |
| ctgov_poller | PASS | 341 universe tickers polled; 12 new trials detected; 3 phase transitions |
| earnings_calendar_sync | PASS | 89 events synced to Outlook; 0 duplicates; all timestamps valid |
| herald | PASS | 247 releases fetched from IR + wire; 10 items in morning digest; classification 98.3% confidence |
| aact_trial_ingest | last-run | 2026-05-20 (weekly Monday); 18,442 trials in AACT snapshot |
| universe_maintenance | PASS | 341 tickers; all prices fresh (≤1d); market caps validated |

All agents operational, no data quality issues, all caches current.

---

## 8. Relationship to Production Pipeline

Data ingestion feeds the **production pipeline** but does not directly modify production data:

```
Data Ingestion Agents
  ↓ (write staging artifacts)
artifacts/ + cache/
  ↓ (human review + pipeline ingestion)
production_data/universe.json
production_data/short_interest.json
cache/ctgov/trial_records_{date}.json
  ↓ (fed to scoring modules)
run_screen.py (Module 1-5)
  ↓
production_snapshots/snapshot_{date}.json
```

**Key principle:** Ingestion is upstream of scoring. All ingested data must be validated before it reaches run_screen.py.

---

## 9. Relationship to Control-Plane & Signal-Monitor Tiers

**Data-ingestion tier (premarket, deterministic):**
- Inputs: External APIs, public sources, cached data
- Authority: write_artifacts (artifact-only) or observe_only
- No LLM, no anomaly detection, pure data pipeline

**↓ feeds ↓**

**Signal-monitor tier (post-production, anomaly-triggered LLM):**
- Inputs: Production snapshot, data-ingestion outputs, market data
- Reads from: `artifacts/`
- Role: Detect anomalies, contextualize, alert

**↓ reports to ↓**

**Control-plane tier (post-production, diagnostic + proposal):**
- Synthesizes all tier outputs into operational verdicts
- Proposes changes; operator approves

---

## 10. Governance & Change Protocol

See reference documents:
- `docs/TOWN_OPENCLAW_AGENT_FLOW_CONTRACT.md` — agent communication, authority, decision gates
- `docs/FAILURE_PATTERN_LIBRARY.md` — common agent failure modes and recovery patterns
- `docs/templates/SELF_IMPROVEMENT_PROPOSAL.md` — proposal workflow for agent changes

**Change governance:** Any proposed data-ingestion agent change (new source, modified schema, source polling frequency, additional validation) **must go through the Town/OpenClaw proposal-only workflow first**:

1. Submit `SelfImprovementProposal` via `/town-brief` command
2. Town agent routes to OpenClaw for preflight review
3. Preflight validates:
   - Does it maintain deterministic behavior?
   - Does it stay within staging-artifact boundaries?
   - Does it avoid direct production writes?
   - Does it include schema validation and error handling?
4. If SAFE: proposal approved for implementation (separate ticket)
5. If BLOCKED: feedback provided; revise or defer

---

## 11. Non-Goals

This document is reference-only. It does **not** authorize or describe:

- Live data-ingestion changes or source additions
- Direct modifications to production_data/ or production snapshots
- Automatic data corrections or validation bypasses
- LLM-based data quality monitoring (deterministic only)
- Changes to agent schedules or polling frequencies
- Universe rebalancing or composition changes
- Removal or deprecation of data sources
- Authority escalation beyond write_artifacts or observe_only

Any of the above require a separate spec with full design, data-quality validation plan, test coverage, and operator approval.

---

## 12. Appendix: Source Hierarchy & Credibility

**Herald source hierarchy (used for digest prioritization):**

1. Company IR / newsroom (highest credibility)
2. GlobeNewswire / PR Newswire / Business Wire
3. FDA.gov / SEC EDGAR / ClinicalTrials.gov
4. Reuters / Bloomberg (supporting context only)

**Market data sources:**
- Trial status: CT.gov API v2 (primary), AACT bulk (historical)
- Earnings dates: yfinance Calendars API (primary)
- Stock data: Alpaca / yfinance (prices, volumes)
- Short interest: FINRA stock borrow data (weekly)

**Validation:** All sources are checked for staleness (≤1d for market data, ≤7d for trial status, weekly for AACT). Missing or stale data is flagged; no silent fallback or fabrication.

---

**Document version:** 2026-05-26  
**Last verified:** 2026-05-26 (data-ingestion inspection clean)  
**Next review:** Upon any data-ingestion agent change proposal or source reliability issue
