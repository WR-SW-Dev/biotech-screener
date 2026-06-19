# Scientific Cartography LangGraph LG4 — Dashboard Design

## Status

**LANGGRAPH_PHASE_LG4_DASHBOARD_DESIGN**

```
DESIGN_ONLY
NO_RUNTIME_DASHBOARD
NO_PRODUCTION_HOOK
NO_SCORING_UI
NO_AUTOMATION_APPROVAL
```

This document specifies the dashboard design for Scientific Cartography LangGraph review artifacts. **No implementation code is included.** No dashboard runtime, server, cron job, or production hook is enabled or approved.

---

## Purpose

LG4 is a **read-only artifact browser** for Scientific Cartography review outputs (LG1/LG2/LG3). It surfaces review runs, disease maps, human decisions, and scheduled execution health to enable operators and researchers to explore review artifacts without requiring command-line tools.

**Core design principle**: LG4 does not compute scores, make recommendations, rank assets, rank companies, size positions, or approve automation.

---

## Non-Goals

Explicitly out of scope:

- Dashboard server or API deployment
- Integration into production pipeline
- Cron job or automated triggers
- Scoring, ranking, or sizing UI
- Portfolio action recommendation
- Trading or execution interface
- LLM-powered summarization or decision automation
- Authentication or multi-user access control
- Real-time data updates
- Production data access

---

## Current LG1/LG2/LG3 Baseline

### LG1: Standalone Review Orchestrator
- Deterministic LangGraph workflow
- Reads artifacts, generates review summary (JSON + Markdown)
- Outputs to `artifacts/scientific_cartography/<as_of_date>/review/`
- Status: OPERATIONAL

### LG2: Human Decision Artifacts
- CLI flags: `--approve-review`, `--reject-review`, `--hold-review`
- Appends decisions to JSONL audit trail
- Governance: automation_approval immutably False
- Status: OPERATIONAL

### LG3: Scheduled Review Runtime
- Cron-compatible wrapper (Mode B)
- Auto-detects latest snapshot, invokes LG1, logs to JSONL
- Non-blocking failure (exit 0 always)
- Status: OPERATIONAL, observation period 2026-06-19 to 2026-07-03

---

## Design Principle

**LG4 is a read-only artifact browser for Scientific Cartography review outputs.**

LG4 does not compute scores, make recommendations, rank assets, rank companies, size positions, or approve automation.

All displayed data is sourced from existing artifacts. No live computation, no model integration, no decision engine.

---

## User Workflow

```
1. Operator opens dashboard (static or local server)
2. Dashboard displays index of available review runs (by as_of_date)
3. Operator selects a run to explore
4. Dashboard shows:
   - Review summary (LG1 output)
   - Disease maps (disease_map_index.json + individual disease_map.json files)
   - Human decisions (langgraph_human_decisions.jsonl)
   - Scheduled execution health (scheduled_review_audit.jsonl)
5. Operator can filter/sort disease maps by name, program count, or artifact date
6. Operator can export or download artifacts for offline analysis
7. Dashboard always displays governance panel (all flags false except read_only_diagnostic)
```

---

## Dashboard Data Sources

The dashboard reads **artifact files only**. No live data, no production database, no API integration.

### LG1 Outputs
```
artifacts/scientific_cartography/<as_of_date>/review/langgraph_review_summary.json
artifacts/scientific_cartography/<as_of_date>/review/langgraph_review_summary.md
artifacts/scientific_cartography/<as_of_date>/review/langgraph_review_state.json
```

### LG2 Outputs
```
artifacts/scientific_cartography/<as_of_date>/review/langgraph_human_decisions.jsonl
```

### LG3 Outputs
```
artifacts/scientific_cartography/<as_of_date>/review/scheduled_review_audit.jsonl
```

### Disease Map Index
```
artifacts/scientific_cartography/<as_of_date>/disease_map_index.json
artifacts/scientific_cartography/<as_of_date>/diseases/*/disease_map.json
artifacts/scientific_cartography/<as_of_date>/diseases/*/disease_map.md
```

