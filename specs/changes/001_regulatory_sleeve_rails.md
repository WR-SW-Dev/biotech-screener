# Change Spec: Regulatory Sleeve Construction Rails

**Status**: IMPLEMENTED
**Author**: arrenchulz
**Date**: 2026-03-08 through 2026-03-09
**Ruleset impact**: NO (portfolio policy, not ranking ruleset)

---

## Objective

Add structured portfolio construction rails for regulatory-catalyst positions: family-targeted allocation, time-ladder sub-buckets, quality-proportional weighting, and auto-resolution of past-event names. Goal: concentrate regulatory exposure in the regulatory sweet spot (15-90 days pre-event) while limiting near-term gap risk.

## PIT / Data Constraints

- [x] No lookahead — regulatory_days computed from snapshot as_of_date
- Data source: `pdufa_dates.json` (PDUFA manual), `run_screen.py` enrichment via event ledger
- Historical availability: PDUFA manual has 11 current entries; event ledger covers 2025+
- Known gaps: Reranked snapshots lack `has_regulatory_upcoming_180d` (enriched at runtime only)

## Inputs

| Input | Source | Schema |
|-------|--------|--------|
| has_regulatory_upcoming_180d | rankings.csv (runtime) | "0" or "1" |
| regulatory_days | rankings.csv (runtime) | str(int), "" if none |
| regulatory_quality | rankings.csv (runtime) | str(float) 0.0-1.0 |
| regulatory_event_type | rankings.csv (runtime) | "PDUFA", "FDA_ADCOM", etc. |
| portfolio_policy.json | production_data/ | schema portfolio_policy.v3 |

## Outputs

| Output | Destination | Schema |
|--------|-------------|--------|
| positions[].reg_sub_bucket | positions JSON | "reg_0_14" / "reg_15_45" / "reg_46_90" / "reg_91_180" / "" |
| positions[].effective_family | positions JSON | "REGULATORY" / "CLINICAL" / "" |
| summary.resolved_regulatory | positions JSON | [{ticker, regulatory_event_type, regulatory_days}] |
| Regulatory Sleeve section | weekly_summary.md | Markdown table |
| Regulatory Ladder section | weekly_summary.md | Markdown table with Min Q / Max Q |
| Resolved Regulatory section | weekly_summary.md | Markdown list |

## Invariants

1. Budget conservation: total allocated == bucket budget +/- $100 (SYSTEM_SPEC 4.6)
2. Deterministic: same rankings + same policy → identical positions (SYSTEM_SPEC 1.1)
3. Cap enforcement: `min(family_name_cap, ladder_sub_bucket_cap)` per position
4. Quality tilt monotonicity: higher quality → more dollars (within same sub-bucket)
5. Resolution only applies to REGULATORY family (CLINICAL unaffected)

## Failure Modes

| Scenario | Expected behavior |
|----------|-------------------|
| Zero regulatory names in bucket | REGULATORY family budget reflows to CLINICAL |
| Zero names in a sub-bucket | Sub-bucket budget reflows (priority: 15_45 → 46_90 → 91_180 → 0_14) |
| Missing regulatory_quality | Clipped to q_lo (0.30), gets proportionally less but not zero |
| All names hit cap | Budget fully allocated up to N*cap; remainder is unavoidable cap drag |
| Ladder disabled | No sub-bucket assignment; flat allocation within family |

## Validation Plan

### Tests (83 total across 4 test files)
- [x] 19 tests in `test_family_sleeve_allocation.py` — effective_family, 70/30 split, reflow, summary
- [x] 25 tests in `test_regulatory_ladder.py` — sub-bucket boundaries, caps, reflow, weights
- [x] 17 tests in `test_event_resolution.py` — resolution detection, exclusion, budget reflow
- [x] 22 tests in `test_quality_tilt.py` — weights, allocation, monotonicity, budget conservation, caps

### Evaluation
- [x] Policy A/B on 50 dates (>=3% regulatory coverage, 2025+)
- [x] 63d excess delta: +1.85pp (B over A)
- [x] 84d excess delta: +1.59pp (B over A)
- [x] Verdict: POSITIVE

### Integration
- [x] Full suite: 11,198 passed, 0 failed, 3 skipped
- [x] Pre-commit hooks pass

## Expected Effect Size

Structural improvement in regulatory position sizing. Direct return impact limited by regulatory coverage (~3-4% of eligible names via PDUFA manual). Expect larger impact when enriched with full event ledger data. Primary benefit: concentration in sweet spot (15-90d) + gap-risk reduction at 0-14d.

## Non-Goals

- Does not change the ranking order (no IC impact)
- Does not add new signals or features
- Does not modify the event ledger or PDUFA manual
- Does not implement overlap de-duplication (future work)

---

## Implementation Log

### 2026-03-08 — Family sleeve allocation (commit 6aa9aac0)
- Files: `tools/live_shadow_portfolio.py`, `tests/test_family_sleeve_allocation.py`
- 19 tests

### 2026-03-08 — Regulatory time-ladder (commit f6b3859b)
- Files: `tools/live_shadow_portfolio.py`, `tests/test_regulatory_ladder.py`
- 25 tests

### 2026-03-08 — Event resolution (commit b2363c76)
- Files: `tools/live_shadow_portfolio.py`, `tests/test_event_resolution.py`
- 17 tests

### 2026-03-09 — Quality tilt (commit bf9ec6a8)
- Files: `tools/live_shadow_portfolio.py`, `tests/test_quality_tilt.py`
- 14 tests

### 2026-03-09 — Quality tilt polish (commit 22b4ca02)
- Files: `tools/live_shadow_portfolio.py`, `tests/test_quality_tilt.py`
- 8 additional edge-case tests, min/max quality in summary

### 2026-03-09 — Test fixes + A/B evaluation (commits cc6adee6, b1fcfe9d)
- Fix 5 pre-existing test failures:
  - `test_default_ruleset_id_pinned`: DEFAULT_RULESET hash drifted (`7e4bc79c` → `c00a4c58`)
  - `test_all_pass`, `test_pass_allows_trade_plan`: read real production manifest instead of mock
  - `test_pinned_id_fallback`: hardcoded stale ruleset ID instead of importing dynamically
  - `test_first_snapshot_all_buys`: `build_trade_packet()` searched production `artifacts/` when `prior_path=None`; added `positions_dir` kwarg for isolation
- New: `scripts/research/eval_regulatory_policy_ab.py`
- Full suite green: 11,198 passed, 0 failed, 3 skipped

### 2026-03-09 — Spec infrastructure (commit aa4180c6)
- Created `specs/SYSTEM_SPEC.md`, `specs/CHANGE_SPEC_TEMPLATE.md`, this change spec
- Updated `CLAUDE.md` with three-lane workflow

### A/B Result Summary
- **Coverage**: 11 PDUFA entries, ~3-4% of eligible names, 50 evaluable dates (>= 3% regulatory coverage)
- **63d excess delta**: +1.85pp (policy B over baseline A)
- **84d excess delta**: +1.59pp (policy B over baseline A)
- **Position count**: 44 avg (B) vs 60 avg (A) — tighter construction
- **Caveat**: enrichment limited to 11-entry manual PDUFA set; treat as positive lower-bound evidence
- **Next step**: expand regulatory event sources (event ledger integration), then rerun A/B
