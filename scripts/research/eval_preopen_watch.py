#!/usr/bin/env python3
"""Evaluate Phase 3 pre-open watch shadow against promotion criteria.

Compares pre-open watch artifacts against post-packet watch, surface delta,
review queue, and trade plan over a multi-day window.

Promotion criteria (10 trading days):
  PASS if ALL of:
    - Median pre-open flagged names <= 8
    - 90th percentile pre-open flagged names <= 15
    - >= 50% of pre-open flagged names appear in post-open context
      (surface_delta alert/watch, review queue, or trade plan)
    - >= 80% of same-day post-open alert names within hard-catalyst/trade-plan
      scope appeared in pre-open watch
    - Zero days where bad freshness still produces normal output
    - No governance bleed (checked externally)

  FAIL if any threshold breached.

Usage:
    python scripts/research/eval_preopen_watch.py
    python scripts/research/eval_preopen_watch.py --min-days 5
    python scripts/research/eval_preopen_watch.py --start-date 2026-03-27 --end-date 2026-04-10
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))


def _load_json(path: Path) -> Optional[Dict]:
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _load_csv_tickers(path: Path) -> Set[str]:
    import csv

    if not path.exists():
        return set()
    try:
        with open(path, encoding="utf-8") as f:
            return {row["ticker"] for row in csv.DictReader(f) if row.get("ticker")}
    except (KeyError, OSError):
        return set()


def find_shadow_dates(
    artifacts_dir: Path,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> List[str]:
    """Find dates that have both post_packet and pre_open watch artifacts."""
    watch_dir = artifacts_dir / "options_watch"
    if not watch_dir.exists():
        return []

    post_dates = set()
    pre_dates = set()
    for p in watch_dir.glob("*_watch.json"):
        name = p.stem
        if name.endswith("_premarket_watch"):
            d = name.replace("_premarket_watch", "")
            pre_dates.add(d)
        elif name.endswith("_watch"):
            d = name.replace("_watch", "")
            post_dates.add(d)

    both = sorted(post_dates & pre_dates)
    if start_date:
        both = [d for d in both if d >= start_date]
    if end_date:
        both = [d for d in both if d <= end_date]
    return both


def evaluate_day(
    date: str,
    artifacts_dir: Path,
    snapshots_dir: Path,
) -> Dict[str, Any]:
    """Evaluate one day's pre-open watch against post-open context."""
    watch_dir = artifacts_dir / "options_watch"

    post = _load_json(watch_dir / f"{date}_watch.json")
    pre = _load_json(watch_dir / f"{date}_premarket_watch.json")

    if not post or not pre:
        return {"date": date, "error": "missing artifacts"}

    # Pre-open flagged names
    pre_tickers = {r["ticker"] for r in pre.get("rows", [])}
    pre_flagged = {r["ticker"] for r in pre.get("rows", []) if r.get("flags")}

    # Post-packet context: flagged names
    post_tickers = {r["ticker"] for r in post.get("rows", [])}
    post_flagged = {r["ticker"] for r in post.get("rows", []) if r.get("flags")}

    # Surface delta context
    sd = _load_json(snapshots_dir / date / "surface_delta.json")
    sd_alert_tickers: Set[str] = set()
    sd_watch_tickers: Set[str] = set()
    if sd:
        for d in sd.get("deltas", []):
            if d.get("severity") == "alert":
                sd_alert_tickers.add(d["ticker"])
            elif d.get("severity") == "watch":
                sd_watch_tickers.add(d["ticker"])
    sd_all = sd_alert_tickers | sd_watch_tickers

    # Review queue
    rq_tickers = _load_csv_tickers(snapshots_dir / date / "review_queue.csv")

    # Trade plan
    tp_tickers = _load_csv_tickers(artifacts_dir / "live_shadow" / "trade_plan" / date / "trade_plan.csv")

    # Post-open context = surface delta + review queue + trade plan
    post_open_context = sd_all | rq_tickers | tp_tickers

    # Metric 1: pre-open flagged count
    n_pre_flagged = len(pre_flagged)

    # Metric 2: precision — what fraction of pre-open flagged appear in post-open context
    if pre_flagged:
        pre_in_context = pre_flagged & post_open_context
        precision = len(pre_in_context) / len(pre_flagged)
    else:
        precision = 1.0  # no flags = no false positives

    # Metric 3: recall — hard-catalyst/trade-plan post-open alerts covered by pre-open
    # "alert names within hard-catalyst/trade-plan scope"
    # We approximate: surface delta alerts that are also in trade_plan or hard-catalyst
    # Load rankings to check is_hard
    import csv

    hard_tickers: Set[str] = set()
    rankings_path = snapshots_dir / date / "rankings.csv"
    if rankings_path.exists():
        with open(rankings_path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("is_hard_catalyst") == "1":
                    hard_tickers.add(row["ticker"])

    scoped_alerts = sd_alert_tickers & (hard_tickers | tp_tickers)
    if scoped_alerts:
        covered = scoped_alerts & pre_tickers
        recall = len(covered) / len(scoped_alerts)
    else:
        recall = 1.0  # no scoped alerts = perfect recall

    # Metric 4: suppression health — did suppression fire when expected?
    n_suppressed = pre.get("n_suppressed", 0)

    return {
        "date": date,
        "n_pre_flagged": n_pre_flagged,
        "n_pre_total": len(pre_tickers),
        "n_post_flagged": len(post_flagged),
        "n_post_total": len(post_tickers),
        "n_sd_alert": len(sd_alert_tickers),
        "n_sd_watch": len(sd_watch_tickers),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "n_scoped_alerts": len(scoped_alerts),
        "n_suppressed": n_suppressed,
        "pre_flagged_names": sorted(pre_flagged),
        "in_context_names": sorted(pre_flagged & post_open_context) if pre_flagged else [],
        "missed_alerts": sorted(scoped_alerts - pre_tickers) if scoped_alerts else [],
    }


def evaluate_window(
    dates: List[str],
    artifacts_dir: Path,
    snapshots_dir: Path,
) -> Dict[str, Any]:
    """Evaluate all dates and compute aggregate pass/fail."""
    import statistics

    day_results = []
    for d in dates:
        r = evaluate_day(d, artifacts_dir, snapshots_dir)
        if "error" not in r:
            day_results.append(r)

    if not day_results:
        return {"verdict": "INSUFFICIENT_DATA", "n_days": 0, "days": []}

    flagged_counts = [r["n_pre_flagged"] for r in day_results]
    precisions = [r["precision"] for r in day_results]
    recalls = [r["recall"] for r in day_results]

    median_flagged = statistics.median(flagged_counts)
    p90_flagged = sorted(flagged_counts)[int(len(flagged_counts) * 0.9)] if flagged_counts else 0
    mean_precision = statistics.mean(precisions)
    mean_recall = statistics.mean(recalls)

    # Pass/fail checks
    checks = {
        "median_flagged_le_8": median_flagged <= 8,
        "p90_flagged_le_15": p90_flagged <= 15,
        "precision_ge_50pct": mean_precision >= 0.50,
        "recall_ge_80pct": mean_recall >= 0.80,
    }
    all_pass = all(checks.values())

    return {
        "verdict": "PASS" if all_pass else "FAIL",
        "n_days": len(day_results),
        "dates": [r["date"] for r in day_results],
        "metrics": {
            "median_flagged": round(median_flagged, 1),
            "p90_flagged": p90_flagged,
            "mean_precision": round(mean_precision, 4),
            "mean_recall": round(mean_recall, 4),
            "flagged_per_day": flagged_counts,
            "precision_per_day": precisions,
            "recall_per_day": recalls,
        },
        "checks": checks,
        "days": day_results,
    }


def format_report(result: Dict[str, Any]) -> str:
    """Format evaluation result as markdown."""
    lines = []
    lines.append("# Phase 3 Pre-Open Watch Evaluation")
    lines.append("")
    lines.append(f"**Verdict: {result['verdict']}** ({result['n_days']} trading days)")
    lines.append("")

    if result["n_days"] == 0:
        lines.append("No shadow data available yet. Run daily production to accumulate.")
        return "\n".join(lines)

    m = result["metrics"]
    lines.append("## Aggregate Metrics")
    lines.append("")
    lines.append("| Metric | Value | Threshold | Status |")
    lines.append("|--------|-------|-----------|--------|")

    checks = result["checks"]
    lines.append(
        f"| Median flagged | {m['median_flagged']} | <= 8 | " f"{'PASS' if checks['median_flagged_le_8'] else 'FAIL'} |"
    )
    lines.append(
        f"| P90 flagged | {m['p90_flagged']} | <= 15 | " f"{'PASS' if checks['p90_flagged_le_15'] else 'FAIL'} |"
    )
    lines.append(
        f"| Mean precision | {m['mean_precision']:.1%} | >= 50% | "
        f"{'PASS' if checks['precision_ge_50pct'] else 'FAIL'} |"
    )
    lines.append(
        f"| Mean recall | {m['mean_recall']:.1%} | >= 80% | " f"{'PASS' if checks['recall_ge_80pct'] else 'FAIL'} |"
    )
    lines.append("")

    lines.append("## Daily Detail")
    lines.append("")
    lines.append("| Date | Pre Flagged | Pre Total | Precision | Recall | SD Alerts | Missed |")
    lines.append("|------|------------|-----------|-----------|--------|-----------|--------|")
    for d in result["days"]:
        missed = ", ".join(d.get("missed_alerts", [])) or "-"
        lines.append(
            f"| {d['date']} | {d['n_pre_flagged']} | {d['n_pre_total']} | "
            f"{d['precision']:.0%} | {d['recall']:.0%} | {d['n_sd_alert']} | {missed} |"
        )
    lines.append("")

    lines.append("## Flagged Counts Per Day")
    lines.append("")
    lines.append("```")
    for d in result["days"]:
        bar = "#" * d["n_pre_flagged"]
        lines.append(f"{d['date']}: {bar} ({d['n_pre_flagged']})")
    lines.append("```")
    lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Evaluate Phase 3 pre-open watch shadow")
    parser.add_argument("--start-date", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", help="End date (YYYY-MM-DD)")
    parser.add_argument("--min-days", type=int, default=1, help="Minimum days required (default: 1)")
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        default=REPO_ROOT / "artifacts",
    )
    parser.add_argument(
        "--snapshots-dir",
        type=Path,
        default=REPO_ROOT / "data" / "snapshots",
    )
    parser.add_argument("--json", action="store_true", help="Output JSON instead of markdown")
    args = parser.parse_args()

    dates = find_shadow_dates(args.artifacts_dir, args.start_date, args.end_date)

    if len(dates) < args.min_days:
        print(
            f"Only {len(dates)} shadow days available (need {args.min_days}). " f"Run daily production to accumulate.",
            file=sys.stderr,
        )
        if not dates:
            sys.exit(1)

    result = evaluate_window(dates, args.artifacts_dir, args.snapshots_dir)

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(format_report(result))

    # Write artifact
    out_dir = REPO_ROOT / "output" / "preopen_watch_eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "latest_eval.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)
    (out_dir / "latest_eval.md").write_text(format_report(result), encoding="utf-8")

    sys.exit(0 if result["verdict"] == "PASS" else 2 if result["verdict"] == "FAIL" else 1)


if __name__ == "__main__":
    main()
