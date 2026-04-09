#!/usr/bin/env python3
"""Difference audit: which names enter/exit top-K due to flatten-tier.

Compares baseline vs flatten-tier reranked snapshots within binary_91_180
and reports which tickers move in/out of top-K, along with their tier,
clinical score, optionality, and catalyst_days.

Usage:
    python3 scripts/research/diff_audit_flatten_tier.py \\
        --baseline-root data/snapshots_reranked_baseline \\
        --candidate-root data/snapshots_reranked_v1100 \\
        --top-k 20 \\
        --out output/diff_audit_flatten_tier.md
"""

from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from common.ranking_utils import safe_float as _safe_float
from decision_engine import assign_catalyst_bucket


def _load_ranked(snap_dir: Path, top_k: int) -> Dict[str, dict]:
    """Load rankings.csv and return {ticker: row} for top-K eligible names."""
    path = snap_dir / "rankings.csv"
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    result = {}
    for r in rows:
        ar = r.get("actionable_rank", "")
        if not ar:
            continue
        try:
            rank = int(float(ar))
        except (ValueError, TypeError):
            continue
        if rank <= top_k:
            result[r.get("ticker", "")] = r
    return result


def diff_audit(
    baseline_root: Path,
    candidate_root: Path,
    top_k: int = 20,
) -> dict:
    """Compare baseline vs candidate, return diff stats."""
    baseline_dates = sorted(
        d.name for d in baseline_root.iterdir() if d.is_dir() and not d.name.startswith("_") and len(d.name) == 10
    )
    candidate_dates = sorted(
        d.name for d in candidate_root.iterdir() if d.is_dir() and not d.name.startswith("_") and len(d.name) == 10
    )
    common_dates = sorted(set(baseline_dates) & set(candidate_dates))

    enters: List[dict] = []  # names that enter top-K in candidate
    exits: List[dict] = []  # names that exit top-K in candidate
    n_same = 0
    n_diff = 0
    enter_tiers = Counter()
    exit_tiers = Counter()

    for snap_date in common_dates:
        base = _load_ranked(baseline_root / snap_date, top_k)
        cand = _load_ranked(candidate_root / snap_date, top_k)

        base_tickers = set(base.keys())
        cand_tickers = set(cand.keys())

        if base_tickers == cand_tickers:
            n_same += 1
            continue
        n_diff += 1

        # Names entering top-K
        for t in cand_tickers - base_tickers:
            r = cand[t]
            # Check if this ticker is in less_binary bucket
            cd = _safe_float(r.get("catalyst_days"))
            cm = str(r.get("catalyst_mode", ""))
            bucket = r.get("catalyst_bucket") or assign_catalyst_bucket(cd, cm)
            enters.append(
                {
                    "date": snap_date,
                    "ticker": t,
                    "tier": r.get("tier_dev", ""),
                    "bucket": bucket,
                    "optionality": r.get("clinical_optionality_pct_dev", ""),
                    "clinical_z": r.get("clinical_score_z_tier", ""),
                    "catalyst_days": r.get("catalyst_days", ""),
                    "new_rank": r.get("actionable_rank", ""),
                }
            )
            enter_tiers[r.get("tier_dev", "?")] += 1

        # Names exiting top-K
        for t in base_tickers - cand_tickers:
            r = base[t]
            cd = _safe_float(r.get("catalyst_days"))
            cm = str(r.get("catalyst_mode", ""))
            bucket = r.get("catalyst_bucket") or assign_catalyst_bucket(cd, cm)
            exits.append(
                {
                    "date": snap_date,
                    "ticker": t,
                    "tier": r.get("tier_dev", ""),
                    "bucket": bucket,
                    "optionality": r.get("clinical_optionality_pct_dev", ""),
                    "clinical_z": r.get("clinical_score_z_tier", ""),
                    "catalyst_days": r.get("catalyst_days", ""),
                    "old_rank": r.get("actionable_rank", ""),
                }
            )
            exit_tiers[r.get("tier_dev", "?")] += 1

    return {
        "n_dates": len(common_dates),
        "n_same": n_same,
        "n_diff": n_diff,
        "enters": enters,
        "exits": exits,
        "enter_tiers": dict(enter_tiers),
        "exit_tiers": dict(exit_tiers),
    }


