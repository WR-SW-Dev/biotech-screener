# TOOLS.md — Company News Ingest Agent

## Builder scripts

```
# Fetch press releases for all tickers
python tools/fetch_company_press_releases.py --as-of-date 2026-03-31

# Fetch single ticker
python tools/fetch_company_press_releases.py --ticker CELC --as-of-date 2026-03-31

# Health check only
python tools/fetch_company_press_releases.py --health-check

# Classify fetched releases (local keywords)
python tools/classify_press_releases.py --input data/press_releases/releases_2026-03-31.jsonl

# Classify with Grok (requires XAI_API_KEY)
python tools/classify_press_releases.py --input data/press_releases/releases_2026-03-31.jsonl --use-grok
```

## Data sources (read-only)

- `production_data/company_ir_sources.json` — source registry (341 tickers)
- Company IR pages (per ticker)
- GlobeNewswire search (backup per ticker)

## Output locations

```
data/press_releases/
  releases_{date}.jsonl          — raw PR records
  fetch_state.json               — cursor/dedup state
  classified/
    classified_{date}.jsonl      — Grok/local classified records
```

## Environment variables

- `XAI_API_KEY` — xAI API key (optional, for Grok classification)
