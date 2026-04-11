#!/usr/bin/env python3
"""EES interaction test — is trap additive to quality, or redundant?

Four analyses:
  1. Trap performance WITHIN top-quality decile
  2. Quality performance WITHIN non-trap names
  3. 2D decile grid (quality x trap → mean forward return)
  4. Horizon split (5d vs 20d vs 63d by overlay)

Uses the v2 model output directly from score_batch.
"""

from __future__ import annotations

import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from event_ev.expectation_error_model import ExpectationErrorModel
from scripts.eval_forward_returns import (
    compute_forward_return,
    discover_snapshot_dates,
    load_price_series,
    load_rankings,
    resolve_trade_date,
    spearman_ic,
)

HORIZONS = [5, 20, 63]
model = ExpectationErrorModel()


def _quintile(vals: List[float], v: float) -> int:
    """Assign value to quintile 1-5 (1=lowest, 5=highest)."""
    s = sorted(vals)
    n = len(s)
    for q in range(1, 6):
        threshold_idx = min(int(n * q / 5), n - 1)
        if v <= s[threshold_idx]:
            return q
    return 5


def run_interaction(
    snapshot_root: Path,
    price_csv: Path,
    date_from: str = "2022-03-18",
    date_to: str = "2026-03-31",
) -> Dict[str, Any]:
    snap_dates = discover_snapshot_dates(snapshot_root, date_from, date_to)
    prices = load_price_series(price_csv)

    all_dates_set: set = set()
    for tp in prices.values():
        all_dates_set.update(tp.keys())
    sorted_dates = sorted(all_dates_set)

    # Accumulators
    # 1. Conditional IC: trap within top-quality quintile
    trap_in_top_quality_ic: Dict[int, List[float]] = defaultdict(list)
    quality_in_nontrap_ic: Dict[int, List[float]] = defaultdict(list)

    # 2. 2D grid: (quality_q, trap_q) → [forward_returns]
    grid_returns: Dict[int, Dict[Tuple[int, int], List[float]]] = {h: defaultdict(list) for h in HORIZONS}

    # 3. Horizon split per overlay
    overlay_ic: Dict[str, Dict[int, List[float]]] = {
        "quality": defaultdict(list),
        "trap": defaultdict(list),
        "v2": defaultdict(list),
    }

    n_dates = 0

    for snap_date in snap_dates:
        trade_date = resolve_trade_date(sorted_dates, snap_date, "next_trading_day")
        if not trade_date:
            continue

        rankings = load_rankings(snapshot_root / snap_date)
        if not rankings:
            continue

        scores = model.score_batch(rankings, snap_date)
        if not scores:
            continue

        # Build signal maps
        quality_map = {s.ticker: s.quality_overlay_score for s in scores}
        trap_map = {s.ticker: s.trap_overlay_score for s in scores}
        v2_map = {s.ticker: s.ees_v2_score for s in scores}

        n_dates += 1

        for h in HORIZONS:
            # Forward returns
            fwd: Dict[str, float] = {}
            for ticker in quality_map:
                if ticker in prices:
                    ret = compute_forward_return(prices[ticker], sorted_dates, trade_date, h)
                    if ret is not None:
                        fwd[ticker] = ret

            if len(fwd) < 20:
                continue

            common = [t for t in quality_map if t in fwd and t in trap_map]
            if len(common) < 20:
                continue

            # Quintile assignments
            q_vals = [quality_map[t] for t in common]
            t_vals = [trap_map[t] for t in common]
            # v2_vals not needed for grid/conditional — only for per-overlay IC below

            q_quintiles = {t: _quintile(q_vals, quality_map[t]) for t in common}
            t_quintiles = {t: _quintile(t_vals, trap_map[t]) for t in common}

            # --- Analysis 1: Trap IC within top-quality quintile ---
            top_q = [t for t in common if q_quintiles[t] == 5]
            if len(top_q) >= 10:
                ic = spearman_ic([trap_map[t] for t in top_q], [fwd[t] for t in top_q])
                if ic is not None:
                    trap_in_top_quality_ic[h].append(ic)

            # --- Analysis 2: Quality IC within non-bottom-trap quintile ---
            non_trap = [t for t in common if t_quintiles[t] >= 2]
            if len(non_trap) >= 10:
                ic = spearman_ic([quality_map[t] for t in non_trap], [fwd[t] for t in non_trap])
                if ic is not None:
                    quality_in_nontrap_ic[h].append(ic)

            # --- Analysis 3: 2D grid ---
            for t in common:
                cell = (q_quintiles[t], t_quintiles[t])
                grid_returns[h][cell].append(fwd[t])

            # --- Analysis 4: Per-overlay IC ---
            if len(common) >= 10:
                ic_q = spearman_ic([quality_map[t] for t in common], [fwd[t] for t in common])
                ic_t = spearman_ic([trap_map[t] for t in common], [fwd[t] for t in common])
                ic_v = spearman_ic([v2_map[t] for t in common], [fwd[t] for t in common])
                if ic_q is not None:
                    overlay_ic["quality"][h].append(ic_q)
                if ic_t is not None:
                    overlay_ic["trap"][h].append(ic_t)
                if ic_v is not None:
                    overlay_ic["v2"][h].append(ic_v)

    return {
        "n_dates": n_dates,
        "trap_in_top_quality_ic": {h: _ic_summary(ics) for h, ics in trap_in_top_quality_ic.items()},
        "quality_in_nontrap_ic": {h: _ic_summary(ics) for h, ics in quality_in_nontrap_ic.items()},
        "grid_2d": {h: _grid_summary(cells) for h, cells in grid_returns.items()},
        "overlay_ic": {name: {h: _ic_summary(ics) for h, ics in by_h.items()} for name, by_h in overlay_ic.items()},
    }


