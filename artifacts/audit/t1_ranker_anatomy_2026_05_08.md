# T1 — Current Ranker Anatomy (2026-05-08)

**Author:** T1 [researcher]
**Task:** Current ranker anatomy (Task #1 in ranking-alternatives research queue)
**Status:** Research memo — read-only. No code changes. No production artifact writes.

---

## Deployment path

```
Module 2 → Module 5 composite_v3 (rank-norm within stage×size cohort → financial_normalized [5–95])
  → csv_rows["financial_score"]

Coinvest size-residualized z-score (filing-age exponential decay, half-life 90d)
  → coinvest_score_z

Decision Engine → eligibility gates → csv_rows["eligible"]

Selector (A4_SELECTOR_CONFIG, eligible rows only):
  compute_selector_scores() → selector_score [0,1] percentile across eligible cohort
  → temporary actionable_rank by selector_score (top-60 gate for ranker cohort)

Ranker v2 (pairwise_minimal mode):
  filter_cohort(): eligible=1 AND actionable_rank <= 60
  zscore_cohort_features(): z-score both features within top-60 cohort
  score_name(): avg pairwise win probability vs all cohort members
  → final_score = ranker_v2_score for cohort members
  → final_score = selector_score * 0.0001 for eligible non-cohort

Top-30: sorted(eligible_rows, key=-final_score)[:30]
Weights: size-band normalized to 100% (EW base with size-band tilts)
```

---

## Model artifact (production_data/ranker_v2_model.json)

| Field | Value |
|---|---|
| Schema | `ranker_v2_model.v1` |
| Type | `pairwise_logistic` (Bradley-Terry) |
| Features | `["coinvest_score_z", "financial_score"]` |
| Weights (deployed) | `[+0.02, -0.05332037006884376]` |
| Bias | `0.5019276351788997` |
| coinvest cap | Trained +0.0613 → capped to +0.02 at deployment |
| Training set | 36 dates, 12,400 pairs; train_accuracy=1.0 [OVERFITTING FLAG noted in docs] |
| Rollback artifact | `ranker_v2_model_5feat_rollback.json` (5-feature FEATURES_MINIMAL set) |

---

## Feature role table

| Field | Layer | Role | Coefficient / weight | Normalization | Evidence path |
|---|---|---|---|---|---|
| `coinvest_score_z` | Selector (65% weight) + Ranker | Selector: primary institutional signal; Ranker: positive weight | Selector: 1.00 of inst block; Ranker: +0.02 | Size-residualized z-score, exponential decay half-life 90d | `selector_engine.py`, `ranker_v2_pairwise.py`, `ranker_v2_model.json` |
| `financial_score` | Selector (survivability block 35%) + Ranker | Selector: survivability; Ranker: negative weight (penalizes "safe" names) | Selector: 0.35 of surv block (≈3.5% total); Ranker: -0.0533 | Module 5 rank-norm within stage×size cohort [5–95]; z-scored within top-60 at ranker time | `module_5_composite_v3.py`, `ranker_v2_pairwise.py` |
| `catalyst_decay_w` | Selector only | Catalyst block primary (30% of 15% catalyst block) | 0.30 of catalyst block (≈4.5% total) | Decay-weighted timing | `selector_engine.py` |
| `binary_quality_score` | Selector only | Catalyst block quality (25% of catalyst block) | 0.25 of catalyst block (≈3.75% total) | Composite: W_FAMILY=0.35, W_PHASE=0.30, W_SOURCE=0.20, W_DESIGN=0.15 | `common/binary_quality_score.py` |
| `inst_delta_z` | Selector (0% since v1.14.0) | Demoted 2026-05-04; weight = 0.00 | 0.00 | — | `RULESET_CHANGELOG.md`, `INST_DELTA_Z_GOVERNANCE_LOG_2026_05_04.md` |
| `severity` | Selector only | Survivability block 35% | 0.35 of surv block | — | `selector_engine.py` |
| `runway_bucket` | Selector only | Survivability block 30% | 0.30 of surv block | — | `selector_engine.py` |
| Shadow features (clinical_50 ranker, etc.) | Shadow logging only | Never mutate final_score | N/A | — | `run_screen.py`, `ranker_engine.py` |

---

## Selector vs ranker boundary

**Selector (A4_SELECTOR_CONFIG)** — applies to all eligible tickers:

| Block | Weight | Key signals |
|---|---|---|
| Clinical | 0% | All signals inert |
| Catalyst | 15% | catalyst_decay_w (30%), binary_quality_score (25%), cat_priority (20%), catalyst_strength (15%), catalyst_family (10%) |
| Survivability | 10% | financial_score (35%), severity (35%), runway_bucket (30%) |
| **Institutional** | **65%** | coinvest_score_z (100%), inst_delta_z (0%), coinvest_recency_state (0%) |
| Market structure | 10% | de_vol_60d, de_beta_xbi_60d, de_drawdown, de_rsi_14d |

**Ranker v2** — applies to top-60 by selector_score only:
- 2 features: `coinvest_score_z` (+0.02) and `financial_score` (-0.0533)
- No catalyst, clinical, options, or inst_delta_z

---

## Coinvest double-count assessment

**Yes, confirmed.** `coinvest_score_z` drives ~65% of selector score AND appears in the ranker with w=+0.02. The ranker cap (+0.02 vs trained +0.0613) reduces amplification but does not eliminate it. Median Spearman ρ(coinvest_score_z, final_score) = +0.882 on clean snapshots per `RANKER_HYGIENE_NOTE_2026_05_01.md`. Jaccard overlap selector↔ranker top-30: 57%.

**Implication for T4:** The ranker is substantially correlated with the selector. Whether the marginal ranker signal (above coinvest saturation) adds value is the central open question.

---

## Financial_score transformation

```
M2 raw
  → stage rank-norm [5–95] (WINSOR_LOW=5, WINSOR_HIGH=95)
  → stage×size rank-norm [5–95] (overwrites first normalization)
  → csv_rows["financial_score"] via _component_score(rec, "financial")
  → z-scored within top-60 ranker cohort (clamped [-3,+3]) at scoring time
  → pairwise logistic with w = -0.0533
```

**[UNCERTAIN]** Negative coefficient means higher `financial_score` (better financial health per Module 5) → lower pairwise win probability. This is consistent with the "financial stress-upside" thesis (stressed names are underpriced). However, the original training rationale is not confirmed from code alone. See T2 Alternative 5 for investment logic review, and Spec 074 for directional documentation.

---

## Catalyst timing in ranker?

**No.** Production ranker uses exactly 2 features (`FEATURES_MINIMAL_V2`). `catalyst_decay_w` appears in the 5-feature rollback artifact (`ranker_v2_model_5feat_rollback.json`) but not in the live model. `require_catalyst_window=False`. Spec 080 documents this gap explicitly as the motivation for the catalyst-timing ranker ablation design.

---

## Shadow field leakage check

**None found.** Shadow rankers (clinical_50, 2-feat model variants) are computed for logging only. Results are written to `ranker_shadow_comparison.json` but never mutate `final_score`, `ranker_active`, or `actionable_rank` on any row. Code path confirmed in `run_screen.py` and `ranker_engine.py`.

---

## [URGENT FINDING] — common/ranker_active_contract.py does not exist

**Classification: data integrity / documentation gap — not a code defect.**

The file `common/ranker_active_contract.py` is referenced in at least 5 audit documents and project memory as enforcing active ranker field contracts with 21 drift tests. **The file does not exist on disk.** There is no runtime enforcement layer beyond the model artifact's `feature_names` list in `ranker_v2_model.json`.

**T4/T5/T7 must not assume any drift-test enforcement from this module is active.** If drift tests exist, they are in a different location not found in the `tests/` search.

This finding does not constitute a scoring bug (the model artifact's feature_names list still constrains which features are used). It is a documentation/governance gap: the assumed enforcement layer is absent.

---

## Stale / contradictory docs

1. `selector_engine.py` docstring and `DEFAULT_SELECTOR_CONFIG` describe old block weights (clinical=35%, catalyst=25%) which differ from the production A4 config (clinical=0%, institutional=65%).
2. `spec_080` references "Ruleset: 2a3e79eb (v1.13.0)" — current is v1.14.0 (8887576e).
3. `common/ranker_active_contract.py` referenced throughout as a live module — does not exist on disk.

---

## Ambiguity list

1. `common/ranker_active_contract.py` missing — no runtime field contract enforcement confirmed. [URGENT FINDING above]
2. `financial_score` negative coefficient rationale — [UNCERTAIN] whether intentional stress-upside thesis or artifact of training data. Spec 074 may resolve.
3. Accuracy enhancement multiplier on `financial_normalized` — [UNCERTAIN] if active in production path.
4. Temporary vs final `actionable_rank` — ranker cohort uses temporary selector-score-based rank; final rank differs post-ranker.
5. `ranker_v2_model_backup_1776574264.json` — content and provenance not read; relationship to live model unclear.
6. `ranker_v2_model_family_c.json` — identical weights to live model but missing provenance block; not loaded by production code.

---

## Files inspected

- `production_data/ranker_v2_model.json`
- `production_data/ranker_v2_model_2feat.json`
- `production_data/ranker_v2_model_5feat_rollback.json`
- `production_data/ranker_v2_model_family_c.json`
- `ranker_v2_pairwise.py` (full)
- `run_screen.py` (lines 1–172, 4240–4330, 5010–5660, 5720–5760, 7290–7370)
- `selector_engine.py` (full)
- `ranker_engine.py` (lines 1–235)
- `decision_engine.py` (lines 1–110, 741–850, 2262–2313)
- `module_5_composite_v3.py` (lines 1–100, 610–870)
- `module_5_scoring_v3.py` (lines 1471–1510, 2160–2210, 2940–2960, 3980–4010)
- `module_5_composite_with_defensive.py` (lines 1–62)
- `common/feature_registry.py` (lines 1–130)
- `RULESET_CHANGELOG.md` (lines 1–100)
- `RANKER_HYGIENE_NOTE_2026_05_01.md` (full)
- `specs/changes/spec_080_catalyst_timing_ranker_ablation_2026_05_06.md`
- `specs/changes/spec_081_ranker_orthogonality_design_2026_05_06.md`
- `tests/test_ranker_v2_production.py` (lines 1–100)
- `artifacts/audit/ic_decomposition_readout_2026_05_08.md`
- `INST_DELTA_Z_GOVERNANCE_LOG_2026_05_04.md`

---

## Handoff summary

The production ranker is a minimal 2-feature pairwise Bradley-Terry model (coinvest_score_z +0.02, financial_score -0.0533), applied within the top-60 selector cohort. Coinvest double-counting is confirmed and substantial (ρ=+0.882 with final_score). Catalyst timing is absent from the ranker. No shadow field leakage found. Two items flagged for T4/T5/T7 attention: (1) `common/ranker_active_contract.py` does not exist — assumed enforcement layer is absent; (2) financial_score sign direction is [UNCERTAIN] against training rationale — Spec 074 should resolve this before Alternative 5 is assessed.
