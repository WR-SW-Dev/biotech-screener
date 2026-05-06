# Grok Biotech Watch — Classifier Tuning Follow-up

**Created:** 2026-05-06
**Trigger:** ROI audit after reducing cadence to 1x daily (16:00 ET)
**Status:** DEFERRED — do not act until 10-trading-day observation window closes

---

## Findings from ROI Audit (2026-05-06)

### Alert rate is 100% of watchlist

Both substantive runs (2026-03-31 and 2026-05-06) produced alerts for **all 40 watchlist
names** — 131 and 134 alerts respectively. A signal that fires on 100% of names on every
run is not a signal; it is a catalog.

### official_confirmation is too permissive

65 of 134 alerts on 2026-05-06 carried `official_confirmation=True`. Inspection of sources
shows these include evergreen FDA.gov pages, ClinicalTrials.gov entries, and IR pages that
are not date-bounded. A topline result from 2024 filing under the same ticker will still
trigger the classifier.

### Dedup window is intra-day only (4 hours)

`DEDUP_WINDOW_HOURS = 4` in `build_grok_biotech_watch.py`. The same evergreen content
recurs across daily runs and across the 07:00/12:00/15:00 slots. This amplified apparent
alert volume without adding new information.

---

## Required Changes (when observation window closes)

**Do not implement until 10-trading-day window is complete and reviewed.**

### 1. Time-window Grok search results to last 48h

In `search_grok()`, pass a date filter in the query or add a post-filter that discards
results where the `date` field is older than 48 hours. The Grok API's `search.mode: auto`
surfaces both fresh and archived content; the caller must filter.

```python
# Proposed filter in search_grok() after result normalization:
from datetime import datetime, timezone, timedelta
cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
results = [
    r for r in results
    if not r.get("date") or _parse_date(r["date"]) >= cutoff
]
```

### 2. Tighten official_confirmation to require fresh dated sources

The current classifier (`classify_severity`) marks `official_confirmation=True` if the
source domain matches a whitelist (fda.gov, SEC, company IR). This does not verify
recency. Require that `official_confirmation` only applies when:
- Source is official AND
- Result date is within the last 48h

### 3. Extend dedup window to cross-day (7 days minimum)

Change `DEDUP_WINDOW_HOURS = 4` to `DEDUP_WINDOW_HOURS = 168` (7 days) or move to
date-keyed dedup so the same topic hash is not re-surfaced across daily runs.

### 4. Add severity calibration test

After implementing the above, run against the 2026-03-31 and 2026-05-06 artifacts
and verify:
- HIGH alert rate drops below 50% of watchlist names
- official_confirmation alerts are verifiably dated within 48h
- Dedup suppresses known-repeated items

---

## Observation Window: What to Track (2026-05-07 – 2026-05-20, ~10 trading days)

For each 16:00 run, record:

| Date | Alert count | Unique tickers | Official-confirmed | Any manual action? |
|------|-------------|----------------|-------------------|-------------------|
| ...  | ...         | ...            | ...               | ...               |

Check: does alert count stabilize below 40 tickers/run? If still 40/40 after 10 days,
classifier tuning is required before any re-expansion of cadence.

---

## Not in Scope (do not implement without new operator decision)

- Review queue wiring
- Downstream consumer changes
- Production scoring changes
- Herald/news digest overlap deduplification
- Re-expansion to 2x or 3x daily cadence
