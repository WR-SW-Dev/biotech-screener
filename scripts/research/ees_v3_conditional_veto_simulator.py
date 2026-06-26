"""
EES v3 Conditional Veto Simulator

Tests evidence-qualified veto policies against raw veto_core to find
whether conditioning the veto on specific failure modes improves outcomes.

Operator decision: RAW_VETO_CORE = REJECTED_AS_TOO_BROAD
Lead hypothesis: EES_V3_CONDITIONAL_VETO_V1

GOVERNANCE: DIAGNOSTIC_ONLY | NO_PRODUCTION_CHANGES | FREEZE_ACTIVE | NO_CRON
"""

import argparse
import csv
import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional

GOVERNANCE = "DIAGNOSTIC_ONLY | NO_PRODUCTION_CHANGES | FREEZE_ACTIVE | NO_CRON"
SNAP_DIR = "data/snapshots_pit_v2"
PRICE_HISTORY = "production_data/price_history.csv"
OUTPUT_JSON = "artifacts/research/ees_v3_conditional_veto_simulator_2026_06_25.json"
OUTPUT_MD = "artifacts/readiness/EES_V3_CONDITIONAL_VETO_SIMULATOR_2026_06_25.md"

HORIZONS = [21, 42, 63]
PRIMARY_HORIZON = 63
QUINTILE_PCT = 20
EARLY_END = "2024-08-31"
LATE_START = "2024-09-30"

POLICY_NAMES = [
    "raw_veto_core",
    "conditional_veto_v1",
    "conditional_veto_v1_plus_data_guard",
    "conditional_veto_no_options_protected",
    "conditional_veto_far_catalyst_protected",
    "combined_guarded_veto",
]

POLICY_DESCRIPTIONS = {
    "raw_veto_core": "Baseline: veto all HL names (ranker top-Q + EES v3 bottom-Q)",
    "conditional_veto_v1": "Veto only if dilution_overhang OR market_already_priced",
    "conditional_veto_v1_plus_data_guard": "v1 + also exclude stale/no-price names",
    "conditional_veto_no_options_protected": "Veto unless sole evidence is no_options_coverage",
    "conditional_veto_far_catalyst_protected": "Veto unless catalyst_days > 180",
    "combined_guarded_veto": "Veto only dilution/mkt-priced/stale; protect no-coverage + far-catalyst",
}


# ─── helpers ─────────────────────────────────────────────────────────────────


def _safe_float(v, default=None):
    if v is None or v == "" or v in ("None", "nan", "NaN"):
        return default
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except (ValueError, TypeError):
        return default


def _has_priced_move(row):
    val = row.get("priced_move_pct", "")
    if not val or val in ("None", "nan", "NaN", "0", "0.0", ""):
        return False
    try:
        f = float(val)
        return not math.isnan(f) and f != 0.0
    except (ValueError, TypeError):
        return False


def _top_q_threshold(values, pct):
    vals = sorted([v for v in values if v is not None], reverse=True)
    n = max(1, int(len(vals) * pct / 100))
    return vals[n - 1] if vals else 0.0


def _avg_ranks(values):
    indexed = sorted(enumerate(values), key=lambda x: x[1])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i
        while j + 1 < len(indexed) and indexed[j + 1][1] == indexed[i][1]:
            j += 1
        avg = (i + j + 2) / 2.0
        for k in range(i, j + 1):
            ranks[indexed[k][0]] = avg
        i = j + 1
    return ranks


def _spearman_ic(signal: List[float], returns: List[float]) -> Optional[float]:
    n = len(signal)
    if n < 5 or len(returns) != n:
        return None
    if len(set(round(s, 8) for s in signal)) < 2:
        return None
    rx = _avg_ranks(signal)
    ry = _avg_ranks(returns)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    sx = math.sqrt(sum((rx[i] - mx) ** 2 for i in range(n)))
    sy = math.sqrt(sum((ry[i] - my) ** 2 for i in range(n)))
    if sx < 1e-12 or sy < 1e-12:
        return None
    return cov / (sx * sy)