def _ic_summary(ics: List[float]) -> Dict[str, Any]:
    if not ics:
        return {"mean_ic": None, "t_stat": None, "hit_rate": None, "n": 0}
    m = statistics.mean(ics)
    s = statistics.stdev(ics) if len(ics) >= 2 else 0
    t = m / (s / math.sqrt(len(ics))) if s > 0 else 0
    hr = sum(1 for ic in ics if ic > 0) / len(ics)
    return {
        "mean_ic": round(m, 4),
        "t_stat": round(t, 2),
        "hit_rate": round(hr, 3),
        "n": len(ics),
    }


def _grid_summary(cells: Dict[Tuple[int, int], List[float]]) -> List[Dict[str, Any]]:
    rows = []
    for (qq, tq), rets in sorted(cells.items()):
        if rets:
            rows.append(
                {
                    "quality_q": qq,
                    "trap_q": tq,
                    "mean_ret": round(statistics.mean(rets), 6),
                    "n_obs": len(rets),
                }
            )
    return rows


def main() -> None:
    snapshot_root = PROJECT_ROOT / "data" / "snapshots"
    price_csv = PROJECT_ROOT / "production_data" / "price_history.csv"
    out_dir = PROJECT_ROOT / "output" / "ees_interaction"
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Running EES interaction test...")
    results = run_interaction(snapshot_root, price_csv)

    with open(out_dir / "interaction_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)

    n = results["n_dates"]
    print(f"\nEvaluated {n} snapshot dates\n")

    # --- Print conditional IC ---
    print("=" * 70)
    print("  CONDITIONAL IC: Is trap additive to quality?")
    print("=" * 70)
    print(
        f"\n{'Horizon':>8s}  {'Trap|TopQ IC':>12s}  {'t':>7s}  {'hit':>6s}  {'Q|NonTrap IC':>14s}  {'t':>7s}  {'hit':>6s}"
    )
    print("-" * 70)
    for h in HORIZONS:
        tq = results["trap_in_top_quality_ic"].get(h, {})
        qn = results["quality_in_nontrap_ic"].get(h, {})

        def _fmt(d):
            if not d or d.get("mean_ic") is None:
                return "—", "—", "—"
            return f"{d['mean_ic']:+.4f}", f"{d['t_stat']:+.2f}", f"{d['hit_rate']:.0%}"

        ti, tt, th = _fmt(tq)
        qi, qt, qh = _fmt(qn)
        print(f"{h:>5d}d    {ti:>12s}  {tt:>7s}  {th:>6s}  {qi:>14s}  {qt:>7s}  {qh:>6s}")

    # --- Print 2D grid ---
    for h in HORIZONS:
        grid = results["grid_2d"].get(h, [])
        if not grid:
            continue

        print(f"\n{'=' * 70}")
        print(f"  2D GRID: {h}d mean return by (quality quintile × trap quintile)")
        print(f"{'=' * 70}")
        print(f"{'':>12s}", end="")
        for tq in range(1, 6):
            print(f"  Trap Q{tq:d}  ", end="")
        print()

        # Build lookup
        lookup = {}
        for row in grid:
            lookup[(row["quality_q"], row["trap_q"])] = row["mean_ret"]

        for qq in range(1, 6):
            label = f"Quality Q{qq}"
            print(f"{label:>12s}", end="")
            for tq in range(1, 6):
                val = lookup.get((qq, tq))
                if val is not None:
                    print(f"  {val:+.4f}  ", end="")
                else:
                    print("     —     ", end="")
            print()

        # Row/col marginals
        print("\n  Corner spread (Q5/Q5 vs Q1/Q1): ", end="")
        top = lookup.get((5, 5))
        bot = lookup.get((1, 1))
        if top is not None and bot is not None:
            print(f"{top - bot:+.4f}")
        else:
            print("—")

    # --- Print horizon split ---
    print(f"\n{'=' * 70}")
    print("  HORIZON SPLIT: IC by overlay and horizon")
    print(f"{'=' * 70}")
    print(f"{'Overlay':<12s}", end="")
    for h in HORIZONS:
        print(f"  {h:>3d}d IC  {h:>3d}d t  ", end="")
    print()
    print("-" * 70)
    for name in ["quality", "trap", "v2"]:
        by_h = results["overlay_ic"].get(name, {})
        print(f"{name:<12s}", end="")
        for h in HORIZONS:
            d = by_h.get(h, {})
            if d and d.get("mean_ic") is not None:
                print(f"  {d['mean_ic']:+.4f}  {d['t_stat']:+.2f}  ", end="")
            else:
                print("     —       —   ", end="")
        print()

    print(f"\nWritten: {out_dir / 'interaction_results.json'}")


if __name__ == "__main__":
    main()
