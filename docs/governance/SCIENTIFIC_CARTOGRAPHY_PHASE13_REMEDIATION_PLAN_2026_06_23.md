# Scientific Cartography Phase 13 — Remediation Plan

**Date:** 2026-06-23  
**Status:** PLANNING — no implementation code in this document  
**Governance:** READ_ONLY_DIAGNOSTIC throughout; no scoring, ranker, selector, or portfolio changes  
**Source:** Phase 12.1 Operational Review recommendations R1–R6  

---

## Scope

Phase 13 remediates the structural quality gaps identified in Phase 12.1. The production model remains frozen. All deliverables are diagnostic artifacts, documentation, and non-scoring improvements to the cartography layer.

**Explicitly out of scope:**
- No changes to ranker weights, selector, sizing, final_score, or portfolio gates
- No wiring of any cartography field into a scoring system
- No promotion of post-fix artifacts to production without separate operator authorization
- No Phase 13 implementation until operator reviews and authorizes R1 (artifact promotion decision)

---

## Operator Decision Required Before Phase 13 Work Begins

### R1 — Adopt 2026-06-23-postfix as working baseline (operator decision)

The post-fix artifacts at `artifacts/scientific_cartography/2026-06-23-postfix/` are substantively better than the pre-fix baseline (13.8% vs 35.1% mis-normalization, 97.9% vs 0% ticker linkage). Renaming or promoting them as the working baseline requires an explicit operator decision.

**What the operator must decide:**
1. Promote `2026-06-23-postfix/` as the active artifacts directory
2. Confirm the fix commits (`697c0b83` — normalizer, `38edb0ab` — merged) are the authoritative baseline going forward
3. Authorize Phase 13 work to begin against this baseline

**No action in this document.** Phase 13 implementation is gated on operator R1 confirmation.

---

## Implementation Order (operator-recommended sequence)

### Phase 13.1 — R2: Fix ctgov_cache input path

**Priority:** High  
**Blocker:** ctgov-cache mismatch causes 0% ticker linkage in all scheduled/cron runs

**Problem:**  
`tools/run_scientific_cartography_diagnostics.py` accepts `--ctgov-cache <dir>` and looks for `trials.jsonl` or `trials.json` in that directory. The canonical trial data file is `production_data/trial_records.json` — it is neither named `trials.json` nor `trials.jsonl`, so no trial data is loaded and ticker linkage is zero.

The Phase 12.1 post-fix was a one-time workaround: `cp production_data/trial_records.json /tmp/trials.json && --ctgov-cache /tmp`. This does not persist across runs.

**Design choices (for operator/implementer to select):**

Option A — Extend the file lookup (minimal change):  
Add `trial_records.json` to the lookup sequence in `run_scientific_cartography_diagnostics.py` (lines 112–124). Order: `trials.jsonl` → `trials.json` → `trial_records.json`. Zero behavior change for existing callers.

Option B — Add explicit `--trials-file` argument:  
Accept `--trials-file <path>` that points directly to the JSON file. Callers that pass it bypass the directory lookup. The ctgov_cache directory lookup remains as fallback. This is the most explicit and least surprising.

Option C — Update default path in documentation/cron:  
Leave the code unchanged; update cron invocations to pre-copy or symlink `trial_records.json` → `trials.json` before running the wrapper.

**Recommendation:** Option A for the wrapper (non-breaking); add a comment documenting the canonical file name. Then update any cron scripts or documentation to pass `--ctgov-cache production_data/` directly.

**Deliverable:**  
- `tools/run_scientific_cartography_diagnostics.py` updated with extended lookup (or `--trials-file` arg)  
- Updated cron invocation / wrapper documentation  
- Verification: re-run wrapper against `production_data/` and confirm `ticker_count > 0` in generated `map_index.json`  

---

### Phase 13.2 — R4: Manual normalization sample review

**Priority:** Medium  
**Purpose:** Distinguish true positives from false positives in the residual 13.8% mis-normalization rate

**Problem:**  
After the Phase 12.1 fix, the top remaining normalizations are:

| Mapped-to disease | Records |
|---|---|
| lymphoma | 4,116 |
| breast cancer | 1,604 |
| non-small cell lung cancer | 1,193 |
| colorectal cancer | 739 |
| melanoma | 619 |

These are plausibly correct (specific subtypes mapping to parent MONDO terms) or could be substring false positives of the same type as "RA"/"AD". Manual review is required to characterize the error mode before deciding on a code fix.

**Method:**  
Draw a stratified random sample of 50 records (10 from each of the 5 top disease targets). For each record, compare:
- Raw CT.gov indication string (input)
- MONDO term it was mapped to
- Match priority level (which normalizer tier fired: exact / alias / synonym / substring)
- Manual verdict: TRUE_POSITIVE / FALSE_POSITIVE / AMBIGUOUS

**Classification criteria:**
- **TRUE_POSITIVE**: the MONDO term is a valid parent or synonym for the indication (e.g., "Stage IIA Breast Cancer" → *breast cancer*)
- **FALSE_POSITIVE**: the MONDO match is wrong and would mislead the disease map (e.g., short substring coincidence like old "RA"/"AD" bug)
- **AMBIGUOUS**: the match is defensible but imprecise (e.g., specific subtype maps to broad parent)

**Deliverable:**  
- `docs/governance/SCIART_PHASE13_2_NORMALIZATION_SAMPLE_REVIEW_2026_06_23.md` containing:
  - 50-record annotated table
  - True/false/ambiguous counts per disease
  - Verdict: is the 13.8% residual rate an acceptable level of imprecision for a diagnostic layer, or does it require another normalizer fix?
  - Recommendation for Phase 13.3 scope (R3) — whether confidence decoupling matters if normalization is still imprecise

---

### Phase 13.3 — R3: Decouple asset_confidence from overall confidence floor

**Priority:** Medium  
**Gated on:** R4 verdict — only worthwhile if residual normalization is acceptable

**Problem:**  
`ProgramRecord.confidence` is computed as:

```python
overall_confidence = min(
    asset_confidence,      # always 0.0 — asset alias resolver returns None
    sponsor_public_factor, # 1.0 or 0.7
    disease_confidence,    # 0.0–1.0
    stage_factor,          # 0.8 or 0.6
)
```

`asset_alias_resolver.resolve()` returns `None` for all interventions (CT.gov intervention names are not in any asset alias dictionary), so `asset_confidence = 0.0` always. The `min()` collapses overall confidence to zero regardless of disease or sponsor quality. Downstream filters (e.g., `asset_indication_builder.py` line 114: `if not program.disease_name or program.confidence < 0.5`) may suppress otherwise valid records.

**Design choices:**

Option A — Remove asset_confidence from the floor:  
Compute `overall_confidence = min(sponsor_public_factor, disease_confidence, stage_factor)`. Asset_confidence becomes an additive bonus once the resolver is populated, not a floor. This is the smallest, most targeted change.

Option B — Add an unresolved-asset exemption:  
If `asset_confidence is None` (resolver returned None), skip it from the floor. Only include it when the resolver has a real answer. This requires distinguishing "asset not found" from "asset found with low confidence."

Option C — Keep the floor but fix the resolver:  
Populate `asset_alias_resolver` with CT.gov intervention names. This is the "right" fix long-term but requires a separate asset alias database build workstream (not in scope for Phase 13).

**Recommendation:** Option A for Phase 13 (non-blocking fix that lets disease+sponsor confidence signal through). Option C is a separate workstream that would replace Option A once the resolver is populated.

**Deliverable:**  
- `scientific_cartography/build/asset_indication_builder.py` or the confidence computation site updated (location TBD — implementer should read the current code before committing to a specific line)
- Test: verify that a program record with `disease_confidence=0.85`, `sponsor=public`, `stage=phase3` now gets `overall_confidence > 0` instead of 0.0
- Verification artifact: re-run wrapper and confirm `confidence == 0.0` rate drops from 100%

---

