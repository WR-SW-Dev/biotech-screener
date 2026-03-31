"""CRT Phase 3 — Calibration rollup + governance triggers (Spec 042).

Aggregates resolution records into monthly calibration summaries and
evaluates governance trigger conditions.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List


def _load_month_records(resolutions_dir: Path, period: str) -> List[Dict[str, Any]]:
    """Load all resolution records for a given YYYY-MM period."""
    month_dir = resolutions_dir / period
    if not month_dir.exists():
        return []
    records = []
    for f in sorted(month_dir.glob("*.json")):
        try:
            with open(f) as fh:
                rec = json.load(fh)
            if rec.get("ticker") and rec.get("outcome"):
                records.append(rec)
        except Exception:
            continue
    return records


def _load_all_records(resolutions_dir: Path) -> List[Dict[str, Any]]:
    """Load all resolution records across all months."""
    records = []
    if not resolutions_dir.exists():
        return records
    for month_dir in sorted(resolutions_dir.iterdir()):
        if not month_dir.is_dir() or not month_dir.name[:4].isdigit():
            continue
        for f in sorted(month_dir.glob("*.json")):
            try:
                with open(f) as fh:
                    rec = json.load(fh)
                if rec.get("ticker") and rec.get("outcome"):
                    records.append(rec)
            except Exception:
                continue
    return records


def build_calibration_summary(resolutions_dir: Path, period: str) -> Dict[str, Any]:
    """Build monthly calibration summary from resolution records.

    Args:
        resolutions_dir: Root directory containing YYYY-MM/ subdirectories.
        period: Target month as YYYY-MM string.

    Returns:
        Calibration summary dict.
    """
    records = _load_month_records(resolutions_dir, period)

    outcome_dist = Counter(r["outcome"] for r in records)

    # By catalyst type
    by_type: Dict[str, Dict[str, int]] = defaultdict(lambda: {"n": 0, "hit": 0, "miss": 0, "mixed": 0})
    for r in records:
        ct = r.get("catalyst_type", "UNKNOWN")
        by_type[ct]["n"] += 1
        outcome = r["outcome"]
        if outcome == "HIT":
            by_type[ct]["hit"] += 1
        elif outcome == "MISS":
            by_type[ct]["miss"] += 1
        elif outcome == "MIXED":
            by_type[ct]["mixed"] += 1

    by_type_out = {}
    for ct, counts in by_type.items():
        hit_miss = counts["hit"] + counts["miss"]
        by_type_out[ct] = {
            **counts,
            "hit_rate": round(counts["hit"] / hit_miss, 3) if hit_miss > 0 else None,
        }

    # By DEM decile
    by_decile: Dict[str, Dict[str, int]] = {
        "top_10": {"n": 0, "hit": 0, "miss": 0},
        "top_20": {"n": 0, "hit": 0, "miss": 0},
        "top_60": {"n": 0, "hit": 0, "miss": 0},
        "bottom_50": {"n": 0, "hit": 0, "miss": 0},
    }
    for r in records:
        rank_str = r.get("prediction_dem_rank")
        if rank_str is None:
            continue
        try:
            rank = int(rank_str)
        except (ValueError, TypeError):
            continue
        outcome = r["outcome"]
        if rank <= 10:
            by_decile["top_10"]["n"] += 1
            if outcome == "HIT":
                by_decile["top_10"]["hit"] += 1
            elif outcome == "MISS":
                by_decile["top_10"]["miss"] += 1
        if rank <= 20:
            by_decile["top_20"]["n"] += 1
            if outcome == "HIT":
                by_decile["top_20"]["hit"] += 1
            elif outcome == "MISS":
                by_decile["top_20"]["miss"] += 1
        if rank <= 60:
            by_decile["top_60"]["n"] += 1
            if outcome == "HIT":
                by_decile["top_60"]["hit"] += 1
            elif outcome == "MISS":
                by_decile["top_60"]["miss"] += 1
        if rank > 100:
            by_decile["bottom_50"]["n"] += 1
            if outcome == "HIT":
                by_decile["bottom_50"]["hit"] += 1
            elif outcome == "MISS":
                by_decile["bottom_50"]["miss"] += 1

    for bucket in by_decile.values():
        hm = bucket["hit"] + bucket["miss"]
        bucket["hit_rate"] = round(bucket["hit"] / hm, 3) if hm > 0 else None

    return {
        "schema": "calibration_summary.v1",
        "period": period,
        "total_resolutions": len(records),
        "outcome_distribution": dict(outcome_dist),
        "by_catalyst_type": by_type_out,
        "by_dem_decile": by_decile,
    }


def evaluate_governance_triggers(
    resolutions_dir: Path,
    period: str,
) -> List[Dict[str, Any]]:
    """Evaluate governance trigger conditions against all resolution data.

    Returns list of trigger status dicts. Each trigger is pure evaluation:
    check condition, emit boolean. Never recommend — only surface to PM queue.
    """
    all_records = _load_all_records(resolutions_dir)

    triggers: List[Dict[str, Any]] = []

    # 1. pos_v2_calibration_ready: >=10 binary resolutions with outcome != DELAYED/NEEDS_REVIEW
    valid_binary = [r for r in all_records if r["outcome"] in ("HIT", "MISS", "MIXED")]
    triggers.append(
        {
            "trigger": "pos_v2_calibration_ready",
            "condition": ">=10 binary resolutions with definitive outcome",
            "status": "MET" if len(valid_binary) >= 10 else "ACCUMULATING",
            "current_count": len(valid_binary),
            "threshold": 10,
        }
    )

    # 2. clinical_bucket_decomp_ready: >=15 resolutions across >=3 indication buckets
    type_counts = Counter(r.get("catalyst_type", "") for r in valid_binary)
    n_types = sum(1 for c in type_counts.values() if c >= 2)
    triggers.append(
        {
            "trigger": "clinical_bucket_decomp_ready",
            "condition": ">=15 resolutions across >=3 catalyst types (each >=2)",
            "status": "MET" if len(valid_binary) >= 15 and n_types >= 3 else "ACCUMULATING",
            "current_count": len(valid_binary),
            "n_types_with_2plus": n_types,
        }
    )

    # 3. catalyst_taxonomy_empirical: >=20 resolutions across >=4 catalyst types
    n_types_4 = sum(1 for c in type_counts.values() if c >= 2)
    triggers.append(
        {
            "trigger": "catalyst_taxonomy_empirical",
            "condition": ">=20 resolutions across >=4 catalyst types",
            "status": "MET" if len(valid_binary) >= 20 and n_types_4 >= 4 else "ACCUMULATING",
            "current_count": len(valid_binary),
            "n_types_with_2plus": n_types_4,
        }
    )

    # 4. postmortem_coverage_threshold: >=5 resolutions with complete price reaction
    with_prices = [r for r in all_records if r.get("price_t_minus_1") is not None and r.get("price_t_0") is not None]
    triggers.append(
        {
            "trigger": "postmortem_coverage_threshold",
            "condition": ">=5 resolutions with complete price reaction data",
            "status": "MET" if len(with_prices) >= 5 else "ACCUMULATING",
            "current_count": len(with_prices),
            "threshold": 5,
        }
    )

    return triggers
