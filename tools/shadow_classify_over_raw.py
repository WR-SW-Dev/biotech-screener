#!/usr/bin/env python3
"""Shadow run: apply the patched classifier to historical raw press releases
and compare against the canonical classified output.

This is a retroactive equivalent of spec §8's "7-day shadow run" — because
raw `releases_YYYY-MM-DD.jsonl` files are archived and canonical
`classified_YYYY-MM-DD.jsonl` files were produced by the pre-patch code,
we can diff old vs new without waiting for calendar days to accumulate.

Writes shadow output to `data/press_releases/classified_shadow/` and
per-date + aggregate diff reports to `_reports/`. Never modifies canonical.

Usage:
    python tools/shadow_classify_over_raw.py                       # all available raw/classified pairs
    python tools/shadow_classify_over_raw.py --dates 2026-04-17 2026-04-16
    python tools/shadow_classify_over_raw.py --min-date 2026-04-07
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.classify_press_releases import classify_releases  # noqa: E402

RAW_DIR = PROJECT_ROOT / "data" / "press_releases"
CANONICAL_DIR = RAW_DIR / "classified"
SHADOW_DIR = RAW_DIR / "classified_shadow"
REPORT_DIR = SHADOW_DIR / "_reports"


@dataclass
class DayDiff:
    date: str
    raw_count: int = 0
    canonical_count: int = 0
    shadow_count: int = 0
    # By (ticker, headline) keys:
    only_in_canonical: int = 0  # old classified it, new drops as noise
    only_in_shadow: int = 0  # new emits, old dropped (probably none — new is STRICTLY more selective on noise)
    in_both: int = 0
    # Among `in_both`:
    new_collision_hard: int = 0
    new_collision_soft: int = 0
    category_changed: int = 0
    informational_flip_on: int = 0
    informational_flip_off: int = 0
    confidence_moved_gt_0_1: int = 0
    examples_only_in_canonical: List[Dict[str, str]] = field(default_factory=list)
    examples_new_collision_soft: List[Dict[str, str]] = field(default_factory=list)
    examples_new_collision_hard: List[Dict[str, str]] = field(default_factory=list)


def _load(path: Path) -> List[Dict[str, Any]]:
    out = []
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _example(rec: Dict[str, Any], extra: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    out = {"ticker": rec.get("ticker", ""), "headline": (rec.get("headline", "") or "")[:120]}
    if extra:
        out.update({k: str(v) for k, v in extra.items()})
    return out


def run_day(d: str) -> DayDiff:
    diff = DayDiff(date=d)
    raw_path = RAW_DIR / f"releases_{d}.jsonl"
    canonical_path = CANONICAL_DIR / f"classified_{d}.jsonl"
    raw = _load(raw_path)
    canonical = _load(canonical_path)
    diff.raw_count = len(raw)
    diff.canonical_count = len(canonical)

    # Run patched classifier on raw
    shadow = classify_releases(raw, use_grok=False)
    diff.shadow_count = len(shadow)

    # Write shadow output
    SHADOW_DIR.mkdir(parents=True, exist_ok=True)
    out_path = SHADOW_DIR / f"classified_{d}.jsonl"
    with open(out_path, "w") as f:
        for r in shadow:
            f.write(json.dumps(r, default=str) + "\n")

    # Index by (ticker, headline) — stable join key
    def key_of(r):
        return (r.get("ticker", ""), r.get("headline", ""))

    canon_by_key = {key_of(r): r for r in canonical}
    shadow_by_key = {key_of(r): r for r in shadow}

    canon_keys = set(canon_by_key.keys())
    shadow_keys = set(shadow_by_key.keys())
    both = canon_keys & shadow_keys
    diff.in_both = len(both)
    diff.only_in_canonical = len(canon_keys - shadow_keys)
    diff.only_in_shadow = len(shadow_keys - canon_keys)

    for key in canon_keys - shadow_keys:
        if len(diff.examples_only_in_canonical) < 5:
            diff.examples_only_in_canonical.append(_example(canon_by_key[key]))

    for key in both:
        old = canon_by_key[key]
        new = shadow_by_key[key]

        # Collision transitions
        new_flag = bool(new.get("ticker_collision_flag"))
        old_flag = bool(old.get("ticker_collision_flag"))
        if new_flag and not old_flag:
            sev = new.get("collision_severity", "none")
            if sev == "hard":
                diff.new_collision_hard += 1
                if len(diff.examples_new_collision_hard) < 5:
                    diff.examples_new_collision_hard.append(_example(new))
            elif sev == "soft":
                diff.new_collision_soft += 1
                if len(diff.examples_new_collision_soft) < 5:
                    diff.examples_new_collision_soft.append(_example(new))

        # Category change
        oc = old.get("event_category", "")
        nc = new.get("event_category", "")
        if oc and nc and oc != nc:
            diff.category_changed += 1

        # informational_only flips
        oi = bool(old.get("informational_only", False))
        ni = bool(new.get("informational_only", False))
        if oi != ni:
            if ni:
                diff.informational_flip_on += 1
            else:
                diff.informational_flip_off += 1

        # Confidence moved
        ocf = float(old.get("confidence", 0) or 0)
        ncf = float(new.get("confidence", 0) or 0)
        if abs(ncf - ocf) > 0.1:
            diff.confidence_moved_gt_0_1 += 1

    return diff


def _select_dates(dates: Optional[List[str]], min_date: Optional[str], max_date: Optional[str]) -> List[str]:
    if dates:
        return sorted(dates)
    found = sorted({p.stem.replace("releases_", "") for p in RAW_DIR.glob("releases_*.jsonl")})

    def in_range(d):
        if min_date and d < min_date:
            return False
        if max_date and d > max_date:
            return False
        return True

    return [d for d in found if in_range(d)]


def write_aggregate(diffs: List[DayDiff]) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    agg = {
        "days": len(diffs),
        "totals": {
            "raw_count": sum(d.raw_count for d in diffs),
            "canonical_count": sum(d.canonical_count for d in diffs),
            "shadow_count": sum(d.shadow_count for d in diffs),
            "only_in_canonical": sum(d.only_in_canonical for d in diffs),
            "only_in_shadow": sum(d.only_in_shadow for d in diffs),
            "in_both": sum(d.in_both for d in diffs),
            "new_collision_hard": sum(d.new_collision_hard for d in diffs),
            "new_collision_soft": sum(d.new_collision_soft for d in diffs),
            "category_changed": sum(d.category_changed for d in diffs),
            "informational_flip_on": sum(d.informational_flip_on for d in diffs),
            "informational_flip_off": sum(d.informational_flip_off for d in diffs),
            "confidence_moved_gt_0_1": sum(d.confidence_moved_gt_0_1 for d in diffs),
        },
        "per_day": [d.__dict__ for d in diffs],
    }
    path = REPORT_DIR / "_aggregate.json"
    path.write_text(json.dumps(agg, indent=2, default=str))
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Shadow run (retroactive) for classifier hardening")
    parser.add_argument("--dates", nargs="*")
    parser.add_argument("--min-date")
    parser.add_argument("--max-date")
    args = parser.parse_args()

    dates = _select_dates(args.dates, args.min_date, args.max_date)
    if not dates:
        print("No date range selected / raw files not found.")
        return 1

    print(f"Shadow run over {len(dates)} day(s):  {dates[0]} → {dates[-1]}")
    print(f"Shadow output: {SHADOW_DIR}")
    print(f"Reports: {REPORT_DIR}")
    print()
    print(
        f"{'date':12}  {'raw':>4}  {'canon':>5}  {'shadow':>6}  "
        f"{'only_can':>8}  {'new_hard':>8}  {'new_soft':>8}  {'cat_chg':>7}  {'info_on/off':>11}"
    )

    diffs: List[DayDiff] = []
    for d in dates:
        diff = run_day(d)
        diffs.append(diff)
        print(
            f"{diff.date:12}  {diff.raw_count:>4}  {diff.canonical_count:>5}  "
            f"{diff.shadow_count:>6}  {diff.only_in_canonical:>8}  "
            f"{diff.new_collision_hard:>8}  {diff.new_collision_soft:>8}  "
            f"{diff.category_changed:>7}  {diff.informational_flip_on:>4}/{diff.informational_flip_off:<4}"
        )

    rpt = write_aggregate(diffs)
    print(f"\nAggregate report: {rpt}")

    t = {
        "raw_count": sum(d.raw_count for d in diffs),
        "canonical_count": sum(d.canonical_count for d in diffs),
        "shadow_count": sum(d.shadow_count for d in diffs),
        "only_in_canonical": sum(d.only_in_canonical for d in diffs),
        "new_collision_hard": sum(d.new_collision_hard for d in diffs),
        "new_collision_soft": sum(d.new_collision_soft for d in diffs),
        "category_changed": sum(d.category_changed for d in diffs),
        "informational_flip_on": sum(d.informational_flip_on for d in diffs),
        "informational_flip_off": sum(d.informational_flip_off for d in diffs),
    }
    print("\nTotals:")
    for k, v in t.items():
        print(f"  {k:30}  {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
