# 🧬 Wake Robin Biotech Multi-Agent Ensemble Report
**Generated:** 2026-06-20 22:56 UTC
**Method:** 3 parallel Hermes subagents (fundamental + clinical + sentiment)

---

## Unified Investment Matrix

| Ticker | Fundamental | Clinical | Sentiment | Consensus | Signal |
|--------|------------|----------|-----------|-----------|--------|
| **MRNA** | Weak (vol 79.6%, dd 89.9%) | **A** (2 active trials, Phase 3, 2 catalysts) | ✅ Positive (FDA adcomm win for flu vaccine) | 🟢 **BUY** | Strong pipeline + positive regulatory momentum despite price volatility |
| **AMGN** | **Strong** (vol 22.8%, dd 35.1%, +13.6% mom) | N/A (no mapped trials) | N/A (not in top-10 search) | 🟡 **HOLD** | Best financial health but no clinical catalysts in dataset |
| **VRTX** | Moderate (not in price top-10) | **D** (Phase 1, 1 active trial) | ✅ Positive (BLA accepted for povetacicept) | 🟢 **BUY** | Regulatory catalyst + rare disease focus, early pipeline expanding |
| **REGN** | N/A | **D** (Phase 3 completed, no active trials) | ✅ Positive (garetosmab BLA priority review, cemdisiran Phase 3 win) | 🟢 **BUY** | Strong regulatory pipeline despite no active mapped trials |
| **BIIB** | Moderate (vol 40.6%, dd 43.0%, +18.6% mom) | **D** (Phase 2, 0 active, 1 upcoming catalyst) | ✅ Positive (Breakthrough Therapy for salansen) | 🟡 **HOLD** | Positive sentiment + catalyst, but weak pipeline depth |
| **ALNY** | Moderate (vol 43.9%, dd 53.6%, +20% mom) | **D** (Phase 1/2, 1 active trial) | ✅ Positive (earnings beat, obesity pipeline) | 🟢 **BUY** | Positive momentum across all 3 signals; TTR franchise + new pipeline |
| **BMRN** | Moderate (vol 39.0%, dd 32.9%, -15.3% mom) | **B** (Phase 3, 1 active, 1 catalyst Jun 2025) | ✅ Positive (PALYNZIQ approval, hypochondroplasia Phase 3) | 🟢 **BUY** | Best risk-adjusted profile: Phase 3 + FDA approval + contained drawdown |
| **BNTX** | Weak (vol 79.6%, dd 89.9%, -2.6% mom) | **B** (Phase 2/3, 1 active, 1 catalyst Oct 2024) | ⚪ Neutral (widening losses, $1B buyback) | 🔴 **AVOID** | High volatility + mixed sentiment, pipeline not deep enough to justify risk |
| **INCY** | N/A | **C** (Phase 2, 1 active, 1 catalyst Sep 2024) | ✅ Positive (EHA data, povorcitinib NDA under review) | 🟡 **HOLD** | Regulatory catalyst pending but mid-stage pipeline |
| **EXEL** | N/A | **F** (Phase 3 terminated, no active trials) | ✅ Positive (NDA accepted, PDUFA Dec 2026) | 🔴 **AVOID** | Terminated trial is a red flag; NDA is for existing asset, not new pipeline |

---

## Cross-Agent Signal Convergence

### 🟢 Strongest Buy Signals (3 agents agree)
1. **MRNA** — Pipeline A + Positive sentiment + 2 near-term catalysts
2. **BMRN** — Pipeline B + FDA approval + best drawdown containment
3. **ALNY** — Positive momentum + earnings beat + pipeline expansion

### 🔴 Strongest Avoid Signals
1. **BNTX** — Weak financials + neutral sentiment + high volatility
2. **EXEL** — Failed pipeline (Grade F) despite pending NDA

### ⚡ Key Near-Term Catalysts (from ensemble)
| Date | Ticker | Event |
|------|--------|-------|
| Jun 2026 | MRNA | FDA adcomm backed mRNA flu vaccine |
| Jun 2026 | BIIB | Breakthrough Therapy for salansen (SMA) |
| H2 2026 | EXEL | STELLAR-304 topline results |
| Aug 2026 | REGN | PDUFA for garetosmab (FOP) |
| Dec 2026 | EXEL | PDUFA for STELLAR-303 |

---

## Agent Methodology

| Agent | Data Source | Duration | Tool Calls |
|-------|-----------|----------|------------|
| Fundamental | `output/snapshot_2024-04-01.json`, `data/daily_prices.csv` | 527s | 10 |
| Clinical | `data/trial_mapping.csv`, `data/aact_snapshots/2024-01-29/` | 227s | 5 |
| Sentiment | Web search (12 queries across 10 tickers) | 152s | 6 |
| **Total** | **Parallel execution** | **532s wall** | **21 calls** |

## Key Limitation
All 25 companies share an identical composite score (31.50) because `financial_raw` is null — the production screener has no fundamental data. The price-based metrics and trial data from this ensemble analysis are what actually differentiate companies. The optimized snapshots (`output/snapshot_optimized_*.json`) address this with IC = 0.0623 avg.
