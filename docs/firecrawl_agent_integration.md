# Firecrawl Agent Integration Guide

**SDK:** `firecrawl-py==4.28.2` · v2 `Firecrawl` client (`search`, `scrape`)

## Overview

Firecrawl research-only integrations wired into biotech screener data collection and monitoring agents.

**Governance:** Research-only (no alpha inputs, no ranker/selector features)  
**Status:** Production-ready for daily consumption  
**Agents:** Herald (news discovery), Intraday Mover Watch (move enrichment)

---

## 1. Herald + Firecrawl Daily News Discovery

### Architecture

Herald (company IR + press releases) + Firecrawl (external biotech news) = complete daily news surface.

```
2:00 PM ET (cron_data_refresh.sh)
  ├─ stage_herald() → data/press_releases/releases_{date}.jsonl
  └─ stage_firecrawl() → artifacts/research/firecrawl/{date}/
       ├─ search_results.json (15 biotech sources)
       ├─ analyst_summary.md (digest for human review)
       ├─ source_manifest.json (fetch status + URLs)
       └─ _metadata.json (governance confirmation)

8:00 AM ET (optional second run)
  └─ stage_firecrawl() → artifacts/research/firecrawl/{date}/
       (morning search for overnight global biotech news)
```

### Command Reference

**Standalone search (debug mode):**

```bash
python tools/firecrawl_research_ingest.py \
  --query "obesity clinical trial FDA approval 2026" \
  --limit 15 \
  --skip-scrape \
  --out artifacts/research/firecrawl/$(date +%F)
```

**Via cron_data_refresh.sh:**

```bash
# Run Firecrawl stage only
bash tools/cron_data_refresh.sh firecrawl

# Run entire data refresh (includes Firecrawl)
bash tools/cron_data_refresh.sh all
```

**Environment:**

```bash
# Required for live operation
export FIRECRAWL_API_KEY="fc-..."

# Optional schedule override (default: 2 PM ET)
export FIRECRAWL_SEARCH_TIME="08:00"  # 8 AM ET for morning run
```

### Output Consumption

**Herald digest producer** reads `artifacts/research/firecrawl/{date}/analyst_summary.md` and incorporates external biotech news alongside company IR (optional cross-source enrichment).

**Analyst** reviews digests daily:
- Company IR: `artifacts/news_digest/{date}_digest.md` (Herald output)
- External news: `artifacts/research/firecrawl/{date}/analyst_summary.md` (Firecrawl output)

---

## 2. Intraday Mover Watch + Firecrawl News Enrichment

### Architecture

Intraday Mover Watch (price moves + same-day Herald news) + Firecrawl (additional context search) = rich move diagnosis.

```
Throughout trading day (every 15 min)
  ├─ cron_intraday_mover.sh poll
  │   └─ artifacts/intraday_mover_watch/{timestamp}_poll.json
  │
End of day (4:00 PM ET)
  ├─ cron_intraday_mover.sh digest
  │   └─ artifacts/intraday_mover_watch/{date}_digest.json
  │       └─ HIGH-severity moves flagged
  │
  └─ (optional enrichment)
      python tools/enrich_intraday_digest_with_research.py --date {date}
          └─ artifacts/intraday_mover_watch/{date}_digest_enriched.json
              (digest + Firecrawl news context on HIGH moves)
```

### Command Reference

**Enrich existing digest (post-processing):**

```bash
python tools/enrich_intraday_digest_with_research.py \
  --date 2026-05-27 \
  --digest-file artifacts/intraday_mover_watch/2026-05-27_digest.json

# Output: artifacts/intraday_mover_watch/2026-05-27_digest_enriched.json
```

**Cron integration (add to crontab):**

```bash
# After daily intraday digest is generated
0 16 * * 1-5 cd /mnt/c/Projects/biotech_screener/biotech-screener && \
  python tools/enrich_intraday_digest_with_research.py --date $(date +%F)
```

**Environment:**

```bash
export FIRECRAWL_API_KEY="fc-..."
```

### Output Structure

**Enriched digest additions** (under `_firecrawl_context`):

