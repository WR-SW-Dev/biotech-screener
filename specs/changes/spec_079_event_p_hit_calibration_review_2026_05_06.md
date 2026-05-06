# Spec 079 — Event-Level P(HIT) Calibration Review Gate (2026-05-06)

**Status:** Spec only. No code changes. Defines the future review that determines
whether `event_ev_p_hit` (bound by Spec 077) predicts HIT/MISS outcomes and/or
risk-adjusted returns. Review cannot run until ≥30 post-PIT HIT/MISS records with
non-null `event_ev_p_hit` accumulate — estimated ~2026-07-01 at current cadence.

**Origin:** Investment Logic Audit (2026-05-06). The audit confirmed that
`prediction_composite_score` (spec_073) was the wrong EV field and that the correct
forward-looking probability — `event_ev_p_hit` from `outcome_model.py` — was bound
by spec_077 but is still too sparse for calibration (n=7 post-PIT HIT/MISS as of
2026-05-06).

**Hard constraints:**
- No EV model changes (`event_ev/outcome_model.py`)
- No selector / ranker / sizing changes
- No production EV promotion from underpowered results (n < 30)
- No Checklist v2 bypass — even at n ≥ 30, promotion requires full battery
- `DELAYED` and `NEEDS_REVIEW` outcomes excluded from HIT/MISS denominator

---

## 1. Problem statement

Spec 077 wired `event_ev_p_hit` into `ResolutionRecord` (forward-only, shadow-only).
The binder is now in place. The question this spec defines is: **does `event_ev_p_hit`
actually predict whether a catalyst resolves as a HIT vs MISS?**

There are two sub-questions:
1. **Calibration:** does `p_hit = 0.7` produce a ~70% HIT rate in the empirical data?
2. **Return discrimination:** do high-`p_hit` events produce better risk-adjusted
   returns vs XBI around resolution than low-`p_hit` events?

Neither can be answered today. As of 2026-05-06: 7 post-PIT HIT/MISS records total,
of which an unknown fraction have non-null `event_ev_p_hit` (spec_077 just shipped).
Minimum required for meaningful calibration: ≥30 with non-null `p_hit`.
Estimated arrival: ~2026-07-01 (current cadence ~3-4 resolved HIT/MISS per week).

---

## 2. Why it matters to the investment thesis

`event_ev_p_hit` is a 6-layer Bayesian posterior (phase-specific prior, endpoint
strength, design quality, clinical transmission, log-odds updates from PubMed
evidence). If it is calibrated, it could become:

- A decision-time signal for position sizing on catalyst names
- A filter within the catalyst trap layer (Spec 072 vNext) — only names with
  `p_hit ≥ threshold` receive catalyst-release-valve credit
- A complement to `coinvest_score_z` for names with upcoming binary events

If it is not calibrated or is anti-predictive, it should remain diagnostic-only
and not be wired into any production path.

The investment logic audit's principle: **autonomous evidence-driven promotion, not
assumption-driven**. This spec ensures the calibration review is gated on evidence,
not on convenience timing.

---

## 3. Current state

| Item | Status |
|---|---|
| `event_ev_p_hit` field in `ResolutionRecord` | Added by Spec 077, forward-only |
| Post-PIT HIT/MISS total | 7 (5 HIT, 2 MISS) as of 2026-05-06 |
| Post-PIT records with non-null `event_ev_p_hit` | 0 (spec_077 just shipped today) |
| Minimum n for calibration | 30 HIT/MISS with non-null `event_ev_p_hit` |
| Estimated n=30 date | ~2026-07-01 |
| `prediction_composite_score` status | Wrong field — screener quality, not P(HIT) |

---

## 4. Required data

Before running the review:

1. ≥30 resolved CRT records (status `HIT` or `MISS`, excluding `DELAYED`,
   `NEEDS_REVIEW`, `PENDING`) with `event_ev_p_hit` non-null
2. All records must be post-PIT-valid (snapshot date ≥ 2026-04-13)
3. Corresponding daily return data for ±20 trading days around `resolution_date`
   from `production_data/price_history.csv` or equivalent
4. XBI index returns for the same windows (benchmark)
5. False-catalyst flag per record — exclude any record where `catalyst_quality`
   (spec_071/078 output) is not `binary_alpha` or `invalid_status`
6. Catalyst family labels: `DATA_READOUT`, `PDUFA`, `FDA_DECISION`, `ADCOM`

---

## 5. Proposed tests

### 5a. Calibration (Brier score + reliability diagram)

```
For each resolved record with non-null event_ev_p_hit:
  - predicted = event_ev_p_hit  (probability of HIT)
  - observed  = 1 if HIT else 0

Brier score = mean((predicted - observed)^2)
Baseline Brier = mean((base_rate - observed)^2)  [where base_rate = n_HIT / n_total]

Pass condition: Brier < Baseline Brier (better than naive base-rate predictor)
```

