# Change Spec: FDA Designation PoS Multiplier Correction

**Status**: IMPLEMENTED
**Author**: Claude / operator
**Date**: 2026-03-21
**Ruleset impact**: NO (Module 5 scoring change, not decision engine sort)

---

## Objective

Neutralize the `pos_multiplier` applied to PoS scores for FDA-designated names in
Module 5 scoring. The current multiplier (1.12x–1.34x) boosts PoS for names with
BTD/FT/ODD/RMAT/PR designations, but empirical testing shows designations are a
**negative return signal** in this universe (IC=-0.035 at 63d, t=-5.14, -9.53pp spread).

## Motivation

### The finding (2026-03-21 audit)

The FDA designation file was restored from a git regression (135→20 entries) to 149
entries across 53 tickers (45 in universe, 13.2% coverage). IC testing on the restored
data revealed:

| Test | 20d | 63d |
|------|-----|-----|
| Binary IC (has_designation) | -0.023 (t=-2.96) | **-0.035 (t=-5.14)** |
| Continuous IC (score) | -0.071 | **-0.228** |
| Spread (designated vs not) | -3.25pp | **-9.53pp** |
| Sign consistency | 10/24 pos | **5/26 pos** |

### Why the current multiplier is wrong

The pos_multiplier was designed on the reasonable assumption that FDA designations
(BTD, ODD, FT) indicate higher approval probability, which should increase PoS.
However:

1. **Designations are already priced in** — the announcement itself is a public catalyst.
   By the time the screener sees the designation, the market has already adjusted.
2. **Designated names in small-cap biotech tend to be earlier-stage** with higher
   uncertainty and commercially difficult indications.
3. **The multiplier amplifies a negative signal** — it boosts PoS for names that
   systematically underperform, pushing them higher in composite scoring.

### Where it applies

The multiplier is applied in two places:
1. `module_5_composite_v3.py` line 717-721: `pos_score *= fda_multiplier`
2. `module_5_scoring_v3.py` line 2930-2933: `pos_raw *= fda_pos_multiplier`

Both apply before cohort normalization, meaning the boost propagates into final
composite scores.

## Design

### Change: set pos_multiplier to 1.0 for all designations

The simplest correct fix is to neutralize the multiplier without removing the engine:

```python
# module_5_composite_v3.py line 717-721
# BEFORE:
if pos_score is not None and fda:
    fda_multiplier = _to_decimal(fda.get("pos_multiplier"))
    if fda_multiplier and fda_multiplier > Decimal("1.0"):
        pos_score = (pos_score * fda_multiplier).quantize(Decimal("0.01"))

# AFTER:
# FDA designation pos_multiplier DISABLED (Spec 034).
# Designations are a negative return signal in this universe.
# Multiplier neutralized; designation data preserved for attribution.
```

The same neutralization in `module_5_scoring_v3.py`.

### What stays

- `FDADesignationEngine` continues to compute scores (for attribution/diagnostics)
- `fda_designation_signal` still emitted in output (has_designations, designation_types, etc.)
- `fda_designations.json` stays loaded (data is valid, the multiplier application was wrong)

### What changes

- `pos_multiplier` no longer applied to PoS in Module 5 scoring
- No composite score impact from designations (neutral pass-through)

## Invariants

1. Designation data preserved for attribution (no data deletion)
2. fda_designation_signal still emitted in output
3. No sort-order or decision engine changes
4. No eligibility changes
5. Deterministic

## Validation Plan

- [ ] Verify pos_score is unchanged before/after for names WITHOUT designations
- [ ] Verify pos_score is no longer boosted for names WITH designations
- [ ] Run one snapshot end-to-end and confirm fda_designation_signal still populates
- [ ] Compare composite scores: designated names should rank slightly lower than before
- [ ] No test suite regressions

## Expected Effect Size

Small but directionally correct. Only 45/341 universe names (13.2%) are affected, and
the multiplier was 1.12x–1.34x on PoS scores that are one of several composite inputs.
The change removes a wrong-sign boost rather than adding a new signal.

## Non-Goals

- Do NOT reverse the multiplier (make designations a penalty) — that needs more evidence
- Do NOT remove the FDADesignationEngine — keep for attribution
- Do NOT combine with oncology crowding (Spec 033) — separate experiments
- Do NOT change designation data collection — the data is correct, the application was wrong

---

## Implementation Log

### 2026-03-21 — Spec drafted and implemented
- FDA designation audit found designations are negative return signal (IC=-0.035, t=-5.14)
- pos_multiplier (1.12-1.34x) is directionally wrong
- Corrective spec: neutralize multiplier, keep data for attribution
- Separate from oncology crowding (Spec 033) to avoid confounding

### 2026-03-21 — Implementation
- `module_5_composite_v3.py` line 715-721: pos_multiplier application removed
- `module_5_scoring_v3.py` line 2927-2933: pos_multiplier application removed
- Both locations: pos_raw_unadjusted preserved for output compatibility
- fda_designation_signal still emitted (has_designations, types, score)
- FDADesignationEngine still runs (attribution/diagnostics)
- Modules import cleanly

---

*Template version: 1.0.0 — see specs/SYSTEM_SPEC.md for system invariants*
