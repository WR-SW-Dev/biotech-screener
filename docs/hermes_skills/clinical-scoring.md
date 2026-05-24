---
name: clinical-scoring
triggers:
  - clinical scoring
  - PoS engine
  - probability of success
  - phase determination
  - indication mapping
  - LOA table
  - BIO benchmarks
  - clinical score
  - Module 4
  - design quality
  - execution track record
description: >
  15-step clinical scoring for Wake Robin biotech screener. Covers phase
  determination and canonical mapping, base stage scores (PoS engine) vs phase
  scores (Module 4 composite), indication mapping with 6-tier confidence, BIO
  2011-2020 LOA tables for Phase 1/2/3/NDA across 14 indications, confidence
  gating (threshold 0.40), recency scoring, trial count bonus, design quality
  (0-25 pts), execution track record (0-22 pts), endpoint strength (0-20 pts),
  composite normalization (raw/117 * 100), and commercial stage adjustments.
---

# Clinical Scoring Skill

## Purpose

Score a biotech company's clinical development program to produce a normalized 0-100 clinical score. Encodes exact rules, thresholds, and lookup tables from Module 4 + PoS Engine for deterministic, auditable scoring.

## Preconditions

- All arithmetic MUST use `Decimal` (never `float`).
- All dates MUST be ISO 8601. Never call `datetime.now()`.
- PIT safety: only use data where `source_date <= as_of_date - 1`.
- Rounding: `ROUND_HALF_UP`. Scores to 2dp.

---

## Step 1: Determine Lead Phase

Map each company's most advanced trial to a canonical phase (use the **highest** phase across all PIT-admissible trials).

| Raw Phase String | Canonical Phase |
|-----------------|-----------------|
| "Phase 1", "PHASE1", "p1" | `phase_1` |
| "Phase 1/Phase 2", "Phase 1/2" | `phase_1_2` |
| "Phase 2", "PHASE2", "p2" | `phase_2` |
| "Phase 2/Phase 3", "Phase 2/3" | `phase_2_3` |
| "Phase 3", "PHASE3", "p3" | `phase_3` |
| "NDA", "BLA" | `nda_bla` |
| "Approved", "APPROVED" | `commercial` |
| anything else | `preclinical` |

**Phase ordering**: preclinical < phase_1 < phase_1_2 < phase_2 < phase_2_3 < phase_3 < nda_bla < commercial

---

## Step 2: Look Up Base Stage Score (PoS Engine Only)

Used by PoS Engine, NOT by Module 4 composite score.

| Stage | Score |
|-------|-------|
| preclinical | 10 |
| phase_1 | 20 |
| phase_1_2 | 30 |
| phase_2 | 40 |
| phase_2_3 | 52 |
| phase_3 | 65 |
| nda_bla | 80 |
| commercial | 90 |

---

## Step 3: Compute Phase Score (Module 4, 0-30 pts raw)

Used by Module 4 clinical composite, NOT by PoS Engine.

| Phase | Score | Progress Bonus |
|-------|-------|---------------|
| approved | 30 | 5.0 |
| phase 3 | 25 | 4.0 |
| phase 2/3 | 22 | 3.5 |
| phase 2 | 18 | 3.0 |
| phase 1/2 | 12 | 2.0 |
| phase 1 | 8 | 1.0 |
| preclinical | 3 | 0.0 |
| unknown | 0 | 0.0 |

---

## Step 4: Map Indication

Mapping precedence (highest to lowest):

| Source | Confidence |
|--------|-----------|
| ticker_overrides_v3 (PIT-safe, has effective_from/until) | 0.95 |
| ticker_overrides (legacy, no time-bounds) | 0.85 |
| condition_patterns (regex word-boundary, 2+ matches) | 0.80 |
| condition_patterns (single match) | 0.65 |
| ta_fallback (therapeutic area only) | 0.50 |
| phase_only (no condition data) | 0.30 |

Category aliases: cns → neurology, autoimmune → immunology, gi_hepatology → gastroenterology

