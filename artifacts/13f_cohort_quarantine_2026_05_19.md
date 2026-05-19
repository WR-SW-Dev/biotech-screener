# 13F Cohort-Quarantine Diff — 2026-05-15 → 2026-05-19

**Verdict:** `NO_QUARANTINE`

**Reasons:**
- inst_delta_z KS=0.34 ≥ 0.3: refresh confirmed (expected)

## Manager-level context (Section A)

- Registry: 42 elite_core + 6 conditional (v2.5, updated 2026-04-25)
- Pre managers_with_filing: 42 / 42  coverage=85.91%
- Post managers_with_filing: 42 / 42  coverage=84.9%
- managers_with_filing Δ: 0  coverage_pct Δ: -1.01pp

## Top-30 churn

- Jaccard: **0.875**
- Pre top-30: 30; Post top-30: 30
- Names entering: ['ALMS', 'ARGX']
- Names leaving: ['SYRE', 'URGN']

## Per-ticker score deltas

- coinvest_score_z: {'n': 298, 'mean_abs_delta': 0.009, 'max_abs_delta': 0.0489, 'n_large_change': 0, 'ks_stat_vs_pre': 0.0201, 'top_3_movers': [('CMPX', -0.0489), ('IRON', -0.0477), ('INSM', -0.0458)]}
- inst_delta_z: {'n': 298, 'mean_abs_delta': 1.0, 'max_abs_delta': 6.6566, 'n_large_change': 114, 'ks_stat_vs_pre': 0.3389, 'top_3_movers': [('NUVB', -6.6566), ('RNA', -6.4651), ('DRUG', 4.5203)]}

## Coverage

- {'tickers_in_current_pre': 298, 'tickers_in_current_post': 298, 'tickers_common_pre': 279, 'tickers_common_post': 298, 'prior_date_pre': '2025-12-31', 'prior_date_post': '2026-05-15'}

## Top-30 skew (industry / market_cap / stage)

- industry_group: pre={'Biotechnology': 27, 'Drug Manufacturers—Specialty & Generic': 3}, post={'Biotechnology': 27, 'Drug Manufacturers—Specialty & Generic': 3}
- market_cap_bucket: pre={'unknown': 30}, post={'unknown': 30}
- stage_bucket: pre={'late': 24, 'mid': 5, 'early': 1}, post={'late': 25, 'mid': 4, 'early': 1}
