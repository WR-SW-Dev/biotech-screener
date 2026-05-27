# 13F Cohort-Quarantine Diff — 2026-05-15 → 2026-05-26

**Verdict:** `QUARANTINE`

**Reasons:**
- Top-30 Jaccard 0.46 < 0.7: cohort-contaminated 10 trading days

## Manager-level context (Section A)

- Registry: 49 elite_core + 6 conditional (v3.2, updated 2026-05-22)
- Pre managers_with_filing: 42 / 42  coverage=85.91%
- Post managers_with_filing: 49 / 55  coverage=84.9%
- managers_with_filing Δ: 7  coverage_pct Δ: -1.01pp

## Top-30 churn

- Jaccard: **0.463**
- Pre top-30: 30; Post top-30: 30
- Names entering: ['ALMS', 'APGE', 'ARWR', 'CMPS', 'DRUG', 'MLTX', 'MLYS', 'NRIX', 'SNDX', 'TRVI', 'TYRA']
- Names leaving: ['ACAD', 'APLS', 'ASND', 'AXSM', 'BCRX', 'JAZZ', 'JBIO', 'SION', 'TARS', 'TSHA', 'ZYME']

## Per-ticker score deltas

- coinvest_score_z: {'n': 298, 'mean_abs_delta': 0.4512, 'max_abs_delta': 2.9046, 'n_large_change': 31, 'ks_stat_vs_pre': 0.1477, 'top_3_movers': [('LBRX', 2.9046), ('RVMD', 2.5284), ('MLTX', 2.0014)]}
- inst_delta_z: {'n': 298, 'mean_abs_delta': 1.0285, 'max_abs_delta': 5.4409, 'n_large_change': 123, 'ks_stat_vs_pre': 0.1711, 'top_3_movers': [('RNA', -5.4409), ('NUVB', -5.38), ('TARS', 3.9512)]}

## Coverage

- {'tickers_in_current_pre': 298, 'tickers_in_current_post': 298, 'tickers_common_pre': 279, 'tickers_common_post': 298, 'prior_date_pre': '2025-12-31', 'prior_date_post': '2026-05-15'}

## Top-30 skew (industry / market_cap / stage)

- industry_group: pre={'Biotechnology': 27, 'Drug Manufacturers—Specialty & Generic': 3}, post={'Biotechnology': 27, 'Medical Care Facilities': 1, 'Drug Manufacturers—Specialty & Generic': 2}
- market_cap_bucket: pre={'unknown': 30}, post={'unknown': 30}
- stage_bucket: pre={'late': 24, 'mid': 5, 'early': 1}, post={'late': 22, 'mid': 7, 'early': 1}
