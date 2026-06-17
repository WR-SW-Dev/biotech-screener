# Weekly Signal Regime Sweep — 2026-05-29

**Dashboard:** 2026-05-29_dashboard.json (most recent with mature data) | **Generated:** 2026-06-17 20:23 UTC

## Fleet-Level Summary

| Signal | Health | Mean IC | Comparator | Comp Mean IC | ρ | Finding | Fidelity |
|--------|--------|---------|------------|--------------|---|---------|----------|
| inst_delta_z | ALERT | -0.0389 | coinvest_score_z | +0.0374 | -0.6621 | **signal_specific_failure** | ✅ 0.0000 |
| score_rank_pct | WARN | -0.0276 | clinical_optionality_pct_dev | +0.0028 | -0.1639 | **ambiguous** | ✅ 0.0000 |
| clinical_optionality_pct_dev | WEAK | +0.0028 | — | — | — | insufficient (WEAK, not WARN/ALERT) | — |

**Fleet verdict:** 1 signal-specific failure, 1 ambiguous, 0 fidelity failures, 1 insufficient (WEAK).

### Dashboard freshness note

The latest dashboard on disk is `2026-06-12_dashboard.json`, but it reports `NO_DATA` for all signals — the 20-day forward return window has not matured for its lookback range (2026-05-28 → 2026-06-11). This sweep falls back to `2026-05-29_dashboard.json`, the most recent dashboard with mature signal health data.

### Governance context

- **inst_delta_z**: Already governed. Zeroed in selector via v1.14.0 ruleset (8887576e) on 2026-05-04. The ALERT persists in the 60-day rolling window and will age out. Comparator `coinvest_score_z` remains healthy (mean_ic=+0.0374), confirming the institutional-flow lane is functional. **No new action required.**
- **score_rank_pct**: SPEC_REQUIRED active since 2026-05-06 (Day 3). Mean IC has worsened from -0.0119 (Day 3) to -0.0276 (2026-05-29 dashboard). Hit rate 30.0%. The comparator `clinical_optionality_pct_dev` is itself WEAK (mean_ic=+0.0028, near zero), which makes the ambiguous classification expected — the clinical lane is not a clean reference point. **Governance rule: weight reduction requires CRT+IC+PIT+Checklist v2 writeup.**
- **clinical_optionality_pct_dev**: Removed from active SIGNALS list in build_ic_dashboard.py (Spec 111, 2026-06-12). Backwards signal: mean_ic=-0.0338, hit_rate=23.68% over full history. Still appears in the 2026-05-29 dashboard because it was generated before removal. **Deprecated — no action.**

## Detailed Probe Results

### score_rank_pct vs clinical_optionality_pct_dev

**Lane:** composite-vs-clinical
**Window:** 2026-03-13 → 2026-04-29 (40 aligned dates)
**Horizon:** 20d

**Verdict:** ❓ AMBIGUOUS

| Metric | Flagged | Comparator |
|--------|---------|------------|
| Mean IC | -0.0276 | +0.0028 |
| N dates | 40 | 40 |
| Cross-signal Spearman ρ | -0.1639 (p=0.312221) | |
| Cross-signal Pearson r | -0.1389 (p=0.392748) | |
| Dashboard fidelity delta | 0.0000 | |

#### Interpretation

- Mean_ICs: flagged=-0.0276, comparator=+0.0028, ρ=-0.1639
- **Conclusion: Ambiguous.** Insufficient signal to classify.

#### Aligned IC Trajectories (first 10)

| Date | Flagged IC | Comparator IC |
|------|-----------|---------------|
| 2026-03-13 | -0.0290 | +0.0796 |
| 2026-03-14 | +0.0012 | +0.0945 |
| 2026-03-15 | +0.0071 | +0.0944 |
| 2026-03-16 | +0.0438 | +0.0913 |
| 2026-03-17 | +0.0055 | +0.1189 |
| 2026-03-18 | -0.0198 | +0.0689 |
| 2026-03-19 | -0.0524 | +0.0733 |
| 2026-03-20 | -0.0213 | +0.0229 |
| 2026-03-23 | -0.0728 | +0.0585 |
| 2026-03-24 | -0.1034 | +0.0681 |
| … | (30 more dates) | |

### inst_delta_z vs coinvest_score_z

**Lane:** institutional-flow
**Window:** 2026-03-13 → 2026-04-29 (36 aligned dates)
**Horizon:** 20d

**Verdict:** ❗ SIGNAL-SPECIFIC FAILURE

| Metric | Flagged | Comparator |
|--------|---------|------------|
| Mean IC | -0.0389 | +0.0374 |
| N dates | 36 | 36 |
| Cross-signal Spearman ρ | -0.6621 (p=1.1e-05) | |
| Cross-signal Pearson r | -0.7564 (p=0.0) | |
| Dashboard fidelity delta | 0.0000 | |

#### Interpretation

- inst_delta_z mean_ic is negative (-0.0389)
- coinvest_score_z mean_ic is positive (+0.0374) — the lane is healthy
- Cross-signal ρ=-0.6621 indicates moderate correlation
- **Conclusion: Signal-specific degradation.** The comparator in the same lane is performing well.
- Governance path: signal-health review, possible weight reduction or zero-out.

#### Aligned IC Trajectories (first 10)

| Date | Flagged IC | Comparator IC |
|------|-----------|---------------|
| 2026-03-13 | -0.1936 | +0.1721 |
| 2026-03-14 | -0.1561 | +0.1401 |
| 2026-03-15 | -0.1561 | +0.1401 |
| 2026-03-16 | -0.1561 | +0.1401 |
| 2026-03-17 | -0.1566 | +0.1157 |
| 2026-03-18 | -0.1658 | +0.1192 |
| 2026-03-19 | -0.1417 | +0.1197 |
| 2026-03-20 | -0.1152 | +0.0555 |
| 2026-03-23 | -0.1409 | +0.0964 |
| 2026-03-24 | -0.1554 | +0.1014 |
| … | (26 more dates) | |

## All Signals Status

| Signal | Mean IC | Hit Rate | Health | N Dates |
|--------|---------|----------|--------|---------|
| clinical_optionality_pct_dev | +0.0028 | 47.5% | WEAK | 40 |
| inst_delta_z | -0.0389 | 44.4% | ALERT | 36 |
| score_rank_pct | -0.0276 | 30.0% | WARN | 40 |

## What This Does NOT Prove

- Does not recommend specific weight changes. Governance review required before any selector weight modification.
- Does not rule out structural regime shift in the broader market (sector-wide factor degradation).
- Does not validate the comparator signal as investable — only assesses whether both degrade together.
- The probe n_dates (with settled 20d forward returns) may be smaller than the dashboard n_dates. This is expected.

## Provenance

- **Methodology:** `tools/build_ic_dashboard.py` (Spearman ρ, horizon=20, min_n=10)
- **Script:** `scripts/shared_regime_check.py`
- **Dashboard:** `2026-05-29_dashboard.json`
- **Price source:** `production_data/price_history.csv`
- **Generated by:** Hermes Agent (signal-shared-regime-check skill)
- **Date:** 2026-06-17 20:23 UTC