# Change Spec: Top-Level Options Anchor Shadow Candidate

**Status**: IN_PROGRESS
**Author**: dschulz
**Date**: 2026-03-30
**Ruleset impact**: YES (new candidate ruleset, shadow-only — NOT promoted)
**Type**: Research / shadow candidate

---

## Objective

Build a hybrid top-level options anchor that uses `options_quality_composite`
when present and falls back to `optionality_pct` when absent. Evaluate as a
shadow-only candidate with the same 4-gate governance shape already used by
the live policy candidate.

## Why Hybrid

The current options-quality path is narrow and gated:
- `options_quality_91_180` only fires when `has_regulatory_upcoming_180d=1`
- `regulatory_days` must be in 91-180 window
- Prior candidate `1ecddc8c` was demoted: 0 REGULATORY+less_binary rows in 408 snapshots
- A pure options-only anchor would be too brittle today

## Sort Anchor Enum

```python
sort_anchor in {"optionality_pct", "score_z", "options_anchor_hybrid"}
```

### Behavior

```python
if options_quality_composite is present and valid:
    anchor = -options_quality_composite  # higher → sorts first
else:
    anchor = fallback (optionality_pct or comp_rank)

# Bounded modifiers
if has_regulatory_upcoming_180d and 91 < reg_days <= 180:
    anchor *= regulatory_boost (1.10)
if catalyst_days <= 30:
    anchor *= near_catalyst_boost (1.05)
```

Missing data always falls back — never drops names.

## Ruleset Fields

```json
{
  "sort_anchor": "options_anchor_hybrid",
  "options_anchor_regulatory_boost": 1.10,
  "options_anchor_near_catalyst_boost": 1.05,
  "binary_91_180_sort_mode": "clinical_plus_options",
  "binary_91_180_options_quality_weight": 0.5,
  "enable_options_verdict_tilt": true,
  "options_verdict_weight": 0.3
}
```

## Governance Thresholds

- Cumulative hedged delta: >= +0.20pp
- Mean weekly hedged delta: >= -0.05pp
- Turnover delta: <= +0.25pp
- Mean overlap: >= 80%
- Minimum overlap: >= 70%
- Coverage audit: meaningful share of rows must use options_quality_composite

## Implementation Order

1. Add `sort_anchor="options_anchor_hybrid"` to decision engine
2. Implement deterministic fallback behavior
3. Create candidate ruleset JSON
4. Add to manifest as shadow candidate
5. Wire daily shadow accumulation (post-April)

## Non-Goals

- No promotion to active ruleset
- No change to bucket definitions
- No interference with policy candidate (Spec 035)
- No change to options monitoring stack