def _newey_west_tstat(series: List[float], max_lag: Optional[int] = None) -> Dict:
    n = len(series)
    if n < 5:
        return {"mean": None, "t_nw": 0.0, "n": n}
    mean = sum(series) / n
    demeaned = [s - mean for s in series]
    if max_lag is None:
        max_lag = int(math.floor(4.0 * (n / 100.0) ** (2.0 / 9.0)))
    max_lag = max(0, min(max_lag, n - 2))
    gamma_0 = sum(d * d for d in demeaned) / n
    hac_var = gamma_0
    for lag in range(1, max_lag + 1):
        gamma_j = sum(demeaned[t] * demeaned[t - lag] for t in range(lag, n)) / n
        weight = 1.0 - lag / (max_lag + 1.0)
        hac_var += 2.0 * weight * gamma_j
    se = math.sqrt(max(hac_var / n, 1e-20))
    t_nw = mean / se if se > 1e-12 else 0.0
    return {"mean": round(mean, 6), "t_nw": round(t_nw, 2), "n": n}


def _mean(vals):
    v = [x for x in vals if x is not None]
    return sum(v) / len(v) if v else None


def _drawdown_streak(excess_list):
    max_streak = 0
    cur = 0
    worst = None
    for e in excess_list:
        if e is None:
            cur = 0
            continue
        if e < 0:
            cur += 1
            max_streak = max(max_streak, cur)
            worst = e if worst is None else min(worst, e)
        else:
            cur = 0
    return max_streak, worst


# ─── price loading ────────────────────────────────────────────────────────────


def load_prices():
    prices = defaultdict(dict)
    with open(PRICE_HISTORY) as f:
        reader = csv.DictReader(f)
        for row in reader:
            close = _safe_float(row.get("close"))
            if close is not None:
                prices[row["ticker"]][row["date"]] = close
    print(f"Loaded prices for {len(prices)} tickers", file=sys.stderr)
    return prices


def _anchor_price(ticker, snap_date, prices, sorted_dates):
    tp = prices.get(ticker, {})
    p = tp.get(snap_date)
    if p is not None:
        return p
    return next(
        (tp[d] for d in reversed(sorted_dates) if d <= snap_date and d in tp),
        None,
    )


def _next_date(snap_date, n, sorted_dates):
    for i, d in enumerate(sorted_dates):
        if d >= snap_date:
            target = i + n
            return sorted_dates[target] if target < len(sorted_dates) else None
    return None


def _fwd_return(ticker, snap_date, n, prices, sorted_dates):
    tp = prices.get(ticker, {})
    anchor = _anchor_price(ticker, snap_date, prices, sorted_dates)
    if not anchor:
        return None
    fwd_date = _next_date(snap_date, n, sorted_dates)
    if not fwd_date:
        return None
    fwd = tp.get(fwd_date)
    if fwd is None:
        return None
    return (fwd - anchor) / anchor


def _excess_return(ticker, snap_date, n, prices, sorted_dates):
    ret = _fwd_return(ticker, snap_date, n, prices, sorted_dates)
    if ret is None:
        return None
    xbi = _fwd_return("XBI", snap_date, n, prices, sorted_dates)
    if xbi is None:
        return None
    return ret - xbi


# ─── PIT snapshot loading ─────────────────────────────────────────────────────


def load_pit_snapshots():
    snapshots = []
    for d in sorted(os.listdir(SNAP_DIR)):
        path = os.path.join(SNAP_DIR, d, "rankings.csv")
        if not os.path.exists(path):
            continue
        with open(path) as f:
            snapshots.append((d, list(csv.DictReader(f))))
    print(f"Loaded {len(snapshots)} PIT snapshots", file=sys.stderr)
    return snapshots


# ─── failure mode classification (PIT-safe — no forward data) ────────────────


