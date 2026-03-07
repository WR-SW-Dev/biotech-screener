#!/usr/bin/env python3
"""Full-pipeline A/B evaluation for sizing-only features.

Unlike rerank_snapshots.py (which only re-sorts), this script re-runs the
full run_screen.py pipeline for each historical date with a candidate
ruleset, then evaluates forward returns. This is needed for features that
affect portfolio weights (catalyst_tilt, clinical_sizing) rather than sort
order.

Usage:
    python scripts/research/eval_sizing_ab.py \
        --ruleset production_data/decision_rulesets/research_catalyst_tilt_on.json \
        --date-from 2025-06-01 --date-to 2025-12-31 \
        --out-root data/snapshots_fullpipeline_catalyst_tilt \
        --data-dir production_data \
        [--horizons 20,63,126] [--top-k 20] [--dry-run]

Workflow:
    1. For each snapshot date in [date-from, date-to]:
       a. Run run_screen.py --as-of-date {date} --ruleset {candidate}
       b. Save snapshot to out-root/{date}/
    2. Run eval_forward_returns.py on the generated snapshots
    3. Print summary comparison vs baseline
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _discover_dates(snapshot_root: Path, date_from: str, date_to: str) -> list[str]:
    """Find existing snapshot dates in range to know which dates to evaluate."""
    import re

    date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    all_dates = sorted(d.name for d in snapshot_root.iterdir() if d.is_dir() and date_re.match(d.name))
    return [d for d in all_dates if date_from <= d <= date_to]


def _run_screen(
    as_of_date: str,
    data_dir: Path,
    ruleset_path: Path,
    snapshot_dir: Path,
    extra_args: list[str] | None = None,
) -> bool:
    """Run run_screen.py for a single date. Returns True on success."""
    cmd = [
        sys.executable,
        str(REPO_ROOT / "run_screen.py"),
        "--as-of-date",
        as_of_date,
        "--data-dir",
        str(data_dir),
        "--ruleset",
        str(ruleset_path),
        "--snapshot-dir",
        str(snapshot_dir),
        "--decision-mode",
        "phase2",
        "--ranking-mode",
        "decision",
        "--pit-mode",
        "degrade",
        "--no-enhancements",  # Speed: skip momentum/alpha enrichment
    ]
    if extra_args:
        cmd.extend(extra_args)

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=600,
        cwd=str(REPO_ROOT),
    )
    if result.returncode != 0:
        print(f"  FAIL {as_of_date}: exit {result.returncode}")
        if result.stderr:
            # Print last 5 lines of stderr for diagnosis
            for line in result.stderr.strip().split("\n")[-5:]:
                print(f"    {line}")
        return False
    return True


def _run_eval(
    snapshot_root: Path,
    out_dir: Path,
    ruleset_path: Path,
    date_from: str,
    date_to: str,
    horizons: str = "20,63,126",
    top_k: int = 20,
) -> dict | None:
    """Run eval_forward_returns.py and return summary dict."""
    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "eval_forward_returns.py"),
        "--snapshot-root",
        str(snapshot_root),
        "--date-from",
        date_from,
        "--date-to",
        date_to,
        "--horizons",
        horizons,
        "--top-k",
        str(top_k),
        "--out-dir",
        str(out_dir),
        "--ruleset",
        str(ruleset_path),
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=600,
        cwd=str(REPO_ROOT),
    )
    if result.returncode != 0:
        print(f"  Eval failed: {result.stderr[-500:]}")
        return None

    summary_path = out_dir / "summary.json"
    if summary_path.exists():
        with open(summary_path) as f:
            return json.load(f)
    return None


def _load_prices(data_dir: Path) -> Dict[str, Dict[str, float]]:
    """Load price_history.csv → {ticker: {date: close}}."""
    path = data_dir / "price_history.csv"
    prices: Dict[str, Dict[str, float]] = {}
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ticker = row.get("ticker") or row.get("Ticker") or ""
            date_str = row.get("date") or row.get("Date") or ""
            close_str = row.get("close") or row.get("Close") or ""
            if ticker and date_str and close_str:
                try:
                    prices.setdefault(ticker, {})[date_str] = float(close_str)
                except ValueError:
                    pass
    return prices


def _sorted_dates_from_prices(prices: Dict[str, Dict[str, float]]) -> List[str]:
    """Extract sorted unique dates from price data."""
    all_dates = set()
    for ticker_prices in prices.values():
        all_dates.update(ticker_prices.keys())
    return sorted(all_dates)


def _trading_days_after(sorted_dates: List[str], snap_date: str, horizon: int) -> Optional[str]:
    """Find the date that is `horizon` trading days after snap_date."""
    try:
        idx = sorted_dates.index(snap_date)
    except ValueError:
        # Binary search fallback
        import bisect

        idx = bisect.bisect_left(sorted_dates, snap_date)
        if idx >= len(sorted_dates) or sorted_dates[idx] != snap_date:
            return None
    target = idx + horizon
    if target >= len(sorted_dates):
        return None
    return sorted_dates[target]


def _forward_return(
    ticker_prices: Dict[str, float],
    sorted_dates: List[str],
    snap_date: str,
    horizon: int,
) -> Optional[float]:
    """P(t+h)/P(t) - 1."""
    p0 = ticker_prices.get(snap_date)
    if p0 is None or p0 <= 0:
        return None
    end_date = _trading_days_after(sorted_dates, snap_date, horizon)
    if end_date is None:
        return None
    p1 = ticker_prices.get(end_date)
    if p1 is None or p1 <= 0:
        return None
    return p1 / p0 - 1.0


def _read_rankings_weights(rankings_csv: Path, top_k: int) -> List[Tuple[str, float]]:
    """Read top-K tickers and their target_weight_pct from rankings.csv.

    Returns list of (ticker, weight_pct) for the top-K eligible holdings,
    sorted by actionable_rank.
    """
    rows = []
    with open(rankings_csv, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            eligible = row.get("eligible", "True")
            if eligible.lower() in ("false", "0", "no"):
                continue
            try:
                rank = int(row.get("actionable_rank", 9999))
            except (ValueError, TypeError):
                continue
            ticker = row.get("ticker", "")
            try:
                weight = float(row.get("target_weight_pct", 0))
            except (ValueError, TypeError):
                weight = 0.0
            if ticker and weight > 0:
                rows.append((rank, ticker, weight))

    rows.sort(key=lambda x: x[0])
    return [(ticker, weight) for _, ticker, weight in rows[:top_k]]


def _weighted_portfolio_return(
    holdings: List[Tuple[str, float]],
    fwd_rets: Dict[str, float],
) -> Optional[float]:
    """Compute portfolio return using target_weight_pct as weights.

    Normalizes weights to sum to 1.0 for the subset of tickers with
    available forward returns.
    """
    pairs = [(w, fwd_rets[t]) for t, w in holdings if t in fwd_rets]
    if not pairs:
        return None
    total_w = sum(w for w, _ in pairs)
    if total_w <= 0:
        return None
    return sum(w * r for w, r in pairs) / total_w


def _equal_weight_return(
    tickers: List[str],
    fwd_rets: Dict[str, float],
) -> Optional[float]:
    """Equal-weight return for the same set of tickers."""
    held = [t for t in tickers if t in fwd_rets]
    if not held:
        return None
    return statistics.mean(fwd_rets[t] for t in held)


def _compute_weighted_comparison(
    candidate_root: Path,
    baseline_root: Path,
    data_dir: Path,
    dates: List[str],
    horizons: List[int],
    top_k: int,
) -> Dict[int, Dict[str, float]]:
    """Compare weighted vs equal-weight returns across dates and horizons.

    For each date:
      - candidate: weighted return using target_weight_pct
      - baseline: equal-weight return for same top-K tickers from baseline
      - ew_candidate: equal-weight return for candidate top-K (shows rank effect)

    Returns {horizon: {metric: value}} summary.
    """
    prices = _load_prices(data_dir)
    sorted_dates = _sorted_dates_from_prices(prices)

    results: Dict[int, Dict[str, List[float]]] = {
        h: {"weighted": [], "ew_candidate": [], "ew_baseline": [], "weight_spread": []} for h in horizons
    }

    for snap_date in dates:
        cand_csv = candidate_root / snap_date / "rankings.csv"
        base_csv = baseline_root / snap_date / "rankings.csv"
        if not cand_csv.exists() or not base_csv.exists():
            continue

        cand_holdings = _read_rankings_weights(cand_csv, top_k)
        base_holdings = _read_rankings_weights(base_csv, top_k)
        if not cand_holdings:
            continue

        # Weight spread: max/min ratio in candidate (1.0 = equal weight)
        weights = [w for _, w in cand_holdings]
        if min(weights) > 0:
            results[horizons[0]]["weight_spread"].append(max(weights) / min(weights))

        for h in horizons:
            # Compute forward returns for this date
            fwd_rets: Dict[str, float] = {}
            all_tickers = set(t for t, _ in cand_holdings) | set(t for t, _ in base_holdings)
            for ticker in all_tickers:
                if ticker in prices:
                    ret = _forward_return(prices[ticker], sorted_dates, snap_date, h)
                    if ret is not None:
                        fwd_rets[ticker] = ret

            w_ret = _weighted_portfolio_return(cand_holdings, fwd_rets)
            ew_cand = _equal_weight_return([t for t, _ in cand_holdings], fwd_rets)
            ew_base = _equal_weight_return([t for t, _ in base_holdings], fwd_rets)

            if w_ret is not None:
                results[h]["weighted"].append(w_ret)
            if ew_cand is not None:
                results[h]["ew_candidate"].append(ew_cand)
            if ew_base is not None:
                results[h]["ew_baseline"].append(ew_base)

    summary: Dict[int, Dict[str, float]] = {}
    for h in horizons:
        r = results[h]
        n = len(r["weighted"])
        if n == 0:
            continue
        mean_w = statistics.mean(r["weighted"]) if r["weighted"] else 0.0
        mean_ew_c = statistics.mean(r["ew_candidate"]) if r["ew_candidate"] else 0.0
        mean_ew_b = statistics.mean(r["ew_baseline"]) if r["ew_baseline"] else 0.0
        sizing_delta = mean_w - mean_ew_c  # pure sizing effect
        rank_delta = mean_ew_c - mean_ew_b  # pure rank effect

        entry: Dict[str, float] = {
            "n_dates": n,
            "mean_weighted_ret": mean_w,
            "mean_ew_candidate_ret": mean_ew_c,
            "mean_ew_baseline_ret": mean_ew_b,
            "sizing_delta": sizing_delta,
            "rank_delta": rank_delta,
            "total_delta": mean_w - mean_ew_b,
        }
        # t-stat for sizing delta if enough dates
        if n >= 3 and r["weighted"] and r["ew_candidate"]:
            diffs = [w - e for w, e in zip(r["weighted"], r["ew_candidate"])]
            mean_d = statistics.mean(diffs)
            std_d = statistics.stdev(diffs)
            if std_d > 0:
                entry["sizing_t_stat"] = mean_d / (std_d / (n**0.5))

        if r["weight_spread"]:
            entry["mean_weight_spread"] = statistics.mean(r["weight_spread"])

        summary[h] = entry

    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ruleset", required=True, help="Candidate ruleset JSON path")
    parser.add_argument("--date-from", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--date-to", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--out-root", required=True, help="Output snapshot directory")
    parser.add_argument("--data-dir", default="production_data", help="Data directory for run_screen.py")
    parser.add_argument(
        "--reference-snapshots", default="data/snapshots", help="Existing baseline snapshot root (for date discovery)"
    )
    parser.add_argument("--horizons", default="20,63,126", help="Forward-return horizons")
    parser.add_argument("--top-k", type=int, default=20, help="Top-K for IC evaluation")
    parser.add_argument("--dry-run", action="store_true", help="Print dates without running")
    parser.add_argument("--max-dates", type=int, default=0, help="Limit number of dates (0=all)")
    parser.add_argument("--skip-screen", action="store_true", help="Skip screen runs, only eval")
    args = parser.parse_args()

    out_root = Path(args.out_root)
    ref_root = Path(args.reference_snapshots)
    data_dir = Path(args.data_dir)
    ruleset_path = Path(args.ruleset)

    if not ruleset_path.exists():
        print(f"ERROR: Ruleset not found: {ruleset_path}")
        sys.exit(1)

    # Discover dates from reference snapshots
    dates = _discover_dates(ref_root, args.date_from, args.date_to)
    if args.max_dates > 0:
        dates = dates[: args.max_dates]

    print(f"Full-pipeline A/B eval: {len(dates)} dates, {args.date_from} to {args.date_to}")
    print(f"  Ruleset: {ruleset_path}")
    print(f"  Output:  {out_root}")

    if args.dry_run:
        for d in dates:
            print(f"  {d}")
        print(f"\n{len(dates)} dates would be processed.")
        return

    # Step 1: Run screen for each date
    if not args.skip_screen:
        print(f"\n[1/2] Running full screen pipeline for {len(dates)} dates...")
        ok, fail = 0, 0
        for i, d in enumerate(dates):
            existing = out_root / d / "rankings.csv"
            if existing.exists():
                print(f"  [{i+1}/{len(dates)}] {d}: already exists, skipping")
                ok += 1
                continue
            print(f"  [{i+1}/{len(dates)}] {d}: running...", end="", flush=True)
            success = _run_screen(d, data_dir, ruleset_path, out_root)
            if success:
                ok += 1
                print(" OK")
            else:
                fail += 1
        print(f"  Screen complete: {ok} ok, {fail} failed")
    else:
        print("\n[1/2] Skipping screen runs (--skip-screen)")

    # Step 2: Evaluate forward returns
    eval_dir = out_root / "_eval"
    print("\n[2/2] Evaluating forward returns...")
    summary = _run_eval(
        out_root,
        eval_dir,
        ruleset_path,
        args.date_from,
        args.date_to,
        args.horizons,
        args.top_k,
    )

    if summary:
        bh = summary.get("by_horizon", {})
        print(f"\n  {'Horizon':>8s}  {'IC':>8s}  {'t-stat':>8s}  {'Turnover':>8s}  {'GrossRet':>10s}  {'n':>4s}")
        for h in sorted(bh.keys(), key=int):
            d = bh[h]
            t_stat = d.get("ic_t_stat")
            t_str = f"{t_stat:>8.3f}" if t_stat is not None else "     N/A"
            print(
                f"  {h+'d':>8s}  {d['mean_ic']:>8.4f}  {t_str}  {d['mean_turnover']:>8.4f}  {d['mean_gross_return']:>10.4f}  {d['n_dates']:>4d}"
            )
        print(f"\n  Full results: {eval_dir}/summary.json")
    else:
        print("  Evaluation failed or no data.")

    # Step 3: Weighted-return comparison (sizing-specific metric)
    horizons_list = [int(h) for h in args.horizons.split(",")]
    print("\n[3/3] Weighted vs equal-weight return comparison (sizing signal)...")
    wsummary = _compute_weighted_comparison(
        candidate_root=out_root,
        baseline_root=ref_root,
        data_dir=data_dir,
        dates=dates,
        horizons=horizons_list,
        top_k=args.top_k,
    )

    if wsummary:
        print(
            f"\n  {'Horizon':>8s}  {'Weighted':>10s}  {'EW-Cand':>10s}  {'EW-Base':>10s}  "
            f"{'SizeDelta':>10s}  {'t(size)':>8s}  {'RankDelta':>10s}  {'TotalΔ':>10s}  {'WtSpread':>8s}  {'n':>4s}"
        )
        for h in sorted(wsummary.keys()):
            d = wsummary[h]
            t_str = f"{d['sizing_t_stat']:>8.3f}" if "sizing_t_stat" in d else "     N/A"
            ws_str = f"{d['mean_weight_spread']:>8.2f}" if "mean_weight_spread" in d else "     N/A"
            print(
                f"  {str(h)+'d':>8s}  {d['mean_weighted_ret']:>10.4f}  {d['mean_ew_candidate_ret']:>10.4f}  "
                f"{d['mean_ew_baseline_ret']:>10.4f}  {d['sizing_delta']:>10.4f}  {t_str}  "
                f"{d['rank_delta']:>10.4f}  {d['total_delta']:>10.4f}  {ws_str}  {d['n_dates']:>4.0f}"
            )
        print("\n  SizeDelta = weighted - equal-weight (pure sizing effect)")
        print("  RankDelta = EW-candidate - EW-baseline (pure rank effect)")
        print("  TotalΔ    = weighted-candidate - EW-baseline (combined)")
        print("  WtSpread  = max/min weight ratio (1.0 = equal weight)")

        # Save weighted comparison
        wcomp_path = eval_dir / "weighted_comparison.json"
        eval_dir.mkdir(parents=True, exist_ok=True)
        with open(wcomp_path, "w") as f:
            json.dump({str(h): d for h, d in wsummary.items()}, f, indent=2)
        print(f"\n  Weighted comparison saved: {wcomp_path}")
    else:
        print("  No weighted-return data (need both candidate and baseline rankings).")


if __name__ == "__main__":
    main()
