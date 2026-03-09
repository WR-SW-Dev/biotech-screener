#!/usr/bin/env python3
"""Weekly-cadence live-sim A/B: baseline vs candidate snapshot roots.

Simulates a weekly-rebalanced portfolio using production policy logic
(bucket allocation, caps, regulatory ladder, gap-risk) on historical
snapshots, then computes hedged returns, turnover, and bucket attribution.

Output:
    {out_dir}/RESULTS.csv   — one row per rebalance period per arm
    {out_dir}/SUMMARY.md    — OOS/IS tables, delta analysis, top weeks

Usage:
    python3 scripts/research/live_sim_weekly_ab.py \
      --baseline-snapshot-root data/snapshots_reranked_v1100 \
      --candidate-snapshot-root data/snapshots_reranked_b91_quality_primary \
      --out-dir output/research/live_sim_weekly_ab
"""
from __future__ import annotations

import argparse
import csv
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from live_shadow_portfolio import BUCKET_NAMES, build_positions, load_policy, load_rankings

# ---------------------------------------------------------------------------
# Price loading (lightweight, no pandas)
# ---------------------------------------------------------------------------

PRICE_HISTORY_DEFAULT = PROJECT_ROOT / "production_data" / "price_history.csv"


def load_prices(price_csv: Path) -> Dict[str, Dict[str, float]]:
    """Load price_history.csv -> {ticker: {date: close}}."""
    prices: Dict[str, Dict[str, float]] = {}
    with open(price_csv, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ticker = row.get("ticker", "").strip()
            date = row.get("date", "").strip()
            close_str = row.get("close", "").strip()
            if not ticker or not date or not close_str:
                continue
            try:
                close = float(close_str)
            except ValueError:
                continue
            if close > 0:
                prices.setdefault(ticker, {})[date] = close
    return prices


def _get_price(prices: Dict[str, Dict[str, float]], ticker: str, date: str) -> Optional[float]:
    return prices.get(ticker, {}).get(date)


# ---------------------------------------------------------------------------
# Date discovery
# ---------------------------------------------------------------------------


def discover_dates(snap_root: Path) -> List[str]:
    """Return sorted YYYY-MM-DD date dirs that have rankings.csv."""
    dates = []
    for d in snap_root.iterdir():
        if d.is_dir() and len(d.name) == 10 and (d / "rankings.csv").exists():
            dates.append(d.name)
    dates.sort()
    return dates


def load_date_manifest(path: Path) -> set:
    return {d.strip() for d in path.read_text().splitlines() if d.strip()}


def select_rebalance_dates(dates: List[str], cadence: int = 1) -> List[str]:
    """Pick every Nth date from the sorted list."""
    return dates[::cadence]


# ---------------------------------------------------------------------------
# Portfolio return computation
# ---------------------------------------------------------------------------


def compute_period_return(
    positions: List[Dict[str, Any]],
    prices: Dict[str, Dict[str, float]],
    entry_date: str,
    exit_date: str,
    cost_bps: float = 30.0,
    turnover_frac: float = 0.0,
) -> Dict[str, Any]:
    """Compute portfolio return over a holding period.

    Returns dict with gross_return, net_return, xbi_return, hedged_return,
    and per-bucket attribution.
    """
    total_weight = 0.0
    total_weighted_ret = 0.0
    bucket_weight: Dict[str, float] = {b: 0.0 for b in BUCKET_NAMES}
    bucket_weighted_ret: Dict[str, float] = {b: 0.0 for b in BUCKET_NAMES}
    n_priced = 0
    n_missing = 0

    for pos in positions:
        ticker = pos["ticker"]
        w = pos.get("weight_pct", 0.0)
        bucket = pos.get("bucket", "less_binary")
        p0 = _get_price(prices, ticker, entry_date)
        p1 = _get_price(prices, ticker, exit_date)

        if p0 and p1 and p0 > 0 and w > 0:
            ret = (p1 / p0) - 1.0
            total_weight += w
            total_weighted_ret += w * ret
            bucket_weight[bucket] += w
            bucket_weighted_ret[bucket] += w * ret
            n_priced += 1
        else:
            n_missing += 1

    gross = (total_weighted_ret / total_weight) if total_weight > 0 else 0.0
    cost = turnover_frac * (cost_bps / 10_000)
    net = gross - cost

    # XBI return
    xbi_p0 = _get_price(prices, "XBI", entry_date)
    xbi_p1 = _get_price(prices, "XBI", exit_date)
    xbi_ret = ((xbi_p1 / xbi_p0) - 1.0) if (xbi_p0 and xbi_p1 and xbi_p0 > 0) else None
    hedged = (net - xbi_ret) if xbi_ret is not None else None

    # Per-bucket returns
    bucket_attr = {}
    for b in BUCKET_NAMES:
        bw = bucket_weight[b]
        if bw > 0:
            b_ret = bucket_weighted_ret[b] / bw
            b_hedged = (b_ret - xbi_ret) if xbi_ret is not None else None
        else:
            b_ret = 0.0
            b_hedged = None
        bucket_attr[b] = {
            "weight_pct": round(bw, 4),
            "gross_return": round(b_ret, 6),
            "hedged_return": round(b_hedged, 6) if b_hedged is not None else None,
        }

    return {
        "gross_return": round(gross, 6),
        "net_return": round(net, 6),
        "xbi_return": round(xbi_ret, 6) if xbi_ret is not None else None,
        "hedged_return": round(hedged, 6) if hedged is not None else None,
        "n_priced": n_priced,
        "n_missing": n_missing,
        "bucket_attr": bucket_attr,
    }


def compute_turnover(
    prev_positions: List[Dict[str, Any]],
    curr_positions: List[Dict[str, Any]],
) -> float:
    """Fraction of prior names NOT in current portfolio."""
    if not prev_positions:
        return 0.0
    prev_t = {p["ticker"] for p in prev_positions}
    curr_t = {p["ticker"] for p in curr_positions}
    return 1.0 - len(prev_t & curr_t) / len(prev_t)


# ---------------------------------------------------------------------------
# Global top-K portfolio builder (matches eval methodology)
# ---------------------------------------------------------------------------


def build_global_topk_positions(
    rankings: List[Dict[str, str]],
    top_k: int = 20,
    buffer_ranks: int = 30,
    prev_tickers: Optional[set] = None,
) -> List[Dict[str, Any]]:
    """Select top-K names by actionable_rank, equal-weight.

    Applies rebalance buffer: existing holdings stay unless rank > K + buffer.
    This matches the eval_forward_returns methodology used for A/B verdicts.
    """
    from tools.build_action_lists import classify_action_bucket

    ranked = sorted(rankings, key=lambda r: int(r.get("actionable_rank", 9999)))

    if prev_tickers and buffer_ranks > 0:
        # Buffer logic: keep existing holdings unless rank > K + buffer
        selected = []
        for r in ranked:
            rank = int(r.get("actionable_rank", 9999))
            ticker = r["ticker"]
            if rank <= top_k:
                selected.append(r)
            elif ticker in prev_tickers and rank <= top_k + buffer_ranks:
                selected.append(r)
        # Trim to K if buffer added too many
        selected = selected[: top_k + buffer_ranks]
    else:
        selected = ranked[:top_k]

    n = len(selected)
    if n == 0:
        return []

    equal_wt = 100.0 / n
    positions = []
    for r in selected:
        bucket = classify_action_bucket(r)
        positions.append(
            {
                "ticker": r["ticker"],
                "bucket": bucket,
                "weight_pct": round(equal_wt, 4),
                "actionable_rank": int(r.get("actionable_rank", 9999)),
            }
        )
    return positions


# ---------------------------------------------------------------------------
# Arm simulation
# ---------------------------------------------------------------------------


def run_arm(
    arm_name: str,
    snap_root: Path,
    rebal_dates: List[str],
    prices: Dict[str, Dict[str, float]],
    policy: Dict[str, Any],
    cost_bps: float = 30.0,
    global_top_k: int = 0,
    buffer_ranks: int = 30,
) -> List[Dict[str, Any]]:
    """Simulate weekly-rebalanced portfolio for one arm.

    If global_top_k > 0, uses global top-K equal-weight selection (matching
    eval methodology). Otherwise uses per-bucket policy allocation.

    Returns list of per-period result dicts.
    """
    results = []
    prev_positions: List[Dict[str, Any]] = []

    for i in range(len(rebal_dates) - 1):
        entry_date = rebal_dates[i]
        exit_date = rebal_dates[i + 1]

        snap_dir = snap_root / entry_date
        if not (snap_dir / "rankings.csv").exists():
            continue

        rankings = load_rankings(snap_dir)

        if global_top_k > 0:
            prev_tickers = {p["ticker"] for p in prev_positions} if prev_positions else None
            positions = build_global_topk_positions(
                rankings,
                top_k=global_top_k,
                buffer_ranks=buffer_ranks,
                prev_tickers=prev_tickers,
            )
        else:
            pos_data = build_positions(rankings, policy)
            positions = pos_data["positions"]

        turnover = compute_turnover(prev_positions, positions)
        period = compute_period_return(
            positions,
            prices,
            entry_date,
            exit_date,
            cost_bps=cost_bps,
            turnover_frac=turnover,
        )

        row = {
            "arm": arm_name,
            "entry_date": entry_date,
            "exit_date": exit_date,
            "n_positions": len(positions),
            "turnover": round(turnover, 4),
            "gross_return": period["gross_return"],
            "net_return": period["net_return"],
            "xbi_return": period["xbi_return"],
            "hedged_return": period["hedged_return"],
            "n_priced": period["n_priced"],
            "n_missing": period["n_missing"],
        }
        # Bucket-level hedged returns
        for b in BUCKET_NAMES:
            ba = period["bucket_attr"].get(b, {})
            row[f"{b}_hedged"] = ba.get("hedged_return")
            row[f"{b}_weight"] = ba.get("weight_pct")

        results.append(row)
        prev_positions = positions

        if (i + 1) % 50 == 0:
            print(f"    {arm_name}: {i + 1}/{len(rebal_dates) - 1} periods")

    return results


# ---------------------------------------------------------------------------
# Aggregation + output
# ---------------------------------------------------------------------------


def _safe_mean(vals: List[float]) -> Optional[float]:
    clean = [v for v in vals if v is not None]
    return statistics.mean(clean) if clean else None


def _safe_std(vals: List[float]) -> Optional[float]:
    clean = [v for v in vals if v is not None]
    return statistics.stdev(clean) if len(clean) >= 2 else None


def _cumulative(vals: List[float]) -> Optional[float]:
    """Compound returns: prod(1+r) - 1."""
    clean = [v for v in vals if v is not None]
    if not clean:
        return None
    cum = 1.0
    for v in clean:
        cum *= 1.0 + v
    return cum - 1.0


def _percentile(vals: List[float], pct: float) -> Optional[float]:
    clean = sorted(v for v in vals if v is not None)
    if not clean:
        return None
    idx = int(len(clean) * pct)
    idx = max(0, min(idx, len(clean) - 1))
    return clean[idx]


def _fmt_pct(v: Optional[float], dp: int = 2) -> str:
    if v is None:
        return "—"
    return f"{v * 100:.{dp}f}%"


def _fmt_f(v: Optional[float], dp: int = 4) -> str:
    if v is None:
        return "—"
    return f"{v:.{dp}f}"


def _delta_pp(cand: Optional[float], base: Optional[float]) -> str:
    if cand is None or base is None:
        return "—"
    d = (cand - base) * 100
    sign = "+" if d >= 0 else ""
    return f"{sign}{d:.2f}pp"


def aggregate(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute summary stats from per-period results."""
    hedged = [r["hedged_return"] for r in results]
    net = [r["net_return"] for r in results]
    gross = [r["gross_return"] for r in results]
    xbi = [r["xbi_return"] for r in results]
    turnover = [r["turnover"] for r in results]

    agg = {
        "n_periods": len(results),
        "mean_hedged": _safe_mean(hedged),
        "std_hedged": _safe_std(hedged),
        "cum_hedged": _cumulative(hedged),
        "mean_net": _safe_mean(net),
        "cum_net": _cumulative(net),
        "mean_gross": _safe_mean(gross),
        "cum_gross": _cumulative(gross),
        "mean_xbi": _safe_mean(xbi),
        "cum_xbi": _cumulative(xbi),
        "mean_turnover": _safe_mean(turnover),
        "worst_20pct_hedged": _percentile(hedged, 0.20),
    }
    # Per-bucket hedged
    for b in BUCKET_NAMES:
        bh = [r.get(f"{b}_hedged") for r in results]
        agg[f"{b}_mean_hedged"] = _safe_mean(bh)

    return agg


def write_results_csv(results: List[Dict[str, Any]], out_path: Path) -> None:
    if not results:
        return
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(results[0].keys())
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(results)


def write_summary(
    base_results: List[Dict[str, Any]],
    cand_results: List[Dict[str, Any]],
    base_agg: Dict[str, Any],
    cand_agg: Dict[str, Any],
    window: str,
    out_path: Path,
    *,
    base_name: str = "baseline",
    cand_name: str = "candidate",
) -> List[str]:
    """Build summary markdown lines for one window (OOS or IS)."""
    lines = [
        f"### {window} ({base_agg['n_periods']} periods)",
        "",
        f"| Metric | {base_name} | {cand_name} | Δ |",
        "|--------|----------|-----------|---|",
        f"| Mean weekly hedged | {_fmt_pct(base_agg['mean_hedged'])} "
        f"| {_fmt_pct(cand_agg['mean_hedged'])} "
        f"| {_delta_pp(cand_agg['mean_hedged'], base_agg['mean_hedged'])} |",
        f"| Cumulative hedged | {_fmt_pct(base_agg['cum_hedged'])} "
        f"| {_fmt_pct(cand_agg['cum_hedged'])} "
        f"| {_delta_pp(cand_agg['cum_hedged'], base_agg['cum_hedged'])} |",
        f"| Mean weekly net | {_fmt_pct(base_agg['mean_net'])} "
        f"| {_fmt_pct(cand_agg['mean_net'])} "
        f"| {_delta_pp(cand_agg['mean_net'], base_agg['mean_net'])} |",
        f"| Cumulative net | {_fmt_pct(base_agg['cum_net'])} "
        f"| {_fmt_pct(cand_agg['cum_net'])} "
        f"| {_delta_pp(cand_agg['cum_net'], base_agg['cum_net'])} |",
        f"| Std weekly hedged | {_fmt_pct(base_agg['std_hedged'])} " f"| {_fmt_pct(cand_agg['std_hedged'])} | |",
        f"| Mean turnover | {_fmt_pct(base_agg['mean_turnover'])} "
        f"| {_fmt_pct(cand_agg['mean_turnover'])} "
        f"| {_delta_pp(cand_agg['mean_turnover'], base_agg['mean_turnover'])} |",
        f"| Worst-20% hedged | {_fmt_pct(base_agg['worst_20pct_hedged'])} "
        f"| {_fmt_pct(cand_agg['worst_20pct_hedged'])} "
        f"| {_delta_pp(cand_agg['worst_20pct_hedged'], base_agg['worst_20pct_hedged'])} |",
        "",
        "#### Bucket Attribution (mean weekly hedged)",
        "",
        f"| Bucket | {base_name} | {cand_name} | Δ |",
        "|--------|----------|-----------|---|",
    ]
    for b in BUCKET_NAMES:
        bk = f"{b}_mean_hedged"
        lines.append(
            f"| {b} | {_fmt_pct(base_agg.get(bk))} "
            f"| {_fmt_pct(cand_agg.get(bk))} "
            f"| {_delta_pp(cand_agg.get(bk), base_agg.get(bk))} |"
        )

    # Top/bottom weeks driving the delta
    if base_results and cand_results:
        deltas = []
        for br, cr in zip(base_results, cand_results):
            bh = br.get("hedged_return")
            ch = cr.get("hedged_return")
            if bh is not None and ch is not None:
                deltas.append(
                    {
                        "entry_date": br["entry_date"],
                        "exit_date": br["exit_date"],
                        "base_hedged": bh,
                        "cand_hedged": ch,
                        "delta": ch - bh,
                    }
                )
        deltas.sort(key=lambda d: -d["delta"])

        lines.extend(["", "#### Top 10 Weeks Driving Delta", ""])
        lines.append("| Entry | Exit | Base Hedged | Cand Hedged | Δ |")
        lines.append("|-------|------|-------------|-------------|---|")
        for d in deltas[:10]:
            lines.append(
                f"| {d['entry_date']} | {d['exit_date']} "
                f"| {_fmt_pct(d['base_hedged'])} "
                f"| {_fmt_pct(d['cand_hedged'])} "
                f"| {_delta_pp(d['cand_hedged'], d['base_hedged'])} |"
            )

        lines.extend(["", "#### Bottom 10 Weeks (Hurt Delta)", ""])
        lines.append("| Entry | Exit | Base Hedged | Cand Hedged | Δ |")
        lines.append("|-------|------|-------------|-------------|---|")
        for d in deltas[-10:]:
            lines.append(
                f"| {d['entry_date']} | {d['exit_date']} "
                f"| {_fmt_pct(d['base_hedged'])} "
                f"| {_fmt_pct(d['cand_hedged'])} "
                f"| {_delta_pp(d['cand_hedged'], d['base_hedged'])} |"
            )

    lines.append("")
    return lines


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Weekly-cadence live-sim A/B evaluation")
    parser.add_argument(
        "--baseline-snapshot-root",
        type=Path,
        required=True,
        help="Snapshot root for baseline arm",
    )
    parser.add_argument(
        "--candidate-snapshot-root",
        type=Path,
        required=True,
        help="Snapshot root for candidate arm",
    )
    parser.add_argument(
        "--policy",
        type=Path,
        default=PROJECT_ROOT / "production_data" / "portfolio_policy.json",
        help="Portfolio policy JSON",
    )
    parser.add_argument(
        "--price-csv",
        type=Path,
        default=PRICE_HISTORY_DEFAULT,
        help="Price history CSV",
    )
    parser.add_argument(
        "--date-manifest",
        type=Path,
        default=None,
        help="Audited dates file (one YYYY-MM-DD per line)",
    )
    parser.add_argument(
        "--date-from",
        type=str,
        default=None,
        help="Start date (YYYY-MM-DD), inclusive",
    )
    parser.add_argument(
        "--date-to",
        type=str,
        default=None,
        help="End date (YYYY-MM-DD), inclusive",
    )
    parser.add_argument(
        "--rebal-every",
        type=int,
        default=1,
        help="Rebalance every N snapshot dates (default: 1 = every date)",
    )
    parser.add_argument(
        "--cost-bps",
        type=float,
        default=30.0,
        help="Transaction cost in basis points (default: 30)",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=PROJECT_ROOT / "output" / "research" / "live_sim_weekly_ab",
        help="Output directory",
    )
    parser.add_argument(
        "--global-top-k",
        type=int,
        default=0,
        help="Use global top-K equal-weight selection (eval methodology). "
        "0 = use per-bucket policy allocation (default).",
    )
    parser.add_argument(
        "--buffer-ranks",
        type=int,
        default=30,
        help="Rebalance buffer ranks for global-top-k mode (default: 30)",
    )
    parser.add_argument(
        "--baseline-name",
        type=str,
        default="baseline",
    )
    parser.add_argument(
        "--candidate-name",
        type=str,
        default="candidate",
    )
    args = parser.parse_args()

    # Discover dates common to both arms
    base_dates = set(discover_dates(args.baseline_snapshot_root))
    cand_dates = set(discover_dates(args.candidate_snapshot_root))
    common = sorted(base_dates & cand_dates)

    # Apply date filters
    if args.date_manifest:
        allowed = load_date_manifest(args.date_manifest)
        common = [d for d in common if d in allowed]

    if args.date_from:
        common = [d for d in common if d >= args.date_from]
    if args.date_to:
        common = [d for d in common if d <= args.date_to]

    rebal_dates = select_rebalance_dates(common, args.rebal_every)

    print(f"Common dates: {len(common)}, rebalance dates: {len(rebal_dates)}")
    if len(rebal_dates) < 2:
        print("ERROR: Need at least 2 rebalance dates for a simulation.")
        sys.exit(1)

    # Load prices once
    print("Loading prices...")
    prices = load_prices(args.price_csv)
    print(f"  {len(prices)} tickers loaded")

    # Load policy
    policy = load_policy(args.policy)

    mode_label = (
        f"global top-K={args.global_top_k}, buffer={args.buffer_ranks}"
        if args.global_top_k > 0
        else "per-bucket policy"
    )
    print(f"Mode: {mode_label}")

    # Run both arms
    print(f"\nRunning {args.baseline_name}...")
    base_results = run_arm(
        args.baseline_name,
        args.baseline_snapshot_root,
        rebal_dates,
        prices,
        policy,
        args.cost_bps,
        global_top_k=args.global_top_k,
        buffer_ranks=args.buffer_ranks,
    )
    print(f"  {len(base_results)} periods")

    print(f"\nRunning {args.candidate_name}...")
    cand_results = run_arm(
        args.candidate_name,
        args.candidate_snapshot_root,
        rebal_dates,
        prices,
        policy,
        args.cost_bps,
        global_top_k=args.global_top_k,
        buffer_ranks=args.buffer_ranks,
    )
    print(f"  {len(cand_results)} periods")

    # Write RESULTS.csv
    all_results = base_results + cand_results
    csv_path = args.out_dir / "RESULTS.csv"
    write_results_csv(all_results, csv_path)
    print(f"\nCSV: {csv_path}")

    # Aggregate
    base_agg = aggregate(base_results)
    cand_agg = aggregate(cand_results)

    # Build SUMMARY.md
    md_lines = [
        "# Weekly Live-Sim A/B",
        "",
        f"**Baseline**: `{args.baseline_snapshot_root.name}`",
        f"**Candidate**: `{args.candidate_snapshot_root.name}`",
        f"**Policy**: `{args.policy.name}`",
        f"**Mode**: {mode_label}",
        f"**Cost**: {args.cost_bps:.0f}bps",
        f"**Rebalance cadence**: every {args.rebal_every} snapshot date(s)",
        f"**Date range**: {rebal_dates[0]} → {rebal_dates[-1]}",
        "",
    ]

    # If we have both OOS and IS manifests, run both; otherwise just one window
    window_label = "Full"
    if args.date_manifest:
        window_label = args.date_manifest.stem
    elif args.date_from or args.date_to:
        window_label = f"{args.date_from or '...'} → {args.date_to or '...'}"

    md_lines.extend(
        write_summary(
            base_results,
            cand_results,
            base_agg,
            cand_agg,
            window_label,
            args.out_dir,
            base_name=args.baseline_name,
            cand_name=args.candidate_name,
        )
    )

    # Verdict
    tail_delta = None
    if base_agg["worst_20pct_hedged"] is not None and cand_agg["worst_20pct_hedged"] is not None:
        tail_delta = cand_agg["worst_20pct_hedged"] - base_agg["worst_20pct_hedged"]

    md_lines.extend(
        [
            "## Verdict",
            "",
            f"- Mean weekly hedged Δ: {_delta_pp(cand_agg['mean_hedged'], base_agg['mean_hedged'])}",
            f"- Cumulative hedged Δ: {_delta_pp(cand_agg['cum_hedged'], base_agg['cum_hedged'])}",
            f"- Worst-20% tail Δ: {_delta_pp(cand_agg['worst_20pct_hedged'], base_agg['worst_20pct_hedged'])} "
            f"({'PASS' if tail_delta is not None and tail_delta >= -0.001 else 'FAIL'} guardrail ≥ -0.10pp)",
            "",
            f"*{base_agg['n_periods']} periods, {len(rebal_dates)} rebalance dates*",
            "",
        ]
    )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    summary_path = args.out_dir / "SUMMARY.md"
    summary_path.write_text("\n".join(md_lines))
    print(f"Summary: {summary_path}")

    # Print key metrics
    print(f"\n{'='*60}")
    print(
        f"Mean weekly hedged:  base={_fmt_pct(base_agg['mean_hedged'])}  "
        f"cand={_fmt_pct(cand_agg['mean_hedged'])}  "
        f"Δ={_delta_pp(cand_agg['mean_hedged'], base_agg['mean_hedged'])}"
    )
    print(
        f"Cumulative hedged:   base={_fmt_pct(base_agg['cum_hedged'])}  "
        f"cand={_fmt_pct(cand_agg['cum_hedged'])}  "
        f"Δ={_delta_pp(cand_agg['cum_hedged'], base_agg['cum_hedged'])}"
    )
    print(
        f"Mean turnover:       base={_fmt_pct(base_agg['mean_turnover'])}  "
        f"cand={_fmt_pct(cand_agg['mean_turnover'])}"
    )
    print(
        f"Worst-20% tail:      base={_fmt_pct(base_agg['worst_20pct_hedged'])}  "
        f"cand={_fmt_pct(cand_agg['worst_20pct_hedged'])}"
    )
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