def classify_failure_modes_pit(row, snap_date, prices, sorted_dates):
    """
    Returns set of failure modes using only information available at snap_date.
    Does NOT use forward returns (PIT-safe).
    stale_proxy = no anchor price within 30 days before snap_date.
    """
    misprice = _safe_float(row.get("conditional_misprice_score"))
    priced = _has_priced_move(row)
    dilution = _safe_float(row.get("dilution_haircut"), default=0.0)
    financing = _safe_float(row.get("financing_truth_gate"), default=1.0)
    catalyst_days = _safe_float(row.get("catalyst_days"))
    ticker = row.get("ticker", "")

    modes = set()

    if priced and misprice is not None and misprice < -0.1:
        modes.add("market_already_priced")

    if not priced and misprice is not None and abs(misprice) < 0.05:
        modes.add("no_options_coverage")

    if financing is not None and financing < 0.5:
        modes.add("dilution_overhang")
    elif dilution is not None and dilution > 0.25:
        modes.add("dilution_overhang")

    if catalyst_days is not None and catalyst_days > 180:
        modes.add("catalyst_too_far")

    # Stale proxy: no price anchor at or before snap_date
    anchor = _anchor_price(ticker, snap_date, prices, sorted_dates)
    if anchor is None:
        modes.add("stale_proxy")

    if not modes:
        modes.add("other")

    return modes


# ─── policy application ───────────────────────────────────────────────────────


def should_veto(failure_modes: set, policy: str) -> bool:
    """
    Given PIT-safe failure modes for an HL name (ranker-high, EES v3 low),
    return True if this policy vetoes the name (removes it from selection).
    False = name survives the veto filter (is selected despite low EES v3).
    """
    has_dilution = "dilution_overhang" in failure_modes
    has_mkt_priced = "market_already_priced" in failure_modes
    has_far_catalyst = "catalyst_too_far" in failure_modes
    has_stale = "stale_proxy" in failure_modes

    if policy == "raw_veto_core":
        # Always veto all HL names
        return True

    if policy == "conditional_veto_v1":
        # Veto only if dilution_overhang or market_already_priced
        return has_dilution or has_mkt_priced

    if policy == "conditional_veto_v1_plus_data_guard":
        # v1 + stale proxy
        return has_dilution or has_mkt_priced or has_stale

    if policy == "conditional_veto_no_options_protected":
        # Veto unless sole evidence is no_options_coverage
        if failure_modes == {"no_options_coverage"}:
            return False
        return True

    if policy == "conditional_veto_far_catalyst_protected":
        # Veto unless catalyst_too_far
        if has_far_catalyst:
            return False
        return True

    if policy == "combined_guarded_veto":
        # Veto only if strong evidence; protect no_options_coverage-only and catalyst_too_far
        if has_far_catalyst:
            return False
        if failure_modes == {"no_options_coverage"}:
            return False
        return has_dilution or has_mkt_priced or has_stale

    return True


# ─── per-snapshot simulation ─────────────────────────────────────────────────