---

## Step 5: Look Up PoS Benchmarks (BIO 2011-2020)

### Phase 1 LOA

| Indication | LOA |
|-----------|-----|
| oncology | 0.057 |
| rare_disease | 0.106 |
| infectious_disease | 0.195 |
| neurology | 0.084 |
| cardiovascular | 0.071 |
| immunology | 0.112 |
| metabolic | 0.093 |
| respiratory | 0.089 |
| dermatology | 0.124 |
| ophthalmology | 0.117 |
| gastroenterology | 0.098 |
| hematology | 0.102 |
| urology | 0.095 |
| all_indications | 0.079 |

### Phase 2 LOA

| Indication | LOA |
|-----------|-----|
| oncology | 0.131 |
| rare_disease | 0.273 |
| infectious_disease | 0.196 |
| neurology | 0.144 |
| cardiovascular | 0.126 |
| immunology | 0.218 |
| metabolic | 0.167 |
| respiratory | 0.155 |
| dermatology | 0.234 |
| ophthalmology | 0.212 |
| gastroenterology | 0.178 |
| hematology | 0.195 |
| urology | 0.172 |
| all_indications | 0.152 |

### Phase 3 LOA

| Indication | LOA |
|-----------|-----|
| oncology | 0.439 |
| rare_disease | 0.649 |
| infectious_disease | 0.769 |
| neurology | 0.510 |
| cardiovascular | 0.545 |
| immunology | 0.672 |
| metabolic | 0.598 |
| respiratory | 0.567 |
| dermatology | 0.712 |
| ophthalmology | 0.687 |
| gastroenterology | 0.612 |
| hematology | 0.634 |
| urology | 0.589 |
| all_indications | 0.579 |

### NDA/BLA LOA

all_indications: 0.903

`pos_score = LOA_probability * 100`

---

## Step 6: Apply Confidence Gating

### Stage-Adjusted Base Confidence

| Stage | Confidence |
|-------|-----------|
| preclinical | 0.35 |
| phase_1 | 0.45 |
| phase_1_2 | 0.50 |
| phase_2 | 0.58 |
| phase_2_3 | 0.65 |
| phase_3 | 0.75 |
| nda_bla | 0.88 |
| commercial | 0.92 |

### Indication Confidence Modifiers (additive)

rare_disease: +0.05, dermatology: +0.04, infectious_disease: +0.03, ophthalmology: +0.03, immunology: +0.02, hematology: +0.02, metabolic/gastroenterology/urology: 0.00, respiratory: -0.02, cardiovascular: -0.03, all_indications: -0.03, oncology: -0.05, neurology: -0.08

### Data Quality Modifiers

FULL: +0.05, PARTIAL: 0.00, MINIMAL: -0.05, NONE: -0.15

```
final_confidence = clamp(base + indication_modifier + quality_modifier, 0.20, 0.95)
```

**GATING_THRESHOLD: 0.40** — Below this, PoS contributes 0 weight to composite.

---

## Step 7: Apply Optional Multipliers

| Multiplier | Clamp Range |
|-----------|------------|
| trial_design_quality | 0.70 - 1.30 |
| competitive_intensity | 0.70 - 1.00 |

---

## Step 8: Recency Scoring (0-5 pts)

| Days Since Update | Score |
|------------------|-------|
| 0-30 | 5.0 |
| 30-90 | 5.0 to 4.5 (linear) |
| 90-180 | 4.5 to 4.0 (linear) |
| 180-365 | 4.0 to 3.0 (linear) |
| 365-730 | 3.0 to 1.0 (linear) |
| >= 730 | 1.0 |

RECENCY_STALE_THRESHOLD: 730 days (triggers 20% penalty). RECENCY_UNKNOWN_PENALTY: 2.5.

---

## Step 9: Trial Count Bonus (0-5 pts, piecewise linear)

0 trials: 0.0, 1: 0.5, 2: 1.0, 5: 2.0, 10: 3.5, 20: 4.5, >= 100: 5.0

---

