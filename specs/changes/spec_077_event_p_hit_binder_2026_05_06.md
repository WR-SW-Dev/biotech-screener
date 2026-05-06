# Spec 077 — Event-Level P(HIT) Binder (2026-05-06)

**Status:** Scoping ticket. Blocks Event EV calibration. Shadow-only — no production changes.

**Origin:** Post-binder sanity audit (2026-05-06) found that `prediction_composite_score` is the wrong
field for EV calibration. It is a screener/stock-quality composite (coinvest + financial + inst_delta),
not an event-level probability of catalyst success. It has 12 distinct values, 79% in 4 buckets,
inverted HIT rate (Hi bucket = worst), Brier worse than baseline. The correct field — `p_hit` from
`event_ev/outcome_model.py` — exists in daily artifact JSON but is never written into resolution records.

**Hard constraints (do not touch):**
- No selector/ranker/EV scoring changes
- No production ranking changes
- No promotion of any signal
- No change to `confidence_overall`, `prediction_composite_score`, or `final_score` semantics
- No fabricated historical probabilities

---

## 1. Findings from diagnostic pass

### 1a. `p_hit` already exists — correct field

**File:** `artifacts/event_ev/{YYYY-MM-DD}_event_ev_full.json`

Structure:
```
events[i].node.node_id        → "e03d3d883c6e"  (stable hash, join key)
events[i].node.ticker         → "BEAM"
events[i].node.expected_date  → "2025-07-01"
events[i].node.event_type     → "DATA_READOUT"
events[i].outcome.p_hit       → 0.5577          ← THIS is the correct field
events[i].outcome.p_miss      → 0.2623
events[i].outcome.p_mixed     → 0.18
events[i].outcome.confidence  → 0.61            ← EV model confidence (not data quality)
```

Producer: `event_ev/outcome_model.py → OutcomeModel.estimate()`

Bayesian posterior. Phase-specific priors from Wong et al. (Phase 1: 63%, Phase 2: 42%,
Phase 3: 58%, PDUFA: 85-90%). Updated by endpoint_strength, design_quality,
clinical_transmission, log-odds updates.

Coverage: 445 daily artifact files from 2020-01-03 → 2026-05-05. 16 post-PIT-valid artifacts
(2026-04-13 onward). ~400 events per artifact (current: 416 on 2026-05-05).

### 1b. Why `p_hit` is NOT bound today

The EV module is a separate compute lane. `build_event_ev_scores.py` runs nightly and writes
`artifacts/event_ev/{date}_event_ev_full.json`, but:
- Does NOT write `p_hit` to `data/snapshots/{date}/rankings.csv`
- Does NOT write `p_hit` to `data/snapshots/resolutions/` CRT records
- Does NOT write `p_hit` to `artifacts/postmortem/` records

The binder in `tools/event_outcome_binder.py` joins clinical shadow → resolution outcomes (HIT/MISS),
but does NOT do the reverse: prediction-time EV → resolution records.

`tools/catalyst_resolution_tracker.py ResolutionRecord` schema (line 116) has no `event_ev_p_hit`
field. The only prediction field added by spec_073 was `prediction_composite_score` (screener quality).

### 1c. Join strategy problem — (ticker, date) join fails

Attempted post-PIT join using `(ticker, catalyst_date ±30d)` against closest EV artifact:

| Result | Count | % |
|--------|-------|---|
| Exact match (0d) | 4 | 9% |
| ≤30d window | 6 | 14% |
| ≤60d window | 3 | 7% |
| No match (>60d or absent) | 30 | 70% |

Root cause: EV `expected_date` is a FORWARD-LOOKING estimate (when the event is expected);
CRT `catalyst_date` is the ACTUAL resolution date. They diverge because:
1. Many CRT records track future-pending events (catalyst_date in 2026-06 through 2027)
2. For resolved events, the EV date can slip by 36-62+ days vs actual resolution date
3. ~33% of tickers in CRT are not tracked by the EV model at all (9999d distance)

**(ticker, date) join is not safe as a primary key.** It would bind wrong events
or silently leave 70% null.

### 1d. Correct join key: `node_id`

