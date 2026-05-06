# Spec 073 — Catalyst Prediction Binder (2026-05-05)

**Status:** Implementation ticket. Highest priority — blocks Phase A ranker evidence for catalyst signal.

**Hold-off scope:** This ticket is strictly about wiring `prediction_composite_score` into resolution records so that ranker IC can be computed. It does NOT promote `catalyst_score` to the ranker, does not change weights, and does not touch `event_outcome_binder.py`'s clinical shadow logic.

**Verification note (added 2026-05-05):** A post-write research pass found individual resolution JSON files in `data/snapshots/resolutions/` that appear to have `prediction_composite_score` populated (e.g., ALDX at 0.1). This may mean the field is partially populated in the JSON resolution store but still null in the CRT JSONL (`production_data/catalyst_resolution_tracker.jsonl`), which is the source used for IC computation. **Before implementing any step in this ticket, run the diagnostic in §0 below to determine the actual null count and which store is authoritative for Phase A IC evaluation.** The ticket's root-cause analysis and fix steps remain valid if the JSONL store has nulls; if the JSON files are the authoritative source and are already populated, the scope reduces to Step 4 (daily reconciliation) only.

---

## 0. Pre-implementation diagnostic

Run this before touching any code:

```bash
cd /mnt/c/Projects/biotech_screener/biotech-screener

# Check JSONL store (used for IC computation)
python -c "
import json
records = [json.loads(l) for l in open('production_data/catalyst_resolution_tracker.jsonl') if l.strip()]
null_count = sum(1 for r in records if r.get('prediction_composite_score') is None)
total = len(records)
print(f'JSONL store: {null_count}/{total} null prediction_composite_score')
"

# Check JSON file store (data/snapshots/resolutions/)
python -c "
import json, pathlib
files = list(pathlib.Path('data/snapshots/resolutions').rglob('*.json'))
null_count = sum(1 for f in files if json.loads(f.read_text()).get('prediction_composite_score') is None)
print(f'JSON file store: {null_count}/{len(files)} null')
"

# Confirm which store Phase A IC computation reads from
grep -n 'prediction_composite_score\|catalyst_resolution_tracker\|resolutions/' tools/catalyst_phase_a_verdict.py 2>/dev/null | head -20
```

If JSONL null count is 0 and JSON files are also populated: this ticket's scope is Step 4 only (daily reconciliation guard). If JSONL shows significant nulls: proceed with all steps.

---

## 1. Problem statement

`catalyst_score` shows conditional Spearman ρ ≈ +0.19 in shadow evaluation, which is materially stronger than clinical's +0.07. But Phase A verdict (frozen 2026-05-04) cannot compute ranker IC because `prediction_composite_score` is null in all 119 catalyst resolutions — the binder that copies `composite_score` from daily snapshot CSVs into resolution records has never successfully run prospectively.

Without a populated `prediction_composite_score`, there is no way to evaluate whether the at-decision-time ranker prediction matched the eventual outcome. The entire EV evaluation lane is blocked.

---

## 2. Root cause

Three separate issues compound:

**2a. Schema gap — field missing from rankings.csv**

`prediction_composite_score` is defined in the CRT resolution dataclass (`tools/catalyst_resolution_tracker.py:130`) but is NOT written to `data/snapshots/YYYY-MM-DD/rankings.csv`. The daily pipeline in `run_screen.py` writes `composite_score` (the live ranker output) but does not alias or re-export it under the resolution field name.

When `catalyst_resolution_tracker.py` creates a new resolution at event time, it reads:
```python
snap.get("composite_score")   # line 655, 700, 759
```
If `composite_score` is absent from the snapshot row (which it is — the column is not in the CSV), the resolution record gets `prediction_composite_score = None` at birth and is never corrected.

**2b. Backfill tool not wired into cron**

`tools/backfill_resolution_predictions.py` exists to retroactively populate null `prediction_composite_score` fields by scanning historical snapshot CSVs. It correctly maps:
```python
rec["prediction_composite_score"] = _safe_float(snap.get("composite_score"))
```
But it has no cron entry and no evidence of successful execution (119 nulls in production).

**2c. `event_outcome_binder.py` scope is clinical-only**

The daily outcome binder (`tools/event_outcome_binder.py`) handles `clinical_transmission_shadow.jsonl` → resolution index binding. It does not bind catalyst ranker predictions to resolutions. There is no equivalent catalyst-side binder running in the daily pipeline.

