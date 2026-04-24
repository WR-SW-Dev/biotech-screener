#!/usr/bin/env bash
#
# Cutover: finalize the classifier-hardening rollout (spec §8).
#
# State assumed BEFORE this runs:
#   - CH-1..CH-7 + P2 + M1 patches are in tools/classify_press_releases.py,
#     common/news_feed_schema.py, tools/herald_crt_intake.py (already landed,
#     uncommitted-to-main is fine for now).
#   - data/press_releases/classified/ holds historical canonical output
#     produced by the PRE-patch code (mixed Grok + local keywords).
#   - data/press_releases/classified/reclassified/ holds the CH-6 side-dir
#     (patched code applied to cached records, local-only).
#   - data/press_releases/classified_shadow/ holds the retroactive shadow-run
#     output over raw releases for spec §8 validation.
#   - tools/cron_data_refresh.sh line 57 invokes classify_press_releases.py
#     with no --output-dir override, so future daily runs already write
#     PATCHED output into classified/ — no cron edit required.
#
# Cron edit summary: NONE. The cron path already routes to the patched
# classifier's default OUTPUT_DIR. Verify once before promoting.
#
# This script is deliberately GATED and DRY-RUN BY DEFAULT. Pass --confirm
# to actually make changes. Any write is atomic per-directory: archive is
# created first, promotion happens second, verification third.
#
# Usage:
#   tools/cutover_classifier.sh                   # dry-run preview
#   tools/cutover_classifier.sh --archive-only --confirm
#   tools/cutover_classifier.sh --full --confirm
#   tools/cutover_classifier.sh --preserve-old --confirm
#
# Modes:
#   --archive-only
#       Archive existing classified/ → classified_legacy_YYYYMMDD/.
#       Canonical ends up EMPTY. The next cron run populates it with
#       freshly-patched output. Historical consumers break until backfill.
#
#   --full (spec §8 default intent)
#       Archive existing classified/ → classified_legacy_YYYYMMDD/.
#       Promote classified/reclassified/ → classified/ (local-only re-runs
#       replace the historical mixed-method cache).
#       Warning: ~142 records will lose their original Grok-assigned
#       event_category (see FINAL_SUMMARY.md §"quantified impact").
#
#   --preserve-old (most conservative — recommended default)
#       Copy existing classified/ to classified_legacy_YYYYMMDD/ (keep the
#       originals in place). Do NOT promote the side-dir. Going forward,
#       daily cron runs append patched output to the same classified/ dir,
#       so the cache becomes a growing mix of pre-patch (legacy) + post-
#       patch records. Downstream consumers continue to work. The legacy
#       copy exists for rollback if needed.
#
# Every mode runs a post-cutover CH-7 audit and prints a summary. If the
# audit fails the ≥80% purity gate, the operator should inspect + decide
# whether to roll back (rollback instructions printed on success).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
PR_DIR="$REPO_ROOT/data/press_releases"
CLASSIFIED="$PR_DIR/classified"
RECLASSIFIED="$CLASSIFIED/reclassified"
SHADOW="$PR_DIR/classified_shadow"
TODAY_STAMP="$(date -u +%Y%m%d)"
LEGACY="$PR_DIR/classified_legacy_$TODAY_STAMP"

MODE=""
CONFIRM=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --archive-only) MODE="archive-only"; shift ;;
        --full)         MODE="full";         shift ;;
        --preserve-old) MODE="preserve-old"; shift ;;
        --confirm)      CONFIRM=1;           shift ;;
        -h|--help)
            grep -E '^#' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *) echo "Unknown arg: $1"; exit 2 ;;
    esac
done

if [[ -z "$MODE" ]]; then
    echo "ERROR: must specify one of --archive-only | --full | --preserve-old"
    echo "Run tools/cutover_classifier.sh --help for detail."
    exit 2
fi

log()  { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }
run()  {
    if [[ "$CONFIRM" -eq 1 ]]; then
        log "RUN: $*"
        eval "$*"
    else
        log "DRY: $*"
    fi
}

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

log "Cutover mode:     $MODE"
if [[ $CONFIRM -eq 1 ]]; then
    log "Confirm:          YES"
else
    log "Confirm:          NO (dry-run)"
