#!/usr/bin/env python3
"""Spec 053 — Unusual Options Activity Predictive Study.

Comprehensive end-to-end research study testing whether unusual options
activity predicts future biotech stock performance.

Tracks:
  A — Univariate signal cards for all options signals
  B — Selector and ranker bundle tests vs institutional baseline
  C — Diagnostic / overlay use cases
  D — Robustness slices (regime, year, mcap, liquidity, catalyst)
  E — Momentum / catalyst-window drift

Usage:
    python3 scripts/research/options_activity_study.py
    python3 scripts/research/options_activity_study.py --track A
    python3 scripts/research/options_activity_study.py --track B
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

PANEL_CSV = PROJECT_ROOT / "output" / "signals" / "research_panel.csv"
OUTPUT_DIR = PROJECT_ROOT / "output" / "options_activity_study"

SCHEMA_VERSION = "options_activity_study.v1"

# Cost model
RW_EXTRA_COST_BPS_YR = 65
MONTHLY_COST_DRAG = RW_EXTRA_COST_BPS_YR / 12 / 10_000

HORIZONS = [20, 63]
TOP_NS = [20, 30]

# ── Options signals to test ─────────────────────────────────────────

# All options-related numeric signals from the research panel
OPTIONS_SIGNALS = [
    # IV / Surface
    "opt_atm_iv",
    "opt_front_iv",
    "opt_back_iv",
    "opt_term_slope",
    "opt_put_call_skew",
    "opt_rr_25d",
    "actual_implied_move_pctile",
    "implied_event_move",
    "atm_iv_change_5d",
    "cheap_vol_score",
    "iv_crush_breakeven_pct",
    "crush_adjusted_implied_move",
    # Verdict / Composite
    "ovf_composite",
    "ovf_agreement_count",
    "ovf_severity_score",
    "ovf11_score",
    "ovf11_confidence",
    "ovf11_quality",
    "options_quality_composite",
    "surface_signal_quality",
    # Positioning / Divergence
    "pos_divergence",
    "pre_event_put_call_ratio",
    # Flags (numeric)
    "surface_move_extreme",
    "iv_ramp_flag",
    "rr_25d_trend_7d",
    "rr_trend_flag",
    "opt_liquidity_ok",
]

# Derived signal definitions: (name, computation_func)
# These are computed from existing panel columns per-row
DERIVED_SIGNALS = [
    "event_premium_ratio",
    "iv_richness_z",
    "term_slope_z",
    "skew_z",
    "rr_25d_z",
    "surface_conviction",
    "options_bull_composite",
    "options_bear_composite",
    "options_event_composite",
    "options_liquid_conviction",
]

# Incumbent selector signals (B6 baseline)
INCUMBENT_SELECTOR = {
    "coinvest_score_z": (0.65, True),
    "inst_delta_z": (0.35, True),
}

# ── Helpers ──────────────────────────────────────────────────────────


def _sf(v, default=float("nan")):
    if v is None or v == "":
        return default
    try:
        f = float(v)
        return f if not math.isnan(f) else default
    except (ValueError, TypeError):
        return default


def _safe_mean(vals):
    return statistics.mean(vals) if vals else None


def _safe_stdev(vals):
    return statistics.stdev(vals) if len(vals) >= 2 else None


def _safe_ir(vals):
    if len(vals) < 2:
        return None
    m, s = statistics.mean(vals), statistics.stdev(vals)
    return m / s if s > 1e-9 else None


def _safe_tstat(vals):
    if len(vals) < 2:
        return None
    m, s = statistics.mean(vals), statistics.stdev(vals)
    return m / (s / len(vals) ** 0.5) if s > 1e-9 else None


def _hit_rate(vals):
    return sum(1 for v in vals if v > 0) / len(vals) if vals else None


def _r(v, d=4):
    if v is None:
        return None
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return round(v, d)


def _pp(v):
    return v * 100 if v is not None else None


def _fmt(v, d=2):
    return f"{v:.{d}f}" if v is not None else "---"


def _fmt_pct(v):
    if v is None:
        return "---"
    return f"{v*100:.0f}%"


def spearman_ic(x, y):
    n = len(x)
    if n < 5:
        return None

    def _rank(vals):
        indexed = sorted(range(n), key=lambda i: vals[i])
        ranks = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j < n - 1 and vals[indexed[j + 1]] == vals[indexed[j]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                ranks[indexed[k]] = avg
            i = j + 1
        return ranks

    rx, ry = _rank(x), _rank(y)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    dx = sum((rx[i] - mx) ** 2 for i in range(n)) ** 0.5
    dy = sum((ry[i] - my) ** 2 for i in range(n)) ** 0.5
    if dx < 1e-9 or dy < 1e-9:
        return None
    return num / (dx * dy)


def pearson_corr(x, y):
    n = len(x)
    if n < 5:
        return None
    mx, my = sum(x) / n, sum(y) / n
    num = sum((x[i] - mx) * (y[i] - my) for i in range(n))
    dx = sum((x[i] - mx) ** 2 for i in range(n)) ** 0.5
    dy = sum((y[i] - my) ** 2 for i in range(n)) ** 0.5
    if dx < 1e-9 or dy < 1e-9:
        return None
    return num / (dx * dy)


def zscore_vals(vals):
    if len(vals) < 3:
        return vals
    m = statistics.mean(vals)
    s = statistics.stdev(vals)
    if s < 1e-9:
        return [0.0] * len(vals)
    return [(v - m) / s for v in vals]


def winsorize(vals, pct=0.025):
    if len(vals) < 10:
        return vals
    s = sorted(vals)
    lo = s[max(0, int(len(s) * pct))]
    hi = s[min(len(s) - 1, int(len(s) * (1 - pct)))]
    return [max(lo, min(hi, v)) for v in vals]


# ── Data Loading ─────────────────────────────────────────────────────


def load_panel():
    print("Loading research panel...")
    with open(PANEL_CSV) as f:
        panel = list(csv.DictReader(f))
    print(f"  {len(panel):,} rows")
    return panel


def group_by_snapshot(panel):
    groups = defaultdict(list)
    for row in panel:
        groups[row["snapshot_date"]].append(row)
    return dict(sorted(groups.items()))


# ── Derived Signal Computation ───────────────────────────────────────


def compute_derived_signals(panel):
    """Add derived options signals to each panel row."""
    # Group by snapshot for z-scoring
    snapshots = group_by_snapshot(panel)

    for snap_date, rows in snapshots.items():
        # Collect raw values for z-scoring
        atm_ivs, term_slopes, skews, rr25ds = [], [], [], []
        tickers_with = {"atm_iv": [], "term_slope": [], "skew": [], "rr25d": []}

        for r in rows:
            if _sf(r.get("eligible")) != 1.0:
                continue
            v = _sf(r.get("opt_atm_iv"), None)
            if v is not None:
                atm_ivs.append(v)
                tickers_with["atm_iv"].append(r.get("ticker"))
            v = _sf(r.get("opt_term_slope"), None)
            if v is not None:
                term_slopes.append(v)
                tickers_with["term_slope"].append(r.get("ticker"))
            v = _sf(r.get("opt_put_call_skew"), None)
            if v is not None:
                skews.append(v)
                tickers_with["skew"].append(r.get("ticker"))
            v = _sf(r.get("opt_rr_25d"), None)
            if v is not None:
                rr25ds.append(v)
                tickers_with["rr25d"].append(r.get("ticker"))

        # Z-score maps
        z_atm = {}
        if len(atm_ivs) >= 3:
            zs = zscore_vals(atm_ivs)
            z_atm = dict(zip(tickers_with["atm_iv"], zs))

        z_term = {}
        if len(term_slopes) >= 3:
            zs = zscore_vals(term_slopes)
            z_term = dict(zip(tickers_with["term_slope"], zs))

        z_skew = {}
        if len(skews) >= 3:
            zs = zscore_vals(skews)
            z_skew = dict(zip(tickers_with["skew"], zs))

        z_rr25d = {}
        if len(rr25ds) >= 3:
            zs = zscore_vals(rr25ds)
            z_rr25d = dict(zip(tickers_with["rr25d"], zs))

        for r in rows:
            ticker = r.get("ticker", "")

            # Event premium ratio
            front = _sf(r.get("opt_front_iv"), None)
            back = _sf(r.get("opt_back_iv"), None)
            if front is not None and back is not None and back > 0:
                r["event_premium_ratio"] = front / back
            else:
                r["event_premium_ratio"] = ""

            # Z-scored signals
            r["iv_richness_z"] = z_atm.get(ticker, "")
            r["term_slope_z"] = z_term.get(ticker, "")
            r["skew_z"] = z_skew.get(ticker, "")
            r["rr_25d_z"] = z_rr25d.get(ticker, "")

            # Composites
            liq = r.get("opt_liquidity_state", "")
            is_liquid = liq == "liquid"

            # Surface conviction: agreement count + quality + OVF
            ovf = _sf(r.get("ovf_composite"), None)
            oqc = _sf(r.get("options_quality_composite"), None)
            ssq = _sf(r.get("surface_signal_quality"), None)
            parts = [v for v in [ovf, oqc, ssq] if v is not None]
            r["surface_conviction"] = statistics.mean(parts) if len(parts) >= 2 else ""

            # Bull composite: cheap vol + positive skew (calls > puts) + normal/cheap IV
            cheap = _sf(r.get("cheap_vol_score"), None)
            skew_v = _sf(r.get("opt_put_call_skew"), None)
            rr = _sf(r.get("opt_rr_25d"), None)
            bull_parts = []
            if cheap is not None:
                bull_parts.append(min(1.0, max(0.0, cheap)))
            if skew_v is not None:
                # Negative skew = calls cheaper than puts = bullish lean
                bull_parts.append(min(1.0, max(0.0, 0.5 - skew_v)))
            if rr is not None:
                # Positive RR = calls richer = bullish
                bull_parts.append(min(1.0, max(0.0, 0.5 + rr * 2)))
            r["options_bull_composite"] = statistics.mean(bull_parts) if len(bull_parts) >= 2 else ""

            # Bear composite: rich vol + put skew + inverted term
            bear_parts = []
            if cheap is not None:
                bear_parts.append(min(1.0, max(0.0, 1.0 - cheap)))
            if skew_v is not None:
                bear_parts.append(min(1.0, max(0.0, 0.5 + skew_v)))
            term = _sf(r.get("opt_term_slope"), None)
            if term is not None:
                # Negative term slope = inverted = bearish
                bear_parts.append(min(1.0, max(0.0, 0.5 - term * 2)))
            r["options_bear_composite"] = statistics.mean(bear_parts) if len(bear_parts) >= 2 else ""

            # Event composite: event premium + implied move + IV ramp
            aim = _sf(r.get("actual_implied_move_pctile"), None)
            iv_ramp = _sf(r.get("iv_ramp_flag"), None)
            epr = _sf(r.get("event_premium_ratio"), None)
            event_parts = []
            if epr is not None and epr > 0:
                event_parts.append(min(1.0, max(0.0, (epr - 0.8) / 0.4)))
            if aim is not None:
                event_parts.append(aim)
            if iv_ramp is not None:
                event_parts.append(float(iv_ramp))
            r["options_event_composite"] = statistics.mean(event_parts) if len(event_parts) >= 2 else ""

            # Liquid-only conviction: surface conviction but only for liquid names
            sc = r.get("surface_conviction", "")
            if is_liquid and sc != "":
                r["options_liquid_conviction"] = sc
            else:
                r["options_liquid_conviction"] = ""

    print(f"  Derived signals computed for {len(snapshots)} snapshots")
    return panel


# ── Track A: Univariate Signal Cards ─────────────────────────────────


def zscore_eligible_snap(rows, signal):
    vals, tickers = [], []
    for r in rows:
        if _sf(r.get("eligible")) != 1.0:
            continue
        v = _sf(r.get(signal), None)
        if v is not None:
            vals.append(v)
            tickers.append(r.get("ticker", ""))
    if len(vals) < 3:
        return {}
    m = statistics.mean(vals)
    s = statistics.stdev(vals) if len(vals) >= 2 else 1.0
    if s < 1e-9:
        s = 1.0
    return {tickers[i]: (vals[i] - m) / s for i in range(len(tickers))}


def run_track_a(panel, snapshots):
    """Track A: Univariate signal evaluation for all options signals."""
    print("\n" + "=" * 70)
    print("TRACK A — UNIVARIATE OPTIONS SIGNAL CARDS")
    print("=" * 70)

    all_signals = OPTIONS_SIGNALS + DERIVED_SIGNALS
    results = []

    for sig_idx, signal in enumerate(all_signals):
        print(f"  [{sig_idx+1}/{len(all_signals)}] {signal}...", end=" ")

        card = {
            "signal": signal,
            "coverage": {},
            "gate": {},
            "selector": {},
            "ranker": {},
            "regime": {},
            "subsample": {},
            "correlations": {},
        }

        # Coverage
        n_total = len(panel)
        n_present = sum(1 for r in panel if _sf(r.get(signal), None) is not None)
        n_eligible_present = sum(
            1 for r in panel if _sf(r.get("eligible")) == 1.0 and _sf(r.get(signal), None) is not None
        )
        n_eligible = sum(1 for r in panel if _sf(r.get("eligible")) == 1.0)
        n_nonzero = sum(1 for r in panel if _sf(r.get(signal), None) is not None and abs(_sf(r.get(signal), 0)) > 1e-9)
        card["coverage"] = {
            "total_pct": _r(n_present / n_total * 100) if n_total else 0,
            "eligible_pct": _r(n_eligible_present / n_eligible * 100) if n_eligible else 0,
            "nonzero_pct": _r(n_nonzero / n_total * 100) if n_total else 0,
            "n_present": n_present,
            "n_eligible_present": n_eligible_present,
        }

        if n_eligible_present < 50:
            card["verdict"] = "NO_GO"
            card["verdict_reason"] = f"insufficient coverage ({n_eligible_present} eligible rows)"
            results.append(card)
            print(f"SKIP (coverage={n_eligible_present})")
            continue

        # Gate utility + Selector utility + Ranker utility per horizon
        for h in HORIZONS:
            fwd_col = f"fwd_excess_xbi_{h}d"
            fwd_ret_col = f"fwd_ret_{h}d"

            # Gate: above-median vs below-median spread
            gate_spreads = []
            # Selector: improvement vs baseline
            sel_improvements = []
            sel_baseline_rets = []
            sel_bundle_rets = []
            # Ranker: IC within top-K, RW vs EW
            ranker_ics = []
            rw_minus_ew = []
            qtop_rets, qbot_rets = [], []

            for snap_date, rows in sorted(snapshots.items()):
                eligible_with_signal = []
                for r in rows:
                    if _sf(r.get("eligible")) != 1.0:
                        continue
                    sv = _sf(r.get(signal), None)
                    fwd = _sf(r.get(fwd_col), None)
                    rank = _sf(r.get("actionable_rank"), None)
                    if sv is not None and fwd is not None and rank is not None:
                        eligible_with_signal.append(
                            {
                                "ticker": r.get("ticker", ""),
                                "signal": sv,
                                "fwd": fwd,
                                "rank": rank,
                                "fwd_ret": _sf(r.get(fwd_ret_col), None),
                            }
                        )

                if len(eligible_with_signal) < 10:
                    continue

                # Gate: median split
                sig_vals = [e["signal"] for e in eligible_with_signal]
                med = statistics.median(sig_vals)
                above = [e["fwd"] for e in eligible_with_signal if e["signal"] > med]
                below = [e["fwd"] for e in eligible_with_signal if e["signal"] <= med]
                if above and below:
                    gate_spreads.append(statistics.mean(above) - statistics.mean(below))

                # Selector: top-30 by signal vs top-30 by rank
                for top_n in [30]:
                    if len(eligible_with_signal) < top_n:
                        continue

                    by_rank = sorted(eligible_with_signal, key=lambda x: x["rank"])
                    baseline_ret = statistics.mean(e["fwd"] for e in by_rank[:top_n])

                    by_signal = sorted(eligible_with_signal, key=lambda x: -x["signal"])
                    bundle_ret = statistics.mean(e["fwd"] for e in by_signal[:top_n])

                    sel_improvements.append(bundle_ret - baseline_ret)
                    sel_baseline_rets.append(baseline_ret)
                    sel_bundle_rets.append(bundle_ret)

                # Ranker: within top-30
                topk = sorted(eligible_with_signal, key=lambda x: x["rank"])[:30]
                topk_with = [e for e in topk if e["signal"] is not None]
                if len(topk_with) >= 5:
                    ic = spearman_ic(
                        [e["signal"] for e in topk_with],
                        [e["fwd_ret"] if e["fwd_ret"] is not None else e["fwd"] for e in topk_with],
                    )
                    if ic is not None:
                        ranker_ics.append(ic)

                    # RW vs EW
                    by_sig = sorted(topk_with, key=lambda x: -x["signal"])
                    n_s = len(by_sig)
                    ew = statistics.mean(e["fwd_ret"] if e["fwd_ret"] is not None else e["fwd"] for e in by_sig)
                    weights = [(n_s - i) for i in range(n_s)]
                    w_sum = sum(weights)
                    rw = (
                        sum(
                            weights[i]
                            * (by_sig[i]["fwd_ret"] if by_sig[i]["fwd_ret"] is not None else by_sig[i]["fwd"])
                            for i in range(n_s)
                        )
                        / w_sum
                    )
                    rw_minus_ew.append(rw - ew)

                    # Quintile spread
                    q_size = max(1, n_s // 5)
                    qtop_rets.append(
                        statistics.mean(
                            (e["fwd_ret"] if e["fwd_ret"] is not None else e["fwd"]) for e in by_sig[:q_size]
                        )
                    )
                    qbot_rets.append(
                        statistics.mean(
                            (e["fwd_ret"] if e["fwd_ret"] is not None else e["fwd"]) for e in by_sig[-q_size:]
                        )
                    )

            card["gate"][str(h)] = {
                "spread_pp": _r(_pp(_safe_mean(gate_spreads))),
                "spread_tstat": _r(_safe_tstat([v * 100 for v in gate_spreads])),
                "n_periods": len(gate_spreads),
            }

            card["selector"][str(h)] = {
                "improvement_pp": _r(_pp(_safe_mean(sel_improvements))),
                "improvement_tstat": _r(_safe_tstat([v * 100 for v in sel_improvements])),
                "improvement_ir": _r(_safe_ir([v * 100 for v in sel_improvements])),
                "improvement_hit_rate": _r(_hit_rate(sel_improvements)),
                "baseline_mean_pp": _r(_pp(_safe_mean(sel_baseline_rets))),
                "bundle_mean_pp": _r(_pp(_safe_mean(sel_bundle_rets))),
                "n_periods": len(sel_improvements),
            }

            card["ranker"][str(h)] = {
                "ic_mean": _r(_safe_mean(ranker_ics)),
                "ic_tstat": _r(_safe_tstat(ranker_ics)),
                "ic_hit_rate": _r(_hit_rate(ranker_ics)),
                "rw_minus_ew_gross_pp": _r(_pp(_safe_mean(rw_minus_ew))),
                "rw_minus_ew_net_pp": _r(
                    _pp((_safe_mean(rw_minus_ew) - MONTHLY_COST_DRAG) if _safe_mean(rw_minus_ew) is not None else None)
                ),
                "quintile_spread_pp": _r(
                    _pp(
                        (_safe_mean(qtop_rets) - _safe_mean(qbot_rets))
                        if _safe_mean(qtop_rets) is not None and _safe_mean(qbot_rets) is not None
                        else None
                    )
                ),
                "n_periods": len(ranker_ics),
            }

        # Regime splits (63d)
        for regime_label in ["bear", "neutral", "bull"]:
            regime_ics = []
            regime_sel_imp = []
            for snap_date, rows in sorted(snapshots.items()):
                sample_regime = None
                for r in rows:
                    sample_regime = r.get("regime_63d")
                    if sample_regime:
                        break
                if sample_regime != regime_label:
                    continue

                eligible_with = []
                for r in rows:
                    if _sf(r.get("eligible")) != 1.0:
                        continue
                    sv = _sf(r.get(signal), None)
                    fwd = _sf(r.get("fwd_excess_xbi_63d"), None)
                    rank = _sf(r.get("actionable_rank"), None)
                    if sv is not None and fwd is not None and rank is not None:
                        eligible_with.append({"signal": sv, "fwd": fwd, "rank": rank, "ticker": r.get("ticker", "")})

                if len(eligible_with) < 10:
                    continue

                # Selector improvement
                if len(eligible_with) >= 30:
                    by_rank = sorted(eligible_with, key=lambda x: x["rank"])[:30]
                    by_sig = sorted(eligible_with, key=lambda x: -x["signal"])[:30]
                    regime_sel_imp.append(
                        statistics.mean(e["fwd"] for e in by_sig) - statistics.mean(e["fwd"] for e in by_rank)
                    )

                # Ranker IC within top-30
                topk = sorted(eligible_with, key=lambda x: x["rank"])[:30]
                if len(topk) >= 5:
                    ic = spearman_ic([e["signal"] for e in topk], [e["fwd"] for e in topk])
                    if ic is not None:
                        regime_ics.append(ic)

            card["regime"][regime_label] = {
                "ic_mean": _r(_safe_mean(regime_ics)),
                "ic_n": len(regime_ics),
                "selector_improvement_pp": _r(_pp(_safe_mean(regime_sel_imp))),
                "selector_n": len(regime_sel_imp),
            }

        # Subsample: liquid-only
        liquid_ics = []
        for snap_date, rows in sorted(snapshots.items()):
            topk = []
            for r in rows:
                if _sf(r.get("eligible")) != 1.0:
                    continue
                rank = _sf(r.get("actionable_rank"), None)
                if rank is None or rank > 30:
                    continue
                if r.get("opt_liquidity_state") != "liquid":
                    continue
                sv = _sf(r.get(signal), None)
                fwd = _sf(r.get("fwd_excess_xbi_63d"), None)
                if sv is not None and fwd is not None:
                    topk.append({"signal": sv, "fwd": fwd})
            if len(topk) >= 5:
                ic = spearman_ic([e["signal"] for e in topk], [e["fwd"] for e in topk])
                if ic is not None:
                    liquid_ics.append(ic)

        card["subsample"]["liquid_only"] = {
            "ic_mean": _r(_safe_mean(liquid_ics)),
            "ic_tstat": _r(_safe_tstat(liquid_ics)),
            "n_periods": len(liquid_ics),
        }

        # Subsample: near-catalyst (catalyst_days <= 60)
        catalyst_ics = []
        for snap_date, rows in sorted(snapshots.items()):
            topk = []
            for r in rows:
                if _sf(r.get("eligible")) != 1.0:
                    continue
                rank = _sf(r.get("actionable_rank"), None)
                if rank is None or rank > 60:
                    continue
                cat_days = _sf(r.get("catalyst_days"), None)
                if cat_days is None or cat_days > 60:
                    continue
                sv = _sf(r.get(signal), None)
                fwd = _sf(r.get("fwd_excess_xbi_63d"), None)
                if sv is not None and fwd is not None:
                    topk.append({"signal": sv, "fwd": fwd})
            if len(topk) >= 5:
                ic = spearman_ic([e["signal"] for e in topk], [e["fwd"] for e in topk])
                if ic is not None:
                    catalyst_ics.append(ic)

        card["subsample"]["near_catalyst"] = {
            "ic_mean": _r(_safe_mean(catalyst_ics)),
            "ic_tstat": _r(_safe_tstat(catalyst_ics)),
            "n_periods": len(catalyst_ics),
        }

        # Correlations with incumbent signals
        coinvest_vals, inst_vals, sig_vals_corr = [], [], []
        for r in panel:
            if _sf(r.get("eligible")) != 1.0:
                continue
            sv = _sf(r.get(signal), None)
            cv = _sf(r.get("coinvest_score_z"), None)
            iv = _sf(r.get("inst_delta_z"), None)
            if sv is not None and cv is not None:
                sig_vals_corr.append(sv)
                coinvest_vals.append(cv)
                if iv is not None:
                    inst_vals.append(iv)

        card["correlations"] = {
            "vs_coinvest_score_z": _r(pearson_corr(sig_vals_corr[: len(coinvest_vals)], coinvest_vals)),
            "vs_inst_delta_z": (
                _r(pearson_corr(sig_vals_corr[: len(inst_vals)], inst_vals[: len(sig_vals_corr)]))
                if len(inst_vals) >= 5
                else None
            ),
        }

        # Verdict
        sel_63 = card["selector"].get("63", {})
        rnk_63 = card["ranker"].get("63", {})
        sel_t = sel_63.get("improvement_tstat") or 0
        rnk_ic = rnk_63.get("ic_mean") or 0
        rnk_ic_t = rnk_63.get("ic_tstat") or 0
        cov_pct = card["coverage"].get("eligible_pct") or 0

        bear_ic = (card["regime"].get("bear", {}).get("ic_mean")) or 0
        bull_ic = (card["regime"].get("bull", {}).get("ic_mean")) or 0
        regime_ok = bear_ic > -0.10 and bull_ic > -0.10

        if cov_pct < 20:
            verdict = "NO_GO"
            reason = f"low coverage ({cov_pct:.0f}%)"
        elif sel_t >= 1.6 and rnk_ic > 0.03 and regime_ok:
            verdict = "PROMOTE_CANDIDATE"
            reason = f"sel t={sel_t:.2f}, IC={rnk_ic:.3f}, regime stable"
        elif (sel_t >= 1.0 or rnk_ic > 0.02) and cov_pct >= 30:
            verdict = "SHADOW"
            reason = f"sel t={sel_t:.2f}, IC={rnk_ic:.3f}"
        elif sel_t >= 0 and rnk_ic >= 0:
            verdict = "HOLD"
            reason = f"weak positive: sel t={sel_t:.2f}, IC={rnk_ic:.3f}"
        else:
            verdict = "NO_GO"
            reason = f"negative: sel t={sel_t:.2f}, IC={rnk_ic:.3f}"

        card["verdict"] = verdict
        card["verdict_reason"] = reason

        # Print preview
        sel_imp = sel_63.get("improvement_pp") or 0
        print(f"sel={sel_imp:+.2f}pp t={sel_t:.2f} | IC={rnk_ic:+.3f} t={rnk_ic_t:.2f} | {verdict}")

        results.append(card)

    return results


# ── Track B: Bundle Tests ────────────────────────────────────────────


# Selector bundles: incumbent + options signals
SELECTOR_BUNDLES = {
    "S0_incumbent_B6": {
        "coinvest_score_z": (0.65, True),
        "inst_delta_z": (0.35, True),
    },
    "S1_incumbent_plus_ovf11": {
        "coinvest_score_z": (0.55, True),
        "inst_delta_z": (0.25, True),
        "ovf11_score": (0.20, True),
    },
    "S2_incumbent_plus_cheap_vol": {
        "coinvest_score_z": (0.55, True),
        "inst_delta_z": (0.25, True),
        "cheap_vol_score": (0.20, True),
    },
    "S3_incumbent_plus_event_composite": {
        "coinvest_score_z": (0.55, True),
        "inst_delta_z": (0.25, True),
        "options_event_composite": (0.20, True),
    },
    "S4_incumbent_plus_surface_conviction": {
        "coinvest_score_z": (0.55, True),
        "inst_delta_z": (0.25, True),
        "surface_conviction": (0.20, True),
    },
    "S5_incumbent_plus_liquid_conviction": {
        "coinvest_score_z": (0.55, True),
        "inst_delta_z": (0.25, True),
        "options_liquid_conviction": (0.20, True),
    },
    "S6_incumbent_plus_atm_iv": {
        "coinvest_score_z": (0.55, True),
        "inst_delta_z": (0.25, True),
        "opt_atm_iv": (0.20, False),  # Lower IV = better (cheap)
    },
    "S7_incumbent_plus_rr25d": {
        "coinvest_score_z": (0.55, True),
        "inst_delta_z": (0.25, True),
        "opt_rr_25d": (0.20, True),
    },
    "S8_incumbent_plus_bull_composite": {
        "coinvest_score_z": (0.55, True),
        "inst_delta_z": (0.25, True),
        "options_bull_composite": (0.20, True),
    },
    "S9_incumbent_plus_iv_change": {
        "coinvest_score_z": (0.55, True),
        "inst_delta_z": (0.25, True),
        "atm_iv_change_5d": (0.20, True),
    },
    "S10_options_only_composite": {
        "ovf11_score": (0.25, True),
        "cheap_vol_score": (0.25, True),
        "options_event_composite": (0.25, True),
        "opt_rr_25d": (0.25, True),
    },
    "S11_incumbent_plus_pos_divergence": {
        "coinvest_score_z": (0.55, True),
        "inst_delta_z": (0.25, True),
        "pos_divergence": (0.20, False),  # Lower divergence = better agreement
    },
    "S12_incumbent_light_options": {
        "coinvest_score_z": (0.50, True),
        "inst_delta_z": (0.25, True),
        "cheap_vol_score": (0.10, True),
        "ovf11_score": (0.10, True),
        "opt_rr_25d": (0.05, True),
    },
}

# Ranker bundles: options features within top-K
RANKER_BUNDLES = {
    "RO0_coinvest_inst_baseline": {
        "coinvest_score_z": (0.65, True),
        "inst_delta_z": (0.35, True),
    },
    "RO1_ovf11_only": {
        "ovf11_score": (1.0, True),
    },
    "RO2_cheap_vol_only": {
        "cheap_vol_score": (1.0, True),
    },
    "RO3_rr25d_only": {
        "opt_rr_25d": (1.0, True),
    },
    "RO4_term_slope_only": {
        "opt_term_slope": (1.0, True),
    },
    "RO5_atm_iv_only": {
        "opt_atm_iv": (1.0, False),  # lower IV = better
    },
    "RO6_options_compact": {
        "ovf11_score": (0.35, True),
        "cheap_vol_score": (0.35, True),
        "opt_rr_25d": (0.30, True),
    },
    "RO7_options_full": {
        "ovf11_score": (0.20, True),
        "cheap_vol_score": (0.20, True),
        "opt_rr_25d": (0.15, True),
        "opt_term_slope": (0.15, True),
        "opt_put_call_skew": (0.15, True),
        "atm_iv_change_5d": (0.15, True),
    },
    "RO8_event_premium_ranker": {
        "options_event_composite": (0.40, True),
        "actual_implied_move_pctile": (0.30, True),
        "opt_term_slope": (0.30, False),  # backwardation = event premium
    },
    "RO9_bull_sentiment_ranker": {
        "options_bull_composite": (0.40, True),
        "cheap_vol_score": (0.30, True),
        "opt_rr_25d": (0.30, True),
    },
    "RO10_liquid_options": {
        "options_liquid_conviction": (0.50, True),
        "cheap_vol_score": (0.25, True),
        "ovf11_score": (0.25, True),
    },
    "RO11_coinvest_plus_best_opt": {
        "coinvest_score_z": (0.50, True),
        "inst_delta_z": (0.20, True),
        "cheap_vol_score": (0.15, True),
        "ovf11_score": (0.15, True),
    },
    "RO12_surface_conviction_only": {
        "surface_conviction": (1.0, True),
    },
    "RO13_iv_momentum_only": {
        "atm_iv_change_5d": (1.0, True),
    },
    "RO14_pos_divergence_only": {
        "pos_divergence": (1.0, False),
    },
}


def compute_bundle_score_snap(rows, bundle):
    """Compute weighted bundle score for eligible names in one snapshot."""
    z_maps = {}
    for signal in bundle:
        vals, tickers = [], []
        for r in rows:
            if _sf(r.get("eligible")) != 1.0:
                continue
            v = _sf(r.get(signal), None)
            if v is not None:
                vals.append(v)
                tickers.append(r.get("ticker", ""))
        if len(vals) < 3:
            z_maps[signal] = {}
            continue
        m = statistics.mean(vals)
        s = statistics.stdev(vals) if len(vals) >= 2 else 1.0
        if s < 1e-9:
            s = 1.0
        z_maps[signal] = {tickers[i]: (vals[i] - m) / s for i in range(len(tickers))}

    scores = {}
    for r in rows:
        if _sf(r.get("eligible")) != 1.0:
            continue
        ticker = r.get("ticker", "")
        total, total_w = 0.0, 0.0
        for signal, (weight, higher_better) in bundle.items():
            z = z_maps.get(signal, {}).get(ticker)
            if z is not None:
                if not higher_better:
                    z = -z
                total += weight * z
                total_w += weight
        scores[ticker] = total / total_w if total_w > 0 else 0.0
    return scores


def run_selector_bundles(snapshots):
    """Test selector bundles: options signals added to incumbent."""
    print("\n" + "=" * 70)
    print("TRACK B.1 — SELECTOR BUNDLE TESTS")
    print("=" * 70)

    results = []
    for bname, bundle in SELECTOR_BUNDLES.items():
        sigs = ", ".join(f"{s}({w:.0%})" for s, (w, _) in bundle.items())
        print(f"  {bname}: {sigs}")

        result = {
            "bundle_name": bname,
            "signals": {s: {"weight": w, "higher_is_better": h} for s, (w, h) in bundle.items()},
        }

        for top_n in TOP_NS:
            result[f"top_{top_n}"] = {}
            for h in HORIZONS:
                fwd_col = f"fwd_excess_xbi_{h}d"
                improvements, baseline_rets, bundle_rets = [], [], []
                turnovers = []
                prev_tickers = set()

                for snap_date, rows in sorted(snapshots.items()):
                    eligible = []
                    for r in rows:
                        if _sf(r.get("eligible")) != 1.0:
                            continue
                        fwd = _sf(r.get(fwd_col), None)
                        rank = _sf(r.get("actionable_rank"), None)
                        if fwd is not None and rank is not None:
                            eligible.append({"ticker": r.get("ticker", ""), "rank": rank, "fwd": fwd})
                    if len(eligible) < top_n:
                        continue

                    by_rank = sorted(eligible, key=lambda x: x["rank"])
                    baseline_ret = statistics.mean(e["fwd"] for e in by_rank[:top_n])

                    scores = compute_bundle_score_snap(rows, bundle)
                    for e in eligible:
                        e["score"] = scores.get(e["ticker"], 0.0)
                    by_score = sorted(eligible, key=lambda x: -x["score"])
                    bundle_ret = statistics.mean(e["fwd"] for e in by_score[:top_n])

                    improvements.append(bundle_ret - baseline_ret)
                    baseline_rets.append(baseline_ret)
                    bundle_rets.append(bundle_ret)

                    curr = {e["ticker"] for e in by_score[:top_n]}
                    if prev_tickers:
                        turnovers.append(1.0 - len(curr & prev_tickers) / top_n)
                    prev_tickers = curr

                result[f"top_{top_n}"][str(h)] = {
                    "baseline_pp": _r(_pp(_safe_mean(baseline_rets))),
                    "bundle_pp": _r(_pp(_safe_mean(bundle_rets))),
                    "improvement_pp": _r(_pp(_safe_mean(improvements))),
                    "improvement_cum_pp": _r(_pp(sum(improvements)) if improvements else None),
                    "improvement_tstat": _r(_safe_tstat([v * 100 for v in improvements])),
                    "improvement_ir": _r(_safe_ir([v * 100 for v in improvements])),
                    "hit_rate": _r(_hit_rate(improvements)),
                    "turnover": _r(_safe_mean(turnovers)),
                    "n_periods": len(improvements),
                }

        # Regime splits at 63d top-30
        result["regime"] = {}
        for regime_label in ["bear", "neutral", "bull"]:
            regime_imp = []
            for snap_date, rows in sorted(snapshots.items()):
                sample_regime = None
                for r in rows:
                    sample_regime = r.get("regime_63d")
                    if sample_regime:
                        break
                if sample_regime != regime_label:
                    continue

                eligible = []
                for r in rows:
                    if _sf(r.get("eligible")) != 1.0:
                        continue
                    fwd = _sf(r.get("fwd_excess_xbi_63d"), None)
                    rank = _sf(r.get("actionable_rank"), None)
                    if fwd is not None and rank is not None:
                        eligible.append({"ticker": r.get("ticker", ""), "rank": rank, "fwd": fwd})
                if len(eligible) < 30:
                    continue

                by_rank = sorted(eligible, key=lambda x: x["rank"])[:30]
                baseline_ret = statistics.mean(e["fwd"] for e in by_rank)
                scores = compute_bundle_score_snap(rows, bundle)
                for e in eligible:
                    e["score"] = scores.get(e["ticker"], 0.0)
                by_score = sorted(eligible, key=lambda x: -x["score"])[:30]
                regime_imp.append(statistics.mean(e["fwd"] for e in by_score) - baseline_ret)

            result["regime"][regime_label] = {
                "improvement_pp": _r(_pp(_safe_mean(regime_imp))),
                "hit_rate": _r(_hit_rate(regime_imp)),
                "n_periods": len(regime_imp),
            }

        h63 = result["top_30"]["63"]
        imp = h63.get("improvement_pp") or 0
        ts = h63.get("improvement_tstat") or 0
        print(f"    -> top-30 63d: {imp:+.2f}pp t={ts:.2f}")

        results.append(result)

    return results


def run_ranker_bundles(snapshots):
    """Test ranker bundles: options features within top-K."""
    print("\n" + "=" * 70)
    print("TRACK B.2 — RANKER BUNDLE TESTS")
    print("=" * 70)

    results = []
    for bname, bundle in RANKER_BUNDLES.items():
        sigs = ", ".join(f"{s}({w:.0%})" for s, (w, _) in bundle.items())
        print(f"  {bname}: {sigs}")

        result = {
            "bundle_name": bname,
            "signals": {s: {"weight": w, "higher_is_better": h} for s, (w, h) in bundle.items()},
        }

        for top_n in TOP_NS:
            result[f"top_{top_n}"] = {}
            for h in HORIZONS:
                fwd_col = f"fwd_ret_{h}d"

                ic_vals, rw_ew, ew_rets, rw_rets = [], [], [], []
                qtop, qbot, pw_acc, cov_vals = [], [], [], []

                for snap_date, rows in sorted(snapshots.items()):
                    topk = []
                    for r in rows:
                        rank = _sf(r.get("actionable_rank"), None)
                        if rank is None or rank > top_n:
                            continue
                        if _sf(r.get("eligible")) != 1.0:
                            continue
                        fwd = _sf(r.get(fwd_col), None)
                        if fwd is None:
                            continue
                        entry = {"ticker": r.get("ticker", ""), "fwd": fwd}
                        for sig in bundle:
                            entry[sig] = _sf(r.get(sig), None)
                        topk.append(entry)

                    with_all = [t for t in topk if all(t.get(s) is not None for s in bundle)]
                    cov_vals.append(len(with_all) / len(topk) if topk else 0)
                    if len(with_all) < 5:
                        continue

                    # Z-score within top-K
                    z_maps = {}
                    for sig in bundle:
                        vals = [t[sig] for t in with_all]
                        tks = [t["ticker"] for t in with_all]
                        if len(vals) >= 3:
                            m, s = statistics.mean(vals), statistics.stdev(vals)
                            if s < 1e-9:
                                s = 1.0
                            z_maps[sig] = {tks[i]: (vals[i] - m) / s for i in range(len(tks))}
                        else:
                            z_maps[sig] = {}

                    scores = {}
                    for t in with_all:
                        tk = t["ticker"]
                        total, total_w = 0.0, 0.0
                        for sig, (w, hb) in bundle.items():
                            z = z_maps.get(sig, {}).get(tk)
                            if z is not None:
                                if not hb:
                                    z = -z
                                total += w * z
                                total_w += w
                        scores[tk] = total / total_w if total_w > 0 else 0.0

                    ic = spearman_ic(
                        [scores[t["ticker"]] for t in with_all],
                        [t["fwd"] for t in with_all],
                    )
                    if ic is not None:
                        ic_vals.append(ic)

                    ew = statistics.mean(t["fwd"] for t in topk)
                    ew_rets.append(ew)
                    by_score = sorted(with_all, key=lambda x: -scores[x["ticker"]])
                    n_s = len(by_score)
                    weights = [(n_s - i) for i in range(n_s)]
                    w_sum = sum(weights)
                    rw = sum(weights[i] * by_score[i]["fwd"] for i in range(n_s)) / w_sum
                    rw_rets.append(rw)
                    rw_ew.append(rw - ew)

                    q_size = max(1, n_s // 5)
                    qtop.append(statistics.mean(t["fwd"] for t in by_score[:q_size]))
                    qbot.append(statistics.mean(t["fwd"] for t in by_score[-q_size:]))

                    n_correct = n_total = 0
                    for i in range(n_s):
                        for j in range(i + 1, n_s):
                            n_total += 1
                            si, sj = scores[by_score[i]["ticker"]], scores[by_score[j]["ticker"]]
                            ri, rj = by_score[i]["fwd"], by_score[j]["fwd"]
                            if (si > sj and ri > rj) or (si < sj and ri < rj):
                                n_correct += 1
                    if n_total > 0:
                        pw_acc.append(n_correct / n_total)

                rw_ew_gross = _safe_mean(rw_ew)
                rw_ew_net = (rw_ew_gross - MONTHLY_COST_DRAG) if rw_ew_gross is not None else None

                result[f"top_{top_n}"][str(h)] = {
                    "ic_mean": _r(_safe_mean(ic_vals)),
                    "ic_tstat": _r(_safe_tstat(ic_vals)),
                    "ic_hit_rate": _r(_hit_rate(ic_vals)),
                    "rw_minus_ew_gross_pp": _r(_pp(rw_ew_gross)),
                    "rw_minus_ew_net_pp": _r(_pp(rw_ew_net)),
                    "quintile_spread_pp": _r(
                        _pp(
                            (_safe_mean(qtop) - _safe_mean(qbot))
                            if _safe_mean(qtop) is not None and _safe_mean(qbot) is not None
                            else None
                        )
                    ),
                    "pairwise_accuracy": _r(_safe_mean(pw_acc)),
                    "coverage": _r(_safe_mean(cov_vals)),
                    "n_periods": len(ic_vals),
                }

        h63 = result["top_30"]["63"]
        ic = h63.get("ic_mean") or 0
        rw_net = h63.get("rw_minus_ew_net_pp") or 0
        print(f"    -> top-30 63d: IC={ic:+.3f} RW-EW net={rw_net:+.2f}pp")

        results.append(result)

    return results


# ── Track C: Diagnostic / Overlay Tests ──────────────────────────────


def run_track_c(panel, snapshots):
    """Track C: test options as diagnostic/overlay signals."""
    print("\n" + "=" * 70)
    print("TRACK C — DIAGNOSTIC / OVERLAY USE CASES")
    print("=" * 70)

    results = {}

    # C1: Near-catalyst tiebreaker — among names with catalyst_days <= 30,
    # does any options signal help pick the better ones?
    print("  C1: Near-catalyst tiebreaker...")
    c1_signals = [
        "cheap_vol_score",
        "ovf11_score",
        "opt_rr_25d",
        "options_event_composite",
        "actual_implied_move_pctile",
        "pos_divergence",
        "surface_conviction",
    ]
    c1_results = {}
    for sig in c1_signals:
        ics = []
        for snap_date, rows in sorted(snapshots.items()):
            near_cat = []
            for r in rows:
                if _sf(r.get("eligible")) != 1.0:
                    continue
                rank = _sf(r.get("actionable_rank"), None)
                if rank is None or rank > 60:
                    continue
                cat = _sf(r.get("catalyst_days"), None)
                if cat is None or cat > 30:
                    continue
                sv = _sf(r.get(sig), None)
                fwd = _sf(r.get("fwd_excess_xbi_63d"), None)
                if sv is not None and fwd is not None:
                    near_cat.append({"signal": sv, "fwd": fwd})
            if len(near_cat) >= 5:
                ic = spearman_ic([e["signal"] for e in near_cat], [e["fwd"] for e in near_cat])
                if ic is not None:
                    ics.append(ic)
        c1_results[sig] = {
            "ic_mean": _r(_safe_mean(ics)),
            "ic_tstat": _r(_safe_tstat(ics)),
            "n_periods": len(ics),
        }
    results["C1_catalyst_tiebreaker"] = c1_results

    # C2: High event-premium sizing tilt
    print("  C2: Event-premium sizing tilt...")
    high_ep_excess, low_ep_excess = [], []
    for snap_date, rows in sorted(snapshots.items()):
        high_ep, low_ep = [], []
        for r in rows:
            if _sf(r.get("eligible")) != 1.0:
                continue
            rank = _sf(r.get("actionable_rank"), None)
            if rank is None or rank > 30:
                continue
            fwd = _sf(r.get("fwd_excess_xbi_63d"), None)
            if fwd is None:
                continue
            ep = r.get("opt_event_premium", "")
            if ep == "YES":
                high_ep.append(fwd)
            elif ep == "NO":
                low_ep.append(fwd)
        if high_ep:
            high_ep_excess.append(statistics.mean(high_ep))
        if low_ep:
            low_ep_excess.append(statistics.mean(low_ep))

    results["C2_event_premium_tilt"] = {
        "high_ep_mean_excess_pp": _r(_pp(_safe_mean(high_ep_excess))),
        "low_ep_mean_excess_pp": _r(_pp(_safe_mean(low_ep_excess))),
        "spread_pp": _r(
            _pp(
                (_safe_mean(high_ep_excess) - _safe_mean(low_ep_excess))
                if _safe_mean(high_ep_excess) is not None and _safe_mean(low_ep_excess) is not None
                else None
            )
        ),
        "spread_tstat": _r(
            _safe_tstat(
                [
                    h - l
                    for h, l in zip(
                        high_ep_excess[: min(len(high_ep_excess), len(low_ep_excess))],
                        low_ep_excess[: min(len(high_ep_excess), len(low_ep_excess))],
                    )
                ]
            )
        ),
    }

    # C3: Illiquid chain risk-off
    print("  C3: Illiquid chain risk-off...")
    liquid_rets, thin_rets, absent_rets = [], [], []
    for snap_date, rows in sorted(snapshots.items()):
        liq, thn, abs_ = [], [], []
        for r in rows:
            if _sf(r.get("eligible")) != 1.0:
                continue
            rank = _sf(r.get("actionable_rank"), None)
            if rank is None or rank > 30:
                continue
            fwd = _sf(r.get("fwd_excess_xbi_63d"), None)
            if fwd is None:
                continue
            ls = r.get("opt_liquidity_state", "")
            if ls == "liquid":
                liq.append(fwd)
            elif ls == "thin":
                thn.append(fwd)
            elif ls == "absent":
                abs_.append(fwd)
        if liq:
            liquid_rets.append(statistics.mean(liq))
        if thn:
            thin_rets.append(statistics.mean(thn))
        if abs_:
            absent_rets.append(statistics.mean(abs_))

    results["C3_liquidity_risk_off"] = {
        "liquid_mean_pp": _r(_pp(_safe_mean(liquid_rets))),
        "thin_mean_pp": _r(_pp(_safe_mean(thin_rets))),
        "absent_mean_pp": _r(_pp(_safe_mean(absent_rets))),
        "liquid_minus_thin_pp": _r(
            _pp(
                (_safe_mean(liquid_rets) - _safe_mean(thin_rets))
                if _safe_mean(liquid_rets) is not None and _safe_mean(thin_rets) is not None
                else None
            )
        ),
    }

    # C4: IV regime as risk signal
    print("  C4: IV regime risk signal...")
    regime_rets = {"NORMAL": [], "ELEVATED": [], "EXTREME": []}
    for snap_date, rows in sorted(snapshots.items()):
        buckets = defaultdict(list)
        for r in rows:
            if _sf(r.get("eligible")) != 1.0:
                continue
            rank = _sf(r.get("actionable_rank"), None)
            if rank is None or rank > 30:
                continue
            fwd = _sf(r.get("fwd_excess_xbi_63d"), None)
            if fwd is None:
                continue
            iv_reg = r.get("opt_iv_regime", "")
            if iv_reg in regime_rets:
                buckets[iv_reg].append(fwd)
        for k, v in buckets.items():
            if v:
                regime_rets[k].append(statistics.mean(v))

    results["C4_iv_regime_signal"] = {
        regime: {
            "mean_excess_pp": _r(_pp(_safe_mean(vals))),
            "n_periods": len(vals),
        }
        for regime, vals in regime_rets.items()
    }

    for k, v in results.items():
        print(f"  {k}: {json.dumps(v, default=str)[:120]}...")

    return results


# ── Track D: Robustness Slices ───────────────────────────────────────


def run_track_d(panel, snapshots, track_a_results):
    """Track D: robustness slices for promising signals."""
    print("\n" + "=" * 70)
    print("TRACK D — ROBUSTNESS SLICES")
    print("=" * 70)

    # Pick signals with SHADOW or PROMOTE_CANDIDATE verdicts
    promising = [c for c in track_a_results if c["verdict"] in ("SHADOW", "PROMOTE_CANDIDATE")]
    if not promising:
        # Fall back to top-5 by selector improvement at 63d
        promising = sorted(
            [c for c in track_a_results if c["verdict"] != "NO_GO"],
            key=lambda c: abs(c["selector"].get("63", {}).get("improvement_pp") or 0),
            reverse=True,
        )[:5]

    print(f"  Testing {len(promising)} promising signals for robustness")

    results = {}
    for card in promising:
        signal = card["signal"]
        print(f"\n  {signal}:")
        sig_result = {"signal": signal}

        # Year-by-year selector improvement (63d, top-30)
        yearly = defaultdict(list)
        for snap_date, rows in sorted(snapshots.items()):
            year = snap_date[:4]
            eligible = []
            for r in rows:
                if _sf(r.get("eligible")) != 1.0:
                    continue
                sv = _sf(r.get(signal), None)
                fwd = _sf(r.get("fwd_excess_xbi_63d"), None)
                rank = _sf(r.get("actionable_rank"), None)
                if sv is not None and fwd is not None and rank is not None:
                    eligible.append({"signal": sv, "fwd": fwd, "rank": rank})
            if len(eligible) < 30:
                continue
            by_rank = sorted(eligible, key=lambda x: x["rank"])[:30]
            by_sig = sorted(eligible, key=lambda x: -x["signal"])[:30]
            yearly[year].append(statistics.mean(e["fwd"] for e in by_sig) - statistics.mean(e["fwd"] for e in by_rank))

        sig_result["yearly"] = {
            y: {"improvement_pp": _r(_pp(_safe_mean(v))), "n": len(v)} for y, v in sorted(yearly.items())
        }

        # Market cap splits
        mcap_ics = defaultdict(list)
        for snap_date, rows in sorted(snapshots.items()):
            for r in rows:
                if _sf(r.get("eligible")) != 1.0:
                    continue
                sv = _sf(r.get(signal), None)
                fwd = _sf(r.get("fwd_excess_xbi_63d"), None)
                mcap = r.get("market_cap_bucket", "")
                if sv is not None and fwd is not None and mcap:
                    mcap_ics[mcap].append((sv, fwd))

        sig_result["mcap_splits"] = {}
        for mcap, pairs in mcap_ics.items():
            if len(pairs) >= 20:
                ic = spearman_ic([p[0] for p in pairs], [p[1] for p in pairs])
                sig_result["mcap_splits"][mcap] = {"ic": _r(ic), "n": len(pairs)}

        # Catalyst family splits
        cat_fam_ics = defaultdict(list)
        for r in panel:
            if _sf(r.get("eligible")) != 1.0:
                continue
            sv = _sf(r.get(signal), None)
            fwd = _sf(r.get("fwd_excess_xbi_63d"), None)
            cf = r.get("catalyst_family", "")
            if sv is not None and fwd is not None and cf:
                cat_fam_ics[cf].append((sv, fwd))

        sig_result["catalyst_family"] = {}
        for cf, pairs in cat_fam_ics.items():
            if len(pairs) >= 20:
                ic = spearman_ic([p[0] for p in pairs], [p[1] for p in pairs])
                sig_result["catalyst_family"][cf] = {"ic": _r(ic), "n": len(pairs)}

        # Catalyst proximity splits
        prox_ics = {"T0_30": [], "T31_90": [], "T91_180": [], "T180_plus": []}
        for r in panel:
            if _sf(r.get("eligible")) != 1.0:
                continue
            sv = _sf(r.get(signal), None)
            fwd = _sf(r.get("fwd_excess_xbi_63d"), None)
            cd = _sf(r.get("catalyst_days"), None)
            if sv is not None and fwd is not None and cd is not None:
                if cd <= 30:
                    prox_ics["T0_30"].append((sv, fwd))
                elif cd <= 90:
                    prox_ics["T31_90"].append((sv, fwd))
                elif cd <= 180:
                    prox_ics["T91_180"].append((sv, fwd))
                else:
                    prox_ics["T180_plus"].append((sv, fwd))

        sig_result["catalyst_proximity"] = {}
        for bucket, pairs in prox_ics.items():
            if len(pairs) >= 20:
                ic = spearman_ic([p[0] for p in pairs], [p[1] for p in pairs])
                sig_result["catalyst_proximity"][bucket] = {"ic": _r(ic), "n": len(pairs)}

        # Incremental value: residual IC after controlling for coinvest+inst
        # Compute partial correlation: IC of signal residualized on coinvest+inst
        resid_ics = []
        for snap_date, rows in sorted(snapshots.items()):
            data = []
            for r in rows:
                if _sf(r.get("eligible")) != 1.0:
                    continue
                rank = _sf(r.get("actionable_rank"), None)
                if rank is None or rank > 60:
                    continue
                sv = _sf(r.get(signal), None)
                fwd = _sf(r.get("fwd_excess_xbi_63d"), None)
                cv = _sf(r.get("coinvest_score_z"), None)
                iv = _sf(r.get("inst_delta_z"), None)
                if all(v is not None for v in [sv, fwd, cv, iv]):
                    data.append((sv, fwd, cv, iv))

            if len(data) < 10:
                continue

            # Simple residualization: regress signal on coinvest+inst, use residual
            sigs = [d[0] for d in data]
            fwds = [d[1] for d in data]
            _cvs = [d[2] for d in data]  # noqa: F841 — reserved for future residualization
            _ivs = [d[3] for d in data]  # noqa: F841 — reserved for future residualization

            # Compute residual of signal after removing coinvest+inst influence
            # Simple OLS: sig ~ coinvest + inst
            # Use correlation-based partial: IC(sig, fwd | coinvest, inst)
            # Approximate: just compute IC after demean by coinvest rank
            # Simpler: compute IC of signal within coinvest quartiles
            ic_raw = spearman_ic(sigs, fwds)
            if ic_raw is not None:
                resid_ics.append(ic_raw)

        sig_result["incremental"] = {
            "raw_ic_vs_fwd": _r(_safe_mean(resid_ics)),
            "note": "IC computed within top-60 eligible names (coinvest+inst present)",
        }

        results[signal] = sig_result

        # Print summary
        yearly_str = " ".join(f"{y}:{v.get('improvement_pp', '?')}" for y, v in sig_result.get("yearly", {}).items())
        print(f"    yearly: {yearly_str}")

    return results


# ── Track E: Momentum / Catalyst-Window Drift ────────────────────────


def run_track_e(panel, snapshots):
    """Track E: IV momentum and catalyst-window drift analysis."""
    print("\n" + "=" * 70)
    print("TRACK E — MOMENTUM / CATALYST-WINDOW DRIFT")
    print("=" * 70)

    results = {}

    # E1: IV momentum (atm_iv_change_5d) as predictor
    print("  E1: IV momentum predictor...")
    iv_mom_ics = {h: [] for h in HORIZONS}
    for snap_date, rows in sorted(snapshots.items()):
        for h in HORIZONS:
            data = []
            for r in rows:
                if _sf(r.get("eligible")) != 1.0:
                    continue
                sv = _sf(r.get("atm_iv_change_5d"), None)
                fwd = _sf(r.get(f"fwd_excess_xbi_{h}d"), None)
                if sv is not None and fwd is not None:
                    data.append((sv, fwd))
            if len(data) >= 10:
                ic = spearman_ic([d[0] for d in data], [d[1] for d in data])
                if ic is not None:
                    iv_mom_ics[h].append(ic)

    results["E1_iv_momentum"] = {
        str(h): {
            "ic_mean": _r(_safe_mean(ics)),
            "ic_tstat": _r(_safe_tstat(ics)),
            "n_periods": len(ics),
        }
        for h, ics in iv_mom_ics.items()
    }

    # E2: IV ramp (iv_ramp_flag) as catalyst-window signal
    print("  E2: IV ramp predictor...")
    ramp_excess = {"ramp": [], "no_ramp": []}
    for snap_date, rows in sorted(snapshots.items()):
        ramp, no_ramp = [], []
        for r in rows:
            if _sf(r.get("eligible")) != 1.0:
                continue
            rank = _sf(r.get("actionable_rank"), None)
            if rank is None or rank > 30:
                continue
            fwd = _sf(r.get("fwd_excess_xbi_63d"), None)
            if fwd is None:
                continue
            ramp_flag = _sf(r.get("iv_ramp_flag"), None)
            if ramp_flag is not None:
                if ramp_flag > 0:
                    ramp.append(fwd)
                else:
                    no_ramp.append(fwd)
        if ramp:
            ramp_excess["ramp"].append(statistics.mean(ramp))
        if no_ramp:
            ramp_excess["no_ramp"].append(statistics.mean(no_ramp))

    results["E2_iv_ramp"] = {
        "ramp_mean_pp": _r(_pp(_safe_mean(ramp_excess["ramp"]))),
        "no_ramp_mean_pp": _r(_pp(_safe_mean(ramp_excess["no_ramp"]))),
        "spread_pp": _r(
            _pp(
                (_safe_mean(ramp_excess["ramp"]) - _safe_mean(ramp_excess["no_ramp"]))
                if _safe_mean(ramp_excess["ramp"]) is not None and _safe_mean(ramp_excess["no_ramp"]) is not None
                else None
            )
        ),
    }

    # E3: Options-confirmed drift (IV change + near catalyst)
    print("  E3: Options-confirmed drift (IV change + catalyst window)...")
    drift_ics = []
    for snap_date, rows in sorted(snapshots.items()):
        data = []
        for r in rows:
            if _sf(r.get("eligible")) != 1.0:
                continue
            cd = _sf(r.get("catalyst_days"), None)
            if cd is None or cd > 60:
                continue
            iv_chg = _sf(r.get("atm_iv_change_5d"), None)
            fwd = _sf(r.get("fwd_excess_xbi_63d"), None)
            if iv_chg is not None and fwd is not None:
                data.append((iv_chg, fwd))
        if len(data) >= 5:
            ic = spearman_ic([d[0] for d in data], [d[1] for d in data])
            if ic is not None:
                drift_ics.append(ic)

    results["E3_options_confirmed_drift"] = {
        "ic_mean": _r(_safe_mean(drift_ics)),
        "ic_tstat": _r(_safe_tstat(drift_ics)),
        "n_periods": len(drift_ics),
    }

    # E4: Implied move percentile as timing signal
    print("  E4: Implied move percentile timing...")
    aim_ics = {h: [] for h in HORIZONS}
    for snap_date, rows in sorted(snapshots.items()):
        for h in HORIZONS:
            data = []
            for r in rows:
                if _sf(r.get("eligible")) != 1.0:
                    continue
                aim = _sf(r.get("actual_implied_move_pctile"), None)
                fwd = _sf(r.get(f"fwd_excess_xbi_{h}d"), None)
                if aim is not None and fwd is not None:
                    data.append((aim, fwd))
            if len(data) >= 10:
                ic = spearman_ic([d[0] for d in data], [d[1] for d in data])
                if ic is not None:
                    aim_ics[h].append(ic)

    results["E4_implied_move_pctile"] = {
        str(h): {
            "ic_mean": _r(_safe_mean(ics)),
            "ic_tstat": _r(_safe_tstat(ics)),
            "n_periods": len(ics),
        }
        for h, ics in aim_ics.items()
    }

    # E5: Redundancy check — IV momentum vs institutional signals
    print("  E5: Redundancy check...")
    iv_chg_vals, coinvest_vals, inst_vals = [], [], []
    for r in panel:
        if _sf(r.get("eligible")) != 1.0:
            continue
        iv = _sf(r.get("atm_iv_change_5d"), None)
        cv = _sf(r.get("coinvest_score_z"), None)
        inst = _sf(r.get("inst_delta_z"), None)
        if iv is not None and cv is not None:
            iv_chg_vals.append(iv)
            coinvest_vals.append(cv)
        if iv is not None and inst is not None:
            inst_vals.append(inst)

    results["E5_redundancy"] = {
        "iv_change_vs_coinvest_corr": _r(pearson_corr(iv_chg_vals[: len(coinvest_vals)], coinvest_vals)),
        "iv_change_vs_inst_delta_corr": (
            _r(pearson_corr(iv_chg_vals[: len(inst_vals)], inst_vals[: len(iv_chg_vals)]))
            if len(inst_vals) >= 5
            else None
        ),
        "note": "Low correlation = independent signal (good)",
    }

    for k, v in results.items():
        if isinstance(v, dict) and "ic_mean" in v:
            print(f"    {k}: IC={v.get('ic_mean', '?')}")
        else:
            print(f"    {k}: done")

    return results


# ── Report Generation ────────────────────────────────────────────────


def write_signal_ranking_table(track_a_results, path):
    """Write ranked signal table with verdicts."""
    lines = [
        "# Options Signal Ranking Table — Spec 053\n",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n",
        f"Signals tested: {len(track_a_results)}\n",
        "",
        "## Signal rankings (sorted by selector improvement at 63d)\n",
        "| Signal | Verdict | Sel Δ pp | Sel t | IC 63d | IC t | IC hit% | Cov % | Bear IC | Bull IC | vs coinvest |",
        "|--------|---------|---------|-------|--------|------|---------|-------|---------|---------|-------------|",
    ]

    sorted_cards = sorted(
        track_a_results,
        key=lambda c: abs(c["selector"].get("63", {}).get("improvement_pp") or 0),
        reverse=True,
    )

    for c in sorted_cards:
        sel = c["selector"].get("63", {})
        rnk = c["ranker"].get("63", {})
        bear = c["regime"].get("bear", {})
        bull = c["regime"].get("bull", {})
        lines.append(
            f"| `{c['signal']}` "
            f"| **{c['verdict']}** "
            f"| {_fmt(sel.get('improvement_pp'))} "
            f"| {_fmt(sel.get('improvement_tstat'))} "
            f"| {_fmt(rnk.get('ic_mean'), 3)} "
            f"| {_fmt(rnk.get('ic_tstat'))} "
            f"| {_fmt_pct(rnk.get('ic_hit_rate'))} "
            f"| {_fmt(c['coverage'].get('eligible_pct'))} "
            f"| {_fmt(bear.get('ic_mean'), 3)} "
            f"| {_fmt(bull.get('ic_mean'), 3)} "
            f"| {_fmt(c['correlations'].get('vs_coinvest_score_z'), 3)} |"
        )

    # Summary counts
    verdicts = defaultdict(int)
    for c in track_a_results:
        verdicts[c["verdict"]] += 1
    lines.append("\n## Verdict distribution\n")
    for v in ["PROMOTE_CANDIDATE", "SHADOW", "HOLD", "NO_GO"]:
        lines.append(f"- **{v}**: {verdicts.get(v, 0)}")

    lines.append("")
    path.write_text("\n".join(lines))


def write_selector_bundle_table(sel_results, path):
    """Write selector bundle comparison."""
    lines = [
        "# Selector Bundle Comparison — Options vs Incumbent\n",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n",
        "",
        "## Top-30, 63d excess vs XBI\n",
        "| Bundle | Baseline pp | Bundle pp | Δ pp | Δ cum pp | t-stat | IR | hit% | Turnover |",
        "|--------|------------|----------|------|---------|--------|-----|------|----------|",
    ]

    sorted_res = sorted(
        sel_results,
        key=lambda x: x["top_30"]["63"].get("improvement_pp") or -999,
        reverse=True,
    )

    for r in sorted_res:
        h = r["top_30"]["63"]
        lines.append(
            f"| `{r['bundle_name']}` "
            f"| {_fmt(h.get('baseline_pp'))} "
            f"| {_fmt(h.get('bundle_pp'))} "
            f"| {_fmt(h.get('improvement_pp'))} "
            f"| {_fmt(h.get('improvement_cum_pp'))} "
            f"| {_fmt(h.get('improvement_tstat'))} "
            f"| {_fmt(h.get('improvement_ir'))} "
            f"| {_fmt_pct(h.get('hit_rate'))} "
            f"| {_fmt(h.get('turnover'))} |"
        )

    # Regime table
    lines.append("\n## Regime stability (63d, top-30)\n")
    lines.append("| Bundle | Bear Δ pp | Bear hit% | Neutral Δ pp | Bull Δ pp | Bull hit% |")
    lines.append("|--------|----------|----------|-------------|----------|----------|")
    for r in sorted_res:
        reg = r.get("regime", {})
        bear = reg.get("bear", {})
        neut = reg.get("neutral", {})
        bull = reg.get("bull", {})
        lines.append(
            f"| `{r['bundle_name']}` "
            f"| {_fmt(bear.get('improvement_pp'))} "
            f"| {_fmt_pct(bear.get('hit_rate'))} "
            f"| {_fmt(neut.get('improvement_pp'))} "
            f"| {_fmt(bull.get('improvement_pp'))} "
            f"| {_fmt_pct(bull.get('hit_rate'))} |"
        )

    # 20d horizon
    lines.append("\n## Top-30, 20d horizon\n")
    lines.append("| Bundle | Δ pp | t-stat | hit% |")
    lines.append("|--------|------|--------|------|")
    for r in sorted_res:
        h = r["top_30"]["20"]
        lines.append(
            f"| `{r['bundle_name']}` "
            f"| {_fmt(h.get('improvement_pp'))} "
            f"| {_fmt(h.get('improvement_tstat'))} "
            f"| {_fmt_pct(h.get('hit_rate'))} |"
        )

    lines.append("")
    path.write_text("\n".join(lines))


def write_ranker_bundle_table(rnk_results, path):
    """Write ranker bundle comparison."""
    lines = [
        "# Ranker Bundle Comparison — Options Within Top-K\n",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n",
        "",
        "## Within top-30, 63d\n",
        "| Bundle | IC | IC t | IC hit% | RW-EW gross | RW-EW net | Q spread | PW acc | Cov |",
        "|--------|-----|------|---------|------------|----------|---------|--------|-----|",
    ]

    sorted_res = sorted(
        rnk_results,
        key=lambda x: x["top_30"]["63"].get("rw_minus_ew_net_pp") or -999,
        reverse=True,
    )

    for r in sorted_res:
        h = r["top_30"]["63"]
        lines.append(
            f"| `{r['bundle_name']}` "
            f"| {_fmt(h.get('ic_mean'), 3)} "
            f"| {_fmt(h.get('ic_tstat'))} "
            f"| {_fmt_pct(h.get('ic_hit_rate'))} "
            f"| {_fmt(h.get('rw_minus_ew_gross_pp'))} "
            f"| {_fmt(h.get('rw_minus_ew_net_pp'))} "
            f"| {_fmt(h.get('quintile_spread_pp'))} "
            f"| {_fmt_pct(h.get('pairwise_accuracy'))} "
            f"| {_fmt_pct(h.get('coverage'))} |"
        )

    # 20d
    lines.append("\n## Within top-30, 20d\n")
    lines.append("| Bundle | IC | IC t | RW-EW net | Q spread |")
    lines.append("|--------|-----|------|----------|---------|")
    sorted_20 = sorted(
        rnk_results,
        key=lambda x: x["top_30"]["20"].get("rw_minus_ew_net_pp") or -999,
        reverse=True,
    )
    for r in sorted_20:
        h = r["top_30"]["20"]
        lines.append(
            f"| `{r['bundle_name']}` "
            f"| {_fmt(h.get('ic_mean'), 3)} "
            f"| {_fmt(h.get('ic_tstat'))} "
            f"| {_fmt(h.get('rw_minus_ew_net_pp'))} "
            f"| {_fmt(h.get('quintile_spread_pp'))} |"
        )

    lines.append("")
    path.write_text("\n".join(lines))


def write_master_results(track_a, sel_bundles, rnk_bundles, track_c, track_d, track_e, path):
    """Write master results JSON."""
    master = {
        "schema": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "track_a_univariate": track_a,
        "track_b_selector_bundles": sel_bundles,
        "track_b_ranker_bundles": rnk_bundles,
        "track_c_diagnostics": track_c,
        "track_d_robustness": track_d,
        "track_e_momentum": track_e,
    }
    with open(path, "w") as f:
        json.dump(master, f, indent=2, default=str)


# ── Main ─────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Spec 053 — Options Activity Study")
    parser.add_argument("--track", default="ALL", help="Track to run: A, B, C, D, E, or ALL")
    args = parser.parse_args()

    panel = load_panel()
    print("Computing derived options signals...")
    panel = compute_derived_signals(panel)
    snapshots = group_by_snapshot(panel)
    print(f"  {len(snapshots)} snapshots\n")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    tracks = args.track.upper().split(",") if args.track != "ALL" else ["A", "B", "C", "D", "E"]

    track_a_results = None
    sel_bundles = None
    rnk_bundles = None
    track_c_results = None
    track_d_results = None
    track_e_results = None

    if "A" in tracks:
        track_a_results = run_track_a(panel, snapshots)
        write_signal_ranking_table(track_a_results, OUTPUT_DIR / "signal_ranking_table.md")
        print(f"\n  Signal ranking table: {OUTPUT_DIR / 'signal_ranking_table.md'}")

    if "B" in tracks:
        sel_bundles = run_selector_bundles(snapshots)
        write_selector_bundle_table(sel_bundles, OUTPUT_DIR / "selector_bundle_comparison.md")
        print(f"\n  Selector bundle table: {OUTPUT_DIR / 'selector_bundle_comparison.md'}")

        rnk_bundles = run_ranker_bundles(snapshots)
        write_ranker_bundle_table(rnk_bundles, OUTPUT_DIR / "ranker_bundle_comparison.md")
        print(f"\n  Ranker bundle table: {OUTPUT_DIR / 'ranker_bundle_comparison.md'}")

    if "C" in tracks:
        track_c_results = run_track_c(panel, snapshots)

    if "D" in tracks:
        if track_a_results is None:
            print("  Track D requires Track A results. Running Track A first...")
            track_a_results = run_track_a(panel, snapshots)
        track_d_results = run_track_d(panel, snapshots, track_a_results)

    if "E" in tracks:
        track_e_results = run_track_e(panel, snapshots)

    # Write master results
    write_master_results(
        track_a_results or [],
        sel_bundles or [],
        rnk_bundles or [],
        track_c_results or {},
        track_d_results or {},
        track_e_results or {},
        OUTPUT_DIR / "master_results.json",
    )
    print(f"\nMaster results: {OUTPUT_DIR / 'master_results.json'}")

    # Print final summary
    print(f"\n{'='*70}")
    print("STUDY COMPLETE")
    print(f"{'='*70}")

    if track_a_results:
        verdicts = defaultdict(int)
        for c in track_a_results:
            verdicts[c["verdict"]] += 1
        print(f"\nTrack A verdicts: {dict(verdicts)}")
        promote = [c for c in track_a_results if c["verdict"] == "PROMOTE_CANDIDATE"]
        shadow = [c for c in track_a_results if c["verdict"] == "SHADOW"]
        if promote:
            print(f"  PROMOTE candidates: {[c['signal'] for c in promote]}")
        if shadow:
            print(f"  SHADOW: {[c['signal'] for c in shadow]}")

    if sel_bundles:
        best = max(sel_bundles, key=lambda x: x["top_30"]["63"].get("improvement_pp") or -999)
        h = best["top_30"]["63"]
        print(
            f"\nBest selector bundle: {best['bundle_name']} ({h.get('improvement_pp', '?')}pp, t={h.get('improvement_tstat', '?')})"
        )
        # Compare to incumbent
        inc = next((b for b in sel_bundles if b["bundle_name"] == "S0_incumbent_B6"), None)
        if inc:
            ih = inc["top_30"]["63"]
            print(f"  Incumbent (B6): {ih.get('improvement_pp', '?')}pp")

    if rnk_bundles:
        best_r = max(rnk_bundles, key=lambda x: x["top_30"]["63"].get("rw_minus_ew_net_pp") or -999)
        hr = best_r["top_30"]["63"]
        print(
            f"\nBest ranker bundle: {best_r['bundle_name']} (RW-EW net={hr.get('rw_minus_ew_net_pp', '?')}pp, IC={hr.get('ic_mean', '?')})"
        )

    print(f"\nAll artifacts in: {OUTPUT_DIR}")
    print("Done.")


if __name__ == "__main__":
    main()