### Forbidden Data Sources
```
❌ rankings.csv
❌ portfolio_positions.csv
❌ screen_output.json
❌ production_data/*
❌ run_screen.py internals
❌ selector outputs
❌ sizing outputs
❌ final_score outputs
❌ trading/order systems
❌ live market data
```

---

## Read-Only Surface Area

The dashboard is strictly read-only. No writes to artifacts, no file mutations, no cache updates, no decision capture.

**Write operations are forbidden.** Human decisions are captured via CLI (`--approve-review`, `--reject-review`, `--hold-review` flags) on the orchestrator itself, not via dashboard UI.

---

## Proposed Views

### View 1: Review Run Index

**Purpose**: Display available Scientific Cartography review runs and their status.

**Data source**: Scan `artifacts/scientific_cartography/` for date directories; read `langgraph_review_summary.json` and `langgraph_human_decisions.jsonl` from each.

**Columns**:
| Field | Source | Example |
|-------|--------|---------|
| as_of_date | Directory name | 2026-06-19 |
| Review present | File exists | ✓ |
| Last updated | File mtime | 2026-06-19 18:05 UTC |
| Governance scan | review_state.json | PASSED |
| Decision state | human_decisions.jsonl | APPROVED_FOR_REVIEW_CONTINUATION |
| Human decisions | Count in JSONL | 1 |
| Disease count | disease_map_index.json | 42 |
| Review summary link | Path | artifacts/scientific_cartography/2026-06-19/review/ |

**Interaction**:
- Click row to open disease map browser for that date
- Sort by date (newest first), disease count, decision state
- No ranking, no scoring, no "priority" labels

---

### View 2: Disease Map Browser

**Purpose**: Browse disease map artifacts for human research review.

**Data source**: `disease_map_index.json` + individual `disease_map.json` files.

**Columns**:
| Field | Source | Example |
|-------|--------|---------|
| Disease name | disease_map.json | Type 2 Diabetes |
| MONDO ID | disease_map.json | MONDO:0005148 |
| Program count | disease_map.json | 847 |
| Cluster count | disease_map.json | 64 |
| Context features | disease_map.json | 12 |
| Unknown fields | coverage_report | 0 |
| Artifact link | Path | diseases/type-2-diabetes/disease_map.json |

**Interaction**:
- Click disease name to open `disease_map.md` (rendered or raw)
- Click MONDO ID to link to MONDO database
- Sort by: disease name (A-Z), program count (high to low), cluster count, artifact date
- Filter by MONDO ID range or program count threshold

**Hard rule**: No ranking language. Forbidden labels: "best," "most attractive," "top investment," "priority," "rank," "score," "conviction." Only sorting allowed: alphabetical, numeric count, date.

---

### View 3: Human Decision Audit Trail

**Purpose**: Display LG2 human decision records for review workflow continuation.

**Data source**: `langgraph_human_decisions.jsonl` (append-only).

**Columns**:
| Field | Source | Example |
|-------|--------|---------|
| Created (UTC) | decision_created_at_utc | 2026-06-19T14:30:00Z |
| Decision | decision_state | APPROVED_FOR_REVIEW_CONTINUATION |
| Actor | decision_actor | alice@example.com |
| Reason | decision_reason | Review artifacts validated |
| Review approved | review_continuation_approved | true |
| automation_approval | automation_approval | false |

**Display rule**:
- automation_approval must **always** be displayed as a separate, prominent column
- If automation_approval is ever true, dashboard must highlight as **GOVERNANCE VIOLATION**
- Show full decision_reason text (may be multi-line)

**Interaction**:
- Sort by created date (newest first)
- Filter by decision_state
- Download as CSV/JSON
- No write access

---

### View 4: Scheduled Review Health

**Purpose**: Display LG3 wrapper execution health and audit trail.

**Data source**: `scheduled_review_cron.jsonl` (append-only, one entry per cron execution).

**Columns**:
| Field | Source | Example |
|-------|--------|---------|
| Executed (UTC) | executed_at_utc | 2026-06-19T13:05:00Z |
| Status | outcome | success |
| Exit code | implicit (0 always) | 0 |
| Duration (sec) | duration_seconds | 45.2 |
| As-of date | as_of_date | 2026-06-19 |
| Error summary | error_message | (truncated if > 200 chars) |
| Non-blocking | governance.non_blocking | true |

