#!/usr/bin/env python3
"""Re-score historical snapshots with the hardened selector config.

Reads existing rankings.csv from each snapshot, recomputes:
  1. coinvest_score_z (size-residualized via market_cap_bucket proxy + filing-age decay)
  2. selector scores with the new A4 v1.1 config (clinical=0%, catalyst=15%)

Produces an updated research panel with honest selector rankings.

Does NOT re-run the full pipeline. Uses existing signal columns from
rankings.csv and only recomputes the selector/coinvest layers.

Usage:
    python3 scripts/research/rescore_historical_snapshots.py
    python3 scripts/research/rescore_historical_snapshots.py --out output/rescored_panel.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from selector_engine import BlockWeight, SelectorConfig, SignalSpec, compute_selector_scores

SNAPSHOTS_DIR = PROJECT_ROOT / "data" / "snapshots"
PRICE_CSV = PROJECT_ROOT / "production_data" / "price_history_split_adj.csv"
OUTPUT_DIR = PROJECT_ROOT / "output" / "rescored_benchmark"

# Hardened A4 v1.1 config
A4_HARDENED = SelectorConfig(
    block_weights=(
        BlockWeight("clinical", 0.00),
        BlockWeight("catalyst", 0.15),
        BlockWeight("survivability", 0.10),
        BlockWeight("institutional", 0.65),
        BlockWeight("market_structure", 0.10),
    ),
    institutional_signals=(
        SignalSpec("coinvest_score_z", 0.65),
        SignalSpec("inst_delta_z", 0.35),
        SignalSpec(
            "coinvest_recency_state",
            0.00,
            categorical=True,
            value_map=(("fresh", 1.0), ("stale", 0.3), ("", 0.0)),
        ),
    ),
)

# Market cap bucket midpoints (log scale) for size residualization proxy
BUCKET_LOG_MCAP = {
    "micro": math.log(100e6),  # ~$100M
    "small": math.log(500e6),  # ~$500M
    "mid": math.log(2e9),  # ~$2B
    "large": math.log(10e9),  # ~$10B
    "mega": math.log(50e9),  # ~$50B
    "": math.log(500e6),  # default: small
}

DECAY_HALF_LIFE = 90  # days


def _sf(val, default=None):
    if val is None or val == "":
        return default
    try:
        v = float(val)
        return v if not math.isnan(v) else default
    except (ValueError, TypeError):
        return default


def _residualize_coinvest(rows: List[Dict]) -> None:
    """Recompute coinvest_score_z with size residualization + filing-age decay.

    Modifies rows in place. Uses market_cap_bucket as a proxy for log(mcap).
    """
    # Collect (index, raw_tier1_count, log_mcap_proxy, filing_age)
    pairs = []
    for i, r in enumerate(rows):
        t1 = _sf(r.get("sponsor_tier1_count"))
        bucket = (r.get("market_cap_bucket") or "").lower().strip()
        log_mcap = BUCKET_LOG_MCAP.get(bucket, BUCKET_LOG_MCAP[""])
        age = _sf(r.get("coinvest_filing_age_days"))
        if t1 is not None:
            pairs.append((i, t1, log_mcap, age))

    if len(pairs) < 10:
        # Not enough data — set all to 0
        for r in rows:
            r["coinvest_score_z"] = "0.0"
        return

    # OLS: tier1_count = alpha + beta * log_mcap + residual
    n = len(pairs)
    y = [p[1] for p in pairs]
    x = [p[2] for p in pairs]
    y_mean = sum(y) / n
    x_mean = sum(x) / n
    cov = sum((y[j] - y_mean) * (x[j] - x_mean) for j in range(n)) / n
    var_x = sum((x[j] - x_mean) ** 2 for j in range(n)) / n
    if var_x > 1e-12:
        beta = cov / var_x
        alpha = y_mean - beta * x_mean
    else:
        beta, alpha = 0.0, y_mean

    # Compute residuals
    residuals = {}
    for i, t1, lm, age in pairs:
        resid = t1 - (alpha + beta * lm)
        # Apply filing-age decay
        if age is not None and age > 0:
            decay = math.exp(-age / DECAY_HALF_LIFE * math.log(2))
            resid *= decay
        residuals[i] = resid

    # Z-score residuals
    vals = list(residuals.values())
    r_mean = sum(vals) / len(vals)
    r_var = sum((v - r_mean) ** 2 for v in vals) / len(vals)
    r_std = r_var**0.5

    for i, r in enumerate(rows):
        if i in residuals and r_std > 0:
            z = (residuals[i] - r_mean) / r_std
            r["coinvest_score_z"] = str(round(z, 4))
        else:
            r["coinvest_score_z"] = "0.0"


def _load_prices(price_csv: Path) -> Dict[str, Dict[str, float]]:
    """Load prices into {ticker: {date: close}}."""
    prices: Dict[str, Dict[str, float]] = {}
    with open(price_csv, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            t = row.get("ticker", "")
            d = row.get("date", "")
            c = _sf(row.get("close"))
            if t and d and c is not None and c > 0:
                prices.setdefault(t, {})[d] = c
    return prices


def _forward_return(
    prices: Dict[str, float],
    sorted_dates: List[str],
    snap_date: str,
    horizon: int,
) -> Optional[float]:
    """Forward return with 1-day execution lag."""
    import bisect

    idx = bisect.bisect_left(sorted_dates, snap_date)
    # Execution lag: start at idx+1
    start_idx = idx + 1
    end_idx = start_idx + horizon
    if end_idx >= len(sorted_dates) or start_idx >= len(sorted_dates):
        return None
    p0 = prices.get(sorted_dates[start_idx])
    p1 = prices.get(sorted_dates[end_idx])
    if p0 and p1 and p0 > 0:
        return (p1 - p0) / p0
    return None


def discover_snapshots(snap_dir: Path) -> List[str]:
    """Find snapshot dates with rankings.csv."""
    date_pat = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    dates = []
    for d in sorted(snap_dir.iterdir()):
        if d.is_dir() and date_pat.match(d.name) and (d / "rankings.csv").exists():
            dates.append(d.name)
    return dates


def rescore_all(
    snap_dir: Path,
    price_csv: Path,
    output_dir: Path,
    horizons: Tuple[int, ...] = (5, 20, 63),
) -> Dict[str, Any]:
    """Re-score all snapshots and build a rescored research panel."""
    snap_dates = discover_snapshots(snap_dir)
    print(f"Found {len(snap_dates)} snapshots")

    # Load prices
    print("Loading prices...")
    all_prices = _load_prices(price_csv)

    # Build sorted date lists per ticker
    ticker_sorted: Dict[str, List[str]] = {}
    for t, pmap in all_prices.items():
        ticker_sorted[t] = sorted(pmap.keys())

    # XBI prices for benchmark
    xbi_prices = all_prices.get("XBI", {})
    xbi_sorted = sorted(xbi_prices.keys())

    output_dir.mkdir(parents=True, exist_ok=True)
    panel_path = output_dir / "rescored_panel.csv"

    panel_fields = [
        "snapshot_date",
        "ticker",
        "eligible",
        "selector_score_old",
        "selector_score_new",
        "selector_rank_old",
        "selector_rank_new",
        "rank_change",
        "coinvest_z_old",
        "coinvest_z_new",
    ]
    for h in horizons:
        panel_fields.extend([f"fwd_ret_{h}d", f"fwd_excess_xbi_{h}d"])

    panel_rows = []
    n_rescored = 0

    for snap_date in snap_dates:
        rankings_path = snap_dir / snap_date / "rankings.csv"
        with open(rankings_path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        eligible = [r for r in rows if r.get("eligible", "") not in ("0", "0.0", "")]
        if len(eligible) < 10:
            continue

        # Save old values
        for r in eligible:
            r["_old_coinvest_z"] = r.get("coinvest_score_z", "0")
            r["_old_selector"] = r.get("selector_score", "0")

        # Recompute coinvest_score_z (residualized + decayed)
        _residualize_coinvest(eligible)

        # Recompute selector scores
        try:
            sel_results = compute_selector_scores(eligible, A4_HARDENED)
        except Exception as e:
            print(f"  {snap_date}: selector error: {e}")
            continue

        # Rank old and new selector scores
        old_scores = [(i, _sf(r.get("_old_selector"), 0)) for i, r in enumerate(eligible)]
        new_scores = [(i, sel_results[i].selector_score) for i in range(len(eligible))]
        old_ranked = {idx: rank + 1 for rank, (idx, _) in enumerate(sorted(old_scores, key=lambda x: -x[1]))}
        new_ranked = {idx: rank + 1 for rank, (idx, _) in enumerate(sorted(new_scores, key=lambda x: -x[1]))}

        for i, r in enumerate(eligible):
            ticker = r.get("ticker", "")
            old_rank = old_ranked.get(i, 999)
            new_rank = new_ranked.get(i, 999)

            row_out = {
                "snapshot_date": snap_date,
                "ticker": ticker,
                "eligible": "1",
                "selector_score_old": r.get("_old_selector", "0"),
                "selector_score_new": str(round(sel_results[i].selector_score, 4)),
                "selector_rank_old": str(old_rank),
                "selector_rank_new": str(new_rank),
                "rank_change": str(new_rank - old_rank),
                "coinvest_z_old": r.get("_old_coinvest_z", "0"),
                "coinvest_z_new": r.get("coinvest_score_z", "0"),
            }

            # Forward returns (with 1-day execution lag)
            t_prices = all_prices.get(ticker, {})
            t_sorted = ticker_sorted.get(ticker, [])
            for h in horizons:
                ret = _forward_return(t_prices, t_sorted, snap_date, h) if t_sorted else None
                xbi_ret = _forward_return(xbi_prices, xbi_sorted, snap_date, h) if xbi_sorted else None
                row_out[f"fwd_ret_{h}d"] = str(round(ret, 6)) if ret is not None else ""
                excess = (ret - xbi_ret) if ret is not None and xbi_ret is not None else None
                row_out[f"fwd_excess_xbi_{h}d"] = str(round(excess, 6)) if excess is not None else ""

            panel_rows.append(row_out)

        n_rescored += 1
        if n_rescored % 20 == 0:
            print(f"  {n_rescored}/{len(snap_dates)} snapshots rescored...")

    # Write panel
    with open(panel_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=panel_fields)
        writer.writeheader()
        writer.writerows(panel_rows)

    print(f"\nRescored {n_rescored} snapshots, {len(panel_rows)} rows")
    print(f"Panel: {panel_path}")

    # Compute summary statistics
    from scripts.research.selector_weight_sensitivity import _spearman_ic

    ic_old_20 = []
    ic_new_20 = []
    for snap_date in set(r["snapshot_date"] for r in panel_rows):
        snap_rows = [r for r in panel_rows if r["snapshot_date"] == snap_date]
        old_s = [_sf(r["selector_score_old"], 0) for r in snap_rows]
        new_s = [_sf(r["selector_score_new"], 0) for r in snap_rows]
        rets = [_sf(r.get("fwd_ret_20d")) for r in snap_rows]
        valid = [(o, n, rt) for o, n, rt in zip(old_s, new_s, rets) if rt is not None]
        if len(valid) >= 10:
            o_vals, n_vals, r_vals = zip(*valid)
            ic_o = _spearman_ic(list(o_vals), list(r_vals))
            ic_n = _spearman_ic(list(n_vals), list(r_vals))
            if ic_o is not None:
                ic_old_20.append(ic_o)
            if ic_n is not None:
                ic_new_20.append(ic_n)

    summary = {
        "n_snapshots": n_rescored,
        "n_rows": len(panel_rows),
        "ic_old_20d": round(sum(ic_old_20) / len(ic_old_20), 4) if ic_old_20 else None,
        "ic_new_20d": round(sum(ic_new_20) / len(ic_new_20), 4) if ic_new_20 else None,
        "ic_n_dates": len(ic_old_20),
    }
    print("\nSelector IC comparison (20d):")
    print(f"  OLD config: {summary['ic_old_20d']} ({len(ic_old_20)} dates)")
    print(f"  NEW config: {summary['ic_new_20d']} ({len(ic_new_20)} dates)")

    summary_path = output_dir / "rescore_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    return summary


def main():
    parser = argparse.ArgumentParser(description="Re-score snapshots with hardened config")
    parser.add_argument("--snap-dir", type=Path, default=SNAPSHOTS_DIR)
    parser.add_argument("--price-csv", type=Path, default=PRICE_CSV)
    parser.add_argument("--out-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()

    rescore_all(args.snap_dir, args.price_csv, args.out_dir)


if __name__ == "__main__":
    main()
