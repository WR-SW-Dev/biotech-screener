# 🧬 Wake Robin Biotech Ensemble Report
**Generated:** 2026-06-21 11:42 UTC
**Snapshot:** `snapshot_optimized_2024-04-01.json` (as-of: 2024-04-01)
**Method:** Deterministic ensemble (fundamental + clinical + optimized scores)

---

## Unified Investment Matrix

| Ticker | Score | 6M Mom% | Vol% | MaxDD% | Health | Phase | Active | Grade | TA | Consensus |
|--------|-------|---------|------|--------|--------|-------|--------|-------|----|-----------|
| **MRNA** | 74.2 | -23.1 | 69.8 | 84.8 | Weak | Phase 3 | 2 | A | Infectious Disease | 🟡 **HOLD** |
| **BNTX** | 69.0 | +73.2 | 77.8 | 89.9 | Weak | Phase 2/Phase 3 | 1 | B | Infectious Disease | 🟡 **HOLD** |
| **BMRN** | 68.8 | +52.1 | 38.8 | 28.6 | Moderate | Phase 3 | 1 | B | Rare Disease | 🟢 **BUY** |
| **REGN** | 64.0 | +10.9 | 32.2 | 37.0 | Strong | Phase 3 | 0 | D | Immunology | 🟡 **HOLD** |
| **EXEL** | 62.2 | +147.5 | 57.7 | 55.2 | Weak | Phase 3 | 0 | F | Oncology | 🟡 **HOLD** |
| **INCY** | 52.6 | -1.6 | 47.6 | 70.7 | Weak | Phase 2 | 1 | C | Oncology | 🟡 **HOLD** |
| **ALNY** | 49.5 | -26.6 | 44.7 | 53.2 | Moderate | Phase 1/Phase 2 | 1 | D | Rare Disease | 🟡 **HOLD** |
| **VRTX** | 43.2 | -3.7 | 32.4 | 39.2 | Moderate | Phase 1 | 1 | D | Rare Disease | 🟡 **HOLD** |
| **BIIB** | 42.7 | -13.9 | 41.2 | 38.5 | Moderate | Phase 2 | 0 | D | Neurology | 🟡 **HOLD** |
| **HALO** | 30.1 | +124.3 | 61.4 | 55.7 | Weak | N/A | 0 | N/A | Oncology | 🔴 **AVOID** |
| **FOLD** | 27.5 | +62.2 | 65.9 | 80.0 | Weak | N/A | 0 | N/A | Rare Disease | 🔴 **AVOID** |
| **EDIT** | 26.4 | +76.0 | 91.4 | 95.2 | Weak | N/A | 0 | N/A | Rare Disease | 🔴 **AVOID** |
| **RARE** | 25.6 | +141.0 | 74.0 | 74.5 | Weak | N/A | 0 | N/A | Rare Disease | 🔴 **AVOID** |
| **SGEN** | 23.2 | +22.7 | 33.7 | 37.2 | Strong | N/A | 0 | N/A | Oncology | 🟡 **HOLD** |
| **IMVT** | 23.1 | +34.4 | 77.6 | 84.9 | Weak | N/A | 0 | N/A | Immunology | 🔴 **AVOID** |

---

## Consensus Picks

| Rating | Tickers |
|--------|---------|
| 🟢 **BUY** | BMRN |
| 🟡 **HOLD** | MRNA, BNTX, REGN, EXEL, INCY, ALNY, VRTX, BIIB, SGEN |
| 🔴 **AVOID** | HALO, FOLD, EDIT, RARE, IMVT |

### 🟢 Top BUY Signals

**BMRN** — Health: Moderate, Pipeline: B, Phase: Phase 3, 1 active trial(s)
  Catalysts: NCT05105568 (2025-06-01)

---

## Upcoming Catalysts

| Ticker | Catalyst |
|--------|----------|
| MRNA | NCT04470427 (2024-09-15) |
| MRNA | NCT04860297 (2024-09-01) |
| BNTX | NCT04368728 (2024-10-01) |
| BMRN | NCT05105568 (2025-06-01) |
| INCY | NCT04488081 (2024-09-01) |
| ALNY | NCT04545749 (2024-10-01) |
| VRTX | NCT05242276 (2024-12-01) |
| BIIB | NCT03872479 (2024-08-01) |

---

## Therapeutic Area Distribution

| Area | Companies |
|------|-----------|
| Rare Disease | 6 |
| Oncology | 4 |
| Infectious Disease | 2 |
| Immunology | 2 |
| Neurology | 1 |

---

## Methodology

| Dimension | Source | Key Metrics |
|-----------|--------|-------------|
| **Fundamental** | `data/daily_prices.csv` | 6M momentum, annualized volatility, max drawdown |
| **Clinical** | `data/aact_snapshots/` + `data/trial_mapping.csv` | Phase, active trials, catalysts, sponsor diversity, A-F grade |
| **Optimized Scores** | Grid-search weighted composite | IC-optimized feature weights (clinical + financial) |

**Consensus Logic:** BUY = 2+ buy signals, 0 avoid. AVOID = 2+ avoid signals, 0 buy. HOLD = everything else.
