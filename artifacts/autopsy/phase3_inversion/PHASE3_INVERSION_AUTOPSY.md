# Phase 3 Inversion Autopsy

> Classification: `PHASE_3_INVERSION_AUTOPSY_DIAGNOSTIC_NO_MODEL_CHANGE`  
> Generated: 2026-06-26 20:36 UTC

---

## Executive Summary

- **Primary diagnosis:** regime detector lag (confidence: high)
- **Secondary diagnosis:** veto overpenalization (confidence: medium)
- **What this means:** The model produced negative excess returns across all Phase 3 snapshots while XBI rallied. The dominant cause is the regime detector being fully offline (regime_label = UNKNOWN on 100% of tickers across every snapshot), combined with idiosyncratic top-30 selection concentrated in drawn-down names that did not participate in the sector recovery.
- **What this does not prove:** That any single model change would have prevented the inversion. Individual name selection may have been correct conditional on regime signal being absent. Out-of-sample validation is required before any model change is authorized.

---

## Phase 3 Facts

- **Window:** 2026-05-16 – 2026-06-09
- **Snapshots available:** 16
- **Model verdict behavior:** HOLD throughout — regime_label = UNKNOWN on all tickers, no regime override activated
- **XBI window return:** +2.13% total
- **XBI mean 5d return/snap:** +1.186pp
- **Top-30 basket mean 5d return/snap:** -0.335pp
- **Mean excess return/snap:** -1.521pp
- **Basket-XBI 5d correlation:** 0.984
- **COGT/DNTH held ranks 1/2 on all 16 snapshots** — roster highly stable

---

## Hypothesis Tests

### 1. Regime Detector Lag

**Confidence: HIGH**

regime_label = UNKNOWN for 100% of Phase 3 tickers on every snapshot. The regime detector was effectively offline — no regime-aware adjustments were possible. This is strong evidence for regime detector lag as a contributing factor: the model had no mechanism to detect or respond to the sector recovery.

| Snap Date | XBI 5d | Regime Labels |
|---|---:|---|
| 2026-05-18 | +4.449pp | {'UNKNOWN': 298} |
| 2026-05-19 | +6.609pp | {'UNKNOWN': 298} |
| 2026-05-20 | +3.250pp | {'UNKNOWN': 298} |
| 2026-05-21 | +3.248pp | {'UNKNOWN': 285} |
| 2026-05-22 | +1.762pp | {'UNKNOWN': 298} |
| 2026-05-26 | -4.192pp | {'UNKNOWN': 298} |
| 2026-05-27 | -3.951pp | {'UNKNOWN': 297} |
| 2026-05-28 | -1.890pp | {'UNKNOWN': 297} |
| 2026-05-29 | -3.285pp | {'UNKNOWN': 297} |
| 2026-06-01 | -4.135pp | {'UNKNOWN': 297} |
| 2026-06-02 | +2.059pp | {'UNKNOWN': 298} |
| 2026-06-03 | +2.357pp | {'UNKNOWN': 285} |
| 2026-06-04 | -3.208pp | {'UNKNOWN': 298} |
| 2026-06-05 | +0.590pp | {'UNKNOWN': 298} |
| 2026-06-08 | +5.691pp | {'UNKNOWN': 298} |
| 2026-06-09 | +4.632pp | {'UNKNOWN': 298} |

### 2. Catalyst / Veto Over-Penalization

**Confidence: MEDIUM**

Ineligible names averaged -1.16pp xs vs top-30 at -1.52pp xs (spread +0.36pp). Ineligible names outperformed top-30, consistent with veto over-penalization during the recovery.

- Top-30 mean xs: -1.519pp  hit rate: 0.374
- Ineligible mean xs: -1.156pp  hit rate: 0.431
- Spread (ineligible – top-30): +0.363pp

### 3. EES / Financing Suppression

**Confidence: LOW**

EES-blocked names averaged -1.55pp xs vs EES-eligible at -0.53pp xs (spread -1.02pp). EES-eligible names matched or outperformed blocked names; EES gate appears directionally correct during Phase 3.

- Mean quality fails/snap: 21.8
- Mean trap fails/snap: 52.5 (consistently ~60)
- EES-eligible mean xs: -0.527pp
- EES-blocked mean xs: -1.546pp
- Spread (blocked – eligible): -1.019pp

### 4. Idiosyncratic Signal vs Sector Beta

**Confidence: MEDIUM**

Basket-XBI 5d correlation = 0.984. Mean model-reported beta = 1.074. Mean 60d alpha for top-30 = 0.133. Basket maintained reasonable correlation with XBI; sector beta was partially captured, suggesting other factors drove the underperformance.

- Mean model-reported beta for top-30: 1.074
- Mean model-reported 60d alpha: 0.133
- Mean model-reported drawdown: -0.14

