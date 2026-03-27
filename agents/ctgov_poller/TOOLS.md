# TOOLS.md — CTgov Daily Poller Agent

## Production builder

```bash
# Full poll (all universe tickers, ~5-10 min)
python tools/poll_ctgov_daily.py

# Quick test (5 tickers)
python tools/poll_ctgov_daily.py --max-tickers 5

# Diff-only mode (no API calls, compare two cache versions)
python tools/poll_ctgov_daily.py --cached-only
```

## Data sources

### CT.gov API v2
- Endpoint: `https://clinicaltrials.gov/api/v2/studies`
- Query: `query.spons={sponsor_name}` per ticker
- Rate limit: 200ms between requests (5 req/sec)
- Fields: nctId, overallStatus, phases, primaryCompletionDate, lastUpdatePosted, enrollment, resultsFirstPostDate

### Local cache (read-only)
- `cache/ctgov/trial_records_{date}.json` — latest PIT-filtered snapshot
- `production_data/universe.json` — ticker list
- `collect_ctgov_data.py:TICKER_TO_SPONSORS` — ticker → sponsor name mapping

## Output

```
artifacts/ctgov_daily/
  {date}_diff.json    — structured diff with change codes
  {date}_diff.md      — human-readable summary
```

## Change codes

| Code | Meaning | Significance |
|------|---------|-------------|
| PHASE_ADVANCEMENT | Phase 2→3 etc. | High — pipeline advancement |
| PHASE_REGRESSION | Phase downgraded | High — protocol amendment |
| TRIAL_TERMINATED | Terminated/withdrawn/suspended | High — failure signal |
| TRIAL_COMPLETED | Status → COMPLETED | Medium — readout imminent |
| BECAME_ACTIVE | Started recruiting | Medium — program alive |
| BECAME_INACTIVE | Stopped recruiting | Low-medium |
| PCD_SHIFTED | Primary completion date moved >=14d | Medium — timeline change |
| RESULTS_POSTED | First results appeared | High — data available |
| NEW_TRIAL | Not in cache at all | Medium — new program |
| STATUS_CHANGED | Other status change | Low |

## Schedule

- Daily, after market close (could run in parallel with production pipeline)
- Or as OpenClaw agent on its own cron schedule
- Full poll: ~300 tickers × 200ms = ~60 seconds minimum
