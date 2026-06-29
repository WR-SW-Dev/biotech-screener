#!/usr/bin/env bash
# run_skill_tests.sh — run skill-related tests from Linux fs to avoid WSL2 /mnt/c I/O overhead
# Usage: ./run_skill_tests.sh [pytest args]
# Typical speedup: ~8x (5s vs 44s) by running from /tmp instead of /mnt/c

set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
MIRROR="/tmp/skill_test_mirror"
SKILL_TESTS=(
    "tests/test_sync_hermes_skills.py"
    "tests/test_hermes_skill_sync_agent.py"
    "tests/test_pattern_to_skillpatch_lane.py"
    "tests/test_skills_execution_logger.py"
    "tests/test_skills_loop_review.py"
    "tests/test_agent_skill_telemetry.py"
    "tests/test_cron_weekly_skills_review.py"
    "tests/test_weekly_skills_digest_fleet_ops.py"
)

# --- Mirror to Linux filesystem ---
mkdir -p \
    "$MIRROR/tests" \
    "$MIRROR/docs/hermes_skills" \
    "$MIRROR/agents" \
    "$MIRROR/.learnings"

rsync -a --delete "$REPO/tools/"             "$MIRROR/tools/"
rsync -a --delete "$REPO/skills/"            "$MIRROR/skills/"
rsync -a --delete "$REPO/docs/hermes_skills/" "$MIRROR/docs/hermes_skills/"
rsync -a --delete "$REPO/.learnings/"        "$MIRROR/.learnings/"
rsync -a          "$REPO/agents/AGENT_REGISTRY.json" "$MIRROR/agents/"
cp "$REPO/pyproject.toml" "$MIRROR/pyproject.toml"

# Copy only the skill test files (not the whole tests/ dir)
touch "$MIRROR/tests/__init__.py"
for t in "${SKILL_TESTS[@]}"; do
    cp "$REPO/$t" "$MIRROR/tests/"
done

# --- Run pytest from Linux fs ---
cd "$MIRROR"
exec python3 -m pytest tests/ -q -m 'not network' "$@"
