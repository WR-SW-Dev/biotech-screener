#!/usr/bin/env python3
"""CH-7: Escalation-pool purity audit.

Samples the pool of records that currently escalate for review (Grok or human)
and reports composition for purity adjudication. The escalation pool is defined as:

    needs_review == True
    AND informational_only == False
    AND ticker_collision_flag in (False, None)

This is the population a model swap (e.g., FinGPT) would have to demonstrate value
against. Target purity per the hardening spec: ≥ 80% legitimate biotech events.

The tool does NOT compute purity automatically — that requires human adjudication.
Instead, it prints a structured sample plus re-run noise/collision verdicts so a
reviewer can label each item quickly and compute the ratio.

Usage:
    python tools/audit_escalation_pool.py                       # canonical cache
    python tools/audit_escalation_pool.py --source reclassified # side-dir (post-fix)
    python tools/audit_escalation_pool.py --compare             # A/B numeric compare
    python tools/audit_escalation_pool.py --n 30 --seed 20260419
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.classify_press_releases import _is_noise, _is_ticker_collision, _load_company_names  # noqa: E402

CANONICAL_DIR = PROJECT_ROOT / "data" / "press_releases" / "classified"
RECLASSIFIED_DIR = CANONICAL_DIR / "reclassified"

DEFAULT_SAMPLE_N = 30
DEFAULT_SEED = 20260419

# Balanced category targets for a 30-item sample.
SAMPLE_TARGETS = {"clinical": 8, "regulatory": 6, "financing": 4, "mna": 3, "safety": 2, "other": 7}


def _iter_records(source_dir: Path, min_date: Optional[str] = None) -> List[Dict[str, Any]]:
    """Load JSONL records from a classified source directory.

    If `min_date` is provided (YYYY-MM-DD), only include files whose filename-
    embedded date is >= min_date. Useful post-cutover to audit fresh-cron output
    without the promoted historical cache diluting the sample.
    """
    records: List[Dict[str, Any]] = []
    for fp in sorted(source_dir.glob("classified_*.jsonl")):
        if min_date:
            stem_date = fp.stem.replace("classified_", "")
            if stem_date < min_date:
                continue
        with open(fp) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    # Also include deduped_*.jsonl archives — only if no min_date filter applied
    # (deduped files are bulk historical dumps and always pre-cutover).
    if not min_date:
        for fp in sorted(source_dir.glob("deduped_*.jsonl")):
            with open(fp) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    return records


def _in_escalation_pool(r: Dict[str, Any]) -> bool:
    if not r.get("needs_review"):
        return False
    if r.get("informational_only"):
        return False
    # ticker_collision_flag is None on legacy records, False on post-feature records
    # → both treat as "in the pool"; True means already suppressed.
    if r.get("ticker_collision_flag") is True:
        return False
    return True


def _dedupe(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out = []
    for r in records:
        key = r.get("dedupe_key") or (r.get("ticker", ""), r.get("headline", ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _sample_balanced(
    pool: List[Dict[str, Any]],
    n: int,
    rng: random.Random,
    targets: Optional[Dict[str, int]] = None,
) -> List[Dict[str, Any]]:
    targets = targets or SAMPLE_TARGETS
    by_cat: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in pool:
        by_cat[r.get("event_category", "other")].append(r)
    for cat in by_cat:
        rng.shuffle(by_cat[cat])
    chosen: List[Dict[str, Any]] = []
    for cat, want in targets.items():
        chosen.extend(by_cat.get(cat, [])[:want])
    # Fill shortfall from any remaining pool
    if len(chosen) < n:
        used = {id(r) for r in chosen}
        remaining = [r for r in pool if id(r) not in used]
        rng.shuffle(remaining)
        chosen.extend(remaining[: n - len(chosen)])
    return chosen[:n]


def _rerun_verdicts(r: Dict[str, Any], company_names: Dict[str, List[str]]) -> Tuple[bool, bool]:
    """Returns (is_noise_now, is_collision_now) under current patched code."""
    hl = r.get("headline", "")
    tk = (r.get("ticker", "") or "").upper()
    return _is_noise(hl), _is_ticker_collision(hl, tk, company_names)


def _pool_stats(pool: List[Dict[str, Any]]) -> Dict[str, Any]:
    cats = Counter(r.get("event_category", "other") for r in pool)
    conf_buckets = Counter()
    for r in pool:
        c = float(r.get("confidence", 0) or 0)
        if c < 0.3:
            conf_buckets["<0.3"] += 1
        elif c < 0.5:
            conf_buckets["0.3-0.5"] += 1
        elif c < 0.7:
            conf_buckets["0.5-0.7"] += 1
        else:
            conf_buckets[">=0.7"] += 1
    return {
        "pool_size": len(pool),
        "by_category": dict(cats),
        "by_confidence": dict(conf_buckets),
    }


def audit(source_dir: Path, n: int, seed: int, min_date: Optional[str] = None) -> Dict[str, Any]:
    all_records = _iter_records(source_dir, min_date=min_date)
    pool_raw = [r for r in all_records if _in_escalation_pool(r)]
    pool = _dedupe(pool_raw)
    company_names = _load_company_names()

    sample = _sample_balanced(pool, n, random.Random(seed))

    # Compute re-run verdicts on the sample
    rerun_counts = Counter()
    sample_rows = []
    for r in sample:
        noise_now, coll_now = _rerun_verdicts(r, company_names)
        tag = "clean" if not (noise_now or coll_now) else ("noise" if noise_now else "collision")
        rerun_counts[tag] += 1
        sample_rows.append(
            {
                "event_id": r.get("event_id", ""),
                "ticker": r.get("ticker", ""),
                "headline": r.get("headline", ""),
                "stored_category": r.get("event_category", ""),
                "stored_confidence": r.get("confidence", 0),
                "stored_outcome": r.get("event_outcome_guess", ""),
                "rerun_noise": noise_now,
                "rerun_collision": coll_now,
                "rerun_tag": tag,
                "manual_label": "",  # placeholder — reviewer fills in
            }
        )

    return {
        "source_dir": str(source_dir.relative_to(PROJECT_ROOT)),
        "min_date_filter": min_date,
        "raw_record_count": len(all_records),
        "raw_pool_count": len(pool_raw),
        "pool_count_deduped": len(pool),
        "pool_stats": _pool_stats(pool),
        "sample_n": len(sample),
        "sample_seed": seed,
        "sample_rerun_counts": dict(rerun_counts),
        "sample_rows": sample_rows,
    }


def print_report(report: Dict[str, Any]) -> None:
    src = report["source_dir"]
    print(f"\n=== Escalation-pool audit — {src} ===")
    print(f"Raw records read:       {report['raw_record_count']}")
    print(f"Raw escalation pool:    {report['raw_pool_count']}")
    print(f"Pool (deduped):         {report['pool_count_deduped']}")
    ps = report["pool_stats"]
    print(f"Pool by category:       {ps['by_category']}")
    print(f"Pool by confidence:     {ps['by_confidence']}")
    print(f"\nSample (n={report['sample_n']}, seed={report['sample_seed']}):")
    print(f"  Re-run verdicts:       {report['sample_rerun_counts']}")
    for row in report["sample_rows"]:
        tag = row["rerun_tag"].upper()
        print(
            f"  [{tag:9}] {row['ticker']:6} {row['stored_category']:10} "
            f"c={row['stored_confidence']:.2f}  {row['headline'][:90]}"
        )


def compare(a: Dict[str, Any], b: Dict[str, Any]) -> None:
    print("\n=== A/B comparison ===")
    print(f"{'':28}  {a['source_dir']:<35}  {b['source_dir']}")
    print(f"{'Raw records':28}  {a['raw_record_count']:<35}  {b['raw_record_count']}")
    print(f"{'Pool (raw)':28}  {a['raw_pool_count']:<35}  {b['raw_pool_count']}")
    print(f"{'Pool (deduped)':28}  {a['pool_count_deduped']:<35}  {b['pool_count_deduped']}")
    a_cats = a["pool_stats"]["by_category"]
    b_cats = b["pool_stats"]["by_category"]
    all_cats = sorted(set(list(a_cats.keys()) + list(b_cats.keys())))
    print(f"{'Pool by category':28}")
    for c in all_cats:
        print(f"  {c:26}  {str(a_cats.get(c, 0)):<35}  {b_cats.get(c, 0)}")
    print(f"\n{'Sample re-run verdicts':28}")
    for tag in ("clean", "collision", "noise"):
        print(f"  {tag:26}  {str(a['sample_rerun_counts'].get(tag, 0)):<35}  {b['sample_rerun_counts'].get(tag, 0)}")


def _source_path(which: str) -> Path:
    if which == "reclassified":
        return RECLASSIFIED_DIR
    return CANONICAL_DIR


def main() -> int:
    parser = argparse.ArgumentParser(description="CH-7 escalation-pool purity audit")
    parser.add_argument("--source", choices=["canonical", "reclassified"], default="canonical")
    parser.add_argument("--compare", action="store_true", help="Run against BOTH canonical and reclassified, print A/B")
    parser.add_argument("--n", type=int, default=DEFAULT_SAMPLE_N)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--min-date",
        type=str,
        default=None,
        help="YYYY-MM-DD; include only classified_*.jsonl files on/after this date "
        "(skips deduped bulk files). Use post-cutover to audit fresh cron output.",
    )
    parser.add_argument(
        "--json-out", type=Path, default=None, help="Write full audit JSON here (per-source if --compare)"
    )
    args = parser.parse_args()

    if args.compare:
        a = audit(CANONICAL_DIR, args.n, args.seed, min_date=args.min_date)
        b = audit(RECLASSIFIED_DIR, args.n, args.seed, min_date=args.min_date)
        print_report(a)
        print_report(b)
        compare(a, b)
        if args.json_out:
            args.json_out.write_text(json.dumps({"canonical": a, "reclassified": b}, indent=2, default=str))
    else:
        src = _source_path(args.source)
        report = audit(src, args.n, args.seed, min_date=args.min_date)
        print_report(report)
        if args.json_out:
            args.json_out.write_text(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
