# Scientific Cartography Layer

A read-only diagnostic module that maps the investable biotech universe by disease, mechanism, asset, stage, evidence, competitive context, and inflection points.

## What This Does

- **Disease mapping**: Normalizes raw disease labels → canonical MONDO/normalized disease records
- **Stage normalization**: Standardizes clinical stage strings across multiple sources
- **Asset tracking**: Links assets to indications, mechanisms, and sponsors
- **Competitive context**: Identifies competitor programs and mechanism crowding
- **Evidence grids**: Tracks evidence quality and trial design strength (diagnostic only)
- **Landscape features**: Computes white-space and crowding scores (diagnostic only)

## What This Does NOT Do

❌ Modify `final_score`, `ranker_v2_score`, `selector` eligibility, or portfolio sizing  
❌ Feed new columns into production ranking  
❌ Change portfolio construction or action labels  
❌ Promote new alpha signals  
❌ Use LLM outputs as source-of-truth without review/caching  

All outputs are **read-only diagnostic context** only.

## Governance

```text
SCIENTIFIC_CARTOGRAPHY_CONTEXT_LAYER
READ_ONLY_DIAGNOSTIC
NO_RANKER_CHANGE
NO_SELECTOR_CHANGE
NO_SIZING_CHANGE
NO_ALPHA_PROMOTION
POINT_IN_TIME_SAFE_REQUIRED
```

## Quick Start

### Phase 0/1: Skeleton & Normalizers (Current)

Available now:
- Disease normalizer with manual override support
- Stage normalizer with hierarchy rules
- CLI shell for build and QA
- Test suite for normalizers

```bash
# Build artifacts from cache (no network calls)
python -m scientific_cartography.cli build \
  --as-of-date 2026-06-16 \
  --snapshot-dir artifacts/snapshots/2026-06-16 \
  --output-dir artifacts/scientific_cartography/2026-06-16

# Run QA
python -m scientific_cartography.cli qa \
  --as-of-date 2026-06-16 \
  --artifact-dir artifacts/scientific_cartography/2026-06-16
```

### Phase 1–7 (Upcoming)

| Phase | Feature | Status |
|-------|---------|--------|
| 0 | Package skeleton, schemas, CLI | ✅ |
| 1 | Disease + stage normalization | ✅ |
| 2 | Asset/program builder | 🔜 |
| 3 | Mechanism/modality classification | 🔜 |
| 4 | Competitive clusters | 🔜 |
| 5 | Landscape features | 🔜 |
| 6 | Exporters | 🔜 |
| 7 | QA hardening | 🔜 |

## Key Design Principles

### Unknowns Stay Unknown

If a disease/mechanism/stage cannot be confidently mapped, we preserve the raw input with `confidence < 0.5`, not invent mappings.

```python
# Bad
mapping = {"unmapped_disease": "Unknown Disease"}  # ❌

# Good
record = DiseaseRecord(
    raw_name="unmapped_disease",
    normalized_name="unmapped_disease",
    confidence=0.0,  # Low confidence flag
    source="unmapped",
)
```

### Point-in-Time Safety

Every record includes `as_of_date`. Production builds reject source files newer than `as_of_date` (except static ontologies).

```python
record = DiseaseRecord(
    ...,
    as_of_date="2026-06-16",
    source_refs=["NCT123456", "SEC filing 8-K"],
)
```

### Cache-Only Production

Production builds pass `--cache-only` and reject live API calls:

```bash
python -m scientific_cartography.cli build --cache-only  # ✅
```

Live refresh is a separate explicit command.

## Artifact Layout

```
artifacts/scientific_cartography/{as_of_date}/
├── build_report.json
├── coverage_report.json
├── point_in_time_audit.json
├── disease_records.jsonl
├── program_records.jsonl
└── disease_maps/
    └── {normalized_disease_slug}/
        └── landscape.json
```

## Source Priority

1. **Manual overrides** (highest priority)
2. **MONDO** disease ontology
3. **ClinicalTrials.gov** condition labels
4. **SEC** filing data
5. **Open Targets** / **ChEMBL** (future phases)
6. **PubMed** metadata (optional future)

## Testing

```bash
# Run Phase 0/1 tests only
pytest tests/scientific_cartography/test_disease_normalizer.py -v
pytest tests/scientific_cartography/test_stage_normalizer.py -v
```

## Acceptance Criteria

Phase 0/1 passes if:

- ✅ Package imports without errors
- ✅ Disease normalizer tests pass (exact match, manual override, unknown preservation)
- ✅ Stage normalizer tests pass (hierarchy, active/inactive, ranking)
- ✅ CLI build command runs cache-only
- ✅ CLI qa command generates stub reports
- ✅ No production code modified (ranker, selector, sizing, final_score)

## Next Steps

1. Phase 2: Asset/program builder with SEC/ClinicalTrials.gov data ingestion
2. Phase 3: Mechanism normalizer with target/modality classification
3. Phase 4: Competitive cluster construction
4. Phase 5: Landscape feature engineering (crowding, white-space, differentiation)
5. Phase 6: Export to rankings diagnostics CSV
6. Phase 7: QA hardening and manual artifact review

## For Developers

### Adding a New Normalizer

1. Create `scientific_cartography/normalize/new_normalizer.py`
2. Implement `class NewNormalizer` with `normalize()` and `bulk_normalize()` methods
3. Add unit tests under `tests/scientific_cartography/test_new_normalizer.py`
4. Register in `scientific_cartography/__init__.py`
5. Add to CLI subcommand
6. Document in this README

### Adding Source Data

1. Create `scientific_cartography/ingest/source_ingest.py`
2. Implement loader (cache-only for production, refresh-capable for explicit commands)
3. Test for PIT compliance (`future_dated_sources` detection)
4. Document source priority

## Contact

See `GOVERNANCE.md` for decision-making and escalation paths.
