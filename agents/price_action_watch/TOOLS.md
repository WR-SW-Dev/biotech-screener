# TOOLS.md — Price Action Watch Agent

## Production builder

```bash
python tools/build_price_action_watch.py --as-of-date 2026-03-27
```

Runs in daily production pipeline at step 5k.5c.

## Alert codes

| Code | Trigger | Level |
|------|---------|-------|
| STOCK_BIG_MOVE_UP | 1d return >= +10% | High |
| STOCK_MOVE_UP | 1d return >= +5% | Medium |
| STOCK_BIG_MOVE_DOWN | 1d return <= -10% | High |
| STOCK_MOVE_DOWN | 1d return <= -5% | Medium |
| MOVE_INTENSITY_SPIKE | 1d |return| >= 2.5x trailing 20d avg (proxy for RVOL; real volume v2) | Medium |
| IV_RAMP_HIGH | atm_iv_change_5d >= +0.10 | Medium |
| IV_CRUSH | atm_iv_change_5d <= -0.10 | Medium |
| OPTIONS_SURFACE_MOVE_HIGH | actual_implied_move_pctile >= 0.80 | Medium |
| SKEW_EXTREME | |opt_rr_25d| >= 0.40 | Low |
| STOCK_DOWN_IV_UP | Stock -3%+ with IV +5%+ | High |
| STOCK_UP_IV_DOWN | Stock +3%+ with IV -5%+ | Medium |

## Data sources

- `production_data/price_history.csv` — stock prices
- `data/snapshots/{date}/rankings.csv` — options metrics
- Watchlist: review queue + trade plan + shadow positions + catalyst delta + A-tier <=30d

## Output

```
artifacts/price_action_watch/
  {date}_watch.json
  {date}_watch.md
```
