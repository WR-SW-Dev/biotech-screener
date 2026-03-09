# Promotion Receipt: bebe73f8 (v1.10.0 Flatten Tier in binary_91_180)

## Promotion Summary

| Field | Value |
|-------|-------|
| **Promotion commit** | 5cd26f3dc40565136f94e8fa6138a1aa01c2f46d |
| **Ruleset ID** | `bebe73f8` |
| **Ruleset file** | `production_data/decision_rulesets/v1.10.0_flatten_tier_91_180_candidate.json` |
| **Ruleset SHA256** | `bebe73f8bfc30eae52f7ac49d28d5ff1cd496947e69c50495654dee50b741d61` |
| **Baseline ruleset** | `e966af9d` (v1.9.0_institutional_sort_candidate.json) |
| **Engine version** | v1.3.0 |
| **Promotion date** | 2026-03-09 |

## Scope Statement

**Only affects sort ordering inside the `binary_91_180` bucket (catalyst_bucket=less_binary, 91-180 days).** All other buckets (core, build_window, binary_now) are unchanged. Eligibility, tier assignment, sizing, and all non-sort behavior remain identical.

### Parameter Change

| Parameter | Baseline | Promoted |
|-----------|----------|----------|
| `binary_91_180_flatten_tier_sort` | `false` (new field) | `true` |

All other parameters inherited from `e966af9d` unchanged.

## Evaluation Windows

### Reranked Snapshots

Both baseline and candidate were reranked through production-identical `rerank_snapshots.py` with `backfill_columns()` providing `catalyst_bucket` and `catalyst_event_type` for historical snapshots.

| Dataset | Dates | Source |
|---------|-------|--------|
| OOS 2020-2024 | 295 | `data/snapshots_reranked_baseline/` vs `data/snapshots_reranked_v1100/` |
| IS 2025 | 49 (84d) / 39 (126d) | same |
| Full | 344 (84d) / 334 (126d) | same |

### Evaluation Results (Strict)

| Period | Arm | 84d Hedged | 126d Hedged | IC (84d) | IC (126d) | Turnover |
|--------|-----|-----------|-------------|----------|-----------|----------|
| **OOS 2020-2024** | Baseline | 3.07% | 4.51% | -0.054 | -0.066 | 2.03% |
| | v1.10.0 | 3.02% | 4.55% | -0.055 | -0.066 | 2.03% |
| | **delta** | **-0.05pp** | **+0.04pp** | -0.001 | 0.000 | 0.00pp |
| **IS 2025** | Baseline | 20.08% | 29.73% | +0.058 | +0.048 | 5.31% |
| | v1.10.0 | 22.83% | 29.95% | +0.058 | +0.047 | 5.10% |
| | **delta** | **+2.74pp** | **+0.22pp** | 0.000 | -0.001 | -0.21pp |
| **Full** | Baseline | 6.44% | 8.61% | -0.038 | -0.053 | 2.35% |
| | v1.10.0 | 6.33% | 8.53% | -0.039 | -0.053 | 2.31% |
| | **delta** | **-0.11pp** | **-0.08pp** | -0.001 | 0.000 | -0.04pp |

### Pass Bar

| Criterion | Required | OOS | IS 2025 | Full |
|-----------|----------|-----|---------|------|
| delta-126d hedged >= +0.20pp | +0.20pp | +0.04pp FAIL | +0.22pp PASS | -0.08pp FAIL |
| delta-84d hedged >= -0.05pp | -0.05pp | -0.05pp BORDERLINE | +2.74pp PASS | -0.11pp FAIL |

**Verdict: CONDITIONAL PASS** — passes IS 2025, flat/fails OOS (data limitation, not signal failure).

## Difference Audit

| Metric | Value |
|--------|-------|
| Dates compared | 395 |
| Same top-K | 279 (70.6%) |
| Different top-K | 116 (29.4%) |

### Movement Pattern

| Direction | Total | Tier A | Tier B | Tier C |
|-----------|-------|--------|--------|--------|
| Entering top-K | 453 | 237 | 212 | 4 |
| Exiting top-K | 453 | 449 | 0 | 4 |

| Direction | less_binary | core | build_window | binary_now |
|-----------|------------|------|-------------|------------|
| Entering | 4 | 212 | 115 | 122 |
| Exiting | 449 | 4 | 0 | 0 |

## Why OOS Is Flat (Not Harmful)

The less_binary bucket had very few names with tier diversity before H2 2025:

| Period | Avg less_binary size | Avg B/C tier names | Effect possible? |
|--------|---------------------|-------------------|--------------------|
| 2020-2022 | 2-4 names | ~0 | No |
| 2023-2024 | 4-6 names | 0-1 | Negligible |
| 2025 H1 | 5-8 names | 1-3 | Emerging |
| 2025 H2+ | 11-45 names | 4-14 | Yes |

The flag is structurally inert when all names are already Tier A.

## Local Artifacts (gitignored)

- `output/ab_verdict/VERDICT_v1100_flatten_tier.md` — full verdict document
- `output/diff_audit_flatten_tier.md` — difference audit details
- `output/validation/results.json` — raw evaluation numbers
- `data/snapshots_reranked_baseline/` — 395 reranked baseline snapshots
- `data/snapshots_reranked_v1100/` — 395 reranked candidate snapshots