Reliability diagram: group records into 5 equal-width buckets by `event_ev_p_hit`.
For each bucket: plot mean predicted p_hit vs empirical HIT rate. A calibrated model
should fall near the diagonal.

### 5b. HIT/MISS discrimination (AUC-ROC)

```
AUC = area under ROC curve (event_ev_p_hit as predictor, HIT=1/MISS=0)

Pass condition: AUC > 0.55 (marginal), AUC > 0.65 (moderate), AUC > 0.75 (strong)
```

### 5c. Return discrimination vs XBI (event study)

For each resolved record:
```
excess_return_5d  = ticker_return_5d_post_resolution - xbi_return_5d_post_resolution
excess_return_20d = ticker_return_20d_post_resolution - xbi_return_20d_post_resolution

Split into p_hit quintiles. Report median excess_return_5d / 20d per quintile.
```

Pass condition: monotonic relationship between p_hit quintile and median excess return.
Use Spearman ρ(p_hit, excess_return) with NW-corrected t-stat.

### 5d. Catalyst-family slices

Repeat 5a-5c within catalyst family:
- `DATA_READOUT` (CTGOV-origin)
- `PDUFA` / `FDA_DECISION` (primary disclosure origin)
- All other

Report family-level Brier and AUC separately. If one family is calibrated and another
is not, they should not be pooled.

### 5e. False-catalyst sensitivity

Re-run 5a-5b excluding any records where the resolved catalyst was retrospectively
identified as false (i.e., the event that resolved was OLE / PK / CORPORATE_UPDATE
per spec_071/078 classification). Report whether exclusion materially changes Brier/AUC.

---

## 6. Minimum evidence thresholds for promotion

| Gate | Threshold | Action if not met |
|---|---|---|
| n (HIT+MISS with non-null p_hit) | ≥ 30 | Do not run review |
| Brier < baseline | Required | Diagnostic-only; do not promote |
| AUC-ROC | ≥ 0.55 | Below: diagnostic-only |
| NW-corrected t (return discrimination) | ≥ 2.0 at 20d | Below: diagnostic-only |
| Checklist v2 battery | Required for production | 6 modules, 36 tests |

No production promotion, no ranker feature addition, no sizing weight change can
follow from this review unless all thresholds are met AND Checklist v2 is completed.

---

## 7. Review schedule

| Milestone | Condition |
|---|---|
| First check | n(HIT+MISS, non-null p_hit) ≥ 15 — descriptive only, no verdict |
| Calibration review | n ≥ 30 — estimated ~2026-07-01 |
| Promotion gate | n ≥ 50 + all thresholds + Checklist v2 |
| 2026-05-22 review | **CANCELLED** — n will be < 30 at that date |

The 2026-05-22 review date from prior planning is explicitly cancelled. Do not run
calibration with n < 30. The only action at 2026-05-22 is to check the running count.

---

## 8. What is explicitly out of scope

- Changes to `event_ev/outcome_model.py` (phase priors, log-odds weights, etc.)
- Backfill of `event_ev_p_hit` into pre-spec_077 resolution records
- Polymarket integration — remains prospective shadow-only (see polymarket_alpha_verdict)
- Calibration of `p_miss` or `p_mixed` — focus is `p_hit` vs HIT/MISS binary
- Sizing or portfolio-weight changes based on calibration results
- Any review before n(HIT+MISS with non-null p_hit) ≥ 30

---

## 9. Output artifacts

When the review runs, produce:

- `artifacts/calibration_evidence/event_ev_p_hit_calibration_<date>.json`
- `artifacts/calibration_evidence/event_ev_p_hit_calibration_<date>.md`

The markdown report must include:
1. n total, n HIT, n MISS, n with non-null p_hit
2. Brier score vs baseline, pass/fail
3. AUC-ROC with confidence interval
4. Reliability diagram (tabular in markdown: bucket, mean p_hit, empirical HIT rate, n)
5. Return discrimination: Spearman ρ and NW-corrected t for 5d and 20d
6. Catalyst-family breakdown
7. False-catalyst sensitivity delta
8. Explicit verdict: DIAGNOSTIC_ONLY / SHADOW_ELIGIBLE / CHECKLIST_REQUIRED / DO_NOT_PROMOTE

---

## 10. Dependencies

| Dependency | Status |
|---|---|
| Spec 077 (event_ev_p_hit binder) | Shipped 2026-05-06 — must accumulate records |
| ≥30 post-PIT HIT/MISS with non-null p_hit | Not yet met (~2026-07-01) |
| Spec 078 (false-catalyst gate) | Needed for sensitivity analysis (§5e) |
| Post-13F cohort window | Records generated after ~2026-05-15 are cleaner |
