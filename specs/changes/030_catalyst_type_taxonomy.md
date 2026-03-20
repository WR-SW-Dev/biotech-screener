# Change Spec: Catalyst Type Quality Multiplier

**Status**: DRAFT
**Author**: Wake Robin Capital
**Date**: 2026-03-20
**Ruleset impact**: YES (requires promotion pipeline)

---

## Objective

Add a `catalyst_type_mult` that scales the existing catalyst signal by event quality.
Currently, all catalyst events are weighted by proximity and source confidence alone —
a confirmed PDUFA and a CT.gov primary completion date get equal treatment at the same
distance. This spec introduces a type-based multiplier so that higher-conviction event
types carry more weight in both the sort key and L3 sizing.

## Motivation

- 125/190 eligible names (66%) have `CT_PRIMARY_COMPLETION` as their catalyst — a soft
  calendar milestone, not a confirmed binary event.
- Only 8 names have `FDA_PDUFA_DATE` and 18 have `DATA_READOUT`.
- The existing `is_hard_catalyst` classifier already distinguishes hard vs soft events
  but this information does not flow into ranking or sizing — it is only used for
  options research filtering.
- The catalyst base is now materially stronger (SEC 8-K enrichment, secondary regulatory
  coverage 1.5%→5.4%, PDUFA calendar 7→15 names) so type discrimination is more
  tractable than it was pre-coverage-expansion.

## PIT / Data Constraints

- [x] No lookahead — catalyst_event_type is computed from PIT-safe event ledger
- [x] Data source: `event_ledger.py` (CATALYST_FAMILY_MAP), `common/hard_catalyst.py`
- [x] Historical availability: all archives since 2025-01-03
- [x] Known gaps: 22/190 eligible names have empty catalyst_event_type (12%)

## Design

### Type Quality Ladder

Multiplier on the existing catalyst contribution to sort key and L3 sizing.
Higher multiplier = stronger conviction that the event will produce a tradeable move.

| Tier | Event Types | Mult | Rationale |
|------|-------------|------|-----------|
| **T1: Confirmed regulatory** | FDA_PDUFA_DATE, FDA_ADCOM, FDA_APPROVAL, FDA_CRL, FDA_RTF, FDA_DECISION | 1.00 | Date-certain, binary outcome |
| **T2: Pivotal data** | DATA_READOUT, DATA_PRESENTATION | 0.90 | High-conviction but date less certain |
| **T3: ClinTrials calendar** | CT_PRIMARY_COMPLETION, CT_STUDY_COMPLETION | 0.60 | Calendar milestone, often noisy/delayed |
| **T4: Softer signals** | CT_RESULTS_POSTED, CT_DATE_CONFIRMED_ACTUAL, CT_TIMELINE_PULLIN, CT_STATUS_UPGRADE | 0.40 | Activity indicators, not event dates |
| **T5: Unknown/missing** | (empty), unmapped types | 0.50 | Conservative neutral |

### Integration Points

1. **Sort key**: `catalyst_type_mult` multiplies the catalyst-related sort contributions
   (catalyst_bonus, binary_quality, clinical_quality_91_180) in `compute_actionable_sort_key()`.

2. **L3 sizing**: `catalyst_type_mult` multiplies alongside `catalyst_tilt_mult` in
   `compute_target_weights()` — same pattern as cost_mult and mom_state_tilt_mult.

3. **Ruleset config**: New fields in `DecisionRuleset`:
   - `enable_catalyst_type_mult: bool = False` (default OFF)
   - `catalyst_type_mults: tuple` (tier→mult mapping, same pattern as `catalyst_tilt_mults`)

4. **Snapshot output**: New columns `catalyst_type_mult`, `catalyst_type_tier`,
   `catalyst_type_applied` for audit trail.

## Inputs

| Input | Source | Schema |
|-------|--------|--------|
| catalyst_event_type | run_screen.py → event ledger | str, one of CATALYST_FAMILY_MAP keys or empty |
| catalyst_source | run_screen.py → event ledger | str (SEC_8K_FILING, CTGOV_CALENDAR, etc.) |
| is_hard_catalyst | common/hard_catalyst.py | bool |