| Snap Date | Basket 5d | XBI 5d | XS 5d | Reported Beta |
|---|---:|---:|---:|---:|
| 2026-05-18 | +3.18% | +4.45% | -1.27pp | 1.105 |
| 2026-05-19 | +4.28% | +6.61% | -2.33pp | 1.104 |
| 2026-05-20 | +1.52% | +3.25% | -1.73pp | 1.105 |
| 2026-05-21 | +2.47% | +3.25% | -0.78pp | 1.069 |
| 2026-05-22 | +2.22% | +1.76% | +0.46pp | 1.056 |
| 2026-05-26 | -6.64% | -4.19% | -2.45pp | 1.056 |
| 2026-05-27 | -6.12% | -3.95% | -2.17pp | 1.022 |
| 2026-05-28 | -3.89% | -1.89% | -2.00pp | 1.022 |
| 2026-05-29 | -5.98% | -3.29% | -2.70pp | 1.036 |
| 2026-06-01 | -6.02% | -4.13% | -1.89pp | 1.036 |
| 2026-06-02 | +0.80% | +2.06% | -1.26pp | 1.112 |
| 2026-06-03 | +1.80% | +2.36% | -0.55pp | 1.102 |
| 2026-06-08 | +4.77% | +5.69% | -0.92pp | 1.108 |
| 2026-06-09 | +2.93% | +4.63% | -1.71pp | 1.102 |

### 5. XBI Rally Composition

**Confidence: LOW**

EES trap-filtered names averaged -2.12pp xs vs top-30 at -1.52pp xs (spread -0.60pp). Persistent trap names include large-cap biotech: FATE, GOSS, IMMP, AZN, INCY, AARD, FHTX, CHRS. Trap-filtered names did not consistently outperform; universe mismatch is a secondary factor.

Persistent EES trap-filtered names (≥50% of snapshots):  
`FATE, GOSS, IMMP, AZN, INCY, AARD, FHTX, CHRS, AMGN, CRBU, APLS, AQST`

- Trap-filtered mean xs: -2.119pp
- Top-30 mean xs: -1.519pp
- Spread (trap – top-30): -0.600pp

### 6. Structural Defensiveness

**Confidence: LOW**

Top-30 names showed mean drawdown -14.2%, mean relative drawdown vs XBI -9.5%, mean trailing 60d alpha 12.8%. EES block rate slope -0.006/snap. Drawdown and alpha readings do not clearly indicate structural defensiveness.

| Snap Date | N Eligible | EES Block Rate | Mean Drawdown | Mean 60d Alpha |
|---|---:|---:|---:|---:|
| 2026-05-18 | 212 | 31.6% | -11.5% | 18.9% |
| 2026-05-19 | 212 | 31.1% | -12.0% | 15.0% |
| 2026-05-20 | 212 | 20.8% | -11.5% | 18.9% |
| 2026-05-21 | 208 | 0.0% | -12.9% | 14.1% |
| 2026-05-22 | 215 | 18.6% | -12.7% | 14.4% |
| 2026-05-26 | 215 | 18.6% | -12.7% | 14.4% |
| 2026-05-27 | 217 | 31.8% | -12.5% | 12.4% |
| 2026-05-28 | 217 | 33.2% | -12.5% | 12.4% |
| 2026-05-29 | 216 | 37.0% | -12.3% | 13.2% |
| 2026-06-01 | 214 | 29.0% | -13.3% | 12.8% |
| 2026-06-02 | 203 | 17.2% | -18.4% | 11.7% |
| 2026-06-03 | 193 | 0.0% | -17.6% | 10.3% |
| 2026-06-04 | 208 | 27.4% | -15.4% | 9.8% |
| 2026-06-05 | 206 | 14.6% | -15.5% | 9.0% |
| 2026-06-08 | 197 | 15.2% | -18.1% | 9.8% |
| 2026-06-09 | 199 | 15.1% | -17.7% | 8.3% |

---

## Diagnosis Ranking

| Hypothesis | Confidence | Fix Implication |
|---|:---:|---|
| regime detector lag | high | Add regime override or faster recovery detector as shadow-only diagnostic |
| veto overpenalization | medium | Recalibrate veto thresholds in recovery regimes |
| idiosyncratic miss | medium | Add beta-capture allocation lens |
| ees suppression | low | Conditional EES override in recovery regime — not raw removal |
| universe mismatch | low | Benchmark against covered-universe equal-weight, not XBI only |
| structural defensiveness | low | Add decay/expiry to risk-off state logic |

---

## Fix Implications

**Safe next experiments (shadow-only, no production wiring):**
- Implement a sector regime overlay (XBI rolling trend, sector momentum signal) as a shadow diagnostic — monitor for ≥20 snapshots before any promotion gate
- Add covered-universe equal-weight return as a secondary benchmark alongside XBI to separate universe mismatch from model signal failures
- Audit whether persistent trap-filtered names (AMGN, GILD, BIIB, INCY, EXEL) drove XBI during Phase 3 — this quantifies the universe mismatch component

**Unsafe changes (require separate explicit authorization):**
- Modifying EES gates or veto logic in production
- Relaxing financing_truth_gate thresholds
- Adding regime logic to the selector or ranker
- Changing final_score computation or component weights

**Required evidence before capital scaling:**
- Phase 3 explanation validated out-of-sample on a second inversion episode
- Regime detector shadow running ≥20 snapshots without false positives
- Mean IC > 0.04 over 6+ clean PIT months
- Positive excess return in ≥55% of non-overlapping forward windows

---

## Governance Verdict

```
Classification:    PHASE_3_INVERSION_AUTOPSY_DIAGNOSTIC_NO_MODEL_CHANGE
Model change:      NO
Ranker change:     NO
Selector change:   NO
Sizing change:     NO
Production wiring: NO

Status: DIAGNOSIS COMPLETE
        AUTOPSY FINDINGS REQUIRE OUT-OF-SAMPLE VALIDATION BEFORE
        ANY MODEL CHANGE IS AUTHORIZED
```
