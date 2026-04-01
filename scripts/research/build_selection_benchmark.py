"""Selection-only benchmark: equal-weight top-N by DEM rank.

Answers the key question: is the selection layer generating alpha
before construction drag?

Runs alongside the constructed shadow portfolio using the same price
data and date range, but with simple equal-weight allocation to the
top-N DEM-ranked names, rebalanced at each snapshot.

Usage:
    python scripts/research/build_selection_benchmark.py
    python scripts/research/build_selection_benchmark.py --top-n 30
    python scripts/research/build_selection_benchmark.py --start-date 2026-03-01
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

SNAPSHOT_DIR = REPO_ROOT / "data" / "snapshots"
PRICE_PATH = REPO_ROOT / "production_data" / "price_history.csv"
SHADOW_PERF_PATH = REPO_ROOT / "artifacts" / "live_shadow" / "performance.csv"
OUTPUT_DIR = REPO_ROOT / "output" / "benchmarks"

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("selection_benchmark")


def load_price_map(price_path: Path) -> dict[str, dict[str, float]]:
    """Load price_history.csv → {date: {ticker: close}}."""
    prices: dict[str, dict[str, float]] = defaultdict(dict)
    with open(price_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ticker = row.get("ticker", "").strip()
            date_str = row.get("date", "").strip()
            close = row.get("close", "").strip()
            if ticker and date_str and close:
                try:
                    prices[date_str][ticker] = float(close)
                except ValueError:
                    pass
    return dict(prices)


def load_rankings(snapshot_date: str) -> list[dict]:
    """Load rankings.csv for a given snapshot date, sorted by actionable_rank."""
    rpath = SNAPSHOT_DIR / snapshot_date / "rankings.csv"
    if not rpath.exists():
        return []
    with open(rpath, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    ranked = []
    for r in rows:
        ar = r.get("actionable_rank", "").strip()
        if ar:
            try:
                r["_rank"] = int(ar)
                ranked.append(r)
            except ValueError:
                pass
    ranked.sort(key=lambda r: r["_rank"])
    return ranked


def load_shadow_performance() -> list[dict]:
    """Load constructed shadow performance.csv."""
    if not SHADOW_PERF_PATH.exists():
        return []
    rows = []
    with open(SHADOW_PERF_PATH, encoding="utf-8") as f:
        for line in csv.reader(f):
            if len(line) >= 10 and line[0] == "live_shadow_perf.v1":
                try:
                    rows.append(
                        {
                            "date": line[1],
                            "prior_date": line[2],
                            "pnl_pct": float(line[4]) if line[4] else 0,
                            "xbi_pct": float(line[5]) if line[5] else 0,
                            "excess": float(line[6]) if line[6] else 0,
                            "n_held": int(line[7]) if line[7] else 0,
                            "turnover": float(line[8]) if line[8] else 0,
                        }
                    )
                except (ValueError, IndexError):
                    pass
    return rows


def get_snapshot_dates(start_date: str = "2000-01-01") -> list[str]:
    """Get available snapshot dates, sorted ascending."""
    if not SNAPSHOT_DIR.exists():
        return []
    dates = sorted(
        d.name for d in SNAPSHOT_DIR.iterdir() if d.is_dir() and d.name >= start_date and (d / "rankings.csv").exists()
    )
    return dates


def build_ew_positions(rankings: list[dict], top_n: int) -> list[dict]:
    """Build equal-weight top-N positions."""
    selected = rankings[:top_n]
    if not selected:
        return []
    weight = 100.0 / len(selected)
    return [
        {
            "ticker": r.get("ticker", "").upper(),
            "rank": r["_rank"],
            "weight_pct": weight,
            "tier": r.get("tier_any", ""),
            "catalyst_days": r.get("catalyst_days", ""),
            "archetype": r.get("archetype", ""),
        }
        for r in selected
    ]


def compute_ew_return(
    prior_positions: list[dict],
    prior_prices: dict[str, float],
    current_prices: dict[str, float],
) -> dict:
    """Compute equal-weight portfolio return between two dates."""
    if not prior_positions:
        return {"pnl_pct": 0.0, "n_held": 0, "n_priced": 0, "contributors": []}

    total_weight = sum(p["weight_pct"] for p in prior_positions)
    weighted_return = 0.0
    n_priced = 0
    contributors = []

    for pos in prior_positions:
        ticker = pos["ticker"]
        w = pos["weight_pct"] / total_weight
        p0 = prior_prices.get(ticker)
        p1 = current_prices.get(ticker)
        if p0 and p1 and p0 > 0:
            ret = (p1 / p0) - 1.0
            weighted_return += w * ret
            n_priced += 1
            contributors.append({"ticker": ticker, "return": ret, "contrib": w * ret})
        # If price missing, treat as flat (conservative)

    contributors.sort(key=lambda c: c["contrib"], reverse=True)
    return {
        "pnl_pct": weighted_return * 100,
        "n_held": len(prior_positions),
        "n_priced": n_priced,
        "contributors": contributors,
    }


def compute_xbi_return(prior_prices: dict[str, float], current_prices: dict[str, float]) -> float:
    """Compute XBI return between two dates."""
    p0 = prior_prices.get("XBI")
    p1 = current_prices.get("XBI")
    if p0 and p1 and p0 > 0:
        return ((p1 / p0) - 1.0) * 100
    return 0.0


def run_benchmark(top_n: int = 20, start_date: str = "2000-01-01") -> dict:
    """Run the selection-only benchmark across all available snapshots."""
    log.info("Loading prices...")
    all_prices = load_price_map(PRICE_PATH)
    log.info("Loaded prices for %d dates", len(all_prices))

    dates = get_snapshot_dates(start_date)
    log.info("Found %d snapshot dates (from %s)", len(dates), start_date)

    if len(dates) < 2:
        log.error("Need at least 2 snapshots to compute returns")
        return {}

    # Build positions for each date
    positions_by_date = {}
    for d in dates:
        rankings = load_rankings(d)
        positions_by_date[d] = build_ew_positions(rankings, top_n)

    # Compute period returns
    periods = []
    for i in range(1, len(dates)):
        prior_date = dates[i - 1]
        current_date = dates[i]

        prior_pos = positions_by_date.get(prior_date, [])
        prior_prices = all_prices.get(prior_date, {})
        current_prices = all_prices.get(current_date, {})

        if not prior_pos or not prior_prices or not current_prices:
            continue

        ew_result = compute_ew_return(prior_pos, prior_prices, current_prices)
        xbi_ret = compute_xbi_return(prior_prices, current_prices)

        # Turnover: how many names changed?
        prior_tickers = set(p["ticker"] for p in prior_pos)
        current_pos = positions_by_date.get(current_date, [])
        current_tickers = set(p["ticker"] for p in current_pos)
        overlap = len(prior_tickers & current_tickers)
        turnover = 1.0 - (overlap / max(len(prior_tickers), 1))

        periods.append(
            {
                "date": current_date,
                "prior_date": prior_date,
                "ew_pnl_pct": round(ew_result["pnl_pct"], 4),
                "xbi_pct": round(xbi_ret, 4),
                "ew_excess": round(ew_result["pnl_pct"] - xbi_ret, 4),
                "n_held": ew_result["n_held"],
                "n_priced": ew_result["n_priced"],
                "turnover": round(turnover, 4),
                "top_contrib": ew_result["contributors"][0] if ew_result["contributors"] else None,
                "bottom_contrib": ew_result["contributors"][-1] if ew_result["contributors"] else None,
            }
        )

    # Load shadow for comparison
    shadow_perf = load_shadow_performance()
    shadow_by_date = {s["date"]: s for s in shadow_perf}

    # Merge
    for p in periods:
        shadow = shadow_by_date.get(p["date"], {})
        p["shadow_pnl_pct"] = shadow.get("pnl_pct", None)
        p["shadow_excess"] = shadow.get("excess", None)

    # Cumulative stats
    cum_ew = 0.0
    cum_shadow = 0.0
    cum_xbi = 0.0
    n_ew_wins = 0
    n_shadow_wins = 0

    for p in periods:
        cum_ew += p["ew_pnl_pct"]
        cum_xbi += p["xbi_pct"]
        p["cum_ew"] = round(cum_ew, 4)
        p["cum_xbi"] = round(cum_xbi, 4)
        p["cum_ew_excess"] = round(cum_ew - cum_xbi, 4)

        if p["shadow_pnl_pct"] is not None:
            cum_shadow += p["shadow_pnl_pct"]
            p["cum_shadow"] = round(cum_shadow, 4)
            p["cum_shadow_excess"] = round(cum_shadow - cum_xbi, 4)
            if p["ew_excess"] > 0:
                n_ew_wins += 1
            if p["shadow_excess"] is not None and p["shadow_excess"] > 0:
                n_shadow_wins += 1

    n_periods = len(periods)
    n_shadow_periods = sum(1 for p in periods if p["shadow_pnl_pct"] is not None)

    summary = {
        "schema": "selection_benchmark.v1",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "top_n": top_n,
        "n_periods": n_periods,
        "date_range": f"{periods[0]['prior_date']} to {periods[-1]['date']}" if periods else "",
        "ew_cumulative_pct": round(cum_ew, 4),
        "ew_cumulative_excess_pct": round(cum_ew - cum_xbi, 4),
        "ew_win_rate": round(n_ew_wins / max(n_periods, 1), 4),
        "ew_avg_return_pct": round(cum_ew / max(n_periods, 1), 4),
        "ew_avg_excess_pct": round((cum_ew - cum_xbi) / max(n_periods, 1), 4),
        "shadow_cumulative_pct": round(cum_shadow, 4) if n_shadow_periods > 0 else None,
        "shadow_cumulative_excess_pct": round(cum_shadow - cum_xbi, 4) if n_shadow_periods > 0 else None,
        "shadow_win_rate": round(n_shadow_wins / max(n_shadow_periods, 1), 4) if n_shadow_periods > 0 else None,
        "xbi_cumulative_pct": round(cum_xbi, 4),
        "construction_drag_pct": round(cum_ew - cum_shadow, 4) if n_shadow_periods > 0 else None,
        "diagnosis": "",
    }

    # Diagnosis
    if summary["construction_drag_pct"] is not None:
        drag = summary["construction_drag_pct"]
        ew_excess = summary["ew_cumulative_excess_pct"]
        if ew_excess > 0 and drag > 0:
            summary["diagnosis"] = "CONSTRUCTION_DRAG: Selection is generating alpha, construction is losing it"
        elif ew_excess > 0 and drag <= 0:
            summary["diagnosis"] = "BOTH_OK: Selection and construction both adding value"
        elif ew_excess <= 0 and drag > 0:
            summary["diagnosis"] = "SIGNAL_COLD_PLUS_DRAG: Signal is cold AND construction is dragging"
        else:
            summary["diagnosis"] = (
                "SIGNAL_COLD: Selection itself is underperforming, construction is not the primary problem"
            )

    return {"summary": summary, "periods": periods}


def main():
    parser = argparse.ArgumentParser(description="Selection-only benchmark")
    parser.add_argument("--top-n", type=int, default=20)
    parser.add_argument("--start-date", default="2000-01-01")
    parser.add_argument("--also-top30", action="store_true", help="Also run top-30 benchmark")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for n in [args.top_n, 30] if args.also_top30 else [args.top_n]:
        log.info("Running EW top-%d benchmark...", n)
        result = run_benchmark(top_n=n, start_date=args.start_date)

        if not result:
            log.error("No results produced")
            continue

        s = result["summary"]
        output_path = OUTPUT_DIR / f"selection_only_top{n}.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        log.info("Wrote %s", output_path)

        # Print summary
        print(f"\n{'='*60}")
        print(f"SELECTION-ONLY BENCHMARK: Equal-Weight Top-{n}")
        print(f"{'='*60}")
        print(f"Date range: {s['date_range']}")
        print(f"Periods: {s['n_periods']}")
        print()
        print(f"{'Metric':<35} {'EW Top-{n}':<15} {'Shadow':<15} {'XBI':<15}")
        print(f"{'-'*35} {'-'*15} {'-'*15} {'-'*15}")
        print(
            f"{'Cumulative return':<35} {s['ew_cumulative_pct']:>+.2f}%{'':<9} "
            f"{(str(round(s['shadow_cumulative_pct'],2))+'%') if s['shadow_cumulative_pct'] is not None else 'N/A':<15} "
            f"{s['xbi_cumulative_pct']:>+.2f}%"
        )
        print(
            f"{'Cumulative excess vs XBI':<35} {s['ew_cumulative_excess_pct']:>+.2f}%{'':<9} "
            f"{(str(round(s['shadow_cumulative_excess_pct'],2))+'%') if s['shadow_cumulative_excess_pct'] is not None else 'N/A':<15}"
        )
        print(
            f"{'Win rate (excess > 0)':<35} {s['ew_win_rate']:.1%}{'':<10} "
            f"{(str(round(s['shadow_win_rate']*100,1))+'%') if s['shadow_win_rate'] is not None else 'N/A':<15}"
        )
        if s["construction_drag_pct"] is not None:
            print(f"\n{'Construction drag (EW - Shadow)':<35} {s['construction_drag_pct']:>+.2f}%")
        print(f"\nDIAGNOSIS: {s['diagnosis']}")
        print()


if __name__ == "__main__":
    main()
