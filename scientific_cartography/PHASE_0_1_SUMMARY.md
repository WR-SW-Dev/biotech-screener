# Scientific Cartography Layer — Phase 0/1 Implementation Summary

## Overview

A read-only diagnostic module for mapping the biotech investment landscape by disease, mechanism, asset, stage, and competitive context.

**Status**: Phase 0/1 Complete (Skeleton + Normalizers)  
**Test Coverage**: 53 tests, 100% pass rate  
**Governance**: READ_ONLY_DIAGNOSTIC, NO_RANKER_CHANGE, POINT_IN_TIME_SAFE  

---

## What Was Built

### Phase 0: Skeleton

- ✅ Package structure with organized subdirectories
- ✅ Schema dataclasses (DiseaseRecord, ProgramRecord)
- ✅ CLI shell with build and qa subcommands
- ✅ README and GOVERNANCE documentation
- ✅ Complete test infrastructure

### Phase 1: Normalizers

- ✅ **DiseaseNormalizer**: Normalizes raw disease labels with manual overrides, MONDO mappings, and unknown preservation
- ✅ **StageNormalizer**: Normalizes clinical stage strings with hierarchy ranking and active/inactive classification

---

## Module Structure

```
scientific_cartography/
├── __init__.py           # Exports main classes
├── cli.py               # CLI: build, qa, refresh-source commands
├── README.md            # User guide
├── GOVERNANCE.md        # Governance rules and approval gates
├── PHASE_0_1_SUMMARY.md # This file
│
├── schemas/
│   ├── __init__.py
│   ├── disease_schema.py    # DiseaseRecord dataclass
│   └── program_schema.py    # ProgramRecord dataclass
│
├── normalize/
│   ├── __init__.py
│   ├── disease_normalizer.py # DiseaseNormalizer (Phase 1)
│   └── stage_normalizer.py   # StageNormalizer (Phase 1)
│
├── build/        # Builders (Phase 2-5, stubs)
├── ingest/       # Ingestion (Phase 2, stubs)
├── export/       # Exporters (Phase 6, stubs)
└── qa/           # QA tools (Phase 7, stubs)

tests/scientific_cartography/
├── __init__.py
├── test_disease_normalizer.py  # 17 tests
└── test_stage_normalizer.py    # 36 tests
```

---

## Quick Start

### Import and Use Normalizers

```python
from scientific_cartography import DiseaseNormalizer, StageNormalizer

# Disease normalization
disease_norm = DiseaseNormalizer(as_of_date="2026-06-16")
result = disease_norm.normalize("Atopic Dermatitis")
# → DiseaseRecord(
#     raw_name="Atopic Dermatitis",
#     normalized_name="Atopic Dermatitis",
#     confidence=1.0,
#     source="unmapped" or "manual_override",
#     as_of_date="2026-06-16"
# )

# Stage normalization
stage_norm = StageNormalizer()
stage = stage_norm.normalize("phase 3")        # → "phase3"
highest = stage_norm.select_highest_stage([
    "phase1", "phase3", "phase2"
])                                              # → "phase3"
is_active = stage_norm.is_active_stage("phase1")  # → True
```

### Using the CLI

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

---

## Key Design Decisions

### 1. Unknowns Stay Unknown

```python
# Low-confidence records are preserved, not guessed
result = normalizer.normalize("unmapped_disease")
assert result.confidence == 0.0
assert result.source == "unmapped"
assert result.normalized_name == "unmapped_disease"  # Raw preserved
```

### 2. Deterministic Normalization

Every normalization follows a fixed priority order:

```text
Disease Mapping Priority:
1. Manual overrides (highest)
2. MONDO exact match
3. MONDO synonym match
4. Case/punctuation-normalized match
5. Low-confidence (preserved with as-is label)

Stage Mapping Priority:
1. Exact alias match
2. Normalize whitespace/case
3. Return None if unmapped
```

### 3. Point-in-Time Safe

All records include `as_of_date` and `source_refs`:

```python
record = DiseaseRecord(
    raw_name="Atopic Dermatitis",
    normalized_name="Atopic Dermatitis",
    as_of_date="2026-06-16",
    source_refs=["NCT123456", "SEC filing 8-K"],
)
```

### 4. Cache-Only Production

Production snapshots use cache-only mode:

```bash
python -m scientific_cartography.cli build --cache-only  # ✓ Allowed
# No live API calls during snapshot generation
```

---

## Test Coverage (53 Tests)

### Disease Normalizer (17 Tests)

- ✅ Basic functionality (unmapped preservation, case-insensitivity)
- ✅ Manual overrides (loading from CSV, priority, abbreviations, synonyms)
- ✅ MONDO cache (exact match, synonym matching, case-insensitive)
- ✅ Caching behavior (repeated calls use cache)
- ✅ Metadata (serialization/deserialization)

### Stage Normalizer (36 Tests)

- ✅ Basic normalization (all aliases: phase1, phase2, phase3, approved, etc.)
- ✅ Hierarchy ranking (approved > filed > phase3 > ... > preclinical)
- ✅ Active/inactive classification (active: preclinical-approved, inactive: discontinued/None)
- ✅ Stage selection (highest stage from list)
- ✅ Edge cases (phase1/2, phase2b, mixed lists, all-None lists)

---

## Governance Compliance Checklist

