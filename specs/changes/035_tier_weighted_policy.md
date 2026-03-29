# Spec 035: Tier-Weighted Portfolio Policy Shadow Candidate

**Status:** IN PROGRESS — Phase A (historical replay)
**Date:** 2026-03-29
**Lane:** Portfolio construction policy
**Type:** Shadow-only sizing / exit overlay
**Priority:** High — most actionable finding from shadow attribution audit

## Rationale

Shadow attribution shows the main drag is downstream of ranking:
- C-tier: -0.769% P&L/weight-day (2x worse than A-tier)
- Headwind names bleed at 2.3x the rate of non-headwind
- Tier-weighted policy: +1.60pp improvement over 18-day window
- Tier-weighted + headwind exit: +1.82pp improvement

## Variants

- **Variant A**: A=4%, B=2.5%, C=1%, D=0% (normalized)
- **Variant B**: Variant A + headwind+drawdown exit (>=3 consecutive days)

## Files

- specs/changes/035_tier_weighted_policy.md
- scripts/research/backtest_tier_weighted_policy.py
- tests/test_backtest_tier_weighted_policy.py
