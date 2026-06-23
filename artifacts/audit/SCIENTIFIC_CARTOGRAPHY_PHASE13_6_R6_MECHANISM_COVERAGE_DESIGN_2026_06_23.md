# Scientific Cartography Phase 13.6 — R6 Mechanism Coverage Design Memo
**Date:** 2026-06-23
**Type:** DESIGN_ONLY — no code changes in this phase
**Verdict:** `DESIGN_ONLY_R6_MECHANISM_COVERAGE_PLAN_READY_FOR_FUTURE_IMPLEMENTATION`

---

## 1. Current State

### What the normalizer does

`MechanismNormalizer` has two resolution paths:

1. **Manual alias dict** (`mechanism_aliases`): maps `raw_text` → mechanism
   data. Loaded from CSV or passed at construction. Currently always empty —
   no alias CSV exists on disk.

2. **Built-in mechanism phrase dict** (`_mechanism_dict`): ~30 entries like
   `"jak inhibitor"`, `"parp inhibitor"`, `"pd-1 inhibitor"`. Matched by exact
   or substring lookup against the raw intervention text.

### Observed coverage

Running the normalizer against representative CT.gov biotech drug names:

```
RMC-6236             → mechanism=None  modality=None
sotorasib            → mechanism=None  modality=None
pembrolizumab        → mechanism=None  modality=None
venetoclax           → mechanism=None  modality=None
olaparib             → mechanism=None  modality=None
nivolumab            → mechanism=None  modality=None
ibrutinib            → mechanism=None  modality=None
BGB-3111             -> mechanism=None  modality=None
MRTX-1719            → mechanism=None  modality=None
```

Every CT.gov drug name returns `mechanism=None`. The `_mechanism_dict` is
never hit because intervention text from CT.gov is a drug name ("olaparib"),
not a mechanism descriptor ("PARP inhibitor"). The alias CSV that would bridge
drug names to mechanism classes does not exist.

### Why sparse mechanism coverage weakens RA-style maps

A disease landscape map groups competitive programs by
`disease_id | mechanism_class | modality | target`. When `mechanism_class` is
null for ~100% of records, every program falls into one undifferentiated
"unknown mechanism" lane. The map cannot answer:

- "How many PD-1 programs in NSCLC versus KRAS inhibitors?"
- "Which mechanisms are crowded versus white-space?"
- "Is this asset entering an already-saturated mechanism class?"

The map structure exists and is correct. The lanes are empty because the
name-to-mechanism bridge is missing, not because the data is absent from
the underlying CT.gov registrations.

**Unknown mechanism lanes must remain explicit.** They should appear as
`mechanism_class="unknown"` in coverage reports rather than being collapsed or
hidden, so the map honestly represents the current knowledge state. Hiding
unknowns would make coverage look artificially high.

---

## 2. Root-Cause Categories

### 2a. Missing alias CSV

The most direct fix. `MechanismNormalizer.from_csv()` already accepts a
`raw_text,mechanism_class,target,modality,confidence,notes` CSV. The method
is implemented and tested. The file simply does not exist. A manually curated
CSV with ~50–200 well-known INN drug names would cover the majority of the
screener universe.

### 2b. Weak asset alias resolution feeding into mechanism

`AssetAliasResolver` returns `resolution_status='unknown'` for CT.gov
intervention names (R3 fix addressed confidence; mechanism was out of scope).
Even if the asset alias resolver resolved a drug to a known internal asset
record, no mechanism is stored in the alias dict. Asset alias records carry
`asset_id` and `confidence` but not `mechanism_class` or `target`. Bridging
the two requires either enriching the alias dict with mechanism fields or
building a separate drug-to-mechanism mapping.

### 2c. Free-text mechanism not extracted

CT.gov `brief_title` and `detailed_description` often contain the mechanism
description inline ("A Phase 2 Study of the KRAS G12C Inhibitor RMC-6236...").
Extracting mechanism from free text is feasible for known phrases but
introduces false-positive risk at scale. This is a future path, not the
first approach.

### 2d. Target available, mechanism_class missing

The mechanism dict stores target alongside mechanism (e.g., KRAS → KRAS
inhibitor). If the asset alias resolver returns a target name, a
target-to-mechanism lookup could fill the gap. No such lookup table currently
exists. Building one is low-risk because target → mechanism is largely 1:1 for
the biotech screener universe.