fi
log "Repo root:        $REPO_ROOT"
log "Classified dir:   $CLASSIFIED"
log "Legacy target:    $LEGACY"
log "Reclassified dir: $RECLASSIFIED"
log "Shadow dir:       $SHADOW"
echo

if [[ ! -d "$CLASSIFIED" ]]; then
    echo "ERROR: $CLASSIFIED does not exist. Aborting."
    exit 1
fi

if [[ -d "$LEGACY" ]]; then
    echo "ERROR: legacy path $LEGACY already exists. Pick a different date or remove it."
    exit 1
fi

if [[ "$MODE" == "full" && ! -d "$RECLASSIFIED" ]]; then
    echo "ERROR: --full mode requires $RECLASSIFIED (run tools/reclassify_press_release_cache.py first)."
    exit 1
fi

if [[ ! -d "$SHADOW" ]]; then
    log "WARN: shadow dir $SHADOW not found. Spec §8 recommends a shadow run before cutover. Continuing."
fi

# ---------------------------------------------------------------------------
# Step 1 — archive existing classified/
# ---------------------------------------------------------------------------

case "$MODE" in
    archive-only|full)
        log "Step 1: archive $CLASSIFIED → $LEGACY"
        run "mv \"$CLASSIFIED\" \"$LEGACY\""
        run "mkdir -p \"$CLASSIFIED\""
        ;;
    preserve-old)
        log "Step 1: copy $CLASSIFIED → $LEGACY (keep originals in place)"
        run "cp -r \"$CLASSIFIED\" \"$LEGACY\""
        ;;
esac

# ---------------------------------------------------------------------------
# Step 2 — promote reclassified/ → classified/ (full mode only)
# ---------------------------------------------------------------------------

if [[ "$MODE" == "full" ]]; then
    log "Step 2: promote reclassified/*.jsonl → $CLASSIFIED"
    # After Step 1's mv, the reclassified/ dir lives at $LEGACY/reclassified/.
    # In dry-run (no mv yet) it is still at $CLASSIFIED/reclassified/ —
    # glob that location so the preview lists what WOULD move.
    if [[ "$CONFIRM" -eq 1 ]]; then
        src_reclassified="$LEGACY/reclassified"
    else
        src_reclassified="$CLASSIFIED/reclassified"
    fi
    if [[ -d "$src_reclassified" ]]; then
        count=0
        for f in "$src_reclassified"/*.jsonl; do
            [[ -e "$f" ]] || continue
            run "mv \"$f\" \"$CLASSIFIED/\""
            count=$((count + 1))
        done
        log "Step 2: $count jsonl file(s) queued for promotion"
        run "mv \"$src_reclassified/_reports\" \"$CLASSIFIED/_reclassify_reports\" 2>/dev/null || true"
    else
        log "Step 2: $src_reclassified not found — nothing to promote"
    fi
else
    log "Step 2: skipped (mode=$MODE does not promote reclassified/)"
fi

# ---------------------------------------------------------------------------
# Step 3 — post-cutover audit
# ---------------------------------------------------------------------------

log "Step 3: run CH-7 audit on new $CLASSIFIED"
if [[ "$CONFIRM" -eq 1 ]]; then
    (
        cd "$REPO_ROOT"
        $PYTHON tools/audit_escalation_pool.py --source canonical || true
    )
else
    log "DRY: (would run) python tools/audit_escalation_pool.py --source canonical"
fi

# ---------------------------------------------------------------------------
# Rollback instructions (printed every run)
# ---------------------------------------------------------------------------

cat <<EOF

────────────────────────────────────────────────────────────────────────────
Rollback instructions (run AT MOST ONCE if something looks wrong):

  # Full rollback (matches archive-only and full modes):
  rm -rf "$CLASSIFIED"
  mv "$LEGACY" "$CLASSIFIED"

  # Preserve-old rollback:
  rm -rf "$LEGACY"   # just removes the backup; originals untouched

Cron edit: NONE required. tools/cron_data_refresh.sh line 57 already invokes
tools/classify_press_releases.py with the patched OUTPUT_DIR. Next scheduled
run will write patched output to $CLASSIFIED.
────────────────────────────────────────────────────────────────────────────
EOF

if [[ $CONFIRM -eq 1 ]]; then
    log "Cutover $MODE COMPLETE."
else
    log "Cutover $MODE DRY-RUN done."
fi
