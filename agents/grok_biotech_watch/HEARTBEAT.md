# HEARTBEAT.md — Grok Biotech Watch

## Checks

1. xAI API credentials present (XAI_API_KEY)
2. Latest alert artifact exists for today (or SKIP if market closed)
3. Dedup state file exists and is not corrupt
4. Email credentials present (WARN if missing, not FAIL)

## Response

- All checks pass → `HEARTBEAT_OK`
- Missing xAI credentials → `FAIL: no XAI_API_KEY`
- Missing email credentials → `WARN: email disabled, artifacts still written`
- API rate limited → `WARN: rate limited, will retry next cycle`
