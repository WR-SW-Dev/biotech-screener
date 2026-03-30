# TOOLS.md — Grok Biotech Watch Agent

## Builder

```
python tools/build_grok_biotech_watch.py --as-of-date 2026-03-30
python tools/build_grok_biotech_watch.py --as-of-date 2026-03-30 --send-email
python tools/build_grok_biotech_watch.py --as-of-date 2026-03-30 --digest-only
```

## Data sources (read-only)

### Watchlist construction
- `data/snapshots/{date}/rankings.csv` — tier, rank, catalyst context
- `data/snapshots/{date}/review_queue.csv` — review queue tickers
- `artifacts/live_shadow/positions/{date}.json` — shadow portfolio holdings
- `artifacts/live_shadow/trade_plan/{date}/trade_plan.csv` — trade plan names
- `artifacts/catalyst_delta/{date}_delta.json` — recent catalyst changes

### DEM enrichment
- `data/snapshots/{date}/rankings.csv` — tier_dev, actionable_rank, catalyst_days,
  catalyst_family, is_hard_catalyst, mom_state
- `artifacts/policy_shadow/tier_weighted/{date}_compare.json` — policy status

### External
- xAI Grok API — web search and chat completion endpoints
- Auth: `XAI_API_KEY` environment variable (get from console.x.ai)

## Output location

```
artifacts/grok_watch/
  {date}_alerts.json    — structured alert records
  {date}_alerts.md      — human-readable summary
  dedup_state.json      — rolling dedup state (ticker+topic_hash -> last_alert_ts)
```

## Environment variables

- `XAI_API_KEY` — xAI API key from console.x.ai (required)
- `SMTP_HOST` — email server (default: smtp.gmail.com)
- `SMTP_PORT` — email port (default: 587)
- `SMTP_USER` — sender email address
- `SMTP_PASSWORD` — sender password or app password
- `ALERT_EMAIL_TO` — recipient (default: dschulz@wakerobin.co)
