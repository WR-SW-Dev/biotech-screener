# Change Spec: Deadline-Constrained Milestone Optionality Overlay

**Status**: DRAFT
**Author**: Claude / operator
**Date**: 2026-03-31
**Ruleset impact**: YES (candidate-only at first; requires promotion pipeline before any default-on use)

---

## Objective

Add a bounded, PIT-safe overlay that estimates **milestone success by deadline**
rather than eventual program success. The goal is to refine dev-side optionality
for names where value is dominated by high-impact, time-constrained clinical or
regulatory milestones, without replacing the ranking composite or introducing a
new classifier.

## PIT / Data Constraints

- [x] No lookahead — all milestone state, deadline state, safety flags, and
      program metadata must satisfy PIT rules as of snapshot date
- [x] Data source: existing program / catalyst / clinical fields in snapshots,
      plus deterministic derived milestone fields generated in research or
      production artifact code
- [ ] Historical availability: UNKNOWN — depends on milestone/deadline field
      backfill depth across historical snapshots
- [x] Known gaps: ambiguous deadlines, missing milestone sequencing, sparse
      support for some indication-specific milestone types, correlated multi-
      milestone programs

## Inputs

| Input | Source | Schema |
|-------|--------|--------|
| `clinical_optionality_pct_dev` | rankings / DEM outputs | float, 0-100 |
| `lead_program_phase` | rankings / M4 | normalized phase string |
| `catalyst_event_type` | rankings / event ledger | string enum / blank |
| `catalyst_days` | rankings / event ledger | int days / blank |
| milestone metadata | derived artifact | list/dict of milestone type, deadline, payout/importance proxy, indication, support |
| safety / execution flags | existing snapshot fields + derived overlay | bounded binary/ordinal flags |
| support metadata | derived artifact | n / confidence / fallback policy |

## Outputs

| Output | Destination | Schema |
|--------|-------------|--------|
| `milestone_deadline_mode` | rankings.csv / artifact | enum: `none`, `dated_event`, `fixed_deadline`, `inferred_window` |
| `milestone_count_active` | rankings.csv / artifact | int >= 0 |
| `milestone_primary_type` | rankings.csv / artifact | string |
| `milestone_primary_days_to_deadline` | rankings.csv / artifact | int / blank |
| `milestone_timeline_slack_days` | rankings.csv / artifact | int / blank |
| `milestone_timeline_feasible_flag` | rankings.csv / artifact | 0/1 |
| `milestone_safety_delay_flag` | rankings.csv / artifact | 0/1 |
| `milestone_corr_cluster_count` | rankings.csv / artifact | int >= 0 |
| `milestone_confidence_support` | rankings.csv / artifact | enum: `high`, `medium`, `low`, `fallback` |
| `milestone_pos_by_deadline_raw` | rankings.csv / artifact | float, 0-1 |
| `milestone_pos_by_deadline_shrunk` | rankings.csv / artifact | float, 0-1 |
| `milestone_value_weight` | rankings.csv / artifact | float, 0-1 |
| `milestone_timeline_weight` | rankings.csv / artifact | float, 0-1 |
| `milestone_corr_penalty` | rankings.csv / artifact | float, 0-1 |
| `milestone_deadline_ev_raw` | rankings.csv / artifact | float, 0-1 |
| `milestone_deadline_ev_pct` | rankings.csv / artifact | float, 0-100 |
| `milestone_deadline_overlay_z` | rankings.csv / artifact | float, bounded z |
| `clinical_optionality_deadline_overlay_pct` | rankings.csv / artifact | float, 0-100 |

## Invariants

1. **PIT-safe**: no milestone deadline, feasibility estimate, or safety haircut may
   use information unavailable on the snapshot date.
2. **Deterministic**: same inputs → identical overlay values, identical artifact,
   identical rankings impact.
3. **Bounded**: all probability-like fields remain in [0, 1]; all pct outputs remain
   in [0, 100]; all penalties and weights are clipped to documented ranges.
4. **Fail-closed on ambiguity**: unknown or weakly supported milestone/deadline
   inputs degrade to neutral or fallback values, never optimistic inference.
