# Catalyst Timing & Source Quality Audit

**Date:** 2026-06-20  
**Status:** COMPLETE  
**Classification:** CATALYST_ORTHOGONAL_SIGNAL_CANDIDATE + CATALYST_SIGNAL_HEALTHY_BUT_FLAT

---

## Status

```
CATALYST_TIMING_AND_SOURCE_QUALITY_AUDIT_COMPLETE
READ_ONLY
NO_CATALYST_POLICY_CHANGE
NO_SELECTOR_CHANGE
NO_RANKER_CHANGE
NO_MODEL_CHANGE
NO_PRODUCTION_OUTPUT_CHANGE
NOT_COMMITTED
```

---

## Scope

Determine whether catalyst signal can provide an orthogonal ranking signal for Phase 3, after the Institutional Signal Health audit found institutional circularity (selector inst_block ↔ coinvest_score_z correlation = 1.000).

---

## Background

The DEM ranker is blocked pending July 8 IC. The Institutional audit showed the ranker re-ranks on the same axis (institutional 13F) that selected the cohort — likely circular, a candidate explanation for the IC failure. Phase 3 needs a signal **orthogonal** to institutional. This audit tests catalyst as that candidate, conditional on it being (a) orthogonal and (b) source/date-quality robust.

---

## Artifacts Inspected

| Artifact | Purpose | Status |
|----------|---------|--------|
| data/snapshots/2026-06-18/rankings.csv | Distributions, orthogonality | ✅ |
| Catalyst columns (catalyst_score, _days, _bucket, _precision, _source, _family, etc.) | Quality decomposition | ✅ |
| selector_catalyst_block, selector_institutional_block, coinvest_score_z, financial_score | Orthogonality correlations | ✅ |

---

## Catalyst Score Distribution by Rank Bucket (2026-06-18)

```
bucket        n   cat_score_mean   cat_score_med   in_window%   near_days_med
top10        10       45.69            44.04          50%           60
top30        20       47.03            49.00          20%           90
rank31-60    30       46.20            45.24          43%           60
non-cohort  147       43.22            42.43          33%           92
```

**Catalyst_score is nearly FLAT across rank buckets.** top30 (47.0) is statistically indistinguishable from rank31-60 (46.2); non-cohort (43.2) is only ~4 points below top10. Catalyst does not separate the cohort from the rest, and barely separates within the cohort.

---

## Catalyst Timing Bucket Distribution

```
Eligible universe (207):
  overdue:    0
  0-7d:      12
  8-30d:     54
  31-90d:    32
  90+d:      88
  unknown:   21

top-30:  {90+d: 13, 31-90d: 8, 8-30d: 9}
```

**Top-30 is NOT concentrated in near-term catalysts.** 13 of 30 top-30 names have catalysts 90+ days out (e.g., RVMD at 286 days); only 9 are within 30 days; only 20% are "in window." This confirms top-30 membership is driven by institutional conviction, not catalyst proximity. **No catalyst-timing gaming of the cohort.**

---

## Catalyst Date Precision Review

```
Eligible:  DAY=160 (77%), MONTH=24, UNKNOWN=1, blank=22
top-30:    DAY=28, MONTH=2
```

**Top-ranked names are NOT dependent on low-precision dates** — 28 of 30 top-30 are DAY-precision. Coarse precision (MONTH) is concentrated in lower ranks.

### Mild date-clustering artifact (lower ranks)

```
Repeated next_catalyst_date:
  2026-07-01: 24 names    2026-08-01: 10 names
  2026-06-30: 21 names    2026-12-01: 10 names
  2026-09-01: 18 names    2026-10-01:  9 names
```

Clustering on month boundaries (07-01, 09-01, 08-01, 10-01, 12-01) indicates MONTH-precision dates anchored to month start/end — a date-resolution artifact, not 24 genuinely same-day events. **Concentrated in lower ranks; does not affect the DAY-precise top-30.** Mild, not material.

---

## Catalyst Source Quality Review

```
source:      CTGOV_CALENDAR=121, SEC_8K_FILING=50, SEC_6K_FILING=5,
             CTGOV_PCD_FAR=7, PDUFA_MANUAL=2, FDA_ADCOM_CALENDAR=1, blank=21
event_type:  DATA_READOUT=75, CT_PRIMARY_COMPLETION=73, FDA_PDUFA_DATE=25,
             CT_STUDY_COMPLETION=12, FDA_ADCOM=1, blank=21
family:      CLINICAL=160, REGULATORY=26, NO_CATALYST=21
quality:     registry_only=135, binary_alpha=50, blank=22
is_hard:     hard=101, soft=106
```

**Sources are legitimate and well-attributed:** clinicaltrials.gov calendar (the bulk), SEC filings, PDUFA dates, FDA AdCom calendar. No suspect/unsourced events. The 21 blank/NO_CATALYST names are eligible-but-no-catalyst names — all ranked ≥116 (none in cohort).

---

## Stale or Overdue Catalyst Review

```
Past-dated next_catalyst_date (< 2026-06-18):  0
catalyst_days < 0 (overdue):                    0
```

