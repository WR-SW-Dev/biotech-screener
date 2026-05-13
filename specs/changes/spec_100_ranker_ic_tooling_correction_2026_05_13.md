# Spec 100 — Ranker IC Tooling Correction

**Status**: SPEC ONLY (tooling/label clarity, no production scoring change)  
**Date**: 2026-05-13  
**Priority**: 1 (blocks interpretation of all future ranker IC claims)  
**Investment**: ~4–6 hours (audit tool output, update labels, add universe validation)

---

## Problem Statement

Spec 095 audit revealed that `run_rank_ic_backtest.py` measures `composite_score` / `composite_rank` IC, while production ranking uses `final_score` / `actionable_rank`. The two rankings are **effectively different** (0.25 correlation, 7/30 top-30 overlap).

**Consequence**: Any existing "ranker IC" claims may actually be measuring composite_score IC, not production ranker IC. This conflation blocks proper interpretation of ranker value.

Spec 100 defines the tooling fix and prevents future mislabeling.

---

## Investment Logic

- IC interpretation is foundational to ranker evaluation
- Conflated scope undermines credibility of any IC claims
- Fix is purely mechanical (labeling + scope filter)
- High-impact governance: prevents future mislabeling
- No algorithm changes or model retraining needed

---

## Exact Evidence & Analysis Needed

### 1. Identify Composite_Score Source

**Investigation**:
- Search `decision_engine.py` for composite_score / composite_rank construction
- Search `defensive_overlay_adapter.py` for overlay contributions
- Search `module_5_scoring_v3.py` for ranking output assignments
- Check snapshot metadata or schema docs

**Outcome**: Determine whether composite_score is:
- ❓ Old ranker version (pre-final_score)?
- ❓ Quality/confidence metric (not a ranking signal)?
- ❓ Decision-engine overlay artifact?
- ❓ Other output source?

**Impact**: If composite is a quality metric, deprecate from IC measurement. If old ranker, sunset entirely. If overlay, clarify relationship to final_score.

### 2. Audit Existing IC Output

**Inventory**:
- Check `output/rank_ic_backtest.json` (if exists)
- Search CLAUDE.md, memory files, reports for "ranker IC" claims
- Check documentation that cites IC values
- Identify any published IC numbers (e.g., "ranker IC = 0.12")

**Action**: Tag every composite IC claim with a **confidence marker**:
- `⚠️ COMPOSITE_SCORE_IC` (not production ranker IC)
- Include caveat: "This measures composite_score IC, not final_score ranker IC"

### 3. Define Correct Evaluation Scopes

**Scope A: Selector-Only IC**
- **Score field**: `selector_score` (percentile [0,1])
- **Universe**: Full eligible pre-ranker universe (~341 tickers, pre-gates)
- **Measure**: Spearman rank correlation of selector_score with forward_5d / forward_20d
- **Purpose**: Validates selector-only performance baseline

**Scope B: Ranker IC (True)**
- **Score field**: `final_score` (selector_score + ranker_adjustment)
- **Universe**: Ranker-eligible universe (~60 tickers post-coinvest/liquidity/runway gates)
- **Measure**: Spearman rank correlation of final_score with forward returns within eligible set
- **Purpose**: Measures production ranker IC on its operational universe

**Scope C: Actionable Portfolio Test**
- **Ranking field**: `actionable_rank` (top-30/top-60 post-gates)
- **Universe**: Actionable names (top-N eligible)
- **Measure**: Hit rate, median returns by rank cohort, drawdown
- **Purpose**: Tests portfolio-level performance of final output

**Scope D: Ranker Marginal Value (Spec 094)**
- **Method**: Compare (ranker top-30 names) to (selector-only top-30 names)
- **Universe**: Eligible candidates only
- **Measure**: (Forward returns of ranker-added) - (forward returns of ranker-removed)
- **Purpose**: Isolates ranker's incremental contribution

### 4. Tool Changes Required

**Current Tool** (`run_rank_ic_backtest.py`):
- ✗ Loads `composite_score` / `composite_rank`
- ✗ Filters to "investable universe" (forward-return data availability)
- ✗ Re-ranks within investable set
- ✗ Labels output as "ranker IC"

**Required Changes**:

| Change | Type | Detail |
|--------|------|--------|
| Add score-field parameter | Config | Allow `--score-field final_score` or `--score-field composite_score` |
| Add universe filter | Config | Allow `--universe eligible` or `--universe actionable` or `--universe all` |
| Add validation output | Logic | Report: row count, score/rank fields used, correlation sanity check |
| Add overlap check | Logic | Compute top-30 overlap vs production actionable_rank (should be >70%) |
| Update output labels | Schema | Add explicit `score_field`, `universe`, `row_count`, `snapshot_dates` to JSON output |
| Add deprecation warning | Logic | If composite_score mode: warn "⚠️ COMPOSITE_SCORE_IC, not production ranker IC" |

**Example output labels** (required):
```json
{
  "metadata": {
    "tool": "rank_ic_backtest.py",
    "snapshot_date": "2026-05-13",
    "score_field": "final_score",
    "universe": "eligible",
    "universe_size": 60,
    "rows_used": 45,
    "deprecation_warning": null
  },
  "ic": {
    "spearman": 0.123,
    "t_stat": 2.45,
    "p_value": 0.018
  }
}
```