## Step 10: Indication Diversity Bonus (0-5 pts)

Based on unique condition tokens across all trials. 0: 0.0, 2: 0.7, 5: 1.5, 10: 3.0, 20: 4.0, >= 30: 5.0

---

## Step 11: Design Quality Scoring (0-25 pts)

- Base: 12 pts
- Randomized: +5 pts
- Double-Blind: +4 pts (mutually exclusive with single-blind)
- Single-Blind: +2 pts
- Strong Endpoint: +4 pts (mutually exclusive with weak)
- Weak Endpoint: -3 pts

**Strong endpoint patterns**: overall survival, OS, PFS, complete response, CR, ORR, DFS, EFS, MMR

**Weak endpoint patterns**: biomarker, pharmacokinetic, PK, safety, tolerability, dose-finding, MTD

---

## Step 12: Execution Track Record (0-22 pts)

- Base: 12 pts
- Completion Rate Contribution: `completion_rate * 10` pts
- Termination Rate Penalty: `termination_rate * 8` pts (subtracted)

### Trial Status Quality Weights

COMPLETED: 1.0, ACTIVE: 0.8, RECRUITING: 0.7, NOT_YET_RECRUITING: 0.6, ENROLLING_BY_INVITATION: 0.7, SUSPENDED: 0.2, TERMINATED: 0.0, WITHDRAWN: 0.0, UNKNOWN: 0.5

---

## Step 13: Endpoint Strength (0-20 pts)

- Base: 10 pts
- Strong endpoint found: +2 pts per occurrence
- Weak endpoint found: -1 pt per occurrence

---

## Step 14: Compute Total Clinical Score

```
raw_total = phase_score + phase_progress + trial_count_bonus
          + diversity_bonus + recency_bonus + design_score
          + execution_score + endpoint_score

clinical_score = clamp((raw_total / 117) * 100, 0, 100)
```

Maximum raw total = 30 + 5 + 5 + 5 + 5 + 25 + 22 + 20 = 117.
(execution_score max is 22, not 25 — base 12 + completion 10. PR #288 corrected denominator from 120.)

---

## Step 15: Commercial Stage Differentiation (PoS Engine)

### Pipeline Tier LOA Adjustments

| Tier | Min Trials | LOA Bonus |
|------|-----------|-----------|
| exceptional | >= 100 | 0.00 |
| strong | >= 30 | -0.02 |
| moderate | >= 10 | -0.05 |
| limited | >= 3 | -0.10 |
| minimal | 0-2 | -0.15 |

### Indication-Specific Commercial Risk

rare_disease: 0.00, dermatology/ophthalmology: -0.02, neurology/hematology: -0.02, oncology/immunology: -0.03, metabolic/respiratory/gastroenterology/urology: -0.04, infectious_disease/cardiovascular/all_indications: -0.05

+0.02 if >= 3 distinct phases in pipeline. Commercial LOA clamped to [0.82, 1.00].

---

## Severity Classification

| Condition | Severity |
|----------|----------|
| No trials found | SEV1 (10% penalty) |
| All trials stale (> 730 days) | SEV1 |
| No PIT-admissible data | SEV2 (50% penalty) |
| Lead phase = preclinical only | NONE |

---

## Composite Integration

| Weight Set | Clinical Weight |
|-----------|----------------|
| V3 Enhanced | 26% |
| V3 Default | 40% |
| V3 Partial | 33% |
| Baker-Style | 35% |

**PoS Delta Cap**: Maximum PoS contribution to composite = 6.0 points.

---

## Source Files

| Component | File |
|----------|------|
| PoS Engine | `pos_engine.py` (v1.2.0) |
| Clinical Scoring | `module_4_clinical_dev_v2.py` (v2.1.0) |
| Indication Mapper | `indication_mapper.py` (v2.0.0) |
| PoS Benchmarks | `data/pos_benchmarks_bio_2011_2020_v1.json` |
| Catalyst Scoring | `module_3_scoring_v2.py` (v2.0.0) |
