# TOOLS.md — Intraday Mover Watch Agent

## Production builder

```bash
# Dry-run poll artifact (safe without credentials)
python tools/build_intraday_mover_watch.py --as-of-ts 2026-04-17T14:30:00Z

# End-of-day digest rollup
python tools/build_intraday_mover_watch.py --as-of-date 2026-04-17 --digest-only

# Live mode (requires Alpaca credentials)
python tools/build_intraday_mover_watch.py --as-of-ts 2026-04-17T14:30:00Z --send-email
```

Phases 1 + 1.5 + 2 + 3 complete. Cron wrapper: `tools/cron_intraday_mover.sh`. Registration is manual (crontab -e) — see the script header for the recommended conservative first-week entries.

## Alert codes

| Code | Trigger | Level |
|---|---|---|
| INTRADAY_ABS_MOVE_UP_HIGH | intraday abs ≥ +10% | High |
| INTRADAY_ABS_MOVE_UP_MEDIUM | intraday abs ≥ +5% | Medium |
| INTRADAY_ABS_MOVE_DOWN_HIGH | intraday abs ≤ -10% | High |
| INTRADAY_ABS_MOVE_DOWN_MEDIUM | intraday abs ≤ -5% | Medium |
| INTRADAY_REL_MOVE_UP_HIGH | vs XBI ≥ +7pp | High |
| INTRADAY_REL_MOVE_UP_MEDIUM | vs XBI ≥ +4pp | Medium |
| INTRADAY_REL_MOVE_DOWN_HIGH | vs XBI ≤ -7pp | High |
| INTRADAY_REL_MOVE_DOWN_MEDIUM | vs XBI ≤ -4pp | Medium |
| INTRADAY_RVOL_SPIKE | volume / 20d avg ≥ 2.5× (requires real volume) | Medium |
| INTRADAY_MOVE_WITH_OFFICIAL_NEWS | Herald classified/raw same-day hit | Context |
| INTRADAY_MOVE_WITH_SUPPORTING_NEWS | Grok watch same-day hit only | Context |
| INTRADAY_MOVE_NO_OFFICIAL_NEWS | triggered but no same-day source | Context |

## Data sources

- Intraday quotes: Alpaca Basic REST snapshots (15-min delayed) via `common.realtime_quote_client.AlpacaQuoteClient`
- Watchlist: `common.watchlist_config.build_model_relevant_watchlist` (shared with `price_action_watch` target)
- Same-day news: `artifacts/herald/classified/{date}.json` → `artifacts/herald/raw/{date}.json` → `artifacts/grok_biotech_watch/{date}_watch.json`
- Benchmark: XBI (fetched every poll, not part of watchlist)

## Environment

| Var | Role | Required |
|---|---|---|
| APCA_API_KEY_ID | Alpaca API key (primary production credential) | Yes for live mode |
| APCA_API_SECRET_KEY | Alpaca API secret | Yes for live mode |
| APCA_API_DATA_URL | Override Alpaca data base URL | No |
| MASSIVE_API_KEY | Optional paid-upgrade credential (Polygon/Massive) | No |
| POLYGON_API_KEY | Alias for MASSIVE_API_KEY | No |
| BIOTECH_INTRADAY_REALTIME_TIER | Legacy gate for Polygon/Massive path only | No |
| BIOTECH_INTRADAY_DEV_FALLBACK | `1` to allow yfinance for local tests | No |
| BIOTECH_INTRADAY_POLL_MINUTES | Advisory poll cadence (default 15) | No |
| SMTP_* | Reused from Herald/Grok (Phase 2+) | For email send |
| ALERT_EMAIL_TO | Recipient (reused from Herald) | For email send |

## Provider selection order

1. `APCA_API_KEY_ID` + `APCA_API_SECRET_KEY` → `AlpacaQuoteClient`
2. `MASSIVE_API_KEY` / `POLYGON_API_KEY` → `PolygonMassiveQuoteClient` (paid-upgrade path)
3. `BIOTECH_INTRADAY_DEV_FALLBACK=1` → `DevFallbackQuoteClient` (yfinance, local only)
4. else → `NullQuoteClient`

## Output

```
artifacts/intraday_mover_watch/
  {YYYY-MM-DD}T{HH-MM-SS}Z_poll.json
  {date}_digest.json
  {date}_digest.md
  sent_alerts.json                # persistent dedupe state (Phase 3)
```

## Cron (Phase 3)

Wrapper: `tools/cron_intraday_mover.sh {poll|digest} [--no-email]`
- Loads `.env`, holds a lockfile, derives the ET trading date, runs one builder invocation.
- `--no-email` is the safe default for manual testing; cron entries pass through the default (email on).

Recommended conservative first-week crontab (upgrade to 15-min core cadence after one clean week):

```
35,50 9 * * 1-5 /mnt/c/Projects/biotech_screener/biotech-screener/tools/cron_intraday_mover.sh poll >> /mnt/c/Projects/biotech_screener/biotech-screener/logs/intraday_mover.log 2>&1
0,30 10-15 * * 1-5 /mnt/c/Projects/biotech_screener/biotech-screener/tools/cron_intraday_mover.sh poll >> /mnt/c/Projects/biotech_screener/biotech-screener/logs/intraday_mover.log 2>&1
15 16 * * 1-5 /mnt/c/Projects/biotech_screener/biotech-screener/tools/cron_intraday_mover.sh digest >> /mnt/c/Projects/biotech_screener/biotech-screener/logs/intraday_mover.log 2>&1
```
