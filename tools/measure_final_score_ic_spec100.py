#!/usr/bin/env python3
"""
Spec 100: Measure final_score IC on eligible universe only.

This tool computes the corrected ranker IC for final_score, scoped to the eligible
universe (post-gate, ~60 tickers) as required by Spec 100/095.

Compares against composite_score IC (full universe, 295+ tickers) as diagnostic reference
(INVALIDATED for ranker evidence).

Usage:
    python3 tools/measure_final_score_ic_spec100.py --start-date 2026-06-01 --end-date 2026-06-18
    python3 tools/measure_final_score_ic_spec100.py --start-date 2026-06-01 --end-date 2026-06-18 --dry-run

    # Read-only standalone signal IC diagnostics (does NOT change the ranker):
    python3 tools/measure_final_score_ic_spec100.py --score-field catalyst_score --dry-run
    python3 tools/measure_final_score_ic_spec100.py --score-field coinvest_score_z --dry-run

The --score-field argument defaults to "final_score" (original Spec 100 behavior,
byte-identical when unspecified). Non-default fields write field-suffixed output
files so they never overwrite the production DEM IC artifacts.
"""

import argparse
import csv
import json
import math
import statistics
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _sf(v, default=float("nan")):
    """Safe float conversion."""
    if v is None or v == "":
        return default
    try:
        f = float(v)
        return f if f == f else default
    except (ValueError, TypeError):
        return default


def _rank(vals: List[float]) -> List[float]:
    """Compute ranks for a list of values. Handles NaNs and Nones."""
    n = len(vals)

    def sort_key(i):
        v = vals[i]
        try:
            f = float(v) if v is not None else float("nan")
            if f != f:  # NaN check
                return (float("inf"), i)
            return (f, i)
        except (TypeError, ValueError):
            return (float("inf"), i)

    indexed = sorted(range(n), key=sort_key)
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        vi = vals[indexed[i]]
        while j < n - 1:
            vj_next = vals[indexed[j + 1]]
            if vj_next == vi or (vi != vi and vj_next != vj_next):  # equal or both NaN
                j += 1
            else:
                break
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[indexed[k]] = avg
        i = j + 1
    return ranks


def _spearman_ic(x: List[float], y: List[float]) -> Tuple[float, float]:
    """Compute Spearman rank correlation and t-stat. Returns (ic, t_stat)."""
    n = len(x)
    if n < 5:
        return (float("nan"), float("nan"))

    # Remove NaNs and align
    valid_idx = [i for i in range(n) if x[i] == x[i] and y[i] == y[i]]
    if len(valid_idx) < 5:
        return (float("nan"), float("nan"))

    x_clean = [x[i] for i in valid_idx]
    y_clean = [y[i] for i in valid_idx]

    # Rank
    x_ranks = _rank(x_clean)
    y_ranks = _rank(y_clean)

    # Correlation
    n_clean = len(x_clean)
    mx = sum(x_ranks) / n_clean
    my = sum(y_ranks) / n_clean

    num = sum((x_ranks[i] - mx) * (y_ranks[i] - my) for i in range(n_clean))
    dx = math.sqrt(sum((x_ranks[i] - mx) ** 2 for i in range(n_clean)))
    dy = math.sqrt(sum((y_ranks[i] - my) ** 2 for i in range(n_clean)))

    if dx < 1e-9 or dy < 1e-9:
        # Zero variance in scores (dx) or returns (dy) — IC unobservable, not zero.
        # dy near zero typically means stale snapshot prices (all forward returns = 0).
        return (float("nan"), float("nan"))

    ic = num / (dx * dy)

    # t-stat
    t_stat = 0.0
    if abs(ic) < 1.0:
        t_stat = ic * math.sqrt(n_clean - 2) / math.sqrt(1 - ic**2)

    return (ic, t_stat)


def load_snapshot(snapshot_dir: Path) -> Optional[Dict]:
    """Load rankings.csv from snapshot."""
    rankings_file = snapshot_dir / "rankings.csv"
    if not rankings_file.exists():
        return None

    rows = []
    with open(rankings_file) as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    return {"date": snapshot_dir.name, "rows": rows}


