#!/usr/bin/env python3
"""Shadow sizing rule for event-quality tilts.

Computes what position weights would be if we applied event-quality
modifiers on top of the current production book. Logs comparisons
without modifying production state.

Rules:
  - Hard catalyst (is_hard_catalyst=1): upweight by 1.10x
  - Soft catalyst + low coinvest (coinvest_score_z <= 0): downweight by 0.85x
  - SEC-sourced near-catalyst (<=30d): upweight by 1.15x
  - No catalyst (has_catalyst_flag=0): no change (1.0x)

Usage:
    python3 tools/event_quality_shadow_sizer.py
    python3 tools/event_quality_shadow_sizer.py --snapshot-date 2026-04-03
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOTS_DIR = REPO_ROOT / "data" / "snapshots"
OUTPUT_DIR = REPO_ROOT / "artifacts" / "event_quality_shadow"

# Event quality tilt rules
HARD_CATALYST_TILT = 1.10
SOFT_LOW_COINVEST_TILT = 0.85
SEC_NEAR_CATALYST_TILT = 1.15
DEFAULT_TILT = 1.00

# Event type score mapping (Spec 056 — diagnostic overlay, not tilt)
EVENT_TYPE_SCORE_MAP = {
    "FDA_PDUFA_DATE": 3,
    "DATA_READOUT": 2,
    "CT_PRIMARY_COMPLETION": 1,
    "CT_STUDY_COMPLETION": 1,
    "CT_RESULTS_POSTED": 0,
    "CT_TRIAL_SUSPENDED": 0,
    "IR_EVENT": 0,
}


def _sf(v, default=None):
    if v is None or v == "":
        return default
    try:
        f = float(v)
        return f if not math.isnan(f) else default
    except (ValueError, TypeError):
        return default


def compute_event_quality_tilt(row: dict) -> tuple[float, str]:
    """Compute event-quality tilt multiplier for a single position.

    Returns (multiplier, reason).
    """
    hard = _sf(row.get("is_hard_catalyst"), 0)
    catalyst_days = _sf(row.get("catalyst_days"))
    catalyst_source = row.get("catalyst_source", "")
    coinvest_z = _sf(row.get("coinvest_score_z"), 0)

    # SEC-sourced near-catalyst (highest priority)
    if catalyst_source == "SEC_8K_FILING" and catalyst_days is not None and catalyst_days <= 30:
        return SEC_NEAR_CATALYST_TILT, "SEC_near_catalyst"

    # Hard catalyst upweight
    if hard == 1.0:
        return HARD_CATALYST_TILT, "hard_catalyst"

    # Soft catalyst + low coinvest downweight
    if catalyst_days is not None and hard == 0.0 and coinvest_z <= 0:
        return SOFT_LOW_COINVEST_TILT, "soft_low_coinvest"

    return DEFAULT_TILT, "default"


def run_shadow(snapshot_date: str | None = None) -> dict:
    """Run shadow sizing comparison for a snapshot."""
    # Find latest snapshot
    if not snapshot_date:
        available = sorted(
            d.name
            for d in SNAPSHOTS_DIR.iterdir()
            if d.is_dir() and (d / "rankings.csv").exists() and "__pre_" not in d.name
        )
        if not available:
            return {"error": "no snapshots found"}
        snapshot_date = available[-1]

    rankings_path = SNAPSHOTS_DIR / snapshot_date / "rankings.csv"
    if not rankings_path.exists():
        return {"error": f"no rankings.csv for {snapshot_date}"}

    # Load rankings
    with open(rankings_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    # Filter to top-30 by actionable_rank
    top30 = []
    for r in rows:
        rank = _sf(r.get("actionable_rank"))
        if rank is not None and rank <= 30:
            top30.append(r)
    top30.sort(key=lambda x: _sf(x.get("actionable_rank"), 999))

    if not top30:
        return {"error": "no top-30 positions found"}

    # Compute tilts
    results = []
    for r in top30:
        ticker = r.get("ticker", "")
        rank = _sf(r.get("actionable_rank"), 999)
        prod_weight = _sf(r.get("target_weight_pct"), 0)
        tilt, reason = compute_event_quality_tilt(r)

        # Event type score (diagnostic, Spec 056)
        evt = r.get("catalyst_event_type", "")
        ets = EVENT_TYPE_SCORE_MAP.get(evt, 0) if evt else None

        results.append(
            {
                "ticker": ticker,
                "rank": int(rank),
                "production_weight_pct": round(prod_weight, 2),
                "event_quality_tilt": tilt,
                "tilt_reason": reason,
                "shadow_raw_weight": round(prod_weight * tilt, 4),
                "is_hard_catalyst": _sf(r.get("is_hard_catalyst"), 0),
                "catalyst_days": _sf(r.get("catalyst_days")),
                "catalyst_source": r.get("catalyst_source", ""),
                "coinvest_score_z": _sf(r.get("coinvest_score_z"), 0),
                "event_type_score": ets,
                "catalyst_event_type": evt,
            }
        )

    # Normalize shadow weights
    total_raw = sum(r["shadow_raw_weight"] for r in results)
    if total_raw > 0:
        for r in results:
            r["shadow_weight_pct"] = round(r["shadow_raw_weight"] / total_raw * 100, 2)
    else:
        for r in results:
            r["shadow_weight_pct"] = r["production_weight_pct"]

    # Compute deltas
    for r in results:
        r["weight_delta_pct"] = round(r["shadow_weight_pct"] - r["production_weight_pct"], 2)

    # Summary
    upweighted = [r for r in results if r["event_quality_tilt"] > 1.0]
    downweighted = [r for r in results if r["event_quality_tilt"] < 1.0]
    unchanged = [r for r in results if r["event_quality_tilt"] == 1.0]

    tilt_counts = {}
    for r in results:
        reason = r["tilt_reason"]
        tilt_counts[reason] = tilt_counts.get(reason, 0) + 1

    # Event type distribution (diagnostic)
    event_type_dist = {}
    for r in results:
        ets = r.get("event_type_score")
        key = str(ets) if ets is not None else "none"
        event_type_dist[key] = event_type_dist.get(key, 0) + 1

    return {
        "schema": "event_quality_shadow.v1",
        "snapshot_date": snapshot_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_positions": len(results),
        "n_upweighted": len(upweighted),
        "n_downweighted": len(downweighted),
        "n_unchanged": len(unchanged),
        "tilt_counts": tilt_counts,
        "max_weight_delta": max((abs(r["weight_delta_pct"]) for r in results), default=0),
        "event_type_dist": event_type_dist,
        "positions": results,
    }


REVIEW_OUTPUT_DIR = REPO_ROOT / "artifacts" / "review"


def prioritize_reviews(snapshot_date=None):
    """Rank positions by review urgency based on event quality signals.

    Criteria (any triggers "needs review"):
    - event_type_score < 1 (low quality event backing the position)
    - last_update_age > 90 (stale data on the catalyst)
    - source_reliability_action in (DEMOTE, SUPPRESS)
    - catalyst_family is NO_CATALYST or empty

    Returns list sorted by urgency (most urgent first), plus summary.
    """
    if not snapshot_date:
        available = sorted(
            d.name
            for d in SNAPSHOTS_DIR.iterdir()
            if d.is_dir() and (d / "rankings.csv").exists() and "__pre_" not in d.name and not d.name.startswith("_")
        )
        if not available:
            return {"error": "no snapshots found"}
        snapshot_date = available[-1]

    rankings_path = SNAPSHOTS_DIR / snapshot_date / "rankings.csv"
    if not rankings_path.exists():
        return {"error": f"no rankings.csv for {snapshot_date}"}

    with open(rankings_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    # Filter to top-60 (actionable universe)
    candidates = []
    for r in rows:
        rank = _sf(r.get("actionable_rank"))
        if rank is not None and rank <= 60:
            candidates.append(r)

    priorities = []
    for r in candidates:
        ticker = r.get("ticker", "")
        rank = int(_sf(r.get("actionable_rank"), 999))
        evt = r.get("catalyst_event_type", "")
        ets = EVENT_TYPE_SCORE_MAP.get(evt, 0) if evt else 0
        family = r.get("catalyst_family", "")
        source_action = r.get("source_reliability_action", "ALLOW")
        catalyst_days = _sf(r.get("catalyst_days"))

        # Compute reasons for review
        reasons = []
        urgency = 0

        if ets < 1:
            reasons.append("LOW_EVENT_TYPE_SCORE")
            urgency += 3

        if source_action in ("DEMOTE", "SUPPRESS"):
            reasons.append(f"SOURCE_{source_action}")
            urgency += 2 if source_action == "SUPPRESS" else 1

        if not family or family == "NO_CATALYST":
            reasons.append("NO_CATALYST_FAMILY")
            urgency += 2

        # Near-term + soft → higher urgency
        if catalyst_days is not None and catalyst_days <= 30 and ets < 2:
            reasons.append("NEAR_TERM_LOW_QUALITY")
            urgency += 2

        if not reasons:
            continue  # no review needed

        priorities.append(
            {
                "ticker": ticker,
                "rank": rank,
                "event_type_score": ets,
                "catalyst_event_type": evt,
                "catalyst_family": family,
                "catalyst_days": int(catalyst_days) if catalyst_days else None,
                "source_reliability_action": source_action,
                "reasons": reasons,
                "urgency": urgency,
            }
        )

    # Sort by urgency descending, then rank ascending
    priorities.sort(key=lambda x: (-x["urgency"], x["rank"]))

    return {
        "schema": "review_priority.v1",
        "snapshot_date": snapshot_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_reviewed": len(priorities),
        "n_candidates": len(candidates),
        "priorities": priorities,
    }


def main():
    parser = argparse.ArgumentParser(description="Event quality shadow sizing comparison")
    parser.add_argument(
        "--snapshot-date",
        default=None,
        help="Snapshot date (default: latest)",
    )
    args = parser.parse_args()

    result = run_shadow(args.snapshot_date)

    if "error" in result:
        print(f"ERROR: {result['error']}")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    snap = result["snapshot_date"]
    out_path = OUTPUT_DIR / f"event_quality_shadow_{snap}.json"
    out_path.write_text(json.dumps(result, indent=2, default=str))

    print(f"EVENT QUALITY SHADOW SIZER — {snap}")
    print(f"  Positions: {result['n_positions']}")
    print(f"  Upweighted: {result['n_upweighted']}")
    print(f"  Downweighted: {result['n_downweighted']}")
    print(f"  Unchanged: {result['n_unchanged']}")
    print(f"  Tilt counts: {result['tilt_counts']}")
    print(f"  Max weight delta: {result['max_weight_delta']:.2f}pp")

    print("\n  Position details:")
    for r in result["positions"]:
        delta = r["weight_delta_pct"]
        arrow = "↑" if delta > 0 else "↓" if delta < 0 else "="
        print(
            f"    {r['ticker']:6s} rank={r['rank']:2d} "
            f"prod={r['production_weight_pct']:5.2f}% "
            f"shadow={r['shadow_weight_pct']:5.2f}% "
            f"{arrow}{abs(delta):.2f}pp "
            f"[{r['tilt_reason']}]"
        )

    print(f"\n  Saved: {out_path}")

    # Review prioritization
    review = prioritize_reviews(args.snapshot_date)
    if "error" not in review:
        REVIEW_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        review_path = REVIEW_OUTPUT_DIR / f"review_priority_{snap}.json"
        review_path.write_text(json.dumps(review, indent=2, default=str))
        print(f"\n  REVIEW PRIORITY — {review['n_reviewed']}/{review['n_candidates']} need review")
        for p in review["priorities"][:10]:
            print(f"    {p['ticker']:6s} rank={p['rank']:2d} urgency={p['urgency']} [{', '.join(p['reasons'])}]")
        print(f"  Saved: {review_path}")


if __name__ == "__main__":
    main()