5. **No classifier creep**: this is an overlay on dev optionality, not a new
   multivariate predictor replacing DEM or M5.
6. **No naive double-counting**: multi-milestone programs must apply a correlation
   penalty before producing a program-level overlay.
7. **No direct default-on production effect**: Phase 1 is artifact-only; any DEM
   integration must clear evidence packet + promotion gates.
8. **Rollback-safe**: any later decision-engine use must be fully removable via
   candidate ruleset or feature disable path.

## Failure Modes

| Scenario | Expected behavior |
|----------|-------------------|
| No milestone data for a name | Overlay fields emit neutral / blank diagnostics; no rank impact |
| Milestone type known but no deadline | `milestone_deadline_mode=none`; timeline weight defaults neutral-to-conservative |
| Deadline exists but feasibility cannot be estimated | Apply fallback shrinkage + mark support `fallback` |
| Multiple highly correlated milestones on same program | Apply documented correlation penalty; do not sum raw EV directly |
| Safety signal ambiguous or absent | No haircut unless explicitly supported as-of-date |
| Contractual payout missing for non-CVR names | Use bounded milestone-importance proxy, not market-implied value |
| Sparse support for milestone type / indication | Shrink toward reference prior; surface low-confidence support |
| Derived artifact missing / unreadable | Hard fail in builder; fail-closed for production consumer |

## Formula / Translation Rules

### 1) Base milestone probability by deadline

Start from existing bounded clinical prior logic:

`p_base = PoS_prior(phase, endpoint_bucket, milestone_type, support_bucket)`

This is a prior input, not a standalone score replacement.

### 2) Timeline feasibility weight

Let:

- `slack_days = deadline_date - conservative_completion_date`
- `m = 0`
- `s = tuned scale parameter`

Then:

`timeline_weight = sigmoid((slack_days - m) / s)`

Operational behavior:
- negative slack → strong penalty
- near-zero slack → partial credit only
- ample positive slack → approaches 1.0

### 3) Safety / execution haircut

`risk_weight = 1 - safety_haircut - execution_haircut`

Bounded defaults:
- `safety_haircut ∈ [0.00, 0.25]`
- `execution_haircut ∈ [0.00, 0.20]`

If no explicit supported flag exists as-of-date, haircut defaults to 0.

### 4) Value / milestone-importance weight

For true contingent-value situations:
- use contractual payout normalized to total contingent package

For general dev names:
- approval milestone: `1.00`
- NDA/BLA filing: `0.80`
- phase 3 readout: `0.70`
- phase 2 readout: `0.50`
- earlier milestone: `0.25 - 0.40`

### 5) Correlation penalty

For `n_cluster` materially linked milestones on the same program:

`corr_penalty = 1 / (1 + alpha * (n_cluster - 1))`

`alpha` is tuned conservatively and clipped so correlation reduces but does not
zero-out valid multi-milestone programs.

### 6) Program-level expected-value overlay

For each milestone `i`:

`ev_i = p_base_i * timeline_weight_i * risk_weight_i * value_weight_i`

Program total:

`program_ev = corr_penalty * sum(ev_i)`

Final emitted overlay:

`clinical_optionality_deadline_overlay_pct = clip(100 * program_ev, 0, 100)`

### 7) Later DEM integration candidate

Phase 1: emit artifact only.

Phase 2/3 candidate path:
- blend existing dev optionality with deadline overlay rather than replacing it

`opt_dev_blend = (1 - beta) * clinical_optionality_pct_dev + beta * clinical_optionality_deadline_overlay_pct`

Where:
- `beta` is bounded and initially small
- blend is opt-in only
- no hard gate allowed on first integration pass

## Validation Plan

