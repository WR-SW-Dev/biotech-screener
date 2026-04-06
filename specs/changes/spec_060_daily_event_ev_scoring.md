# Spec 060 — Daily Event EV Scoring

**Status**: IMPLEMENTED
**Author**: Claude / arrenchulz
**Date**: 2026-04-06
**Ruleset impact**: NO (diagnostic/operator-facing only — no selector/ranker/construction changes)

---

## Objective

Wire the Event EV engine (Spec 057) into the daily production cycle so it produces a scored catalyst leaderboard every trading day. This makes the EV engine operational rather than research-only, enabling the operator to see: *"Which catalysts in my universe have the highest expected value right now, and why?"*

## Policy Constraint

**Diagnostic only.** The EV scores do NOT feed the selector, ranker, or construction.
The alpha stack is frozen. This spec produces **operator-facing artifacts** for situational awareness, not trading signals.

When the EV engine accumulates enough forward evidence (calibrated CRT resolutions, timing accuracy, outcome model Brier score), a separate promotion spec would be required to wire EV into any decision path.

## Scope

### What this spec does

1. **Daily EV scoring step** in `run_daily_production.py` (Step 5k.21)
   - Builds catalyst graph from existing data sources (PDUFA dates, catalyst events, event ledger, CRT)
   - Loads market features from the just-promoted snapshot
   - Runs `EventEVCalculator` on the actionable cohort (0-180d window)
   - Writes artifacts to `artifacts/event_ev/`

2. **Production scoring tool** (`tools/build_event_ev_scores.py`)
   - Standalone tool callable from daily production or ad-hoc
   - Reuses `load_catalyst_graph()` and `load_market_features()` from research harness
   - Produces: `{date}_event_ev_scores.json`, `{date}_ev_leaderboard.json`, `{date}_ev_leaderboard.md`
   - Includes Spec 059 overlays: branch sensitivity, surface anomalies, risk alerts

3. **Dashboard endpoints**
   - `GET /api/event_ev/leaderboard/{date}` — top-N catalysts by downside-adjusted EV
   - `GET /api/event_ev/detail/{ticker}/{date}` — full EventEV breakdown for one name
   - `GET /api/event_ev/history` — recent leaderboard snapshots for trend tracking

### What this spec does NOT do

- Feed EV into the ranker or selector
- Change portfolio construction or position sizing
- Promote any signal from the EV engine
- Tune or calibrate the outcome model (CRT-dependent, accumulating)
- Replace existing timing hazard dashboard (complementary)

## Architecture

```
run_daily_production.py
  └─ Step 5k.21: Event EV scoring (non-blocking)
       └─ tools/build_event_ev_scores.py
            ├─ load_catalyst_graph(as_of)     ← from research harness
            ├─ load_market_features(as_of)    ← from research harness
            ├─ EventEVCalculator.run_from_graph()
            ├─ Spec 059 overlays (branch_sensitivity, surface_diagnostics)
            └─ Write artifacts:
                 ├─ {date}_event_ev_scores.json   (full EventEV per catalyst)
                 ├─ {date}_ev_leaderboard.json    (compact summary table)
                 └─ {date}_ev_leaderboard.md      (operator-readable memo)

dashboard/app.py
  ├─ GET /api/event_ev/leaderboard/{date}
  ├─ GET /api/event_ev/detail/{ticker}/{date}
  └─ GET /api/event_ev/history
```

## Inputs

| Input | Source | Schema |
|-------|--------|--------|
| PDUFA dates | production_data/pdufa_dates.json | list of {ticker, date, disclosed_at} |
| Catalyst events | production_data/catalyst_events_*.json | {summaries: [...]} |
| Event ledger | data/catalyst_history/catalyst_history_events.jsonl | JSONL of ledger entries |
| CRT resolutions | data/snapshots/resolutions/**/*.json | resolution records |
| Rankings snapshot | data/snapshots/{date}/rankings.csv | full rankings row per ticker |
| Options forward log | data/snapshots/{date}/options_forward_log.json | Spec 059 implied moves |
| CRT calibration | data/snapshots/resolutions/ | for outcome model priors |

## Outputs

| Output | Destination | Schema |
|--------|-------------|--------|
| Full EV scores | artifacts/event_ev/{date}_event_ev_scores.json | List[EventEV.to_dict()] |
| EV leaderboard | artifacts/event_ev/{date}_ev_leaderboard.json | Compact summary table |
| Operator memo | artifacts/event_ev/{date}_ev_leaderboard.md | Markdown digest |
| Dashboard data | /api/event_ev/leaderboard/{date} | JSON response |

### Leaderboard columns