**Display rule**:
- Scheduled review failure is diagnostic only. Do not show as production failure.
- Always display "Exit code: 0 (non-blocking)" even if outcome is "failure"
- If error_message is long, provide "View full error" modal

**Interaction**:
- Sort by executed date (newest first)
- Filter by status (success/failure)
- Expand row to view full error_message
- Download as CSV/JSON

---

### View 5: Governance / Boundary Panel

**Purpose**: Make governance boundaries explicit to operators and researchers.

**Data source**: Metadata from review state and wrapper audit trail.

**Display**:
```
SCIENTIFIC CARTOGRAPHY REVIEW — GOVERNANCE BOUNDARIES

READ_ONLY_DIAGNOSTIC: ✓ true
PRODUCTION_MODEL_CHANGE: ✗ false
RANKER_CHANGE: ✗ false
SELECTOR_CHANGE: ✗ false
SIZING_CHANGE: ✗ false
FINAL_SCORE_CHANGE: ✗ false
TRADING_OR_PORTFOLIO_ACTION: ✗ false
AUTOMATION_APPROVAL: ✗ false (IMMUTABLE)

No scoring is performed.
This is a diagnostic artifact browser, not an investment decision system.
No ranker/selector/sizing/final_score integration.
No automation approval cascade.
```

**Display rule**:
- Always visible (footer, sidebar, or modal)
- Use green checkmark for true, red X for false
- Highlight automation_approval with warning color (red background)
- Provide link to governance documentation

---

## Data Contract

### File Discovery Rules

Dashboard must handle missing/stale artifacts gracefully:

```
IF artifact file missing:
  → Display "not yet available" message
  → Do not error

IF artifact file stale (>7 days):
  → Display warning badge
  → Show last modified timestamp

IF directory structure nonstandard:
  → Log diagnostic message
  → Skip malformed date directories
  → Continue with valid directories
```

### Failure / Missing Artifact Behavior

**Graceful degradation**:
- If `langgraph_review_summary.json` missing: show "Review not yet generated"
- If `langgraph_human_decisions.jsonl` missing: show "No decisions recorded"
- If `scheduled_review_audit.jsonl` missing: show "Scheduled audit trail not yet created"
- If `disease_map_index.json` missing: show "Disease maps not yet indexed"

**Never crash** on missing artifacts. Always provide user-friendly fallback.

---

## Security and Safety Boundaries

### No Authentication Required
LG4 is read-only and artifact-only. Authentication is not required. The dashboard operates on already-committed, immutable artifact files.

### No Live Data Integration
Dashboard reads snapshots only. No live market data, no real-time portfolio, no trading system integration.

### No Decision Capture
Dashboard does not capture human decisions. Decision capture happens via CLI (`--approve-review`, `--reject-review`, `--hold-review`).

### No Access to Production Systems
Dashboard has no access to:
- Portfolio positions
- Ranking engine
- Selector
- Sizing engine
- Final score computation
- Trading execution

### No External API Calls (Optional)
Recommended: Dashboard is fully local/static and makes no external API calls. If MONDO ID links are included, use read-only public API only.

---

## No-Scoring UI Rules

The dashboard must **forbid** the following language in the UI:

Forbidden terms (anywhere in UI):
```
score, alpha, rank, rating, buy, sell, recommend, conviction, weight, attractive, 
expected_return, portfolio action, position sizing, priority, top, best, outperform, 
underperform, overweight, underweight, target allocation, momentum score
```

**Exception**: Governance disclaimers may use these terms when quoting the governance rules:

```
"This dashboard does not perform scoring, ranking, or portfolio action recommendation."
```

---

## Implementation Options

### Option A: Static HTML Generator

**Approach**: Python script generates static HTML from artifacts.

**Characteristics**:
- No server, no cron, no authentication
- Run manually: `python3 tools/generate_lg4_dashboard.py --output-dir ./dashboard/`
- Outputs: `index.html`, `review_<date>.html`, `assets/` (CSS, JS)
- Refresh: Re-run script daily or on-demand
- Deployment: Commit HTML to repo or serve from S3