The event store in `event_ev/event_store.py` uses `node_id` (6-byte hex hash) as the stable
event identifier. The clinical shadow (`tools/clinical_transmission_shadow.py`) already
uses `catalyst_id` = `node_id` as its row key (added in commit `67697d6c7`).

The CRT resolution records do NOT record `node_id`. That is the gap.

**Fix:** At CRT resolution time, look up the matching event node from the event store (same
source the EV model uses) and record its `node_id`. Then bind `p_hit` from the EV artifact
dated closest to `prediction_snapshot_date` using `node_id` as the join key.

### 1e. Backfill is NOT safe

Historical CRT records have no `node_id`. The (ticker, date) windowed join has 30% match rate.
Binding wrong p_hit values is worse than null. **Backfill not recommended.**
Forward-only from implementation date.

### 1f. Post-PIT sample too small for calibration now

Post-PIT-valid HIT/MISS records: **7** (5 HIT, 2 MISS).
Required for meaningful calibration: ≥30 HIT/MISS with non-null `event_ev_p_hit`.
Estimated arrival at current cadence: ~2026-06-15 to 2026-07-01.
The 2026-05-22 review date is too early — push verdict to 2026-07-01 or later.

---

## 2. Candidate input fields (inputs to outcome_model, NOT direct P(HIT) proxies)

These exist in snapshots but are INPUTS to the EV model — not calibrated outcome probabilities.
Do not use them as P(HIT) substitutes.

| Field | Where | What it is | Use |
|-------|-------|-----------|-----|
| `endpoint_strength_score` | rankings.csv | Clinical endpoint rigor [0,1] | Input to EV |
| `design_quality_score` | rankings.csv | Study design rigor [0,1] | Input to EV |
| `binary_quality_score` | rankings.csv | Event quality tiebreaker [0,1] | Input to EV |
| `calendar_confidence` | rankings.csv | Confidence in catalyst DATE [0,1] | Not P(HIT) |
| `conditional_confidence` | rankings.csv | Diagnostic only [0,1] | Not P(HIT) |
| `confidence_overall` | rankings.csv | Data quality blend [0.68-0.90] | Not P(HIT) |

None of these are calibrated per-event success probabilities. `event_ev_p_hit` is the only
correct field.

---

## 3. Minimal forward-only implementation

### 3a. Schema additions (shadow-only)

Add to `ResolutionRecord` in `tools/catalyst_resolution_tracker.py`:

```python
event_ev_node_id: Optional[str] = None        # EV event store node_id for exact join
event_ev_p_hit: Optional[float] = None        # decision-time P(HIT) from outcome_model
event_ev_p_miss: Optional[float] = None       # decision-time P(MISS)
event_ev_p_mixed: Optional[float] = None      # decision-time P(MIXED)
event_ev_confidence: Optional[float] = None   # EV model confidence (not data quality)
event_ev_asof_date: Optional[str] = None      # date of the EV artifact used for binding
event_ev_match_type: Optional[str] = None     # "exact_node" | "ticker_date_7d" | "none"
```

Add to postmortem `resolution_source` section:

```python
"event_ev_p_hit": resolution_rec.get("event_ev_p_hit"),
"event_ev_p_miss": resolution_rec.get("event_ev_p_miss"),
"event_ev_confidence": resolution_rec.get("event_ev_confidence"),
"event_ev_asof_date": resolution_rec.get("event_ev_asof_date"),
"event_ev_match_type": resolution_rec.get("event_ev_match_type"),
```

### 3b. Files to touch

| File | Change |
|------|--------|
| `tools/catalyst_resolution_tracker.py` | Add 7 fields to `ResolutionRecord`; add `_bind_event_ev_p_hit()` helper called at write time |
| `agents/postmortem/scripts/run_postmortem.py` | Propagate 5 new fields into `resolution_source` |
| `tests/test_catalyst_resolution_tracker.py` (new or existing) | Smoke test: ≥1 resolution record with non-null `event_ev_p_hit` |

Do NOT touch: `event_ev/outcome_model.py`, `event_ev/event_store.py`, `run_screen.py`,
`module_5_scoring_v3.py`, selector, ranker, `event_outcome_binder.py`.