**No stale or overdue catalysts.** Every catalyst date is forward-looking relative to the snapshot. No expired events leaking into eligibility or ranking. Clean.

---

## Top-30 Catalyst Dependency

- Top-30 catalyst_score (47.0) ≈ rank31-60 (46.2) — catalyst does not distinguish them
- Only 20% of top-30 are in a near-term catalyst window
- All 30 top-30 names HAVE a catalyst signal (no missing-data entrants)
- 28/30 are DAY-precision

**Verdict:** Top-30 names have clean, complete catalyst data, but their catalyst strength is **not** what put them in the top-30. Institutional conviction did (per the Institutional audit). Catalyst is a passenger, not a driver, in current ranking.

---

## Rank-60 Boundary Catalyst Exposure

Catalyst_score is flat across the boundary band (rank31-60 = 46.2, similar to top30). Boundary churn (Selector Boundary audit) is driven by small institutional-signal differences, **not** catalyst. Catalyst does not explain rank-60 oscillation.

---

## Catalyst vs Institutional Orthogonality

**The decisive measurement.** Spearman correlations (eligible universe, n=207):

```
catalyst_score   vs coinvest_score_z:      +0.249    ← substantially orthogonal
catalyst_block   vs institutional_block:   +0.193
catalyst_score   vs selector_score (rank): +0.314    ← weakly discriminative

WITHIN cohort (top-60):
catalyst_score   vs coinvest_score_z:      -0.107    ← genuinely independent inside cohort

For reference (the other DEM feature):
financial_score  vs coinvest_score_z:      +0.086    ← also orthogonal
catalyst_score   vs financial_score:       -0.062    ← catalyst & financial mutually orthogonal
```

**Catalyst is genuinely orthogonal to institutional signal** (+0.249 universe, −0.107 within cohort). It carries information independent of the 13F axis that dominates selection and ranking. Within the cohort, catalyst and institutional are even slightly negatively correlated — a clean independent axis.

Catalyst is also orthogonal to financial_score (−0.062), so it would add a genuine third dimension.

---

## Orthogonal Signal Assessment

### Catalyst qualifies as orthogonal — but orthogonality is necessary, NOT sufficient

**The critical caveat:** `financial_score` is ALSO orthogonal to institutional (+0.086) — yet the DEM ranker that includes it **still failed IC** (Phase B). This proves orthogonality alone does not produce predictive power.

```
Necessary for a useful ranker feature:
  1. Orthogonal to existing signals    ← catalyst PASSES (+0.249 / -0.107)
  2. Predictive of forward returns (IC) ← catalyst UNMEASURED

financial_score has (1) but apparently lacks (2) → DEM IC fails.
Adding catalyst on (1) alone risks repeating that mistake.
```

**Within-cohort catalyst has real spread** (mean 46.4, stdev 5.37, range 36.4–55.1), so it is not flat *inside* the cohort — there is something to rank on. But whether that spread predicts returns is unknown.

**Conclusion:** Catalyst is the **best orthogonal candidate found so far**, materially more independent than institutional-on-institutional. But its standalone forward-return IC must be measured **before** Phase 3 inclusion — using the same Spec 100 methodology DEM is gated on. Including catalyst without an IC test would repeat the DEM error of shipping an unvalidated feature.

---

## Answers to Required Questions

```
1. catalyst_score flat or discriminative?
   FLAT across rank buckets (top30≈rank31-60); weak rank corr +0.314.
   But has genuine spread WITHIN the cohort (stdev 5.37).

2. Separates top-30 from rank 31-60?
   NO. 47.0 vs 46.2 — indistinguishable.

3. Top-30 concentrated near-term?
   NO. 13/30 are 90+d out; only 20% in-window. Institutionally selected, not catalyst-timed.

4. Top names dependent on low-precision dates?
   NO. 28/30 top-30 are DAY-precision.

5. Stale/overdue catalysts affecting ranking?
   NO. Zero past-dated, zero overdue.

6. Catalyst explains rank-60 boundary churn?
   NO. Boundary is institutional-driven; catalyst flat across it.

7. Could catalyst serve as orthogonal Phase 3 signal?
   CANDIDATE YES on orthogonality (+0.249 / -0.107). But predictive IC is
   UNPROVEN and must be measured first. Orthogonality ≠ alpha.

8. Data-quality, policy, or healthy design?
   HEALTHY design + data. Mild month-boundary date clustering in lower ranks
   is a minor precision artifact, not a defect.
```

---

## Defects

**NONE.** No logic or data errors.

- Catalyst sources are legitimate and attributed
- No stale/overdue/expired catalysts
- Top-30 catalyst data is complete and DAY-precise
- Month-boundary clustering is an expected MONTH-precision artifact, confined to lower ranks

---

## Governance Risks

### Risk 1: Premature Catalyst Inclusion in Phase 3 (MEDIUM — forward-looking)

If Phase 3 adds catalyst as a ranker feature based on orthogonality alone, it could repeat the DEM mistake: financial_score is orthogonal too, yet contributes no demonstrated IC. Catalyst must clear a standalone forward-return IC test first.

**Severity:** MEDIUM (avoidable with a gate)

