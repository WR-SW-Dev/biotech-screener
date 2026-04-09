"""Monthly IC decomposition — rolling selector health view.

Computes Spearman IC between DEM actionable_rank and forward returns
at multiple horizons, grouped by month. Answers: is the optionality
anchor IC stable or decaying?

Uses PIT price caches for forward returns (no lookahead).

Usage:
    python scripts/research/monthly_ic_decomposition.py
    python scripts/research/monthly_ic_decomposition.py --start-date 2020-01-01
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

SNAPSHOT_DIR = REPO_ROOT / "data" / "snapshots"
PIT_CACHE_DIR = REPO_ROOT / "data" / "caches" / "price_pit" / "PIT"
OUTPUT_DIR = REPO_ROOT / "output" / "forward_eval"

import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("monthly_ic")


def _avg_ranks(values: list[float]) -> list[float]:
    """Average-rank method for ties."""
    n = len(values)
    indexed = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j < n - 1 and values[indexed[j + 1]] == values[indexed[j]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[indexed[k]] = avg
        i = j + 1
    return ranks


def spearman_ic(signal: list[float], returns: list[float]) -> float | None:
    """Spearman rank correlation. Returns None if n < 10."""
    n = len(signal)
    if n < 10:
        return None
    rx = _avg_ranks(signal)
    ry = _avg_ranks(returns)
    mx = statistics.mean(rx)
    my = statistics.mean(ry)
    cov = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    sx = math.sqrt(sum((rx[i] - mx) ** 2 for i in range(n)))
    sy = math.sqrt(sum((ry[i] - my) ** 2 for i in range(n)))
    if sx == 0.0 or sy == 0.0:
        return None
    return cov / (sx * sy)


def load_rankings_signal(snapshot_date: str) -> dict[str, float]:
    """Load negated actionable_rank as signal (higher = better)."""
    rpath = SNAPSHOT_DIR / snapshot_date / "rankings.csv"
    if not rpath.exists():
        return {}
    signal = {}
    with open(rpath, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ar = row.get("actionable_rank", "").strip()
            ticker = row.get("ticker", "").strip().upper()
            if ar and ticker:
                try:
                    signal[ticker] = -float(ar)
                except ValueError:
                    pass
    return signal


def load_pit_forward_returns(snapshot_date: str) -> dict[str, dict[str, float]]:
    """Load forward returns from PIT cache.

    Returns {ticker: {h5: ret, h20: ret, h63: ret}}.
    """
    cache_dir = PIT_CACHE_DIR / snapshot_date
    prices_path = cache_dir / "prices.csv"
    if not prices_path.exists():
        return {}

    result = {}
    with open(prices_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ticker = row.get("ticker", "").strip().upper()
            anchor = row.get("anchor_close", "").strip()
            if not ticker or not anchor:
                continue
            try:
                p0 = float(anchor)
            except ValueError:
                continue
            if p0 <= 0:
                continue

            rets = {}
            for h in ["h5", "h20", "h63"]:
                hclose = row.get(f"{h}_close", "").strip()
                if hclose:
                    try:
                        p1 = float(hclose)
                        if p1 > 0:
                            ret = (p1 / p0) - 1.0
                            # Skip suspicious returns (splits/errors)
                            if abs(ret) < 3.0:
                                rets[h] = ret
                    except ValueError:
                        pass
            if rets:
                result[ticker] = rets

    return result


def compute_ic_for_date(snapshot_date: str) -> dict[str, float | None]:
    """Compute IC at multiple horizons for one snapshot date."""
    signal = load_rankings_signal(snapshot_date)
    returns = load_pit_forward_returns(snapshot_date)

    if not signal or not returns:
        return {}

    result = {"date": snapshot_date, "n_tickers": 0}

    for h in ["h5", "h20", "h63"]:
        tickers = [t for t in signal if t in returns and h in returns[t]]
        if not tickers:
            result[f"ic_{h}"] = None
            continue

        sig = [signal[t] for t in tickers]
        ret = [returns[t][h] for t in tickers]
        ic = spearman_ic(sig, ret)
        result[f"ic_{h}"] = round(ic, 4) if ic is not None else None
        result["n_tickers"] = max(result["n_tickers"], len(tickers))

    return result


def run_decomposition(start_date: str = "2020-01-01") -> dict:
    """Run monthly IC decomposition across all available PIT caches."""
    # Find all PIT cache dates with matching snapshots
    if not PIT_CACHE_DIR.exists():
        log.error("No PIT cache directory")
        return {}

    cache_dates = sorted(
        d.name
        for d in PIT_CACHE_DIR.iterdir()
        if d.is_dir() and d.name >= start_date and (SNAPSHOT_DIR / d.name / "rankings.csv").exists()
    )
    log.info("Found %d PIT cache dates with matching snapshots (from %s)", len(cache_dates), start_date)

    # Compute IC for each date
    daily_ics = []
    for d in cache_dates:
        ic = compute_ic_for_date(d)
        if ic and ic.get("n_tickers", 0) > 0:
            daily_ics.append(ic)

    log.info("Computed IC for %d dates", len(daily_ics))

    if not daily_ics:
        return {}

    # Group by month
    monthly: dict[str, list[dict]] = defaultdict(list)
    for ic in daily_ics:
        month = ic["date"][:7]  # YYYY-MM
        monthly[month].append(ic)

    # Compute monthly summary
    monthly_summary = []
    for month in sorted(monthly.keys()):
        entries = monthly[month]
        summary = {
            "month": month,
            "n_dates": len(entries),
            "avg_n_tickers": round(statistics.mean(e["n_tickers"] for e in entries)),
        }

        for h in ["h5", "h20", "h63"]:
            ics = [e.get(f"ic_{h}") for e in entries if e.get(f"ic_{h}") is not None]
            if ics:
                summary[f"mean_ic_{h}"] = round(statistics.mean(ics), 4)
                summary[f"median_ic_{h}"] = round(statistics.median(ics), 4)
                summary[f"pct_positive_{h}"] = round(sum(1 for x in ics if x > 0) / len(ics), 3)
                summary[f"n_obs_{h}"] = len(ics)
            else:
                summary[f"mean_ic_{h}"] = None
                summary[f"median_ic_{h}"] = None
                summary[f"pct_positive_{h}"] = None
                summary[f"n_obs_{h}"] = 0

        monthly_summary.append(summary)

    # Rolling 3-month IC
    rolling_3m = []
    for i in range(2, len(monthly_summary)):
        window = monthly_summary[i - 2 : i + 1]
        entry = {"end_month": window[-1]["month"], "start_month": window[0]["month"]}
        for h in ["h5", "h20", "h63"]:
            all_ics = []
            for w in window:
                if w.get(f"mean_ic_{h}") is not None:
                    all_ics.append(w[f"mean_ic_{h}"])
            if all_ics:
                entry[f"rolling_mean_ic_{h}"] = round(statistics.mean(all_ics), 4)
            else:
                entry[f"rolling_mean_ic_{h}"] = None
        rolling_3m.append(entry)

    # Overall summary
    all_h20 = [e.get("ic_h20") for e in daily_ics if e.get("ic_h20") is not None]
    all_h63 = [e.get("ic_h63") for e in daily_ics if e.get("ic_h63") is not None]

    overall = {
        "n_total_dates": len(daily_ics),
        "date_range": f"{daily_ics[0]['date']} to {daily_ics[-1]['date']}",
        "n_months": len(monthly_summary),
    }
    for label, ics in [("h20", all_h20), ("h63", all_h63)]:
        if ics:
            overall[f"overall_mean_ic_{label}"] = round(statistics.mean(ics), 4)
            overall[f"overall_median_ic_{label}"] = round(statistics.median(ics), 4)
            overall[f"overall_pct_positive_{label}"] = round(sum(1 for x in ics if x > 0) / len(ics), 3)
            # t-stat
            mu = statistics.mean(ics)
            se = statistics.stdev(ics) / math.sqrt(len(ics)) if len(ics) > 1 else 1
            overall[f"overall_tstat_{label}"] = round(mu / se, 2) if se > 0 else 0

    return {
        "schema": "monthly_ic_decomposition.v1",
        "generated_at": datetime.now().isoformat(),
        "overall": overall,
        "monthly": monthly_summary,
        "rolling_3m": rolling_3m,
        "daily": daily_ics,
    }


def print_summary(result: dict):
    overall = result["overall"]
    monthly = result["monthly"]
    # rolling_3m available in result

    print(f"\n{'='*75}")
    print("MONTHLY IC DECOMPOSITION — Selector Health")
    print(f"{'='*75}")
    print(f"Date range: {overall['date_range']}")
    print(f"Total dates: {overall['n_total_dates']}, Months: {overall['n_months']}")

    print("\nOverall IC:")
    for h in ["h20", "h63"]:
        mu = overall.get(f"overall_mean_ic_{h}", "—")
        med = overall.get(f"overall_median_ic_{h}", "—")
        pct = overall.get(f"overall_pct_positive_{h}", "—")
        t = overall.get(f"overall_tstat_{h}", "—")
        print(f"  {h}: mean={mu}, median={med}, pct_positive={pct}, t-stat={t}")

    print(f"\n{'Month':<10} {'N':<4} {'IC h20':<10} {'IC h63':<10} {'%+ h20':<8} {'%+ h63':<8}")
    print(f"{'-'*10} {'-'*4} {'-'*10} {'-'*10} {'-'*8} {'-'*8}")
    for m in monthly:
        ic20 = m.get("mean_ic_h20")
        ic63 = m.get("mean_ic_h63")
        pp20 = m.get("pct_positive_h20")
        pp63 = m.get("pct_positive_h63")
        print(
            (
                f"{m['month']:<10} {m['n_dates']:<4} " f"{ic20:>+7.4f}   "
                if ic20 is not None
                else f"{m['month']:<10} {m['n_dates']:<4} {'—':>10} "
            ),
            end="",
        )
        print(f"{ic63:>+7.4f}   " if ic63 is not None else f"{'—':>10} ", end="")
        print(f"{pp20:>5.0%}   " if pp20 is not None else f"{'—':>8} ", end="")
        print(f"{pp63:>5.0%}" if pp63 is not None else "—")

    # Signal health verdict
    recent_months = monthly[-6:] if len(monthly) >= 6 else monthly
    recent_h20 = [m["mean_ic_h20"] for m in recent_months if m.get("mean_ic_h20") is not None]
    if recent_h20:
        recent_mean = statistics.mean(recent_h20)
        if recent_mean > 0.03:
            verdict = "STRONG"
        elif recent_mean > 0.01:
            verdict = "MODERATE"
        elif recent_mean > -0.01:
            verdict = "WEAK"
        else:
            verdict = "COLD"
        print(f"\nSignal health (last 6 months, h20): {verdict} (mean IC = {recent_mean:+.4f})")


def main():
    parser = argparse.ArgumentParser(description="Monthly IC decomposition")
    parser.add_argument("--start-date", default="2020-01-01")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    result = run_decomposition(start_date=args.start_date)

    if not result:
        log.error("No results")
        return

    output_path = OUTPUT_DIR / "monthly_ic_summary.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    log.info("Wrote %s", output_path)

    # Also write CSV for easy charting
    csv_path = OUTPUT_DIR / "monthly_ic_summary.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=result["monthly"][0].keys())
        writer.writeheader()
        writer.writerows(result["monthly"])
    log.info("Wrote %s", csv_path)

    print_summary(result)


if __name__ == "__main__":
    main()
