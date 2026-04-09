#!/usr/bin/env python3
"""Label existing benchmark artifacts with pseudo_pit_version = 1.

Scans output/benchmarks/ and output/selection_benchmark/ for JSON files
that lack a pseudo_pit_version field and stamps them as v1 (contaminated).

Also creates output/pit/labeling_log.json with a record of what was touched.

Usage:
    python tools/pit_label_benchmarks.py
    python tools/pit_label_benchmarks.py --dry-run
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_DIRS = [
    PROJECT_ROOT / "output" / "benchmarks",
    PROJECT_ROOT / "output" / "selection_benchmark",
]
PIT_OUTPUT = PROJECT_ROOT / "output" / "pit"


def label_file(path: Path, dry_run: bool) -> dict | None:
    """Add pseudo_pit_version=1 to a JSON benchmark file if missing."""
    try:
        with open(path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        return None

    if not isinstance(data, dict):
        return None

    if "pseudo_pit_version" in data:
        return None  # already labeled

    record = {
        "file": str(path.relative_to(PROJECT_ROOT)),
        "action": "labeled_v1",
        "had_version": False,
    }

    if not dry_run:
        data["pseudo_pit_version"] = 1
        data["pit_version_note"] = (
            "Labeled pseudo-PIT v1: generated from retro-regenerated snapshots "
            "with known survivorship contamination. See spec_048_pit_remediation_plan.md."
        )
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    return record


def main():
    parser = argparse.ArgumentParser(description="Label benchmark artifacts as pseudo-PIT v1")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be labeled without writing")
    args = parser.parse_args()

    labeled = []
    skipped = 0

    for bdir in BENCHMARK_DIRS:
        if not bdir.exists():
            continue
        for jf in sorted(bdir.glob("*.json")):
            result = label_file(jf, args.dry_run)
            if result:
                labeled.append(result)
            else:
                skipped += 1

    prefix = "[DRY-RUN] " if args.dry_run else ""
    print(f"{prefix}Labeled: {len(labeled)} files")
    print(f"{prefix}Skipped: {skipped} (already labeled or not JSON dicts)")

    for r in labeled:
        print(f"  {r['file']}")

    if not args.dry_run and labeled:
        PIT_OUTPUT.mkdir(parents=True, exist_ok=True)
        log_path = PIT_OUTPUT / "labeling_log.json"
        log_data = {
            "labeled_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "files_labeled": len(labeled),
            "files_skipped": skipped,
            "details": labeled,
        }
        with open(log_path, "w") as f:
            json.dump(log_data, f, indent=2)
        print(f"\nLog written to: {log_path}")


if __name__ == "__main__":
    main()
