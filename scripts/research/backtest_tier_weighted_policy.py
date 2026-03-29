#!/usr/bin/env python3
"""Backtest tier-weighted portfolio policy (Spec 035).

Replays historical shadow positions under three policies:
  - Current: flat weight (as-is)
  - Variant A: tier-weighted (A=4, B=2.5, C=1, D=0)
  - Variant B: tier-weighted + headwind+drawdown exit

Reports cumulative returns, turnover, concentration, and per-tier/momentum
attribution.

Output:
    output/research/tier_weighted_policy_compare.json
    output/research/tier_weighted_policy_compare.md

Usage:
    python scripts/research/backtest_tier_weighted_policy.py
    python scripts/research/backtest_tier_weighted_policy.py --a-weights 4,2.5,1,0
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("tier_weighted_policy")

# Default tier weights for Variant A
DEFAULT_TIER_WEIGHTS = {"A": 4.0, "B": 2.5, "C": 1.0, "D": 0.0}

# Headwind exit: require this many consecutive headwind+drawdown days
DEFAULT_HEADWIND_EXIT_PERSISTENCE = 3


def load_prices(price_path: Path) -> Dict[str, Dict[str, float]]:
    prices: Dict[str, Dict[str, float]] = defaultdict(dict)
    with open(price_path) as f:
        for row in csv.DictReader(f):
            t = row.get("ticker", "")
            d = row.get("date", "")
            c = row.get("close", "")
            if t and d and c:
                try:
                    prices[t][d] = float(c)
                except ValueError:
                    pass
    return prices


def get_price(prices: Dict[str, Dict[str, float]], ticker: str, date: str) -> Optional[float]:
    tp = prices.get(ticker, {})
    avail = sorted(d for d in tp if d <= date)
    return tp[avail[-1]] if avail else None


def load_positions(pos_dir: Path) -> Dict[str, Dict[str, Dict]]:
    """Load all position snapshots. Returns {date: {ticker: position_dict}}."""
    result = {}
    for f in sorted(pos_dir.glob("*.json")):
        date = f.stem
        data = json.loads(f.read_text())
        result[date] = {p["ticker"]: p for p in data.get("positions", [])}
    return result


def load_rankings(snap_dir: Path, dates: List[str]) -> Dict[str, Dict[str, Dict]]:
    """Load rankings for each date. Returns {date: {ticker: ranking_dict}}."""
    result = {}
    for date in dates:
        rpath = snap_dir / date / "rankings.csv"
        if rpath.exists():
            with open(rpath) as f:
                result[date] = {r["ticker"]: r for r in csv.DictReader(f)}
    return result


def compute_policy_weights(
    positions: Dict[str, Dict],
    rankings: Dict[str, Dict],
    tier_weights: Dict[str, float],
    apply_exit: bool = False,
    headwind_streak: Optional[Dict[str, int]] = None,
    exit_persistence: int = DEFAULT_HEADWIND_EXIT_PERSISTENCE,
) -> Dict[str, float]:
    """Compute normalized weights under a given policy.

    Returns {ticker: weight_pct} where weights sum to ~100%.
    """
    raw_weights = {}
    for ticker in positions:
        r = rankings.get(ticker, {})
        tier = r.get("tier_dev", "")
        mom = r.get("mom_state", "")
        risk = r.get("risk_flags", "")

        w = tier_weights.get(tier, 0.0)

        # Variant B: exit headwind + deep_drawdown after persistence threshold
        if apply_exit and headwind_streak is not None:
            streak = headwind_streak.get(ticker, 0)
            if mom == "headwind" and "deep_drawdown" in risk and streak >= exit_persistence:
                w = 0.0

        if w > 0:
            raw_weights[ticker] = w

    # Normalize to sum to 100%
    total = sum(raw_weights.values())
    if total <= 0:
        return {}
    return {t: w / total * 100.0 for t, w in raw_weights.items()}


def simulate_policies(
    pos_dates: List[str],
    daily_positions: Dict[str, Dict[str, Dict]],
    daily_rankings: Dict[str, Dict[str, Dict]],
    prices: Dict[str, Dict[str, float]],
    tier_weights: Dict[str, float],
    exit_persistence: int = DEFAULT_HEADWIND_EXIT_PERSISTENCE,
) -> Dict[str, Any]:
    """Simulate three policies across all date pairs."""

    # Track headwind+drawdown streak per ticker
    headwind_streak: Dict[str, int] = defaultdict(int)

    policy_names = ["current", "tiered", "tiered_exit"]
    daily_returns = {p: [] for p in policy_names}
    daily_turnover = {p: [] for p in policy_names}
    tier_pnl = {p: defaultdict(float) for p in policy_names}
    tier_weight_days = {p: defaultdict(float) for p in policy_names}
    mom_pnl = {p: defaultdict(float) for p in policy_names}
    mom_weight_days = {p: defaultdict(float) for p in policy_names}

    prev_weights = {p: {} for p in policy_names}

    for i in range(1, len(pos_dates)):
        date = pos_dates[i]
        prior_date = pos_dates[i - 1]

        positions = daily_positions.get(prior_date, {})
        rankings = daily_rankings.get(prior_date, {})

        if not positions or not rankings:
            continue

        # Update headwind streaks
        for ticker in positions:
            r = rankings.get(ticker, {})
            if r.get("mom_state") == "headwind" and "deep_drawdown" in r.get("risk_flags", ""):
                headwind_streak[ticker] += 1
            else:
                headwind_streak[ticker] = 0

        # Compute weights for each policy
        # Current: use actual position weights
        w_current = {t: p.get("weight_pct", 3.0) for t, p in positions.items()}
        total_c = sum(w_current.values())
        if total_c > 0:
            w_current = {t: w / total_c * 100 for t, w in w_current.items()}

        w_tiered = compute_policy_weights(positions, rankings, tier_weights)
        w_tiered_exit = compute_policy_weights(
            positions,
            rankings,
            tier_weights,
            apply_exit=True,
            headwind_streak=headwind_streak,
            exit_persistence=exit_persistence,
        )

        weights_map = {"current": w_current, "tiered": w_tiered, "tiered_exit": w_tiered_exit}

        for policy in policy_names:
            weights = weights_map[policy]
            day_ret = 0.0

            for ticker, w in weights.items():
                p0 = get_price(prices, ticker, prior_date)
                p1 = get_price(prices, ticker, date)
                if p0 is None or p1 is None or p0 <= 0:
                    continue

                stock_ret = (p1 - p0) / p0
                weighted_ret = w / 100.0 * stock_ret
                day_ret += weighted_ret

                # Attribution
                tier = rankings.get(ticker, {}).get("tier_dev", "?")
                mom = rankings.get(ticker, {}).get("mom_state", "?")
                tier_pnl[policy][tier] += w * stock_ret
                tier_weight_days[policy][tier] += w
                mom_pnl[policy][mom] += w * stock_ret
                mom_weight_days[policy][mom] += w

            daily_returns[policy].append((date, day_ret * 100))

            # Turnover: sum of absolute weight changes
            pw = prev_weights[policy]
            all_tickers = set(list(weights.keys()) + list(pw.keys()))
            turnover = sum(abs(weights.get(t, 0) - pw.get(t, 0)) for t in all_tickers) / 2
            daily_turnover[policy].append((date, turnover))
            prev_weights[policy] = weights

    return {
        "daily_returns": daily_returns,
        "daily_turnover": daily_turnover,
        "tier_pnl": tier_pnl,
        "tier_weight_days": tier_weight_days,
        "mom_pnl": mom_pnl,
        "mom_weight_days": mom_weight_days,
    }


def format_results(
    sim: Dict, tier_weights: Dict[str, float], exit_persistence: int = DEFAULT_HEADWIND_EXIT_PERSISTENCE
) -> Dict[str, Any]:
    """Format simulation results into output structure."""
    policies = ["current", "tiered", "tiered_exit"]
    policy_labels = {
        "current": "Current (flat)",
        "tiered": f"Tier-weighted (A={tier_weights['A']}/B={tier_weights['B']}/C={tier_weights['C']}/D={tier_weights['D']})",
        "tiered_exit": "Tier-weighted + headwind exit",
    }

    summary = {}
    for p in policies:
        rets = [r for _, r in sim["daily_returns"][p]]
        turns = [t for _, t in sim["daily_turnover"][p]]
        cum_ret = sum(rets)
        max_dd = 0.0
        peak = 0.0
        running = 0.0
        for r in rets:
            running += r
            peak = max(peak, running)
            dd = peak - running
            max_dd = max(max_dd, dd)

        summary[p] = {
            "label": policy_labels[p],
            "cumulative_return_pct": round(cum_ret, 2),
            "n_days": len(rets),
            "mean_daily_return_pct": round(cum_ret / max(len(rets), 1), 3),
            "max_drawdown_pct": round(max_dd, 2),
            "mean_daily_turnover_pct": round(sum(turns) / max(len(turns), 1), 1),
            "total_turnover_pct": round(sum(turns), 1),
        }

    # Tier attribution per policy
    tier_attr = {}
    for p in policies:
        tier_attr[p] = {}
        for tier in ["A", "B", "C", "D", "?"]:
            wd = sim["tier_weight_days"][p].get(tier, 0)
            pnl = sim["tier_pnl"][p].get(tier, 0)
            if wd > 0:
                tier_attr[p][tier] = {
                    "weighted_pnl_pct": round(pnl, 3),
                    "weight_days": round(wd, 0),
                    "pnl_per_weight_day_pct": round(pnl / wd * 100, 3),
                }

    # Momentum attribution per policy
    mom_attr = {}
    for p in policies:
        mom_attr[p] = {}
        for mom in ["headwind", "neutral", "tailwind", "?"]:
            wd = sim["mom_weight_days"][p].get(mom, 0)
            pnl = sim["mom_pnl"][p].get(mom, 0)
            if wd > 0:
                mom_attr[p][mom] = {
                    "weighted_pnl_pct": round(pnl, 3),
                    "weight_days": round(wd, 0),
                    "pnl_per_weight_day_pct": round(pnl / wd * 100, 3),
                }

    # Daily return path
    daily_path = []
    cum = {p: 0.0 for p in policies}
    for i in range(len(sim["daily_returns"]["current"])):
        date = sim["daily_returns"]["current"][i][0]
        row = {"date": date}
        for p in policies:
            ret = sim["daily_returns"][p][i][1] if i < len(sim["daily_returns"][p]) else 0
            cum[p] += ret
            row[f"{p}_cum_pct"] = round(cum[p], 2)
            row[f"{p}_day_pct"] = round(ret, 2)
        daily_path.append(row)

    return {
        "schema": "tier_weighted_policy_compare.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tier_weights": tier_weights,
        "headwind_exit_persistence": exit_persistence,
        "summary": summary,
        "tier_attribution": tier_attr,
        "momentum_attribution": mom_attr,
        "daily_path": daily_path,
    }


def format_md(result: Dict) -> str:
    lines = []
    lines.append("# Tier-Weighted Policy Compare (Spec 035)")
    lines.append("")
    tw = result["tier_weights"]
    lines.append(f"Weights: A={tw['A']} / B={tw['B']} / C={tw['C']} / D={tw['D']}")
    lines.append(f"Headwind exit persistence: {result['headwind_exit_persistence']} days")
    lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append("| Policy | Cum Return | Max DD | Mean Turnover | Total Turnover |")
    lines.append("|--------|-----------|--------|---------------|----------------|")
    for p, s in result["summary"].items():
        lines.append(
            f"| {s['label']} | {s['cumulative_return_pct']:+.2f}% | "
            f"{s['max_drawdown_pct']:.2f}% | {s['mean_daily_turnover_pct']:.1f}% | "
            f"{s['total_turnover_pct']:.1f}% |"
        )
    lines.append("")

    # Improvement
    c_ret = result["summary"]["current"]["cumulative_return_pct"]
    for p in ["tiered", "tiered_exit"]:
        delta = result["summary"][p]["cumulative_return_pct"] - c_ret
        lines.append(f"**{result['summary'][p]['label']}** improvement: **{delta:+.2f}pp**")
    lines.append("")

    lines.append("## Tier Attribution (P&L per weight-day)")
    lines.append("")
    lines.append("| Tier | Current | Tiered | Tier+Exit |")
    lines.append("|------|---------|--------|-----------|")
    for tier in ["A", "B", "C", "D"]:
        vals = []
        for p in ["current", "tiered", "tiered_exit"]:
            ta = result["tier_attribution"].get(p, {}).get(tier, {})
            v = ta.get("pnl_per_weight_day_pct")
            vals.append(f"{v:+.3f}%" if v is not None else "—")
        lines.append(f"| {tier} | {vals[0]} | {vals[1]} | {vals[2]} |")
    lines.append("")

    lines.append("## Momentum Attribution (P&L per weight-day)")
    lines.append("")
    lines.append("| Momentum | Current | Tiered | Tier+Exit |")
    lines.append("|----------|---------|--------|-----------|")
    for mom in ["headwind", "neutral", "tailwind"]:
        vals = []
        for p in ["current", "tiered", "tiered_exit"]:
            ma = result["momentum_attribution"].get(p, {}).get(mom, {})
            v = ma.get("pnl_per_weight_day_pct")
            vals.append(f"{v:+.3f}%" if v is not None else "—")
        lines.append(f"| {mom} | {vals[0]} | {vals[1]} | {vals[2]} |")
    lines.append("")

    lines.append("## Daily Return Path")
    lines.append("")
    lines.append("| Date | Current | Tiered | Tier+Exit |")
    lines.append("|------|---------|--------|-----------|")
    for row in result["daily_path"]:
        if abs(row.get("current_day_pct", 0)) > 0.01:
            lines.append(
                f"| {row['date']} | {row['current_cum_pct']:+.2f}% | "
                f"{row['tiered_cum_pct']:+.2f}% | {row['tiered_exit_cum_pct']:+.2f}% |"
            )
    lines.append("")

    lines.append(f"*Generated: {result.get('generated_at', '')}*")
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Backtest tier-weighted policy (Spec 035)")
    parser.add_argument("--a-weights", default="4,2.5,1,0", help="A,B,C,D tier weights")
    parser.add_argument("--exit-persistence", type=int, default=DEFAULT_HEADWIND_EXIT_PERSISTENCE)
    args = parser.parse_args()

    weights = [float(w) for w in args.a_weights.split(",")]
    tier_weights = {"A": weights[0], "B": weights[1], "C": weights[2], "D": weights[3]}

    # Load data
    prices = load_prices(PROJECT_ROOT / "production_data" / "price_history.csv")
    logger.info("Prices: %d tickers", len(prices))

    pos_dir = PROJECT_ROOT / "artifacts" / "live_shadow" / "positions"
    daily_positions = load_positions(pos_dir)
    pos_dates = sorted(daily_positions.keys())
    logger.info("Position dates: %d (%s to %s)", len(pos_dates), pos_dates[0], pos_dates[-1])

    daily_rankings = load_rankings(PROJECT_ROOT / "data" / "snapshots", pos_dates)
    logger.info("Rankings dates: %d", len(daily_rankings))

    # Simulate
    sim = simulate_policies(
        pos_dates, daily_positions, daily_rankings, prices, tier_weights, exit_persistence=args.exit_persistence
    )

    # Format results
    result = format_results(sim, tier_weights, exit_persistence=args.exit_persistence)

    # Write
    out_dir = PROJECT_ROOT / "output" / "research"
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "tier_weighted_policy_compare.json"
    with open(json_path, "w") as f:
        json.dump(result, f, indent=2, default=str)
    logger.info("Wrote %s", json_path)

    md_path = out_dir / "tier_weighted_policy_compare.md"
    md_path.write_text(format_md(result))
    logger.info("Wrote %s", md_path)

    # Summary
    for p, s in result["summary"].items():
        logger.info(
            "%s: cum=%+.2f%%, dd=%.2f%%, turnover=%.1f%%",
            s["label"],
            s["cumulative_return_pct"],
            s["max_drawdown_pct"],
            s["total_turnover_pct"],
        )


if __name__ == "__main__":
    main()
