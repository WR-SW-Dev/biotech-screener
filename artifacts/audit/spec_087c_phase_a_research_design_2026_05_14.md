# Spec 087C Phase A — Bioshort Alpha Research Design (2026-05-14)

**Author:** Research design (read-only)  
**Task:** Spec 087C — Phase A research scope definition  
**Status:** DESIGN — no implementation, blocker analysis, unblocking path proposed  
**Blocker:** "Need ≥4 fresh weekly hedge reports OR a historical reconstruction plan"

---

## Summary

Spec 087C investigates whether bioshort hedge-report guidance is valuable — not as an execution signal (explicitly prohibited), but as hedge-governance evidence. This memo defines the research scope using 2 fresh reports (2026-05-07, 2026-05-08) and 5 total reports (back to 2026-03-17), proposes a data reconstruction plan to unblock the ≥4-report blocker, and identifies which research questions are answerable now vs. requiring fresh data.

---

## 1. Research Objective — "Bioshort Alpha"

**Scope guard:** This is NOT trading alpha, NOT execution signal, NOT a selector/ranker/EV/sizing candidate. Hedge governance means: does the hedge-report guidance reduce portfolio drawdown cost relative to carry expense?

**Core questions:**
1. In months when the portfolio would drawdown (regime state: volatility spike, biotech rotation, macro hedge failure), does the recommended hedge structure protect? What is the tail payoff vs carry cost?
2. Is the 71 bps annualized carry cost (current verdict) reasonable against historical payoff months?
3. Does XBI (current best vehicle by R²=0.905) provide better hedge coverage than IBB (R²=0.701)?
4. How stable is the HEDGE NOW verdict across different portfolio compositions and market regimes?