### 2e. CT.gov names lacking mechanism in source

CT.gov intervention names are INN drug names or company codes. They carry no
mechanism metadata at the source. The gap is a lookup problem, not a source
data problem.

### 2f. Unknown preservation working as intended

The `resolution_status="unknown"` fallback is correct behavior, not a bug.
The normalizer correctly refuses to guess. The fix is to fill the lookup table,
not to loosen the matching logic.

---

## 3. Candidate Data Sources (Design Only)

### Tier 1 — existing cache/artifacts, no new fetch required

**Mechanism alias CSV** (`scientific_cartography/data/mechanism_aliases.csv`)
Manually curated mapping of INN drug names and company codes to mechanism
class/target/modality. Format already supported by `MechanismNormalizer.from_csv()`.
Can cover 50–200 names with a few hours of curation. This is the recommended
first implementation.

**Asset alias resolver enrichment**
Extend asset alias records to carry optional `mechanism_class`, `target`,
`modality` fields. When the asset alias resolver returns `resolution_status='resolved'`,
use those fields as the primary mechanism source. This co-locates asset and
mechanism enrichment in one lookup.

**Screener pipeline descriptions (SEC/deck-derived)**
If any existing cached artifact stores parsed mechanism descriptions from SEC
filings or company pipeline decks, those fields could be linked to the asset
alias dict. Requires verifying what mechanism-bearing fields exist in the
current cached artifacts before implementing.

### Tier 2 — future explicitly approved source layers (not this phase)

**Open Targets**
Provides drug → target → mechanism class mappings with literature support.
High coverage, machine-readable API. Requires: (1) explicit operator
authorization, (2) live-fetch gate, (3) cache layer so diagnostic runs remain
cache-only after initial fetch. **Not authorized for this phase.**

**ChEMBL**
INN name → mechanism of action + target. Similar coverage to Open Targets.
Same authorization requirement. **Not authorized for this phase.**

**PubMed / clinical trial registry free text**
NLP extraction from protocol text. High-risk (false positives),
high-maintenance, requires ML pipeline. **Not authorized for this phase.**

---

## 4. Proposed Mechanism Enrichment Hierarchy

Resolution priority, from highest to lowest confidence:

```
1. Manual alias CSV (mechanism_aliases.csv)
   raw_text exact match → mechanism_class, target, modality
   confidence = 0.95
   source = "manual_alias"

2. Asset alias resolver mechanism fields (future enrichment)
   asset_alias_resolved["mechanism_class"] if present and resolution_status='resolved'
   confidence = 0.90
   source = "asset_alias"

3. Target-to-mechanism lookup table (future)
   target name (from asset alias) → known mechanism class
   e.g., KRAS → "KRAS inhibitor"; PDCD1 → "PD-1 inhibitor"
   confidence = 0.80
   source = "target_derived"

4. Modality + target combined inference (future)
   modality="monoclonal antibody" + target="PDCD1" → "PD-1 inhibitor"
   Only when both are known; never from modality alone.
   confidence = 0.75
   source = "modality_target_derived"

5. Disease-specific curated mechanism fixture (future)
   e.g., all AD programs in Phase 3 with unknown mechanism: "unknown (AD)"
   Only for well-understood disease/mechanism landscapes.
   confidence = 0.60
   source = "disease_fixture"

6. Unresolved / unknown
   resolution_status = "unknown"
   mechanism_class = None
   confidence = 0.0
   Emit diagnostic warning; preserve in coverage report.
```

Each tier is additive. Higher-tier results block lower-tier lookup for the
same record. All tiers below Tier 1 are deferred to a future approved phase.

---

## 5. Confidence Model

`mechanism_confidence` should be tracked separately from `disease_confidence`
and `asset_confidence` in `ProgramRecord` (analogous to R3's
`confidence_warnings`). Rationale:

- Disease confidence is well-defined (MONDO coverage is narrow but
  accurate).
- Asset confidence is structural (R3 fixed the collapse issue; alias coverage
  is still sparse).
- Mechanism confidence is the sparsest of the three. Adding it to the hard
  `min()` floor would again collapse every record to 0.0 — the same bug R3
  fixed for asset confidence.