def simulate_snapshot(snap_date, rows, prices, sorted_dates):
    """
    Returns per-policy results for a single snapshot.
    """
    # Quintile thresholds
    fs_vals = [_safe_float(r.get("final_score")) for r in rows]
    v3_vals = [_safe_float(r.get("ees_v3_score")) for r in rows]

    fs_top_q = _top_q_threshold(fs_vals, QUINTILE_PCT)
    v3_bottom_q = _top_q_threshold([-v for v in v3_vals if v is not None], QUINTILE_PCT)
    v3_bottom_q = -v3_bottom_q

    era = "EARLY" if snap_date <= EARLY_END else "LATE"

    # Classify each row
    classified = []
    for row in rows:
        ticker = row.get("ticker", "")
        fs = _safe_float(row.get("final_score"))
        v3 = _safe_float(row.get("ees_v3_score"))
        if fs is None or v3 is None:
            continue

        ranker_top = fs >= fs_top_q
        ees_bottom = v3 <= v3_bottom_q
        is_hl = ranker_top and ees_bottom

        failure_modes = classify_failure_modes_pit(row, snap_date, prices, sorted_dates) if is_hl else set()

        # Forward returns (computed once per name)
        fwd = {h: _fwd_return(ticker, snap_date, h, prices, sorted_dates) for h in HORIZONS}
        exc = {h: _excess_return(ticker, snap_date, h, prices, sorted_dates) for h in HORIZONS}

        classified.append(
            {
                "ticker": ticker,
                "fs": fs,
                "v3": v3,
                "ranker_top": ranker_top,
                "ees_bottom": ees_bottom,
                "is_hl": is_hl,
                "failure_modes": failure_modes,
                "fwd": fwd,
                "exc": exc,
            }
        )

    # Apply each policy
    policy_results = {}
    for policy in POLICY_NAMES:
        selected = []
        vetoed = []
        hl_protected = []

        for c in classified:
            if not c["ranker_top"]:
                continue
            if c["is_hl"]:
                if should_veto(c["failure_modes"], policy):
                    vetoed.append(c)
                else:
                    selected.append(c)
                    hl_protected.append(c)
            else:
                selected.append(c)

        # IC computation: binary score (1=selected, 0=vetoed) for all ranker-top names
        ranker_top_rows = [c for c in classified if c["ranker_top"]]
        ic_by_h = {}
        for h in HORIZONS:
            scores = []
            rets = []
            for c in ranker_top_rows:
                r = c["exc"][h]
                if r is None:
                    continue
                is_sel = 1.0 if c in selected else 0.0
                scores.append(is_sel)
                rets.append(r)
            ic_by_h[h] = _spearman_ic(scores, rets)

        # Mean excess return and hit rate for selected names
        exc_by_h = {}
        hit_by_h = {}
        for h in HORIZONS:
            vals = [c["exc"][h] for c in selected if c["exc"][h] is not None]
            exc_by_h[h] = _mean(vals)
            hit_by_h[h] = sum(1 for v in vals if v > 0) / len(vals) if vals else None

        # Failure mode attribution for protected names (HL names not vetoed)
        mode_attr = defaultdict(lambda: {"n": 0, "exc_63d": []})
        for c in hl_protected:
            for m in c["failure_modes"]:
                mode_attr[m]["n"] += 1
                if c["exc"][PRIMARY_HORIZON] is not None:
                    mode_attr[m]["exc_63d"].append(c["exc"][PRIMARY_HORIZON])
        # Also track names correctly vetoed
        mode_vetoed = defaultdict(lambda: {"n": 0, "exc_63d": []})
        for c in vetoed:
            for m in c["failure_modes"]:
                mode_vetoed[m]["n"] += 1
                if c["exc"][PRIMARY_HORIZON] is not None:
                    mode_vetoed[m]["exc_63d"].append(c["exc"][PRIMARY_HORIZON])

        policy_results[policy] = {
            "era": era,
            "n_selected": len(selected),
            "n_vetoed": len(vetoed),
            "n_hl_protected": len(hl_protected),
            "selected_tickers": [c["ticker"] for c in selected],
            "ic": ic_by_h,
            "exc": exc_by_h,
            "hit": hit_by_h,
            "mode_attr_protected": {k: dict(v) for k, v in mode_attr.items()},
            "mode_attr_vetoed": {k: dict(v) for k, v in mode_vetoed.items()},
        }

    return policy_results, classified


# ─── aggregation ─────────────────────────────────────────────────────────────


