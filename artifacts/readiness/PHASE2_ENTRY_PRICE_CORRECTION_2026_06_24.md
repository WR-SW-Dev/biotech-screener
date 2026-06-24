# Phase 2 Monitoring — Entry Price Correction Diagnostic
**Date**: 2026-06-24  
**Monitoring Day**: 12  
**Status**: DIAGNOSTIC ONLY — no governance decisions made here  
**Authority**: Entry price file sourced from Robinhood MCP actual fills (account 802349084, 2026-06-24T15:38:00Z)

---

## Defect Summary

Phase 2 daily monitoring artifacts (Day 1 through Day 12) used screener **June 9 reference prices** as position entry prices. Actual fills occurred on **June 10, 2026** at Robinhood `avg_buy_price` values. This affected 13 of 15 positions.

**Source of defect**: The monitoring pipeline pulled `entry_price` from the screener rankings snapshot (Jun 9 close) rather than from actual Robinhood execution prices.

**Authoritative baseline**: `production_data/phase2_entry_prices.json`  
Sourced via Robinhood MCP `get_equity_positions` on 2026-06-24. All 15 positions present.

---

## Entry Price Comparison (Old Monitoring vs Actual Fill)

| Ticker | Old Entry | Actual Fill | Error | Direction |
|--------|-----------|-------------|-------|-----------|
| COGT   | $35.24    | $31.35      | +12.4% | Overstated |
| DNTH   | $90.94    | $72.10      | +26.1% | Overstated |
| NRIX   | $17.51    | $15.46      | +13.3% | Overstated |
| URGN   | $26.43    | $28.02      | -5.7% | Understated |
| ALMS   | $20.30    | $20.37      | -0.3% | ≈ Correct |
| SYRE   | $70.48    | $76.10      | -7.4% | Understated |
| RVMD   | $161.26   | $143.76     | +12.2% | Overstated |
| CMPS   | $14.62    | $11.30      | +29.4% | Overstated |
| SLDB   | $7.26     | $6.49       | +11.9% | Overstated |
| DRUG   | $86.48    | $63.59      | +36.0% | Overstated |
| STOK   | $30.51    | $28.74      | +6.2% | Overstated |
| PRAX   | $338.06   | $241.92     | +39.7% | Overstated |
| TRVI   | $13.99    | $13.43      | +4.2% | Overstated |
| ERAS   | $14.68    | $13.27      | +10.6% | Overstated |
| XENE   | $53.66    | $51.95      | +3.3% | Overstated |

13 of 15 positions had overstated entry prices. ALMS was essentially correct (-0.3%). SYRE and URGN were understated (actual fills were higher than reference prices, meaning monitoring slightly overstated those gains).

---

## Corrected P&L vs Jun 23 Close

| Ticker | Old P&L% | Corrected P&L% | Change | Old Status |
|--------|----------|----------------|--------|------------|
| COGT   | +3.04%   | **+15.82%**    | +12.8pp | OK |
| DNTH   | -3.75%   | **+21.40%**    | +25.2pp | AT_RISK |
| NRIX   | +7.71%   | **+21.99%**    | +14.3pp | OK |
| URGN   | +32.99%  | **+25.45%**    | -7.5pp  | OK |
| ALMS   | +20.74%  | **+20.32%**    | -0.4pp  | OK |
| SYRE   | +37.70%  | **+27.53%**    | -10.2pp | OK |
| RVMD   | +5.12%   | **+17.91%**    | +12.8pp | OK |
| CMPS   | -13.47%  | **+11.95%**    | +25.4pp | AT_RISK |
| SLDB   | +21.07%  | **+35.44%**    | +14.4pp | OK |
| DRUG   | **-24.69%** | **+2.42%**  | +27.1pp | **CRITICAL ← RETRACTED** |
| STOK   | +1.97%   | **+8.25%**     | +6.3pp  | OK |
| PRAX   | -9.67%   | **+26.23%**    | +35.9pp | AT_RISK |
| TRVI   | +24.23%  | **+29.41%**    | +5.2pp  | OK |
| ERAS   | +2.66%   | **+13.56%**    | +10.9pp | OK |
| XENE   | +1.77%   | **+5.12%**     | +3.4pp  | OK |

**All 15 positions are positive vs actual fill prices.**

---

## Portfolio-Level Correction

| Metric | Old (Wrong Entry) | Corrected (Actual Fills) |
|--------|-------------------|--------------------------|
| Portfolio return vs entry | +7.16% | **+18.84%** |
| XBI return since Jun 10 entry | +10.04% | +10.04% (unchanged) |
| Portfolio vs XBI | **-2.88pp (TRIPPED)** | **+8.80pp (clear)** |
| Positions with P&L ≤ -20% | 1 (DRUG) | **0** |
| Drawdown gate status | TRIPPED | **NOT TRIPPED** |
| Emergency exit (-5.0pp vs XBI) | Clear | Clear |

---

## Gate Status — Corrected

| Gate | Old Status | Corrected Status |
|------|------------|------------------|
| Drawdown vs XBI (-2.0pp threshold) | TRIPPED -2.88pp | **CLEAR +8.80pp** |
| Emergency exit (-5.0pp) | Clear | Clear |
| Position -20% breach (DRUG) | TRIPPED | **RETRACTED — +2.42%** |
| Jaccard 13F cohort | PASS (0.875) | Unchanged |
| IC checkpoint | OVERDUE (operator decision required) | Unchanged |

**The drawdown gate was NEVER tripped on actual entry prices.** All reported gate breaches from Day 1 through Day 12 were artifacts of inflated reference-price entries.

---

## Pending Governance Decisions (Not Made Here)

This memo is diagnostic only. The following remain operator decisions:

1. **IC checkpoint** — Day 5 checkpoint (Jun 17) is 7 days overdue. Corrected P&L does not resolve this — it requires explicit operator decision to extend or revert Phase 2.
2. **Path C formal closure** — IC gate satisfied (+0.0432 HEALTHY, 35 dates). Separate memo required with operator sign-off.
3. **h20d re-evaluation gate** — due 2026-07-01. Jaccard check required.
4. **13F Q1 production promotion** — 6-manager → 47-manager upgrade. Separate explicit authorization required.
5. **Forward monitoring pipeline fix** — entry prices must be sourced from `phase2_entry_prices.json` going forward; screener reference prices must not be used as entry prices.

---

## Provenance

- Actual fills: `production_data/phase2_entry_prices.json` (Robinhood MCP, 2026-06-24T15:38:00Z)
- Old monitoring artifact: `artifacts/monitoring/daily_2026_06_24.json` (Day 12)
- Corrected artifact: `artifacts/phase2_monitoring/daily_2026_06_24_corrected.json`
- Comparison script: inline Python, committed with this memo
