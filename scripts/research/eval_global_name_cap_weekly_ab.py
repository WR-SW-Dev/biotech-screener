#!/usr/bin/env python3
"""A/B evaluation: weekly live-sim with global name cap ON vs OFF.

Reads archived snapshots + price_history.csv.  For each week:
  - Builds equal-weight top-N portfolio from rankings
  - Applies global name cap (reflow) when ON
  - Computes 1-week forward returns
  - Tracks hedged excess, turnover, and worst-name contribution

Sweeps cap levels: 3.0%, 3.5%, 4.0% (configurable).

Output:
  output/research/global_cap_ab/RESULTS.csv
  output/research/global_cap_ab/SUMMARY.md
"""

import csv
import io
import os
import sys
import tarfile
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from tools.trade_decision import _apply_global_name_cap_reflow

ARCHIVES_DIR = PROJECT_ROOT / "data" / "archives"
PRICE_CSV = PROJECT_ROOT / "production_data" / "price_history.csv"
OUTPUT_DIR = PROJECT_ROOT / "output" / "research" / "global_cap_ab"

TOP_N = 40
ACCOUNT_USD = 500_000
CAP_LEVELS = [0.020, 0.025, 0.030, 0.035]

# Realistic weight template: mirrors actual portfolio construction
# binary_91_180 (55%) across ~12 top names → ~4.6% each (uncapped)
# binary_31_90 (25%) across ~10 names → ~2.5% each
# binary_0_30 (10%) across ~8 names → ~1.25% each
# less_binary (10%) across ~10 names → ~1.0% each
# Total: ~40 names
WEIGHT_TEMPLATE_PCT = (
    [4.6] * 12  # binary_91_180: top ranked names
    + [2.5] * 10  # binary_31_90
    + [1.25] * 8  # binary_0_30
    + [1.0] * 10  # less_binary
)
# Normalize to sum to ~68% (matching real portfolio invested fraction)
_WT_SUM = sum(WEIGHT_TEMPLATE_PCT)
WEIGHT_TEMPLATE_PCT = [w / _WT_SUM * 68.0 for w in WEIGHT_TEMPLATE_PCT]


def load_price_history():
    prices = defaultdict(dict)
    with open(PRICE_CSV) as f:
        reader = csv.DictReader(f)
        for row in reader:
            close = row.get("close", "")
            if close:
                try:
                    prices[row["ticker"]][row["date"]] = float(close)
                except (ValueError, KeyError):
                    pass
    return prices


def load_archive_rankings(archive_path, as_of_date):
    try:
        with tarfile.open(archive_path, "r:gz") as tf:
            rankings_path = f"{as_of_date}/rankings.csv"
            try:
                member = tf.getmember(rankings_path)
            except KeyError:
                return None
            f = tf.extractfile(member)
            if f is None:
                return None
            text = io.TextIOWrapper(f, encoding="utf-8")
            reader = csv.DictReader(text)
            rows = []
            for row in reader:
                rank_str = row.get("actionable_rank", "")
                if not rank_str:
                    continue
                try:
                    int(rank_str)
                except ValueError:
                    continue
                eligible = row.get("eligible", "1")
                if eligible == "0":
                    continue
                rows.append(row)
            rows.sort(key=lambda r: int(r["actionable_rank"]))
            return rows[:TOP_N]
    except Exception:
        return None


def get_weekly_dates():
    dates = []
    for fn in os.listdir(ARCHIVES_DIR):
        if fn.endswith(".tar.gz"):
            dates.append(fn.replace(".tar.gz", ""))
    dates.sort()
    return dates


def find_next_price_date(prices_xbi, date_str, max_days=7):
    from datetime import datetime, timedelta

    dt = datetime.strptime(date_str, "%Y-%m-%d")
    for i in range(max_days):
        candidate = (dt + timedelta(days=i)).strftime("%Y-%m-%d")
        if candidate in prices_xbi:
            return candidate
    return None


