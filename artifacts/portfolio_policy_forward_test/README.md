# Phase 2 Forward Paper Test

**Status:** Paper-only diagnostic. No live trading. No production integration.

## Overview

Manual forward test tracking 5 portfolio rebalancing policies side-by-side from the latest approved production snapshot through a 60–90 trading day forward window.

## Policies Tracked

1. **current_advisory** – Current portfolio state (advisory/available-snapshot behavior)
2. **weekly_trade_packet_proxy** – Hypothetical weekly rebalance (~52/period)
3. **quarterly_rebalance_proxy** – Hypothetical quarterly rebalance (4/period)
4. **static_inception_hold** – Buy and hold from inception
5. **delisting_liquidity_only** – Rebalance only on delisting/liquidity events (~2–5/period)

## Artifacts

### Daily Outputs (per trading date)

```
{date}/
  holdings.json          – Top-30 holdings and weights per policy
  performance.json       – Cumulative and daily returns, alpha vs XBI
  staleness.json         – Price freshness, data quality metrics
  turnover.json          – Rebalance transactions and costs
  attribution.json       – Per-ticker contribution, exposure, timing
  transaction_costs.json – Estimated trading costs (20 bps per trade)
```

### Checkpoint Memos

```
checkpoints/
  30day_memo.md    – Early results, data quality, continuation decision
  60day_memo.md    – Attribution deep-dive, mechanism analysis
  90day_memo.md    – Final results, Phase 3 decision recommendation
```

## Running the Test

### Manual Dry Run (First Output)

```bash
python scripts/run_phase2_forward_paper_test.py \
  --snapshot-date <LATEST_APPROVED_SNAPSHOT> \
  --test-length 1 \
  --output-dir artifacts/portfolio_policy_forward_test/ \
  --paper-only
```

### Full Forward Test (60–90 days, manual daily)

```bash
# Run each trading day manually:
python scripts/run_phase2_forward_paper_test.py \
  --start-date <FIRST_TRADING_DAY> \
  --end-date <90_TRADING_DAYS_LATER> \
  --output-dir artifacts/portfolio_policy_forward_test/ \
  --paper-only \
  --checkpoint-days 30 60 90
```

## Boundaries

- ✗ No cron scheduling
- ✗ No live portfolio execution
- ✗ No production pipeline integration
- ✗ No scoring/ranking/selector modifications
- ✓ Read-only price data access
- ✓ Paper-only artifacts (labeled as such)
- ✓ Manual/on-demand execution

## Governance Gates

Phase 2 pauses at:
- **Day 30:** Early check (data quality, continuation decision)
- **Day 60:** Attribution review (mechanism analysis)
- **Day 90:** Final results (Phase 3 decision)

Governance must approve continuation or termination at each gate.

## Approval & Authorization

Phase 2 forward test approved for implementation by governance on 2026-05-29.
- **Authorization scope:** Paper-only infrastructure only
- **No production changes authorized**
- **No live trading authorized**
- **Execution model:** Manual/on-demand
