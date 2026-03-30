#!/bin/bash
# Self-improvement activator — UserPromptSubmit hook
# Injects a brief reminder to log learnings when appropriate.
# Reads user message from stdin, emits reminder to stdout.

set -euo pipefail

LEARNINGS_DIR="$(cd "$(dirname "$0")/../../.." && pwd)/.learnings"

# Count pending items
PENDING=0
if [ -d "$LEARNINGS_DIR" ]; then
  PENDING=$(grep -rh 'Status\*\*: pending' "$LEARNINGS_DIR"/*.md 2>/dev/null | wc -l || echo 0)
fi

# Only inject reminder if there are pending learnings
if [ "$PENDING" -gt 0 ]; then
  echo "[self-improvement: $PENDING pending learnings in .learnings/. If you notice errors, corrections, or improvement opportunities during this task, append to the appropriate .learnings/*.md file.]"
fi