def build_positions_from_rankings(rankings, account_usd):
    """Build positions with realistic weight template from rankings.

    Uses WEIGHT_TEMPLATE_PCT to assign higher weights to top-ranked names,
    mirroring the actual portfolio construction's bucket concentration.
    """
    n = min(len(rankings), len(WEIGHT_TEMPLATE_PCT))
    if n == 0:
        return []
    positions = []
    for i in range(n):
        wt_pct = WEIGHT_TEMPLATE_PCT[i]
        dollars = account_usd * wt_pct / 100
        positions.append(
            {
                "ticker": rankings[i]["ticker"],
                "target_dollars": round(dollars, 2),
                "weight_pct": round(wt_pct, 4),
            }
        )
    return positions


def apply_cap_to_positions(positions, cap_pct, account_usd):
    """Apply global name cap with reflow, return new positions list."""
    import copy

    capped = copy.deepcopy(positions)
    cap_dollars = account_usd * cap_pct
    _apply_global_name_cap_reflow(capped, cap_dollars)
    for p in capped:
        if account_usd > 0:
            p["weight_pct"] = round(p["target_dollars"] / account_usd * 100, 4)
    return capped


def compute_portfolio_return(positions, prices, trade_start, trade_end, account_usd):
    """Compute portfolio return using position weights."""
    total_weight = sum(p["target_dollars"] for p in positions)
    if total_weight <= 0:
        return None, None, None

    port_ret = 0.0
    worst_ret = float("inf")
    worst_ticker = ""
    worst_contrib = 0.0
    valid = 0

    for p in positions:
        ticker = p["ticker"]
        t_prices = prices.get(ticker, {})
        p_start = t_prices.get(trade_start)
        p_end = t_prices.get(trade_end)
        if not p_start or not p_end or p_start <= 0:
            continue

        ret = p_end / p_start - 1.0
        weight = p["target_dollars"] / total_weight
        contrib = ret * weight
        port_ret += contrib
        valid += 1

        if ret < worst_ret:
            worst_ret = ret
            worst_ticker = ticker
            worst_contrib = contrib

    if valid == 0:
        return None, None, None

    return port_ret * 100, worst_ticker, worst_contrib * 100


def compute_turnover(prev_positions, curr_positions):
    """Compute one-way turnover between two position sets."""
    prev_map = {p["ticker"]: p["target_dollars"] for p in prev_positions}
    curr_map = {p["ticker"]: p["target_dollars"] for p in curr_positions}
    all_tickers = set(prev_map) | set(curr_map)
    total_prev = sum(prev_map.values())
    if total_prev <= 0:
        return 0.0
    turnover = sum(abs(curr_map.get(t, 0) - prev_map.get(t, 0)) for t in all_tickers) / 2
    return turnover / total_prev * 100


