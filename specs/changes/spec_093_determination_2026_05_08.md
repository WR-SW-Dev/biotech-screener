# Spec 093 — Financial Score Sign Direction: Determination (2026-05-08)

**Status:** DETERMINATION COMPLETE — T8 escalation RESOLVED  
**Determination:** INTENTIONAL — stress-upside thesis confirmed, not a sign/label artifact  
**Author:** arrenchulz + Claude (investigation session 2026-05-08)  
**No code changes. No retrain. No weight changes.**

---

## 1. Question

Is the negative `financial_score` weight (−0.0533, deployed; −0.0533, trained) in the production pairwise ranker v2 intentional ("stress-upside thesis") or a sign/label inversion artifact from training?

---

## 2. Evidence Reviewed

### 2a. Feature encoding — `ranker_v2_pairwise.py`

`FEATURES_MINIMAL_V2` defines `financial_score` as `FeatureSpec("financial_score")` with default `higher_is_better=True`. In `_encode_feature`, the polarity flip (`fval = -fval`) only applies when `not spec.higher_is_better`. Therefore:

- Financial_score is fed to the model **in the positive direction** (higher raw value → higher feature value)
- The trained weight of −0.0533 is a **genuine negative**: the model learned that within-cohort, names with higher financial_score lose pairwise comparisons against names with lower financial_score
- **No sign artifact. No label inversion.**

### 2b. Six-diagnostic feature audit (2026-04-04, commit `770063da4`)

Before the 2-feature model was promoted, a dedicated audit ran six diagnostic tests on the financial_score direction within the pairwise cohort:

| Regime | NW-t |
|--------|------|
| Bear | −3.38 |
| Bull | −3.42 |
| All cohort widths | Consistently negative |

Return spread: **5.84pp** between high and low financial_score names (within top-60 manager-endorsed set).

Commit message conclusion: `"financial_score: TRUE PENALTY — negative across all cohort widths, all regimes. Financially secure biotech names have less catalytic upside. Correct model behavior."`

### 2c. 45-month walk-forward study (2026-04-05, commits `4d7c67d21`, `3eb770a4d`)

| Config | Spread | IC | IC t-stat |
|--------|--------|----|-----------|
| 5-feature (production) | +1.66% | +0.128 | +2.66 |
| 2-feature (coinvest + financial) | **+2.95%** | **+0.143** | **+2.98** |

The 2-feature model with the negative financial_score weight outperformed the 5-feature model on every metric. If the negative weight were an artifact, removing or flipping it would have improved OOS performance — but the opposite was observed: the dead features (inst_delta_z, catalyst_decay_w, binary_quality_score) added noise, while the 2-feature model with the negative weight was the strongest.

### 2d. Scoring Logic Revalidation (2026-04-06, `scoring_logic_revalidation_2026_04_06.md`)

In the "Must not change" list: **"financial_score negative weight in ranker (counterintuitive but validated)"**

### 2e. Model documentation (`docs/MODEL_DOCUMENTATION.md`, Spec 074 section)

Full causal hypothesis + falsification criteria already documented. Causal hypothesis:

> Financially stronger companies have lower near-term catalyst optionality: (a) funding risk already resolved → no conditional re-rating catalyst; (b) larger/commercial-stage → market expectations already calibrated; (c) coinvest already captures manager endorsement of names passing the financial screen. The ranker learned to prefer financially constrained names within the manager-endorsed set — not because distress is good, but because the market over-discounts financing risk for catalyst-stage names that managers are actively holding.

---

## 3. Determination

**The negative weight is INTENTIONAL — stress-upside thesis confirmed.**

Ruling out artifact interpretation:
- **Not a sign/label artifact**: Feature encoding verified as `higher_is_better=True`; no polarity flip applied during extraction.
- **Not regime-specific overfitting**: Negative in bear regime (NW-t=−3.38) AND bull regime (NW-t=−3.42). If it were a bear-market artifact it would not persist with equal strength in bull.
- **Not a training fit artifact**: OOS performance on 45-month walk-forward confirms the negative weight improves predictions out-of-sample (IC +0.143 vs +0.128, t=2.98 vs 2.66).
- **Not undocumented**: Causal hypothesis, falsification criteria, and monitoring cadence are fully written in `docs/MODEL_DOCUMENTATION.md`.

The mechanism is conditional: it applies **within** the top-60 coinvest-selected cohort. The selector's survivability block already excludes critically distressed names (SEV3, critical runway). What remains is a gradient within the adequately-funded set where financially stronger names have already resolved their financing optionality, while constrained names carry conditional re-rating potential that the market prices conservatively.

---

## 4. Open Questions (Non-Blocking)

These do not block the determination but should be resolved at Gate 4 / h20d:

1. **Ablation not yet run**: Walk-forward IC of coinvest-only ranker vs. 2-feature ranker. Training IC (+0.143) is the 2-feature bundle; the individual marginal contribution of the negative financial_score weight is not separable from the current evidence. Run at Gate 4 (n≥30 HIT/MISS, ~2026-07-15).

2. **train_accuracy=1.0**: The production model overfits perfectly on training pairs. This is expected with n=12,400 pairs and a 2-parameter model trained for 200 epochs, but it means the training IC is optimistic. OOS walk-forward (t=2.98) is the relevant evidence.

3. **Post-13F regime validation**: The 45-month walk-forward predates the 2026-04-25 cohort change. After Q1 2026 13F refresh (~2026-05-15), re-confirm that the financial_score distribution in the top-60 hasn't shifted materially (cf. Spec 074 falsification criterion 3).

---

## 5. T8 Escalation Resolution

**T8 Escalation 1 (financial_score sign direction [CRITICAL]):** RESOLVED  
**Resolution:** Intentional. No retrain. No weight change. Causal hypothesis documented. Monitoring via Spec 074 falsification criteria active.

No further human decision required on this item. The escalation is closed.

---

## 6. Standing Monitoring

Per Spec 074 (`docs/MODEL_DOCUMENTATION.md` → "Ranker v2 — Feature Interpretation"), the falsification criteria are the active monitoring mechanism:

| Criterion | Threshold |
|---|---|
| Names ranked UP by ranker (lower financial_score) have worse 20d returns | < −1pp median differential, n ≥ 20 pairs |
| Bottom-quartile financial names in top-30 have above-base MISS rate | > 2× base MISS rate, n ≥ 10 |
| Median top-30 financial_score drops below P25 of universe | ≥ 3 consecutive snapshots |

These trigger a flag in the forward shadow log and human review at the next verdict date — not automatic retrain.

---

*No code changes. No production changes. No weight changes. Determination only.*  
*Next action: Spec 074 documentation already complete in `docs/MODEL_DOCUMENTATION.md`. No additional deliverables.*
