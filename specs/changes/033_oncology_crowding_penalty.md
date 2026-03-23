# Change Spec: Oncology-Specific Crowding Penalty

**Status**: NEEDS_MORE (shadow)
**Author**: Claude / operator
**Date**: 2026-03-21
**Ruleset impact**: YES (requires promotion pipeline, if signal confirms)

---

## Objective

Add an oncology-specific crowding penalty to the sort key, penalizing oncology names in
crowded indications relative to uncrowded oncology names. The goal is to exploit the
finding that competitive intensity is **non-monotonic across therapeutic areas** but
**consistently negative within oncology** — the one therapeutic area that dominates the
universe (39% of eligible names).

## Motivation

### The finding (2026-03-21 session)

Cross-universe competitive_intensity_z was tested and found confounded:
- 63d IC = +0.053 (t=3.45) — looks significant but misleading
- U-shaped category returns: uncrowded (+26pp) AND highly_crowded (+28pp) outperform
- Quintile spread -9.83pp (crowded underperforms uncrowded)

Within-indication split revealed the signal is **real in oncology, reversed elsewhere**:
- **Oncology-only**: 63d IC = -0.055, t = -2.76, pos/neg = 10/21 (crowding HURTS)
- **Non-oncology**: 63d IC = +0.066, t = +3.49, pos/neg = 24/7 (crowding = validation)
- **Oncology uncrowded vs crowded**: +5.35pp at 63d, positive 20/31 dates

### Why oncology is different

Oncology has the most competitors per indication in biotech. Unlike rare disease or
CNS where "crowded" means the indication has been validated (positive signal), in
oncology "crowded" means too many companies chasing the same indications with similar
mechanisms — a genuine competitive disadvantage.

### Why this is orthogonal to optionality

Clinical optionality measures internal pipeline breadth. Competitive intensity measures
external market structure. A company can have high optionality (many shots on goal) but
be in a crowded oncology indication (many competitors with similar shots). The two axes
are weakly correlated at best.

## Prior Art

| Signal | Scope | IC (63d) | t-stat | Verdict |
|--------|-------|----------|--------|---------|
| competitive_intensity_z (cross-universe) | All | +0.053 | +3.45 | Confounded (U-shaped) |
| competitive_intensity_z (oncology only) | Oncology | **-0.055** | **-2.76** | Real signal |
| competitive_intensity_z (non-oncology) | Non-onc | +0.066 | +3.49 | Opposite direction |
| Quality tiebreaks (Specs 030, 031) | Various | ~0 | <1 | No signal |
| PI trial count (Spec 032) | All | -0.006 | -1.11 | No signal |

## PIT / Data Constraints

- [x] No lookahead — competitive intensity is computed from current CT.gov trial data,
  which is PIT-safe via the existing trial_records pipeline
- [x] Data source: `CompetitiveIntensityEngine` (already live in run_screen.py)
- [x] Historical availability: competitive_intensity_z populated in snapshots since ~2025-08
- [x] Known gaps: `therapeutic_area` classification may have edge cases; 14/190 eligible
  names have empty therapeutic_area

## Design

### Signal: oncology-gated crowding penalty

Binary or continuous penalty applied only to names where `therapeutic_area == "oncology"`.

**Option A: Binary penalty (simpler)**
```
if therapeutic_area == "oncology" and crowding_level in ("crowded", "highly_crowded"):
    penalty = -oncology_crowding_weight
else:
    penalty = 0
```

**Option B: Continuous penalty (uses more signal)**
```
if therapeutic_area == "oncology":
    penalty = -oncology_crowding_weight * competitive_intensity_z
else:
    penalty = 0
```

Option B is preferred because it uses the full crowding gradient, not just a binary cut.
But the evaluation should test both.

### Integration: new sort contribution (#14)

Add to `_build_sort_contributions()` as a new contribution gated on
`therapeutic_area == "oncology"`:

```python
# 14. Oncology crowding penalty (Spec 033)
if ruleset.enable_oncology_crowding_penalty:
    ta = str(decision_fields.get("therapeutic_area", ""))
    if ta == "oncology":
        ci_z = _safe_float(decision_fields.get("competitive_intensity_z"), default=0.0)
        delta = -ruleset.oncology_crowding_weight * ci_z  # negative: crowded → sorts later
        contribs.append(SortContribution("oncology_crowding", ci_z, ruleset.oncology_crowding_weight, delta))
```

### Ruleset fields

```python
enable_oncology_crowding_penalty: bool = False  # default OFF
oncology_crowding_weight: float = 0.3  # calibrate via sweep
```

### Why only oncology

The within-indication IC analysis showed crowding has **opposite effects** by therapeutic
area. Applying the penalty cross-universe would hurt non-oncology names where crowding
is actually a positive signal. The oncology gate ensures the penalty only fires where
the evidence supports it.

## Inputs