def compute_forward_return(ticker: str, start_date: str, end_date: str, snapshots: Dict[str, Dict]) -> Optional[float]:
    """
    Compute forward return for a ticker between start_date and end_date.

    Uses close_price from snapshots. Returns (end_price - start_price) / start_price.
    """
    start_snap = snapshots.get(start_date)
    end_snap = snapshots.get(end_date)

    if not start_snap or not end_snap:
        return None

    # Find ticker rows
    start_row = None
    for r in start_snap["rows"]:
        if r.get("ticker", "").strip() == ticker.strip():
            start_row = r
            break

    end_row = None
    for r in end_snap["rows"]:
        if r.get("ticker", "").strip() == ticker.strip():
            end_row = r
            break

    if not start_row or not end_row:
        return None

    start_price = _sf(start_row.get("close_price"))
    end_price = _sf(end_row.get("close_price"))

    if start_price != start_price or end_price != end_price or start_price <= 0:
        return None

    return (end_price - start_price) / start_price


def resolve_forward_date(
    requested_date: str,
    available_dates,
    mode: str = "exact",
    tolerance_days: int = 0,
    explicit_forward_date: Optional[str] = None,
) -> Tuple[Optional[str], Optional[int], bool, str]:
    """Resolve which forward snapshot date to use for forward-return computation.

    Returns (observed_date | None, delta_days | None, used_fallback, reason).

    Behavior:
      - explicit_forward_date (if given) overrides mode/tolerance; it must exist
        in available_dates or the result is unobservable.
      - mode == "exact" (DEFAULT): only the requested_date qualifies. This is the
        original tool behavior, preserved byte-for-byte when no new flags are passed.
      - mode == "nearest_later": prefer requested_date; otherwise the earliest
        available date strictly AFTER requested_date and within tolerance_days.

    Never substitutes an EARLIER date than requested. When nothing qualifies,
    returns (None, None, False, <reason>) so the caller can mark UNOBSERVABLE.
    """
    avail = set(available_dates)
    req_dt = datetime.strptime(requested_date, "%Y-%m-%d")
    if explicit_forward_date is not None:
        if explicit_forward_date in avail:
            delta = (datetime.strptime(explicit_forward_date, "%Y-%m-%d") - req_dt).days
            return (
                explicit_forward_date,
                delta,
                explicit_forward_date != requested_date,
                "explicit_forward_date",
            )
        return (None, None, False, f"explicit forward-date {explicit_forward_date} has no snapshot")
    if requested_date in avail:
        return (requested_date, 0, False, "exact")
    if mode == "exact":
        return (None, None, False, f"exact forward snapshot {requested_date} missing (mode=exact)")
    # nearest_later: search strictly-later dates within tolerance, soonest first.
    for k in range(1, tolerance_days + 1):
        cand = (req_dt + timedelta(days=k)).strftime("%Y-%m-%d")
        if cand in avail:
            return (cand, k, True, f"nearest_later within {tolerance_days}d")
    return (None, None, False, f"no forward snapshot in ({requested_date}, +{tolerance_days}d]")


