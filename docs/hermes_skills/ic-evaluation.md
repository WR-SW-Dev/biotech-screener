---
name: ic-evaluation
triggers:
  - IC measurement
  - signal evaluation
  - Checklist v2
  - forward shadow
  - signal promotion
  - signal demotion
  - IC backtest
  - ranker evaluation
  - evidence hierarchy
description: >
  Reference for the statistical framework used to evaluate, promote, and demote
  signals. Covers IC decomposition (Spec 100 corrected to final_score), Checklist v2
  5-gate promotion battery, forward shadow monitoring, and the evidence hierarchy.
  All composite_score IC claims are invalidated — use final_score only.
---

# IC & Signal Evaluation Skill

## Purpose

Reference for the statistical framework used to evaluate, promote, and demote signals in the biotech screener. Covers IC measurement, the Checklist v2 promotion battery, forward shadow monitoring, and the evidence hierarchy.

This skill is organized into two sections:

1. **Framework Reference** - Stable rules, constants, and methodology (changes only with code updates)
2. **Operational State** - Volatile snapshots that go stale and require periodic refresh

---

# SECTION 1: FRAMEWORK REFERENCE

---

## IC Decomposition

**Tool**: `tools/ic_decomposition.py`

Measures Spearman IC of a signal vs forward returns, segmented by cohort and stage.

### Key Features

- Forward returns panel: PIT-safe, h5d (5-day horizon)
- Cohort-contamination tagging: dates after manager additions flagged as contaminated
- Pre/post IC reported separately (clean vs contaminated windows)
- Stage_bucket segmentation (early/mid/late)
- catalyst_quality segmentation (auto-detects column presence)
- Top-30 walk-forward: mean/median excess 5d return per snap date + cumulative

### IC Tooling Scope Gap — RESOLVED via Spec 100 (2026-05-17)

**Prior finding (Spec 095, 2026-05-13):** The IC backtest tool measured composite_score IC, NOT production ranker final_score IC.

- composite_rank correlates only 0.25 with actionable_rank (production)
- Top-30 overlap: 7/30 (23%) between composite vs production rankings

**Spec 100 Implementation (2026-05-17):** Tool corrected to measure `final_score` by default.

- Default signal changed from `score_rank_pct` → `final_score`
- Metadata includes explicit `spec_100_status: "CORRECTED"`
- `composite_score` IC marked as INVALIDATED for promotion purposes
- All future IC output states score field, tool version, and measurement status
- Prior composite_score IC claims remain invalidated

**Tooling specification:** `run_rank_ic_backtest.py --signal final_score` (now default)

### Interpretation Rules

- Serial correlation is heavy (5-day windows overlap across daily snapshots)
- 14 snap dates yields ~37 effective observations
- IC t-stats are indicative only, not promotion-grade
- Promotion requires Checklist v2 (full battery below)
- **Ranker IC is now measurable (Spec 100, 2026-05-17)** — historical composite_score IC claims are invalidated

---

## Checklist v2 Promotion Battery

**File**: `scripts/research/checklist_v2_rerun.py`

5-gate statistical bar. A signal must pass ALL gates for promotion.

### Gate 1: Fama-MacBeth (FM) Regression

- Cross-sectional regression with Newey-West corrected standard errors
- Positive t-stat required
- Controls for size, momentum, and sector

### Gate 2: Bootstrap

- 1000 iterations of resampled IC
- 95% CI must exclude zero
- P(>0) threshold for confidence

### Gate 3: FDR (False Discovery Rate)

- Benjamini-Hochberg correction across all tested signals
- Controls for multiple comparison bias

### Gate 4: LOSO (Leave-One-Slice-Out)

- Robustness across all dimensions: time, sector, market cap, regime
- Must be ROBUST (not fragile to any single slice removal)

### Gate 5: Year Stability

- Signal must maintain positive IC across rolling annual windows
- 1-year stability gate for production promotion

### Scoring

| Score | Meaning |
|-------|---------|
| 5/5 | Full promotion eligible |
| 3-4/5 | Shadow research, monitor |
| 1-2/5 | Shadow only, do not promote |
| 0/5 | Dead lane |

---

## Forward Shadow Monitoring

**Tracker**: coinvest_shadow_tracker v2 (7 arms, wired into `run_daily.py`)