**Design rule:** mechanism_confidence participates in `overall_confidence`
only when `resolution_status='resolved'`. When unknown, it contributes a
diagnostic warning flag (`"mechanism_unresolved"`) to `confidence_warnings`
but does not reduce the floor. This preserves R3's invariant: confidence
reflects what is known, not what is absent.

**Coverage report metric:**
`programs_with_mechanism` / `total_programs` should be emitted in the
diagnostic wrapper alongside the R5 therapeutic_area coverage report. Unknown
mechanism must be counted, not hidden.

---

## 6. Map UX Impact

### Current state (after R5 but before R6 implementation)

- ~100% of mechanism lanes are `unknown`
- The disease map correctly shows a dominant "unknown mechanism" lane
- This is honest and must not be suppressed

### Correct interim behavior for the RA-style map prototype

- Use `therapeutic_area` (R5, now populated) as the primary grouping axis
- Within each therapeutic area, show disease clusters grouped by disease
- Suppress mechanism breakdown at map-render time until coverage > threshold
  (suggested: < 20% mechanism coverage → show "mechanism breakdown unavailable")
- Include a coverage indicator in map metadata so the UI can adapt

### After R6 implementation (Tier 1 only)

- Mechanism will be populated for well-known INN names (~50–200 drugs)
- Rare disease / early-stage names will remain unknown
- The map can show partial mechanism lanes for high-coverage disease areas
  (e.g., Oncology checkpoint programs)

### Longer term (Tier 2 sources authorized)

- Open Targets or ChEMBL would bring mechanism coverage to >70% for
  commercially registered drugs
- At that point, mechanism-lane grouping becomes the primary map axis

---

## 7. Test Plan

Tests to add when Tier 1 implementation is approved:

| Test | Behavior Verified |
|------|------------------|
| `test_manual_alias_csv_exact_match` | INN name in CSV → correct mechanism_class |
| `test_manual_alias_csv_case_insensitive` | "Pembrolizumab" matches "pembrolizumab" entry |
| `test_no_mechanism_for_unknown_asset` | Unknown drug name → mechanism=None, warning emitted |
| `test_mechanism_does_not_inflate_confidence` | Unknown mechanism → confidence unchanged from disease/sponsor floor |
| `test_mechanism_warning_flag_emitted` | "mechanism_unresolved" in confidence_warnings when unknown |
| `test_coverage_report_counts_unknown` | Diagnostic wrapper reports unknown_mechanism_count > 0 |
| `test_no_false_positive_from_substring` | "pembrolizumab" does NOT match via "mab" substring |
| `test_ambiguous_mechanism_produces_none` | Multi-phrase substring match → mechanism=None |

---

## 8. Governance

- DESIGN_ONLY: no code changes in this phase
- No ranker, selector, sizing, final_score, gates, snapshots, or portfolio changes
- No model promotion
- No freeze lift
- No live data fetch; no API calls to Open Targets, ChEMBL, PubMed
- No cron or scheduler activation

---

## 9. Recommended Next Implementation Gate

**Do not implement mechanism enrichment until after:**

1. Stage parser compatibility is fixed — stage is a core map axis and the
   all-unknown-stage issue is a field-name parser mismatch, not true missing
   data. Fixing stage takes priority over mechanism.

2. Map v0.2b prototype is generated against refreshed artifacts — the
   prototype will reveal which axes (mechanism vs. stage vs. disease) are
   most limiting for UX, and that should inform how much mechanism investment
   is warranted before the next UX review.

3. The alias CSV is validated on a sample run — build the CSV, run diagnostics,
   verify coverage %, and review false positives before committing the coverage
   improvement.

---

## 10. Summary

The mechanism coverage gap is structural: the normalizer architecture is
correct, the confidence model is sound, and the CSV-based enrichment path is
already implemented. The gap is a missing lookup table. Tier 1 implementation
(manual alias CSV covering ~100–200 well-known INN/company names) is a
half-day curation task that would provide meaningful coverage for the most
active disease areas. This should proceed after the stage parser fix and map
v0.2b prototype, not before, because the prototype will clarify how much
mechanism coverage is required before the map becomes actionable.