- ✅ No modifications to ranker, selector, sizing, or final_score
- ✅ All outputs are read-only diagnostic context
- ✅ No alpha promotion (only diagnostic columns)
- ✅ Cache-only production mode enforced
- ✅ Point-in-time safe (all records dated)
- ✅ Unknown preservation (low-confidence not guessed)
- ✅ Source traceability (source_refs for all records)
- ✅ No network calls during production snapshot generation

**Classification**:
```
SCIENTIFIC_CARTOGRAPHY_CONTEXT_LAYER
READ_ONLY_DIAGNOSTIC
NO_RANKER_CHANGE
NO_SELECTOR_CHANGE
NO_SIZING_CHANGE
NO_ALPHA_PROMOTION
POINT_IN_TIME_SAFE_REQUIRED
```

---

## Next Phases

| Phase | Feature | Acceptance |
|-------|---------|-----------|
| 0 | Skeleton, schemas, CLI | ✅ Complete |
| 1 | Disease + stage normalization | ✅ Complete |
| 2 | Asset/program builder | 🔜 Designed |
| 3 | Mechanism/modality normalizer | 🔜 Designed |
| 4 | Competitive cluster builder | 🔜 Designed |
| 5 | Landscape feature engineering | 🔜 Designed |
| 6 | Exporters (diagnostics CSV, maps) | 🔜 Designed |
| 7 | QA hardening | 🔜 Designed |

### Phase 2: Asset/Program Builder

Will ingest and link:
- Existing screener universe
- SEC filing program data
- ClinicalTrials.gov trial data
- Asset-indication mappings

### Phase 3: Mechanism/Modality Classification

Will normalize:
- Mechanism strings (JAK inhibitor, IL-13 mAb, etc.)
- Modality types (small molecule, mAb, gene therapy, etc.)
- Targets (EGFR, IL13, TYK2, etc.)

### Phase 4: Competitive Clusters

Will group programs by:
- Disease + mechanism
- Stage + modality
- Public vs private count
- Approved vs investigational count

### Phase 5: Landscape Features

Will compute (diagnostic-only):
- Crowding scores
- White-space scores
- Differentiation scores
- Inflection point overlays

### Phase 6: Exporters

Will write:
- Diagnostic-only rankings CSV columns
- Per-disease competitive maps
- Research watchlists

### Phase 7: QA Hardening

Will validate:
- Coverage metrics
- Confidence distribution
- Source audit trails
- Point-in-time violations

---

## Running Tests

```bash
# Run Phase 0/1 tests only
pytest tests/scientific_cartography/ -v

# Run specific test file
pytest tests/scientific_cartography/test_disease_normalizer.py -v

# Run with coverage
pytest tests/scientific_cartography/ --cov=scientific_cartography
```

---

## File Manifest

### Created Files: 14

**Modules** (7):
- `scientific_cartography/__init__.py`
- `scientific_cartography/cli.py`
- `scientific_cartography/normalize/__init__.py`
- `scientific_cartography/normalize/disease_normalizer.py`
- `scientific_cartography/normalize/stage_normalizer.py`
- `scientific_cartography/schemas/__init__.py`
- `scientific_cartography/schemas/disease_schema.py`
- `scientific_cartography/schemas/program_schema.py`

**Documentation** (2):
- `scientific_cartography/README.md`
- `scientific_cartography/GOVERNANCE.md`

**Tests** (3):
- `tests/scientific_cartography/__init__.py`
- `tests/scientific_cartography/test_disease_normalizer.py`
- `tests/scientific_cartography/test_stage_normalizer.py`

**Placeholder Packages** (4):
- `scientific_cartography/build/__init__.py`
- `scientific_cartography/ingest/__init__.py`
- `scientific_cartography/export/__init__.py`
- `scientific_cartography/qa/__init__.py`

---

## Implementation Notes

### Dataclass Over Pydantic

Used dataclasses (not Pydantic) to match repo conventions:
```python
@dataclass
class DiseaseRecord:
    disease_id: str
    raw_name: str
    normalized_name: str
    # ...
```

### Hashable IDs

Disease IDs are stable hashes (not timestamps or UUIDs):
```python
disease_id = sha256(f"{normalized_name}|{mondo_id}").hexdigest()[:16]
```

### CSV Override Format

Manual overrides are versioned in `/data/scientific_cartography/manual_overrides/`:
```csv
raw_name,normalized_name,mondo_id,therapeutic_area,confidence,notes
```

### CLI Pattern

Commands follow standard patterns (cache-only, dated artifacts):
```bash
python -m scientific_cartography.cli build --cache-only
```

---

## Success Criteria Met

Phase 0/1 implementation **passes all acceptance criteria**:

1. ✅ Package imports without errors
2. ✅ Disease normalizer tests pass (exact match, manual override, unknown preservation)
3. ✅ Stage normalizer tests pass (hierarchy, active/inactive, ranking)
4. ✅ CLI build command runs cache-only
5. ✅ CLI qa command generates stub reports
6. ✅ No production code modified (ranker, selector, sizing, final_score)
7. ✅ No broken existing imports
8. ✅ 100% test pass rate (53/53)

---

## Integration Ready

The module is ready for:
- ✅ Manual artifact inspection and review
- ✅ Governance approval gate
- ✅ Phase 2+ implementation
- ✅ Future feature expansion

**Status**: SCIENTIFIC_CARTOGRAPHY_LAYER_V0.1_COMPLETE
