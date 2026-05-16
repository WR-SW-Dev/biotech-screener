# Spec 100 Investigation Memo (2026-05-16)

**Status**: INVESTIGATION COMPLETE  
**Findings**: Root cause identified and mapped  
**Next phase**: Tool implementation (2026-05-20+)

---

## Root Cause Confirmed

### The Problem: "composite_score" is Misnamed

**Module 5 scoring pipeline** (`module_5_scoring_v3.py`, line 4371):
```python
"composite_score": str(final_score),  # ← This is the selector score, not composite
```

Module 5 computes a `final_score` internally (selector-only output after clinical gates), but **exports it as `"composite_score"` in rankings.csv**. This field is the Module 5 selector score *before* ranker adjustments.

### What the Rankings CSV Actually Contains

| Field | What it Is | Rank | Purpose |
|-------|-----------|------|---------|
| `composite_score` | Module 5 selector output (pre-ranker) | `composite_rank` | Selector-only baseline |
| `selector_score` | Redundant copy of above | (no explicit rank) | Clarity field for ranker input |
| `final_score` | Selector + ranker adjustment | (none) | Production ranker output |
| `actionable_rank` | Final top-30 rank post-gates | (none) | **Production decision ranking** |
| `ranker_adjustment` | Bounded adjustment applied | (none) | Magnitude of ranker contribution |

### The IC Tooling Bug

The `run_rank_ic_backtest.py` tool loads `composite_score` and `composite_rank` (lines 1054, 1199, etc.), measuring **selector-only IC**, not ranker IC:

```python
rank_str = row.get("composite_rank", "").strip()
score_str = row.get("composite_score", "").strip()
# Measure forward returns against composite_rank / composite_score
```

**This measures**: How well Module 5's selector alone predicts returns  
**It does NOT measure**: How much the ranker improves (or degrades) those predictions

### Scope Comparison (from Spec 095 audit)

| Scope | Field(s) | Universe | N | Use |
|-------|---------|----------|---|-----|
| **Composite (current tool)** | composite_score / composite_rank | Full 341 (with forward return data) | ~120 | Selector-only baseline |
| **Ranker (unmeasured)** | final_score / actionable_rank | Post-eligible-gates (~60) | ~40 | **PRODUCTION ranker** |
| **Portfolio** | actionable_rank | Top-30 actionable | ~30 | Portfolio-level performance |

The current tool re-ranks the investable universe, but still uses the selector-only score field, not the production ranker output.

---

## Fields in Current Snapshot (2026-05-15)

From `data/snapshots/2026-05-15/rankings.csv` column headers:

- **Column 284**: `composite_rank` ← Ranking of composite_score (selector-only)
- **Column 285**: `composite_score` ← Module 5 selector output (misnamed)
- **Column 309**: `selector_score` ← Explicit selector input to ranker
- **Column 317**: `ranker_adjustment` ← Bounded ranker contribution
- **Column 318**: `final_score` ← Selector + ranker adjustment (production)
- **Column 3**: `actionable_rank` ← Final ranking used for portfolio construction

All fields are present and populated correctly; only the labeling/interpretation is wrong.

---

## Invalidated Claims

Any IC measurement labeled "ranker IC" or "ranker contributes X" that cite `run_rank_ic_backtest.py` output or historical IC values is **COMPOSITE_SCORE_IC**, not true ranker IC.

**Example**:
- Claim: "Ranker IC +0.089 t=2.07" (pre-PIT-v2 backtest)
- Reality: "Composite_score IC +0.089" (selector-only, not ranker)
- Ranker true IC: **UNMEASURED**

---

## Implementation Plan (Spec 100)

### Phase 1: Tool Refactoring

1. **Add score-field parameter** to `run_rank_ic_backtest.py`
   - `--score-field composite_score` → selector-only IC (current behavior, relabeled)
   - `--score-field final_score` → production ranker IC (new measurement)

2. **Add universe parameter**
   - `--universe all` → investable universe (full forward-return data)
   - `--universe eligible` → post-gate universe (~60 tickers)
   - `--universe actionable` → top-30 post-gates

3. **Update output metadata** (JSON schema)
   - `score_field`: which score was measured
   - `universe`: universe size and name
   - `row_count`: actual rows used
   - `deprecation_warning`: if composite_score mode, warn it's not production ranker

4. **Add validation checks**
   - Sanity check: Ranker IC universe ~60 rows, Selector IC ~341 rows
   - Overlap check: Compare top-30 with production actionable_rank (should be >70%)
   - Correlation check: final_score vs composite_score (should be low when ranker active)

### Phase 2: Validation & Calibration

1. Run both scopes on historical snapshots (7 quarterly 2023-Q3 2024)
   - Selector IC = baseline (composite_score, ~120 rows)
   - Ranker IC = production (final_score, ~40 rows)

2. Compare overlap & correlation

3. Document findings for Spec 101+ (future ranker re-evaluation)

### Phase 3: Governance Clarification

1. Mark all existing IC output with caveat: "⚠️ COMPOSITE_SCORE_IC (not production ranker)"
2. Document scope in Spec 100 final memo
3. Lift IC evidence hold once tool is verified

---

## No Changes Required To

- Production scoring algorithm (Module 5, ranker, defensive overlay)
- Rankings.csv schema (all fields already present)
- Snapshot data (all measurements are present and correct)
- Historical backtest results (just relabeled as composite_score IC)

---

## Timeline

- **2026-05-16**: Investigation complete (this memo)
- **2026-05-20**: Phase 1 tool implementation (estimated 4-6 hours)
- **2026-05-27**: Phase 2 validation (estimated 2-3 hours)
- **2026-06-03**: Governance sign-off

**Blocking removal**: Once Spec 100 is complete, h20d checkpoint (2026-05-26) can be cleared for architecture freeze lift and Phase 23 / KG sprint continuation.

---

## Related Docs

- Spec 095 (IC Scope Gap audit) — Source of discovery
- Spec 100 (Tool remediation) — Implementation details
- governance_ic_evidence_hold_2026_05_13 — Temporary hold enforced until this is done
- spec_095_ic_scope_gap_critical — Memory record of critical finding