def measure_final_score_ic(
    snapshot: Dict,
    forward_snapshots: Dict[str, Dict],
    horizon_days: int,
    score_field: str = "final_score",
    forward_date_mode: str = "exact",
    forward_tolerance_days: int = 0,
    explicit_forward_date: Optional[str] = None,
) -> Optional[Dict]:
    """
    Measure score_field IC on ranker cohort only (actionable_rank <= 60).

    Spec 100 scope: eligible universe post-gate, which for the ranker is the
    top-60 by actionable_rank (the cohort the ranker actually ranks).

    score_field selects which column to correlate against forward returns.
    DEFAULT is "final_score" — the original Spec 100 behavior, byte-identical
    when score_field is unspecified. Other fields (e.g. catalyst_score,
    coinvest_score_z) enable read-only standalone signal IC diagnostics; passing
    a non-default field does NOT change the production ranker in any way.

    Result dict keys retain the `final_score_*` names for backward compatibility
    with downstream readers; `score_field` records which column was actually used.

    Returns: {
        "date": snapshot_date,
        "score_field": field_used,
        "eligible_count": n_eligible,
        "final_score_ic": ic_value,          # IC of score_field (key name kept stable)
        "final_score_t_stat": t_stat,
        "final_score_observations": n_observations,
        "composite_score_ic": ic_value (diagnostic only),
        "composite_score_t_stat": t_stat (diagnostic only),
        "composite_score_observations": n_observations (diagnostic only)
    }
    """
    rows = snapshot["rows"]
    snap_date = snapshot["date"]

    # Compute requested future date, then resolve to an available snapshot.
    snap_dt = datetime.strptime(snap_date, "%Y-%m-%d")
    future_dt = snap_dt + timedelta(days=horizon_days)
    requested_forward_date = future_dt.strftime("%Y-%m-%d")
    observed_forward_date, forward_delta_days, forward_fallback_used, forward_reason = resolve_forward_date(
        requested_forward_date,
        forward_snapshots.keys(),
        forward_date_mode,
        forward_tolerance_days,
        explicit_forward_date,
    )
    # `future_date` retained for backward-compat; may be None (then forward
    # returns are NaN and the field IC is unobservable).
    future_date = observed_forward_date

    # Filter to ranker cohort: actionable_rank <= 60 (the top-K that ranker ranks)
    eligible_rows = []
    for r in rows:
        try:
            rank = _sf(r.get("actionable_rank"))
            if rank == rank and rank <= 60:  # not NaN and <= 60
                eligible_rows.append(r)
        except Exception:
            pass

    if len(eligible_rows) < 10:
        return {
            "date": snap_date,
            "eligible_count": len(eligible_rows),
            "error": f"Insufficient cohort rows: {len(eligible_rows)} < 10",
        }

    # Measure score_field IC on eligible universe (default: final_score).
    # If the forward snapshot was unresolved (observed_forward_date is None),
    # skip forward-return computation entirely so the result is genuinely
    # UNOBSERVABLE (obs=0, IC=NaN) rather than a misleading measured 0.0000.
    final_scores = []
    fwd_returns = []
    if future_date is not None:
        for row in eligible_rows:
            ticker = row.get("ticker", "").strip()
            fs = _sf(row.get(score_field))
            fret = compute_forward_return(ticker, snap_date, future_date, forward_snapshots)

            # `fret is not None` is required: compute_forward_return returns None
            # (not NaN) for missing data, and `None == None` would otherwise pass
            # the NaN guard and inject a None "return".
            if fret is not None and fs == fs and fret == fret:
                final_scores.append(fs)
                fwd_returns.append(fret)

    # Detect stale snapshot prices: if >80% of forward returns are exactly 0.0,
    # the forward snapshot likely carries the same close_price as the base snapshot
    # (price refresh failed). IC is unobservable in that case.
    stale_prices = False
    if fwd_returns:
        zero_frac = sum(1 for r in fwd_returns if r == 0.0) / len(fwd_returns)
        if zero_frac > 0.8:
            stale_prices = True

    final_score_ic = float("nan")
    final_score_t_stat = float("nan")
    if len(final_scores) >= 5 and not stale_prices:
        final_score_ic, final_score_t_stat = _spearman_ic(final_scores, fwd_returns)

    # Diagnostic: measure composite_score IC on full universe (INVALIDATED for ranker)
    composite_scores = []
    fwd_returns_full = []
    if future_date is not None:
        for row in rows:
            ticker = row.get("ticker", "").strip()
            cs = _sf(row.get("composite_score"))
            fret = compute_forward_return(ticker, snap_date, future_date, forward_snapshots)

            if fret is not None and cs == cs and fret == fret:
                composite_scores.append(cs)
                fwd_returns_full.append(fret)

    composite_ic = float("nan")
    composite_t_stat = float("nan")
    if len(composite_scores) >= 5:
        composite_ic, composite_t_stat = _spearman_ic(composite_scores, fwd_returns_full)

    return {
        "date": snap_date,
        "score_field": score_field,
        "horizon_days": horizon_days,
        "future_date": future_date,
        "requested_forward_date": requested_forward_date,
        "observed_forward_date": observed_forward_date,
        "forward_date_delta_days": forward_delta_days,
        "forward_date_mode": forward_date_mode,
        "forward_fallback_used": forward_fallback_used,
        "forward_unobservable_reason": None if observed_forward_date else forward_reason,
        "stale_prices": stale_prices,
        "eligible_count": len(eligible_rows),
        "final_score_observations": len(final_scores) if not stale_prices else 0,
        "final_score_ic": final_score_ic,
        "final_score_t_stat": final_score_t_stat,
        "composite_score_observations": len(composite_scores),
        "composite_score_ic": composite_ic,
        "composite_score_t_stat": composite_t_stat,
        "composite_score_caveat": "INVALIDATED_DIAGNOSTIC_REFERENCE_ONLY",
    }