### Tests (write BEFORE implementation)
- [ ] `test_deadline_overlay_missing_inputs_neutral` — no milestone/deadline → neutral output
- [ ] `test_deadline_overlay_monotonic_more_slack_higher_weight` — more slack raises timeline weight
- [ ] `test_deadline_overlay_negative_slack_penalized` — infeasible timeline materially penalized
- [ ] `test_deadline_overlay_corr_penalty_monotonic` — more linked milestones lowers program EV
- [ ] `test_deadline_overlay_safety_flag_bounded` — safety haircut clipped and deterministic
- [ ] `test_deadline_overlay_contractual_weight_applied` — CVR-style payout weights respected
- [ ] `test_deadline_overlay_proxy_weight_applied` — non-contractual milestone type uses proxy weight
- [ ] `test_deadline_overlay_shrinkage_respects_support` — sparse support shrinks toward reference
- [ ] `test_deadline_overlay_deterministic` — same inputs → byte-identical artifact
- [ ] `test_deadline_overlay_fail_closed_on_bad_artifact` — unreadable/malformed artifact hard-fails
- [ ] `test_deadline_overlay_rank_impact_bounded_candidate` — candidate blend stays within documented replay bars

### Evaluation (if signal/ranking change)
Phase 1:
- [ ] Coverage audit: milestone overlay populated for meaningful share of dev names
- [ ] Bucket audit: coverage by `binary_now`, `build_window`, `less_binary`, `core`
- [ ] Redundancy audit: correlation vs `clinical_optionality_pct_dev`
- [ ] Dispersion audit: signal has non-trivial cross-sectional spread

Phase 2:
- [ ] Signal evidence packet run on candidate rerank vs active baseline
- [ ] Horizons: 20d / 63d / 84d (or repo-standard longest horizon if updated)
- [ ] Coverage >= 50%
- [ ] Primary bar: +0.20pp at longest evaluated horizon
- [ ] Guardrail: no worse than -0.05pp on any evaluated horizon
- [ ] Recommendation must be `PROMISING` or strong `NEEDS_MORE`, not `REJECT`

Phase 3:
- [ ] Opt-in replay compare on curated snapshot window
- [ ] Top-60 overlap >= 90% for each date
- [ ] Mean top-60 overlap >= 93% on aggregate compare
- [ ] Max rank shift <= 30
- [ ] Worst A-tier regression = 0
- [ ] Flagged dates = 0 before default-on consideration

### Integration
- [ ] Full suite passes
- [ ] No pre-commit hook failures
- [ ] Artifact schema version stamped and documented
- [ ] Candidate ruleset or feature toggle is rollback-safe
- [ ] Metadata / rankings output include overlay provenance if enabled

## Expected Effect Size

UNKNOWN — needs evaluation.

Best case: modest but real improvement in dev-name ordering where milestone value
is highly deadline-sensitive and the existing optionality signal is too coarse.
Worst case: highly intuitive but mostly redundant with current dev optionality,
yielding little portfolio-level lift after dilution across the full universe.

Expected near-term benefit is more likely **better dev tie-break ordering** and
cleaner milestone diagnostics than immediate large IC lift.

## Non-Goals

- Does not build a generic market-implied CVR pricer
- Does not use stock price to reverse-engineer contingent value
- Does not replace `clinical_optionality_pct_dev`
- Does not replace DEM sort anchor, composite ranking, or tiering logic
- Does not add a new unbounded classifier
- Does not change commercial archetype ranking behavior
- Does not become a hard eligibility gate in first implementation
- Does not bypass promotion / rollback governance

---

## Implementation Log

### 2026-03-31 — Draft spec
- Files modified: `specs/changes/041_deadline_milestone_optionality_overlay.md`
- Tests added: 0
- Commit: pending

### 2026-03-31 — Phase 1 implementation
- Feature builder: `common/milestone_optionality.py` (SCHEMA_VERSION: milestone_optionality.v1)
- Tests: `tests/test_milestone_optionality.py` (19 tests, all passing)
- Diagnostics: `scripts/research/run_milestone_diagnostics.py`
- Signal evidence: `scripts/research/eval_milestone_signal.py`
- Coverage: 244/294 tickers (83%), DEM top-30 100%, 13 hard deadlines, 231 dated events
- Phase 2 signal evidence: running

---

*Template version: 1.0.0 — see specs/SYSTEM_SPEC.md for system invariants*