The ONLY true out-of-sample evidence. Accumulates daily from production.

### Evaluation Rules

- Evaluate after 30+ trading days of true-PIT daily production
- If forward evidence is positive: re-establish selector thesis from clean data
- If forward evidence is negative: selector needs structural re-examination
- Do NOT backfill from historical

---

## Evidence Hierarchy

| Rank | Source | Strength |
|------|--------|---------|
| 1 | Checklist v2 rerun (2026-04-04) | STRONGEST (signals) |
| 2 | True PIT backtest (Spec 050) | STRONGEST (portfolio) |
| 3 | Pairwise feature audit (2026-04-04) | SUPPORTING |
| 4 | Forward shadow | MONITORING |
| 5 | Old PIT benchmark (Spec 048) | SUPERSEDED |

---

## IC Measurement Constants

| Constant | Value | Purpose |
|----------|-------|---------|
| MIN_OBS_IC | 10 | Minimum observations for IC |
| MIN_OBS_TSTAT | 20 | Minimum for t-statistic |
| MIN_OBS_BOOTSTRAP | 30 | Minimum for bootstrap CI |
| MIN_ROLLING_WINDOW | 12 weeks | Minimum rolling window |
| BOOTSTRAP_ITERATIONS | 1000 | Bootstrap resampling count |
| TSTAT_THRESHOLD_95 | 2.0 | 95% confidence |
| TSTAT_THRESHOLD_99 | 2.58 | 99% confidence |

### Forward Return Horizons

| Horizon | Trading Days |
|---------|-------------|
| 1w | 5 |
| 2w | 10 |
| 1m | 20 |
| 1.5m | 30 |
| 3m | 60 |
| 4.5m | 90 |

---

## Deprecated Evidence (Do Not Cite)

- All survivorship-only benchmark numbers (+93.7pp, +110.5pp, etc.)
- Pre-Checklist-v2 signal card t-stats
- "Bear IR 3.35" regime story from contaminated data
- Any promotion memo citing pre-Spec-050 selector performance
- **Any ranker IC claim based on composite_score** (Spec 095, 2026-05-13; Spec 100 fix, 2026-05-17)

---

## Source Files

| Component | File |
|----------|------|
| IC Decomposition | `tools/ic_decomposition.py` |
| Checklist v2 Rerun | `scripts/research/checklist_v2_rerun.py` |
| Statistical QA Package | `common/stats/` (6 modules) |
| Forward Shadow Tracker | Part of `run_daily.py` |
| Signal Evidence Runner | `scripts/run_signal_evidence.py` |

---

# SECTION 2: OPERATIONAL STATE

> **SNAPSHOT DATA** - The values below are point-in-time and go stale. Verify against current pipeline output before citing.

---

## Current Signal Scores (Checklist v2)

*Last reviewed: 2026-05-08*

| Signal | Score | Status |
|--------|-------|--------|
| B6 bundle (coinvest + inst_delta) | 5/5 | Production (as bundle) |
| event_type_score | 5/5 | Overlay only (doesn't improve B6) |
| coinvest_score_z standalone | 3/5 | Part of bundle |
| insider_exec_buy_value_90d | 1/5 | Shadow only, FRAGILE |
| aact_execution_score | 1/5 | Shadow only, bear-unstable |

## coinvest_score_z IC Snapshot

*Last reviewed: 2026-05-13*

| Window | n_dates | Mean IC | Hit Rate |
|--------|---------|---------|----------|
| Pooled (all) | 14 | -0.031 | 28.6% |
| Pre-cohort (clean) | 9 | -0.051 | 11.1% |
| Post-cohort (contaminated) | 5 | -0.008 | 60.0% |

**Verdict**: OBSERVE. April selloff drove pre-cohort negativity. Post-cohort recovering.

## Governance Freeze Status

*Last reviewed: 2026-05-24*

- **Architecture Freeze**: ACTIVE — h20d DEFERRED (Path B). No promotions without Checklist v2.
- **13F Quarantine**: ACTIVE — Jaccard 0.364. No selector/ranker changes until cohort clears.
- **Ranker IC tooling**: Spec 100 corrected (2026-05-17). Interpretation deferred post-freeze.
- **Re-decision gate**: Condition-based (Jaccard ≥ 0.70 + ≥10 post-refresh snapshots + dist cleared)
