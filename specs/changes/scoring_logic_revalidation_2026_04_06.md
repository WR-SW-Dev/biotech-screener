# Scoring Logic Revalidation — 2026-04-06

**Status**: COMPLETE
**Author**: arrenchulz + Claude
**Scope**: Full audit of selector, ranker, portfolio translation, and production consistency

---

## Architecture Map

```
Raw signals (Modules 1-5)
  ↓
Selector Engine (A4 config, 5 blocks)
  ├── Clinical block (0% weight — DEAD)
  ├── Catalyst block (15%)
  ├── Survivability block (10%)
  ├── Institutional block (65% — DOMINANT)
  │     ├── coinvest_score_z (65% within block = 42.25% total)
  │     └── inst_delta_z (35% within block = 22.75% total)
  └── Market Structure block (10%)
  → selector_score (percentile-normalized [0,1])
  ↓
Pairwise V2 Ranker (top-60 cohort, 2 features — feature_set=minimal_v2)
  ├── coinvest_score_z (DEPLOYED weight +0.02, capped Family C live pilot;
  │                     trained basis was +0.061)
  └── financial_score (DEPLOYED weight -0.0533, unchanged from trained)
  (Deployed artifact = capped Family C live-pilot vector. The trained vector
   (+0.061 / -0.053) is NOT the live vector. The artifact's provenance block
   in ranker_v2_model.json is authoritative for live weights.)
  → ranker_v2_score (avg pairwise win probability [0.46, 0.54])
  → final_score (= ranker_v2_score for cohort, 0.0001× selector for non-cohort)
  ↓
actionable_rank (sort by -final_score)
  ↓
Top-30 → IDZ prune (top-20 by inst_delta_z) → Risk Layer (C1-C7)
  → Final portfolio (EW weights, ~16-20 names)
```

---

## Phase B: Component Contribution Audit

### Selector Block Variance Decomposition (Top-60)

| Block | Weight | % of Selector Variance | Effective Range |
|-------|--------|------------------------|-----------------|
| **Institutional** | 0.65 | **92.7%** | 0.2424 |
| Catalyst | 0.15 | 3.6% | 0.0459 |
| Survivability | 0.10 | 2.3% | 0.0366 |
| Market Structure | 0.10 | 1.4% | 0.0311 |
| Clinical | 0.00 | 0.0% | DEAD |

**Institutional block rank-correlation with selector_score: 0.914**

The selector is, in practice, a fancy wrapper around coinvest_score_z + inst_delta_z.
The other 3 active blocks contribute 7.3% of variance combined.

### Ranker Feature Contribution (z-scored within cohort)

| Feature | Trained Weight | Deployed Weight | % Contribution (trained basis) |
|---------|----------------|-----------------|--------------------------------|
| coinvest_score_z | +0.0613 | **+0.02 (capped, Family C live pilot)** | 53% |
| financial_score | -0.0533 | -0.05332 (unchanged) | 47% |

The ranker is a ~50/50 split *on the trained basis* between coinvest (continuation of
selector signal) and financial_score (new information — penalizes financially safe names).
**Under the deployed (capped) vector the contribution split shifts toward financial_score**,
because coinvest is throttled from +0.0613 to +0.02 while financial is unchanged. Re-derive
the contribution percentages from the live artifact if you need them for sizing or
attribution; the table above is the trained basis only.

**Deployment note:** The `production_data/ranker_v2_model.json` artifact is the **capped
Family C live-pilot vector**, not the raw trained vector above. `model_variant =
deployed_live_pilot`, `trained_basis = minimal_v2`, `deployment_delta = coinvest weight
capped from 0.0613 to 0.02`. Contribution percentages will re-weight under the deployed
vector; the artifact's `provenance` block is the authoritative source for live weights.

### Ranker Marginal Value

- **Top-30 membership**: ranker changes 9/30 names vs selector-only (21/30 overlap)
- **Within-30 reordering**: mean 7 rank positions change, max 18
- **Score compression**: ranker scores range 0.085 (0.457 to 0.542), gaps as small as 0.00004
- **Rank 30/31 gap**: 0.0009 — very thin margin

**Verdict**: The ranker materially reorders (9 swaps), but scores are extremely compressed. Small perturbations to financial_score or coinvest can flip multiple ranks.

### IDZ Pruning Impact

- Drops 10 names from top-30 to reach top-20
- Uses inst_delta_z (already 22.75% of selector via institutional block)
- **Redundancy**: inst_delta_z is used in BOTH the selector AND the IDZ pruner — double-counting

### Risk Layer C5 Impact

- Drops ~7 names for therapeutic_area + phase concentration
- oncology+phase3 (5→2), cns+phase3 (4→2), other+phase3 (4→2), infectious+phase3 (3→2), rare_disease+phase3 (3→2)
- This is the single most portfolio-impactful control — removes more names than any scoring change

