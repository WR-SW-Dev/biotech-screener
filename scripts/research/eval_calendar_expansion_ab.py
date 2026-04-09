#!/usr/bin/env python3
"""A/B evaluation: old regulatory calendar vs expanded calendar.

Uses the same snapshot root + policy for both arms. The only difference is
which PDUFA calendar enriches the rankings before portfolio construction.

  A = old calendar (11 entries, pre-expansion)
  B = new calendar (20 entries, post-expansion)

Simulates weekly-rebalanced portfolio, computes hedged returns, turnover,
and bucket attribution. Outputs SUMMARY.md with pass/fail verdict.

Usage:
    python3 scripts/research/eval_calendar_expansion_ab.py \
      --snapshot-root data/snapshots_reranked_v1100 \
      --old-calendar /tmp/pdufa_dates_old.json \
      --new-calendar production_data/pdufa_dates.json \
      --out-dir output/research/reg_calendar_policy_ab
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from datetime import date as _date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from live_shadow_portfolio import BUCKET_NAMES, build_positions, load_policy, load_rankings

# ---------------------------------------------------------------------------
# Calendar enrichment (adapted from eval_regulatory_policy_ab.py)
# ---------------------------------------------------------------------------


def load_calendar(path: Path) -> List[Dict[str, str]]:
    """Load PDUFA calendar JSON."""
    if not path.is_file():
        return []
    with open(path) as f:
        return json.load(f)


def enrich_with_calendar(
    rankings: List[Dict[str, str]],
    as_of_date: str,
    calendar: List[Dict[str, str]],
) -> Tuple[List[Dict[str, str]], int]:
    """Enrich ranking rows with regulatory fields from a PDUFA calendar.

    For each ticker, find nearest PDUFA entry within 1-180 days forward.
    Applies PIT filter: only entries with as_of_disclosed_at <= as_of_date.
    Returns (enriched_rankings, n_flagged).
    """
    try:
        ref = _date.fromisoformat(as_of_date)
    except ValueError:
        return rankings, 0

    # Build ticker → nearest (days, event_type) map
    pdufa_map: Dict[str, Tuple[int, str]] = {}
    for entry in calendar:
        ticker = entry.get("ticker", "").upper()
        pdufa_date_str = entry.get("pdufa_date", "")
        if not ticker or not pdufa_date_str:
            continue

        # PIT filter: skip if disclosed after as_of_date
        disclosed = entry.get("as_of_disclosed_at", "")
        if disclosed and disclosed > as_of_date:
            continue

        try:
            pd = _date.fromisoformat(pdufa_date_str)
        except ValueError:
            continue
        days = (pd - ref).days
        if 1 <= days <= 180:
            event_type = entry.get("event_type", "PDUFA")
            if ticker not in pdufa_map or days < pdufa_map[ticker][0]:
                pdufa_map[ticker] = (days, event_type)

    n_flagged = 0
    for row in rankings:
        ticker = row.get("ticker", "").upper()
        if ticker in pdufa_map:
            days, evt = pdufa_map[ticker]
            row["has_regulatory_upcoming_180d"] = "1"
            row["regulatory_days"] = str(days)
            row["regulatory_event_type"] = evt
            bqs = row.get("binary_quality_score", "")
            row["regulatory_quality"] = bqs if bqs else "0.50"
            n_flagged += 1
        else:
            row["has_regulatory_upcoming_180d"] = "0"
            row["regulatory_days"] = ""
            row["regulatory_event_type"] = ""
            row["regulatory_quality"] = "0"
    return rankings, n_flagged


# ---------------------------------------------------------------------------
# Price loading
# ---------------------------------------------------------------------------

PRICE_HISTORY_DEFAULT = PROJECT_ROOT / "production_data" / "price_history.csv"


def load_prices(price_csv: Path) -> Dict[str, Dict[str, float]]:
    """Load price_history.csv -> {ticker: {date: close}}."""
    prices: Dict[str, Dict[str, float]] = {}
    with open(price_csv, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ticker = row.get("ticker", "").strip()
            dt = row.get("date", "").strip()
            close_str = row.get("close", "").strip()
            if not ticker or not dt or not close_str:
                continue
            try:
                close = float(close_str)
            except ValueError:
                continue
            if close > 0:
                prices.setdefault(ticker, {})[dt] = close
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
    """Compute portfolio return over a holding period."""
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

    xbi_p0 = _get_price(prices, "XBI", entry_date)
    xbi_p1 = _get_price(prices, "XBI", exit_date)
    xbi_ret = ((xbi_p1 / xbi_p0) - 1.0) if (xbi_p0 and xbi_p1 and xbi_p0 > 0) else None
    hedged = (net - xbi_ret) if xbi_ret is not None else None

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
    if not prev_positions:
        return 0.0
    prev_t = {p["ticker"] for p in prev_positions}
    curr_t = {p["ticker"] for p in curr_positions}
    return 1.0 - len(prev_t & curr_t) / len(prev_t)


# ---------------------------------------------------------------------------
# Arm simulation with on-the-fly enrichment
# ---------------------------------------------------------------------------


def run_arm(
    arm_name: str,
    snap_root: Path,
    rebal_dates: List[str],
    prices: Dict[str, Dict[str, float]],
    policy: Dict[str, Any],
    calendar: List[Dict[str, str]],
    cost_bps: float = 30.0,
) -> Tuple[List[Dict[str, Any]], Dict[str, List[int]]]:
    """Simulate weekly-rebalanced portfolio for one arm.

    Enriches rankings with the given calendar before building positions.
    Returns (per-period results, {date: [n_eligible, n_flagged]}).
    """
    results = []
    prev_positions: List[Dict[str, Any]] = []
    coverage: Dict[str, List[int]] = {}

    for i in range(len(rebal_dates) - 1):
        entry_date = rebal_dates[i]
        exit_date = rebal_dates[i + 1]

        snap_dir = snap_root / entry_date
        if not (snap_dir / "rankings.csv").exists():
            continue

        # Load fresh rankings and enrich with this arm's calendar
        rankings = load_rankings(snap_dir)
        rankings, n_flagged = enrich_with_calendar(rankings, entry_date, calendar)
        coverage[entry_date] = [len(rankings), n_flagged]

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
            "n_regulatory": n_flagged,
            "turnover": round(turnover, 4),
            "gross_return": period["gross_return"],
            "net_return": period["net_return"],
            "xbi_return": period["xbi_return"],
            "hedged_return": period["hedged_return"],
            "n_priced": period["n_priced"],
            "n_missing": period["n_missing"],
        }
        for b in BUCKET_NAMES:
            ba = period["bucket_attr"].get(b, {})
            row[f"{b}_hedged"] = ba.get("hedged_return")
            row[f"{b}_weight"] = ba.get("weight_pct")

        results.append(row)
        prev_positions = positions

        if (i + 1) % 50 == 0:
            print(f"    {arm_name}: {i + 1}/{len(rebal_dates) - 1} periods")

    return results, coverage


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def _safe_mean(vals: List[float]) -> Optional[float]:
    clean = [v for v in vals if v is not None]
    return statistics.mean(clean) if clean else None


def _safe_std(vals: List[float]) -> Optional[float]:
    clean = [v for v in vals if v is not None]
    return statistics.stdev(clean) if len(clean) >= 2 else None


def _cumulative(vals: List[float]) -> Optional[float]:
    clean = [v for v in vals if v is not None]
    if not clean:
        return None
    cum = 1.0
    for v in clean:
        cum *= 1.0 + v
    return cum - 1.0


def _fmt_pct(v: Optional[float], dp: int = 2) -> str:
    if v is None:
        return "—"
    return f"{v * 100:.{dp}f}%"


def _delta_pp(cand: Optional[float], base: Optional[float]) -> str:
    if cand is None or base is None:
        return "—"
    d = (cand - base) * 100
    sign = "+" if d >= 0 else ""
    return f"{sign}{d:.2f}pp"


def aggregate(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    hedged = [r["hedged_return"] for r in results]
    net = [r["net_return"] for r in results]
    turnover = [r["turnover"] for r in results]
    n_reg = [r["n_regulatory"] for r in results]

    agg = {
        "n_periods": len(results),
        "mean_hedged": _safe_mean(hedged),
        "std_hedged": _safe_std(hedged),
        "cum_hedged": _cumulative(hedged),
        "mean_net": _safe_mean(net),
        "cum_net": _cumulative(net),
        "mean_turnover": _safe_mean(turnover),
        "mean_n_regulatory": _safe_mean(n_reg),
    }
    for b in BUCKET_NAMES:
        bh = [r.get(f"{b}_hedged") for r in results]
        agg[f"{b}_mean_hedged"] = _safe_mean(bh)
    return agg


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


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
    base_coverage: Dict[str, List[int]],
    cand_coverage: Dict[str, List[int]],
    old_cal_n: int,
    new_cal_n: int,
    out_dir: Path,
    snapshot_root: Path,
    date_range: Tuple[str, str],
) -> Path:
    """Write SUMMARY.md with verdict."""
    lines = [
        "# Regulatory Calendar Expansion A/B",
        "",
        f"**Snapshot root**: `{snapshot_root.name}`",
        f"**Old calendar**: {old_cal_n} entries",
        f"**New calendar**: {new_cal_n} entries",
        f"**Date range**: {date_range[0]} to {date_range[1]}",
        f"**Periods**: {base_agg['n_periods']}",
        "",
        "## Regulatory Coverage",
        "",
        "| Metric | Old Calendar | New Calendar |",
        "|--------|-------------|-------------|",
        f"| Mean tickers flagged | {base_agg.get('mean_n_regulatory', 0):.1f} "
        f"| {cand_agg.get('mean_n_regulatory', 0):.1f} |",
    ]

    # Count dates where new calendar adds flags old didn't
    n_dates_with_new_flags = 0
    for d in sorted(cand_coverage.keys()):
        old_n = base_coverage.get(d, [0, 0])[1]
        new_n = cand_coverage.get(d, [0, 0])[1]
        if new_n > old_n:
            n_dates_with_new_flags += 1
    lines.append(f"| Dates with additional flags | — | {n_dates_with_new_flags} |")
    lines.append("")

    # Main results table
    lines.extend(
        [
            "## Returns (weekly rebalance, 30bps cost)",
            "",
            "| Metric | Old Calendar | New Calendar | Delta |",
            "|--------|-------------|-------------|-------|",
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
            "",
        ]
    )

    # Bucket attribution
    lines.extend(
        [
            "## Bucket Attribution (mean weekly hedged)",
            "",
            "| Bucket | Old Calendar | New Calendar | Delta |",
            "|--------|-------------|-------------|-------|",
        ]
    )
    for b in BUCKET_NAMES:
        bk = f"{b}_mean_hedged"
        lines.append(
            f"| {b} | {_fmt_pct(base_agg.get(bk))} "
            f"| {_fmt_pct(cand_agg.get(bk))} "
            f"| {_delta_pp(cand_agg.get(bk), base_agg.get(bk))} |"
        )
    lines.append("")

    # Top/bottom weeks
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
                        "base_n_reg": br.get("n_regulatory", 0),
                        "cand_n_reg": cr.get("n_regulatory", 0),
                    }
                )
        deltas.sort(key=lambda d: -d["delta"])

        # Only show weeks where delta != 0
        nonzero = [d for d in deltas if abs(d["delta"]) > 1e-8]

        if nonzero:
            lines.extend(
                [
                    "## Top 5 Weeks Driving Positive Delta",
                    "",
                    "| Entry | Exit | Old Hedged | New Hedged | Delta | Old Reg | New Reg |",
                    "|-------|------|------------|------------|-------|---------|---------|",
                ]
            )
            for d in nonzero[:5]:
                lines.append(
                    f"| {d['entry_date']} | {d['exit_date']} "
                    f"| {_fmt_pct(d['base_hedged'])} "
                    f"| {_fmt_pct(d['cand_hedged'])} "
                    f"| {_delta_pp(d['cand_hedged'], d['base_hedged'])} "
                    f"| {d['base_n_reg']} | {d['cand_n_reg']} |"
                )
            lines.append("")

            lines.extend(
                [
                    "## Bottom 5 Weeks (Hurt Delta)",
                    "",
                    "| Entry | Exit | Old Hedged | New Hedged | Delta | Old Reg | New Reg |",
                    "|-------|------|------------|------------|-------|---------|---------|",
                ]
            )
            for d in nonzero[-5:]:
                lines.append(
                    f"| {d['entry_date']} | {d['exit_date']} "
                    f"| {_fmt_pct(d['base_hedged'])} "
                    f"| {_fmt_pct(d['cand_hedged'])} "
                    f"| {_delta_pp(d['cand_hedged'], d['base_hedged'])} "
                    f"| {d['base_n_reg']} | {d['cand_n_reg']} |"
                )
            lines.append("")

    # Verdict
    cum_delta = None
    if base_agg["cum_hedged"] is not None and cand_agg["cum_hedged"] is not None:
        cum_delta = cand_agg["cum_hedged"] - base_agg["cum_hedged"]

    turnover_delta = None
    if base_agg["mean_turnover"] is not None and cand_agg["mean_turnover"] is not None:
        turnover_delta = cand_agg["mean_turnover"] - base_agg["mean_turnover"]

    mean_delta = None
    if base_agg["mean_hedged"] is not None and cand_agg["mean_hedged"] is not None:
        mean_delta = cand_agg["mean_hedged"] - base_agg["mean_hedged"]

    lines.extend(
        [
            "## Verdict",
            "",
            "### Pass Bars",
            "",
            "| Criterion | Threshold | Actual | Status |",
            "|-----------|-----------|--------|--------|",
        ]
    )

    # Primary: cum hedged delta >= +0.20pp (= 0.0020)
    primary_pass = cum_delta is not None and cum_delta >= 0.0020
    lines.append(
        "| Cumulative hedged delta | >= +0.20pp "
        f"| {_delta_pp(cand_agg['cum_hedged'], base_agg['cum_hedged'])} "
        f"| {'PASS' if primary_pass else 'FAIL'} |"
    )

    # Guardrail: mean hedged delta >= -0.05pp (= -0.0005)
    guardrail_pass = mean_delta is not None and mean_delta >= -0.0005
    lines.append(
        "| Mean weekly hedged delta | >= -0.05pp "
        f"| {_delta_pp(cand_agg['mean_hedged'], base_agg['mean_hedged'])} "
        f"| {'PASS' if guardrail_pass else 'FAIL'} |"
    )

    # Turnover: delta <= +0.25pp (= 0.0025)
    turnover_pass = turnover_delta is not None and turnover_delta <= 0.0025
    lines.append(
        "| Turnover increase | <= +0.25pp "
        f"| {_delta_pp(cand_agg['mean_turnover'], base_agg['mean_turnover'])} "
        f"| {'PASS' if turnover_pass else 'FAIL'} |"
    )

    lines.append("")

    if primary_pass and guardrail_pass and turnover_pass:
        verdict = "PASS"
        lines.append(
            "**PASS**: Expanded calendar meets all pass bars. "
            "The additional regulatory entries improve hedged returns "
            "without excessive turnover."
        )
    elif guardrail_pass and turnover_pass:
        verdict = "NEUTRAL"
        lines.append(
            "**NEUTRAL**: Expanded calendar does not hurt (guardrail + turnover OK) "
            "but cumulative hedged delta is below +0.20pp threshold. "
            "Safe to keep but impact is limited."
        )
    else:
        verdict = "FAIL"
        failed = []
        if not guardrail_pass:
            failed.append("mean hedged guardrail")
        if not turnover_pass:
            failed.append("turnover")
        lines.append(
            f"**FAIL**: Expanded calendar fails {', '.join(failed)}. " "Investigate which entries are causing harm."
        )

    lines.extend(["", "---", "*Generated by eval_calendar_expansion_ab.py*"])

    out_dir.mkdir(parents=True, exist_ok=True)
    summary_path = out_dir / "SUMMARY.md"
    summary_path.write_text("\n".join(lines))

    # Also write JSON
    json_data = {
        "schema": "calendar_expansion_ab.v1",
        "verdict": verdict,
        "old_calendar_n": old_cal_n,
        "new_calendar_n": new_cal_n,
        "n_periods": base_agg["n_periods"],
        "date_range": list(date_range),
        "base_agg": base_agg,
        "cand_agg": cand_agg,
        "primary_pass": primary_pass,
        "guardrail_pass": guardrail_pass,
        "turnover_pass": turnover_pass,
    }
    json_path = out_dir / "SUMMARY.json"
    with open(json_path, "w") as f:
        json.dump(json_data, f, indent=2, default=str)

    return summary_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="A/B: old vs expanded regulatory calendar")
    parser.add_argument(
        "--snapshot-root",
        type=Path,
        required=True,
        help="Snapshot root with rankings.csv per date",
    )
    parser.add_argument(
        "--old-calendar",
        type=Path,
        required=True,
        help="Old PDUFA calendar JSON (pre-expansion)",
    )
    parser.add_argument(
        "--new-calendar",
        type=Path,
        default=PROJECT_ROOT / "production_data" / "pdufa_dates.json",
        help="New PDUFA calendar JSON (post-expansion)",
    )
    parser.add_argument(
        "--policy",
        type=Path,
        default=PROJECT_ROOT / "production_data" / "portfolio_policy.json",
    )
    parser.add_argument(
        "--price-csv",
        type=Path,
        default=PRICE_HISTORY_DEFAULT,
    )
    parser.add_argument("--date-from", type=str, default=None)
    parser.add_argument("--date-to", type=str, default=None)
    parser.add_argument(
        "--rebal-every",
        type=int,
        default=1,
        help="Rebalance every N snapshot dates (default: 1)",
    )
    parser.add_argument("--cost-bps", type=float, default=30.0)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=PROJECT_ROOT / "output" / "research" / "reg_calendar_policy_ab",
    )
    args = parser.parse_args()

    # Load calendars
    old_cal = load_calendar(args.old_calendar)
    new_cal = load_calendar(args.new_calendar)
    print(f"Old calendar: {len(old_cal)} entries")
    print(f"New calendar: {len(new_cal)} entries")

    # Discover dates
    all_dates = discover_dates(args.snapshot_root)
    if args.date_from:
        all_dates = [d for d in all_dates if d >= args.date_from]
    if args.date_to:
        all_dates = [d for d in all_dates if d <= args.date_to]

    rebal_dates = all_dates[:: args.rebal_every]
    print(f"Snapshot dates: {len(all_dates)}, rebalance dates: {len(rebal_dates)}")

    if len(rebal_dates) < 2:
        print("ERROR: Need at least 2 rebalance dates.")
        sys.exit(1)

    # Load prices
    print("Loading prices...")
    prices = load_prices(args.price_csv)
    print(f"  {len(prices)} tickers loaded")

    # Load policy
    policy = load_policy(args.policy)

    # Run both arms
    print("\nRunning old calendar arm...")
    base_results, base_coverage = run_arm(
        "old_calendar",
        args.snapshot_root,
        rebal_dates,
        prices,
        policy,
        old_cal,
        args.cost_bps,
    )
    print(f"  {len(base_results)} periods")

    print("\nRunning new calendar arm...")
    cand_results, cand_coverage = run_arm(
        "new_calendar",
        args.snapshot_root,
        rebal_dates,
        prices,
        policy,
        new_cal,
        args.cost_bps,
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

    # Write SUMMARY.md
    date_range = (rebal_dates[0], rebal_dates[-1])
    summary_path = write_summary(
        base_results,
        cand_results,
        base_agg,
        cand_agg,
        base_coverage,
        cand_coverage,
        len(old_cal),
        len(new_cal),
        args.out_dir,
        args.snapshot_root,
        date_range,
    )
    print(f"Summary: {summary_path}")

    # Print key metrics
    print(f"\n{'=' * 60}")
    print(
        f"Mean weekly hedged:  old={_fmt_pct(base_agg['mean_hedged'])}  "
        f"new={_fmt_pct(cand_agg['mean_hedged'])}  "
        f"delta={_delta_pp(cand_agg['mean_hedged'], base_agg['mean_hedged'])}"
    )
    print(
        f"Cumulative hedged:   old={_fmt_pct(base_agg['cum_hedged'])}  "
        f"new={_fmt_pct(cand_agg['cum_hedged'])}  "
        f"delta={_delta_pp(cand_agg['cum_hedged'], base_agg['cum_hedged'])}"
    )
    print(
        f"Mean turnover:       old={_fmt_pct(base_agg['mean_turnover'])}  "
        f"new={_fmt_pct(cand_agg['mean_turnover'])}  "
        f"delta={_delta_pp(cand_agg['mean_turnover'], base_agg['mean_turnover'])}"
    )
    print(
        f"Mean reg flagged:    old={base_agg.get('mean_n_regulatory', 0):.1f}  "
        f"new={cand_agg.get('mean_n_regulatory', 0):.1f}"
    )
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
