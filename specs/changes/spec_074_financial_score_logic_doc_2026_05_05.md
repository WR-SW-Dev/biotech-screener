# Spec 074 — Financial Score Logic Documentation (2026-05-05)

**Status:** Documentation ticket. No code changes, no retrain.

**Hold-off scope:** No weight changes. No model changes. Output is a doc section in `docs/MODEL_DOCUMENTATION.md` that makes the existing behavior legible and auditable.

---

## 1. What to document

The deployed ranker (`production_data/ranker_v2_model.json`, variant `deployed_live_pilot`) has:

```json
"coinvest_score_z": 0.02      (trained: 0.0613, capped at deployment)
"financial_score":  -0.05332  (trained and deployed weight)
"bias":             0.5019
```

The negative `financial_score` coefficient means: all else equal, a ticker with a better (higher) financial score ranks *lower* in pairwise comparisons. This is counterintuitive and is currently undocumented. Without a written causal hypothesis and falsification criteria, the coefficient cannot be monitored, challenged, or safely updated in a future retrain.

---

## 2. Causal hypothesis to document

Write the following causal hypothesis in the doc section. This is the best-supported interpretation of the training outcome — it is not claimed as proven.

> **Hypothesis:** `financial_score` captures financial strength (cash runway, burn rate, balance sheet quality). In the biotech universe, financially stronger companies tend to have lower near-term catalyst optionality because: (a) their funding risk is already resolved, removing a conditional re-rating catalyst; (b) they are more likely to be large-cap or commercial-stage names where the market's expectation is already well-calibrated; and (c) the coinvest signal (which loads positively at +0.02) already captures manager endorsement of names that survive the financial screen. The ranker learned to modestly prefer financially constrained names within the manager-endorsed set — not because distress is good, but because the market over-discounts financing risk for catalyst-stage biotechs that managers are actively holding.

This is distinct from a "distress factor" and distinct from "financial_score is bad data." The mechanism is conditional: it only applies within the subset already passing the institutional filter.

---

## 3. Falsification criteria to document

The hypothesis is falsified (and the coefficient should be flagged for retrain review) if any of the following are observed over a rolling 90-day window:

| Criterion | Falsification threshold |
|---|---|
| Names ranked UP by ranker (vs. coinvest-only order) due to lower financial_score have *worse* 20d returns than names ranked DOWN | Consistent negative differential (< -1pp median, n ≥ 20 pairs) |
| Top-30 includes names with financial_score in bottom quartile AND negative catalyst outcomes (MISS/DELAY) at higher-than-base rate | > 2× base MISS rate for bottom-quartile financial names in top-30, n ≥ 10 |
| `financial_score` distribution in top-30 shifts materially below universe median without corresponding ranker performance improvement | Median financial_score top-30 < P25 of universe for ≥ 3 consecutive snapshots |

These criteria do NOT trigger automatic retrain. They trigger a flag in the forward shadow log and a human review at the next scheduled verdict date.

---

## 4. Existing behavior to clarify

Also document:

- `financial_score` in the ranker is the **Module 5 rank-normalized score**, NOT the raw Module 2 cash/burn output. This distinction matters because rank-normalization removes outlier sensitivity — a very strong balance sheet and a merely adequate one score closer together than their raw values suggest.
- The cap on `coinvest_score_z` (0.02 deployed vs. 0.0613 trained) was a deliberate conservative deployment decision. The financial_score weight was NOT capped — it is used at full trained strength.
- `financial_score` appears in the **ranker only**, not in the selector. The selector's financial module (Module 5) uses `financial_score` as a penalty gate, not a gradient.

---

## 5. Location

Add a new subsection to `docs/MODEL_DOCUMENTATION.md`:

```
## Ranker v2 — Feature Interpretation
### coinvest_score_z (weight: +0.02)
### financial_score (weight: −0.0533)
  - Causal hypothesis
  - Falsification criteria
  - Monitoring cadence
### Deployment delta: trained vs. deployed weights
```

If `docs/MODEL_DOCUMENTATION.md` already has a ranker section, extend it rather than creating a parallel section.

---

## 6. No-op confirmation

After writing the doc:
- Run `python -m pytest tests/ -q` to confirm no test regressions from doc-only change.
- Confirm `production_data/ranker_v2_model.json` is unchanged (git diff should show no JSON mutations).

---

## 7. Review gate

This doc section should be reviewed by the same person who approves any future ranker retrain. It is the written record of the intent behind the current weights, and a future retrain that changes `financial_score`'s sign requires either (a) falsification evidence per §3, or (b) an explicit decision to override the hypothesis with a competing explanation.