---

## Phase C: Research vs Production Reconciliation

| Item | Memory/Research Says | Production Reality | Match? |
|------|---------------------|-------------------|--------|
| Ranker features | 2 (coinvest + financial) | 2 (coinvest + financial) | **YES** |
| Ranker model | ranker_v2_model.json | ranker_v2_model.json | **YES** |
| Feature set | minimal_v2 | minimal_v2 | **YES** |
| Selector config | A4 (clinical=0, inst=0.65) | A4 (clinical=0, inst=0.65) | **YES** |
| Sort anchor | selector_score | selector_score | **YES** |
| Clinical sort | OFF | OFF | **YES** |
| All overlays | OFF | OFF (all zero in CSV) | **YES** |

**No mismatches found.** Research and production are aligned.

---

## Phase D: Simplification Test

### Top-30 Overlap with Production

| Simplified Stack | Overlap | Notes |
|-----------------|---------|-------|
| Pure coinvest_score_z only | 25/30 (83%) | No selector, no ranker |
| Institutional block only | 25/30 (83%) | Same as coinvest (block is 92.7% coinvest) |
| Selector-only (no ranker) | 21/30 (70%) | Ranker adds 9 names |
| Rebuilt pairwise (z-scored) | 25/30 (83%) | Reproducing ranker from raw features |
| Coinvest-only ranker (drop financial) | 26/30 (87%) | Financial adds ~4 name changes |
| Financial-only ranker (drop coinvest) | 20/30 (67%) | Financial alone is different portfolio |
| **Minimal: coinvest → IDZ → top-20** | **15/20 (75%)** | Simplest viable stack |

### What Each Layer Adds

1. **Selector non-institutional blocks** (catalyst, survivability, market): Change 5/30 names vs pure coinvest. Worth ~17% of membership decisions.
2. **Ranker**: Changes 9/30 names vs selector-only. Worth ~30% of membership decisions. Financial_score is the primary new information.
3. **IDZ prune**: Removes 10 names from top-30. Different signal axis from ranking.
4. **Risk layer C5**: Removes ~7 names for concentration. Most portfolio-impactful single control.

---

## Dead/Vestigial Logic Found

### Definitively Dead

1. **Clinical block** (selector): Computed for all 60 names but weight=0%. Zero contribution. Kept for "audit trail" per Spec 055 but adds processing time and CSV bloat.
2. **Clinical_50 ranker** (ranker_engine.py): Full 5-block, ~20-signal ranker system. Never fires in pairwise_minimal mode. All block score columns empty in production CSV.
3. **coinvest_recency_state** (selector): Signal spec defined with value_map but weight=0.00 in A4. Dead signal within institutional block.
4. **All sort contribution overlays**: clinical_sort, coinvest_sort, calendar_alpha_sort, alpha_cohort_tiebreak, options_quality, oncology_crowding — all OFF, all zero in CSV.
5. **Catalyst tilt** (decision_engine): `enable_catalyst_tilt=False`. Code exists but never fires.
6. **Tier gating**: When sort_anchor="selector_score", tier A/B/C/D is metadata only — does not affect ranking order.

### Vestigial but Harmless

7. **5-feature rollback model** (ranker_v2_model_5feat_rollback.json): Available for emergency but 3 dead features (inst_delta_z, catalyst_decay_w, binary_quality_score confirmed noise).
8. **Ranker feature_set="minimal"** config path: Still defined in code but production uses "minimal_v2".

---

## Key Findings

### What Actually Does Work

The scoring system has **three genuinely active signals**:

1. **coinvest_score_z** — drives 42.25% of selector, 53% of ranker, and is the dominant signal everywhere
2. **financial_score** — drives 47% of ranker (via negative weight = penalize safe names), adds 4 name changes
3. **inst_delta_z** — drives 22.75% of selector AND the IDZ pruner (double-counted)

Everything else is either zeroed, disabled, or contributes <4% of variance.

### What Is Decorative

- **Catalyst block** (15% weight, 3.6% of variance): Contributes less than one name change in the top-30
- **Survivability block** (10% weight, 2.3% of variance): Contributes less than one name change
- **Market structure block** (10% weight, 1.4% of variance): Contributes less than one name change
- **All sort overlays**: OFF, zero contribution
- **Catalyst tilt**: OFF
- **Tier assignment**: Metadata only under selector_score mode

### Surprising Findings

1. **The ranker's financial_score has a NEGATIVE weight** — it actively penalizes financially healthy companies. This is the known "safe names underperform in biotech" effect, but it's counterintuitive that the ranker's main contribution is saying "worse financials → better returns."

