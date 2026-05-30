# AGENTS.md — Company News Ingest Agent

## Upstream

- None (this is a source-of-truth collector)

## Downstream consumers

- `tools/classify_press_releases.py` — Grok/local classification
- `tools/catalyst_resolution_tracker.py` — CRT intake for resolution candidates
- Dashboard — company news panel
- `common/news_feed_features.py` — ticker-level rolling features

## Peer agents

- `grok_biotech_watch` — discovery/search lane (complements, does not replace this agent)
- `catalyst_delta` — detects event changes from pipeline data (different source)
