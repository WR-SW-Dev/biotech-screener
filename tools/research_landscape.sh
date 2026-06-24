#!/usr/bin/env bash
# Manual-only thematic landscape sweep via Hermes Tool Gateway web search/extract.
# Usage: ./tools/research_landscape.sh "THEME" [SLUG]
# Example: ./tools/research_landscape.sh "RAS oncology small molecule" "ras_oncology"
# Example: ./tools/research_landscape.sh "KRAS G12C inhibitors" "kras_g12c"
#
# SLUG defaults to a lowercased, underscored version of THEME if not provided.
# Constraints: read-only, no git, no pipeline writes, no cron.
# Output: artifacts/research_notes/YYYY-MM-DD/SLUG_landscape.md

set -euo pipefail

THEME="${1:-}"
SLUG="${2:-}"

if [[ -z "$THEME" ]]; then
    echo "Usage: $0 \"THEME\" [SLUG]"
    echo "Example: $0 \"RAS oncology\" \"ras_oncology\""
    exit 1
fi

# Auto-generate slug if not provided
if [[ -z "$SLUG" ]]; then
    SLUG=$(echo "$THEME" | tr '[:upper:]' '[:lower:]' | tr ' /' '_' | tr -cd 'a-z0-9_')
fi

TODAY=$(date +%Y-%m-%d)
OUTDIR="artifacts/research_notes/${TODAY}"
OUTFILE="${OUTDIR}/${SLUG}_landscape.md"

cd "$(dirname "$0")/.."

echo ">>> Landscape: \"$THEME\" | slug=$SLUG | date=$TODAY | output=$OUTFILE"

hermes chat -q "$(cat <<PROMPT
You are a read-only biotech research assistant. Your ONLY allowed write action is saving the output file described below.

HARD CONSTRAINTS — violating any of these is a critical error:
- No git commands (no add, commit, push, status, log)
- No edits to any pipeline file (*.py, *.json config, *.yml, requirements*)
- No writes outside artifacts/research_notes/
- No cron scheduling
- No browser automation
- No trading or order actions

TASK: Competitive landscape sweep for the "$THEME" space as of $TODAY.

SEARCH SEQUENCE (use web search & extract):
1. Recent clinical data: search "$THEME clinical trial results 2025 2026" — pull key readouts, response rates, endpoints
2. Competitive field: search "$THEME companies pipeline" — identify all active clinical-stage programs (Ph1+), organized by company
3. News coverage: search "$THEME" on BioPharma Dive, STAT News, Fierce Biotech — last 90 days
4. Upcoming events: search "$THEME ASCO ESMO ASH AACR 2026 conference" — any presentations or abstracts expected
5. White space: note any disease subtype, mechanism, or patient segment with no current coverage

REQUIRED OUTPUT FORMAT (markdown, save to $OUTFILE):
---
theme: $THEME
slug: $SLUG
generated: $TODAY
governance: READ_ONLY_RESEARCH | NO_ALPHA_INPUTS | NO_PIPELINE_WRITES
---

# $THEME — Landscape Sweep $TODAY

## Executive Summary
(4–6 sentences: current competitive state, leading programs, key differentiators, what's driving activity)

## Key Players
| Company | Ticker | Drug | Mechanism | Stage | Latest Update |
|---------|--------|------|-----------|-------|--------------|
(one row per active clinical program; include private co's if known)

## Recent Data Readouts (last 90 days)
| Date | Company | Drug | Data | Significance |
|------|---------|------|------|-------------|

## Upcoming Catalysts (next 6 months)
| Est. Date | Company | Drug | Event | Confidence |
|-----------|---------|------|-------|-----------|

## Competitive Differentiation
(Brief table or bullets: how leading programs differ on efficacy, safety, dosing, patient population)

## White Space / Gaps
(2–4 bullets: disease subsets, mechanisms, patient segments with no current coverage or weak coverage)

## Screening Universe Overlap
List any tickers from this landscape that appear in a small-cap biotech screener context (sub-\$5B market cap, US-listed). Flag if any are notable absences.

## Sources
| URL | Date | Relevance |
|-----|------|----------|

FINAL STEP: Write the completed note to $OUTFILE. Print "DONE: $OUTFILE" when complete.
PROMPT
)"
