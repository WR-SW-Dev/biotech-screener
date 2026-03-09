# Change Spec: [TITLE]

**Status**: DRAFT | IN_PROGRESS | IMPLEMENTED | ARCHIVED
**Author**: [name]
**Date**: YYYY-MM-DD
**Ruleset impact**: YES/NO (if YES, requires promotion pipeline)

---

## Objective

[1-2 sentences: what this change does and why it matters. Not how — just the goal.]

## PIT / Data Constraints

- [ ] No lookahead — all data access satisfies PIT rules
- [ ] Data source: [name specific files/APIs]
- [ ] Historical availability: [date range where data exists]
- [ ] Known gaps: [any periods or tickers without coverage]

## Inputs

| Input | Source | Schema |
|-------|--------|--------|
| [field] | [file/module] | [type + constraints] |

## Outputs

| Output | Destination | Schema |
|--------|-------------|--------|
| [field] | [file/column] | [type + constraints] |

## Invariants

[Hard rules this change must not violate. Reference SYSTEM_SPEC.md sections.]

1. [e.g., "Budget conservation: total allocated == bucket budget +/- $100"]
2. [e.g., "Deterministic: same input → same output across runs"]
3. ...

## Failure Modes

| Scenario | Expected behavior |
|----------|-------------------|
| [Missing data] | [Falls back to X / WARN / FAIL] |
| [Edge case] | [Handled by Y] |

## Validation Plan

### Tests (write BEFORE implementation)
- [ ] `test_[feature]_happy_path` — [what it proves]
- [ ] `test_[feature]_edge_case` — [what it proves]
- [ ] `test_[feature]_deterministic` — same inputs → same outputs
- [ ] `test_[feature]_budget_conservation` — (if portfolio-affecting)

### Evaluation (if signal/ranking change)
- [ ] IS metrics: [horizons, thresholds]
- [ ] OOS metrics: [horizons, thresholds]
- [ ] Paired t-stat >= 2.0
- [ ] Primary bar: +0.20pp at longest horizon
- [ ] Guardrail: no worse than -0.05pp at 84d

### Integration
- [ ] Full suite passes (11,200+ tests)
- [ ] No pre-commit hook failures
- [ ] Weekly summary renders correctly (if reporting change)

## Expected Effect Size

[Be honest about what you expect. "Structural improvement, no direct IC impact" is valid. "UNKNOWN — needs evaluation" is valid. Inflated claims are not.]

## Non-Goals

[Explicitly list what this change does NOT attempt. Prevents scope creep.]

---

## Implementation Log

### [Date] — [what was done]
- Files modified: ...
- Tests added: ...
- Commit: ...

---

*Template version: 1.0.0 — see specs/SYSTEM_SPEC.md for system invariants*
