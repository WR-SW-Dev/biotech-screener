#!/usr/bin/env python3
"""Hedge structure efficacy study using Massive historical option closes.

Compares XBI/IBB hedge structures across 12-24 months of actual option
prices from Massive S3 day aggs. Measures hedged vs unhedged return,
max drawdown reduction, worst-month improvement, regime cost profile,
and historical Greeks at entry.

This is a RESEARCH script — read-only, does not modify production
scoring, ranking, or execution logic.

Usage:
    python scripts/research/hedge_efficacy_study.py
    python scripts/research/hedge_efficacy_study.py --months 24 --etf XBI
    python scripts/research/hedge_efficacy_study.py --output-dir output/hedge_efficacy

Output:
    hedge_efficacy_study.json — full structured results
    hedge_efficacy_study.md  — IC-readable summary
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from common.historical_hedge_backtest import (
    find_nearest_trading_date,
    load_day_aggs_for_date,
    price_structure_historical,
)
from common.options_greeks import compute_historical_greeks

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("hedge_efficacy_study")

TRADING_DAYS_PER_YEAR = 252
DEFAULT_RISK_FREE = 0.05

# Structure definitions: name → (type, offsets)
STRUCTURES = {
    "Straight put 5% OTM": ("straight_put", {"put": -0.05}),
    "Straight put 10% OTM": ("straight_put", {"put": -0.10}),
    "Straight put 15% OTM": ("straight_put", {"put": -0.15}),
    "Put spread 5/15": ("put_spread", {"buy_put": -0.05, "sell_put": -0.15}),
    "Put spread 10/20": ("put_spread", {"buy_put": -0.10, "sell_put": -0.20}),
    "Collar 5% OTM": ("collar", {"put": -0.05, "call": 0.05}),
    "Collar 10% OTM": ("collar", {"put": -0.10, "call": 0.05}),
    "Put ratio 1x2 10/25": ("put_ratio", {"buy_put": -0.10, "sell_put": -0.25}),
}


# ---------------------------------------------------------------------------
# Monthly period generation
# ---------------------------------------------------------------------------


def generate_monthly_periods(
    end_date: str,
    months: int,
    etf_prices: Dict[str, float],
) -> List[Dict[str, Any]]:
    """Generate monthly periods with ETF start/end prices."""
    ref = date.fromisoformat(end_date)
    all_dates = sorted(etf_prices.keys())
    if not all_dates:
        return []

    periods = []
    for m in range(months):
        end_dt = ref - timedelta(days=30 * m)
        start_dt = end_dt - timedelta(days=30)

        # Find nearest trading dates
        start_str = _nearest_date(all_dates, start_dt.isoformat())
        end_str = _nearest_date(all_dates, end_dt.isoformat())
        if not start_str or not end_str or start_str >= end_str:
            continue

        p0 = etf_prices.get(start_str)
        p1 = etf_prices.get(end_str)
        if not p0 or not p1 or p0 <= 0 or p1 <= 0:
            continue

        etf_ret = (p1 - p0) / p0
        periods.append(
            {
                "start_date": start_str,
                "end_date": end_str,
                "etf_start_price": p0,
                "etf_end_price": p1,
                "etf_return": round(etf_ret, 6),
                "days": (date.fromisoformat(end_str) - date.fromisoformat(start_str)).days,
            }
        )

    return list(reversed(periods))


def _nearest_date(sorted_dates: List[str], target: str) -> Optional[str]:
    best = None
    for d in sorted_dates:
        if d <= target:
            best = d
        else:
            break
    return best


# ---------------------------------------------------------------------------
# Per-structure backtest
# ---------------------------------------------------------------------------


def backtest_structure_historical(
    struct_name: str,
    struct_type: str,
    offsets: Dict[str, float],
    etf_ticker: str,
    periods: List[Dict[str, Any]],
    contracts: int = 10,
) -> Dict[str, Any]:
    """Backtest one structure across all periods using historical option closes."""
    results = []
    historical_months = 0
    bs_fallback_months = 0

    for p in periods:
        start_dt = date.fromisoformat(p["start_date"])
        end_dt = date.fromisoformat(p["end_date"])
        etf_start = p["etf_start_price"]
        etf_end = p["etf_end_price"]
        etf_ret = p["etf_return"]
        dte = p["days"]

        # Expiry window
        min_exp = (start_dt + timedelta(days=7)).isoformat()
        max_exp = (start_dt + timedelta(days=60)).isoformat()

        # Load day aggs
        entry_data_dt = find_nearest_trading_date(start_dt, "backward", 5, [etf_ticker])
        exit_data_dt = find_nearest_trading_date(end_dt, "backward", 5, [etf_ticker])

        pricing_source = "bs_fallback"
        hedge_pnl = 0.0
        entry_greeks: Optional[Dict[str, Any]] = None

        if entry_data_dt and exit_data_dt:
            entry_records = load_day_aggs_for_date(entry_data_dt, [etf_ticker])
            exit_records = load_day_aggs_for_date(exit_data_dt, [etf_ticker])

            hist_result = price_structure_historical(
                struct_type,
                offsets,
                etf_start,
                etf_ticker,
                entry_records,
                exit_records,
                min_exp,
                max_exp,
                contracts,
            )

            if hist_result["pricing_source"] in ("historical", "historical_partial"):
                hedge_pnl = hist_result["pnl"]
                pricing_source = hist_result["pricing_source"]
                historical_months += 1

                # Recover entry Greeks from the matched contracts
                entry_greeks = _recover_entry_greeks(
                    hist_result.get("legs", []),
                    etf_start,
                    dte,
                )
            else:
                hedge_pnl = _bs_fallback_pnl(
                    struct_type,
                    offsets,
                    etf_start,
                    etf_end,
                    dte,
                    contracts,
                )
                bs_fallback_months += 1
        else:
            hedge_pnl = _bs_fallback_pnl(
                struct_type,
                offsets,
                etf_start,
                etf_end,
                dte,
                contracts,
            )
            bs_fallback_months += 1

        results.append(
            {
                "start_date": p["start_date"],
                "end_date": p["end_date"],
                "etf_return": etf_ret,
                "hedge_pnl": round(hedge_pnl, 0),
                "pricing_source": pricing_source,
                "entry_greeks": entry_greeks,
            }
        )

    # Compute summary stats
    total_months = len(results)
    if total_months == 0:
        return {"structure": struct_name, "periods": [], "summary": {}}

    hedge_pnls = [r["hedge_pnl"] for r in results]
    etf_rets = [r["etf_return"] for r in results]
    hedge_rets = [r["etf_return"] + r["hedge_pnl"] / (10 * contracts * 100) for r in results]

    # Regime split
    up_months = [r for r in results if r["etf_return"] > 0.03]
    flat_months = [r for r in results if -0.03 <= r["etf_return"] <= 0.03]
    down_months = [r for r in results if r["etf_return"] < -0.03]

    def _avg(vals: List[float]) -> float:
        return sum(vals) / len(vals) if vals else 0

    def _max_dd(rets: List[float]) -> float:
        peak = cum = 1.0
        max_dd = 0.0
        for r in rets:
            cum *= 1 + r
            peak = max(peak, cum)
            max_dd = max(max_dd, (peak - cum) / peak)
        return max_dd

    def _sharpe(rets: List[float]) -> Optional[float]:
        if len(rets) < 3:
            return None
        m = sum(rets) / len(rets)
        v = sum((r - m) ** 2 for r in rets) / len(rets)
        return m / math.sqrt(v) * math.sqrt(12) if v > 0 else None

    summary = {
        "structure": struct_name,
        "type": struct_type,
        "total_months": total_months,
        "historical_months": historical_months,
        "bs_fallback_months": bs_fallback_months,
        "historical_pct": round(historical_months / total_months, 2) if total_months else 0,
        # Returns
        "total_return_unhedged": round(sum(etf_rets), 4),
        "total_return_hedged": round(sum(hedge_rets), 4),
        # Drawdown
        "max_dd_unhedged": round(_max_dd(etf_rets), 4),
        "max_dd_hedged": round(_max_dd(hedge_rets), 4),
        "dd_reduction": round(_max_dd(etf_rets) - _max_dd(hedge_rets), 4),
        # Worst month
        "worst_month_unhedged": round(min(etf_rets), 4),
        "worst_month_hedged": round(min(hedge_rets), 4),
        "worst_month_improvement": round(min(hedge_rets) - min(etf_rets), 4),
        # Sharpe
        "sharpe_unhedged": round(_sharpe(etf_rets), 2) if _sharpe(etf_rets) else None,
        "sharpe_hedged": round(_sharpe(hedge_rets), 2) if _sharpe(hedge_rets) else None,
        # Total hedge P&L
        "total_hedge_pnl": round(sum(hedge_pnls), 0),
        # Regime
        "up_months": len(up_months),
        "up_avg_pnl": round(_avg([r["hedge_pnl"] for r in up_months]), 0),
        "flat_months": len(flat_months),
        "flat_avg_pnl": round(_avg([r["hedge_pnl"] for r in flat_months]), 0),
        "down_months": len(down_months),
        "down_avg_pnl": round(_avg([r["hedge_pnl"] for r in down_months]), 0),
    }

    return {"structure": struct_name, "periods": results, "summary": summary}


def _recover_entry_greeks(
    legs: List[Dict[str, Any]],
    underlying_price: float,
    dte: int,
) -> Optional[Dict[str, Any]]:
    """Recover Greeks from entry option closes using compute_historical_greeks."""
    if not legs:
        return None

    greeks_by_leg = []
    for leg in legs:
        entry_close = leg.get("entry_close")
        strike = leg.get("entry_strike") or leg.get("target_strike")
        if entry_close is None or strike is None or entry_close <= 0:
            continue

        direction = leg.get("direction", "")
        opt_type = "put" if "put" in direction else "call"

        hg = compute_historical_greeks(
            entry_close,
            underlying_price,
            strike,
            dte,
            opt_type,
        )
        greeks_by_leg.append(
            {
                "direction": direction,
                "strike": strike,
                "entry_close": entry_close,
                "implied_vol": hg.get("implied_vol"),
                "delta": hg.get("delta"),
                "gamma": hg.get("gamma"),
                "vega": hg.get("vega"),
                "theta": hg.get("theta"),
            }
        )

    return greeks_by_leg if greeks_by_leg else None


def _bs_fallback_pnl(
    struct_type: str,
    offsets: Dict[str, float],
    etf_start: float,
    etf_end: float,
    dte: int,
    contracts: int,
    sigma: float = 0.30,
) -> float:
    """BS-based PnL fallback."""
    from tools.biotech_hedge_report import _simulate_structure_pnl

    T = dte / 365.0
    return _simulate_structure_pnl(
        struct_type,
        offsets,
        etf_start,
        etf_end,
        T,
        sigma,
        0,
        contracts,
    )


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def generate_markdown(
    results: List[Dict[str, Any]],
    etf_ticker: str,
    months: int,
    as_of_date: str,
) -> str:
    """Generate IC-readable markdown summary."""
    lines = [
        f"# Hedge Structure Efficacy Study — {etf_ticker}",
        "",
        f"*{months}-month backtest ending {as_of_date}, " "Massive historical option closes*",
        "",
    ]

    # Main comparison table
    lines.append("## Structure Comparison\n")
    lines.append(
        "| Structure | Hedged Return | Max DD | DD Reduction | Worst Month | "
        "Down-Month Avg P&L | Total Hedge P&L | Hist Coverage | Sharpe |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|")

    # Sort by DD reduction (best first)
    sorted_results = sorted(
        results,
        key=lambda r: -(r["summary"].get("dd_reduction", 0)),
    )

    for r in sorted_results:
        s = r["summary"]
        sh = s.get("sharpe_hedged")
        sh_str = f"{sh:.2f}" if sh else "N/A"
        lines.append(
            f"| {s['structure']} "
            f"| {s['total_return_hedged']:.2%} "
            f"| {s['max_dd_hedged']:.2%} "
            f"| {s['dd_reduction']:+.2%} "
            f"| {s['worst_month_hedged']:.2%} "
            f"| ${s['down_avg_pnl']:,.0f} "
            f"| ${s['total_hedge_pnl']:,.0f} "
            f"| {s['historical_pct']:.0%} "
            f"| {sh_str} |"
        )
    lines.append("")

    # Unhedged baseline
    if sorted_results:
        s0 = sorted_results[0]["summary"]
        baseline = (
            "**Unhedged baseline**: "
            f"return={s0['total_return_unhedged']:.2%}, "
            f"max DD={s0['max_dd_unhedged']:.2%}, "
            f"worst month={s0['worst_month_unhedged']:.2%}"
        )
        lines.append(baseline)
        lines.append("")

    # Regime breakdown for top 3
    lines.append("## Regime Cost Profile (top 3 by DD reduction)\n")
    lines.append("| Structure | Up months (avg P&L) | Flat months (avg P&L) | Down months (avg P&L) |")
    lines.append("|---|---|---|---|")
    for r in sorted_results[:3]:
        s = r["summary"]
        lines.append(
            f"| {s['structure']} "
            f"| {s['up_months']} (${s['up_avg_pnl']:,.0f}) "
            f"| {s['flat_months']} (${s['flat_avg_pnl']:,.0f}) "
            f"| {s['down_months']} (${s['down_avg_pnl']:,.0f}) |"
        )
    lines.append("")

    # Historical Greeks summary for top structure
    top = sorted_results[0] if sorted_results else None
    if top:
        greeks_periods = [p for p in top["periods"] if p.get("entry_greeks") and p["etf_return"] < -0.03]
        if greeks_periods:
            lines.append("## Entry Greeks in Down Months (top structure)\n")
            lines.append("| Period | Entry IV | Entry Delta | Entry Vega | Hedge P&L |")
            lines.append("|---|---|---|---|---|")
            for p in greeks_periods:
                gl = p["entry_greeks"]
                if gl:
                    # Aggregate across legs
                    avg_iv = _avg_greek(gl, "implied_vol")
                    total_delta = sum(g.get("delta", 0) or 0 for g in gl)
                    total_vega = sum(g.get("vega", 0) or 0 for g in gl)
                    lines.append(
                        f"| {p['start_date']} to {p['end_date']} " f"| {avg_iv:.1%} "
                        if avg_iv
                        else "| N/A " f"| {total_delta:.3f} " f"| {total_vega:.4f} " f"| ${p['hedge_pnl']:,.0f} |"
                    )
            lines.append("")

    # Caveats
    lines.append("## Caveats\n")
    lines.append("- Pricing: Massive S3 day-agg option closes (OPRA flat files)")
    lines.append("- BS fallback when historical contract print missing")
    lines.append("- Monthly rebalance, no transaction costs")
    lines.append("- 10 contracts per structure (not beta-adjusted)")
    lines.append("- This study is for IC discussion, not execution")
    lines.append("")

    return "\n".join(lines)


def _avg_greek(legs: List[Dict], field: str) -> Optional[float]:
    vals = [g.get(field) for g in legs if g.get(field) is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run_study(
    etf_ticker: str,
    months: int,
    as_of_date: str,
    price_csv: Path,
    output_dir: Path,
    contracts: int = 10,
) -> Dict[str, Any]:
    """Run the full hedge efficacy study."""
    logger.info("=== Hedge Efficacy Study — %s, %d months ===", etf_ticker, months)

    # Load ETF prices
    import csv

    etf_prices: Dict[str, float] = {}
    with open(price_csv, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("ticker", "").strip() == etf_ticker:
                try:
                    etf_prices[row["date"]] = float(row["close"])
                except (ValueError, KeyError):
                    pass
    logger.info("Loaded %d price days for %s", len(etf_prices), etf_ticker)

    # Generate monthly periods
    periods = generate_monthly_periods(as_of_date, months, etf_prices)
    logger.info("Generated %d monthly periods", len(periods))

    # Backtest each structure
    all_results = []
    for name, (stype, offsets) in STRUCTURES.items():
        logger.info("  Backtesting: %s", name)
        result = backtest_structure_historical(
            name,
            stype,
            offsets,
            etf_ticker,
            periods,
            contracts,
        )
        s = result.get("summary", {})
        logger.info(
            "    %d/%d historical, DD reduction=%s, down-month avg=$%s",
            s.get("historical_months", 0),
            s.get("total_months", 0),
            f"{s.get('dd_reduction', 0):+.2%}",
            f"{s.get('down_avg_pnl', 0):,.0f}",
        )
        all_results.append(result)

    # Write outputs
    output_dir.mkdir(parents=True, exist_ok=True)

    study_data = {
        "schema": "hedge_efficacy_study.v1",
        "etf_ticker": etf_ticker,
        "months": months,
        "as_of_date": as_of_date,
        "contracts": contracts,
        "n_periods": len(periods),
        "structures": [r["summary"] for r in all_results],
        "periods": periods,
    }

    json_path = output_dir / "hedge_efficacy_study.json"
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".json",
        dir=str(output_dir),
        delete=False,
    ) as tmp:
        json.dump(study_data, tmp, indent=2, default=str)
        tmp_name = tmp.name
    os.replace(tmp_name, str(json_path))

    md_content = generate_markdown(all_results, etf_ticker, months, as_of_date)
    md_path = output_dir / "hedge_efficacy_study.md"
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".md",
        dir=str(output_dir),
        delete=False,
    ) as tmp:
        tmp.write(md_content)
        tmp_name = tmp.name
    os.replace(tmp_name, str(md_path))

    logger.info("Wrote %s", json_path)
    logger.info("Wrote %s", md_path)

    # Print top-line summary
    sorted_by_dd = sorted(
        all_results,
        key=lambda r: -(r["summary"].get("dd_reduction", 0)),
    )
    if sorted_by_dd:
        best = sorted_by_dd[0]["summary"]
        logger.info(
            "\n=== BEST BY DD REDUCTION: %s — DD reduction %s, " "down-month avg P&L $%s ===",
            best["structure"],
            f"{best['dd_reduction']:+.2%}",
            f"{best['down_avg_pnl']:,.0f}",
        )

    return study_data


def run_rolling_study(
    etf_ticker: str,
    total_months: int,
    window_sizes: List[int],
    as_of_date: str,
    price_csv: Path,
    output_dir: Path,
    contracts: int = 10,
) -> Dict[str, Any]:
    """Run rolling-window hedge efficacy study.

    For each window size, slides across the total period and backtests
    all structures on each subwindow.  Reports per-window winners and
    cross-window stability.
    """
    import csv as _csv

    logger.info(
        "=== Rolling Hedge Efficacy — %s, %dm total, windows=%s ===",
        etf_ticker,
        total_months,
        window_sizes,
    )

    etf_prices: Dict[str, float] = {}
    with open(price_csv, newline="", encoding="utf-8") as f:
        for row in _csv.DictReader(f):
            if row.get("ticker", "").strip() == etf_ticker:
                try:
                    etf_prices[row["date"]] = float(row["close"])
                except (ValueError, KeyError):
                    pass

    # Generate all monthly periods for the full window
    all_periods = generate_monthly_periods(as_of_date, total_months, etf_prices)
    logger.info("Full period: %d months", len(all_periods))

    rolling_results: Dict[int, List[Dict[str, Any]]] = {}

    for win in window_sizes:
        if win > len(all_periods):
            logger.info("  Window %dm: skipped (only %d periods)", win, len(all_periods))
            continue

        windows = []
        for start_idx in range(len(all_periods) - win + 1):
            window_periods = all_periods[start_idx : start_idx + win]
            window_label = f"{window_periods[0]['start_date']}_to_{window_periods[-1]['end_date']}"

            # Backtest each structure on this window
            window_winners: Dict[str, Any] = {"label": window_label, "n_months": len(window_periods)}
            best_dd_name = ""
            best_dd_val = 1.0

            for name, (stype, offsets) in STRUCTURES.items():
                result = backtest_structure_historical(
                    name,
                    stype,
                    offsets,
                    etf_ticker,
                    window_periods,
                    contracts,
                )
                s = result.get("summary", {})
                dd_hedged = s.get("max_dd_hedged", 1.0)
                if dd_hedged < best_dd_val:
                    best_dd_val = dd_hedged
                    best_dd_name = name
                window_winners[name] = {
                    "dd_reduction": s.get("dd_reduction", 0),
                    "max_dd_hedged": dd_hedged,
                    "down_avg_pnl": s.get("down_avg_pnl", 0),
                    "total_hedge_pnl": s.get("total_hedge_pnl", 0),
                    "historical_pct": s.get("historical_pct", 0),
                }

            window_winners["efficacy_winner"] = best_dd_name
            windows.append(window_winners)

        rolling_results[win] = windows
        # Count how often each structure wins
        win_counts: Dict[str, int] = {}
        for w in windows:
            winner = w.get("efficacy_winner", "")
            win_counts[winner] = win_counts.get(winner, 0) + 1
        logger.info(
            "  Window %dm: %d subwindows, winner counts: %s",
            win,
            len(windows),
            ", ".join(f"{k}={v}" for k, v in sorted(win_counts.items(), key=lambda x: -x[1])),
        )

    # Write outputs
    output_dir.mkdir(parents=True, exist_ok=True)

    study_data = {
        "schema": "hedge_efficacy_rolling.v1",
        "etf_ticker": etf_ticker,
        "total_months": total_months,
        "window_sizes": window_sizes,
        "as_of_date": as_of_date,
        "n_full_periods": len(all_periods),
        "rolling_results": {str(k): v for k, v in rolling_results.items()},
    }

    json_path = output_dir / "hedge_efficacy_rolling.json"
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".json",
        dir=str(output_dir),
        delete=False,
    ) as tmp:
        json.dump(study_data, tmp, indent=2, default=str)
        tmp_name = tmp.name
    os.replace(tmp_name, str(json_path))

    # Markdown summary
    lines = [
        f"# Rolling Hedge Efficacy — {etf_ticker}",
        "",
        f"*{total_months}-month total, windows={window_sizes}, ending {as_of_date}*",
        "",
    ]

    for win in window_sizes:
        windows = rolling_results.get(win, [])
        if not windows:
            continue

        # Winner frequency
        win_counts = {}
        for w in windows:
            winner = w.get("efficacy_winner", "")
            win_counts[winner] = win_counts.get(winner, 0) + 1

        lines.append(f"## {win}-Month Rolling Windows ({len(windows)} subwindows)\n")
        lines.append("### Winner Frequency\n")
        lines.append("| Structure | Windows Won | Win Rate |")
        lines.append("|---|---|---|")
        for name, count in sorted(win_counts.items(), key=lambda x: -x[1]):
            pct = count / len(windows) if windows else 0
            lines.append(f"| {name} | {count} | {pct:.0%} |")
        lines.append("")

        # Per-structure average DD reduction across windows
        lines.append("### Average DD Reduction Across Windows\n")
        lines.append("| Structure | Avg DD Reduction | Avg Down-Month P&L | Avg Historical Coverage |")
        lines.append("|---|---|---|---|")
        for name in STRUCTURES:
            dd_vals = [w.get(name, {}).get("dd_reduction", 0) for w in windows]
            pnl_vals = [w.get(name, {}).get("down_avg_pnl", 0) for w in windows]
            cov_vals = [w.get(name, {}).get("historical_pct", 0) for w in windows]
            avg_dd = sum(dd_vals) / len(dd_vals) if dd_vals else 0
            avg_pnl = sum(pnl_vals) / len(pnl_vals) if pnl_vals else 0
            avg_cov = sum(cov_vals) / len(cov_vals) if cov_vals else 0
            lines.append(f"| {name} | {avg_dd:+.2%} | ${avg_pnl:,.0f} | {avg_cov:.0%} |")
        lines.append("")

    lines.append("## Caveats\n")
    lines.append("- Massive S3 day-agg option closes, BS fallback when missing")
    lines.append("- Monthly rebalance, no transaction costs")
    lines.append("- Rolling windows overlap; not independent samples")
    lines.append("")

    md_path = output_dir / "hedge_efficacy_rolling.md"
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".md",
        dir=str(output_dir),
        delete=False,
    ) as tmp:
        tmp.write("\n".join(lines))
        tmp_name = tmp.name
    os.replace(tmp_name, str(md_path))

    logger.info("Wrote %s", json_path)
    logger.info("Wrote %s", md_path)

    return study_data


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Hedge structure efficacy study using Massive historical options",
    )
    parser.add_argument("--etf", type=str, default="XBI", help="ETF ticker (XBI or IBB)")
    parser.add_argument("--months", type=int, default=12, help="Backtest months")
    parser.add_argument(
        "--as-of-date",
        type=str,
        default=date.today().isoformat(),
        help="End date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--price-csv",
        type=Path,
        default=PROJECT_ROOT / "production_data" / "price_history.csv",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "output" / "hedge_efficacy",
    )
    parser.add_argument("--contracts", type=int, default=10)
    parser.add_argument(
        "--rolling",
        action="store_true",
        help="Run rolling-window study instead of point-in-time",
    )
    parser.add_argument(
        "--windows",
        type=str,
        default="6,12",
        help="Rolling window sizes in months (comma-separated)",
    )
    args = parser.parse_args()

    if args.rolling:
        window_sizes = [int(w.strip()) for w in args.windows.split(",")]
        run_rolling_study(
            etf_ticker=args.etf,
            total_months=args.months,
            window_sizes=window_sizes,
            as_of_date=args.as_of_date,
            price_csv=args.price_csv,
            output_dir=args.output_dir,
            contracts=args.contracts,
        )
        return 0

    run_study(
        etf_ticker=args.etf,
        months=args.months,
        as_of_date=args.as_of_date,
        price_csv=args.price_csv,
        output_dir=args.output_dir,
        contracts=args.contracts,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
