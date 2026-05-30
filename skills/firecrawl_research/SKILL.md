# Firecrawl Research Discovery Skill

## Purpose

Research-only web news discovery for biotech screener operators and agents. Uses Firecrawl SDK v2 to search and scrape external sources. **No ranker, selector, or scoring inputs.**

## Activation

Use when:

- Running daily biotech news discovery (`cron_data_refresh.sh firecrawl`)
- Enriching intraday mover digests with external news context (HIGH moves only)
- Manual competitor or catalyst research

## Configuration

| Variable | Required | Notes |
| --- | --- | --- |
| `FIRECRAWL_API_KEY` | Yes (for live runs) | From [firecrawl.dev](https://firecrawl.dev); set in repo `.env` |

Add to `.env` (see `.env.example`). Cron scripts `source .env` on WSL; Python tools call `common.repo_env.load_repo_dotenv()`.

**SDK:** `firecrawl-py==4.28.2` · `from firecrawl import Firecrawl`

## Commands

```bash
# Daily research (cron / manual)
bash tools/cron_data_refresh.sh firecrawl

# Direct ingest
python tools/firecrawl_research_ingest.py \
  --query "biotech clinical trial FDA approval" \
  --limit 15 \
  --out artifacts/research/firecrawl/$(date +%F)

# EOD intraday digest enrichment (also runs after digest via cron_intraday_mover.sh)
python tools/enrich_intraday_digest_with_research.py --date YYYY-MM-DD
```

## Cron wiring (operator WSL)

| Job | Script | Firecrawl |
| --- | --- | --- |
| Data refresh 8 AM ET | `tools/cron_data_refresh.sh` (`firecrawl` / `all`) | Daily search + scrape |
| Intraday EOD digest | `tools/cron_intraday_mover.sh digest` | Optional enrich if key set |

Schedule for data refresh is in `cron_data_refresh.sh` header comments; intraday digest at **16:15 ET** per `cron_intraday_mover.sh`.

## Output paths

| Artifact | Path |
| --- | --- |
| Daily research | `artifacts/research/firecrawl/YYYY-MM-DD/` |
| Enriched digest | `artifacts/intraday_mover_watch/YYYY-MM-DD_digest_enriched.json` |

## Governance

- Research-only; `_metadata.json` on every ingest run
- Graceful skip when `FIRECRAWL_API_KEY` unset
- Cloud VMs without operator `.env` skip Firecrawl stages (expected)

## References

- `docs/firecrawl_research_integration.md`
- `docs/firecrawl_agent_integration.md`
- `tools/firecrawl_research_ingest.py`
