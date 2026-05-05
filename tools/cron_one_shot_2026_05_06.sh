#!/usr/bin/env bash
# cron_one_shot_2026_05_06.sh — Post-deploy checkpoint for Stages A/B/C.
#
# Fires once on Wednesday 2026-05-06 ~18:00 ET — after the daily pipeline
# (16:30), wrapper-tail (~17:00), diagnostics backstop (17:25), and
# postmortem (17:40) have all had a chance to run. Verifies that yesterday's
# code changes (Stages A-C) produced the expected artifacts and field
# additions. Read-only — no producers, no fixups.
#
# Self-skips on any other date and on re-invocations (marker file).
#
# Verifications:
#   1. logs/diagnostics_backstop.log for 2026-05-06 mentions build_rank_change_monitor
#   2. data/snapshots/2026-05-06 contract checker → PASS
#   3. ranker_shadow_comparison.json contains the new ranker_shadow_2feat_status field
#   4. artifacts/clinical_transmission_shadow.jsonl last entry has catalyst_id on changed_names
#   5. event_outcome_binder dry-run reports n_match_exact > 0 (was 0 before today's schema add)
#
# Cron entry (annual recurrence; marker prevents re-runs within the same year):
#   0 18 6 5 * /mnt/c/Projects/biotech_screener/biotech-screener/tools/cron_one_shot_2026_05_06.sh >> /mnt/c/Projects/biotech_screener/biotech-screener/logs/one_shot.log 2>&1

set -uo pipefail

REPO_ROOT="/mnt/c/Projects/biotech_screener/biotech-screener"
PYTHON="/usr/bin/python3"
TARGET_DATE="2026-05-06"
MARKER="${REPO_ROOT}/logs/.one_shot_${TARGET_DATE}.done"
REPORT="${REPO_ROOT}/artifacts/post_snapshot_done/CHECKPOINT_${TARGET_DATE}.md"
LOG_PREFIX="[$(date -Iseconds)]"

if [ -f "$MARKER" ]; then
    echo "${LOG_PREFIX} SKIP: already fired (marker $MARKER exists)"
    exit 0
fi

TODAY=$(date +%Y-%m-%d)
if [ "$TODAY" != "$TARGET_DATE" ]; then
    echo "${LOG_PREFIX} SKIP: today=${TODAY} != target=${TARGET_DATE}"
    exit 0
fi

echo "${LOG_PREFIX} Firing post-deploy checkpoint for Stages A/B/C"
cd "$REPO_ROOT"
mkdir -p "$(dirname "$REPORT")"

${PYTHON} - "$REPO_ROOT" "$TARGET_DATE" "$REPORT" <<'PYEOF'
"""Inline post-deploy checkpoint.

Args (sys.argv): repo_root, target_date, report_path
"""
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(sys.argv[1])
TARGET = sys.argv[2]
REPORT = Path(sys.argv[3])

results: list[dict] = []


def record(name: str, status: str, detail: str = "") -> None:
    results.append({"name": name, "status": status, "detail": detail})


# ---------------------------------------------------------------------------
# 1. diagnostics_backstop.log mentions build_rank_change_monitor
# ---------------------------------------------------------------------------
backstop_log = REPO_ROOT / "logs" / "diagnostics_backstop.log"
if not backstop_log.exists():
    record("diagnostics_backstop_log", "FAIL", f"{backstop_log} does not exist")
else:
    text = backstop_log.read_text(errors="ignore")
    target_lines = [
        ln for ln in text.splitlines()
        if TARGET in ln and "build_rank_change_monitor" in ln
    ]
    # Some log lines mention the date in a header preceding the tool line; also accept
    # a window-based check (any build_rank_change_monitor entry written today).
    today_lines = [
        ln for ln in text.splitlines()
        if "build_rank_change_monitor" in ln
    ]
    if target_lines:
        record(
            "diagnostics_backstop_log",
            "PASS",
            f"{len(target_lines)} build_rank_change_monitor line(s) mentioning {TARGET}",
        )
    elif today_lines:
        # Backstop wrote rank-change but timestamp/date format doesn't match target;
        # still a positive signal.
        record(
            "diagnostics_backstop_log",
            "WARN",
            f"build_rank_change_monitor present in log ({len(today_lines)} lines) but none mention {TARGET}",
        )
    else:
        record(
            "diagnostics_backstop_log",
            "FAIL",
            "no build_rank_change_monitor line found — Stage B.1 wiring may not be live",
        )


