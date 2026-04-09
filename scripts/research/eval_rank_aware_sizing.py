#!/usr/bin/env python3
"""Rank-aware sizing research diagnostic.

Compares three DE portfolio weighting schemes on identical top-K membership:
  1. Current: size_band × multipliers (production)
  2. Equal-weight: 1/N across top-K
  3. Rank-aware: size_band × rank taper within bucket

The rank taper multiplies the base size-band weight by a position-dependent
factor within each catalyst_bucket:
  - Top 25% of bucket:  1.10×
  - Middle 50%:         1.00×
  - Bottom 25%:         0.90×
Then renormalize to 100%.

This isolates whether rank-congruent sizing adds value over flat size-band
sizing, using the same selection and ordering as the live DE.

Usage:
    python scripts/research/eval_rank_aware_sizing.py \
        --ruleset production_data/decision_rulesets/v1.11.0_b91_clinical_quality_w05_candidate.json \
        --start 2025-06-01
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from decision_engine import DEFAULT_RULESET, DecisionRuleset
from run_decision_ruleset_sweep import init_providers, load_archive_data
from run_decision_strategy_backtest import (
    DEFAULT_TIER_FILTER,
    DEFAULT_TOP_K,
    HORIZONS,
    build_strategy_portfolio,
    compute_multi_horizon_returns,
    hydrate_archive_drawdown,
)
from run_rank_ic_backtest import ARCHIVE_DIR, PRICE_CSV, compute_as_of_fence, discover_archives

# ---------------------------------------------------------------------------
# Weight modes
# ---------------------------------------------------------------------------


def apply_equal_weight(positions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Replace weights with 1/N equal weight."""
    out = copy.deepcopy(positions)
    if not out:
        return out
    w = round(100.0 / len(out), 4)
    for pos in out:
        pos["weight_pct"] = w
    return out