def write_audit_md(audit: dict, out_path: Path) -> str:
    lines = []
    lines.append("# Difference Audit: Flatten Tier in binary_91_180")
    lines.append("")
    lines.append(f"**Dates compared**: {audit['n_dates']}")
    lines.append(f"**Same top-K**: {audit['n_same']} ({100 * audit['n_same'] / max(1, audit['n_dates']):.1f}%)")
    lines.append(f"**Different top-K**: {audit['n_diff']} ({100 * audit['n_diff'] / max(1, audit['n_dates']):.1f}%)")
    lines.append("")

    # Tier breakdown of movements
    lines.append("## Tier Breakdown of Movements")
    lines.append("")
    lines.append("### Names Entering Top-K (candidate)")
    lines.append(f"Total: {len(audit['enters'])}")
    lines.append("")
    for tier, count in sorted(audit["enter_tiers"].items()):
        lines.append(f"- Tier {tier}: {count}")
    lines.append("")
    lines.append("### Names Exiting Top-K (displaced)")
    lines.append(f"Total: {len(audit['exits'])}")
    lines.append("")
    for tier, count in sorted(audit["exit_tiers"].items()):
        lines.append(f"- Tier {tier}: {count}")
    lines.append("")

    # Bucket breakdown of enters
    enter_buckets = Counter(e["bucket"] for e in audit["enters"])
    lines.append("### Entering Names by Bucket")
    for bucket, count in sorted(enter_buckets.items(), key=lambda x: -x[1]):
        lines.append(f"- {bucket}: {count}")
    lines.append("")

    exit_buckets = Counter(e["bucket"] for e in audit["exits"])
    lines.append("### Exiting Names by Bucket")
    for bucket, count in sorted(exit_buckets.items(), key=lambda x: -x[1]):
        lines.append(f"- {bucket}: {count}")
    lines.append("")

    # Sample movements (first 20)
    lines.append("## Sample Movements (first 20 enters)")
    lines.append("")
    lines.append("| Date | Ticker | Tier | Bucket | Optionality | Clinical Z | Days | New Rank |")
    lines.append("|------|--------|------|--------|-------------|------------|------|----------|")
    for e in audit["enters"][:20]:
        opt = e["optionality"]
        cz = e["clinical_z"]
        lines.append(
            f"| {e['date']} | {e['ticker']} | {e['tier']} | {e['bucket']} "
            f"| {opt} | {cz} | {e['catalyst_days']} | {e['new_rank']} |"
        )
    lines.append("")

    lines.append("## Sample Displacements (first 20 exits)")
    lines.append("")
    lines.append("| Date | Ticker | Tier | Bucket | Optionality | Clinical Z | Days | Old Rank |")
    lines.append("|------|--------|------|--------|-------------|------------|------|----------|")
    for e in audit["exits"][:20]:
        opt = e["optionality"]
        cz = e["clinical_z"]
        lines.append(
            f"| {e['date']} | {e['ticker']} | {e['tier']} | {e['bucket']} "
            f"| {opt} | {cz} | {e['catalyst_days']} | {e['old_rank']} |"
        )
    lines.append("")

    md = "\n".join(lines)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md, encoding="utf-8")
    return md


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Difference audit: flatten-tier vs baseline")
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--out", type=Path, default=Path("output/diff_audit_flatten_tier.md"))
    args = parser.parse_args()

    audit = diff_audit(args.baseline_root, args.candidate_root, args.top_k)
    md = write_audit_md(audit, args.out)
    print(md)


if __name__ == "__main__":
    main()