def aggregate(all_results):
    """
    Aggregate per-snapshot results across all snapshots.
    Returns per-policy summary statistics.
    """
    by_policy = defaultdict(
        lambda: {
            "ic": defaultdict(list),
            "exc": defaultdict(list),
            "hit": defaultdict(list),
            "n_selected": [],
            "n_vetoed": [],
            "n_hl_protected": [],
            "prev_selected": None,
            "turnover": [],
            "selected_sets": [],
            "era": defaultdict(lambda: {"ic": defaultdict(list), "exc": defaultdict(list), "hit": defaultdict(list)}),
            "mode_attr_protected": defaultdict(lambda: {"n": 0, "exc_63d": []}),
            "mode_attr_vetoed": defaultdict(lambda: {"n": 0, "exc_63d": []}),
        }
    )

    for snap_date, snap_results in all_results:
        for policy, res in snap_results.items():
            p = by_policy[policy]
            for h in HORIZONS:
                if res["ic"].get(h) is not None:
                    p["ic"][h].append(res["ic"][h])
                if res["exc"].get(h) is not None:
                    p["exc"][h].append(res["exc"][h])
                if res["hit"].get(h) is not None:
                    p["hit"][h].append(res["hit"][h])

            p["n_selected"].append(res["n_selected"])
            p["n_vetoed"].append(res["n_vetoed"])
            p["n_hl_protected"].append(res["n_hl_protected"])

            # Turnover
            cur = set(res["selected_tickers"])
            if p["prev_selected"] is not None:
                prev = p["prev_selected"]
                union = len(cur | prev)
                jaccard = len(cur & prev) / union if union > 0 else 1.0
                p["turnover"].append(1 - jaccard)
            p["prev_selected"] = cur

            # Era
            era = res["era"]
            for h in HORIZONS:
                if res["ic"].get(h) is not None:
                    p["era"][era]["ic"][h].append(res["ic"][h])
                if res["exc"].get(h) is not None:
                    p["era"][era]["exc"][h].append(res["exc"][h])
                if res["hit"].get(h) is not None:
                    p["era"][era]["hit"][h].append(res["hit"][h])

            # Mode attribution
            for m, s in res["mode_attr_protected"].items():
                p["mode_attr_protected"][m]["n"] += s["n"]
                p["mode_attr_protected"][m]["exc_63d"].extend(s.get("exc_63d", []))
            for m, s in res["mode_attr_vetoed"].items():
                p["mode_attr_vetoed"][m]["n"] += s["n"]
                p["mode_attr_vetoed"][m]["exc_63d"].extend(s.get("exc_63d", []))

    summary = {}
    for policy, p in by_policy.items():
        horizon_stats = {}
        for h in HORIZONS:
            ic_series = p["ic"][h]
            exc_series = p["exc"][h]
            hit_series = p["hit"][h]

            ic_nw = _newey_west_tstat(ic_series)
            exc_nw = _newey_west_tstat(exc_series)

            # Drawdown streak on per-period mean excess
            per_period_exc = p["exc"][h]
            streak, worst = _drawdown_streak(per_period_exc)

            # Top-decile spread: 90th vs 10th pct of excess returns across all periods
            all_exc = sorted([e for e in per_period_exc if e is not None])
            if len(all_exc) >= 10:
                p10 = all_exc[len(all_exc) // 10]
                p90 = all_exc[-len(all_exc) // 10]
                spread = p90 - p10
            else:
                spread = None

            # Era breakdown
            era_stats = {}
            for era_label in ["EARLY", "LATE"]:
                e_ic = p["era"][era_label]["ic"][h]
                e_exc = p["era"][era_label]["exc"][h]
                e_hit = p["era"][era_label]["hit"][h]
                era_stats[era_label] = {
                    "n_periods": len(e_ic),
                    "ic_mean": round(_mean(e_ic), 4) if e_ic else None,
                    "exc_mean_pct": round(_mean(e_exc) * 100, 2) if e_exc else None,
                    "hit_rate": round(_mean(e_hit), 3) if e_hit else None,
                }

            horizon_stats[h] = {
                "ic_mean": ic_nw["mean"],
                "t_nw": ic_nw["t_nw"],
                "n_periods": ic_nw["n"],
                "hit_rate": round(_mean(hit_series), 3) if hit_series else None,
                "mean_excess_pct": round(exc_nw["mean"] * 100, 2) if exc_nw["mean"] is not None else None,
                "drawdown_streak": streak,
                "worst_period_excess_pct": round(worst * 100, 2) if worst is not None else None,
                "top_decile_spread_pct": round(spread * 100, 2) if spread is not None else None,
                "era": era_stats,
            }

        # Mode attribution summary
        def _mode_summary(mode_dict):
            out = {}
            for m, s in sorted(mode_dict.items(), key=lambda x: -x[1]["n"]):
                exc_vals = [v for v in s["exc_63d"] if v is not None]
                hit = sum(1 for v in exc_vals if v > 0) / len(exc_vals) if exc_vals else None
                out[m] = {
                    "n": s["n"],
                    "mean_excess_63d_pct": round(_mean(exc_vals) * 100, 2) if exc_vals else None,
                    "hit_rate": round(hit, 3) if hit is not None else None,
                }
            return out

        summary[policy] = {
            "description": POLICY_DESCRIPTIONS[policy],
            "n_selected_avg": round(_mean(p["n_selected"]), 1) if p["n_selected"] else None,
            "n_vetoed_avg": round(_mean(p["n_vetoed"]), 1) if p["n_vetoed"] else None,
            "n_hl_protected_avg": round(_mean(p["n_hl_protected"]), 1) if p["n_hl_protected"] else None,
            "turnover_mean": round(_mean(p["turnover"]), 3) if p["turnover"] else None,
            "horizons": horizon_stats,
            "mode_attr_protected": _mode_summary(p["mode_attr_protected"]),
            "mode_attr_vetoed": _mode_summary(p["mode_attr_vetoed"]),
        }

    return summary


# ─── recommendation logic ─────────────────────────────────────────────────────


def make_recommendation(summary):
    raw = summary.get("raw_veto_core", {}).get("horizons", {}).get(PRIMARY_HORIZON, {})
    raw_t = raw.get("t_nw", 0)
    raw_exc = raw.get("mean_excess_pct", 0) or 0

    best_policy = "raw_veto_core"
    best_t = raw_t
    best_exc = raw_exc

    for policy in POLICY_NAMES[1:]:
        s = summary.get(policy, {}).get("horizons", {}).get(PRIMARY_HORIZON, {})
        t = s.get("t_nw", 0) or 0
        exc = s.get("mean_excess_pct", 0) or 0
        if t > best_t and exc >= raw_exc * 0.8:
            best_t = t
            best_exc = exc
            best_policy = policy

    if best_policy == "raw_veto_core":
        verdict = "RAW_VETO_REMAINS_BEST"
    elif best_t >= 2.0 and best_exc >= raw_exc:
        verdict = "CONDITIONAL_VETO_BETTER"
    else:
        verdict = "NO_VETO_POLICY_READY"

    return verdict, best_policy


# ─── markdown output ──────────────────────────────────────────────────────────


def write_markdown(summary, verdict, best_policy, n_snaps, output_path):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    def fmt_pct(v):
        return f"{v:+.1f}%" if v is not None else "n/a"

    def fmt_ic(v):
        return f"{v:.4f}" if v is not None else "n/a"

    def fmt_t(v):
        return f"{v:.2f}" if v is not None else "n/a"

    def fmt_rate(v):
        return f"{v:.1%}" if v is not None else "n/a"

    def fmt_n(v):
        return f"{v:.1f}" if v is not None else "n/a"

    h = PRIMARY_HORIZON
    lines = [
        "# EES v3 Conditional Veto Simulator — Results",
        "",
        "**Date:** 2026-06-25",
        "**Status:** DIAGNOSTIC_ONLY",
        "**Governance:** FREEZE_ACTIVE | NO_PRODUCTION_WIRING | NO_PROMOTION_AUTHORIZED",
        "**Operator context:** RAW_VETO_CORE rejected as too broad. Testing evidence-qualified veto policies.",
        f"**Data:** {n_snaps} PIT monthly snapshots, 2020-01-31 -> 2026-04-16",
        "**Script:** `scripts/research/ees_v3_conditional_veto_simulator.py`",
        "**Raw output:** `artifacts/research/ees_v3_conditional_veto_simulator_2026_06_25.json` (gitignored)",
        "",
        "---",
        "",
        "## Policy Definitions",
        "",
    ]

    for p_name, p_desc in POLICY_DESCRIPTIONS.items():
        lines.append(f"- **`{p_name}`**: {p_desc}")

    lines += [
        "",
        "---",
        "",
        f"## {PRIMARY_HORIZON}d Primary Results",
        "",
        "| Policy | IC | t_NW | Hit Rate | Mean Excess | N Sel | N Veto | Turnover |",
        "|--------|----|----|---------|-------------|-------|--------|----------|",
    ]

    for p_name in POLICY_NAMES:
        ps = summary.get(p_name, {})
        hs = ps.get("horizons", {}).get(h, {})
        row = (
            f"| {p_name} "
            f"| {fmt_ic(hs.get('ic_mean'))} "
            f"| {fmt_t(hs.get('t_nw'))} "
            f"| {fmt_rate(hs.get('hit_rate'))} "
            f"| {fmt_pct(hs.get('mean_excess_pct'))} "
            f"| {fmt_n(ps.get('n_selected_avg'))} "
            f"| {fmt_n(ps.get('n_vetoed_avg'))} "
            f"| {fmt_rate(ps.get('turnover_mean'))} |"
        )
        lines.append(row)

    lines += [
        "",
        "---",
        "",
        "## Era Breakdown (63d mean excess vs XBI)",
        "",
        "| Policy | EARLY excess | EARLY hit | LATE excess | LATE hit |",
        "|--------|-------------|-----------|-------------|----------|",
    ]

    for p_name in POLICY_NAMES:
        hs = summary.get(p_name, {}).get("horizons", {}).get(h, {})
        era = hs.get("era", {})
        e = era.get("EARLY", {})
        late = era.get("LATE", {})
        lines.append(
            f"| {p_name} "
            f"| {fmt_pct(e.get('exc_mean_pct'))} "
            f"| {fmt_rate(e.get('hit_rate'))} "
            f"| {fmt_pct(late.get('exc_mean_pct'))} "
            f"| {fmt_rate(late.get('hit_rate'))} |"
        )

    lines += [
        "",
        "---",
        "",
        "## Drawdown Risk (63d)",
        "",
        "| Policy | Worst Period | Max Streak |",
        "|--------|------------|------------|",
    ]
    for p_name in POLICY_NAMES:
        hs = summary.get(p_name, {}).get("horizons", {}).get(h, {})
        lines.append(
            f"| {p_name} " f"| {fmt_pct(hs.get('worst_period_excess_pct'))} " f"| {hs.get('drawdown_streak', 'n/a')} |"
        )

    lines += [
        "",
        "---",
        "",
        "## Failure Mode Attribution (Protected Names — not vetoed despite low EES v3)",
        "",
        "Names that each policy chose to protect (HL names it did NOT veto).",
        "Positive excess = veto was wrong (false negative). Negative excess = protection was wrong.",
        "",
    ]

    for p_name in POLICY_NAMES:
        ps = summary.get(p_name, {})
        prot = ps.get("mode_attr_protected", {})
        if not prot:
            lines.append(f"**{p_name}**: all HL names vetoed (no protected names)\n")
            continue
        lines.append(f"**{p_name}** (avg {fmt_n(ps.get('n_hl_protected_avg'))} protected/snapshot):")
        for m, ms in prot.items():
            lines.append(
                f"  - {m}: n={ms['n']}, mean_excess={fmt_pct(ms.get('mean_excess_63d_pct'))}, hit={fmt_rate(ms.get('hit_rate'))}"
            )
        lines.append("")

    # Final recommendation
    lines += [
        "---",
        "",
        "## Final Recommendation",
        "",
        f"**Verdict: `{verdict}`**",
        f"**Best policy identified: `{best_policy}`**",
        "",
        "```",
        "LEAD_INTEGRATION_HYPOTHESIS = EES_V3_CONDITIONAL_VETO_V1",
        "RAW_VETO_CORE = REJECTED_AS_TOO_BROAD",
        f"SIMULATOR_VERDICT = {verdict}",
        f"BEST_CONDITIONAL_POLICY = {best_policy}",
        "STATUS = DIAGNOSTIC_ONLY",
        "FREEZE = ACTIVE",
        "PRODUCTION_PROMOTION = NOT_AUTHORIZED",
        "```",
        "",
        "Do not promote anything.",
        "Do not wire into production.",
        "Shadow gate (20d, gates unmet) must be satisfied before any promotion.",
        "",
    ]

    with open(output_path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Wrote markdown to {output_path}", file=sys.stderr)


# ─── main ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of-date", default=None)
    parser.add_argument("--output-json", default=OUTPUT_JSON)
    parser.add_argument("--output-md", default=OUTPUT_MD)
    parser.add_argument("--limit-snaps", type=int, default=None)
    args = parser.parse_args()

    print(f"GOVERNANCE: {GOVERNANCE}", file=sys.stderr)
    print("Loading prices...", file=sys.stderr)
    prices = load_prices()
    sorted_dates = sorted(prices.get("XBI", {}).keys())

    print("Loading PIT snapshots...", file=sys.stderr)
    snapshots = load_pit_snapshots()
    if args.as_of_date:
        snapshots = [(d, r) for d, r in snapshots if d <= args.as_of_date]
    if args.limit_snaps:
        snapshots = snapshots[-args.limit_snaps :]

    print(f"Simulating {len(snapshots)} snapshots...", file=sys.stderr)
    all_results = []
    for i, (snap_date, rows) in enumerate(snapshots):
        if i % 10 == 0:
            print(f"  {i}/{len(snapshots)} {snap_date}", file=sys.stderr)
        snap_results, _ = simulate_snapshot(snap_date, rows, prices, sorted_dates)
        all_results.append((snap_date, snap_results))

    print("Aggregating...", file=sys.stderr)
    summary = aggregate(all_results)
    verdict, best_policy = make_recommendation(summary)

    # Write JSON
    os.makedirs(os.path.dirname(args.output_json), exist_ok=True)
    output = {
        "governance": GOVERNANCE,
        "generated_at": datetime.now().isoformat(),
        "as_of_date": args.as_of_date or "all",
        "n_snapshots": len(snapshots),
        "operator_context": {
            "raw_veto_core_status": "REJECTED_AS_TOO_BROAD",
            "lead_hypothesis": "EES_V3_CONDITIONAL_VETO_V1",
        },
        "methodology": {
            "hl_definition": f"final_score >= top-{QUINTILE_PCT}th-pct AND ees_v3_score <= bottom-{QUINTILE_PCT}th-pct",
            "failure_mode_classification": "PIT-safe (no forward data used)",
            "veto_score": "1=selected, 0=vetoed (binary IC within ranker-top-Q universe)",
            "excess_vs": "XBI",
        },
        "policies": POLICY_DESCRIPTIONS,
        "summary": summary,
        "final_recommendation": {
            "verdict": verdict,
            "best_policy": best_policy,
        },
    }
    with open(args.output_json, "w") as f:
        json.dump(output, f, indent=2)
    print(f"Wrote JSON to {args.output_json}", file=sys.stderr)

    write_markdown(summary, verdict, best_policy, len(snapshots), args.output_md)

    # Console summary
    print(f"\n=== Conditional Veto Simulator — {PRIMARY_HORIZON}d Results ===")
    print(f"{'Policy':<45} {'IC':>7} {'t_NW':>6} {'Excess':>8} {'N_sel':>6} {'Veto':>5}")
    for p_name in POLICY_NAMES:
        ps = summary.get(p_name, {})
        hs = ps.get("horizons", {}).get(PRIMARY_HORIZON, {})
        ic = hs.get("ic_mean")
        t = hs.get("t_nw")
        exc = hs.get("mean_excess_pct")
        n = ps.get("n_selected_avg")
        nv = ps.get("n_vetoed_avg")
        print(f"  {p_name:<43} {ic or 0:7.4f} {t or 0:6.2f} " f"{(exc or 0):+7.2f}% {n or 0:6.1f} {nv or 0:5.1f}")
    print(f"\nVerdict: {verdict}")
    print(f"Best policy: {best_policy}")


if __name__ == "__main__":
    main()
