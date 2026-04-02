# TOOLS.md — Earnings Calendar Sync Agent

## Stage 1: Fetch earnings

```bash
cd /mnt/c/Projects/biotech_screener/biotech-screener
python3 scripts/fetch_earnings_calendar.py \
  --symbols-file production_data/universe.json \
  --start YYYY-MM-DD \
  --end YYYY-MM-DD \
  --output artifacts/earnings_sync/earnings_raw_YYYY-MM-DD.json
```

Output: `artifacts/earnings_sync/earnings_raw_YYYY-MM-DD.json` (schema: `earnings_raw.v1`)

## Stage 2: Generate ICS

```bash
python3 scripts/sync_earnings_to_outlook.py \
  --raw-file artifacts/earnings_sync/earnings_raw_YYYY-MM-DD.json \
  --ics-out artifacts/earnings_sync/biotech_earnings.ics \
  --timezone US/Eastern
```

Output:
- `artifacts/earnings_sync/biotech_earnings.ics` — subscribable calendar file
- `artifacts/earnings_sync/earnings_normalized_YYYY-MM-DD.json`

## Full pipeline (both stages)

```bash
cd /mnt/c/Projects/biotech_screener/biotech-screener
TODAY=$(date +%Y-%m-%d)
END=$(date -d "+60 days" +%Y-%m-%d)
python3 scripts/fetch_earnings_calendar.py \
  --symbols-file production_data/universe.json \
  --start "$TODAY" --end "$END" \
  --output "artifacts/earnings_sync/earnings_raw_${TODAY}.json"
python3 scripts/sync_earnings_to_outlook.py \
  --raw-file "artifacts/earnings_sync/earnings_raw_${TODAY}.json" \
  --ics-out artifacts/earnings_sync/biotech_earnings.ics \
  --timezone US/Eastern
```

## Data sources (read-only)

- `production_data/universe.json` — symbol universe (341 tickers)

## Artifacts

```
artifacts/earnings_sync/
  biotech_earnings.ics                 — ICS file for Outlook subscription
  earnings_raw_YYYY-MM-DD.json         — raw yfinance output
  earnings_normalized_YYYY-MM-DD.json  — normalized event schema
```

## Outlook subscription

1. Open Outlook (desktop or web)
2. Add calendar > Subscribe from file / URL
3. Point to `biotech_earnings.ics` (local path or file share)
4. Outlook refreshes on its sync interval; each Bellringer run overwrites
   the .ics with current data, and stable UIDs ensure updates not duplicates

## Cadence

- Daily on weekdays (after market data settles)
- Each run overwrites the .ics — Outlook picks up changes on next refresh
