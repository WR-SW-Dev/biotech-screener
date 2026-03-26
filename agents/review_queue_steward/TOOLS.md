# TOOLS.md — Review Queue Steward

## Data sources (read-only)

### Primary — review queue
- `data/snapshots/{date}/review_queue.csv`
  - Columns: ticker, tier, composite_score, catalyst_days, catalyst_family,
    action, action_reason, market_model_disagreement, ts_flag_type,
    ts_blind_spot_days, options_quality_composite, regulatory_days, as_of_date
- `data/snapshots/{date}/review_queue.md` — human-readable version

### Coverage context
- `data/snapshots/{date}/coverage_quality.json`
  - options_data_freshness, catalyst_coverage, component_coverage
  - Term structure flags: n_mismatch, n_blind_spot, n_not_pricing

### Model context (for "must look now" classification)
- `data/snapshots/{date}/rankings.csv` — tier, rank, catalyst_days, is_hard
- `artifacts/live_shadow/positions/{date}.json` — shadow portfolio membership
- `artifacts/live_shadow/trade_plan/{date}/trade_plan.csv` — trade plan membership

### Prior queue (for change detection)
- `data/snapshots/{prior_date}/review_queue.csv`

## Queue action codes

| Code | Meaning | Severity |
|------|---------|----------|
| `no_add_until_review` | Blocked from adding — human must review first | HIGH |
| `size_haircut` | Position sizing reduced due to flag | MEDIUM |
| `monitor_only` | Flagged for monitoring, no restriction | LOW |
| `manual_review_required` | Explicit manual review needed | HIGH |

## Disagreement levels

| Level | Meaning |
|-------|---------|
| `high` | Large model-market divergence |
| `medium` | Moderate divergence |
| `low` | Minor divergence |

## Term structure flag types

| Flag | Meaning |
|------|---------|
| `MARKET_SEES_SOONER` | Market pricing event earlier than model expects |
| `MARKET_NOT_PRICING_EVENT` | Model sees event, market doesn't price it |
| `BLIND_SPOT` | Persistent unresolved disagreement (streak tracked) |

## Environment

- WSL2 Ubuntu, Python 3.12
- All reads are file-based — no commands to run
- This is a read-only agent: no write scope, no artifact output