| Input | Source | Schema |
|-------|--------|--------|
| competitive_intensity_z | run_screen.py → CompetitiveIntensityEngine | float, z-scored |
| therapeutic_area | run_screen.py → Module 5 | str: oncology, cns, autoimmune, etc. |
| crowding_level | CompetitiveIntensityEngine | enum: uncrowded, moderate, crowded, highly_crowded |

## Outputs

| Output | Destination | Schema |
|--------|-------------|--------|
| de_sort_contrib_oncology_crowding | rankings.csv | float (new column) |
| Reordered actionable_rank | rankings.csv | int |

## Invariants

1. Default OFF: `enable_oncology_crowding_penalty=False` → no behavioral change
2. Non-oncology names unaffected: penalty only fires when therapeutic_area == "oncology"
3. Optionality anchor preserved: crowding penalty is additive, does not replace anchor
4. Eligibility unchanged: no gate changes
5. Budget conservation: sort-only change, no L3 sizing effect
6. Deterministic: same inputs → same outputs

## Failure Modes

| Scenario | Expected behavior |
|----------|-------------------|
| therapeutic_area missing/empty | No penalty (gate fails) |
| competitive_intensity_z missing | No penalty (default 0.0) |
| All oncology names same crowding | Reduces to no effect (uniform penalty = no rerank) |
| Non-oncology names | Completely unaffected |

## Validation Plan

### Phase 1: Weight sweep (rerank only)

Sweep oncology_crowding_weight in {0.15, 0.25, 0.35, 0.50}:
- Top-20/60 overlap vs baseline
- Mean rank shift (global and within oncology)
- Verify non-oncology names are unaffected
- Check that uncrowded oncology names move up, crowded move down

### Phase 2: Signal evidence

- Replay across catalyst_tilt_eval manifest (34 dates)
- Primary bar: +0.20pp at 84d hedged
- Guardrail: no worse than -0.05pp at any horizon
- Acceptance replay

### Phase 3: Interaction test

- Correlation with optionality signal (redundancy check)
- Does oncology crowding add information beyond what optionality already captures?
- Conditional IC: oncology crowding IC within high-optionality vs low-optionality subsets

## Expected Effect Size

**Small to moderate.** Oncology is 39% of the eligible universe (~75 names), so the penalty
can affect top-K composition. The uncrowded-vs-crowded spread of +5.35pp at 63d is
economically meaningful. But the signal concentrates in the 14-20 "uncrowded" oncology
names, so the top-K impact depends on how many of those are near the top-20 boundary.

Unlike the quality tiebreak specs (030, 031) which failed because they targeted signals
correlated with the existing anchor, this signal is genuinely orthogonal — competitive
position is not captured by clinical optionality.

Honest estimate: this is the best candidate since catalyst tilt for creating real
portfolio-level impact, but the effect size is uncertain because the initial IC was
measured on a limited eval window.

## Non-Goals

- Do NOT apply to non-oncology therapeutic areas (signal is opposite there)
- Do NOT replace optionality anchor
- Do NOT change eligibility gates or L3 sizing
- Do NOT integrate competitive intensity as a cross-universe signal
- Do NOT promote without clearing standard governance battery

---

## Implementation Log

### 2026-03-21 — Phase 1 weight sweep
- 63 dates with data, w={0.15, 0.25, 0.35, 0.50}
- w=0.25 selected: top-20 overlap 93.9% (meaningful), mean shift 3.52, 14.8 onc up, 43 onc down
- Directionally correct: uncrowded oncology up, crowded down, non-oncology cascade only

### 2026-03-21 — Phase 2 signal evidence → NEEDS_MORE
- **w=0.25** (6e91fb7a): 27/34 dates evaluated
- 84d hedged: +0.020pp (below +0.20pp bar)
- All deltas positive (IC, hedged, net, turnover), but magnitudes small
- Better than Specs 030/031 (which were zero), but 10x below promotion threshold
- Root cause: oncology is 39% of universe, and only a fraction of those are near the
  top-K boundary. The within-oncology IC (-0.055) is real but diluted at portfolio level.
- **Decision**: NEEDS_MORE. Signal is directionally correct and economically positive,
  but too small to clear the promotion bar on 27 eval dates. Revisit if:
  - More eval dates accumulate (longer history)
  - Oncology fraction of top-K increases
  - Combined with other orthogonal signals
- Manifest entry: 6e91fb7a, status=shadow

### 2026-03-21 — Spec drafted
- Motivated by within-indication IC finding: oncology IC=-0.055 (t=-2.76)
- Cross-universe signal confounded (U-shaped); oncology-specific is clean
- CompetitiveIntensityEngine already live, competitive_intensity_z in snapshots
- therapeutic_area column available in rankings.csv
- Next step: Phase 1 weight sweep

---

*Template version: 1.0.0 — see specs/SYSTEM_SPEC.md for system invariants*
