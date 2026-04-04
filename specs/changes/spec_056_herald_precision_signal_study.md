# Spec 056 — Herald Precision / Catalyst Quality Signal Study

**Status**: COMPLETE — event_type_score PASSES Checklist v2 (first signal to do so); use as diagnostic/filter, not selector weight
**Date**: 2026-04-04
**Predecessor**: Specs 053 (Herald audit), 049 (signal framework), 055 (statistical QA)
**Evaluation**: Under Promotion Checklist v2 (mandatory)

## Motivation

The Herald precision audit (Spec 053) fixed classifier bugs and identified quality issues,
but never tested whether **catalyst date quality predicts returns**. Early signal check
shows `is_hard_catalyst` has +3.44pp spread — strong. But precision/confidence signals
are inverted (MONTH > DAY, low conf > high conf), suggesting confounds.

This study applies the full Checklist v2 framework to catalyst quality signals.

## Signal Inventory

### From research panel (already available)

| Signal | Coverage | Direction | Notes |
|--------|----------|-----------|-------|
| `is_hard_catalyst` | 100% | Higher = better | Binary: hard event vs soft/none |
| `clinical_date_confidence` | 30% | Higher = better? | 0.60–1.00 range |
| `clinical_days_precision` | 30% | DAY > MONTH? | Categorical: DAY, MONTH |
| `catalyst_days` | 63% | Ambiguous | Days to event |
| `catalyst_bucket` | 100% | Categorical | core/build_window/binary_now/less_binary |
| `catalyst_family` | 31% | Categorical | CLINICAL/REGULATORY |
| `catalyst_event_type` | 63% | Categorical | CT_PRIMARY_COMPLETION, DATA_READOUT, FDA_PDUFA |
| `catalyst_source` | 63% | Categorical | CTGOV_PCD_FAR, CTGOV_CALENDAR, SEC_8K_FILING |
| `catalyst_mode` | 100%* | Categorical | specific_days/far_window/blended_window/no_upcoming |

### Derived signals (computed per snapshot)

| Signal | Definition | Direction |
|--------|-----------|-----------|
| `hard_catalyst_z` | z-scored is_hard within eligible | Higher = better |
| `catalyst_proximity_z` | z-scored 1/catalyst_days within eligible | Higher = better (closer) |
| `source_quality_score` | SEC_8K=3, CTGOV_CALENDAR=2, CTGOV_PCD_FAR=1, none=0 | Higher = better |
| `event_type_score` | FDA_PDUFA=3, DATA_READOUT=2, CT_PCD=1, none=0 | Higher = better |
| `binary_now_flag` | 1 if catalyst_bucket == binary_now | Binary |
| `has_catalyst_flag` | 1 if catalyst_days is not null | Binary |
| `hard_clinical_flag` | is_hard AND catalyst_family == CLINICAL | Binary |
| `regulatory_flag` | 1 if catalyst_family == REGULATORY | Binary |

## Evaluation (Checklist v2 mandatory)

### Track A: Univariate signal cards
Standard: coverage, gate, selector Δ, ranker IC, regime slices

### Track B: Bundle tests
- B6 + hard_catalyst at 10-25% weight
- B6 + source_quality at 10-25% weight
- B6 + event_type at 10-25% weight
- Catalyst-only bundles

### Track C: Interaction tests
- Hard catalyst × coinvest interaction (does hard + high coinvest compound?)
- Hard catalyst × catalyst proximity interaction
- Source quality within near-catalyst (≤30d) names

### Checklist v2 Gates (mandatory for any promote candidate)
1. Fama-MacBeth: incremental NW-t ≥ 1.96 after institutional controls
2. Bootstrap: 95% CI on portfolio delta excludes zero
3. BH FDR: q-value < 0.10 within testing family
4. LOSO robustness: worst-slice delta still positive
5. Year stability: negative in ≤ 1 of tested years
