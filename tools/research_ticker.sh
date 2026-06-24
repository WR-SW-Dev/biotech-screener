#!/usr/bin/env bash
# Manual-only ticker deep dive via Hermes Tool Gateway web search/extract.
# Usage: ./tools/research_ticker.sh TICKER [INDICATION]
# Example: ./tools/research_ticker.sh RVMD "RAS oncology"
#
# Constraints: read-only, no git, no pipeline writes, no cron.
# Output: artifacts/research_notes/YYYY-MM-DD/TICKER_deep_dive.md

set -euo pipefail

TICKER="${1:-}"
INDICATION="${2:-}"

if [[ -z "$TICKER" ]]; then
    echo "Usage: $0 TICKER [INDICATION]"
    echo "Example: $0 RVMD 'RAS oncology'"
    exit 1
fi

TODAY=$(date +%Y-%m-%d)
OUTDIR="artifacts/research_notes/${TODAY}"
OUTFILE="${OUTDIR}/${TICKER}_deep_dive.md"

cd "$(dirname "$0")/.."

echo ">>> Research: $TICKER | date=$TODAY | output=$OUTFILE"

hermes chat -q "$(cat <<PROMPT
You are a read-only biotech research assistant. Your ONLY allowed write action is saving the output file described below.

HARD CONSTRAINTS — violating any of these is a critical error:
- No git commands (no add, commit, push, status, log)
- No edits to any pipeline file (*.py, *.json config, *.yml, requirements*)
- No writes outside artifacts/research_notes/
- No cron scheduling
- No browser automation
- No trading or order actions

TASK: Deep dive on $TICKER${INDICATION:+ ($INDICATION)}.

SEARCH SEQUENCE (use web search & extract):
1. SEC EDGAR 8-K filings: search "site:sec.gov $TICKER 8-K" — pull the 3 most recent press releases with clinical or corporate events
2. ClinicalTrials.gov: search "$TICKER clinical trials" — identify all active/completed Phase 2+ trials, note primary endpoints and estimated completion dates
3. BioPharma Dive + STAT News + Fierce Biotech: search "$TICKER" news last 90 days — pull headline + one-sentence summary for each relevant article
4. Company IR: if you can find the IR page, check for recent pipeline updates or investor presentations

REQUIRED OUTPUT FORMAT (markdown, save to $OUTFILE):
---
ticker: $TICKER
indication: ${INDICATION:-unknown}
generated: $TODAY
governance: READ_ONLY_RESEARCH | NO_ALPHA_INPUTS | NO_PIPELINE_WRITES
---

# $TICKER Deep Dive — $TODAY

## Summary
(2–3 sentences: what company does, current clinical stage, most important near-term event)

## Pipeline
| Drug | Indication | Stage | Status | Key Endpoint | Est. Readout |
|------|-----------|-------|--------|-------------|--------------|
(one row per program)

## Recent Catalysts (last 90 days)
| Date | Event | Source | Significance |
|------|-------|--------|-------------|
(press releases, data readouts, regulatory actions, corporate events)

## Upcoming Catalysts (next 6 months)
| Est. Date | Event | Confidence |
|-----------|-------|-----------|
(trial readouts, PDUFA dates, conferences, analyst days)

## Key Risks
- (bullet list: clinical, regulatory, financial, competitive)

## Competitive Context
(2–4 sentences: who else is in this space, how does $TICKER differentiate)

## Sources
| URL | Date | Relevance |
|-----|------|----------|
(all sources consulted, including misses)

FINAL STEP: Write the completed note to $OUTFILE. Print "DONE: $OUTFILE" when complete.
PROMPT
)"