# ---------------------------------------------------------------------------
# 2. Output contract checker — required + optional artifacts present
# ---------------------------------------------------------------------------
proc = subprocess.run(
    [sys.executable, "tools/check_output_contract.py", "--as-of", TARGET],
    cwd=str(REPO_ROOT),
    capture_output=True,
    text=True,
    timeout=30,
)
try:
    contract = json.loads(proc.stdout)
except json.JSONDecodeError:
    record(
        "output_contract",
        "FAIL",
        f"unparseable contract output (rc={proc.returncode}): {proc.stdout[:200]}",
    )
    contract = None

if contract is not None:
    overall = contract.get("overall")
    missing = contract.get("missing_required", [])
    if overall == "PASS":
        record("output_contract", "PASS", "all required + optional artifacts present")
    elif overall == "WARN":
        record(
            "output_contract",
            "WARN",
            f"required complete; optional missing: {contract.get('missing_optional')}",
        )
    else:
        record("output_contract", "FAIL", f"missing required: {missing}")


# ---------------------------------------------------------------------------
# 3. ranker_shadow_comparison.json contains ranker_shadow_2feat_status
# ---------------------------------------------------------------------------
rsc_path = REPO_ROOT / "data" / "snapshots" / TARGET / "ranker_shadow_comparison.json"
if not rsc_path.exists():
    record("ranker_shadow_2feat_status", "FAIL", f"{rsc_path.name} not present in snapshot")
else:
    try:
        rsc = json.loads(rsc_path.read_text())
    except json.JSONDecodeError as e:
        record("ranker_shadow_2feat_status", "FAIL", f"unparseable JSON: {e}")
    else:
        status = rsc.get("ranker_shadow_2feat_status")
        if status is None:
            record(
                "ranker_shadow_2feat_status",
                "FAIL",
                "field absent — Stage A.2 edit not in this snapshot",
            )
        else:
            err = rsc.get("ranker_shadow_2feat_error")
            detail = f"status={status}"
            if err:
                detail += f", error={err}"
            verdict = "PASS" if status in ("OK", "IDENTICAL_TO_PROD", "NOT_RUN") else "WARN"
            record("ranker_shadow_2feat_status", verdict, detail)


# ---------------------------------------------------------------------------
# 4. clinical_transmission_shadow.jsonl last entry has catalyst_id on rows
# ---------------------------------------------------------------------------
ledger = REPO_ROOT / "artifacts" / "clinical_transmission_shadow.jsonl"
if not ledger.exists():
    record("clinical_shadow_catalyst_id", "FAIL", "ledger does not exist")
else:
    lines = [ln for ln in ledger.read_text().splitlines() if ln.strip()]
    if not lines:
        record("clinical_shadow_catalyst_id", "FAIL", "ledger is empty")
    else:
        last = json.loads(lines[-1])
        if last.get("as_of_date") != TARGET:
            record(
                "clinical_shadow_catalyst_id",
                "WARN",
                f"latest entry as_of={last.get('as_of_date')} != {TARGET}; shadow may have skipped today",
            )
        else:
            cn = last.get("changed_names") or []
            if not cn:
                record(
                    "clinical_shadow_catalyst_id",
                    "WARN",
                    "today's entry has 0 changed_names — cannot verify schema",
                )
            else:
                with_id = sum(1 for r in cn if r.get("catalyst_id"))
                with_exp = sum(1 for r in cn if r.get("expected_date"))
                pct_id = 100.0 * with_id / len(cn)
                pct_exp = 100.0 * with_exp / len(cn)
                if pct_id == 0 and pct_exp == 0:
                    record(
                        "clinical_shadow_catalyst_id",
                        "FAIL",
                        f"none of {len(cn)} rows have catalyst_id or expected_date — Stage A.3 not applied",
                    )
                else:
                    record(
                        "clinical_shadow_catalyst_id",
                        "PASS",
                        f"{with_id}/{len(cn)} ({pct_id:.0f}%) with catalyst_id; "
                        f"{with_exp}/{len(cn)} ({pct_exp:.0f}%) with expected_date",
                    )


