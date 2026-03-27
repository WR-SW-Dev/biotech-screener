# TOOLS.md — Shadow Monitor Agent

## Data sources (read-only)

### Performance history
- `artifacts/live_shadow/performance.csv` — daily P&L, excess vs XBI, sleeve attribution
- `artifacts/live_shadow/portfolio_report.md` — cumulative summary

### Position context
- `artifacts/live_shadow/positions/{date}.json` — current positions with entry prices
- `production_data/price_history.csv` — for computing position-level returns

### Readiness
- `artifacts/readiness/scorecard_{date}.json` — daily scorecard with checks/verdict

### Prior monitor
- `artifacts/shadow_monitor/{prior_date}_monitor.json` — for trend comparison

## Production builder

The core logic is implemented in `tools/build_shadow_monitor.py`:

```bash
python tools/build_shadow_monitor.py --as-of-date 2026-03-27
```

This runs automatically in the daily production pipeline (step 5k.6).
The agent's role is to interpret the builder's output, not duplicate its logic.

## Output location

```
artifacts/shadow_monitor/
  {date}_monitor.json    — structured monitor (schema shadow_monitor.v1)
  {date}_monitor.md      — human-readable briefing
```

## Alert codes

| Code | Trigger | Level |
|------|---------|-------|
| DRAWDOWN_STREAK | 3+ consecutive losing days | WARN/ALERT |
| SINGLE_DAY_LOSS | >2% single-day loss | WARN/ALERT |
| EXCESS_DETERIORATION | Cumulative excess < -3% | WARN/ALERT |
| MAX_DRAWDOWN | >8% max drawdown | WARN/ALERT |
| SLEEVE_CONCENTRATION | One sleeve >60% of total loss | WARN |
| SCORECARD_FAIL | Readiness check failed | WARN |

## Environment

- WSL2 Ubuntu, Python 3.12
- All reads are file-based — no API calls
- Schedule: after production pipeline completes (step 5k.6)
