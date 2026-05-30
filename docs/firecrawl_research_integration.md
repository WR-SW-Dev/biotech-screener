# Firecrawl Research Integration

**SDK:** `firecrawl-py==4.28.2` (v2 client: `from firecrawl import Firecrawl`)

## Overview

Firecrawl research-only adapter for biotech news discovery and competitor intelligence gathering. This tool enables agents to search and scrape web content for research purposes **only** — no features are extracted for the ranker, selector, or alpha stack.

## Governance

**RESEARCH_ONLY = true** — enforced at all levels:

```python
RESEARCH_ONLY = True
NO_MODEL_FEATURES = True
NO_RANKER_INPUTS = True
NO_SELECTOR_INPUTS = True
SOURCE_URL_REQUIRED = True
FETCH_TIMESTAMP_REQUIRED = True
```

Every artifact is tagged with governance metadata (`_metadata.json`) confirming research-only status. This prevents accidental wiring into production scoring.

## Usage

### CLI

Basic search:

```bash
python tools/firecrawl_research_ingest.py \
  --query "biotech clinical trial results" \
  --limit 20 \
  --out artifacts/research/firecrawl/$(date +%F)
```

Search + scrape:

```bash
python tools/firecrawl_research_ingest.py \
  --query "Novo Nordisk obesity drug" \
  --limit 10 \
  --timeout 30 \
  --out artifacts/research/firecrawl/novo_analysis
```

Debug (search only, no scraping):

```bash
python tools/firecrawl_research_ingest.py \
  --query "GLP-1 receptor agonist" \
  --limit 5 \
  --skip-scrape \
  --out artifacts/research/firecrawl/debug
```

### Python SDK

```python
from tools.firecrawl_research_ingest import FirecrawlResearchAdapter

# Requires: pip install firecrawl-py (pinned in requirements.txt)
adapter = FirecrawlResearchAdapter(api_key="fc-...")

# Search
results = adapter.search("obesity gene therapy", limit=20)

# Scrape URLs
adapter.scrape_urls([r.url for r in results])

# Write artifacts
artifacts = adapter.write_artifacts("artifacts/research/firecrawl/2026-05-27")
```

## Output Structure

```
artifacts/research/firecrawl/YYYY-MM-DD/
├── _metadata.json           # Governance constraints + fetch stats
├── search_results.json      # Raw search output (URLs, titles, descriptions)
├── source_manifest.json     # Fetch status per URL (success/failed, timestamps)
├── analyst_summary.md       # High-level digest (titles + summaries)
└── scraped_pages.md         # Markdown-cleaned content per URL
```

### _metadata.json Example

```json
{
  "research_only": true,
  "no_model_features": true,
  "no_ranker_inputs": true,
  "no_selector_inputs": true,
  "source_url_required": true,
  "fetch_timestamp_required": true,
  "generated_at": "2026-05-27T15:10:14.898285+00:00",
  "total_sources": 15,
  "successful_scrapes": 12,
  "failed_scrapes": 3
}
```

## API Key Setup

Export `FIRECRAWL_API_KEY` env var:

```bash
export FIRECRAWL_API_KEY="fc-..."
python tools/firecrawl_research_ingest.py --query "..." --out artifacts/research/firecrawl/test
```

Or pass via CLI:

```bash
python tools/firecrawl_research_ingest.py \
  --query "..." \
  --api-key "fc-..." \
  --out artifacts/research/firecrawl/test
```

## Integration with Hermes Agents

To use Firecrawl as a **catalyst-discovery queue** or **research tool** in Hermes:

1. **Discovery Lane** (Layer B): Run periodic searches for biotech keywords
   ```python
   # In a Hermes skill:
   adapter = FirecrawlResearchAdapter()
   results = adapter.search("obesity trial results", limit=20)
   # Log to artifacts/research/firecrawl/$(date +%F)/ for analysts
   ```

2. **Analyst Digest** (Layer C): Consume research artifacts daily
   ```python
   # In post-analysis supervisor:
   for date_dir in artifacts/research/firecrawl/*/
       digest = read(date_dir / "analyst_summary.md")
       # Feed to manual intelligence queue, not ranker
   ```

3. **Future: Catalyst Tagging** (when governance allows)
   - Extract specific catalyst types (trial, acquisition, leadership change)
   - Tag with confidence and source URL
   - Route to Spec 063 (Intraday Mover Watch) for correlation analysis
   - **Still research-only:** no direct scoring

## Known Limitations

- Some sites deny scraping (paywalls, JS-heavy, bot-protection) → logged as `failed` in manifest
- Timeout minimum: 1000ms (enforced by Firecrawl API)
- Search covers web, news, images depending on Firecrawl index freshness
- No rate-limiting on user side (respect API quotas)

## Success Criteria

- ✅ Searches return URLs, titles, descriptions
- ✅ Scrapes return markdown content or fail gracefully
- ✅ All artifacts tagged with governance metadata
- ✅ No features extracted for ranker/selector
- ✅ Source URLs and timestamps required on all records
- ✅ Analyst can consume daily digests without touching code

## Next Steps (Post-Validation)

After 2+ weeks of daily research-only operation, evaluate:

1. **Catalyst extraction**: Can we tag trial results, acquisitions, leadership changes?
2. **Intraday correlation**: Do Firecrawl discoveries precede Spec 063 movers?
3. **Ranker candidacy**: Should any clean signals feed a future gate/feature?

**Gate:** Spec 089 KG governance approval + 13F cohort stability + h20d decision all required.
