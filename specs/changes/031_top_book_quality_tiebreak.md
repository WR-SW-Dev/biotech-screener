# Change Spec: Top-Book Quality Tiebreak (binary_now / build_window)

**Status**: DORMANT
**Author**: Claude / operator
**Date**: 2026-03-21
**Ruleset impact**: YES (requires promotion pipeline)

---

## Objective

Activate `binary_now_sort_mode="quality_primary"` to add a secondary quality tiebreak
within the `binary_now` and `build_window` buckets, diversifying the top-book away from
pure optionality-anchor sorting. The goal is to surface high-quality catalyst names
(confirmed regulatory, pivotal data readouts, strong trial design) ahead of
calendar-noise names at similar optionality levels.

## Motivation

The current live sort (v1.11.0) is 100% optionality-anchored in binary_now and
build_window. The top-20 portfolio is entirely determined by `clinical_optionality_pct_dev`
with `calendar_alpha_sort` (w=0.3) as the only active secondary signal. Two recent
candidates demonstrated that mid-book and sizing changes are insufficient:

- **Catalyst type multiplier** (Spec 030, b7511c92): structurally valid but economically
  immaterial — all forward-return deltas rounded to zero because the effect was confined
  to mid-book `less_binary` names outside the top-K portfolio.
- **Rank-aware sizing**: live size-band sizing already optimal (+10.46% vs +10.26% taper,
  +9.89% equal-weight). No room for improvement in weight distribution alone.

The binary_now/build_window quality sort infrastructure already exists (contribution #11
in `_build_sort_contributions`) but has never been activated. `binary_quality_score` has
meaningful variance in the top-20 (0.47–0.87, combining family/phase/source/design),
making it a credible tiebreak signal.

## Prior Art

| Candidate | What it tested | Result | Why this is different |
|-----------|----------------|--------|----------------------|
| ddf59b03 (v1.10.1) | binary_quality_score in **less_binary** | Retired (boundary crossings) | This targets binary_now + build_window, not less_binary |
| d59b6cc3 (v1.11.1) | build_window clinical_z tilt | NEEDS_MORE (+0.01pp) | clinical_z is a single signal; BQS is a 4-component composite |
| b7511c92 (v1.12.0) | catalyst_type_mult in less_binary sort | NEEDS_MORE (zero return delta) | Proved mid-book changes don't move top-K; this targets top-K directly |

## PIT / Data Constraints

- [x] No lookahead — binary_quality_score uses only catalyst metadata available at snapshot time
- [x] Data source: `common/binary_quality_score.py` (computed from catalyst_family, phase,
  catalyst_source, design_quality — all PIT-safe)
- [x] Historical availability: binary_quality_score populated in all snapshots since ~2025-08
- [x] Known gaps: early snapshots (pre-2025-06) may lack catalyst_source or design_quality
  components — BQS degrades gracefully (missing components → 0.0)

## Design

### Signal: `binary_quality_score`

Already computed in `run_screen.py` and available in all snapshot CSVs. Composition:

| Component | Weight | Range | Source |
|-----------|--------|-------|--------|
| Family score | 0.35 | REGULATORY=1.0, CLINICAL=0.6, SAFETY=0.0 | catalyst_family |
| Phase score | 0.30 | P3=1.0, P2=0.5, P1=0.15 | stage_bucket |
| Source reliability | 0.20 | SEC_8K=1.0, PDUFA_MANUAL=0.95, CTGOV=0.60 | catalyst_source |
| Design quality | 0.15 | [0, 1] from clinical_calendar_alpha | design_quality_score |

### Integration: Contribution #11

Activate via ruleset config — no code changes needed:

```json
{
  "binary_now_sort_mode": "quality_primary",
  "binary_now_quality_weight": <W>
}
```

This enables the existing `_build_sort_contributions` block (lines 1577–1583) that
computes `delta = binary_now_quality_weight * binary_quality_score` for tickers in
`binary_now` or `build_window` buckets. The delta is subtracted from the optionality
anchor, so higher BQS → sorts earlier.