### Risk 2: Date-Precision Clustering (LOW)

MONTH-precision catalysts anchored to month boundaries (07-01, 09-01) create artificial same-date clusters in lower ranks. Not currently affecting the top-30, but if catalyst were promoted to a ranker feature, these coarse dates could inject timing noise.

**Severity:** LOW (lower-rank only; would need attention only if catalyst is promoted)

---

## Classification

```
PRIMARY:   CATALYST_ORTHOGONAL_SIGNAL_CANDIDATE
           (genuinely orthogonal to institutional: +0.249 universe, -0.107 within cohort)

SECONDARY: CATALYST_SIGNAL_HEALTHY_BUT_FLAT
           (clean data + sources; flat as a CURRENT rank discriminator)

NOT:  CATALYST_DEFECT_FOUND          (no logic/data error)
NOT:  CATALYST_STALENESS_RISK         (0 stale, 0 overdue)
NOT:  CATALYST_SOURCE_QUALITY_RISK    (legitimate, attributed sources)
NOT:  CATALYST_TIMING_CONCENTRATION_GOVERNANCE_RISK  (top-30 not near-term-concentrated)
```

---

## Recommended Next Step

**Catalyst is the strongest orthogonal candidate identified — but candidacy must be validated, not assumed.**

1. **Phase 3 design input:** Catalyst (and possibly event_ev_score / event_ev_score_z, which exist in the schema and may carry forward-return-calibrated signal) are the orthogonal axes worth testing. Institutional is NOT — it is circular with selection.

2. **REQUIRED before any catalyst ranker inclusion:** Measure catalyst_score's standalone forward-return IC on the eligible cohort, using the same Spec 100 methodology as DEM. Treat it with the same gate (IC ≥ 0.0200). This can be designed now (read-only) and run on July 8 alongside the DEM IC remeasurement.

3. **Do NOT change catalyst policy, weights, or buckets.** This audit is diagnosis only.

**Roadmap continuation:** `FINAL_SCORE_HANDOFF_AND_CUTOFF_AUDIT` (#3) — now well-positioned: we've established that institutional drives ranking and catalyst/financial are orthogonal-but-unproven. The handoff audit can check whether the selector→ranker→final_score plumbing introduces discontinuities that compound the single-axis dependency.

**Strong Phase 3 thesis emerging across audits:**
> The DEM ranker fails IC likely because it re-ranks on the institutional axis that already selected the cohort. The fix is not tuning institutional weight — it is adding a *validated* orthogonal predictive feature. Catalyst is orthogonal; whether it is predictive is the open question, and must be IC-tested before inclusion.

---

## Governance Boundary

✅ **NO VIOLATIONS**

- ✅ Read-only inspection
- ✅ No catalyst policy / bucket / formula changes
- ✅ No selector/ranker/model/weight changes
- ✅ No production outputs modified
- ✅ No commits

---

## Files Modified

**None (production files).**

Pre-existing unrelated working-tree changes (NOT from this audit): `web/app.py`, `web/data_loader.py`, `web/routes/atlas.py`, `web/routes/network.py`, `data/regulatory/drugsfda.zip` — predate this session, unrelated to catalyst/selector/ranker code.

This audit added only: `artifacts/audit/catalyst_timing_source_quality_audit_2026_06_20.md` (untracked).

---

## Summary

| Aspect | Finding | Verdict |
|--------|---------|---------|
| **Catalyst rank discrimination** | Flat across buckets (top30≈rank31-60) | Flat |
| **Orthogonality to institutional** | +0.249 universe, −0.107 within cohort | ✅ Orthogonal |
| **Orthogonality to financial** | −0.062 | ✅ Independent 3rd axis |
| **Top-30 timing concentration** | Not near-term (13/30 are 90+d) | ✅ Not gamed |
| **Date precision (top-30)** | 28/30 DAY | ✅ High |
| **Stale/overdue catalysts** | 0 | ✅ Clean |
| **Source quality** | CTGOV/SEC/PDUFA, attributed | ✅ Legitimate |
| **Date clustering (lower ranks)** | Month-boundary artifact | ⚠️ Minor |
| **Predictive IC** | UNMEASURED | 🔑 Must test before Phase 3 |
| **Defects** | None | ✅ |

**Classification:** `CATALYST_ORTHOGONAL_SIGNAL_CANDIDATE + CATALYST_SIGNAL_HEALTHY_BUT_FLAT`

**Bottom line:** Catalyst is the best orthogonal candidate for a Phase 3 ranker feature — but orthogonality is necessary, not sufficient (financial_score is orthogonal too and DEM still fails IC). Catalyst's forward-return IC must be measured before inclusion.

---

## References

- **Institutional audit:** institutional circularity (inst_block ↔ coinvest_z = 1.000); DEM likely fails IC because it re-ranks on the selection axis
- **Selector Boundary audit:** catalyst block weak rank discriminator (0.333)
- **Phase B:** DEM final_score IC fails; financial_score (orthogonal) insufficient
- **Phase 2d:** financial_score never reaches z-score bounds
- **Schema note:** event_ev_score / event_ev_score_z exist and may be additional orthogonal candidates worth IC-testing
