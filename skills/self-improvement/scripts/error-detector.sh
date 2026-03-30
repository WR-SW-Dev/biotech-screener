#!/bin/bash
# Self-improvement error detector — PostToolUse hook (Bash only)
# Detects non-zero exit codes and suggests logging to .learnings/ERRORS.md.
# WARNING: This script reads CLAUDE_TOOL_OUTPUT. Only enable in trusted environments.

set -euo pipefail

# Only trigger on Bash tool failures
if [ "${CLAUDE_TOOL_NAME:-}" != "Bash" ]; then
  exit 0
fi

EXIT_CODE="${CLAUDE_TOOL_EXIT_CODE:-0}"
if [ "$EXIT_CODE" = "0" ]; then
  exit 0
fi

# Extract first line of error output (redacted)
ERROR_PREVIEW=""
if [ -n "${CLAUDE_TOOL_OUTPUT:-}" ]; then
  ERROR_PREVIEW=$(echo "$CLAUDE_TOOL_OUTPUT" | grep -i "error\|traceback\|exception\|failed" | head -1 | cut -c1-120)
fi

if [ -n "$ERROR_PREVIEW" ]; then
  echo "[self-improvement: command failed (exit $EXIT_CODE). Consider logging to .learnings/ERRORS.md if this is a recurring or non-obvious issue. Preview: $ERROR_PREVIEW]"
fi