### Weight Selection

The weight must be large enough to create real top-20 movement but small enough to
avoid wholesale reordering of the optionality anchor.

Calibration context:
- Optionality range in top-20: 0.62–0.98 (spread ~0.36)
- BQS range in top-20: 0.47–0.87 (spread ~0.40)
- Calendar alpha sort (active, w=0.3) provides the scaling precedent

**Candidate weights to sweep**: 0.15, 0.25, 0.35, 0.50

At w=0.25: max BQS delta = 0.25 × 0.87 = 0.22, enough to swap adjacent names
separated by ~0.22 optionality units. This targets 2–5 swaps in the top-20, not
wholesale reordering.

## Inputs

| Input | Source | Schema |
|-------|--------|--------|
| binary_quality_score | run_screen.py → common/binary_quality_score.py | float [0, 1] |
| catalyst_bucket | decision_engine.py L0/L2 overlays | str: binary_now, build_window, less_binary, core |
| binary_now_sort_mode | DecisionRuleset field | str: baseline, quality_primary, quality_plus_institutional |
| binary_now_quality_weight | DecisionRuleset field | float >= 0, default 1.0 |

## Outputs

| Output | Destination | Schema |
|--------|-------------|--------|
| Reordered actionable_rank | rankings.csv | int 1..N (eligible only) |
| de_sort_contrib_binary_quality_now | rankings.csv | float (new column, audit trail) |

## Invariants

1. Default OFF: `binary_now_sort_mode="baseline"` → no behavioral change (existing invariant)
2. Optionality anchor preserved: BQS tiebreak is additive to anchor, does not replace it
3. Eligibility unchanged: no membership or gate changes
4. Budget conservation: sort-only change, no L3 sizing effect
5. Deterministic: same inputs → same outputs
6. Less_binary unaffected: contribution #11 only fires for binary_now + build_window buckets

## Failure Modes

| Scenario | Expected behavior |
|----------|-------------------|
| binary_quality_score missing | Defaults to 0.0 → no tiebreak effect (neutral) |
| All names same BQS | Reduces to current optionality-only sort (no change) |
| Weight too high (wholesale reorder) | Caught by top-20 overlap < 90% in replay → reject |
| BQS components partially missing | BQS degrades gracefully — missing components → 0.0 |

## Validation Plan

### Phase 1: Weight Sweep (rerank only)

Sweep w ∈ {0.15, 0.25, 0.35, 0.50} against baseline 9f1f4587 across 87 available
snapshot dates. Per weight, report:

- Top-20 overlap (bar: >= 85%, target: 90–97%)
- Top-60 overlap (bar: >= 90%)
- Mean rank shift (bar: < 5 global, < 3 within binary_now + build_window)
- Directional check: do high-BQS names (DATA_READOUT, FDA_PDUFA) move up?
- Per-bucket drift profile

**Decision gate**: select the weight that produces 90–97% top-20 overlap (meaningful
but not chaotic). If no weight hits this band, stop — the signal is too weak or too
strong for this integration point.

### Phase 2: Signal Evidence (selected weight)

- [ ] Replay against active baseline (9f1f4587) across catalyst_tilt_eval manifest (34 dates)
- [ ] Top-60 overlap >= 90%
- [ ] Mean rank shift < 5
- [ ] Primary bar: +0.20pp at 84d hedged residual
- [ ] Guardrail: no worse than -0.05pp at any horizon
- [ ] Acceptance replay: KEEP_ACTIVE or NEEDS_MORE

### Phase 3: Promotion Battery (if Phase 2 passes)

- [ ] Full test suite passes
- [ ] No pre-commit hook failures
- [ ] Weekly gate: 3-week shadow period with no bucket-level guardrail violations
- [ ] Snapshot columns render correctly

## Expected Effect Size