def main():
    print("Loading price history...")
    prices = load_price_history()
    prices_xbi = prices.get("XBI", {})
    if not prices_xbi:
        print("ERROR: No XBI prices found", file=sys.stderr)
        return

    weekly_dates = get_weekly_dates()
    print(f"Found {len(weekly_dates)} archive dates")

    # Run A/B for each cap level (+ baseline with no cap)
    configs = [("OFF", None)] + [(f"{c*100:.1f}pct".replace(".0pct", "pct"), c) for c in CAP_LEVELS]

    results = {name: [] for name, _ in configs}
    prev_positions = {name: None for name, _ in configs}

    for i, as_of in enumerate(weekly_dates):
        if i >= len(weekly_dates) - 1:
            break

        next_date = weekly_dates[i + 1]
        archive_path = ARCHIVES_DIR / f"{as_of}.tar.gz"
        rankings = load_archive_rankings(archive_path, as_of)
        if rankings is None:
            continue

        trade_start = find_next_price_date(prices_xbi, as_of)
        trade_end = find_next_price_date(prices_xbi, next_date)
        if not trade_start or not trade_end:
            continue

        xbi_start = prices_xbi.get(trade_start)
        xbi_end = prices_xbi.get(trade_end)
        if not xbi_start or not xbi_end:
            continue
        xbi_ret = (xbi_end / xbi_start - 1.0) * 100

        base_positions = build_positions_from_rankings(rankings, ACCOUNT_USD)
        if not base_positions:
            continue

        for name, cap_pct in configs:
            if cap_pct is not None:
                positions = apply_cap_to_positions(base_positions, cap_pct, ACCOUNT_USD)
            else:
                positions = base_positions

            port_ret, worst_ticker, worst_contrib = compute_portfolio_return(
                positions, prices, trade_start, trade_end, ACCOUNT_USD
            )
            if port_ret is None:
                continue

            excess = port_ret - xbi_ret

            turnover = 0.0
            if prev_positions[name] is not None:
                turnover = compute_turnover(prev_positions[name], positions)
            prev_positions[name] = positions

            max_wt = max(p["target_dollars"] for p in positions) / ACCOUNT_USD * 100

            # Worst-name contributor fraction
            blow_up_frac = 0.0
            if port_ret < 0 and worst_contrib < 0:
                blow_up_frac = worst_contrib / port_ret

            results[name].append(
                {
                    "as_of": as_of,
                    "port_ret_pct": round(port_ret, 4),
                    "xbi_ret_pct": round(xbi_ret, 4),
                    "excess_pct": round(excess, 4),
                    "turnover_pct": round(turnover, 2),
                    "max_position_pct": round(max_wt, 2),
                    "worst_ticker": worst_ticker,
                    "worst_contrib_pct": round(worst_contrib, 4),
                    "blow_up_frac": round(blow_up_frac, 4),
                }
            )

    # Write results
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for name, rows in results.items():
        if not rows:
            continue
        path = OUTPUT_DIR / f"weekly_{name}.csv"
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=rows[0].keys())
            w.writeheader()
            w.writerows(rows)
        print(f"Wrote {len(rows)} rows to {path}")

    # Summary
    lines = ["# Global Name Cap A/B Results", ""]
    lines.append(f"Archives: {weekly_dates[0]} to {weekly_dates[-1]}")
    lines.append(f"Top-N: {TOP_N}, Account: ${ACCOUNT_USD:,}")
    lines.append("")
    lines.append("## Summary Table")
    lines.append("")
    lines.append("| Config | Weeks | Mean Excess | Worst-20 Avg Excess | Turnover | Max Pos% | Blow-up >25% |")
    lines.append("|--------|-------|-------------|---------------------|----------|----------|-------------|")

    for name, cap_pct in configs:
        rows = results[name]
        if not rows:
            continue
        n = len(rows)
        excess_vals = [r["excess_pct"] for r in rows]
        turnover_vals = [r["turnover_pct"] for r in rows]
        max_pos_vals = [r["max_position_pct"] for r in rows]
        blow_up_vals = [r["blow_up_frac"] for r in rows]

        mean_excess = sum(excess_vals) / n
        mean_turnover = sum(turnover_vals) / n
        mean_max_pos = sum(max_pos_vals) / n

        worst_20 = sorted(excess_vals)[:20]
        worst_20_avg = sum(worst_20) / len(worst_20)

        # Weeks where worst single name explains >25% of portfolio loss
        blow_up_weeks = sum(1 for b in blow_up_vals if b > 0.25)
        blow_up_pct = blow_up_weeks / n * 100

        lines.append(
            f"| {name:6s} | {n:5d} | {mean_excess:+.4f}% | {worst_20_avg:+.4f}% | "
            f"{mean_turnover:.2f}% | {mean_max_pos:.2f}% | {blow_up_weeks} ({blow_up_pct:.0f}%) |"
        )

    # Acceptance bars
    lines.append("")
    lines.append("## Acceptance Bars")
    lines.append("")

    for name, cap_pct in configs:
        if cap_pct is None:
            continue
        rows = results[name]
        baseline = results["OFF"]
        if not rows or not baseline:
            continue

        excess_vals = [r["excess_pct"] for r in rows]
        baseline_excess = [r["excess_pct"] for r in baseline]
        turnover_vals = [r["turnover_pct"] for r in rows]
        baseline_turnover = [r["turnover_pct"] for r in baseline]

        mean_excess = sum(excess_vals) / len(excess_vals)
        base_mean = sum(baseline_excess) / len(baseline_excess)
        delta_excess = mean_excess - base_mean

        mean_turnover = sum(turnover_vals) / len(turnover_vals)
        base_turnover = sum(baseline_turnover) / len(baseline_turnover)
        delta_turnover = mean_turnover - base_turnover

        worst_20 = sorted(excess_vals)[:20]
        base_worst_20 = sorted(baseline_excess)[:20]
        w20_avg = sum(worst_20) / len(worst_20)
        base_w20_avg = sum(base_worst_20) / len(base_worst_20)
        delta_tail = w20_avg - base_w20_avg

        pass_excess = delta_excess >= -0.05
        pass_turnover = delta_turnover <= 0.25
        pass_tail = delta_tail > 0

        lines.append(f"### {name}")
        lines.append(
            f"- Mean excess delta: {delta_excess:+.4f}pp {'PASS' if pass_excess else 'FAIL'} (bar: >= -0.05pp)"
        )
        lines.append(
            f"- Turnover delta: {delta_turnover:+.2f}pp {'PASS' if pass_turnover else 'FAIL'} (bar: <= 0.25pp)"
        )
        lines.append(f"- Worst-20 tail delta: {delta_tail:+.4f}pp {'PASS' if pass_tail else 'FAIL'} (bar: > 0)")
        lines.append("")

    # Detailed worst-20 comparison
    lines.append("## Worst 20 Weeks — OFF vs Best Cap Level")
    lines.append("")

    # Find best cap level by tail improvement
    best_name = None
    best_tail_delta = -999
    for name, cap_pct in configs:
        if cap_pct is None:
            continue
        rows = results[name]
        baseline = results["OFF"]
        if not rows or not baseline:
            continue
        w20 = sorted([r["excess_pct"] for r in rows])[:20]
        bw20 = sorted([r["excess_pct"] for r in baseline])[:20]
        delta = sum(w20) / len(w20) - sum(bw20) / len(bw20)
        if delta > best_tail_delta:
            best_tail_delta = delta
            best_name = name

    if best_name:
        lines.append(f"Best level: **{best_name}** (tail improvement: {best_tail_delta:+.4f}pp)")
        lines.append("")

        off_rows = sorted(results["OFF"], key=lambda r: r["excess_pct"])[:20]
        cap_rows_map = {r["as_of"]: r for r in results[best_name]}

        lines.append("| Date | OFF Excess | Cap Excess | Delta | OFF Worst | Cap Worst |")
        lines.append("|------|-----------|-----------|-------|----------|----------|")
        for r in off_rows:
            cr = cap_rows_map.get(r["as_of"], {})
            lines.append(
                f"| {r['as_of']} | {r['excess_pct']:+.2f}% | {cr.get('excess_pct', 0):+.2f}% | "
                f"{cr.get('excess_pct', 0) - r['excess_pct']:+.2f}pp | "
                f"{r['worst_ticker']} ({r['worst_contrib_pct']:+.2f}%) | "
                f"{cr.get('worst_ticker', '?')} ({cr.get('worst_contrib_pct', 0):+.2f}%) |"
            )

    summary_path = OUTPUT_DIR / "SUMMARY.md"
    with open(summary_path, "w") as f:
        f.write("\n".join(lines))
    print(f"\nSummary: {summary_path}")

    # Print to stdout too
    for line in lines:
        print(line)


if __name__ == "__main__":
    main()
