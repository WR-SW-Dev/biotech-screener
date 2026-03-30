# Errors Log

<!-- Self-improving agent error entries. Format: [ERR-YYYYMMDD-XXX] -->

## [ERR-20260329-001] open_targets_drug_query_400

**Logged**: 2026-03-29T17:00:00Z
**Priority**: high
**Status**: resolved
**Area**: data_pipeline

### Summary
Open Targets drug detail query returned HTTP 400 — field `maxPhaseForIndication` does not exist on `ClinicalIndicationFromDrug` type.

### Error
```
HTTP 400: {"errors":[{"message":"Cannot query field 'maxPhaseForIndication' on type 'ClinicalIndicationFromDrug'."}]}
```

### Context
The OT API schema changed the field name to `maxClinicalStage`. The `_graphql_post` helper was swallowing the 400 error silently (returning None), so the failure appeared as "0 results" rather than an explicit error.

### Suggested Fix
Applied: renamed field to `maxClinicalStage`. Also added two-step query pattern (search → detail) to avoid SearchResult type fragment issue.

### Metadata
- Reproducible: yes (prior to fix)
- Related Files: tools/enrich_open_targets.py
- See Also: LRN-20260329-003

## [ERR-20260329-002] snapshot_double_nesting

**Logged**: 2026-03-29T17:45:00Z
**Priority**: medium
**Status**: resolved
**Area**: ops

### Summary
run_screen.py with `--snapshot-dir data/snapshots/2026-03-28` nested output under `data/snapshots/2026-03-28/2026-03-28/` instead of directly in the target directory.

### Error
Screen output files were under a double-nested path. Had to manually `mv` files up one level.

### Context
The `--snapshot-dir` flag appends the date as a subdirectory internally. When the user provides a date-suffixed path, it creates double nesting.

### Suggested Fix
Either use `--snapshot-dir data/snapshots` (without date) or strip trailing date from the provided path. Documented as known behavior.

### Metadata
- Reproducible: yes
- Related Files: run_screen.py
