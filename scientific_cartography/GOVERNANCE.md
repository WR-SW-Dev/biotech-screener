# Scientific Cartography Layer — Governance

## Classification

```
SCIENTIFIC_CARTOGRAPHY_CONTEXT_LAYER
READ_ONLY_DIAGNOSTIC
NO_RANKER_CHANGE
NO_SELECTOR_CHANGE
NO_SIZING_CHANGE
NO_ALPHA_PROMOTION
POINT_IN_TIME_SAFE_REQUIRED
```

## What Is Allowed

✅ Produce diagnostic CSV with optional scientific map columns  
✅ Produce disease/mechanism/competitive maps and summaries  
✅ Produce research watchlists as artifacts (not as portfolio input)  
✅ Flag low-confidence and unmapped records  
✅ Add documentation and schema evolution  
✅ Create standalone exploratory analyses  

## What Is Forbidden

❌ Modify `final_score` based on scientific map features  
❌ Add crowding/white-space into `ranker_v2_score`  
❌ Change `selector` eligibility based on mechanism/competition  
❌ Change position sizing based on map features  
❌ Add governance gates driven by map data  
❌ Promote scientific map alpha without explicit approval  
❌ Use LLM-only disease/mechanism assignments as source-of-truth  
❌ Make network calls during production snapshot generation  

## Approval Gates

| Change Type | Approval Required | Notes |
|---|---|---|
| Add diagnostic-only columns to rankings CSV | None (Phase 6) | Must document as advisory-only |
| Modify disease normalizer logic | Module owner | Changes to normalization must be tested |
| Add new source (MONDO, CTGov, etc.) | Module owner | Document source priority |
| Add new feature (crowding, white-space, etc.) | Module owner | Must be documented as diagnostic |
| Feed map features into ranker/selector/final_score | **Full governance review** | **PROHIBITED in v1** |
| Promote map-derived alpha | **Full governance review** | **PROHIBITED in v1** |
| Create LLM extraction pipeline | **Full governance review** | Outputs must be cached, cited, reviewed |

## Point-in-Time Discipline

Every record must include:

```python
record = {
    "as_of_date": "YYYY-MM-DD",     # Date this record is valid
    "source_refs": ["ref1", "ref2"],  # Traceable sources
}
```

Production builds enforce:

- ❌ No source files dated after `as_of_date` (except static ontologies)
- ❌ No live API calls during snapshot generation
- ✅ All caches read from `{as_of_date}` folder
- ✅ All outputs written with matching `as_of_date`

## Testing Requirements

Each new feature must have:

- Unit tests proving correct behavior
- Tests proving unknowns remain unknown
- PIT audit showing no future-dated sources
- Integration test with Phase 1 normalizers

Example:

```python
def test_unmapped_disease_stays_unmapped():
    """Unknowns must not be forced into low-confidence mappings."""
    normalizer = DiseaseNormalizer()
    result = normalizer.normalize("totally_unknown_disease_xyz")
    assert result.confidence < 0.5  # Not guessed
    assert result.normalized_name == "totally_unknown_disease_xyz"  # Preserved
```

## Source Prioritization

Fixed priority order (no runtime changes):

1. **Manual overrides** (trusted, highest confidence)
2. **MONDO ontology** (authoritative disease mapping)
3. **ClinicalTrials.gov** (public trial registry)
4. **SEC filings** (company-disclosed programs)
5. **FDA** (regulatory history)
6. **Open Targets** / **ChEMBL** (mechanism/target data)
7. **PubMed** / **Patents** (optional future research context)

Sources **cannot** be reordered at runtime. If source priority needs to change, it requires a new explicit deployment.

## Cache Management

**Production snapshots** use cache-only mode:

```bash
python -m scientific_cartography.cli build --cache-only
```

**Explicit refresh jobs** use refresh commands:

```bash
python -m scientific_cartography.cli refresh-source --source ctgov
```

Refresh jobs write dated caches, never mutate shared source files.

## Unknown Handling

Rules:

| Scenario | Behavior | Confidence |
|---|---|---|
| Exact manual override match | Use override | 1.0 |
| Exact MONDO match | Use MONDO record | 0.95 |
| Synonym match in MONDO | Use MONDO record | 0.90 |
| No match found | Preserve raw input | 0.0 |
| Ambiguous (multiple matches) | Preserve raw input | 0.0 |

Do not use fuzzy matching or inference in Phase 0/1. Unknown data stays unknown.

## Escalation Path

| Issue | Owner | Timeline |
|---|---|---|
| Bug in normalizer | Module owner | 1 business day |
| Source data staleness | Data team | 2 business days |
| Request to feed map into ranker | Governance committee | 1 week review |
| Proposal for LLM extraction | Governance committee | 2 week review |

## Review Cadence

| Milestone | Frequency |
|---|---|
| Coverage report (QA) | Every build |
| Confidence distribution | Weekly |
| Source audit (PIT violations) | Weekly |
| Governance compliance | Monthly |

## Compliance Checklist

Before each release:

- [ ] No changes to `final_score`, `ranker`, `selector`, or `sizing`
- [ ] All diagnostic columns are prefixed `scientific_map_*` or similar
- [ ] All diagnostic columns documented in README as advisory-only
- [ ] Point-in-time audit passes (no future-dated sources)
- [ ] Coverage report generated and reviewed
- [ ] Unit tests pass
- [ ] No network calls in production builds
- [ ] All records have `as_of_date` and `source_refs`
- [ ] Low-confidence records documented

## Version Pinning

Current version: **v0.1** (Phase 0/1 skeleton)

Schema version in build reports:

```json
{
  "schema_version": "0.1",
  "status": "Phase 0/1: Skeleton and normalizers"
}
```

Schema changes require version bump and changelog entry.
