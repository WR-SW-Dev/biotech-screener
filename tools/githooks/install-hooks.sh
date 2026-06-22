#!/bin/sh
# Install repo git hooks from tools/githooks/ into .git/hooks/.
# Idempotent. Preserves the existing git-lfs pre-push as pre-push.lfs-orig.
# Usage: sh tools/githooks/install-hooks.sh
set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"
SRC="$REPO_ROOT/tools/githooks"
DST="$(git rev-parse --git-path hooks)"

# pre-push: preserve the current (git-lfs) hook, then install the guard.
if [ -f "$DST/pre-push" ] && [ ! -f "$DST/pre-push.lfs-orig" ]; then
  if ! grep -q "INC-2026-06-20-AUTOPUSH" "$DST/pre-push" 2>/dev/null; then
    cp "$DST/pre-push" "$DST/pre-push.lfs-orig"
    echo "preserved existing pre-push -> pre-push.lfs-orig"
  fi
fi
cp "$SRC/pre-push" "$DST/pre-push"
chmod +x "$DST/pre-push" "$DST/pre-push.lfs-orig" 2>/dev/null || true
echo "installed: $DST/pre-push (INC-2026-06-20-AUTOPUSH guard, chains to lfs-orig)"