def discover_snapshots(root: Path, start_date: str, end_date: str) -> List[str]:
    """Find snapshot dates in range."""
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")

    snapshots = []
    current = start_dt
    while current <= end_dt:
        snap_dir = root / current.strftime("%Y-%m-%d")
        if (snap_dir / "rankings.csv").exists():
            snapshots.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)

    return sorted(snapshots)


def main():
    parser = argparse.ArgumentParser(description="Spec 100: Measure final_score IC on eligible universe only")
    parser.add_argument("--start-date", default="2026-06-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", default="2026-06-18", help="End date (YYYY-MM-DD)")
    parser.add_argument("--snapshot-dir", default="data/snapshots", help="Snapshots root directory")
    parser.add_argument("--output-dir", default="artifacts/audit", help="Output directory")
    parser.add_argument("--horizons", nargs="*", type=int, default=[5, 10, 20], help="Horizons in days")
    parser.add_argument(
        "--score-field",
        default="final_score",
        help="Column to correlate against forward returns (default: final_score). "
        "Use e.g. catalyst_score / catalyst_decay_w / coinvest_score_z for "
        "read-only standalone signal IC diagnostics. Non-default values do NOT "
        "change the production ranker.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Audit only; no writes")
    parser.add_argument(
        "--forward-date-mode",
        choices=["exact", "nearest_later"],
        default="exact",
        help="Forward snapshot resolution. 'exact' (default) = original behavior: "
        "the base+horizon date must have a snapshot. 'nearest_later' = allow "
        "the soonest later snapshot within --forward-tolerance-days.",
    )
    parser.add_argument(
        "--forward-tolerance-days",
        type=int,
        default=0,
        help="Max calendar days AFTER the requested forward date to search "
        "(only used when --forward-date-mode=nearest_later).",
    )
    parser.add_argument(
        "--forward-date",
        default=None,
        help="Explicit forward snapshot date (YYYY-MM-DD) override; must exist. "
        "Bypasses --forward-date-mode/--forward-tolerance-days.",
    )

    args = parser.parse_args()

    snap_root = Path(args.snapshot_dir)
    out_dir = Path(args.output_dir)
    score_field = args.score_field
    is_default_field = score_field == "final_score"

    print(f"Spec 100 {score_field} IC: {args.start_date} to {args.end_date}")
    print(f"Horizons: {args.horizons}")
    print(f"Snapshots root: {snap_root}")

    # Discover snapshots
    snap_dates = discover_snapshots(snap_root, args.start_date, args.end_date)
    print(
        f"Found {len(snap_dates)} snapshots: {snap_dates[0] if snap_dates else 'none'} through {snap_dates[-1] if snap_dates else 'none'}"
    )

    if not snap_dates:
        print("No snapshots found. Exiting.")
        return

    # Load all snapshots for forward-return computation
    print("Loading snapshots...")
    all_snapshots = {}
    for snap_date in snap_dates:
        snap = load_snapshot(snap_root / snap_date)
        if snap:
            all_snapshots[snap_date] = snap

    print(f"Loaded {len(all_snapshots)} snapshots")

    # Compute IC for each snapshot and horizon
    results_by_horizon = {h: [] for h in args.horizons}

    for snap_date in snap_dates:
        snap = all_snapshots.get(snap_date)
        if not snap:
            continue

        for horizon in args.horizons:
            result = measure_final_score_ic(
                snap,
                all_snapshots,
                horizon,
                score_field,
                forward_date_mode=args.forward_date_mode,
                forward_tolerance_days=args.forward_tolerance_days,
                explicit_forward_date=args.forward_date,
            )
            if result and "error" not in result:
                results_by_horizon[horizon].append(result)
                ic_str = (
                    f"{result['final_score_ic']:.4f}" if result["final_score_ic"] == result["final_score_ic"] else "nan"
                )
                print(
                    f"  {snap_date} T+{horizon}: eligible={result['eligible_count']}, "
                    f"obs={result['final_score_observations']}, IC={ic_str}, "
                    f"t={result['final_score_t_stat']:.2f}"
                    if result["final_score_t_stat"] == result["final_score_t_stat"]
                    else f"  {snap_date} T+{horizon}: eligible={result['eligible_count']}, "
                    f"obs={result['final_score_observations']}, IC={ic_str}, t=nan"
                )
                if result.get("stale_prices"):
                    print(
                        f"    [stale-prices] forward snapshot {result.get('observed_forward_date')} has same close_price as base — IC unobservable"
                    )
                elif result.get("forward_fallback_used"):
                    print(
                        f"    [forward-fallback] requested {result['requested_forward_date']} -> "
                        f"observed {result['observed_forward_date']} (+{result['forward_date_delta_days']}d)"
                    )
                elif result.get("observed_forward_date") is None:
                    print(f"    [forward-unobservable] {result.get('forward_unobservable_reason')}")
            elif result:
                print(f"  {snap_date} T+{horizon}: {result.get('error', 'unknown error')}")

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)

    for horizon in args.horizons:
        results = results_by_horizon[horizon]
        if not results:
            print(f"\nT+{horizon}: NO DATA")
            continue

        ic_values = [r["final_score_ic"] for r in results if r["final_score_ic"] == r["final_score_ic"]]
        t_values = [r["final_score_t_stat"] for r in results if r["final_score_t_stat"] == r["final_score_t_stat"]]

        if ic_values:
            mean_ic = statistics.mean(ic_values)
            std_ic = statistics.stdev(ic_values) if len(ic_values) > 1 else 0.0
            mean_t = statistics.mean(t_values) if t_values else float("nan")
            pct_positive = sum(1 for x in ic_values if x > 0) / len(ic_values) if ic_values else 0.0

            print(f"\nT+{horizon}:")
            print(f"  Observations: {len(results)} dates")
            print(
                f"  {score_field} IC: mean={mean_ic:.4f}, std={std_ic:.4f}, min={min(ic_values):.4f}, max={max(ic_values):.4f}"
            )
            print(f"  t-statistic: mean={mean_t:.2f}")
            print(f"  Pct positive: {pct_positive:.1%}")
            print(f"  >= 0.0200 threshold: {'YES' if mean_ic >= 0.0200 else 'NO'}")
        else:
            print(f"\nT+{horizon}: UNOBSERVABLE (no valid observations)")

    # Write results if not dry-run
    if not args.dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)

        # Output filenames: default (final_score) keeps the original DEM-gate names
        # byte-for-byte; non-default fields get a field-suffixed name so they never
        # clobber the production DEM IC artifacts.
        if is_default_field:
            summary_basename = "dem_ranker_phase_2b_final_score_ic_summary.json"
            csv_prefix = "dem_ranker_phase_2b_final_score_ic"
        else:
            safe_field = score_field.replace("/", "_")
            summary_basename = f"signal_ic_{safe_field}_summary.json"
            csv_prefix = f"signal_ic_{safe_field}"

        # Write JSON summary
        summary = {
            "score_field": score_field,
            "forward_date_mode": args.forward_date_mode,
            "forward_tolerance_days": args.forward_tolerance_days,
            "explicit_forward_date": args.forward_date,
        }
        for horizon in args.horizons:
            results = results_by_horizon[horizon]
            ic_values = [r["final_score_ic"] for r in results if r["final_score_ic"] == r["final_score_ic"]]
            t_values = [r["final_score_t_stat"] for r in results if r["final_score_t_stat"] == r["final_score_t_stat"]]

            summary[f"T+{horizon}"] = {
                "n_observations": len(results),
                "n_valid_ic": len(ic_values),
                "mean_ic": statistics.mean(ic_values) if ic_values else None,
                "std_ic": statistics.stdev(ic_values) if len(ic_values) > 1 else None,
                "mean_t_stat": statistics.mean(t_values) if t_values else None,
                "passes_threshold_0_0200": statistics.mean(ic_values) >= 0.0200 if ic_values else False,
            }

        summary_file = out_dir / summary_basename
        with open(summary_file, "w") as f:
            json.dump(summary, f, indent=2)
        print(f"\nWrote: {summary_file}")

        # Write detailed results CSV for each horizon
        for horizon in args.horizons:
            results = results_by_horizon[horizon]
            if results:
                csv_file = out_dir / f"{csv_prefix}_T+{horizon}.csv"
                with open(csv_file, "w", newline="") as f:
                    fieldnames = [
                        "date",
                        "horizon_days",
                        "eligible_count",
                        "final_score_observations",
                        "final_score_ic",
                        "final_score_t_stat",
                        "composite_score_observations",
                        "composite_score_ic",
                        "composite_score_t_stat",
                    ]
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    for r in results:
                        writer.writerow({k: r.get(k) for k in fieldnames})
                print(f"Wrote: {csv_file}")


if __name__ == "__main__":
    main()
