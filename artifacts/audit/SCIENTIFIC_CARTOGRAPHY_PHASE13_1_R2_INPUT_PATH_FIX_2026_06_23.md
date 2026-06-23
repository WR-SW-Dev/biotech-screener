# Scientific Cartography Phase 13.1 R2 — Input Path Correction

**Date:** 2026-06-23  
**Verdict:** `PASS_SCIENTIFIC_CARTOGRAPHY_R2_INPUT_PATH_FIX_DIAGNOSTIC_ONLY`  
**Governance:** DIAGNOSTIC_ONLY | NO_PRODUCTION_CHANGES | FREEZE_ACTIVE

---

## 1. Problem

Phase 12.1 review found that prior Sci-Cart artifacts had 0% ticker linkage. Root
cause: the diagnostic wrapper (`tools/run_scientific_cartography_diagnostics.py`)
looked only for `trials.jsonl` and `trials.json` in the ctgov_cache directory. The
actual available input is `production_data/trial_records.json` — a list-style JSON
file with 20,057 trial records. The wrapper would fall through to the no-files
warning and produce empty trial loads.

---

## 2. Fix

**File changed:** `tools/run_scientific_cartography_diagnostics.py`

**Change:** Replaced the two-candidate `if/elif` input-discovery block with an ordered
candidate list that checks three filenames in priority order:

| Priority | Filename | Format |
|----------|----------|--------|
| 1 | `trials.jsonl` | JSONL (one trial per line) |
| 2 | `trials.json` | JSON list or single object |
| 3 | `trial_records.json` | JSON list (same as `trials.json`) |

The loop breaks on the first existing file. Subsequent candidates are not loaded.

`trial_records.json` uses the existing `ingest_from_json_file()` path, which already
handles list-style JSON (`isinstance(data, list)` branch). No changes to
`CTGovIngest` were required.

The diagnostic print message now includes the source filename:
```
✓ Loaded N trials from cache (source: trial_records.json)
```

The no-files warning was updated to mention all three accepted filenames.

**No production data files were copied, renamed, or mutated.**

---

## 3. Before / After

### Before (lines 110–129):
```python
jsonl_path = ctgov_cache / "trials.jsonl"
json_path = ctgov_cache / "trials.json"

if jsonl_path.exists():
    trials = ctgov_ingest.ingest_from_jsonl_file(jsonl_path)
elif json_path.exists():
    trials = ctgov_ingest.ingest_from_json_file(json_path)
else:
    status["warnings"].append(
        "No trial data files (trials.jsonl or trials.json) found in ctgov_cache"
    )
print(f"✓ Loaded {len(trials)} trials from cache", file=sys.stderr)
```

### After:
```python
_trial_candidates = [
    (ctgov_cache / "trials.jsonl", "jsonl"),
    (ctgov_cache / "trials.json", "json"),
    (ctgov_cache / "trial_records.json", "json"),
]
_trial_source = None
for _candidate_path, _fmt in _trial_candidates:
    if _candidate_path.exists():
        try:
            if _fmt == "jsonl":
                trials = ctgov_ingest.ingest_from_jsonl_file(_candidate_path)
            else:
                trials = ctgov_ingest.ingest_from_json_file(_candidate_path)
            _trial_source = _candidate_path.name
        except Exception as e:
            status["warnings"].append(f"Failed to load from {_candidate_path.name}: {e}")
        break

if _trial_source is None and not trials:
    status["warnings"].append(
        "No trial data files (trials.jsonl, trials.json, or trial_records.json)"
        " found in ctgov_cache"
    )
print(f"✓ Loaded {len(trials)} trials from cache (source: {_source_label})", ...)
```

---

## 4. Tests

**File:** `tests/scientific_cartography/test_phase7_diagnostic_pipeline.py`  
**New class:** `TestTrialInputDiscovery` (5 tests)

| Test | Scenario |
|------|----------|
| `test_discovers_trials_jsonl` | `trials.jsonl` present → loaded, no missing-file warning |
| `test_discovers_trials_json` | `trials.json` only → loaded, no missing-file warning |
| `test_discovers_trial_records_json` | `trial_records.json` only → loaded, no missing-file warning |
| `test_priority_jsonl_over_trial_records` | Both `trials.jsonl` + `trial_records.json` present → jsonl called, `trial_records.json` not called |
| `test_no_trial_files_emits_warning` | Empty cache → warning mentions all three filenames including `trial_records.json` |

**Results:** 13/13 pass (8 pre-existing + 5 new).

---

## 5. Governance

| Check | Status |
|-------|--------|
| Production model freeze | ACTIVE — no ranker/selector/sizing/final_score/gate/snapshot/portfolio changes |
| No production data mutation | PASS — `trial_records.json` read-only; no copies or renames |
| No cron / scheduler | PASS |
| No live fetch | PASS |
| No EES changes | PASS |
| No scoring changes | PASS |
| Sci-Cart artifacts generated | NOT generated — this memo and the tests are the only outputs |

---

## 6. Phase 13 Sequence Status

| Ref | Task | Status |
|-----|------|--------|
| R2 | Input-path correction (`trial_records.json` discovery) | ✅ COMPLETE (this commit) |
| R4 | Ticker linkage verification (confirm linkage improves with live input) | pending |
| R3 | Baseline artifact re-run with `trial_records.json` | pending |
| R5 | Coverage gap analysis | pending |
| R6 | Phase 13 summary memo | pending |

Next step: R4 — verify that ticker linkage improves when the wrapper is run against
`production_data/trial_records.json`.

---

*DIAGNOSTIC_ONLY | NO_PRODUCTION_CHANGES | FREEZE_ACTIVE*