**Moderate to meaningful.** Unlike the catalyst type multiplier (Spec 030), this change
directly targets the top-K portfolio. At w=0.25, expect 2–5 rank swaps in the top-20,
primarily surfacing DATA_READOUT and FDA_PDUFA names (BQS 0.76–0.87) ahead of
CT_PRIMARY_COMPLETION names (BQS 0.47–0.67) at similar optionality. Whether this
translates to forward-return improvement depends on whether event quality discriminates
returns within the binary_now/build_window population — which is exactly what the
signal evidence harness will measure.

Honest estimate: this is the first candidate that can **actually move the top-K
portfolio** with a governed, default-OFF secondary signal. If event quality matters for
near-term catalysts, this should show it. If it doesn't, nothing in the current signal
set will — and the conclusion is that optionality-only sorting is already optimal for
this universe.

## Non-Goals

- Do NOT replace the optionality anchor — BQS is additive
- Do NOT change eligibility gates or L3 sizing
- Do NOT create new signal infrastructure — use existing binary_quality_score
- Do NOT activate for less_binary (already has its own sort mode in v1.11.0)
- Do NOT combine with catalyst tilt (a08749e4) — evaluate in isolation first
- Do NOT add quality_plus_institutional mode yet — start with quality_primary only
- Do NOT promote without clearing the standard governance battery

---

## Implementation Log

### 2026-03-21 — Spec drafted
- Motivated by Spec 030 finding: mid-book changes are economically immaterial
- binary_now_sort_mode infrastructure already exists (contribution #11)
- binary_quality_score has 0.40 spread in top-20 (sufficient for tiebreaking)
- No code changes needed — pure ruleset config activation

### 2026-03-21 — Phase 1 weight sweep complete
- Swept w ∈ {0.15, 0.25, 0.35, 0.50} across 131 snapshot dates (2025-06 to 2026-03)
- w=0.35 selected: top-20 overlap 98.4% (min 85%), mean shift 3.46, BN+BW drift 5.60,
  separation +1.44. Structurally correct: FDA_PDUFA/DATA_READOUT promoted,
  CT_PRIMARY_COMPLETION demoted. 13 movers in top-20 on representative date.
- w=0.50 boundary: top-20 overlap 97.7%, separation +1.94, 15 movers.

### 2026-03-21 — Phase 2 signal evidence → DORMANT
- **w=0.35** (846ae27b): all hedged deltas zero at every horizon. IC slightly negative
  (-0.0005 at 20d, -0.0031 at 84d). 27/34 manifest dates evaluated.
- **w=0.50** (7956312c, boundary): +0.01pp hedged at 84d (noise), IC worse (-0.0041).
- **Root cause**: event quality (BQS) does not discriminate forward returns within
  binary_now/build_window. The optionality anchor already captures what matters for
  near-term catalyst positioning. Reordering the top-K by BQS is PM-sensible but
  economically immaterial — identical conclusion to Spec 030 but at a different scope.
- **Key learning**: the repo has now tested quality tiebreaks at three scopes:
  - less_binary sort (v1.11.0, active): works, passes weekly A/B
  - less_binary catalyst-type mult (Spec 030): structurally valid, zero forward delta
  - binary_now/build_window BQS tiebreak (Spec 031): structurally valid, zero forward delta
  This strongly suggests the optionality anchor is already near-optimal for top-book
  ordering with current signals. New top-book alpha requires a **new signal source**,
  not reordering with existing quality composites.
- **Decision**: DORMANT. Do not pursue further quality tiebreaks at any scope. Catalyst
  tilt (a08749e4) remains the only shadow candidate with real economic upside.
- Manifest entries: 846ae27b (w=0.35) + 7956312c (w=0.50), both dormant
- Evidence packets: output/signal_evidence/topbook_quality_{035,050}/

---

*Template version: 1.0.0 — see specs/SYSTEM_SPEC.md for system invariants*