**Non-questions (out of scope):**
- Whether to execute the hedge (that's an IC discussion, not a research question)
- Whether to reactivate `bioshort_watch` LLM agent (separate decision)
- Whether to integrate hedge recommendation into selector/ranker/sizing (prohibited)

---

## 2. Data Landscape

### Reports Available

| Date | Portfolio | Status | Notes |
|---|---|---|---|
| 2026-03-17 | EW-60 from rankings.csv | Stale (41d gap follows) | Initial report in this series |
| 2026-03-18 | EW-60 from rankings.csv | Stale (41d gap follows) | Daily sequence, same portfolio |
| 2026-03-26 | EW-60 from rankings.csv | Stale (41d gap follows) | Final pre-gap report |
| 2026-05-07 | 30-pos portfolio file | Fresh (manual run) | Post-gap; portfolio construction changed |
| 2026-05-08 | 30-pos portfolio file | Fresh (first-fire cron) | Production run; latest report |

**Key constraint:** Portfolio construction changed between Mar-26 and May-07. Mar-26 used top-60 EW (buy all eligible); May-07/08 use a 30-position portfolio file with portfolio_weight_pct. Direct cross-period comparison (e.g., "did carry improve?") requires portfolio-composition accounting. Within-period comparisons (Mar-17 to Mar-26, or May-07 to May-08) are cleaner.

### Evidence Inside the Reports

Each report contains:

- **`backtest`** — 11 months of historical data; fields: total_months, payoff_months, total_hedge_pnl, total_return_unhedged/hedged, worst_month_unhedged/hedged, max_drawdown_unhedged/hedged, Sharpe_unhedged/hedged
- **`backtest_months`** — per-month breakdown (11 rows in May-08 report; 11/11 historical coverage)
- **`ranked_structures`** — 16 option structures ranked by `hedge_score`, with `cost_score`, `protection_score`, `tail_score`, implied_vol, greeks
- **`regime_analysis`** — 3 regime states: carry dynamics, put/call ratio, skew profile
- **`beta_stats`** — XBI and IBB: beta to portfolio, R², correlation, realized vol, term structure
- **`ic_decision`** — final verdict: primary_hedge (e.g., "IBB 15% OTM put"), primary_score, confidence_score
- **`weekly_diff`** — vs prior report: vehicle changed? structure changed? score shifted?
- **`shadow_efficacy`** — static_winner, static_hedge_score (unused; for future dynamic hedging research)

---

## 3. Answerable Now (2 Fresh Reports)

### Single-Snapshot Analysis (May-08)

- Current carry cost: 71 bps/year annualized
- Historical payoff months from backtest: how many of 11 months had positive hedge PnL?
- Backtest Sharpe: unhedged vs hedged (is drawdown reduction significant?)
- XBI vehicle: R²=0.905 (excellent beta match), IBB R²=0.701 (weaker match)
- Structure confidence: 16 options ranked; top structures have cost_score, protection_score, tail_score — which trade-off is chosen?

**Actionable output:** Backtest evidence memo documenting carry cost vs expected payoff frequency (N of 11 months with positive hedge PnL), regime-specific performance (which regimes benefit most?), and structure comparison (why top-1 structure over top-4?).

### Week-Over-Week Diff (May-07 → May-08)

The May-08 report already computes `weekly_diff` fields:
- `best_vehicle_prior` vs `best_vehicle_current`
- `carry_cost_bps_prior` vs `carry_cost_bps_current`
- `best_structure_prior` vs `best_structure_current`
- `confidence_prior` vs `confidence_current`

**Actionable output:** First-week stability check — did vehicle/structure/verdict change in just 1 day of fresh data? If not, that's a positive signal for "plan is stable week-to-week."

### Backtest Coverage Quality

- 11/11 months historical (100% coverage)
- 0 BS-fallback months (all actual option data)
- Options source: Tastytrade (live; no stale pricing artifact)

**Actionable output:** High-confidence backtest claim (not "average historical returns"; actual option Greeks, realized PnL).

---

## 4. Blocked Without ≥4 Fresh Reports

### Stability of Verdict (Multi-Week Time Series)

Without ≥4 reports spanning 4+ weeks, cannot assess:
- Does HEDGE NOW persist across market moves?
- Does carry cost trend up/down over weeks?
- Are structure/vehicle choices stable or sensitive to weekly data noise?

→ Need May-15, May-22, May-29 (next 3 Fridays) to answer this.

### Regime-Shift Detection

Current verdict is tied to `confidence_score=85` and regime analysis. To know if the hedge recommendation is robust to regime change (e.g., vol spike, biotech rotation, style shift):
- Need reports across 2+ distinct regime states
- Single week (May-07 to May-08) is insufficient

→ Need ≥4 reports across 4+ weeks to capture regime variability.

### Vehicle/Structure Ranking Stability

Top structures ranked by hedge_score; top vehicle by R²/Sharpe. Stability requires:
- Multiple weeks of data
- Cross-validation that top-1 structure is consistently better than top-2, top-3

→ Need ≥4 reports spanning ≥4 weeks.

---

## 5. Historical Reconstruction Plan (Unblocking Path)

### Proposal

Run `tools/biotech_hedge_report.py` against historical portfolio snapshots for Fridays where `data/snapshots/{YYYY-MM-DD}/portfolio_positions.csv` exists. This requires:

1. **Identify candidate Fridays** — glob `data/snapshots/[0-9]*-*/portfolio_positions.csv`, parse dates, filter to Fridays
2. **Reconstruction sweep** — for each Friday YYYY-MM-DD:
   ```bash
   python tools/biotech_hedge_report.py \
     --as-of-date YYYY-MM-DD \
     --portfolio-csv data/snapshots/YYYY-MM-DD/portfolio_positions.csv
   ```
3. **Data source fallback** — for historical dates, producer already falls back to BS pricing (if no live options chain available) or realized-vol proxy. This is read-only reconstruction, not a scoring change.
4. **Storage** — reports written to `output/hedge_report/hedge_report_YYYY-MM-DD.json` as normal.

### Rationale

- All required inputs (portfolio CSV, price history, snapshot dir) are present
- Producer is idempotent (same inputs → same output)
- Fallback to BS/realized-vol is documented behavior (not a regression)
- This is a read-only data operation, not a scoring change
- No bioshort_watch LLM reactivation needed (builder remains gated by B0)

### Expected Outcome

If ≥4 Fridays with portfolio snapshots exist in recent history, reconstruction produces ≥4 reports spanning historical portfolio construction. Enables time-series analysis of verdict stability, carry trends, structure ranking persistence.

### Execution Gate

Requires **operator approval** before running. This is a multi-step data backfill, not a one-off analysis.

---

## 6. Hard Gates (Never Allowed)

**Explicit scope guards per operator decision and Spec 087 memo §1:**

- [x] No selector / ranker / EV / sizing / eligibility / scoring changes
- [x] No `catalyst_delta_score` change
- [x] No bioshort_watch LLM reactivation (separate decision)
- [x] No treating hedge report as alpha-generating execution signal
- [x] Cross-period comparisons (Mar-26 vs May-08) must explicitly account for portfolio construction change

---

## 7. Disposition

### Status

- **Phase A**: Research design complete (this memo)
- **Blocker**: "≥4 fresh weekly reports OR historical reconstruction plan" — reconstruction plan proposed (requires operator approval)
- **Phase B**: Implementation eligible after either (a) 4 fresh reports received (May-15, 22, 29 + current), or (b) historical reconstruction approved and executed

### Phase B Scope (TBD)

If research design proceeds:
- Single-snapshot evidence memo (backtest, carry, structure analysis)
- Week-over-week stability check
- Regime-conditional verdict analysis
- Hedge-payoff vs carry-cost trade-off memo

All read-only; no code changes to scoring, selector, ranker, EV, sizing, or decision engine.

---

_Spec 087C Phase A research design complete. Awaiting operator approval of historical reconstruction plan or fresh-data cadence confirmation._
