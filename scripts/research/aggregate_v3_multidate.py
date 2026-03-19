#!/usr/bin/env python3
"""Aggregate multi-date v3 phase score compare for default-on promotion.

Reads baseline and v3 snapshot rankings.csv files, computes per-date and
aggregate promotion gates matching the repo-native promotion checker.

Usage:
    python scripts/research/aggregate_v3_multidate.py \
        --baseline output/phase_v3_multidate/baseline \
        --candidate output/phase_v3_multidate/v3 \
        --output output/phase_v3_multidate/reports
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, Tuple


def load_rankings(snap_dir: Path) -> Tuple[Dict[str, int], Dict[str, str]]:
    """Load rankings.csv → (ticker→rank, ticker→tier_dev)."""
    path = snap_dir / "rankings.csv"
    if not path.exists():
        return {}, {}
    ranks = {}
    tiers = {}
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            t = r.get("ticker", "")
            ar = r.get("actionable_rank", "")
            if not t or not ar:
                continue
            try:
                ranks[t] = int(float(ar))
            except (ValueError, TypeError):
                continue
            tiers[t] = r.get("tier_dev", "")
    return ranks, tiers


def compare_date(base_dir: Path, cand_dir: Path, topk: int = 60) -> Dict[str, Any]:
    br, bt = load_rankings(base_dir)
    cr, ct = load_rankings(cand_dir)

    common = sorted(set(br) & set(cr))
    if not common:
        return {"status": "no_common_tickers"}

    shifts = {t: abs(br[t] - cr[t]) for t in common}
    signed_shifts = {t: cr[t] - br[t] for t in common}
    abs_shifts = list(shifts.values())

    base_topk = {t for t, rk in br.items() if rk <= topk}
    cand_topk = {t for t, rk in cr.items() if rk <= topk}
    overlap = len(base_topk & cand_topk) / max(len(base_topk), 1)

    base_top100 = {t for t, rk in br.items() if rk <= 100}
    cand_top100 = {t for t, rk in cr.items() if rk <= 100}
    overlap_100 = len(base_top100 & cand_top100) / max(len(base_top100), 1)

    # A-tier analysis
    a_base = {t for t in common if bt.get(t) == "A"}
    a_cand = {t for t in common if ct.get(t) == "A"}
    a_downgrades = sorted(a_base - a_cand)
    a_upgrades = sorted(a_cand - a_base)

    # Worst A-tier regression
    a_regression = 0
    for t in a_downgrades:
        a_regression = max(a_regression, signed_shifts.get(t, 0))

    # B-tier big shifts
    b_big = [t for t in common if bt.get(t) == "B" and shifts[t] > 5]

    # Largest movers
    top_movers = sorted(common, key=lambda t: -shifts[t])[:10]

    return {
        "n_common": len(common),
        "top60_overlap": round(overlap * 100, 1),
        "top100_overlap": round(overlap_100 * 100, 1),
        "mean_abs_shift": round(statistics.mean(abs_shifts), 2),
        "median_abs_shift": int(statistics.median(abs_shifts)),
        "max_shift": max(abs_shifts),
        "a_downgrades": a_downgrades,
        "a_upgrades": a_upgrades,
        "a_regression_worst": a_regression,
        "b_big_shifts": len(b_big),
        "entrants_topk": sorted(cand_topk - base_topk),
        "exits_topk": sorted(base_topk - cand_topk),
        "top_movers": [
            {
                "ticker": t,
                "base_rank": br[t],
                "cand_rank": cr[t],
                "shift": signed_shifts[t],
                "base_tier": bt.get(t, ""),
                "cand_tier": ct.get(t, ""),
            }
            for t in top_movers
        ],
    }


def main():
    parser = argparse.ArgumentParser(description="Aggregate multi-date v3 compare")
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("output/phase_v3_multidate/reports"))
    parser.add_argument("--topk", type=int, default=60)
    args = parser.parse_args()

    # Discover dates present in both baseline and candidate
    base_dates = {d.name for d in args.baseline.iterdir() if d.is_dir() and (d / "rankings.csv").exists()}
    cand_dates = {d.name for d in args.candidate.iterdir() if d.is_dir() and (d / "rankings.csv").exists()}
    dates = sorted(base_dates & cand_dates)

    if not dates:
        print("ERROR: No common dates found between baseline and candidate.")
        return 1

    print(f"Dates found: {len(dates)}")

    per_date = []
    for d in dates:
        result = compare_date(args.baseline / d, args.candidate / d, args.topk)
        result["date"] = d
        result["flagged"] = (
            result.get("top60_overlap", 0) < 90.0
            or result.get("max_shift", 999) > 30
            or result.get("a_regression_worst", 0) > 2
        )
        per_date.append(result)
        flag = " *** FLAGGED ***" if result["flagged"] else ""
        print(
            f"  {d}: top60={result['top60_overlap']}% max_shift={result['max_shift']} "
            f"A_down={len(result.get('a_downgrades', []))} mean={result['mean_abs_shift']}{flag}"
        )

    # Aggregate
    overlaps = [r["top60_overlap"] for r in per_date]
    max_shifts = [r["max_shift"] for r in per_date]
    mean_overlap = round(statistics.mean(overlaps), 2)
    min_overlap = min(overlaps)
    max_max_shift = max(max_shifts)
    total_a_downgrades = sum(len(r.get("a_downgrades", [])) for r in per_date)
    worst_a_regression = max(r.get("a_regression_worst", 0) for r in per_date)
    n_flagged = sum(1 for r in per_date if r["flagged"])

    promote = (
        min_overlap >= 90.0
        and mean_overlap >= 93.0
        and max_max_shift <= 30
        and worst_a_regression <= 2
        and n_flagged == 0
    )

    summary = {
        "dates_evaluated": len(per_date),
        "dates": dates,
        "mean_top60_overlap": mean_overlap,
        "min_top60_overlap": min_overlap,
        "max_rank_shift": max_max_shift,
        "total_a_downgrades": total_a_downgrades,
        "worst_a_regression": worst_a_regression,
        "n_flagged_dates": n_flagged,
        "promote_default_on": promote,
        "per_date": per_date,
    }

    args.output.mkdir(parents=True, exist_ok=True)

    # JSON
    json_path = args.output / "aggregate.json"
    json_path.write_text(json.dumps(summary, indent=2, default=str) + "\n")

    # Markdown
    md = _generate_md(summary, per_date)
    md_path = args.output / "aggregate.md"
    md_path.write_text(md)

    print(f"\n{'=' * 60}")
    print("AGGREGATE RESULT")
    print(f"{'=' * 60}")
    print(f"Dates evaluated:      {len(per_date)}")
    print(f"Mean top-60 overlap:  {mean_overlap}% (>= 93%: {'PASS' if mean_overlap >= 93.0 else 'FAIL'})")
    print(f"Min top-60 overlap:   {min_overlap}% (>= 90%: {'PASS' if min_overlap >= 90.0 else 'FAIL'})")
    print(f"Max rank shift:       {max_max_shift} (<= 30: {'PASS' if max_max_shift <= 30 else 'FAIL'})")
    print(f"A-tier downgrades:    {total_a_downgrades}")
    print(f"Worst A regression:   {worst_a_regression} (<= 2: {'PASS' if worst_a_regression <= 2 else 'FAIL'})")
    print(f"Flagged dates:        {n_flagged}")
    print(f"{'=' * 60}")
    print(f"VERDICT: {'PROMOTE DEFAULT-ON' if promote else 'HOLD'}")
    print(f"{'=' * 60}")
    print(f"\nWrote: {json_path}, {md_path}")

    return 0


def _generate_md(summary, per_date) -> str:
    promote = summary["promote_default_on"]
    lines = [
        "# Phase Scores V3 Multi-Date Promotion Compare",
        "",
        f"**Verdict: {'PROMOTE DEFAULT-ON' if promote else 'HOLD'}**",
        "",
        "## Aggregate Gates",
        "",
        "| Gate | Value | Threshold | Pass |",
        "|------|-------|-----------|------|",
        f"| Mean top-60 overlap | {summary['mean_top60_overlap']}% | >= 93% | {'YES' if summary['mean_top60_overlap'] >= 93.0 else 'NO'} |",
        f"| Min top-60 overlap | {summary['min_top60_overlap']}% | >= 90% | {'YES' if summary['min_top60_overlap'] >= 90.0 else 'NO'} |",
        f"| Max rank shift | {summary['max_rank_shift']} | <= 30 | {'YES' if summary['max_rank_shift'] <= 30 else 'NO'} |",
        f"| Worst A regression | {summary['worst_a_regression']} | <= 2 | {'YES' if summary['worst_a_regression'] <= 2 else 'NO'} |",
        f"| Flagged dates | {summary['n_flagged_dates']} | 0 | {'YES' if summary['n_flagged_dates'] == 0 else 'NO'} |",
        "",
        "## Per-Date Results",
        "",
        "| Date | N | Top-60 | Top-100 | Mean Shift | Max Shift | A Down | Flag |",
        "|------|---|--------|---------|-----------|-----------|--------|------|",
    ]
    for r in per_date:
        flag = "YES" if r.get("flagged") else ""
        lines.append(
            f"| {r['date']} | {r['n_common']} | {r['top60_overlap']}% | "
            f"{r['top100_overlap']}% | {r['mean_abs_shift']} | {r['max_shift']} | "
            f"{len(r.get('a_downgrades', []))} | {flag} |"
        )

    # Top-60 entrants/exits across dates
    all_entrants: Dict[str, int] = {}
    all_exits: Dict[str, int] = {}
    for r in per_date:
        for t in r.get("entrants_topk", []):
            all_entrants[t] = all_entrants.get(t, 0) + 1
        for t in r.get("exits_topk", []):
            all_exits[t] = all_exits.get(t, 0) + 1

    if all_entrants or all_exits:
        lines += ["", "## Top-60 Membership Changes (Across All Dates)", ""]
        if all_entrants:
            lines.append("**Entrants** (appear in v3 top-60 but not baseline):")
            for t, count in sorted(all_entrants.items(), key=lambda x: -x[1]):
                lines.append(f"- {t}: {count}/{len(per_date)} dates")
        if all_exits:
            lines.append("")
            lines.append("**Exits** (appear in baseline top-60 but not v3):")
            for t, count in sorted(all_exits.items(), key=lambda x: -x[1]):
                lines.append(f"- {t}: {count}/{len(per_date)} dates")

    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
