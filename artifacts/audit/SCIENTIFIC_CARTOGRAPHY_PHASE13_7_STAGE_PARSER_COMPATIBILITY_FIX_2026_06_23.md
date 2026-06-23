# Scientific Cartography Phase 13.7 — Stage Parser Compatibility Fix
**Date:** 2026-06-23
**Status:** PASS
**Verdict:** `PASS_STAGE_PARSER_COMPATIBILITY_DIAGNOSTIC_ONLY`

---

## 1. Problem Statement

`trial_records.json` (20,057 CT.gov records) uses CT.gov API constants for
the `"phase"` field:

| CT.gov value | Count | StageNormalizer before fix |
|---|---|---|
| `PHASE1` | 4,992 | `"phase1"` ✓ |
| `PHASE2` | 4,695 | `"phase2"` ✓ |
| `PHASE3` | 3,541 | `"phase3"` ✓ |
| `N/A` | 3,072 | `None` (acceptable) |
| `NA` | 2,294 | `None` (acceptable) |
| `PHASE4` | 1,331 | `None` ✗ |
| `EARLY_PHASE1` | 132 | `None` ✗ |

`PHASE4` and `EARLY_PHASE1` together represent 1,463 source records and
~5,290 derived program records with silently unknown stage. Additionally,
`PHASE1_PHASE2`, `PHASE2_PHASE3`, and `NOT_APPLICABLE` are CT.gov constants
defined in the API spec that must be handled if they appear in future ingests.

### Parser context

`CTGovIngest._parse_simplified_format()` was already fixed in commit
`dc1aaed6` (Phase 13.5 R2b) to read the singular `"phase"` field:

```python
phases_raw = data.get("phases")
if phases_raw:
    phases = self._ensure_list(phases_raw)
else:
    phases = self._ensure_list(data.get("phase", []))
```

The parser was correct. The gap was in `StageNormalizer.STAGE_ALIASES`,
which had no aliases for `EARLY_PHASE1`, `PHASE4`, `PHASE1_PHASE2`, or
`PHASE2_PHASE3`.

---

## 2. Fix Applied

**File:** `scientific_cartography/normalize/stage_normalizer.py`

Added CT.gov uppercase/underscore aliases to `STAGE_ALIASES`:

| CT.gov constant | Canonical stage | Rationale |
|---|---|---|
| `EARLY_PHASE1` | `"phase1"` | Early Phase 1 IS Phase 1 |
| `PHASE1_PHASE2` | `"phase1/2"` | Compound = adaptive Phase 1/2 |
| `PHASE2_PHASE3` | `"phase3"` | Adaptive trial → map to higher bound |
| `PHASE4` | `"approved"` | Post-marketing surveillance = approved drug |
| `N/A`, `NA`, `NOT_APPLICABLE` | `None` | Not a clinical phase; no alias needed |

The `N/A`, `NA`, and `NOT_APPLICABLE` values already returned `None`
via the default fallback, which is correct behavior (non-interventional
trials, expanded access, observational studies). No change needed.

---

## 3. Tests Updated / Added

**Updated:** `tests/scientific_cartography/test_phase13_5_r2b_stage_parser.py`

Three tests previously asserted `None` for `PHASE4`, `PHASE1_PHASE2`, and
`EARLY_PHASE1`. Updated to assert the new correct canonical values.

**Added:** `tests/scientific_cartography/test_stage_normalizer.py`

New class `TestStageNormalizerCTGovFormat` (14 tests):

| Test | Behavior Verified |
|---|---|
| `test_phase1_uppercase` | PHASE1 → phase1 |
| `test_phase2_uppercase` | PHASE2 → phase2 |
| `test_phase3_uppercase` | PHASE3 → phase3 |
| `test_phase4_maps_to_approved` | PHASE4 → approved |
| `test_early_phase1_underscore` | EARLY_PHASE1 → phase1 |
| `test_phase1_phase2_underscore` | PHASE1_PHASE2 → phase1/2 |
| `test_phase2_phase3_underscore` | PHASE2_PHASE3 → phase3 |
| `test_not_applicable_returns_none` | NOT_APPLICABLE → None |
| `test_na_returns_none` | N/A → None |
| `test_na_bare_returns_none` | NA → None |
| `test_phase4_is_active` | PHASE4 → approved → active |
| `test_early_phase1_is_active` | EARLY_PHASE1 → phase1 → active |
| `test_phase2_phase3_rank_above_phase2` | PHASE2_PHASE3 ranks > phase2 |
| `test_not_applicable_not_active` | NOT_APPLICABLE → None → not active |

---

## 4. Test Results

```
438 passed in 8.27s
```

All Phase 0–13 Sci-Cart tests pass. 14 new CT.gov format tests pass.

---

## 5. Diagnostic Run Results (2026-06-23, trial_records.json, 20,057 trials)

Diagnostic run against `production_data/trial_records.json` without a
snapshot (no ticker-linked companies loaded):

### Stage Coverage

| Metric | Value |
|---|---|
| Total programs | 73,075 |
| With stage | 59,159 (81.0%) |
| Without stage | 13,916 (19.0%) |

Stage distribution:

| Stage | Programs | % |
|---|---|---|
| phase1 | 23,674 | 32.4% |
| phase2 | 20,853 | 28.5% |
| None/unknown | 13,916 | 19.0% |
| phase3 | 11,418 | 15.6% |
| approved | 3,214 | 4.4% |

The 19.0% unknown corresponds to the `N/A` + `NA` records (non-interventional
and observational trials with no clinical phase). This is expected and correct.

### Downstream Metrics

| Metric | Value | Notes |
|---|---|---|
| Confidence > 0 | 14,475 (19.8%) | R3 intact — requires MONDO-mapped disease |
| Therapeutic area coverage | 14,475 (19.8%) | R5 intact |
| Mechanism coverage | 53 (0.1%) | R6 design confirmed sparse — as expected |
| Ticker linkage | 0% | No snapshot loaded; expected in this diagnostic |

Ticker linkage is 0% because the snapshot directory was empty (no
`rankings.csv`). A full diagnostic run against a snapshot with `rankings.csv`
will restore ~98% ticker linkage. This is a test-setup artifact, not a
regression.

---

## 6. Governance Constraints Preserved

- READ_ONLY_DIAGNOSTIC: no production model files modified
- No ranker, selector, sizing, final_score, gates, snapshot, or portfolio changes
- No alpha claims; no trading/action language
- No live fetch or API calls
- No cron/scheduler
- Production model freeze remains ACTIVE

---

## 7. Scope Boundary

- Only `stage_normalizer.py` aliases modified
- No disease normalization, confidence aggregation, therapeutic_area, or
  mechanism normalization changes
- Parser (`ctgov_ingest.py`) was already fixed in Phase 13.5 R2b; unchanged here

---

## 8. Next Steps

With stage coverage at 81%, the stage axis is now usable for RA-style map
grouping. Remaining 19% unknown stage is structural (non-interventional
trials) and cannot be improved without additional source data.

**Immediate next:** Regenerate the Sci-Cart artifact baseline against a
real snapshot (with `rankings.csv`) and implement the static RA-style map
v0.2b prototype using the now-populated stage, therapeutic_area, and disease
columns.