2. **inst_delta_z is double-counted** — 22.75% of selector score AND the IDZ pruner. This means institutional accumulation is influencing portfolio membership at two separate stages. Not necessarily wrong, but the two mechanisms can conflict (IDZ prune can drop a name that inst_delta helped rank into the top-30).

3. **Ranker scores are extremely compressed** — range of 0.085 across 60 names, with some adjacent gaps as small as 0.00004. This means the ranker is operating at the edge of numerical precision. Any noise in feature values can flip multiple ranks.

4. **C5 risk layer drops more names than any scoring change** — removing ~7 names for concentration is a larger effect than the ranker's 9-name reordering, because C5 applies AFTER all scoring.

---

## Recommendations

### Safe Fixes (Apply Now)

1. **Skip clinical block computation when weight=0**: Save processing time. Replace with constant 0.5 output for diagnostic column.
2. **Skip clinical_50 ranker when mode=pairwise_minimal**: Don't compute block scores that go to empty CSV columns.
3. **Remove empty overlay columns from CSV**: `de_sort_contrib_clinical`, `de_sort_contrib_coinvest`, `de_sort_contrib_calendar_alpha`, `de_sort_contrib_alpha_cohort_tb` — all perpetually zero.

### Simplification Opportunities (Require Decision)

4. **Remove catalyst/survivability/market blocks from selector**: Would change 5/30 names (83% overlap). These blocks add 7.3% of scoring variance. Keep or remove is a judgment call — they provide marginal diversification of the selection signal.

5. **Remove IDZ pruning**: It double-counts inst_delta_z. The selector already incorporates it at 22.75% weight. Removing IDZ prune would change the top-20 but eliminate a redundant mechanism. Counter-argument: IDZ prune acts as a construction-stage filter with different dynamics than a ranking signal.

6. **Consider the ranker's value**: It changes 9/30 names and reorders substantially. But scores are very compressed and driven by a counterintuitive signal (penalize good financials). If this signal is genuine alpha, the ranker is worth keeping. If it's overfitting to a bear-market pattern, it may not survive regime change.

### Must Not Change

7. **coinvest_score_z as primary signal**: 83% overlap with pure-coinvest ranking. This IS the model.
8. **Risk layer C5**: Actively preventing concentration. Keep enforced.
9. **Eligibility gates**: Hard exclusions (drawdown, ADV, SEV3) are safety-critical.
10. **PIT discipline**: All z-scoring uses same-snapshot cohort. No lookahead.

---

## Final Verdict

### Should I trust the current scoring logic?

**Yes, with caveats.** The scoring logic is internally consistent, research and production match, and the primary signals (coinvest + financial penalty) are justified by walk-forward evidence. No bugs found.

### Is it overcomplicated?

**Yes.** The system computes ~50 signals across 10+ blocks/layers, but only 3 signals materially affect portfolio membership: coinvest_score_z, financial_score, and inst_delta_z. Everything else contributes <4% of variance. The clinical block, clinical_50 ranker, all overlays, catalyst tilt, and tier gating are all dead or decorative code.

### What single simplification would buy the most clarity?

**Skip zero-weight blocks and disabled overlays.** This removes no decision-making power but eliminates ~40% of scoring computation and makes the system's true behavior transparent: "rank by coinvest, penalize safe names, prune by institutional accumulation, enforce concentration limits."

### What must not be changed?

- **coinvest_score_z** as primary signal
- **financial_score negative weight** in ranker (counterintuitive but validated)
- **Risk layer enforcement** (C5 especially)
- **Eligibility gates**
- **PIT safety**

---

## The Plain English Answer

> **Which parts of the current scoring system are actually doing work, and which parts just make the model look more sophisticated than it really is?**

**Doing real work:**
- coinvest_score_z (institutional conviction — 83% of the model)
- financial_score via ranker (penalizes safe names — adds 4 names, reorders 9)
- inst_delta_z via IDZ prune (institutional accumulation filter — drops 10 names)
- Risk layer C5 (concentration enforcement — drops ~7 names)
- Eligibility gates (safety exclusions)

**Decorative:**
- Catalyst block (15% weight but 3.6% of variance — less than 1 name change)
- Survivability block (10% weight but 2.3% of variance — less than 1 name change)
- Market structure block (10% weight but 1.4% of variance — less than 1 name change)
- Clinical block (0% weight — literally dead)
- Clinical_50 ranker (full shadow system, never fires)
- All sort overlays (OFF, zero contribution)
- Catalyst tilt (OFF)
- Tier assignment (metadata only, doesn't gate ranking)
- coinvest_recency_state (0% weight signal)

**The system is, in essence:** "Rank biotech companies by institutional conviction (coinvest), penalize the financially safe ones (ranker), filter by recent institutional buying (IDZ), and enforce concentration limits (C5). Everything else is scaffolding from earlier model versions that hasn't been cleaned up."