### 3c. Binding logic (`_bind_event_ev_p_hit`)

```
Input: ticker, catalyst_date, prediction_snapshot_date, node_id (optional)
Output: event_ev_p_hit, event_ev_p_miss, event_ev_p_mixed, event_ev_confidence,
        event_ev_asof_date, event_ev_match_type

1. Find closest EV artifact dated ≤ prediction_snapshot_date
   (use artifacts/event_ev/{date}_event_ev_full.json, pick latest date ≤ snap date)

2. Try node_id match first (match_type = "exact_node"):
   - If node_id is known, look it up in events[i].node.node_id
   - If found: bind outcome fields

3. Fallback to (ticker, expected_date ±7d) match (match_type = "ticker_date_7d"):
   - Only if node_id not available or not found
   - Require exact ticker match + |expected_date - catalyst_date| ≤ 7d
   - If multiple candidates: prefer closest date; if tie: pick higher p_hit
   - If none within 7d: leave all fields None (match_type = "none")

4. Never infer or synthesize p_hit from other fields.
5. Never use EV artifact dated AFTER prediction_snapshot_date (would be look-ahead).
```

### 3d. Node_id acquisition

The cleanest source is the event store: `event_ev/event_store.py` already maintains
the node registry. Check whether `build_event_ev_scores.py` or the CRT detection loop
can look up `node_id` for a given (ticker, catalyst_date) at detection time.

If the event store is not importable from CRT without circular dependencies:
fall back to reading the same `{snap_date}_event_ev_full.json` artifact and scanning
by (ticker, expected_date ±7d) to retrieve `node_id`.

### 3e. Proposed test command

```bash
cd /mnt/c/Projects/biotech_screener/biotech-screener
python -m pytest tests/test_catalyst_resolution_tracker.py::test_event_ev_p_hit_binding -v

# Smoke: at least one resolution record has non-null event_ev_p_hit after re-run
python tools/catalyst_resolution_tracker.py --dry-run 2>&1 | grep event_ev_p_hit
```

---

## 4. What is NOT in scope

- Do not add `event_ev_p_hit` to `rankings.csv` or any snapshot field
- Do not change how `p_hit` is computed in `outcome_model.py`
- Do not promote p_hit to selector or ranker
- Do not add Polymarket to EV; it remains prospective shadow-only
- Do not backfill historical records using (ticker, date) windowed join
- Do not treat `conditional_confidence`, `calendar_confidence`, or `binary_quality_score`
  as P(HIT) proxies — they are not

---

## 5. Calibration readiness

| Milestone | Condition |
|-----------|-----------|
| Binding works | ≥1 new resolution record with non-null `event_ev_p_hit` |
| Minimal calibration | ≥30 HIT/MISS with non-null `event_ev_p_hit`, all post-PIT-valid |
| Estimated date | ~2026-07-01 (current cadence ~3-4 HIT/MISS per week) |
| Brier benchmark | Must beat always-predict-base-rate (currently 0.247 for pcs) |
| Checklist v2 eligible | Requires calibration + n ≥ 50 + NW-corrected t ≥ 2.0 |

Post-PIT HIT/MISS today: 7. The 2026-05-22 review date is insufficient.
Do not run EV calibration audit until n ≥ 30 with non-null `event_ev_p_hit`.

---

## 6. Rollback

```bash
git revert <commit-hash>
# ResolutionRecord fields will be absent; any new resolution JSON files
# written with the new fields would need manual null-patching if rollback required
```

New fields are additive. Readers that don't know about them will ignore them.
Existing resolution JSON files are unmodified (forward-only).

---

## 7. Commit message

```
feat(ev): bind event_ev_p_hit into resolution records (shadow-only)

Add event_ev_node_id, event_ev_p_hit, event_ev_p_miss, event_ev_p_mixed,
event_ev_confidence, event_ev_asof_date, event_ev_match_type to ResolutionRecord.

Binding uses node_id exact match primary / (ticker, date ±7d) fallback.
No backfill — (ticker, date) windowed match at 30% rate is not safe.
No production scoring changes. Unblocks EV calibration when n(HIT+MISS) >= 30.
```
