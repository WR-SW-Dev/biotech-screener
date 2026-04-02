# TOOLS.md — Biotech News Digest Agent

## Generate and send digest

```bash
cd /mnt/c/Projects/biotech_screener/biotech-screener
source .env 2>/dev/null
python3 scripts/build_news_digest.py --window morning
python3 scripts/build_news_digest.py --window midday
python3 scripts/build_news_digest.py --window evening
```

## Windows

- `morning` (08:00): last market close (16:00 prior day) → now
- `midday` (15:00): 08:00 → now
- `evening` (18:00): 15:00 → now

## Data sources

- `data/press_releases/releases_YYYY-MM-DD.jsonl` — raw Herald output
- `data/press_releases/classified/*.json` — Grok-classified releases
- `production_data/universe.json` — followed tickers
- `artifacts/grok_watch/` — optional xAI enrichment

## Artifacts

```
artifacts/news_digest/
  biotech_news_digest_YYYY-MM-DD_0800.html
  biotech_news_digest_YYYY-MM-DD_0800.txt
  biotech_news_digest_YYYY-MM-DD_0800.json
  delivery_log.jsonl
```

## Email config (from .env)

- SMTP_USER=djschulz@gmail.com
- SMTP_PASSWORD=(app password)
- ALERT_RECIPIENT=dschulz@wakerobin.co

## Cadence

- 3x daily weekdays: 08:00, 15:00, 18:00 ET
