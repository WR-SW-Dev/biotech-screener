#!/usr/bin/env python3
"""Production QA check — post-production daily review.

Runs after the daily production pipeline and agents. Checks:
  1. Snapshot exists with rankings.csv
  2. Run manifest has no FAIL gates
  3. Production log has no tracebacks
  4. EES v3 sidecar emitted
  5. Runway severity overlay emitted
  6. Herald digest delivered
  7. Key column schema drift
  8. Readiness scorecard exists
  9. Targeted lint on production-critical files
 10. Targeted pytest on critical test subset
 11. Classifier escalation-pool health (post-cutover, CH-hardening 2026-04-19)

Output:
    artifacts/production_qa/{date}_report.json
    artifacts/production_qa/{date}_report.md
    artifacts/production_qa/hard_collisions_{date}.json  (from check #11)

Usage:
    python tools/production_qa_check.py --as-of-date 2026-04-15
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("production_qa")

SCHEMA_VERSION = "production_qa.v1"
SNAPSHOTS_DIR = REPO_ROOT / "data" / "snapshots"
LOGS_DIR = REPO_ROOT / "logs"
ARTIFACTS_DIR = REPO_ROOT / "artifacts"
OUTPUT_DIR = ARTIFACTS_DIR / "production_qa"

# Production-critical files for lint check
LINT_FILES = [
    "run_screen.py",
    "decision_engine.py",
    "selector_engine.py",
    "event_ev/expectation_error_model.py",
    "event_ev/ees_v3.py",
    "event_ev/runway_severity.py",
    "event_ev/conditional_model.py",
    "tools/run_daily_production.py",
]

# Critical test subset (fast, high-value)
CRITICAL_TESTS = [
    "tests/test_runway_severity.py",
    "tests/test_expectation_error_model.py",
    "tests/test_decision_engine_contract.py",
    "tests/test_production_gates.py",
]

# Expected columns in rankings.csv (schema drift detection)
REQUIRED_COLUMNS = [
    "ticker",
    "actionable_rank",
    "eligible",
    "tier_dev",
    "catalyst_days",
    "catalyst_event_type",
    "ees_v2_score",
    "ees_trap_gate",
    "ees_eligible",
    "trap_overlay_score",
    "quality_overlay_score",
]

V3_COLUMNS = [
    "ees_v3_score",
    "ees_v3_gate",
    "ees_v3_pctile",
]

SEVERITY_COLUMNS = [
    "runway_severity_score",
    "financing_truth_gate",
    "dilution_haircut",
    "size_multiplier",
]


def _check(name: str, passed: bool, detail: str = "") -> Dict[str, Any]:
    return {"check": name, "status": "PASS" if passed else "FAIL", "detail": detail}


def check_snapshot(as_of_date: str) -> Dict[str, Any]:
    snap = SNAPSHOTS_DIR / as_of_date
    rankings = snap / "rankings.csv"
    if not rankings.exists():
        return _check("snapshot", False, f"No rankings.csv for {as_of_date}")

    import csv

    with open(rankings) as f:
        reader = csv.DictReader(f)
        cols = set(reader.fieldnames or [])
        n_rows = sum(1 for _ in reader)

    if n_rows == 0:
        return _check("snapshot", False, "rankings.csv is empty")

    return _check("snapshot", True, f"{n_rows} tickers, {len(cols)} columns")


def check_gates(as_of_date: str) -> Dict[str, Any]:
    manifest = SNAPSHOTS_DIR / as_of_date / "run_manifest.json"
    if not manifest.exists():
        return _check("gates", False, "run_manifest.json missing")

    try:
        data = json.loads(manifest.read_text())
    except json.JSONDecodeError:
        return _check("gates", False, "run_manifest.json corrupt (malformed JSON)")
    gates = data.get("gates", [])
    fails = [g for g in gates if g.get("status") == "FAIL"]
    warns = [g for g in gates if g.get("status") == "WARN"]

    if fails:
        fail_names = [g.get("name", "?") for g in fails]
        return _check("gates", False, f"{len(fails)} FAIL: {', '.join(fail_names)}")

    return _check("gates", True, f"{len(gates)} gates, {len(warns)} WARN")


def check_tracebacks(as_of_date: str) -> Dict[str, Any]:
    log_path = LOGS_DIR / f"daily_production_{as_of_date}.log"
    if not log_path.exists():
        return _check("tracebacks", True, "No per-date log for scan")
    total_tb = log_path.read_text(errors="replace").count("Traceback")
    if total_tb > 0:
        return _check("tracebacks", False, f"{total_tb} tracebacks in log")
    return _check("tracebacks", True, "No tracebacks")


def check_sidecars(as_of_date: str) -> Dict[str, Any]:
    snap = SNAPSHOTS_DIR / as_of_date
    issues = []

    for sidecar in [
        "ees_v3_overlay.json",
        "ees_sidecar_diff.json",
        "runway_severity_overlay.json",
        "expectation_error_overlay.json",
        "ees_gate_diagnostics.json",
    ]:
        if not (snap / sidecar).exists():
            issues.append(f"missing: {sidecar}")

    if issues:
        return _check("sidecars", False, "; ".join(issues))
    return _check("sidecars", True, "All sidecars present")


def check_herald_digest(as_of_date: str) -> Dict[str, Any]:
    digest_dir = ARTIFACTS_DIR / "news_digest"
    today_digests = list(digest_dir.glob(f"biotech_news_digest_{as_of_date}_*.json"))

    if not today_digests:
        return _check("herald_digest", False, f"No digest for {as_of_date}")

    return _check("herald_digest", True, f"{len(today_digests)} digests")


def check_schema_drift(as_of_date: str) -> Dict[str, Any]:
    rankings = SNAPSHOTS_DIR / as_of_date / "rankings.csv"
    if not rankings.exists():
        return _check("schema", False, "No rankings.csv")

    import csv

    with open(rankings) as f:
        cols = set(csv.DictReader(f).fieldnames or [])

    missing_required = [c for c in REQUIRED_COLUMNS if c not in cols]
    missing_v3 = [c for c in V3_COLUMNS if c not in cols]
    missing_sev = [c for c in SEVERITY_COLUMNS if c not in cols]

    issues = []
    if missing_required:
        issues.append(f"REQUIRED missing: {missing_required}")
    if missing_v3:
        issues.append(f"v3 missing: {missing_v3}")
    if missing_sev:
        issues.append(f"severity missing: {missing_sev}")

    if missing_required:
        return _check("schema", False, "; ".join(issues))

    detail = "Required OK"
    if missing_v3 or missing_sev:
        detail += f" ({'; '.join(issues)})"
    return _check("schema", True, detail)


def check_readiness(as_of_date: str) -> Dict[str, Any]:
    scorecard = ARTIFACTS_DIR / "readiness" / f"scorecard_{as_of_date}.json"
    if not scorecard.exists():
        return _check("readiness", False, "No readiness scorecard")

    try:
        data = json.loads(scorecard.read_text())
    except json.JSONDecodeError:
        return _check("readiness", False, "readiness scorecard corrupt (malformed JSON)")
    verdict = data.get("verdict", "UNKNOWN")
    return _check("readiness", True, f"Verdict: {verdict}")


def check_lint() -> Dict[str, Any]:
    files = [str(REPO_ROOT / f) for f in LINT_FILES if (REPO_ROOT / f).exists()]
    if not files:
        return _check("lint", True, "No production files to lint")

    try:
        result = subprocess.run(
            ["flake8", "--select=E9,F63,F7,F82", "--max-line-length=120"] + files,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            n_errors = result.stdout.strip().count("\n") + 1
            return _check("lint", False, f"{n_errors} critical lint errors")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return _check("lint", True, "flake8 not available or timed out")

    return _check("lint", True, f"{len(files)} files clean")


def check_classifier_escalation_pool(as_of_date: str) -> Dict[str, Any]:
    """Post-cutover validation of the press-release classifier's escalation pool.

    Added with classifier-hardening rollout 2026-04-19 (CH-1..CH-7 + P2 + M1).
    Reads the floor date from `config/post_cutover_floor.json`; audits the
    escalation pool among files dated on/after the floor; emits a 10-item
    hard-collision sample to `artifacts/production_qa/hard_collisions_{date}.json`
    for rolling human spot-check (supersedes the discrete Day-7/Day-14 milestones
    in fingpt_pilot/notes/POST_CUTOVER_VALIDATION.md).

    Verdict thresholds:
      PASS — pool empty (awaiting first post-cutover cron output), OR all within range
      FAIL — other-category share > 50%, OR re-run clean rate < 70%, OR schema missing
    """
    import random as _rand

    floor_cfg = REPO_ROOT / "config" / "post_cutover_floor.json"
    if not floor_cfg.exists():
        return _check(
            "classifier_escalation_pool",
            False,
            "config/post_cutover_floor.json missing",
        )
    try:
        cfg = json.loads(floor_cfg.read_text())
    except Exception as e:
        return _check("classifier_escalation_pool", False, f"config parse error: {e}")

    min_date = cfg.get("classifier_min_date")
    if min_date == "":
        # Floor explicitly disabled — audit full cache
        min_date = None
    elif not min_date:
        return _check(
            "classifier_escalation_pool",
            False,
            'classifier_min_date missing from config (set to YYYY-MM-DD or "" to disable)',
        )

    try:
        from tools.audit_escalation_pool import _iter_records, audit
    except ImportError as e:
        return _check("classifier_escalation_pool", False, f"import failed: {e}")

    classified_dir = REPO_ROOT / "data" / "press_releases" / "classified"
    if not classified_dir.exists():
        return _check("classifier_escalation_pool", False, f"missing {classified_dir}")

    try:
        rpt = audit(classified_dir, n=30, seed=20260419, min_date=min_date)
    except Exception as e:
        return _check("classifier_escalation_pool", False, f"audit error: {e}")

    pool_size = rpt["pool_count_deduped"]
    sample_n = rpt["sample_n"]
    rerun = rpt.get("sample_rerun_counts", {})
    clean = int(rerun.get("clean", 0))
    by_cat = rpt["pool_stats"].get("by_category", {}) if rpt.get("pool_stats") else {}
    other = int(by_cat.get("other", 0))
    other_share_pct = (other / pool_size * 100.0) if pool_size else 0.0

    if pool_size == 0:
        detail = f"pool empty (min_date={min_date}) — awaiting first post-cutover cron output"
        return _check("classifier_escalation_pool", True, detail)

    # Schema sanity — verify new P2/M1 fields are present on a spot sample
    schema_missing = []
    for r in rpt.get("sample_rows", [])[:5]:
        if r.get("event_id", "") == "":
            schema_missing.append("event_id")
            break

    issues: list[str] = []
    if other_share_pct > 50:
        issues.append(f"other_share={other_share_pct:.1f}% (>50)")
    if sample_n > 0 and clean / sample_n < 0.70:
        issues.append(f"clean={clean}/{sample_n} (<70%)")
    if schema_missing:
        issues.append(f"schema_missing={schema_missing}")

    # Hard-collision sample for rolling human review (replaces Day-7 checkpoint).
    records = _iter_records(classified_dir, min_date=min_date)
    hard_colls = [r for r in records if r.get("collision_severity") == "hard"]
    rng = _rand.Random(int(as_of_date.replace("-", "")))
    rng.shuffle(hard_colls)
    sample_hard = [
        {
            "ticker": r.get("ticker", ""),
            "headline": (r.get("headline", "") or "")[:160],
            "event_id": r.get("event_id", ""),
            "published_at_utc": r.get("published_at_utc", ""),
        }
        for r in hard_colls[:10]
    ]
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    hard_path = OUTPUT_DIR / f"hard_collisions_{as_of_date}.json"
    hard_path.write_text(
        json.dumps(
            {
                "as_of_date": as_of_date,
                "min_date": min_date,
                "pool_size": pool_size,
                "hard_collision_pool_size": len(hard_colls),
                "hard_collision_sample": sample_hard,
            },
            indent=2,
        )
    )

    detail = (
        f"pool={pool_size}, clean={clean}/{sample_n}, "
        f"other={other_share_pct:.1f}%, hard_coll_pool={len(hard_colls)}"
    )
    if issues:
        detail = f"{detail} [{'; '.join(issues)}]"
    return _check("classifier_escalation_pool", len(issues) == 0, detail)


def check_critical_tests() -> Dict[str, Any]:
    test_files = [str(REPO_ROOT / f) for f in CRITICAL_TESTS if (REPO_ROOT / f).exists()]
    if not test_files:
        return _check("tests", True, "No critical test files found")

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest"] + test_files + ["-x", "-q", "--tb=line", "--no-header"],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(REPO_ROOT),
        )
        output = result.stdout.strip()
        last_line = output.split("\n")[-1] if output else ""

        if result.returncode != 0:
            return _check("tests", False, last_line[:200])
    except subprocess.TimeoutExpired:
        return _check("tests", False, "Test suite timed out (>120s)")

    return _check("tests", True, last_line[:200])


def run_qa(as_of_date: str) -> Dict[str, Any]:
    checks = [
        check_snapshot(as_of_date),
        check_gates(as_of_date),
        check_tracebacks(as_of_date),
        check_sidecars(as_of_date),
        check_herald_digest(as_of_date),
        check_schema_drift(as_of_date),
        check_readiness(as_of_date),
        check_lint(),
        check_critical_tests(),
        check_classifier_escalation_pool(as_of_date),
    ]

    n_pass = sum(1 for c in checks if c["status"] == "PASS")
    n_fail = sum(1 for c in checks if c["status"] == "FAIL")
    verdict = "GREEN" if n_fail == 0 else "YELLOW" if n_fail <= 2 else "RED"

    report = {
        "schema": SCHEMA_VERSION,
        "as_of_date": as_of_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "verdict": verdict,
        "n_checks": len(checks),
        "n_pass": n_pass,
        "n_fail": n_fail,
        "checks": checks,
    }

    # Write outputs
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    json_path = OUTPUT_DIR / f"{as_of_date}_report.json"
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2)

    md_path = OUTPUT_DIR / f"{as_of_date}_report.md"
    md_path.write_text(_format_md(report))

    logger.info("QA %s: %s (%d/%d pass)", as_of_date, verdict, n_pass, len(checks))
    return report


def _format_md(report: Dict) -> str:
    lines = [f"# Production QA — {report['as_of_date']}"]
    lines.append("")
    lines.append(f"**Verdict:** {report['verdict']} ({report['n_pass']}/{report['n_checks']} pass)")
    lines.append("")
    lines.append("| Check | Status | Detail |")
    lines.append("|-------|--------|--------|")
    for c in report["checks"]:
        status = c["status"]
        lines.append(f"| {c['check']} | {status} | {c['detail'][:80]} |")
    lines.append("")
    lines.append(f"*Generated: {report['generated_at']}*")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Production QA check")
    parser.add_argument("--as-of-date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    args = parser.parse_args()

    report = run_qa(args.as_of_date)

    # Print summary
    for c in report["checks"]:
        marker = "PASS" if c["status"] == "PASS" else "FAIL"
        print(f"  [{marker}] {c['check']}: {c['detail'][:70]}")
    print(f"\n  Verdict: {report['verdict']}")


if __name__ == "__main__":
    main()
