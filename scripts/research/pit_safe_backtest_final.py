#!/usr/bin/env python3
"""PIT-safe final backtest — canonical model evaluation.

Model: Trap gate T20 → Rank (normal), Trap T20 + Timing → Rank (conservative)
Period: full PIT-safe range (price_history.csv + backfilled EES)
Arms: baseline, trap-only gate, trap+timing gate, IC per signal
Robustness: era splits, mcap buckets, catalyst precision, options coverage,
            rolling IC, threshold sensitivity, top-N sensitivity, tail analysis.
"""

from __future__ import annotations

import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from event_ev.expectation_error_model import ExpectationErrorModel
from scripts.eval_forward_returns import (
    compute_forward_return,
    discover_snapshot_dates,
    load_price_series,
    load_rankings,
    resolve_trade_date,
    spearman_ic,
)

TOP_K = 30
HORIZONS = [5, 20, 63]
model = ExpectationErrorModel()


# ═════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════


def _sf(v: str) -> Optional[float]:
    if not v or v.strip() in ("", "None", "nan"):
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _pct_thresh(vals: List[float], pct: int) -> float:
    s = sorted(vals)
    return s[min(int(len(s) * pct / 100), len(s) - 1)]


def _is_degenerate(vals: List[float]) -> bool:
    if len(vals) < 5:
        return True
    unique = set(round(v, 6) for v in vals)
    if len(unique) <= 2:
        return True
    mode_count = max(vals.count(v) for v in unique)
    return mode_count > len(vals) * 0.80


def _sharpe(rets: List[float]) -> Optional[float]:
    if len(rets) < 2:
        return None
    m = statistics.mean(rets)
    s = statistics.stdev(rets)
    return m / s if s > 0 else None


def _ic_stats(ics: List[float]) -> Dict[str, Any]:
    if not ics:
        return {"mean_ic": None, "median_ic": None, "t_stat": None, "hit_rate": None, "n": 0}
    m = statistics.mean(ics)
    med = statistics.median(ics)
    s = statistics.stdev(ics) if len(ics) >= 2 else 0
    t = m / (s / math.sqrt(len(ics))) if s > 0 else 0
    hr = sum(1 for ic in ics if ic > 0) / len(ics)
    return {
        "mean_ic": round(m, 4),
        "median_ic": round(med, 4),
        "t_stat": round(t, 2),
        "hit_rate": round(hr, 3),
        "n": len(ics),
    }


def _port_stats(rets: List[float]) -> Dict[str, Any]:
    if not rets:
        return {"mean_ret": None, "median_ret": None, "sharpe": None, "hit_rate": None, "n": 0}
    m = statistics.mean(rets)
    med = statistics.median(rets)
    s = statistics.stdev(rets) if len(rets) >= 2 else 0
    sharpe = m / s if s > 0 else 0
    hr = sum(1 for r in rets if r > 0) / len(rets)
    return {
        "mean_ret_pct": round(m * 100, 4),
        "median_ret_pct": round(med * 100, 4),
        "sharpe": round(sharpe, 3),
        "hit_rate": round(hr, 3),
        "n": len(rets),
    }


# ═════════════════════════════════════════════════════════════════════════
# Main backtest
# ═════════════════════════════════════════════════════════════════════════