def apply_rank_taper(
    positions: List[Dict[str, Any]],
    top_mult: float = 1.10,
    mid_mult: float = 1.00,
    bot_mult: float = 0.90,
) -> List[Dict[str, Any]]:
    """Apply rank-aware taper within each catalyst bucket.

    Within each bucket, positions are already sorted by actionable_rank.
    Top 25% get top_mult, middle 50% get mid_mult, bottom 25% get bot_mult.
    Then renormalize to sum to 100%.
    """
    out = copy.deepcopy(positions)
    if not out:
        return out

    # Group by bucket
    by_bucket: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for pos in out:
        bucket = pos.get("catalyst_mode", "unknown")
        by_bucket[bucket].append(pos)

    # Apply taper within each bucket
    for bucket, group in by_bucket.items():
        # Already sorted by actionable_rank from build_strategy_portfolio
        n = len(group)
        top_cutoff = max(1, n // 4)  # top 25%
        bot_cutoff = n - max(1, n // 4)  # bottom 25%

        for i, pos in enumerate(group):
            base_w = pos.get("weight_pct", 0.0)
            if isinstance(base_w, str):
                base_w = float(base_w) if base_w else 0.0
            if i < top_cutoff:
                pos["weight_pct"] = base_w * top_mult
            elif i >= bot_cutoff:
                pos["weight_pct"] = base_w * bot_mult
            else:
                pos["weight_pct"] = base_w * mid_mult

    # Renormalize
    total = sum(pos["weight_pct"] for pos in out)
    if total > 0:
        for pos in out:
            pos["weight_pct"] = round(pos["weight_pct"] / total * 100, 4)

    return out


# ---------------------------------------------------------------------------
# Portfolio return computation
# ---------------------------------------------------------------------------


def compute_weighted_return(
    positions: List[Dict[str, Any]],
    returns: Dict[str, float],
) -> Optional[float]:
    """Weighted portfolio return. Returns None if no coverage."""
    matched = []
    for pos in positions:
        ticker = pos["ticker"]
        w = pos.get("weight_pct", 0.0)
        if isinstance(w, str):
            w = float(w) if w else 0.0
        ret = returns.get(ticker)
        if ret is not None:
            matched.append((w, ret))
    if not matched:
        return None
    total_w = sum(w for w, _ in matched)
    if total_w <= 0:
        return None
    return sum((w / total_w) * r for w, r in matched)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Rank-aware sizing research diagnostic")
    parser.add_argument("--ruleset", type=str, default=None)
    parser.add_argument("--start", type=str, default=None)
    parser.add_argument("--end", type=str, default=None)
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument("--top-mult", type=float, default=1.10)
    parser.add_argument("--mid-mult", type=float, default=1.00)
    parser.add_argument("--bot-mult", type=float, default=0.90)
    parser.add_argument("--output-dir", type=str, default=str(PROJECT_ROOT / "output" / "rank_aware_sizing"))
    args = parser.parse_args()

    if args.ruleset:
        ruleset = DecisionRuleset.from_json(args.ruleset)
        print(f"Loaded ruleset: {args.ruleset}")
    else:
        ruleset = DEFAULT_RULESET
        print("Using default ruleset")

    tier_filter = DEFAULT_TIER_FILTER
    top_k = args.top_k
    horizons = HORIZONS

    # Discover archives
    archive_dir = ARCHIVE_DIR
    archives = discover_archives(archive_dir)
    if args.start:
        archives = [(d, p) for d, p in archives if d >= args.start]
    if args.end:
        archives = [(d, p) for d, p in archives if d <= args.end]

    print(f"Archives: {len(archives)}")

    # Init price providers
    chained, _ms, csv_provider = init_providers(price_csv=PRICE_CSV)
    snapshot_dates = [d for d, _ in archives]
    last_date = csv_provider.get_last_date()
    max_horizon = max(horizons)
    usable_dates, fence_skipped = compute_as_of_fence(snapshot_dates, last_date, max_horizon)
    usable_set = set(usable_dates)

    print(f"  Usable: {len(usable_dates)}, skipped: {len(fence_skipped)} past fence")
    print(f"  Taper: top={args.top_mult}, mid={args.mid_mult}, bot={args.bot_mult}")
    print()

    # Results per snapshot
    results = []

    for i, (date_str, tar_path) in enumerate(archives):
        if date_str not in usable_set:
            continue

        archive_data = load_archive_data(tar_path, date_str)
        hydrate_archive_drawdown(archive_data, csv_provider, date_str)

        mh_returns = compute_multi_horizon_returns(chained, csv_provider, archive_data.tickers, date_str, horizons)

        # Build DE portfolio (same selection + ordering for all three arms)
        strategy_positions = build_strategy_portfolio(archive_data, ruleset, tier_filter, top_k)
        if not strategy_positions:
            continue

        # Three arms
        current = strategy_positions  # size-band weighted
        ew = apply_equal_weight(strategy_positions)
        rank_aware = apply_rank_taper(
            strategy_positions,
            top_mult=args.top_mult,
            mid_mult=args.mid_mult,
            bot_mult=args.bot_mult,
        )

        row = {"date": date_str, "n": len(strategy_positions)}

        for h in horizons:
            raw_rets = mh_returns.raw.get(h, {})
            resid_rets = mh_returns.resid.get(h, {})

            for mode_name, positions in [
                ("current", current),
                ("ew", ew),
                ("rank_aware", rank_aware),
            ]:
                raw_ret = compute_weighted_return(positions, raw_rets)
                resid_ret = compute_weighted_return(positions, resid_rets)
                if raw_ret is not None:
                    row[f"{mode_name}_raw_{h}d"] = round(raw_ret * 100, 4)
                if resid_ret is not None:
                    row[f"{mode_name}_resid_{h}d"] = round(resid_ret * 100, 4)

        results.append(row)
        resid_60 = row.get("current_resid_60d", "n/a")
        ra_60 = row.get("rank_aware_resid_60d", "n/a")
        print(f"  [{i+1}] {date_str}: current_60d={resid_60}, rank_aware_60d={ra_60}")

    if not results:
        print("No usable snapshots!")
        return 1

    # Aggregate
    print(f"\n{'='*70}")
    print("AGGREGATE RESULTS (mean residual return, %)")
    print(f"{'='*70}")
    print(f"{'Mode':<16} {'20d':>10} {'60d':>10}")
    print(f"{'-'*16} {'-'*10} {'-'*10}")

    for mode in ["current", "ew", "rank_aware"]:
        vals_20 = [r[f"{mode}_resid_20d"] for r in results if f"{mode}_resid_20d" in r]
        vals_60 = [r[f"{mode}_resid_60d"] for r in results if f"{mode}_resid_60d" in r]
        m20 = f"{mean(vals_20):+.4f}" if vals_20 else "n/a"
        m60 = f"{mean(vals_60):+.4f}" if vals_60 else "n/a"
        label = {"current": "Size-band (live)", "ew": "Equal-weight", "rank_aware": "Rank-aware"}[mode]
        print(f"{label:<16} {m20:>10} {m60:>10}")

    # Spread: rank-aware vs current
    print()
    spreads_20 = []
    spreads_60 = []
    for r in results:
        if "rank_aware_resid_20d" in r and "current_resid_20d" in r:
            spreads_20.append(r["rank_aware_resid_20d"] - r["current_resid_20d"])
        if "rank_aware_resid_60d" in r and "current_resid_60d" in r:
            spreads_60.append(r["rank_aware_resid_60d"] - r["current_resid_60d"])

    print("SPREAD: rank-aware minus current (pp)")
    if spreads_20:
        print(
            f"  20d: mean={mean(spreads_20):+.4f}, median={median(spreads_20):+.4f}, "
            f"positive={sum(1 for s in spreads_20 if s > 0)}/{len(spreads_20)}"
        )
    if spreads_60:
        print(
            f"  60d: mean={mean(spreads_60):+.4f}, median={median(spreads_60):+.4f}, "
            f"positive={sum(1 for s in spreads_60 if s > 0)}/{len(spreads_60)}"
        )

    # Spread: rank-aware vs equal-weight
    spreads_ew_20 = []
    spreads_ew_60 = []
    for r in results:
        if "rank_aware_resid_20d" in r and "ew_resid_20d" in r:
            spreads_ew_20.append(r["rank_aware_resid_20d"] - r["ew_resid_20d"])
        if "rank_aware_resid_60d" in r and "ew_resid_60d" in r:
            spreads_ew_60.append(r["rank_aware_resid_60d"] - r["ew_resid_60d"])

    print()
    print("SPREAD: rank-aware minus equal-weight (pp)")
    if spreads_ew_20:
        print(f"  20d: mean={mean(spreads_ew_20):+.4f}, median={median(spreads_ew_20):+.4f}")
    if spreads_ew_60:
        print(f"  60d: mean={mean(spreads_ew_60):+.4f}, median={median(spreads_ew_60):+.4f}")

    # Write CSV
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "rank_aware_sizing_comparison.csv"
    if results:
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=results[0].keys())
            writer.writeheader()
            writer.writerows(results)
        print(f"\nCSV → {csv_path}")

    # Write JSON summary
    summary = {
        "taper": {"top": args.top_mult, "mid": args.mid_mult, "bot": args.bot_mult},
        "ruleset_id": ruleset.ruleset_id,
        "n_snapshots": len(results),
        "date_range": [results[0]["date"], results[-1]["date"]],
        "means": {},
        "spreads": {},
    }
    for mode in ["current", "ew", "rank_aware"]:
        vals_20 = [r[f"{mode}_resid_20d"] for r in results if f"{mode}_resid_20d" in r]
        vals_60 = [r[f"{mode}_resid_60d"] for r in results if f"{mode}_resid_60d" in r]
        summary["means"][mode] = {
            "resid_20d": round(mean(vals_20), 4) if vals_20 else None,
            "resid_60d": round(mean(vals_60), 4) if vals_60 else None,
        }
    summary["spreads"]["rank_aware_vs_current"] = {
        "20d": round(mean(spreads_20), 4) if spreads_20 else None,
        "60d": round(mean(spreads_60), 4) if spreads_60 else None,
    }
    summary["spreads"]["rank_aware_vs_ew"] = {
        "20d": round(mean(spreads_ew_20), 4) if spreads_ew_20 else None,
        "60d": round(mean(spreads_ew_60), 4) if spreads_ew_60 else None,
    }

    json_path = out_dir / "rank_aware_sizing_summary.json"
    with open(json_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"JSON → {json_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