### Phase 13.4 — R5: Wire therapeutic_area from MONDO into DiseaseRecord

**Priority:** Low  
**Why low:** Therapeutic area is a readability/grouping improvement; it does not affect normalization accuracy or confidence scoring.

**Problem:**  
`therapeutic_area` is null for all records throughout the pipeline. MONDO ontology records carry `therapeutic_area` in their data; it is not propagated into `DiseaseRecord` construction or `ProgramRecord`. The disease map `artifacts/.../disease_map_summary.json` cannot group by therapeutic area.

**Scope:**
1. Identify where `therapeutic_area` appears in the MONDO ontology data (likely in the raw MONDO OWL/JSON source, filtered during the normalizer's index build)
2. Propagate it from `MondoDiseaseRecord` → `DiseaseRecord` → `ProgramRecord` fields
3. Update `DiseaseMapExporter` and `MapIndexExporter` to include `therapeutic_area` in exported artifacts

**Constraint:** Therapeutic area mapping in MONDO is coarse (disease areas, not precision medicine categories). Do not attempt to build a custom therapeutic area taxonomy in Phase 13 — use whatever MONDO provides verbatim.

**Deliverable:**  
- `DiseaseRecord.therapeutic_area` populated where MONDO provides it
- `disease_map_summary.json` updated to include `therapeutic_area` per entry
- `map_index.json` updated to include `therapeutic_area` grouping
- Verification: at least some fraction of disease records have non-null `therapeutic_area` in post-Phase-13.4 artifacts

---

### Phase 13.5 — R6: Mechanism normalizer coverage (separate workstream planning)

**Priority:** Low (planning only in Phase 13)  
**Status:** 99.9% unknown rate; separate workstream required

**Problem:**  
The mechanism normalizer covers ~30 entries in its manual dictionary. CT.gov intervention names are not matched as mechanisms — they are drug names, not mechanism descriptors. The result is that `mechanism_class` is null for essentially all program records.

**Why this is harder than R2–R5:**  
- Mechanisms in biotech are expressed inconsistently (MOA descriptions, target names, pathway names, drug class names, brand names, INN stems — all may refer to the same mechanism)
- A complete mechanism normalizer requires either a curated ontology (e.g., ChEMBL mechanism of action), a drug-to-target mapping (e.g., DrugBank), or both
- Phase 3 mechanism normalizer was built for a narrow dictionary; expanding it to CT.gov coverage is a significant effort

**Phase 13 deliverable (planning only):**  
A design memo at `docs/governance/SCIART_MECHANISM_COVERAGE_DESIGN_2026_06_23.md` covering:
1. What data sources are available locally (ChEMBL, DrugBank, OpenTargets, existing normalizer dict)
2. What coverage level is achievable without external API calls (cache-only constraint)
3. Recommended approach: extend dictionary OR add a drug-name-to-mechanism resolver OR both
4. Estimated scope (line count, test count, timeline)
5. Governance constraints: any new mechanism mapping must be READ_ONLY_DIAGNOSTIC and not wired into scoring

**No implementation in Phase 13.** Implementation proceeds only after the design memo is reviewed and authorized.

---

## Success Criteria for Phase 13

| Item | Metric | Target |
|---|---|---|
| R2 (ctgov path) | ticker linkage in wrapper run without workaround | ≥ 97% |
| R4 (sample review) | Review doc complete, verdict delivered | 50 records reviewed |
| R3 (confidence) | confidence == 0.0 rate | < 5% |
| R5 (therapeutic_area) | non-null rate | > 0% (MONDO-limited) |
| R6 (mechanism) | Design memo complete | No implementation |

---

## What Is NOT Changing in Phase 13

- Ranker weights, selector, sizing, final_score, portfolio gates — **FROZEN**
- Production snapshots — **READ_ONLY**
- Any cartography field wired into scoring — **PROHIBITED**
- EES (Expectation Error Score) — **DO_NOT_PROMOTE**, separate diagnostic track
- Phase 13 proceeds only after operator confirms R1 (artifact promotion)