| Column | Description |
|--------|-------------|
| rank | EV rank (by downside-adjusted EV) |
| ticker | |
| event_type | PDUFA, DATA_READOUT, etc. |
| days_to_event | Calendar days from as_of |
| p_hit / p_miss | Outcome model probabilities |
| implied_p_hit | Market expectation (crowd belief) |
| mispricing | model p_hit - market implied_p_hit |
| upside_hit / downside_miss | Branch moves (%) |
| scenario_ev | Probability-weighted EV (%) |
| ds_adj_ev | Downside-adjusted EV (%) |
| breakeven_straddle | Options breakeven move (Spec 059) |
| term_shape | Surface shape (Spec 059) |
| risk_alert | Escalated risk flag (Spec 059) |
| timing_on_time | P(on time) from timing model |
| analog_conf | ok / low / insufficient |

## Invariants

1. **No production impact** — zero changes to selector_engine, ranker_engine, decision_engine, or construction
2. **Non-blocking** — daily production completes even if EV scoring fails (try/except wrapper)
3. **PIT-safe** — catalyst graph respects disclosed_at; market features from current snapshot only
4. **Idempotent** — same date + same snapshot → same output
5. **Graceful degradation** — missing data sources → fewer nodes in graph, not errors

## Failure Modes

| Scenario | Expected behavior |
|----------|-------------------|
| No PDUFA dates | Graph has fewer regulatory nodes; continues |
| No catalyst events | Graph has only PDUFA + ledger nodes |
| Empty graph (no actionable events) | Empty leaderboard, log warning |
| Rankings CSV missing | No market features; EV uses prior defaults |
| Outcome model has no CRT calibration | Falls back to Wong et al. base rates |
| Options data absent for a name | branch_sensitivity = null for that name |

## Validation Plan

### Tests (write BEFORE implementation)
- [ ] `test_build_event_ev_scores_happy_path` — produces leaderboard from fixture data
- [ ] `test_empty_graph_produces_empty_leaderboard` — graceful on no events
- [ ] `test_leaderboard_sorted_by_ds_adj_ev` — correct sort order
- [ ] `test_leaderboard_columns_present` — all expected columns
- [ ] `test_spec059_overlays_attached` — branch_sensitivity populated for liquid names
- [ ] `test_operator_memo_renders` — markdown output is valid
- [ ] `test_idempotent` — same inputs → same outputs
- [ ] `test_missing_data_graceful` — missing PDUFA/ledger → still runs

### Integration
- [ ] Full suite passes
- [ ] Existing event_ev tests unaffected
- [ ] run_daily_production.py runs cleanly with new step
- [ ] Dashboard endpoint returns valid JSON

## Expected Effect Size

**No direct alpha impact.** Expected benefits:
- Operator sees daily EV-ranked catalyst leaderboard (replaces ad-hoc research runs)
- Forward evidence accumulation: daily EV snapshots enable future calibration studies
- Spec 059 overlays (branch Greeks, surface anomalies, risk alerts) rendered alongside EV
- Foundation for eventual EV-informed overlays (requires separate promotion spec)

## Non-Goals

- EV as ranker/selector input
- Automated trade recommendations from EV
- Outcome model tuning or recalibration
- Timing model improvements
- CRT-dependent work (CRT grows passively)

---

## Implementation Plan

### Phase A — Scoring Tool
1. Extract `load_catalyst_graph()` and `load_market_features()` from research harness into reusable module
2. Build `tools/build_event_ev_scores.py` with `build_scores(as_of_date) → dict`
3. Produce JSON + leaderboard + markdown artifacts
4. Tests

### Phase B — Daily Production Wiring
1. Add Step 5k.21 to `run_daily_production.py`
2. Non-blocking try/except, logs summary
3. Verify full daily cycle runs cleanly

### Phase C — Dashboard
1. Add `/api/event_ev/leaderboard/{date}` endpoint
2. Add `/api/event_ev/detail/{ticker}/{date}` endpoint
3. Add `/api/event_ev/history` endpoint (last 30 days)

---

## Implementation Log

### 2026-04-06 — All three phases implemented

**Phase A — Scoring Tool**
- `event_ev/loaders.py`: shared `load_catalyst_graph()`, `load_market_features()`, `split_context_features()` extracted from research harness
- `tools/build_event_ev_scores.py`: `build_scores()` → full EV pipeline + leaderboard + markdown memo + artifact writing
- Standalone CLI: `python tools/build_event_ev_scores.py --as-of 2026-04-06`
- Tests: `tests/test_build_event_ev_scores.py` (8 tests)

**Phase B — Daily Production Wiring**
- Step 5k.21 in `tools/run_daily_production.py` — non-blocking, logs summary line
- Outputs: `artifacts/event_ev/{date}_event_ev_scores.json`, `_ev_leaderboard.json`, `_ev_leaderboard.md`, `_event_ev_full.json`

**Phase C — Dashboard**
- `GET /api/event_ev/leaderboard/{date}` — compact leaderboard
- `GET /api/event_ev/detail/{ticker}/{date}` — full EventEV for one name
- `GET /api/event_ev/history` — recent snapshots for trend tracking

**125 tests passing (8 new + 117 existing event_ev/Spec 059).**
**Zero changes to selector_engine.py, ranker_engine.py, or decision_engine.py.**
