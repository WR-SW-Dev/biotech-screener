# Scientific Cartography Phase 13.5 — R2b Stage Parser Compatibility Fix

Date: 2026-06-23
Label: PHASE13_5_R2B_STAGE_PARSER_COMPATIBILITY_FIX

---

## Root Cause

`CTGovIngest._parse_simplified_format` was reading only the plural `"phases"` key
(a list, e.g. `["Phase 2"]`) when constructing a `TrialRecord`.  Production
`trial_records.json` stores the phase value under the singular `"phase"` key as a
bare string (e.g. `"PHASE2"`).  Because `data.get("phases", [])` always returned
an empty list for production records, every program emitted stage `unknown` — 100%
unknown across 73,075 records before the fix.

**Code before fix (line 141 of ctgov_ingest.py):**

```python
phases=self._ensure_list(data.get("phases", [])),
```

**Code after fix (lines 136-155):**

```python
# PHASE13_5_R2B_STAGE_PARSER_COMPATIBILITY_FIX
# Production trial_records.json uses singular "phase" string (e.g. "PHASE2").
# Test fixtures use plural "phases" list. Support both: prefer "phases" if
# present and non-empty, otherwise fall back to "phase" singular string.
phases_raw = data.get("phases")
if phases_raw:
    phases = self._ensure_list(phases_raw)
else:
    phases = self._ensure_list(data.get("phase", []))
```

Priority rule: `phases` (list) wins if present and non-empty; otherwise fall back
to `phase` (string).  Both paths pass through `_ensure_list`, so the downstream
`TrialRecord.phases` field is always a list.

---

## Fix Summary

| Item | Detail |
|---|---|
| File modified | `scientific_cartography/ingest/ctgov_ingest.py` |
| Nature of change | Minimal, backward-compatible; one code block replaced |
| Other files changed | None (no ranker, selector, sizing, pipeline, or snapshot files touched) |

---

## Test Coverage

**Test file:** `tests/scientific_cartography/test_phase13_5_r2b_stage_parser.py`

25 new tests across 8 classes:

| Class | Tests | What is tested |
|---|---|---|
| `TestPhasesListFormat` | 4 | Plural `phases` list still works; list wins over singular |
| `TestPhaseSingularFormat` | 4 | Singular `phase` string (PHASE1/2/3/4) parsed correctly |
| `TestDualPhaseString` | 2 | `PHASE1_PHASE2` compound preserved; `Phase 1/2` alias works |
| `TestEarlyPhase` | 2 | `EARLY_PHASE1` constant preserved; `early phase 1` alias works |
| `TestMissingPhase` | 3 | No phase field → empty list; empty list falls through to singular |
| `TestNullPhase` | 3 | None values → empty list, no crash |
| `TestNotApplicablePhase` | 4 | N/A, NA, NOT_APPLICABLE preserved; normalizer returns None |
| `TestEndToEndProductionRecord` | 3 | Full production-style record; `select_highest_stage` end-to-end |

All 25 tests pass. Full sci-cart regression: **424/424 pass, 0 failures**.

---

## Diagnostic Results

### Stage Coverage

| Metric | Before R2b | After R2b |
|---|---|---|
| Stage known % | 0% (100% unknown) | 75.9% |
| Stage unknown % | 100% | 24.1% |
| Total program records | 73,075 | 73,075 |

**After R2b distribution (73,075 records):**

| Stage | Count | % |
|---|---|---|
| phase1 | 23,185 | 31.7% |
| phase2 | 20,853 | 28.5% |
| unknown | 17,619 | 24.1% |
| phase3 | 11,418 | 15.6% |

The residual 24.1% unknown is expected: records with `N/A`, `NOT_APPLICABLE`,
`EARLY_PHASE1`, `PHASE1_PHASE2`, or no phase field have no canonical mapping in
`StageNormalizer` and correctly emit `unknown`.

### Ticker Linkage

| Metric | Before R2b | After R2b |
|---|---|---|
| Ticker linkage % | 98.0% | 98.0% (unchanged) |
| Linked records | 71,589 / 73,075 | 71,589 / 73,075 |

Ticker linkage was not affected by the parser fix.

### Mechanism Coverage

| Metric | Before R2b | After R2b |
|---|---|---|
| Known mechanism % | 0.07% | 0.07% (unchanged) |

Mechanism coverage is unchanged, as expected.  R3 (mechanism enrichment) is the
next phase.

### Confidence Distribution

| Confidence | Count | % |
|---|---|---|
| missing | 58,600 | 80.2% |
| 0.8 | 11,891 | 16.3% |
| 0.6 | 2,371 | 3.2% |
| 0.7 | 213 | 0.3% |

Non-zero confidence values are present (expected; derived from ticker linkage
confidence, not stage).  Confidence from stage-specific attribution will be
addressed in R3.

---

## Governance

- DIAGNOSTIC_ONLY
- No changes to ranker, selector, sizing, final_score, gates, snapshots, or
  portfolio logic
- No production wiring; no cron; no pipeline integration
- No freeze lift
- Scope: one method in one ingester file + new test file + this audit memo

---

## Next Step

The v0.2b static map prototype can now proceed with real stage columns.
Stage coverage is 75.9% (up from 0%), which is sufficient for the static map
prototype described in
`artifacts/audit/SCIENTIFIC_CARTOGRAPHY_MAP_UX_V0_2B_STATIC_PROTOTYPE_SPEC_2026_06_23.md`.

---

## Verdict

PASS_R2B_STAGE_PARSER_COMPATIBILITY_DIAGNOSTIC_ONLY
