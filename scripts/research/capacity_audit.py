#!/usr/bin/env python3
"""Capacity Audit — execution feasibility analysis.

Recomputes execution capacity on-the-fly from price_history.csv for
each snapshot, then validates against the current top-N portfolio.

Tests:
  1. Sizing feasibility distribution
  2. Percent of top-N clipped by capacity constraints
  3. Average target weight vs max feasible weight
  4. Portfolio-level capacity at current NAV
  5. Simulate realized trade set under capacity caps
  6. NAV scaling breakpoints
  7. Multi-snapshot trend (capacity stability over time)

Success threshold:
  - Materially reduces infeasible exposure
  - Without pretending to be alpha

Usage:
    cd /mnt/c/Projects/biotech_screener/biotech-screener
    python -m scripts.research.capacity_audit
    python -m scripts.research.capacity_audit --nav 5000000 --top-n 30
    python -m scripts.research.capacity_audit --multi --output results.json
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ═════════════════════════════════════════════════════════════════════════
# Paths
# ═════════════════════════════════════════════════════════════════════════

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SNAPSHOTS_DIR = PROJECT_ROOT / "data" / "snapshots_pit_v2"
DEFAULT_PRICE_CSV = PROJECT_ROOT / "production_data" / "price_history.csv"

# ═════════════════════════════════════════════════════════════════════════
# Utilities
# ═════════════════════════════════════════════════════════════════════════


def _sf(v: Any) -> Optional[float]:
    if v is None or v == "" or v == "None":
        return None
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except (ValueError, TypeError):
        return None


def _load_snapshot(snap_dir: Path) -> List[Dict[str, Any]]:
    csv_path = snap_dir / "rankings.csv"
    if not csv_path.exists():
        return []
    with open(csv_path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _discover_snapshot_dates(snapshots_dir: Path) -> List[str]:
    dates = []
    for d in sorted(snapshots_dir.iterdir()):
        if not d.is_dir():
            continue
        name = d.name
        if len(name) != 10 or name[4] != "-" or name[7] != "-":
            continue
        try:
            from datetime import date as dt_date

            dt_date.fromisoformat(name)
        except ValueError:
            continue
        dates.append(name)
    return dates


# ═════════════════════════════════════════════════════════════════════════
# On-the-fly execution capacity scoring
# ═════════════════════════════════════════════════════════════════════════


def _compute_execution_overlays(
    rows: List[Dict[str, Any]],
    snap_date: str,
    price_csv: Path,
    portfolio_nav: float,
) -> Dict[str, Dict[str, Any]]:
    """Compute execution capacity for each ticker using ExecutionCapacityModel.

    Returns {ticker: overlay_dict}.
    """
    sys.path.insert(0, str(PROJECT_ROOT))
    from event_ev.execution_capacity import ExecutionCapacityModel

    model = ExecutionCapacityModel(
        price_history_path=price_csv,
        as_of_date=snap_date,
        portfolio_nav=portfolio_nav,
    )

    overlays = model.score_batch(rows, snap_date)
    return {o.ticker: o.to_dict() for o in overlays}


# ═════════════════════════════════════════════════════════════════════════
# Capacity-constrained portfolio simulation
# ═════════════════════════════════════════════════════════════════════════


def _simulate_constrained_portfolio(
    positions: List[Dict[str, Any]],
    portfolio_nav: float,
) -> Dict[str, Any]:
    """Simulate equal-weight portfolio under capacity caps.

    For each position:
      target = NAV / N
      feasible = min(target, max_position_dollars)
      residual cash gets redistributed to unconstrained names.

    Returns summary of the constrained vs unconstrained portfolio.
    """
    n = len(positions)
    if n == 0:
        return {"error": "empty_portfolio"}

    target_per_name = portfolio_nav / n

    # First pass: identify constrained and unconstrained
    constrained = []
    unconstrained = []
    total_shortfall = 0.0

    for p in positions:
        max_pos = p.get("max_position_dollars") or 0.0
        if max_pos <= 0:
            # No data — treat as unconstrained but flag
            unconstrained.append(p)
            continue

        if max_pos < target_per_name:
            constrained.append(p)
            total_shortfall += target_per_name - max_pos
        else:
            unconstrained.append(p)

    # Second pass: redistribute shortfall to unconstrained
    n_uncon = len(unconstrained)
    if n_uncon > 0 and total_shortfall > 0:
        extra_per_name = total_shortfall / n_uncon
        # Check if redistribution itself causes new constraints
        still_ok = sum(
            1
            for p in unconstrained
            if (p.get("max_position_dollars") or float("inf")) >= target_per_name + extra_per_name
        )
    else:
        extra_per_name = 0.0
        still_ok = n_uncon

    # Final allocations
    allocated_total = 0.0
    position_details = []
    for p in positions:
        max_pos = p.get("max_position_dollars") or 0.0
        if max_pos <= 0:
            alloc = target_per_name
        elif max_pos < target_per_name:
            alloc = max_pos
        else:
            alloc = target_per_name + (extra_per_name if n_uncon > 0 else 0)
            alloc = min(alloc, max_pos) if max_pos > 0 else alloc
        allocated_total += alloc
        position_details.append(
            {
                "ticker": p.get("ticker", ""),
                "target_dollars": round(target_per_name, 0),
                "allocated_dollars": round(alloc, 0),
                "utilization": round(alloc / target_per_name, 4) if target_per_name > 0 else 1.0,
                "constrained": max_pos > 0 and max_pos < target_per_name,
            }
        )

    cash_drag = portfolio_nav - allocated_total
    cash_drag_pct = (cash_drag / portfolio_nav * 100) if portfolio_nav > 0 else 0

    return {
        "n_positions": n,
        "n_constrained": len(constrained),
        "n_unconstrained": n_uncon,
        "total_allocated": round(allocated_total, 0),
        "cash_drag_dollars": round(cash_drag, 0),
        "cash_drag_pct": round(cash_drag_pct, 2),
        "redistribution_ok": still_ok == n_uncon,
        "positions": position_details,
    }


# ═════════════════════════════════════════════════════════════════════════
# ADV concentration analysis
# ═════════════════════════════════════════════════════════════════════════


def _adv_concentration(positions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Analyze ADV distribution of portfolio constituents."""
    advs = []
    for p in positions:
        adv = p.get("adv_20d") or 0.0
        if adv > 0:
            advs.append(adv)

    if not advs:
        return {"n_with_adv": 0}

    advs_sorted = sorted(advs)
    n = len(advs_sorted)

    return {
        "n_with_adv": n,
        "min_adv_mm": round(advs_sorted[0] / 1e6, 2),
        "p10_adv_mm": round(advs_sorted[min(int(n * 0.10), n - 1)] / 1e6, 2),
        "p25_adv_mm": round(advs_sorted[min(int(n * 0.25), n - 1)] / 1e6, 2),
        "median_adv_mm": round(advs_sorted[n // 2] / 1e6, 2),
        "p75_adv_mm": round(advs_sorted[min(int(n * 0.75), n - 1)] / 1e6, 2),
        "max_adv_mm": round(advs_sorted[-1] / 1e6, 2),
        "below_500k": sum(1 for a in advs if a < 500_000),
        "below_1mm": sum(1 for a in advs if a < 1_000_000),
        "above_5mm": sum(1 for a in advs if a >= 5_000_000),
    }


# ═════════════════════════════════════════════════════════════════════════
# Single snapshot audit
# ═════════════════════════════════════════════════════════════════════════


def run_audit(
    snapshot_dir: Path,
    snap_date: str,
    price_csv: Path,
    portfolio_nav: float = 3_000_000.0,
    target_top_n: int = 30,
) -> Dict[str, Any]:
    """Run capacity audit on a single snapshot with on-the-fly scoring."""

    rows = _load_snapshot(snapshot_dir)
    if not rows:
        return {"error": "no_data", "snapshot_dir": str(snapshot_dir)}

    # Compute execution capacity on-the-fly
    exec_map = _compute_execution_overlays(rows, snap_date, price_csv, portfolio_nav)

    # Filter to eligible ranked names
    eligible = []
    for r in rows:
        rank = _sf(r.get("actionable_rank"))
        is_eligible = str(r.get("eligible", "")).strip().lower() in ("true", "1")
        if rank is not None and is_eligible:
            r["_rank"] = rank
            eligible.append(r)

    eligible.sort(key=lambda r: r["_rank"])
    top_n = eligible[:target_top_n]

    logger.info(
        "[%s] %d eligible tickers, %d in top-%d, %d with capacity data",
        snap_date,
        len(eligible),
        len(top_n),
        target_top_n,
        len(exec_map),
    )

    # Build position data
    positions: List[Dict[str, Any]] = []
    for r in top_n:
        ticker = r.get("ticker", "")
        target_wt = _sf(r.get("target_weight_pct")) or (100.0 / target_top_n)
        overlay = exec_map.get(ticker, {})

        cap_score = overlay.get("execution_capacity_score", 0.0)
        max_pos = overlay.get("max_position_dollars", 0.0)
        adv_20d = overlay.get("adv_20d", 0.0)
        adv_60d = overlay.get("adv_60d", 0.0)
        median_20d = overlay.get("median_dollar_volume_20d", 0.0)
        bucket = overlay.get("execution_bucket", "no_data")
        notes = overlay.get("execution_notes", "")

        target_dollars = portfolio_nav * target_wt / 100.0
        feasible_dollars = min(target_dollars, max_pos) if max_pos > 0 else target_dollars
        feasible_wt = feasible_dollars / portfolio_nav * 100.0
        clipped = feasible_wt < target_wt * 0.95  # >5% reduction = clipped

        positions.append(
            {
                "ticker": ticker,
                "rank": int(r["_rank"]),
                "target_weight_pct": round(target_wt, 2),
                "feasible_weight_pct": round(feasible_wt, 2),
                "max_position_dollars": round(max_pos, 0) if max_pos else None,
                "adv_20d": round(adv_20d, 0) if adv_20d else None,
                "adv_60d": round(adv_60d, 0) if adv_60d else None,
                "median_dollar_volume_20d": round(median_20d, 0) if median_20d else None,
                "execution_capacity_score": round(cap_score, 4) if cap_score else None,
                "execution_bucket": bucket,
                "execution_notes": notes,
                "clipped": clipped,
            }
        )

    # Aggregate metrics
    n_clipped = sum(1 for d in positions if d["clipped"])
    n_micro = sum(1 for d in positions if d["execution_bucket"] == "micro_size_only")
    n_untradeable = sum(1 for d in positions if d["execution_bucket"] == "untradeable")
    n_with_data = sum(1 for d in positions if d["execution_capacity_score"] is not None)

    target_wts = [d["target_weight_pct"] for d in positions]
    feasible_wts = [d["feasible_weight_pct"] for d in positions]
    avg_target = statistics.mean(target_wts) if target_wts else 0
    avg_feasible = statistics.mean(feasible_wts) if feasible_wts else 0
    total_target = sum(target_wts)
    total_feasible = sum(feasible_wts)
    capacity_util = total_feasible / total_target if total_target > 0 else 1.0

    # Bucket distribution across full universe
    all_buckets: Dict[str, int] = defaultdict(int)
    for r in eligible:
        tk = r.get("ticker", "")
        overlay = exec_map.get(tk, {})
        b = overlay.get("execution_bucket", "no_data")
        all_buckets[b] += 1

    # ADV concentration for top-N
    adv_analysis = _adv_concentration(positions)

    # NAV scaling analysis
    nav_breakpoints = []
    for test_nav in [1_000_000, 3_000_000, 5_000_000, 10_000_000, 25_000_000, 50_000_000]:
        n_clipped_at_nav = 0
        for d in positions:
            max_pos = d["max_position_dollars"]
            if max_pos is None or max_pos <= 0:
                continue
            target_at_nav = test_nav * (d["target_weight_pct"] / 100.0)
            if target_at_nav > max_pos * 1.05:
                n_clipped_at_nav += 1

        nav_breakpoints.append(
            {
                "nav_mm": test_nav / 1_000_000,
                "pct_clipped": round(n_clipped_at_nav / len(positions) * 100, 1) if positions else 0,
                "n_clipped": n_clipped_at_nav,
            }
        )

    # Constrained portfolio simulation
    sim = _simulate_constrained_portfolio(positions, portfolio_nav)

    # Participation rate analysis: what % of ADV would each position consume?
    participation_rates: List[Dict[str, Any]] = []
    for d in positions:
        adv = d.get("adv_20d") or 0
        target_dollars = portfolio_nav * d["target_weight_pct"] / 100.0
        if adv > 0:
            prate = target_dollars / adv
            participation_rates.append(
                {
                    "ticker": d["ticker"],
                    "participation_rate": round(prate, 4),
                    "above_5pct": prate > 0.05,
                    "above_10pct": prate > 0.10,
                    "above_20pct": prate > 0.20,
                }
            )

    n_above_5pct = sum(1 for p in participation_rates if p["above_5pct"])
    n_above_10pct = sum(1 for p in participation_rates if p["above_10pct"])
    n_above_20pct = sum(1 for p in participation_rates if p["above_20pct"])

    report = {
        "schema": "capacity_audit.v2",
        "snapshot_date": snap_date,
        "portfolio_nav": portfolio_nav,
        "target_top_n": target_top_n,
        "n_eligible": len(eligible),
        "n_in_top_n": len(top_n),
        "n_with_capacity_data": n_with_data,
        "sizing_feasibility": {
            "n_clipped": n_clipped,
            "pct_clipped": round(n_clipped / len(top_n) * 100, 1) if top_n else 0,
            "n_micro_size_only": n_micro,
            "n_untradeable": n_untradeable,
            "avg_target_weight_pct": round(avg_target, 2),
            "avg_feasible_weight_pct": round(avg_feasible, 2),
            "total_target_weight_pct": round(total_target, 1),
            "total_feasible_weight_pct": round(total_feasible, 1),
            "capacity_utilization": round(capacity_util, 4),
        },
        "adv_concentration": adv_analysis,
        "participation_rates": {
            "n_above_5pct_adv": n_above_5pct,
            "n_above_10pct_adv": n_above_10pct,
            "n_above_20pct_adv": n_above_20pct,
            "detail": participation_rates,
        },
        "bucket_distribution_full_universe": dict(sorted(all_buckets.items())),
        "nav_scaling": nav_breakpoints,
        "constrained_simulation": {
            "n_constrained": sim.get("n_constrained", 0),
            "cash_drag_pct": sim.get("cash_drag_pct", 0),
            "redistribution_ok": sim.get("redistribution_ok", True),
        },
        "position_detail": positions,
        "pass_fail": {
            "has_capacity_data": n_with_data >= len(top_n) * 0.5,
            "capacity_utilization_gt_80pct": capacity_util > 0.80,
            "no_untradeable_in_top_n": n_untradeable == 0,
            "less_than_20pct_clipped": (n_clipped / len(top_n) * 100 if top_n else 0) < 20,
            "cash_drag_below_5pct": sim.get("cash_drag_pct", 0) < 5.0,
            "no_position_above_20pct_adv": n_above_20pct == 0,
        },
    }

    return report


# ═════════════════════════════════════════════════════════════════════════
# Multi-snapshot trend analysis
# ═════════════════════════════════════════════════════════════════════════


def run_multi_snapshot_audit(
    snapshots_dir: Path,
    price_csv: Path,
    portfolio_nav: float = 3_000_000.0,
    target_top_n: int = 30,
    max_snapshots: int = 20,
) -> Dict[str, Any]:
    """Run capacity audit across recent snapshots for trend analysis."""

    snap_dates = _discover_snapshot_dates(snapshots_dir)
    snap_dates = snap_dates[-max_snapshots:]

    date_summaries = []
    for snap_date in snap_dates:
        snap_dir = snapshots_dir / snap_date
        report = run_audit(snap_dir, snap_date, price_csv, portfolio_nav, target_top_n)
        if "error" in report:
            continue

        sf = report["sizing_feasibility"]
        date_summaries.append(
            {
                "date": snap_date,
                "n_eligible": report["n_eligible"],
                "n_in_top_n": report["n_in_top_n"],
                "n_clipped": sf["n_clipped"],
                "pct_clipped": sf["pct_clipped"],
                "capacity_utilization": sf["capacity_utilization"],
                "n_untradeable": sf["n_untradeable"],
                "n_micro": sf["n_micro_size_only"],
                "cash_drag_pct": report["constrained_simulation"]["cash_drag_pct"],
            }
        )

    if not date_summaries:
        return {"error": "no_data", "snapshots_dir": str(snapshots_dir)}

    # Trend stats
    utils = [d["capacity_utilization"] for d in date_summaries]
    clipped_pcts = [d["pct_clipped"] for d in date_summaries]
    drags = [d["cash_drag_pct"] for d in date_summaries]

    return {
        "schema": "capacity_audit_multi.v2",
        "snapshots_dir": str(snapshots_dir),
        "portfolio_nav": portfolio_nav,
        "target_top_n": target_top_n,
        "n_snapshots": len(date_summaries),
        "trend_summary": {
            "avg_capacity_utilization": round(statistics.mean(utils), 4),
            "min_capacity_utilization": round(min(utils), 4),
            "max_capacity_utilization": round(max(utils), 4),
            "avg_pct_clipped": round(statistics.mean(clipped_pcts), 1),
            "max_pct_clipped": round(max(clipped_pcts), 1),
            "avg_cash_drag_pct": round(statistics.mean(drags), 2),
            "max_cash_drag_pct": round(max(drags), 2),
        },
        "trend_detail": date_summaries,
        "pass_fail": {
            "avg_utilization_gt_80pct": statistics.mean(utils) > 0.80,
            "no_date_below_60pct_util": min(utils) > 0.60,
            "avg_clipped_below_20pct": statistics.mean(clipped_pcts) < 20,
            "avg_cash_drag_below_5pct": statistics.mean(drags) < 5.0,
        },
    }


# ═════════════════════════════════════════════════════════════════════════
# CLI
# ═════════════════════════════════════════════════════════════════════════


def main() -> None:
    parser = argparse.ArgumentParser(description="Execution capacity audit (on-the-fly from price_history.csv)")
    parser.add_argument(
        "--snapshot-dir",
        type=Path,
        default=None,
        help="Single snapshot directory to audit (e.g., data/snapshots_pit_v2/2026-04-02)",
    )
    parser.add_argument(
        "--snapshots-dir",
        type=Path,
        default=DEFAULT_SNAPSHOTS_DIR,
        help="Directory containing dated snapshot subdirectories",
    )
    parser.add_argument(
        "--prices",
        type=Path,
        default=DEFAULT_PRICE_CSV,
        help="Path to price_history.csv",
    )
    parser.add_argument(
        "--nav",
        type=float,
        default=3_000_000.0,
        help="Portfolio NAV in dollars",
    )
    parser.add_argument("--top-n", type=int, default=30, help="Target top-N positions")
    parser.add_argument(
        "--multi",
        action="store_true",
        help="Run across all recent snapshots for trend analysis",
    )
    parser.add_argument("--output", type=Path, default=None, help="Output JSON path")
    args = parser.parse_args()

    if args.multi:
        report = run_multi_snapshot_audit(args.snapshots_dir, args.prices, args.nav, args.top_n)
    elif args.snapshot_dir:
        # Infer date from directory name
        snap_date = args.snapshot_dir.name
        report = run_audit(args.snapshot_dir, snap_date, args.prices, args.nav, args.top_n)
    else:
        # Default: most recent snapshot
        snap_dates = _discover_snapshot_dates(args.snapshots_dir)
        if not snap_dates:
            logger.error("No snapshots found in %s", args.snapshots_dir)
            sys.exit(1)
        snap_date = snap_dates[-1]
        snap_dir = args.snapshots_dir / snap_date
        report = run_audit(snap_dir, snap_date, args.prices, args.nav, args.top_n)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)
        logger.info("Report written to %s", args.output)
    else:
        print(json.dumps(report, indent=2, default=str))

    # ── Summary ─────────────────────────────────────────────────────
    pf = report.get("pass_fail", {})
    if pf:
        passes = sum(1 for v in pf.values() if v)
        total = len(pf)

        print("\n" + "=" * 60)
        if "trend_summary" in report:
            ts = report["trend_summary"]
            print("CAPACITY AUDIT — MULTI-SNAPSHOT SUMMARY")
            print("=" * 60)
            print(f"  Snapshots:     {report['n_snapshots']}")
            print(f"  Avg util:      {ts['avg_capacity_utilization']:.1%}")
            print(f"  Avg clipped:   {ts['avg_pct_clipped']:.1f}%")
            print(f"  Avg cash drag: {ts['avg_cash_drag_pct']:.2f}%")
        else:
            sf = report.get("sizing_feasibility", {})
            print("CAPACITY AUDIT — SINGLE SNAPSHOT")
            print("=" * 60)
            print(f"  Date:          {report.get('snapshot_date', '?')}")
            print(f"  NAV:           ${report.get('portfolio_nav', 0):,.0f}")
            print(f"  Top-N:         {report.get('n_in_top_n', 0)}")
            print(f"  Utilization:   {sf.get('capacity_utilization', 0):.1%}")
            print(f"  Clipped:       {sf.get('n_clipped', 0)} ({sf.get('pct_clipped', 0):.1f}%)")
            print(f"  Untradeable:   {sf.get('n_untradeable', 0)}")
            cs = report.get("constrained_simulation", {})
            print(f"  Cash drag:     {cs.get('cash_drag_pct', 0):.2f}%")

        status = "PASS" if passes == total else "FAIL"
        print(f"\n  Pass/fail:     {passes}/{total} [{status}]")
        if passes < total:
            failed = [k for k, v in pf.items() if not v]
            for f_name in failed:
                print(f"    FAIL: {f_name}")
        print("=" * 60)


if __name__ == "__main__":
    main()
