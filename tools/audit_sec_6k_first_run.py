#!/usr/bin/env python3
"""Audit the first production snapshot under the 8-K + 6-K producer.

Runs on 2026-04-29 18:00 ET via tools/cron_one_shot_2026_04_29.sh, after
the day's 16:30 cron has produced cache/sec/8k_catalysts/8k_catalysts_
{date}_937b38db.json.

Four checks:
  1. Snapshot exists and is non-empty.
  2. Event-count today vs baseline 2026-04-28 (357). Expected: increase.
  3. Source distribution includes SEC_6K_FILING.
  4. 21 candidate tickers from sec_6k_blast_radius_2026-04-28.json gained
     coverage. Also: 8-K record count for previously-covered tickers did
     not materially regress.

Exits non-zero if any check hard-fails (missing snapshot, zero events,
no SEC_6K_FILING records). Prints PASS/WARN/FAIL summary and writes
artifacts/audit/sec_6k_first_run_{target_date}.json.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / "cache" / "sec" / "8k_catalysts"
ARTIFACT_DIR = REPO_ROOT / "artifacts" / "audit"
BLAST_RADIUS_PATH = REPO_ROOT / "artifacts" / "sec_8k" / "sec_6k_blast_radius_2026-04-28.json"


def _snapshot_path(date_str: str) -> Path:
    matches = sorted(CACHE_DIR.glob(f"8k_catalysts_{date_str}_*.json"))
    if not matches:
        raise FileNotFoundError(f"No snapshot for {date_str} in {CACHE_DIR}")
    return matches[-1]


def _load(path: Path) -> list:
    with open(path) as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected list, got {type(data).__name__}")
    return data


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--target-date", default="2026-04-29")
    p.add_argument("--baseline-date", default="2026-04-28")
    p.add_argument(
        "--baseline-event-count",
        type=int,
        default=357,
        help="Baseline event count from 2026-04-28 snapshot (audited).",
    )
    p.add_argument("--regression-threshold", type=float, default=0.90)
    args = p.parse_args()

    findings: dict = {
        "target_date": args.target_date,
        "baseline_date": args.baseline_date,
        "checks": [],
    }
    overall_pass = True

    # Check 1: snapshot exists
    try:
        snap_path = _snapshot_path(args.target_date)
        events = _load(snap_path)
    except (FileNotFoundError, ValueError) as e:
        findings["checks"].append({"name": "snapshot_exists", "status": "FAIL", "detail": str(e)})
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        out_path = ARTIFACT_DIR / f"sec_6k_first_run_{args.target_date}.json"
        with open(out_path, "w") as fh:
            json.dump(findings, fh, indent=2)
        print(f"FAIL: {e}", file=sys.stderr)
        return 2

    findings["snapshot_path"] = str(snap_path.relative_to(REPO_ROOT))
    findings["snapshot_event_count"] = len(events)
    findings["checks"].append(
        {"name": "snapshot_exists", "status": "PASS", "detail": f"{len(events)} events at {snap_path.name}"}
    )

    # Check 2: event-count vs baseline
    baseline_n = args.baseline_event_count
    delta = len(events) - baseline_n
    delta_pct = 100 * delta / max(1, baseline_n)
    findings["baseline_event_count"] = baseline_n
    findings["event_count_delta"] = delta
    findings["event_count_delta_pct"] = round(delta_pct, 2)
    if len(events) <= 0:
        status, detail = "FAIL", "snapshot is empty"
        overall_pass = False
    elif delta > 0:
        status, detail = "PASS", f"{len(events)} vs baseline {baseline_n} (+{delta}, +{delta_pct:.1f}%)"
    elif len(events) < baseline_n * args.regression_threshold:
        status = "FAIL"
        detail = f"{len(events)} < {args.regression_threshold:.0%} of baseline {baseline_n} — regression"
        overall_pass = False
    else:
        status = "WARN"
        detail = f"{len(events)} vs baseline {baseline_n} ({delta:+d}) — no increase"
    findings["checks"].append({"name": "event_count_vs_baseline", "status": status, "detail": detail})

    # Check 3: source distribution
    by_source = Counter(ev.get("source", "(missing)") for ev in events)
    findings["source_distribution"] = dict(by_source.most_common())
    n_8k = by_source.get("SEC_8K_FILING", 0)
    n_6k = by_source.get("SEC_6K_FILING", 0)
    if n_6k > 0:
        status = "PASS"
        detail = f"SEC_6K_FILING={n_6k}, SEC_8K_FILING={n_8k}"
    else:
        status = "FAIL"
        detail = f"SEC_6K_FILING=0 (8-K={n_8k}); 6-K records did not materialize"
        overall_pass = False
    findings["checks"].append({"name": "sec_6k_records_present", "status": status, "detail": detail})

    # Check 4a: 21 likely-to-gain tickers
    try:
        with open(BLAST_RADIUS_PATH) as fh:
            blast = json.load(fh)
        candidates = blast["cohort_shift_summary"]["likely_to_gain_coverage_intersection"]
    except Exception as e:
        findings["checks"].append(
            {"name": "candidate_coverage", "status": "WARN", "detail": f"could not load blast radius: {e}"}
        )
        candidates = []

    if candidates:
        tickers_today = {ev.get("ticker") for ev in events}
        gained = [t for t in candidates if t in tickers_today]
        missed = [t for t in candidates if t not in tickers_today]
        findings["candidates_total"] = len(candidates)
        findings["candidates_gained"] = gained
        findings["candidates_missed"] = missed
        if len(gained) >= max(1, len(candidates) // 4):
            status = "PASS"
        elif len(gained) >= 1:
            status = "WARN"
        else:
            status = "FAIL"
            overall_pass = False
        findings["checks"].append(
            {
                "name": "candidate_coverage",
                "status": status,
                "detail": f"{len(gained)}/{len(candidates)} candidates have records today",
            }
        )

    # Check 4b: 8-K count regression for previously covered tickers
    try:
        baseline_path = _snapshot_path(args.baseline_date)
        baseline_events = _load(baseline_path)
        baseline_8k_tickers = {ev.get("ticker") for ev in baseline_events if ev.get("source") == "SEC_8K_FILING"}
        baseline_8k_count = sum(1 for ev in baseline_events if ev.get("source") == "SEC_8K_FILING")
        today_8k_count_for_baseline_tickers = sum(
            1 for ev in events if ev.get("source") == "SEC_8K_FILING" and ev.get("ticker") in baseline_8k_tickers
        )
        ratio = today_8k_count_for_baseline_tickers / max(1, baseline_8k_count)
        findings["baseline_8k_count"] = baseline_8k_count
        findings["today_8k_count_for_baseline_tickers"] = today_8k_count_for_baseline_tickers
        findings["8k_retention_ratio"] = round(ratio, 4)
        if ratio >= args.regression_threshold:
            status = "PASS"
            detail = f"{today_8k_count_for_baseline_tickers}/{baseline_8k_count} = {ratio:.1%} (≥{args.regression_threshold:.0%})"
        else:
            status = "FAIL"
            detail = f"{today_8k_count_for_baseline_tickers}/{baseline_8k_count} = {ratio:.1%} < {args.regression_threshold:.0%} — 8-K regression"
            overall_pass = False
        findings["checks"].append({"name": "no_8k_regression", "status": status, "detail": detail})
    except Exception as e:
        findings["checks"].append({"name": "no_8k_regression", "status": "WARN", "detail": str(e)})

    findings["overall"] = "PASS" if overall_pass else "FAIL"

    # Persist
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = ARTIFACT_DIR / f"sec_6k_first_run_{args.target_date}.json"
    with open(out_path, "w") as fh:
        json.dump(findings, fh, indent=2)

    # Print summary
    print(f"=== SEC 6-K first-run audit — {args.target_date} ===")
    print(f"snapshot: {findings.get('snapshot_path', '(missing)')}")
    print(f"events: {findings.get('snapshot_event_count', '?')} (baseline {baseline_n})")
    print(f"source mix: {findings.get('source_distribution', {})}")
    if "candidates_gained" in findings:
        print(
            f"candidates: {len(findings['candidates_gained'])}/{findings['candidates_total']} gained — "
            f"{', '.join(findings['candidates_gained']) or '(none)'}"
        )
    print()
    for c in findings["checks"]:
        print(f"  [{c['status']}] {c['name']}: {c['detail']}")
    print()
    print(f"OVERALL: {findings['overall']}")
    print(f"artifact: {out_path.relative_to(REPO_ROOT)}")
    return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
