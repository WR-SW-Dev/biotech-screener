# Spec 029: Bioshort DTE Optimization + Greeks

**Status**: IN PROGRESS
**Date**: 2026-03-18
**Depends on**: bioshort (tools/biotech_hedge_report.py), historical hedge backtest, common/options_greeks.py

## Goal

Extend bioshort so it answers two questions explicitly:
1. What is the **best DTE / expiry** for the hedge today?
2. What are the **Greeks** of the recommended hedge at full position size?

Read-only extension. Does not change DEM, ranking, execution, or production screen.

## DTE Optimization

Default buckets: 21-35 (short), 36-60 (medium-short), 61-90 (medium), 91-120 (long).
Evaluate structures per bucket, backtest finalists, select best per bucket + overall.

Best-overall decision rule (priority order):
1. historical down-month hedge payoff
2. max drawdown reduction
3. annualized carry
4. historical coverage quality
5. static hedge score

## Greeks

Per-leg: IV, delta, gamma, vega, theta, rho via black_scholes_greeks().
Net structure: signed sum of legs.
Hedge position: net * contracts * 100.
Dollar metrics: theta/day ($), vega P&L per +1 vol point ($).

## Acceptance

- Multiple listed expiries evaluated
- DTE bucket winners + best overall
- Full Greeks on all recommended structures
- Historical-entry Greeks when actual option closes exist
- Markdown: Best DTE Comparison + Greeks Summary tables
- JSON: best_dte_summary, per_leg_greeks, hedge_position_greeks
- Existing verdict/archive/diff unchanged
