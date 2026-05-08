# Spec 093 — financial_score Sign Direction Review (2026-05-08)

**Status:** Human/governance review spec. No code changes. No retrain. No weight change.
**Priority:** 1 (only true production-correctness question from ranking alternatives audit)
**Origin:** T1–T8 ranking alternatives audit (2026-05-08). Flagged as T8 Escalation 1.
**Blocking:** All ablation testing against the production ranker baseline. Gates Alt 5 entirely.

**Hard constraints:**
- No retrain
- No weight change
- No model surgery of any kind
- Review is human-only: inspect original training config and spec, document intent in writing
- Output is a written determination, not a code commit

---

## 1. Problem Statement

The production ranker v2 carries a negative weight on `financial_score`: **-0.05332** (uncapped, full trained strength). In a pairwise Bradley-Terry model, a negative weight means a ticker with a higher `financial_score` loses more pairwise comparisons, all else equal.

`financial_score` is the Module 5 composite rank-norm: higher values indicate stronger financials within the stage×size cohort. A negative weight therefore systematically ranks weaker-financial tickers above stronger-financial ones within the top-60 coinvest cohort.

Two competing interpretations are logically consistent:

**Interpretation A — Intentional stress-upside thesis:**
The ranker deliberately selects for financially stressed names within the high-coinvest cohort, on the theory that high-conviction names under financial stress have asymmetric upside that the market undervalues. This is an aggressive but defensible investment thesis.

**Interpretation B — Training artifact:**
The negative coefficient resulted from a sign/label encoding issue, a feature direction mismatch, or an interaction with the bias term during logistic fitting. If this is the case, the ranker has been systematically penalizing financial quality since deployment.

No amount of IC measurement or ablation testing can adjudicate between interpretations A and B. The training configuration, the label construction, and the original model specification must be reviewed directly.

---

## 2. Scope

**In scope:**
- Review of original ranker v2 training specification (the config, spec, or documentation that governed the training run)
- Review of label construction: what was being predicted, and in what direction
- Review of whether the negative sign was intentional
- Written determination documenting the conclusion

**Out of scope:**
- Any retrain
- Any coefficient change
- Any weight adjustment
- Any new ablation test (that follows after this review, if conclusion is B)

---

## 3. Required Output

A written determination documenting:

1. **Was the negative weight on `financial_score` intentional?** (Yes / No / Uncertain)
2. **If intentional:** What is the rationale? Where is it documented (spec, training notes, original code comment)?
3. **If artifact:** What is the likely cause (label direction, feature normalization, bias interaction)?
4. **Directional conclusion:** Does the current coefficient direction match investment intent?
5. **No-action vs. action recommendation:** If the direction is confirmed correct, no action. If the direction is an artifact, scope a separate retrain spec (do not retrain from this spec).

File the determination as a short addendum to this spec or as a new `specs/changes/spec_093_determination_YYYY_MM_DD.md`.

---

## 4. Relevant Artifacts

- `production_data/ranker_v2_model.json` — live model weights
- `production_data/ranker_v2_model_5feat_rollback.json` — 5-feature rollback (also has financial_score weight; compare sign)
- `RANKER_HYGIENE_NOTE_2026_05_01.md` — notes on coinvest correlation
- `artifacts/audit/t1_ranker_anatomy_2026_05_08.md` — T1 anatomy memo (sign direction flagged as [UNCERTAIN])
- `artifacts/audit/ranking_alternatives_research_2026_05_08.md` — Section D (production correctness question)
- Spec 074 (if completed) — may contain directional rationale

---

## 5. Gate Consequence

Until this review is complete and the determination is filed:

- **Alt 5** (revised financial_score weighting) is frozen
- All ablation tests that use the production ranker as a baseline are methodologically ambiguous
- The forward IC of -0.031 cannot be cleanly interpreted (may reflect sign inversion rather than model failure)

**This spec does not block:** Alt 10 descriptive analysis (no-ranker comparator), catalyst distribution diagnostics (Alts 3/4 shadow), or 13F quarantine monitoring.