```json
{
  "alerts": { ... },
  "_firecrawl_context": {
    "enrichment_timestamp": "2026-05-27T16:10:00Z",
    "governance": "research_only_no_alpha",
    "high_moves_enriched": {
      "RVMD": {
        "ticker": "RVMD",
        "move_type": "INTRADAY_ABS_MOVE_UP_HIGH",
        "magnitude_pct": 12.5,
        "enriched_at": "2026-05-27T16:10:00Z",
        "news_sources": [
          {
            "url": "https://...",
            "title": "...",
            "description": "..."
          }
        ]
      }
    }
  }
}
```

### Behavior

1. **Load** intraday digest for the trading day
2. **Find** all HIGH-severity moves (INTRADAY_ABS_MOVE_UP_HIGH, etc.)
3. **Search** Firecrawl for each HIGH-move ticker (max 5 results per ticker)
4. **Append** news sources as enrichment (URLs + titles + descriptions)
5. **Write** enriched digest (research-only artifact, no scoring applied)

**Graceful degradation:**
- If `FIRECRAWL_API_KEY` not set: returns original digest unchanged
- If search fails for a ticker: continues with other tickers
- If Firecrawl times out: returns partially enriched digest

---

## 3. Integration Points (Future)

### Catalyst Discovery Queue (Post-Governance)

After 2+ weeks of research-only validation (Spec 089 KG approval + 13F stability):

**Extract catalyst types** from Firecrawl news:
- Trial result (Phase readout, PDUFA decision, FDA approval)
- Acquisition / partnership announcement
- Leadership change / restructuring
- Regulatory action (warning letter, audit, etc.)

**Tag** with confidence + source URL

**Route** to Spec 063 (Intraday Mover Watch) catalyst-discovery queue for correlation analysis:
- Do Firecrawl discoveries precede intraday moves? (T0, T+1, T+2?)
- How accurate is Firecrawl timing vs market surprise?
- Can we rank catalyst importance?

**Decision gate (2026-06-17):**
- If catalyst accuracy >60% T0-T1: propose Spec 110 extension
- If <40%: keep research-only, defer ranker candidacy to H2 2026
- Hard prerequisite: 13F cohort stability + Spec 089 KG approval

---

## 4. Troubleshooting

### "FIRECRAWL_API_KEY not set"

**Problem:** API key missing from environment  
**Solution:** 
```bash
export FIRECRAWL_API_KEY="fc-..."  # get from .env or secrets manager
```

### Scrape Success Rate Low (20-40%)

**Expected behavior.** Paywalled sites (NEJM, Bloomberg), JS-heavy (academic), and bot-protected (some news sites) deny scraping. Search results still captured.

**Improvement:** Focus on open-access sources (Fierce Biotech, STAT News, BioPharma Dive, BioSpace).

### Timeout Errors

**Problem:** Firecrawl request exceeded 180s limit  
**Solution:** 
- Check network / Firecrawl API status
- Reduce `--limit` parameter (default 15)
- Increase `--timeout` limit if scraping complex sites

### No Enrichment in Intraday Digest

**Problem:** `_firecrawl_context` missing from enriched digest  
**Cause:** No HIGH-severity moves in digest (or Firecrawl had no results)  
**Expected:** Keep enrichment-optional; original digest is always valid

---

## 5. Governance Checklist

Every Firecrawl output artifact MUST be:

- [ ] **Research-only:** No features extracted for ranker/selector
- [ ] **Source-tracked:** Every URL recorded with timestamp
- [ ] **Governance-tagged:** `_metadata.json` confirms constraints
- [ ] **Analyst-consumable:** Digest markdown for human review
- [ ] **Fail-graceful:** Missing API key, timeouts → continue safely

---

## 6. Skill Invocation (Hermes Agents)

If running inside a Hermes agent session:

```bash
/skill firecrawl-research-discovery
# → prompts for search query, limit, output directory
```

Or preload at session start:

```bash
hermes -s firecrawl-research-discovery
```

See `~/.hermes/skills/biotech-screener/firecrawl-research-discovery/` for full documentation.

---

## 7. Related Docs

- `docs/firecrawl_research_integration.md` — Firecrawl tool architecture + next steps
- `tools/firecrawl_research_ingest.py` — Main search/scrape implementation
- `tools/enrich_intraday_digest_with_research.py` — Intraday enrichment logic
- `tools/cron_data_refresh.sh` — Daily data refresh orchestrator
- `agents/herald/SOUL.md` — Herald agent capabilities
- `agents/intraday_mover_watch/SOUL.md` — Intraday Mover Watch capabilities
