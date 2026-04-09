#!/usr/bin/env python3
"""Herald ground truth sampler -- build labeled dataset for precision audit.

Creates a stratified sample of classified press releases, auto-labels from
CRT resolutions where possible, and generates a markdown review sheet for
human annotation.

Usage:
    python scripts/research/herald_ground_truth_sampler.py --n-samples 100
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

CLASSIFIED_DIR = PROJECT_ROOT / "data" / "press_releases" / "classified"
RESOLUTIONS_DIR = PROJECT_ROOT / "data" / "snapshots" / "resolutions"
OUTPUT_DIR = PROJECT_ROOT / "artifacts" / "herald_ground_truth"

SCHEMA = "herald_ground_truth.v1"

GT_FIELDS = [
    "gt_event_category",
    "gt_event_subtype",
    "gt_severity",
    "gt_informational_only",
    "gt_outcome",
    "gt_noise",
    "gt_correct_ticker",
    "gt_label_source",
    "gt_reviewer",
    "gt_review_date",
]

logger = logging.getLogger(__name__)


def load_classified_records(classified_dir: Path, max_days: int = 30) -> list[dict]:
    """Load recent classified press releases from JSONL files."""
    records = []
    files = sorted(classified_dir.glob("classified_*.jsonl"), reverse=True)
    for f in files[:max_days]:
        try:
            for line in f.read_text().splitlines():
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        except Exception as e:
            logger.warning("Error reading %s: %s", f.name, e)
    logger.info("Loaded %d classified records from %d files", len(records), min(len(files), max_days))
    return records


def load_crt_resolutions(resolutions_dir: Path) -> list[dict]:
    """Load all CRT resolution records."""
    resolutions = []
    if not resolutions_dir.exists():
        logger.warning("Resolutions directory not found: %s", resolutions_dir)
        return resolutions
    for month_dir in resolutions_dir.iterdir():
        if not month_dir.is_dir():
            continue
        for f in month_dir.glob("*.json"):
            try:
                resolutions.append(json.loads(f.read_text()))
            except Exception as e:
                logger.warning("Error reading %s: %s", f, e)
    logger.info("Loaded %d CRT resolutions", len(resolutions))
    return resolutions


def stratified_sample(
    records: list[dict],
    n_total: int = 100,
    min_per_category: int = 5,
    seed: int = 42,
    oversample_confused: bool = False,
    oversample_sec_near: bool = False,
) -> list[dict]:
    """Stratified sample by event_category with minimum representation.

    Oversampling modes (fill from special pools before proportional fill):
    - oversample_confused: records tagged informational but with large price moves
    - oversample_sec_near: SEC-sourced records with catalyst <= 30d
    """
    rng = random.Random(seed)

    # Group by category
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        cat = r.get("event_category", "unknown") or "unknown"
        by_cat[cat].append(r)

    # Ensure minimum per non-empty category
    sampled: list[dict] = []
    sampled_ids: set = set()
    remaining_budget = n_total
    categories = sorted(by_cat.keys())

    # First pass: guarantee minimums
    for cat in categories:
        pool = by_cat[cat]
        take = min(min_per_category, len(pool), remaining_budget)
        if take > 0:
            chosen = rng.sample(pool, take)
            sampled.extend(chosen)
            for c in chosen:
                sampled_ids.add(c.get("event_id"))
            remaining_budget -= take
            by_cat[cat] = [r for r in pool if r.get("event_id") not in sampled_ids]

    # Oversampling pass: confused records (informational with large moves)
    if oversample_confused and remaining_budget > 0:
        confused = [
            r
            for r in records
            if r.get("event_id") not in sampled_ids and r.get("informational_only") is True and _has_large_move(r)
        ]
        take = min(remaining_budget // 4, len(confused))  # up to 25% budget
        if take > 0:
            chosen = rng.sample(confused, take)
            sampled.extend(chosen)
            for c in chosen:
                sampled_ids.add(c.get("event_id"))
            remaining_budget -= take
            logger.info("Oversampled %d confused (informational+large-move) records", take)

    # Oversampling pass: SEC-sourced near-catalyst
    if oversample_sec_near and remaining_budget > 0:
        sec_near = [
            r
            for r in records
            if r.get("event_id") not in sampled_ids
            and "SEC" in (r.get("source_type", "") or "").upper()
            and _is_near_catalyst(r)
        ]
        take = min(remaining_budget // 4, len(sec_near))  # up to 25% budget
        if take > 0:
            chosen = rng.sample(sec_near, take)
            sampled.extend(chosen)
            for c in chosen:
                sampled_ids.add(c.get("event_id"))
            remaining_budget -= take
            logger.info("Oversampled %d SEC near-catalyst records", take)

    # Second pass: fill proportionally from remaining pool
    if remaining_budget > 0:
        remaining_pool = [r for r in records if r.get("event_id") not in sampled_ids]
        if remaining_pool:
            take = min(remaining_budget, len(remaining_pool))
            sampled.extend(rng.sample(remaining_pool, take))

    return sampled


def _has_large_move(record: dict) -> bool:
    """Check if a record had a large price move (>5% abs return)."""
    try:
        ret = abs(float(record.get("price_reaction_1d", 0) or 0))
        return ret > 0.05
    except (ValueError, TypeError):
        return False


def _is_near_catalyst(record: dict) -> bool:
    """Check if a record has a near-term catalyst (<=30d)."""
    try:
        days = float(record.get("catalyst_days", 999) or 999)
        return days <= 30
    except (ValueError, TypeError):
        return False


def auto_label_from_crt(
    sample: list[dict],
    resolutions: list[dict],
    match_window_days: int = 3,
) -> list[dict]:
    """Auto-populate gt_* fields where CRT resolution matches."""
    # Build resolution index: {ticker: [(catalyst_date, resolution)]}
    res_index: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for r in resolutions:
        tk = r.get("ticker", "")
        cd = r.get("catalyst_date", "")
        if tk and cd:
            res_index[tk].append((cd, r))

    # CRT catalyst_type -> Herald event_category mapping
    type_to_cat = {
        "PDUFA_ACTION": "regulatory",
        "NDA_BLA_FILING": "regulatory",
        "REGULATORY_DESIGNATION": "regulatory",
        "ADVISORY_COMMITTEE": "regulatory",
        "PHASE_3_READOUT": "clinical",
        "PHASE_2_READOUT": "clinical",
        "PHASE_1_DATA": "clinical",
        "DATA_READOUT": "clinical",
        "CORPORATE_UPDATE": "other",
    }

    n_matched = 0
    for rec in sample:
        # Add gt_* fields
        for f in GT_FIELDS:
            if f not in rec:
                rec[f] = None
        rec["gt_label_source"] = "unlabeled"

        tk = rec.get("ticker", "")
        pub_date = rec.get("published_at_utc", "")[:10]
        if not tk or not pub_date or tk not in res_index:
            continue

        try:
            pub_d = datetime.strptime(pub_date, "%Y-%m-%d").date()
        except ValueError:
            continue

        # Find matching resolution within window
        for cat_date_str, res in res_index[tk]:
            try:
                cat_d = datetime.strptime(cat_date_str, "%Y-%m-%d").date()
            except ValueError:
                continue
            if abs((pub_d - cat_d).days) <= match_window_days:
                # Match found
                rec["gt_label_source"] = "crt_auto"
                crt_type = res.get("catalyst_type", "")
                rec["gt_event_category"] = type_to_cat.get(crt_type, "other")
                rec["gt_outcome"] = (res.get("outcome", "") or "").lower()
                n_matched += 1
                break

    logger.info("Auto-labeled %d/%d records from CRT", n_matched, len(sample))
    return sample


def generate_review_sheet(labeled_sample: list[dict], output_path: Path) -> None:
    """Write markdown review sheet for human annotation."""
    lines = [
        "# Herald Ground Truth Review Sheet",
        "",
        f"Generated: {datetime.now().isoformat()[:19]}",
        f"Records: {len(labeled_sample)}",
        "",
        "## Instructions",
        "For each record, review the headline and Herald classification.",
        "Fill in the `gt_*` fields. Mark `gt_noise=true` if the record should have been filtered.",
        "Mark `gt_correct_ticker=false` if the headline does not relate to the assigned ticker.",
        "",
        "---",
        "",
    ]

    for i, rec in enumerate(labeled_sample, 1):
        lines.append(f"### Record {i}")
        lines.append("")
        lines.append(f"- **Ticker**: {rec.get('ticker', '?')}")
        lines.append(f"- **Date**: {rec.get('published_at_utc', '?')[:10]}")
        lines.append(f"- **Headline**: {rec.get('headline', '?')}")
        lines.append(f"- **Source**: {rec.get('source_type', '?')}")
        lines.append("")
        lines.append("**Herald classification:**")
        lines.append(f"- event_category: `{rec.get('event_category', '?')}`")
        lines.append(f"- event_subtype: `{rec.get('event_subtype', '?')}`")
        lines.append(f"- severity: `{rec.get('severity', '?')}`")
        lines.append(f"- confidence: `{rec.get('confidence', '?')}`")
        lines.append(f"- informational_only: `{rec.get('informational_only', '?')}`")
        lines.append("")

        if rec.get("gt_label_source") == "crt_auto":
            lines.append("**Auto-label (CRT):**")
            lines.append(f"- gt_event_category: `{rec.get('gt_event_category', '')}`")
            lines.append(f"- gt_outcome: `{rec.get('gt_outcome', '')}`")
            lines.append("")

        lines.append("**Human review:**")
        lines.append(f"- gt_event_category: `{rec.get('gt_event_category', '')}`")
        lines.append("- gt_noise: ``")
        lines.append("- gt_correct_ticker: ``")
        lines.append("")
        lines.append("---")
        lines.append("")

    output_path.write_text("\n".join(lines))
    logger.info("Review sheet written: %s", output_path)


def main():
    parser = argparse.ArgumentParser(description="Herald ground truth sampler")
    parser.add_argument("--classified-dir", type=Path, default=CLASSIFIED_DIR)
    parser.add_argument("--resolutions-dir", type=Path, default=RESOLUTIONS_DIR)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument(
        "--n-samples", "--target-n", type=int, default=100, help="Target number of samples (default: 100)"
    )
    parser.add_argument("--min-per-category", type=int, default=5)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--oversample-confused", action="store_true", help="Oversample informational records with large price moves"
    )
    parser.add_argument(
        "--oversample-sec-near", action="store_true", help="Oversample SEC-sourced near-catalyst records"
    )
    parser.add_argument("--as-of-date", default=date.today().isoformat())
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    records = load_classified_records(args.classified_dir)
    if not records:
        logger.error("No classified records found in %s", args.classified_dir)
        sys.exit(1)

    sample = stratified_sample(
        records,
        args.n_samples,
        args.min_per_category,
        args.seed,
        oversample_confused=args.oversample_confused,
        oversample_sec_near=args.oversample_sec_near,
    )
    logger.info("Sampled %d records", len(sample))

    resolutions = load_crt_resolutions(args.resolutions_dir)
    sample = auto_label_from_crt(sample, resolutions)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    as_of = args.as_of_date

    # Write JSONL (batch format for accumulation)
    gt_batch_dir = PROJECT_ROOT / "data" / "ground_truth"
    gt_batch_dir.mkdir(parents=True, exist_ok=True)
    batch_path = gt_batch_dir / f"batch_{as_of}.jsonl"
    with open(batch_path, "w") as f:
        for rec in sample:
            f.write(json.dumps(rec, default=str) + "\n")
    logger.info("Batch JSONL: %s", batch_path)

    # Also write to legacy output dir
    jsonl_path = args.output_dir / f"sample_{as_of}.jsonl"
    with open(jsonl_path, "w") as f:
        for rec in sample:
            f.write(json.dumps(rec, default=str) + "\n")
    logger.info("Sample JSONL: %s", jsonl_path)

    # Write review sheet
    review_path = args.output_dir / f"review_sheet_{as_of}.md"
    generate_review_sheet(sample, review_path)

    # Write stats
    cats = defaultdict(int)
    for r in sample:
        cats[r.get("event_category", "unknown")] += 1
    n_auto = sum(1 for r in sample if r.get("gt_label_source") == "crt_auto")

    stats = {
        "schema": SCHEMA,
        "as_of_date": as_of,
        "n_sampled": len(sample),
        "n_auto_labeled": n_auto,
        "n_unlabeled": len(sample) - n_auto,
        "category_distribution": dict(sorted(cats.items())),
    }
    stats_path = args.output_dir / f"label_stats_{as_of}.json"
    stats_path.write_text(json.dumps(stats, indent=2))

    print(f"\nHERALD GROUND TRUTH SAMPLER -- {as_of}")
    print(f"  Sampled: {len(sample)} records")
    print(f"  Auto-labeled (CRT): {n_auto}")
    print(f"  Categories: {dict(sorted(cats.items()))}")
    print(f"  JSONL: {jsonl_path}")
    print(f"  Review sheet: {review_path}")


if __name__ == "__main__":
    main()