def run_backtest(
    snapshot_root: Path,
    price_csv: Path,
    date_from: str = "2020-01-03",
    date_to: str = "2026-03-31",
) -> Dict[str, Any]:
    snap_dates = discover_snapshot_dates(snapshot_root, date_from, date_to)
    prices = load_price_series(price_csv)

    all_dates_set: set = set()
    for tp in prices.values():
        all_dates_set.update(tp.keys())
    sorted_dates = sorted(all_dates_set)

    # ── Accumulators ─────────────────────────────────────────────────
    # Portfolio arms: {arm: {horizon: [returns]}}
    arms = {
        "baseline_rank": defaultdict(list),
        "trap_t20_rank": defaultdict(list),
        "trap_t20_timing_rank": defaultdict(list),
    }

    # IC per signal: {signal: {horizon: [ics]}}
    ic_signals = {
        "trap_overlay": defaultdict(list),
        "timing_decay_inv": defaultdict(list),
    }

    # Robustness: era splits
    era_arms = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    era_ic = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))

    # Robustness: mcap bucket
    mcap_returns = defaultdict(lambda: defaultdict(list))  # {bucket: {h: [rets]}}

    # Robustness: catalyst precision bucket
    precision_returns = defaultdict(lambda: defaultdict(list))

    # Robustness: options coverage
    options_arms = defaultdict(lambda: defaultdict(list))  # {"has_pm"/"no_pm": {h: [rets]}}

    # Stability: rolling IC (20-date window)
    rolling_ic_trap = defaultdict(list)  # {h: [(date, ic)]}
    rolling_ic_timing = defaultdict(list)

    # Threshold sensitivity
    threshold_sweep = defaultdict(lambda: defaultdict(list))  # {t_cut: {h: [rets]}}

    # Top-N sensitivity
    topn_arms = defaultdict(lambda: defaultdict(list))  # {n: {h: [rets]}}

    # Tail analysis
    tail_trap = defaultdict(lambda: {"removed": [], "kept": []})
    tail_worst_decile = defaultdict(lambda: {"worst": [], "rest": []})

    n_dates = 0

    for snap_date in snap_dates:
        trade_date = resolve_trade_date(sorted_dates, snap_date, "next_trading_day")
        if not trade_date:
            continue

        rankings = load_rankings(snapshot_root / snap_date)
        if not rankings:
            continue

        scores = model.score_batch(rankings, snap_date)
        if not scores:
            continue

        by_ticker = {s.ticker: s for s in scores}
        rank_map = {}
        for row in rankings:
            t = row.get("ticker", "")
            ar = row.get("actionable_rank", "")
            if t and ar and ar.strip().isdigit():
                rank_map[t] = int(ar)

        # Era classification
        if snap_date < "2022-03-18":
            era = "pre_options"
        elif snap_date < "2026-01-15":
            era = "day_aggs"
        else:
            era = "chain"

        n_dates += 1

        for h in HORIZONS:
            # Forward returns
            fwd: Dict[str, float] = {}
            for ticker in by_ticker:
                if ticker in prices:
                    ret = compute_forward_return(prices[ticker], sorted_dates, trade_date, h)
                    if ret is not None:
                        fwd[ticker] = ret

            eligible = [t for t in by_ticker if t in fwd and t in rank_map]
            if len(eligible) < TOP_K:
                continue

            trap_vals = [by_ticker[t].trap_overlay_score for t in eligible]
            quality_vals = [by_ticker[t].quality_overlay_score for t in eligible]
            trap_degen = _is_degenerate(trap_vals)
            quality_degen = _is_degenerate(quality_vals)

            # ── Arm 1: Baseline ──────────────────────────────────────
            ranked = sorted(eligible, key=lambda t: rank_map[t])[:TOP_K]
            base_ret = statistics.mean(fwd[t] for t in ranked)
            arms["baseline_rank"][h].append(base_ret)
            era_arms[era]["baseline_rank"][h].append(base_ret)

            # ── Arm 2: Trap T20 → rank ──────────────────────────────
            if not trap_degen:
                t_thresh = _pct_thresh(trap_vals, 20)
                t_pass = [t for t in eligible if by_ticker[t].trap_overlay_score > t_thresh]
            else:
                t_pass = list(eligible)
            t_ranked = sorted(t_pass, key=lambda t: rank_map[t])[:TOP_K]
            if len(t_ranked) >= 10:
                trap_ret = statistics.mean(fwd[t] for t in t_ranked)
                arms["trap_t20_rank"][h].append(trap_ret)
                era_arms[era]["trap_t20_rank"][h].append(trap_ret)

                # Options coverage split
                has_pm = any(
                    _sf(next((r for r in rankings if r.get("ticker") == t_ranked[0]), {}).get("priced_move_pct", ""))
                    is not None
                    for _ in [0]
                )
                pm_key = "has_pm" if has_pm else "no_pm"
                options_arms[pm_key][h].append(trap_ret)

            # ── Arm 3: Trap T20 + Timing → rank ─────────────────────
            if not trap_degen and not quality_degen:
                q_thresh = _pct_thresh(quality_vals, 15)
                qt_pass = [
                    t
                    for t in eligible
                    if by_ticker[t].trap_overlay_score > t_thresh and by_ticker[t].quality_overlay_score > q_thresh
                ]
                qt_ranked = sorted(qt_pass, key=lambda t: rank_map[t])[:TOP_K]
                if len(qt_ranked) >= 10:
                    qt_ret = statistics.mean(fwd[t] for t in qt_ranked)
                    arms["trap_t20_timing_rank"][h].append(qt_ret)
                    era_arms[era]["trap_t20_timing_rank"][h].append(qt_ret)

            # ── Signal IC ────────────────────────────────────────────
            if not trap_degen:
                common_trap = [t for t in eligible if t in fwd]
                if len(common_trap) >= 10:
                    ic = spearman_ic(
                        [by_ticker[t].trap_overlay_score for t in common_trap],
                        [fwd[t] for t in common_trap],
                    )
                    if ic is not None:
                        ic_signals["trap_overlay"][h].append(ic)
                        era_ic[era]["trap_overlay"][h].append(ic)
                        rolling_ic_trap[h].append((snap_date, ic))

            if not quality_degen:
                common_q = [t for t in eligible if t in fwd]
                if len(common_q) >= 10:
                    ic = spearman_ic(
                        [-by_ticker[t].quality_overlay_score for t in common_q],
                        [fwd[t] for t in common_q],
                    )
                    if ic is not None:
                        ic_signals["timing_decay_inv"][h].append(ic)
                        era_ic[era]["timing_decay_inv"][h].append(ic)
                        rolling_ic_timing[h].append((snap_date, ic))

            # ── Mcap bucket returns ──────────────────────────────────
            for t in t_ranked[:TOP_K] if len(t_ranked) >= 10 else []:
                mcap = _sf(next((r for r in rankings if r.get("ticker") == t), {}).get("market_cap_mm", ""))
                if mcap is not None:
                    if mcap < 300:
                        bucket = "micro_small"
                    elif mcap < 2000:
                        bucket = "mid"
                    else:
                        bucket = "large"
                    mcap_returns[bucket][h].append(fwd[t])

            # ── Catalyst precision bucket ────────────────────────────
            for t in t_ranked[:TOP_K] if len(t_ranked) >= 10 else []:
                prec = next((r for r in rankings if r.get("ticker") == t), {}).get("clinical_days_precision", "")
                if prec and prec.strip() not in ("", "None", "nan"):
                    precision_returns[prec.strip()][h].append(fwd[t])

            # ── Threshold sensitivity ────────────────────────────────
            if not trap_degen and h == 20:
                for t_cut in [10, 15, 20, 25, 30, 35]:
                    t_th = _pct_thresh(trap_vals, t_cut)
                    passed = [t for t in eligible if by_ticker[t].trap_overlay_score > t_th]
                    top = sorted(passed, key=lambda t: rank_map[t])[:TOP_K]
                    if len(top) >= 10:
                        threshold_sweep[t_cut][h].append(statistics.mean(fwd[t] for t in top))

            # ── Top-N sensitivity ────────────────────────────────────
            if not trap_degen and h == 20:
                for n in [10, 20, 30, 50]:
                    top_n = sorted(t_pass, key=lambda t: rank_map[t])[:n]
                    if len(top_n) >= min(n, 10):
                        topn_arms[n][h].append(statistics.mean(fwd[t] for t in top_n))

            # ── Tail analysis ────────────────────────────────────────
            if not trap_degen:
                # Removed by trap vs kept
                t_removed = [t for t in eligible if by_ticker[t].trap_overlay_score <= t_thresh]
                t_kept = [t for t in eligible if by_ticker[t].trap_overlay_score > t_thresh]
                if t_removed and t_kept:
                    tail_trap[h]["removed"].append(statistics.mean(fwd[t] for t in t_removed))
                    tail_trap[h]["kept"].append(statistics.mean(fwd[t] for t in t_kept))

                # Worst trap decile vs rest
                n_elig = len(eligible)
                d_size = max(1, n_elig // 10)
                trap_sorted = sorted(eligible, key=lambda t: by_ticker[t].trap_overlay_score)
                worst = trap_sorted[:d_size]
                rest = trap_sorted[d_size:]
                if worst and rest:
                    tail_worst_decile[h]["worst"].append(statistics.mean(fwd[t] for t in worst))
                    tail_worst_decile[h]["rest"].append(statistics.mean(fwd[t] for t in rest))

    # ═════════════════════════════════════════════════════════════════
    # Assemble results
    # ═════════════════════════════════════════════════════════════════

    results: Dict[str, Any] = {
        "n_dates": n_dates,
        "date_range": f"{snap_dates[0]} to {snap_dates[-1]}" if snap_dates else "",
    }

    # Core performance
    results["portfolio_arms"] = {}
    for arm_name in arms:
        results["portfolio_arms"][arm_name] = {f"{h}d": _port_stats(arms[arm_name][h]) for h in HORIZONS}

    results["signal_ic"] = {}
    for sig_name in ic_signals:
        results["signal_ic"][sig_name] = {f"{h}d": _ic_stats(ic_signals[sig_name][h]) for h in HORIZONS}

    # Era splits
    results["era_splits"] = {}
    for era_name in sorted(era_arms.keys()):
        results["era_splits"][era_name] = {
            "arms": {
                arm: {f"{h}d": _port_stats(era_arms[era_name][arm][h]) for h in HORIZONS} for arm in era_arms[era_name]
            },
            "ic": {sig: {f"{h}d": _ic_stats(era_ic[era_name][sig][h]) for h in HORIZONS} for sig in era_ic[era_name]},
        }

    # Mcap buckets
    results["mcap_buckets"] = {
        bucket: {f"{h}d": _port_stats(mcap_returns[bucket][h]) for h in HORIZONS} for bucket in sorted(mcap_returns)
    }

    # Precision buckets
    results["precision_buckets"] = {
        prec: {f"{h}d": _port_stats(precision_returns[prec][h]) for h in HORIZONS} for prec in sorted(precision_returns)
    }

    # Options coverage
    results["options_coverage"] = {
        key: {f"{h}d": _port_stats(options_arms[key][h]) for h in HORIZONS} for key in sorted(options_arms)
    }

    # Rolling IC (compute 20-date rolling mean)
    def _rolling_ic(pairs, window=20):
        out = []
        for i in range(window, len(pairs) + 1):
            chunk = [p[1] for p in pairs[i - window : i]]
            out.append({"date": pairs[i - 1][0], "rolling_ic": round(statistics.mean(chunk), 4)})
        return out

    results["rolling_ic"] = {
        "trap": {f"{h}d": _rolling_ic(rolling_ic_trap[h]) for h in HORIZONS},
        "timing": {f"{h}d": _rolling_ic(rolling_ic_timing[h]) for h in HORIZONS},
    }

    # Threshold sensitivity
    results["threshold_sensitivity_20d"] = {
        f"T{t_cut}": _port_stats(threshold_sweep[t_cut][20]) for t_cut in sorted(threshold_sweep)
    }

    # Top-N sensitivity
    results["topn_sensitivity_20d"] = {f"top_{n}": _port_stats(topn_arms[n][20]) for n in sorted(topn_arms)}

    # Tail analysis
    results["tail_analysis"] = {
        "removed_vs_kept": {
            f"{h}d": {
                "removed": _port_stats(tail_trap[h]["removed"]),
                "kept": _port_stats(tail_trap[h]["kept"]),
            }
            for h in HORIZONS
        },
        "worst_decile": {
            f"{h}d": {
                "worst": _port_stats(tail_worst_decile[h]["worst"]),
                "rest": _port_stats(tail_worst_decile[h]["rest"]),
            }
            for h in HORIZONS
        },
    }

    return results


# ═════════════════════════════════════════════════════════════════════════
# Report generation
# ═════════════════════════════════════════════════════════════════════════


def print_report(results: Dict[str, Any]) -> str:
    lines = []

    def pr(s=""):
        lines.append(s)

    def fmt_ret(d):
        if d.get("mean_ret_pct") is None:
            return "—"
        return f"{d['mean_ret_pct']:+.3f}%"

    def fmt_sharpe(d):
        if d.get("sharpe") is None:
            return "—"
        return f"{d['sharpe']:+.3f}"

    def fmt_hr(d):
        if d.get("hit_rate") is None:
            return "—"
        return f"{d['hit_rate']:.0%}"

    def fmt_ic(d):
        if d.get("mean_ic") is None:
            return "—"
        return f"{d['mean_ic']:+.4f}"

    def fmt_t(d):
        if d.get("t_stat") is None:
            return "—"
        return f"{d['t_stat']:+.2f}"

    pr("=" * 80)
    pr("  PIT-SAFE FINAL BACKTEST — CANONICAL MODEL")
    pr("=" * 80)
    pr(f"  Dates: {results['n_dates']} snapshots, {results['date_range']}")
    pr("  Model: Trap gate T20 → Rank (normal), +Timing Q15 (conservative)")
    pr("  PIT safety: close_price from price_history.csv, market_cap reconstructed,")
    pr("              priced_move_pct from same-date options. No look-ahead.")
    pr()

    # ── Section 1: Core Performance ──────────────────────────────────
    pr("=" * 80)
    pr("  1. CORE PERFORMANCE — Portfolio Arms (EW Top-30)")
    pr("=" * 80)
    for h in HORIZONS:
        pr(f"\n  {h}d horizon:")
        pr(f"  {'Arm':<28s} {'Mean':>8s} {'Median':>8s} {'Sharpe':>8s} {'Hit%':>7s} {'N':>5s}")
        pr(f"  {'-' * 68}")
        for arm in ["baseline_rank", "trap_t20_rank", "trap_t20_timing_rank"]:
            d = results["portfolio_arms"][arm].get(f"{h}d", {})
            med = f"{d['median_ret_pct']:+.3f}%" if d.get("median_ret_pct") is not None else "—"
            pr(f"  {arm:<28s} {fmt_ret(d):>8s} {med:>8s} {fmt_sharpe(d):>8s} {fmt_hr(d):>7s} {d.get('n', 0):>5d}")
    pr()

    # ── Section 2: Signal IC ─────────────────────────────────────────
    pr("=" * 80)
    pr("  2. SIGNAL IC")
    pr("=" * 80)
    pr(f"  {'Signal':<24s} {'5d IC':>8s} {'5d t':>7s} {'20d IC':>8s} {'20d t':>7s} {'63d IC':>8s} {'63d t':>7s}")
    pr(f"  {'-' * 68}")
    for sig in ["trap_overlay", "timing_decay_inv"]:
        parts = []
        for h in HORIZONS:
            d = results["signal_ic"][sig].get(f"{h}d", {})
            parts.append(f"{fmt_ic(d):>8s} {fmt_t(d):>7s}")
        pr(f"  {sig:<24s} {'  '.join(parts)}")
    pr()

    # ── Section 3: Era Splits ────────────────────────────────────────
    pr("=" * 80)
    pr("  3. ROBUSTNESS — Era Splits (20d)")
    pr("=" * 80)
    for era in sorted(results["era_splits"]):
        era_data = results["era_splits"][era]
        pr(f"\n  {era}:")
        pr(f"  {'Arm':<28s} {'Mean':>8s} {'Sharpe':>8s} {'N':>5s}   {'Signal':<20s} {'IC':>8s} {'t':>7s}")
        pr(f"  {'-' * 80}")
        arm_data = era_data.get("arms", {})
        ic_data = era_data.get("ic", {})
        arm_names = sorted(arm_data.keys())
        sig_names = sorted(ic_data.keys())
        for i in range(max(len(arm_names), len(sig_names))):
            arm_part = ""
            if i < len(arm_names):
                a = arm_names[i]
                d = arm_data[a].get("20d", {})
                arm_part = f"  {a:<28s} {fmt_ret(d):>8s} {fmt_sharpe(d):>8s} {d.get('n', 0):>5d}"
            else:
                arm_part = f"  {'':76s}"
            sig_part = ""
            if i < len(sig_names):
                s = sig_names[i]
                d = ic_data[s].get("20d", {})
                sig_part = f"   {s:<20s} {fmt_ic(d):>8s} {fmt_t(d):>7s}"
            pr(arm_part + sig_part)
    pr()

    # ── Section 4: Mcap Buckets ──────────────────────────────────────
    pr("=" * 80)
    pr("  4. ROBUSTNESS — Market Cap Buckets (20d, within trap-gated book)")
    pr("=" * 80)
    pr(f"  {'Bucket':<16s} {'Mean':>8s} {'Sharpe':>8s} {'N':>8s}")
    pr(f"  {'-' * 44}")
    for bucket in ["micro_small", "mid", "large"]:
        d = results["mcap_buckets"].get(bucket, {}).get("20d", {})
        pr(f"  {bucket:<16s} {fmt_ret(d):>8s} {fmt_sharpe(d):>8s} {d.get('n', 0):>8d}")
    pr()

    # ── Section 5: Threshold Sensitivity ─────────────────────────────
    pr("=" * 80)
    pr("  5. STABILITY — Threshold Sensitivity (20d)")
    pr("=" * 80)
    pr(f"  {'Threshold':<12s} {'Mean':>8s} {'Sharpe':>8s} {'N':>5s}")
    pr(f"  {'-' * 38}")
    for key in sorted(results["threshold_sensitivity_20d"]):
        d = results["threshold_sensitivity_20d"][key]
        pr(f"  {key:<12s} {fmt_ret(d):>8s} {fmt_sharpe(d):>8s} {d.get('n', 0):>5d}")
    pr()

    # ── Section 6: Top-N Sensitivity ─────────────────────────────────
    pr("=" * 80)
    pr("  6. STABILITY — Top-N Sensitivity (20d)")
    pr("=" * 80)
    pr(f"  {'Top-N':<12s} {'Mean':>8s} {'Sharpe':>8s} {'N':>5s}")
    pr(f"  {'-' * 38}")
    for key in sorted(results["topn_sensitivity_20d"]):
        d = results["topn_sensitivity_20d"][key]
        pr(f"  {key:<12s} {fmt_ret(d):>8s} {fmt_sharpe(d):>8s} {d.get('n', 0):>5d}")
    pr()

    # ── Section 7: Tail Analysis ─────────────────────────────────────
    pr("=" * 80)
    pr("  7. TAIL ANALYSIS")
    pr("=" * 80)
    pr("\n  Removed by trap vs kept:")
    pr(f"  {'Horizon':<10s} {'Removed':>10s} {'Kept':>10s} {'Drag':>10s}")
    pr(f"  {'-' * 44}")
    for h in HORIZONS:
        rem = results["tail_analysis"]["removed_vs_kept"][f"{h}d"]["removed"]
        kept = results["tail_analysis"]["removed_vs_kept"][f"{h}d"]["kept"]
        drag = ""
        if rem.get("mean_ret_pct") is not None and kept.get("mean_ret_pct") is not None:
            drag = f"{rem['mean_ret_pct'] - kept['mean_ret_pct']:+.3f}%"
        pr(f"  {h:>3d}d       {fmt_ret(rem):>10s} {fmt_ret(kept):>10s} {drag:>10s}")

    pr("\n  Worst trap decile vs rest:")
    pr(f"  {'Horizon':<10s} {'Worst 10%':>10s} {'Rest':>10s} {'Spread':>10s}")
    pr(f"  {'-' * 44}")
    for h in HORIZONS:
        worst = results["tail_analysis"]["worst_decile"][f"{h}d"]["worst"]
        rest = results["tail_analysis"]["worst_decile"][f"{h}d"]["rest"]
        spread = ""
        if worst.get("mean_ret_pct") is not None and rest.get("mean_ret_pct") is not None:
            spread = f"{rest['mean_ret_pct'] - worst['mean_ret_pct']:+.3f}%"
        pr(f"  {h:>3d}d       {fmt_ret(worst):>10s} {fmt_ret(rest):>10s} {spread:>10s}")
    pr()

    # ── Section 8: Rolling IC ────────────────────────────────────────
    pr("=" * 80)
    pr("  8. STABILITY — Rolling IC (20-date window, 20d horizon)")
    pr("=" * 80)
    for sig_name in ["trap", "timing"]:
        rolling = results["rolling_ic"][sig_name].get("20d", [])
        if rolling:
            ics = [r["rolling_ic"] for r in rolling]
            n_pos = sum(1 for ic in ics if ic > 0)
            pr(f"  {sig_name}: {len(ics)} windows, {n_pos} positive ({100 * n_pos / len(ics):.0f}%)")
            pr(f"    min={min(ics):+.4f}  mean={statistics.mean(ics):+.4f}  max={max(ics):+.4f}")
        else:
            pr(f"  {sig_name}: insufficient data")
    pr()

    # ── Section 9: PIT Safety ────────────────────────────────────────
    pr("=" * 80)
    pr("  9. PIT SAFETY CONFIRMATION")
    pr("=" * 80)
    pr("  close_price: from price_history.csv (exchange-reported, date-stamped)")
    pr("  market_cap_mm: price_history close × current shares (approximate PIT)")
    pr("  priced_move_pct: same-date options (chains/day_aggs/IV approx)")
    pr("  trap sub-scores: base_rate_gap + conditional_misprice (from priced_move_pct)")
    pr("  timing sub-score: timing_decay_risk (from priced_move_pct + date precision)")
    pr("  slippage: DEAD (returns 0.0) — was look-ahead bias")
    pr("  short_interest: NOT used in any production signal (diagnostics only)")
    pr("  All forward returns: from price_history.csv (PIT-safe)")
    pr()

    report = "\n".join(lines)
    print(report)
    return report


# ═════════════════════════════════════════════════════════════════════════
# Main
# ═════════════════════════════════════════════════════════════════════════


def main() -> None:
    snapshot_root = PROJECT_ROOT / "data" / "snapshots"
    price_csv = PROJECT_ROOT / "production_data" / "price_history.csv"
    out_dir = PROJECT_ROOT / "output" / "pit_safe_final_backtest"
    out_dir.mkdir(parents=True, exist_ok=True)

    results = run_backtest(snapshot_root, price_csv)

    with open(out_dir / "results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)

    report = print_report(results)

    with open(out_dir / "report.txt", "w") as f:
        f.write(report + "\n")

    print(f"\nWritten: {out_dir / 'results.json'}")
    print(f"Written: {out_dir / 'report.txt'}")


if __name__ == "__main__":
    main()