**Pros**:
- Lowest risk
- No runtime dependencies
- Git-friendly (if committed)
- Works offline
- Fastest to build

**Cons**:
- Requires manual refresh
- Limited interactivity
- Static sorting/filtering (baked into HTML)

**Recommendation**: **Use Option A for LG4A (first implementation).**

### Option B: Local Streamlit Viewer

**Approach**: Streamlit app runs locally, reads artifacts, renders interactive views.

**Characteristics**:
- Streamlit framework (Python)
- Run: `streamlit run tools/lg4_dashboard.py`
- Interactive filtering, sorting, search
- Live artifact refresh (on page reload)
- No server deployment needed

**Pros**:
- Interactive UI
- Rich filtering and search
- Quick to prototype
- Familiar to data scientists

**Cons**:
- Streamlit dependency
- Slightly slower cold start
- Less "production-like"
- Requires Python runtime

**Recommendation**: **Use Option B only after Option A is stable (LG4B, deferred).**

### Option C: Existing Internal Dashboard Integration

**Approach**: Integrate LG4 views into existing internal dashboard (if one exists).

**Characteristics**:
- Embeds LG4 panels into dashboard
- Uses existing auth, styling, infrastructure
- Shared codebase with other dashboard features

**Pros**:
- Single UI for all tools
- Shared infrastructure

**Cons**:
- Highest risk
- Requires coordination with dashboard team
- May introduce production dependencies
- Governance approval needed separately

**Recommendation**: **Defer Option C. Not for LG4A.**

---

## Recommended Implementation Path

### LG4A: Static HTML Generator (No Runtime)
1. Write `tools/generate_lg4_dashboard.py`
2. Outputs static HTML to `./artifacts/lg4_dashboard/` (gitignored)
3. Operator runs manually: `python3 tools/generate_lg4_dashboard.py`
4. Opens `artifacts/lg4_dashboard/index.html` in browser
5. No server, no cron, no production hook

**Timeline**: 1-2 weeks (after observation checkpoint ~2026-07-03)

### LG4B: Streamlit Viewer (Optional, Deferred)
1. Build interactive Streamlit app
2. Operator runs: `streamlit run tools/lg4_dashboard.py`
3. Requires separate operator approval
4. Not for LG4A

**Timeline**: Q3 2026 or later

### LG4C: Dashboard Integration (Optional, Deferred)
1. Design integration with existing dashboard
2. Requires separate governance approval
3. Not for LG4A

**Timeline**: TBD

---

## Acceptance Criteria

LG4 design is complete when:

- [x] Dashboard design document exists (this file)
- [x] Data sources are artifact-only (no live data, no production integration)
- [x] No code implemented (design-only)
- [x] No dashboard runtime created
- [x] No production files changed
- [x] No scoring/ranking/action language in UI
- [x] Three implementation options documented
- [x] Static HTML generator recommended as first runtime path
- [x] LG4 runtime (implementation) requires separate operator approval
- [x] Governance boundaries explicit in design

**LG4 design is ready for review.**

---

## Explicitly Deferred

**Not included in LG4A**:

- Dashboard implementation code
- Dashboard server or API
- Cron job or automated dashboard generation
- Streamlit app
- React/Vue frontend
- Authentication system
- Real-time data updates
- Production hook integration
- Scoring or ranking UI
- Portfolio action recommendations
- Integration with portfolio systems
- LLM-powered summarization
- Automatic decision engine
- Multi-user collaboration features
- Websocket or live push updates

These are **future enhancements**, not in scope for design phase.

---

## Next Steps

1. **Design review**: ~2026-07-03 (after LG3 observation checkpoint)
2. **Operator approval for LG4A runtime** (separate decision gate)
3. **Implementation of LG4A** (if approved): 1-2 weeks
4. **Deployment**: Static HTML to artifacts/lg4_dashboard/
5. **Optional LG4B/LG4C** deferred to future

---

**Design status**: COMPLETE (design-only, not committed)  
**Implementation**: Awaiting separate approval  
**Governance**: All invariants preserved (read-only, diagnostic, no automation approval)
