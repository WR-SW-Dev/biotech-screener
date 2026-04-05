# Timing Hazard Retraining Memo — 2026-04-05

## Status: RESEARCH ONLY — do not promote

Production behavior unchanged: dashboard-only, diagnostic, non-binding.

---

## What happened

The timing hazard pilot (Spec 057) was designed as the first proving ground
for the Event EV program. We backfilled predictions across 424 historical
snapshots (2020-01 to 2026-04), detected 2,533 real date revisions from
cross-snapshot catalyst_days drift, and scored the model.

### Phase 1: Calibration baseline (5,918 scoreable records)

- **Verdict: POOR** — Brier=0.2379, ECE=0.155
- Model assigns ~0.70 to both ON_TIME and SLIP outcomes (no discrimination)
- Base rate 65.2% on-time vs mean predicted 69.5% (+4.3% overconfidence)
- Warning flag precision: 10.3% (too low for decision use)

### Phase 2: Retraining (in-sample, 4,981 records excl. EARLY)

| Approach | Brier (IS) | ECE (IS) | N |
|----------|-----------|---------|---|
| segmented_family_CLINICAL | 0.0809 | 0.0701 | 3,493 |
| segmented_hard_True | 0.0569 | 0.0162 | 154 |
| retrained_global | 0.1660 | 0.1715 | 4,981 |
| current_default | 0.1965 | 0.1980 | 4,981 |

In-sample, segmentation looked like a breakthrough: CLINICAL segment
Brier 0.081 vs current 0.197.

### Phase 3: OOS validation (train < 2026, test >= 2026)

| Approach | Brier (OOS) | ECE (OOS) | N |
|----------|------------|----------|---|
| **current_default_coefficients** | **0.1967** | 0.1651 | 2,603 |
| simple_rule_based | 0.1973 | 0.0954 | 2,603 |
| naive_base_rate | 0.2331 | 0.1538 | 2,603 |
| retrained_global | 0.2546 | 0.2285 | 2,603 |
| segmented_CLINICAL | 0.2473 | 0.2755 | 2,088 |
| segmented_by_family | 0.2773 | 0.2981 | 2,603 |
| platt_recalibration | 0.2692 | 0.3116 | 2,603 |

**Every retrained model is worse OOS than the hand-tuned defaults.**

The in-sample improvements were overfit. The base rate shifted 15pp between
train (85.5%) and test (70.2%) — the retrained models learned the train
regime and predicted too low on 2026 data.

### Phase 2.5: Data quality fix

Found and fixed a bug in `hard_catalyst_carry.py`: `forward_carry_hard_catalysts`
overrides `catalyst_event_type` but did not update `catalyst_family`, causing
1,773 records (30% of backfill) to have empty family despite having valid
mapped event types. Three-layer fix applied (carry function, run_screen
post-carry re-classification, review/retrain backfill).

---

## What improved

1. **Infrastructure works.** The review loop, backfill pipeline, outcome
   detection, calibration scoring, and OOS validation framework all function
   correctly. This is reusable for any future timing model iteration.

2. **Regulatory is deterministic.** 100% base rate confirmed OOS (Brier 0.018).
   Does not need a learned model — treat as a rule path.

3. **catalyst_family data quality fixed.** The carry bug that caused 30% of
   records to have empty family is now fixed in production pipeline.

4. **Simple rule-based approach ties the current model** (Brier 0.1973 vs 0.1967)
   with better ECE (0.095 vs 0.165). This is a viable alternative if the
   current logistic model proves too opaque.

## What failed

1. **Retrained logistic coefficients overfit.** In-sample gains vanished OOS.
   Global retrained Brier: 0.166 IS → 0.255 OOS (worse than defaults).

2. **Segmented-by-family overfit.** CLINICAL segment: 0.081 IS → 0.247 OOS.
   The segmentation captured train-period patterns that did not generalize.

3. **Platt recalibration failed OOS.** Brier 0.269 — worse than naive base rate.
   The current predictions have too little discrimination for post-hoc
   calibration to rescue.

4. **Base rate is non-stationary.** Train period: 85.5% on-time. Test period:
   70.2% on-time. Any model trained on one regime will miscalibrate on the other.

## What is still research-only

- All retrained coefficients (global and segmented)
- Segmented-family model architecture
- Platt/isotonic recalibration
- Warning flag thresholds (10.3% precision, not decision-grade)

## What must happen before promotion

1. **Accumulate more 2026 forward data** to understand if the base rate shift
   is structural or transient.

2. **Test adaptive/rolling calibration** instead of fixed-split training —
   the non-stationarity means static coefficients will always lag.

3. **Evaluate the simple rule-based approach** as a potential replacement for
   the logistic model — it matches Brier with better ECE and is transparent.

4. **Re-run OOS with more test data** once 2-3 more months of 2026 snapshots
   accumulate (current test set is Jan-Apr 2026 only).

5. **Any promotion must pass Checklist v2** (FM, bootstrap, FDR, LOSO) on
   the timing-specific outcome, not just signal-level diagnostics.

---

## Blunt operator summary

**The pilot succeeded.**
The infrastructure captured the exact evidence needed.

**The old default coefficients are not good** — Brier 0.197, no discrimination,
warning precision 10.3%.

**But every alternative is worse on OOS data.**
Segmented-family and retrained-global both overfit the training period.

**The timing process is non-stationary** — 85.5% base rate pre-2026 vs 70.2%
in 2026. Any fixed model will lag regime changes.

**Current operational stance: keep defaults, keep dashboard-only, keep
diagnostic. Do not promote any retrained variant until rolling calibration
and more forward data close the IS/OOS gap.**

---

## Artifacts

| Artifact | Path | Status |
|----------|------|--------|
| Review script | `scripts/research/timing_hazard_review.py` | COMMITTED |
| Retrain script | `scripts/research/timing_hazard_retrain.py` | COMMITTED |
| OOS validation | `scripts/research/timing_hazard_oos_validation.py` | COMMITTED |
| Family carry fix | `common/hard_catalyst_carry.py` | COMMITTED |
| Backfill CSV | `output/timing_hazard_review/calibration_backfill.csv` | LOCAL (gitignored) |
| Retrained coefficients | `output/timing_hazard_retrain/retrained_coefficients.json` | LOCAL (CANDIDATE) |
| OOS report | `output/timing_hazard_oos/oos_validation.json` | LOCAL (gitignored) |
| Tests | `tests/test_timing_hazard_review.py`, `tests/test_catalyst_family_carry_fix.py` | COMMITTED |