## Outputs

| Output | Destination | Schema |
|--------|-------------|--------|
| catalyst_type_mult | rankings.csv, DE fields | float, 0.0–1.0 |
| catalyst_type_tier | rankings.csv, DE fields | str: T1/T2/T3/T4/T5 |
| catalyst_type_applied | rankings.csv, DE fields | str: "0" or "1" |

## Invariants

1. **Default OFF**: `enable_catalyst_type_mult = False` → mult = 1.0 for all names
2. **Deterministic**: same event_type + source → same tier + mult
3. **No eligibility change**: this is a sort/sizing multiplier, not an eligibility gate
4. **Budget conservation**: total weights still sum to ~100% after renormalization
5. **Backward compatible**: existing rulesets produce identical output when flag is OFF

## Failure Modes

| Scenario | Expected behavior |
|----------|-------------------|
| Missing catalyst_event_type | Tier T5, mult = 0.50 |
| Unknown/unmapped event type | Tier T5, mult = 0.50 |
| enable_catalyst_type_mult = False | mult = 1.0, no behavioral change |
| All names same tier | Reduces to current behavior (uniform scaling) |

## Validation Plan

### Tests (write BEFORE implementation)
- [ ] `test_catalyst_type_mult_default_off` — flag=False → all mults = 1.0
- [ ] `test_catalyst_type_mult_tier_mapping` — each event type → correct tier + mult
- [ ] `test_catalyst_type_mult_missing_event` — empty event_type → T5/0.50
- [ ] `test_catalyst_type_mult_deterministic` — same inputs → same outputs
- [ ] `test_catalyst_type_mult_budget_conservation` — weights still sum to ~100%
- [ ] `test_catalyst_type_mult_sort_key_impact` — T1 names sort higher than T3 at same optionality

### Evaluation (if signal/ranking change)
- [ ] Replay against active baseline (9f1f4587) across 31 usable archives
- [ ] Per-bucket forward return comparison (binary_now, build_window, less_binary)
- [ ] Top-60 overlap >= 90% (rank-impact gate)
- [ ] Mean rank shift < 5
- [ ] Acceptance replay: weekly policy simulation → KEEP_ACTIVE or NEEDS_MORE
- [ ] Primary bar: +0.20pp at 60d hedged residual
- [ ] Guardrail: no worse than -0.05pp at 60d

### Integration
- [ ] Full test suite passes
- [ ] No pre-commit hook failures
- [ ] Snapshot columns render correctly

## Expected Effect Size

Moderate. The main expected improvement is in **less_binary** and **build_window** buckets
where CT_PRIMARY_COMPLETION dominates (66% of eligible names). By downweighting calendar
milestones relative to confirmed regulatory events and data readouts, the sort should
better differentiate high-conviction catalyst names from calendar noise.

Effect on top-of-book (binary_now + build_window top 20) is expected to be small because
those names are already sorted primarily by clinical optionality, not catalyst quality.

Honest estimate: this is a structural improvement that should improve **selection quality
at the margin**, not a dramatic IC lift. "Helpful but not transformative" is the right
expectation.

## Non-Goals

- Do NOT replace the optionality anchor
- Do NOT change eligibility gates
- Do NOT apply to non-catalyst ranking factors
- Do NOT create a new top-level global factor
- Do NOT reweight the entire sort key — only the catalyst-dependent contributions
- Do NOT promote without clearing the standard governance battery

---

## Implementation Log

### 2026-03-20 — Spec drafted
- Based on sort contribution audit showing top-of-book is 100% optionality-anchored
- Catalyst overlays only fire for less_binary (names 23+)
- Distribution: 125 CT_PRIMARY_COMPLETION, 18 DATA_READOUT, 8 FDA_PDUFA_DATE, 22 empty
- Existing hard_catalyst classifier provides the foundation; this spec adds gradation

---

*Template version: 1.0.0 — see specs/SYSTEM_SPEC.md for system invariants*