# ---------------------------------------------------------------------------
# 5. event_outcome_binder produces exact matches now that schema is populated
# ---------------------------------------------------------------------------
proc = subprocess.run(
    [sys.executable, "tools/event_outcome_binder.py", "--dry-run"],
    cwd=str(REPO_ROOT),
    capture_output=True,
    text=True,
    timeout=60,
)
if proc.returncode != 0:
    record("binder_exact_matches", "FAIL", f"binder exited {proc.returncode}: {proc.stderr[:200]}")
else:
    try:
        summary = json.loads(proc.stdout)
    except json.JSONDecodeError:
        record("binder_exact_matches", "FAIL", f"unparseable binder output: {proc.stdout[:200]}")
    else:
        n_exact = summary.get("n_match_exact", 0)
        n_win = summary.get("n_match_windowed", 0)
        n_bound = summary.get("n_bound", 0)
        if n_exact > 0:
            record(
                "binder_exact_matches",
                "PASS",
                f"n_match_exact={n_exact}, n_match_windowed={n_win}, n_bound={n_bound}",
            )
        elif n_bound > 0:
            record(
                "binder_exact_matches",
                "WARN",
                f"n_match_exact=0 but n_bound={n_bound} (windowed only) — "
                "schema add may not have flowed through, or no exact-date catalysts resolved today",
            )
        else:
            record(
                "binder_exact_matches",
                "WARN",
                "binder produced 0 bindings — no resolved catalysts in shadow ledger",
            )


# ---------------------------------------------------------------------------
# Build report
# ---------------------------------------------------------------------------
n_pass = sum(1 for r in results if r["status"] == "PASS")
n_warn = sum(1 for r in results if r["status"] == "WARN")
n_fail = sum(1 for r in results if r["status"] == "FAIL")

if n_fail > 0:
    overall = "FAIL"
elif n_warn > 0:
    overall = "WARN"
else:
    overall = "PASS"

lines: list[str] = []
lines.append(f"# Stage A/B/C post-deploy checkpoint — {TARGET}")
lines.append("")
lines.append(f"**Overall:** {overall}  ")
lines.append(f"**Tally:** PASS={n_pass} WARN={n_warn} FAIL={n_fail}")
lines.append("")
lines.append("## Checks")
lines.append("")
lines.append("| Check | Status | Detail |")
lines.append("|---|---|---|")
for r in results:
    lines.append(f"| {r['name']} | {r['status']} | {r['detail']} |")
lines.append("")
if overall == "FAIL":
    lines.append("## Recommendation")
    lines.append("")
    lines.append("One or more checks failed. Review FAIL rows above before scheduling Stage C cron or removing the marker.")
elif overall == "WARN":
    lines.append("## Recommendation")
    lines.append("")
    lines.append("Soft warnings only. Inspect WARN rows; if benign, proceed.")
else:
    lines.append("## Recommendation")
    lines.append("")
    lines.append("All Stage A/B/C wiring observed live. Proceed to scheduling event_outcome_binder cron when ready.")
lines.append("")
lines.append("---")
lines.append("")
lines.append(f"_Generated by `tools/cron_one_shot_2026_05_06.sh`._")

REPORT.write_text("\n".join(lines))
print(f"Wrote checkpoint → {REPORT}")
print(f"Overall: {overall} (PASS={n_pass} WARN={n_warn} FAIL={n_fail})")
sys.exit(0 if overall == "PASS" else (2 if overall == "WARN" else 1))
PYEOF

CHECK_RC=$?

echo "${LOG_PREFIX} Checkpoint report ↓↓↓"
cat "$REPORT" 2>/dev/null || echo "(report not written)"
echo "${LOG_PREFIX} Checkpoint report ↑↑↑"
echo "${LOG_PREFIX} Full report: $REPORT"

touch "$MARKER"
echo "${LOG_PREFIX} Done (rc=${CHECK_RC}). Marker written: $MARKER"

# Always exit 0 from the wrapper — the inner Python encodes the verdict
# in the report. Cron logs surface the report content via the cat above.
exit 0