### 5. Validation Checklist

Before Spec 100 implementation is approved:
- ✅ `composite_score` source confirmed (what is it?)
- ✅ Existing IC output relabeled or deprecated
- ✅ Tool updated to accept universe / score-field parameters
- ✅ Output schema includes explicit metadata (score field, universe, row count)
- ✅ Sanity check: Ranker IC universe ~60 rows, Selector IC universe ~341 rows
- ✅ Sanity check: Ranker top-30 overlap with production >70%
- ✅ No scoring artifact changes (only labeling/filtering)

---

## Data Constraints

- Pure tool/labeling work (no data collection)
- No new data sources
- No PIT changes or snapshot edits
- No production output modifications

---

## Out-of-Scope

- ❌ Change ranking algorithm (final_score production)
- ❌ Retrain ranker
- ❌ Promote or demote signals
- ❌ Backtest with corrected tool (that's future Spec 101+)
- ❌ Recompute all historical IC (just label future runs)

---

## Tests / Analysis Commands

```bash
# 1. Find composite_score source
grep -r "composite_score.*=" common/ module_*.py decision_engine.py --include="*.py" | grep -v "test" | head -20

# 2. Identify all existing IC output
find output/ artifacts/ -name "*ic*" -o -name "*rank*" | xargs grep -l "composite\|ranker" | head -10

# 3. Verify universe sizes
python3 << 'EOF'
import pandas as pd

# Current snapshot
df = pd.read_csv("data/snapshots/2026-05-13/rankings.csv")
eligible = (df['eligible'] == 1).sum()
top30 = (df['actionable_rank'] <= 30).sum()

print(f"Full universe: {len(df)}")
print(f"Eligible (post-gates): {eligible}")
print(f"Actionable (top-30): {top30}")
EOF

# 4. Check tool output
python3 run_rank_ic_backtest.py --help 2>&1 | grep -i "score\|universe\|field" | head -20
cat output/rank_ic_backtest.json | jq '.metadata' 2>/dev/null || echo "No metadata in current output"
```

---

## Pass/Fail Criteria

**PASS**:
- ✅ Composite_score source identified and documented
- ✅ All existing IC output labeled with score field and universe
- ✅ Tool supports `--score-field` and `--universe` parameters
- ✅ Output schema includes metadata (score_field, universe, row_count, dates)
- ✅ Ranker IC tool produces output from final_score on eligible universe (~60 rows)
- ✅ Validation checks run (universe sanity, overlap >70%)
- ✅ Deprecation warnings for composite_score mode

**FAIL**:
- ❌ Composite_score source remains unknown
- ❌ Existing output still labeled as "ranker IC" without caveat
- ❌ Tool output lacks explicit metadata
- ❌ Score field or universe not clearly stated in output

---

## Expected Outcome

After Spec 100 implementation:

1. **Composite IC is clearly labeled**: Any composite_score IC report says "COMPOSITE_SCORE_IC ⚠️ (not production ranker IC)"
2. **True ranker IC is measurable**: Tool can compute final_score IC within eligible universe
3. **Future claims are unambiguous**: All output explicitly states score field, universe, row count
4. **No scoring changes**: Production ranker output unchanged; only evaluation tool updated
5. **Governance**: All future ranker evaluations use labeled, scope-aware tool output

---

## Governance Note

**Do NOT use any prior IC evidence to justify ranker promotion or feature changes until Spec 100 is implemented or existing outputs are relabeled.**

This does not invalidate prior audits:
- Spec 093: Financial_score sign-direction verdict **STANDS** (INTENTIONAL_STRESS_UPSIDE)
- Spec 094: Ranker membership changes **STAND** (UNPROVEN but operationally real, 42.7% churn)
- Spec 095: Tool scope issue **STANDS** (composite ≠ ranker)

It clarifies them: The ranker is intentionally changing portfolio composition, but its return/IC value remains **unmeasured until Spec 100 is complete**.

---

## Timeline

- **2026-05-13**: Spec created
- **2026-05-20**: Investigation phase (composite_score source, existing output inventory)
- **2026-05-27**: Tool update phase (parameter support, metadata output)
- **2026-06-03**: Validation & approval phase
- **Post-approval**: Tool is safe to use for future ranker claims

---

## Rollback / No-Op Statement

Spec is pure tooling/labeling work (no algorithm or scoring changes). If implementation is deferred, mark existing IC output as "COMPOSITE_SCORE_IC ⚠️" manually and prohibit new ranker IC claims until tool is fixed.

---

## Related Specs

- **Depends on:** Specs 093–095 (investigation inputs)
- **Unblocks:** Future ranker promotion decisions (once IC tool is corrected)
- **Blocks current state**: Any ranker IC-based claims until relabeled

---

## Priority Note

**HIGH**: This spec is a blocker for proper interpretation of all future ranker IC claims. Do not proceed with ranker feature changes (Specs 098, 099, etc.) that rely on IC evidence until this tool is corrected or existing outputs are relabeled with appropriate caveats.
