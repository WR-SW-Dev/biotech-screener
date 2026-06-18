# Phase 13C-lite Scope: Diagnostic Artifact Generation

**Status:** APPROVED  
**Decision:** DEFER_DASHBOARD / DEFER_MECHANISM_TARGET_EXPANSION  
**Scope:** Repeatable diagnostic artifact generation (not production deployment)

## Requirements Checklist

### 1. Default Behavior (No Changes)
- [ ] Daily pipeline passes all 323 tests without `--run-scientific-cartography-phase13c` flag
- [ ] Default behavior: skip Phase 13C (no performance impact)
- [ ] CLI flag required to enable: `--run-scientific-cartography-phase13c`
- [ ] Non-blocking: failures logged as WARN, do not halt pipeline

### 2. Output & Manifest
- [ ] Artifacts written to: `artifacts/scientific_cartography/<as_of_date>/`
- [ ] Manifest file: `scientific_cartography_manifest.json`
- [ ] Manifest includes:
  - `file_count`: number of generated files
  - `total_size_mb`: sum of file sizes
  - `runtime_seconds`: execution time
  - `governance`: all flags set to correct values
  - `safety_checks`: size_guard_pass, forbidden_fields_scan result, governance_flags_valid

### 3. Safety Guards
- [ ] Size guard: fail if total output > 2GB
- [ ] Forbidden-field scan: error if any artifact contains:
  - "score" (numeric or comparative)
  - "rank" / "ranking"
  - "weight"
  - "final_score"
  - "buy" / "sell" / "recommend" (as action language, not in disclaimers)
- [ ] Governance flag validation: all artifacts have `read_only_diagnostic=true`

### 4. Tests
- [ ] Regression test: daily pipeline (323/323) with and without flag
- [ ] Manifest test: schema validation, completeness
- [ ] Boundary test: no files written to production directories
- [ ] Safety test: forbidden fields error case

### 5. No Production Changes
- [ ] Ranker logic: unchanged
- [ ] Selector logic: unchanged
- [ ] Sizing logic: unchanged
- [ ] Final score logic: unchanged
- [ ] Portfolio construction: unchanged

## Implementation Notes

**Current Status:** Commit cfe07a77 has basic Phase 13C hook. Needs:
1. Manifest generation (`scientific_cartography_manifest.json`)
2. Size guard check
3. Forbidden-field scan post-generation
4. Safety test cases

**Deferred:**
- Phase 13B (dashboard): until usage patterns known
- Phase 14 (mechanism/target expansion): separate design phase

## Decision Authority

✅ **APPROVED:** Phase 13C-lite as specified  
✅ **DEFERRED:** Phase 13B dashboard  
✅ **DEFERRED:** Phase 14 mechanism/target enhancement  

**Timeline:** 
- Implement Phase 13C-lite scope: 2026-06-18 to 2026-06-19
- Operational window: 2026-06-19 to ~2026-07-01 (manual triggers)
- Phase 13B decision gate: ~2026-07-01 (based on actual artifact usage)
