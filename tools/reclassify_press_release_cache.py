#!/usr/bin/env python3
"""CH-6: re-classify existing press-release cache under patched logic.

Reads every `classified_*.jsonl` in `data/press_releases/classified/`,
reconstructs a minimal raw record from each entry, and re-runs it through
`classify_releases([rec], use_grok=False)` with the current CH-1..CH-5 + P2
patched classifier.

Output goes to `data/press_releases/classified/reclassified/` — **originals
are NEVER overwritten** (CCFT "Frozen" rule). A per-file diff report and an
aggregate report are written to `reclassified/_reports/`.

Usage:
    python tools/reclassify_press_release_cache.py --dry-run
    python tools/reclassify_press_release_cache.py                  # all files
    python tools/reclassify_press_release_cache.py --dates 2026-04-17 2026-04-16
    python tools/reclassify_press_release_cache.py --limit 100      # first 100 records per file, for smoke tests

Governance: per CLAUDE.md North Star Rule this script produces evidence
only. The side-dir is NOT promoted to canonical automatically; a separate,
reviewed step is required to cut over.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.classify_press_releases import classify_releases  # noqa: E402

logger = logging.getLogger(__name__)

CLASSIFIED_DIR = PROJECT_ROOT / "data" / "press_releases" / "classified"
OUT_DIR = CLASSIFIED_DIR / "reclassified"
REPORT_DIR = OUT_DIR / "_reports"


@dataclass
class FileDiff:
    path: str
    n_original: int = 0
    n_reclassified: int = 0  # records kept after re-run (post new noise filter)
    n_dropped_as_new_noise: int = 0
    n_newly_collision_hard: int = 0
    n_newly_collision_soft: int = 0
    n_category_changed: int = 0
    n_informational_flip_on: int = 0  # was False, became True
    n_informational_flip_off: int = 0  # was True, became False
    n_confidence_moved_gt_0_1: int = 0
    examples_dropped_as_noise: List[Dict[str, str]] = field(default_factory=list)
    examples_new_hard_collision: List[Dict[str, str]] = field(default_factory=list)
    examples_new_soft_collision: List[Dict[str, str]] = field(default_factory=list)
    examples_category_changed: List[Dict[str, str]] = field(default_factory=list)


def _raw_from_classified(rec: Dict[str, Any]) -> Dict[str, Any]:
    """Reconstruct the minimal raw-record input shape that classify_releases expects."""
    return {
        "ticker": rec.get("ticker", ""),
        "company": rec.get("company", ""),
        "headline": rec.get("headline", ""),
        "source_url": rec.get("source_url", ""),
        "source_type": rec.get("source_type", "company_ir"),
        "published_at_utc": rec.get("published_at_utc", ""),
    }


def _example(rec: Dict[str, Any], extra: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    out = {
        "ticker": rec.get("ticker", ""),
        "headline": (rec.get("headline", "") or "")[:120],
    }
    if extra:
        out.update({k: str(v) for k, v in extra.items()})
    return out


def reclassify_file(src: Path, limit: Optional[int] = None) -> tuple[List[Dict[str, Any]], FileDiff]:
    """Re-classify one JSONL file. Returns the re-classified records and a diff."""
    diff = FileDiff(path=str(src.relative_to(CLASSIFIED_DIR)))
    originals: List[Dict[str, Any]] = []
    with open(src) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                originals.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if limit is not None:
        originals = originals[:limit]
    diff.n_original = len(originals)

    raw_records = [_raw_from_classified(r) for r in originals]
    new_classified = classify_releases(raw_records, use_grok=False)

    # Build an index by (ticker, headline) to rejoin originals with re-classified
    by_key: Dict[tuple, Dict[str, Any]] = {}
    for r in new_classified:
        key = (r.get("ticker", ""), r.get("headline", ""))
        by_key[key] = r

    kept: List[Dict[str, Any]] = []
    for orig in originals:
        key = (orig.get("ticker", ""), orig.get("headline", ""))
        new = by_key.get(key)
        if new is None:
            # Dropped by noise filter under new logic
            diff.n_dropped_as_new_noise += 1
            if len(diff.examples_dropped_as_noise) < 5:
                diff.examples_dropped_as_noise.append(_example(orig))
            continue

        # Merge: keep original event_id + classified_at_utc; overwrite other fields
        merged = dict(new)
        merged["event_id"] = orig.get("event_id", merged.get("event_id"))
        merged["classified_at_utc_original"] = orig.get("classified_at_utc", "")
        # classified_at_utc (new) comes from classify_releases fresh run — leave as-is

        # Diff accounting
        old_info = bool(orig.get("informational_only", False))
        new_info = bool(merged.get("informational_only", False))
        if old_info != new_info:
            if new_info:
                diff.n_informational_flip_on += 1
            else:
                diff.n_informational_flip_off += 1

        old_cat = orig.get("event_category", "")
        new_cat = merged.get("event_category", "")
        if old_cat and new_cat and old_cat != new_cat:
            diff.n_category_changed += 1
            if len(diff.examples_category_changed) < 5:
                diff.examples_category_changed.append(_example(orig, {"old": old_cat, "new": new_cat}))

        old_conf = float(orig.get("confidence", 0.0) or 0.0)
        new_conf = float(merged.get("confidence", 0.0) or 0.0)
        if abs(new_conf - old_conf) > 0.1:
            diff.n_confidence_moved_gt_0_1 += 1

        if merged.get("ticker_collision_flag"):
            sev = merged.get("collision_severity", "none")
            # Was it a collision before? Legacy records have flag=None or flag=False.
            was_collision = bool(orig.get("ticker_collision_flag", False))
            if not was_collision:
                if sev == "hard":
                    diff.n_newly_collision_hard += 1
                    if len(diff.examples_new_hard_collision) < 5:
                        diff.examples_new_hard_collision.append(_example(orig))
                elif sev == "soft":
                    diff.n_newly_collision_soft += 1
                    if len(diff.examples_new_soft_collision) < 5:
                        diff.examples_new_soft_collision.append(_example(orig))

        kept.append(merged)

    diff.n_reclassified = len(kept)
    return kept, diff


def write_output(src: Path, records: List[Dict[str, Any]]) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / src.name  # e.g., classified_2026-04-17.jsonl
    with open(out_path, "w") as f:
        for r in records:
            f.write(json.dumps(r, default=str) + "\n")
    return out_path


def write_per_file_report(diff: FileDiff) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rel = Path(diff.path).name.replace(".jsonl", ".diff.json")
    rpt = REPORT_DIR / rel
    with open(rpt, "w") as f:
        json.dump(diff.__dict__, f, indent=2, default=str)
    return rpt


def write_aggregate_report(diffs: List[FileDiff]) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    agg = {
        "files_processed": len(diffs),
        "totals": {
            "n_original": sum(d.n_original for d in diffs),
            "n_reclassified": sum(d.n_reclassified for d in diffs),
            "n_dropped_as_new_noise": sum(d.n_dropped_as_new_noise for d in diffs),
            "n_newly_collision_hard": sum(d.n_newly_collision_hard for d in diffs),
            "n_newly_collision_soft": sum(d.n_newly_collision_soft for d in diffs),
            "n_category_changed": sum(d.n_category_changed for d in diffs),
            "n_informational_flip_on": sum(d.n_informational_flip_on for d in diffs),
            "n_informational_flip_off": sum(d.n_informational_flip_off for d in diffs),
            "n_confidence_moved_gt_0_1": sum(d.n_confidence_moved_gt_0_1 for d in diffs),
        },
        "per_file": [d.__dict__ for d in diffs],
    }
    rpt = REPORT_DIR / "_aggregate.json"
    with open(rpt, "w") as f:
        json.dump(agg, f, indent=2, default=str)
    return rpt


def _select_files(dates: Optional[Iterable[str]]) -> List[Path]:
    if dates:
        want = set(dates)
        out = []
        for d in want:
            # Match classified_YYYY-MM-DD.jsonl and deduped_YYYY-MM-DD.jsonl
            for prefix in ("classified", "deduped"):
                p = CLASSIFIED_DIR / f"{prefix}_{d}.jsonl"
                if p.exists():
                    out.append(p)
        return sorted(out)
    return sorted(CLASSIFIED_DIR.glob("*.jsonl"))


def main() -> int:
    parser = argparse.ArgumentParser(description="CH-6 cache re-classification (CCFT: side-dir only)")
    parser.add_argument("--dates", nargs="*", help="YYYY-MM-DD list; default = all files in classified/")
    parser.add_argument("--dry-run", action="store_true", help="Do not write output files; report only")
    parser.add_argument("--limit", type=int, default=None, help="Per-file record limit (for smoke tests)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(message)s")

    files = _select_files(args.dates)
    if not files:
        print("No files selected.")
        return 1

    print(f"Re-classifying {len(files)} file(s) from {CLASSIFIED_DIR}")
    print(f"Output: {OUT_DIR}  Reports: {REPORT_DIR}")
    if args.dry_run:
        print("(dry-run: no files will be written)")

    diffs: List[FileDiff] = []
    for src in files:
        try:
            kept, diff = reclassify_file(src, limit=args.limit)
        except Exception as e:  # pragma: no cover
            logger.exception("Failed to re-classify %s: %s", src, e)
            continue
        if not args.dry_run:
            write_output(src, kept)
            write_per_file_report(diff)
        diffs.append(diff)
        print(
            f"  {diff.path:55} n={diff.n_original:>5}  "
            f"dropped(noise)={diff.n_dropped_as_new_noise:>3}  "
            f"coll(hard/soft)={diff.n_newly_collision_hard}/{diff.n_newly_collision_soft}  "
            f"cat_chg={diff.n_category_changed}  "
            f"info_on/off={diff.n_informational_flip_on}/{diff.n_informational_flip_off}"
        )

    if not args.dry_run:
        rpt = write_aggregate_report(diffs)
        print(f"\nAggregate report: {rpt}")

    totals = {
        "files": len(diffs),
        "n_original": sum(d.n_original for d in diffs),
        "n_reclassified": sum(d.n_reclassified for d in diffs),
        "n_dropped_as_new_noise": sum(d.n_dropped_as_new_noise for d in diffs),
        "n_newly_collision_hard": sum(d.n_newly_collision_hard for d in diffs),
        "n_newly_collision_soft": sum(d.n_newly_collision_soft for d in diffs),
        "n_category_changed": sum(d.n_category_changed for d in diffs),
        "n_informational_flip_on": sum(d.n_informational_flip_on for d in diffs),
        "n_informational_flip_off": sum(d.n_informational_flip_off for d in diffs),
    }
    print("\nTotals:")
    for k, v in totals.items():
        print(f"  {k:30} {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