---

## 3. Minimal fix (ordered)

### Step 1 — Write `composite_score` into rankings.csv

In `run_screen.py`, verify that `composite_score` (the final pairwise logistic output) is included in the row dict written to `rankings.csv`. If it is already present under a different alias, document the alias. If not, add it.

**Verification:**
```bash
head -1 data/snapshots/$(date +%Y-%m-%d)/rankings.csv | tr ',' '\n' | grep -i composite
```
If absent, locate where `run_screen.py` constructs the row dict for CSV output and add `"composite_score": row["composite_score"]` (or equivalent from the scoring pipeline).

### Step 2 — Ensure `catalyst_resolution_tracker.py` reads the correct key

Confirm lines 655, 700, 759 of `tools/catalyst_resolution_tracker.py` use the key that actually exists in the snapshot CSV after Step 1. If the CSV column is named differently (e.g., `ranker_v2_score`), update the `snap.get(...)` call to match.

### Step 3 — Run `backfill_resolution_predictions.py`

After Step 1 is confirmed working for at least one daily snapshot:
```bash
cd /mnt/c/Projects/biotech_screener/biotech-screener
python tools/backfill_resolution_predictions.py --dry-run
# Review output — expect changes to most/all of the 119 records
python tools/backfill_resolution_predictions.py
```

Before running: confirm the tool reads from `data/snapshots/*/rankings.csv` (not a stale cache path) and writes to the resolution JSONL in-place.

### Step 4 — Wire a daily reconciliation pass

After the backfill, add a lightweight reconciliation step to the daily pipeline (or to `event_outcome_binder.py`) that checks any resolution created in the last 7 days with a null `prediction_composite_score` and attempts to populate it from the corresponding snapshot CSV. This prevents future null accumulation.

---

## 4. Files to touch

| File | Change |
|---|---|
| `run_screen.py` | Verify/add `composite_score` column in CSV output |
| `tools/catalyst_resolution_tracker.py` | Align `snap.get(...)` key with actual CSV column name |
| `tools/backfill_resolution_predictions.py` | Run once; confirm no path bugs |
| `tools/event_outcome_binder.py` or new `tools/catalyst_prediction_reconciler.py` | Daily null-fill pass |

---

## 5. Tests

**Before any code change**, run:
```bash
python -m pytest tests/ -k "resolution or catalyst_resolution" -x -q
```

After Step 1:
- Add one test: `rankings.csv` written by `run_screen.py` contains a `composite_score` column (or document why the column has a different name and test for that name instead).

After Step 3:
- Spot-check: pick 3 resolution records, find their corresponding snapshot CSV, confirm `prediction_composite_score` now matches the CSV's `composite_score` for that ticker on that date.

After Step 4:
- Add one regression test: a mock resolution with null `prediction_composite_score` created yesterday gets populated by the reconciliation pass when today's snapshot exists.

---

## 6. Rollback

- Steps 1–2 are additive (new column in CSV, key rename in one file). Rollback = revert the two-line change.
- Step 3 is a data mutation. Before running, snapshot the resolution JSONL:
  ```bash
  cp production_data/catalyst_resolution_tracker.jsonl production_data/catalyst_resolution_tracker.jsonl.bak_$(date +%Y%m%d)
  ```
- Step 4: if reconciliation pass has a bug, it will null-out or corrupt records. Guard with `if snap_val is not None` before overwriting any existing non-null value.

---

## 7. Success criterion

After all steps: `python tools/backfill_resolution_predictions.py --stats` (or equivalent) shows `prediction_composite_score` non-null for ≥ 90 of 119 resolutions (some early resolutions may predate the snapshot archive). The Phase A ranker IC computation in `tools/catalyst_phase_a_verdict.py` (or equivalent) can run without skipping records for null predictions.

---

## 8. Dependencies and constraints

- Does NOT change any selector or ranker weights.
- Does NOT change `catalyst_score` computation.
- Does NOT promote catalyst signal — Phase A verdict review remains 2026-05-22.
- `event_outcome_binder.py` clinical shadow path is untouched.
- Backfill run must happen AFTER snapshot archive is confirmed intact (check `data/snapshots/` for coverage back to at least 2026-03-01).
