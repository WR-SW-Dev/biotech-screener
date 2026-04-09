#!/usr/bin/env python3
"""Spec 049 Phase 4 — Ranker bundle tests (within top-K only).

Tests whether signal bundles can improve ordering INSIDE the DEM top-K.
For each snapshot, takes the actual top-K (by actionable_rank), re-ranks
by bundle score, and compares rank-weighted vs equal-weighted returns.

The key question: does any bundle beat EW top-K net of costs?

Usage:
    python3 scripts/research/test_ranker_bundles.py
    python3 scripts/research/test_ranker_bundles.py --top-n 20
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
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

PANEL_CSV = PROJECT_ROOT / "output" / "signals" / "research_panel.csv"
OUTPUT_DIR = PROJECT_ROOT / "output" / "signals"

SCHEMA_VERSION = "ranker_bundle.v1"

# Cost model (from ranker_evaluation_harness.py)
RW_EXTRA_COST_BPS_YR = 65
MONTHLY_COST_DRAG = RW_EXTRA_COST_BPS_YR / 12 / 10_000  # ~0.000542 decimal/mo

# ── Ranker bundle definitions ────────────────────────────────────────
# Each bundle: {signal_name: (weight, higher_is_better)}
# Tested ONLY within the actual DEM top-K.

BUNDLES = {
    # --- Single signals (top Phase 2 winners) ---
    "R1_coinvest_only": {
        "coinvest_score_z": (1.0, True),
    },
    "R2_inst_delta_only": {
        "inst_delta_z": (1.0, True),
    },
    "R3_ovf11_only": {
        "ovf11_score": (1.0, True),
    },
    "R4_aact_only": {
        "aact_execution_score": (1.0, True),
    },
    "R5_cheap_vol_only": {
        "cheap_vol_score": (1.0, True),
    },
    "R6_opt_rr25d_only": {
        "opt_rr_25d": (1.0, True),
    },
    # --- Smart-money combinations ---
    "R7_coinvest_inst": {
        "coinvest_score_z": (0.65, True),
        "inst_delta_z": (0.35, True),
    },
    # --- Options bundles ---
    "R8_options_full": {
        "ovf11_score": (0.30, True),
        "cheap_vol_score": (0.25, True),
        "opt_rr_25d": (0.20, True),
        "opt_put_call_skew": (0.15, True),
        "opt_term_slope": (0.10, True),
    },
    "R9_options_slim": {
        "ovf11_score": (0.40, True),
        "cheap_vol_score": (0.35, True),
        "opt_rr_25d": (0.25, True),
    },
    # --- AACT + execution ---
    "R10_aact_inst": {
        "aact_execution_score": (0.50, True),
        "inst_delta_z": (0.50, True),
    },
    # --- Spec 049 baseline ranker ---
    "R11_spec049_baseline": {
        "ovf11_score": (0.20, True),
        "cheap_vol_score": (0.15, True),
        "coinvest_score_z": (0.25, True),
        "inst_delta_z": (0.15, True),
        "aact_execution_score": (0.15, True),
        "opt_rr_25d": (0.10, True),
    },
    # --- Data-driven top combo ---
    "R12_top3_winners": {
        "coinvest_score_z": (0.45, True),
        "ovf11_score": (0.30, True),
        "inst_delta_z": (0.25, True),
    },
    # --- Production comparator ---
    "R13_composite_score": {
        "composite_score": (1.0, True),
    },
    "R14_de_sort_total": {
        "de_sort_total_adj": (1.0, True),
    },
    # --- Clinical anchor (negative control) ---
    "R15_clinical_only": {
        "clinical_score_v2_z": (1.0, True),
    },
}


# ── Helpers ───────────────────────────────────────────────────────────


def _sf(v, default=float("nan")):
    if v is None or v == "":
        return default
    try:
        f = float(v)
        return f if not math.isnan(f) else default
    except (ValueError, TypeError):
        return default


def _safe_mean(v):
    return statistics.mean(v) if v else None


def _safe_stdev(v):
    return statistics.stdev(v) if len(v) >= 2 else None


def _safe_ir(v):
    if len(v) < 2:
        return None
    m, s = statistics.mean(v), statistics.stdev(v)
    return m / s if s > 1e-9 else None


def _safe_tstat(v):
    if len(v) < 2:
        return None
    m, s = statistics.mean(v), statistics.stdev(v)
    return m / (s / len(v) ** 0.5) if s > 1e-9 else None


def _hit_rate(v):
    return sum(1 for x in v if x > 0) / len(v) if v else None


def _r(v, d=4):
    if v is None:
        return None
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return round(v, d)


def _pp(v):
    return v * 100 if v is not None else None


def _fmt(v, d=2):
    return f"{v:.{d}f}" if v is not None else "—"


def _fmt_pct(v):
    if v is None:
        return "—"
    return f"{v*100:.0f}%" if isinstance(v, float) and v <= 1.0 else f"{v:.0f}%"


def spearman_ic(x: List[float], y: List[float]) -> Optional[float]:
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


# ── Z-scoring within top-K ───────────────────────────────────────────


def zscore_topk(
    topk: List[Dict[str, Any]],
    signal: str,
) -> Dict[str, float]:
    """Z-score a signal across top-K names only."""
    vals = []
    tickers = []
    for t in topk:
        v = t.get(signal)
        if v is not None:
            vals.append(v)
            tickers.append(t["ticker"])

    if len(vals) < 3:
        return {}

    m = statistics.mean(vals)
    s = statistics.stdev(vals) if len(vals) >= 2 else 1.0
    if s < 1e-9:
        s = 1.0

    return {tickers[i]: (vals[i] - m) / s for i in range(len(tickers))}


def compute_bundle_score_topk(
    topk: List[Dict[str, Any]],
    bundle: Dict[str, Tuple[float, bool]],
) -> Dict[str, float]:
    """Compute weighted bundle score within top-K names."""
    z_maps = {}
    for signal in bundle:
        z_maps[signal] = zscore_topk(topk, signal)

    scores = {}
    for t in topk:
        ticker = t["ticker"]
        total = 0.0
        total_w = 0.0
        for signal, (weight, higher_better) in bundle.items():
            z = z_maps.get(signal, {}).get(ticker)
            if z is not None:
                if not higher_better:
                    z = -z
                total += weight * z
                total_w += weight
        scores[ticker] = total / total_w if total_w > 0 else 0.0

    return scores


# ── Core evaluation ───────────────────────────────────────────────────


def evaluate_ranker_bundle(
    snapshots: Dict[str, List[Dict[str, str]]],
    bundle_name: str,
    bundle: Dict[str, Tuple[float, bool]],
    horizons: List[int],
    top_ns: List[int],
) -> Dict[str, Any]:
    """Evaluate a ranker bundle within top-K across all snapshots."""
    result: Dict[str, Any] = {
        "bundle_name": bundle_name,
        "signals": {s: {"weight": w, "higher_is_better": h} for s, (w, h) in bundle.items()},
        "top_ns": {},
    }

    for top_n in top_ns:
        result["top_ns"][str(top_n)] = {"horizons": {}}

        for h in horizons:
            fwd_col = f"fwd_ret_{h}d"
            fwd_xbi_col = f"fwd_excess_xbi_{h}d"

            ic_vals: List[float] = []
            ew_rets: List[float] = []
            rw_rets: List[float] = []
            rw_minus_ew: List[float] = []
            top_q_rets: List[float] = []
            bot_q_rets: List[float] = []
            ew_excess_xbi: List[float] = []
            rw_excess_xbi: List[float] = []
            coverage_vals: List[float] = []
            pairwise_wins: List[float] = []
            n_periods = 0

            for snap_date in sorted(snapshots.keys()):
                rows = snapshots[snap_date]

                # Extract actual top-K with returns
                topk = []
                for r in rows:
                    rank_val = _sf(r.get("actionable_rank"), default=None)
                    if rank_val is None or rank_val > top_n:
                        continue
                    if _sf(r.get("eligible")) != 1.0:
                        continue
                    fwd = _sf(r.get(fwd_col), default=None)
                    fwd_xbi = _sf(r.get(fwd_xbi_col), default=None)
                    if fwd is None:
                        continue

                    ticker = r.get("ticker", "")
                    entry = {"ticker": ticker, "fwd": fwd, "fwd_xbi": fwd_xbi}
                    # Attach raw signal values
                    for signal in bundle:
                        entry[signal] = _sf(r.get(signal), default=None)
                    topk.append(entry)

                if len(topk) < 5:
                    continue

                # Coverage: how many top-K names have all bundle signals?
                with_all = [t for t in topk if all(t.get(s) is not None for s in bundle)]
                cov = len(with_all) / len(topk)
                coverage_vals.append(cov)

                if len(with_all) < 5:
                    continue

                n_periods += 1

                # EW return (all top-K)
                ew = statistics.mean(t["fwd"] for t in topk)
                ew_rets.append(ew)

                xbi_vals = [t["fwd_xbi"] for t in topk if t["fwd_xbi"] is not None]
                if xbi_vals:
                    ew_excess_xbi.append(statistics.mean(xbi_vals))

                # Bundle scores within top-K
                scores = compute_bundle_score_topk(with_all, bundle)

                # IC: bundle score vs forward return
                ic = spearman_ic(
                    [scores[t["ticker"]] for t in with_all],
                    [t["fwd"] for t in with_all],
                )
                if ic is not None:
                    ic_vals.append(ic)

                # Rank-weighted return
                sorted_by_score = sorted(with_all, key=lambda x: -scores[x["ticker"]])
                n_s = len(sorted_by_score)
                weights = [(n_s - i) for i in range(n_s)]
                w_sum = sum(weights)
                rw = sum(weights[i] * sorted_by_score[i]["fwd"] for i in range(n_s)) / w_sum
                rw_rets.append(rw)
                rw_minus_ew.append(rw - ew)

                rw_xbi_vals = [
                    sorted_by_score[i]["fwd_xbi"] for i in range(n_s) if sorted_by_score[i]["fwd_xbi"] is not None
                ]
                if rw_xbi_vals:
                    rw_weighted_xbi = (
                        sum(
                            weights[i] * sorted_by_score[i]["fwd_xbi"]
                            for i in range(n_s)
                            if sorted_by_score[i]["fwd_xbi"] is not None
                        )
                        / w_sum
                    )
                    rw_excess_xbi.append(rw_weighted_xbi)

                # Quintile spread
                q_size = max(1, n_s // 5)
                top_q = sorted_by_score[:q_size]
                bot_q = sorted_by_score[-q_size:]
                top_q_rets.append(statistics.mean(t["fwd"] for t in top_q))
                bot_q_rets.append(statistics.mean(t["fwd"] for t in bot_q))

                # Pairwise accuracy
                n_correct = 0
                n_total = 0
                for i in range(len(sorted_by_score)):
                    for j in range(i + 1, len(sorted_by_score)):
                        n_total += 1
                        si = scores[sorted_by_score[i]["ticker"]]
                        sj = scores[sorted_by_score[j]["ticker"]]
                        ri = sorted_by_score[i]["fwd"]
                        rj = sorted_by_score[j]["fwd"]
                        if (si > sj and ri > rj) or (si < sj and ri < rj):
                            n_correct += 1
                if n_total > 0:
                    pairwise_wins.append(n_correct / n_total)

            # Net of costs
            rw_ew_gross = _safe_mean(rw_minus_ew)
            rw_ew_net = (rw_ew_gross - MONTHLY_COST_DRAG) if rw_ew_gross is not None else None

            # Quintile spread
            top_q_mean = _safe_mean(top_q_rets)
            bot_q_mean = _safe_mean(bot_q_rets)
            q_spread = (top_q_mean - bot_q_mean) if (top_q_mean is not None and bot_q_mean is not None) else None

            result["top_ns"][str(top_n)]["horizons"][str(h)] = {
                "ic_mean": _r(_safe_mean(ic_vals)),
                "ic_tstat": _r(_safe_tstat(ic_vals)),
                "ic_hit_rate": _r(_hit_rate(ic_vals)),
                "ic_n": len(ic_vals),
                "ew_mean_ret_pp": _r(_pp(_safe_mean(ew_rets))),
                "rw_mean_ret_pp": _r(_pp(_safe_mean(rw_rets))),
                "rw_minus_ew_gross_pp": _r(_pp(rw_ew_gross)),
                "rw_minus_ew_net_pp": _r(_pp(rw_ew_net)),
                "rw_minus_ew_cum_gross_pp": _r(_pp(sum(rw_minus_ew)) if rw_minus_ew else None),
                "rw_minus_ew_cum_net_pp": _r(
                    _pp(sum(rw_minus_ew) - MONTHLY_COST_DRAG * len(rw_minus_ew)) if rw_minus_ew else None
                ),
                "ew_excess_xbi_pp": _r(_pp(_safe_mean(ew_excess_xbi))),
                "rw_excess_xbi_pp": _r(_pp(_safe_mean(rw_excess_xbi))),
                "quintile_top_pp": _r(_pp(top_q_mean)),
                "quintile_bot_pp": _r(_pp(bot_q_mean)),
                "quintile_spread_pp": _r(_pp(q_spread)),
                "pairwise_accuracy": _r(_safe_mean(pairwise_wins)),
                "signal_coverage": _r(_safe_mean(coverage_vals)),
                "n_periods": n_periods,
            }

    return result


def evaluate_ranker_regime(
    snapshots: Dict[str, List[Dict[str, str]]],
    bundle: Dict[str, Tuple[float, bool]],
    top_n: int,
) -> Dict[str, Any]:
    """Regime-split ranker evaluation at 63d."""
    result = {}

    for regime_label in ["bear", "neutral", "bull"]:
        ic_vals: List[float] = []
        rw_ew_vals: List[float] = []
        pw_vals: List[float] = []
        n_periods = 0

        for snap_date, rows in sorted(snapshots.items()):
            sample_regime = None
            for r in rows:
                sample_regime = r.get("regime_63d")
                if sample_regime:
                    break
            if sample_regime != regime_label:
                continue

            topk = []
            for r in rows:
                rank_val = _sf(r.get("actionable_rank"), default=None)
                if rank_val is None or rank_val > top_n:
                    continue
                if _sf(r.get("eligible")) != 1.0:
                    continue
                fwd = _sf(r.get("fwd_ret_63d"), default=None)
                if fwd is None:
                    continue
                entry = {"ticker": r.get("ticker", ""), "fwd": fwd}
                for signal in bundle:
                    entry[signal] = _sf(r.get(signal), default=None)
                topk.append(entry)

            with_all = [t for t in topk if all(t.get(s) is not None for s in bundle)]
            if len(with_all) < 5:
                continue

            n_periods += 1
            ew = statistics.mean(t["fwd"] for t in topk)
            scores = compute_bundle_score_topk(with_all, bundle)

            ic = spearman_ic(
                [scores[t["ticker"]] for t in with_all],
                [t["fwd"] for t in with_all],
            )
            if ic is not None:
                ic_vals.append(ic)

            sorted_by_score = sorted(with_all, key=lambda x: -scores[x["ticker"]])
            n_s = len(sorted_by_score)
            weights = [(n_s - i) for i in range(n_s)]
            w_sum = sum(weights)
            rw = sum(weights[i] * sorted_by_score[i]["fwd"] for i in range(n_s)) / w_sum
            rw_ew_vals.append(rw - ew)

            # Pairwise
            n_correct = n_total = 0
            for i in range(n_s):
                for j in range(i + 1, n_s):
                    n_total += 1
                    if (
                        scores[sorted_by_score[i]["ticker"]] > scores[sorted_by_score[j]["ticker"]]
                        and sorted_by_score[i]["fwd"] > sorted_by_score[j]["fwd"]
                    ):
                        n_correct += 1
                    elif (
                        scores[sorted_by_score[i]["ticker"]] < scores[sorted_by_score[j]["ticker"]]
                        and sorted_by_score[i]["fwd"] < sorted_by_score[j]["fwd"]
                    ):
                        n_correct += 1
            if n_total > 0:
                pw_vals.append(n_correct / n_total)

        result[regime_label] = {
            "n_periods": n_periods,
            "ic_mean": _r(_safe_mean(ic_vals)),
            "ic_hit_rate": _r(_hit_rate(ic_vals)),
            "rw_minus_ew_pp": _r(_pp(_safe_mean(rw_ew_vals))),
            "pairwise_accuracy": _r(_safe_mean(pw_vals)),
        }

    return result


# ── Output ────────────────────────────────────────────────────────────


def write_ranker_report(
    results: List[Dict[str, Any]],
    regime_results: Dict[str, Dict[str, Any]],
    path: Path,
    top_n: int,
) -> None:
    """Write the ranker bundle comparison report."""
    lines = [
        "# Ranker Bundle Report — Spec 049 Phase 4\n",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}  ",
        f"Bundles tested: {len(results)}  ",
        f"Evaluation: within DEM top-{top_n} (by actionable_rank)  ",
        f"Question: can any bundle beat EW top-{top_n} net of costs?\n",
    ]

    # Main table at 63d
    lines.append(f"## Ranker comparison (within top-{top_n}, 63d)\n")
    lines.append("| Bundle | IC | IC t | IC hit% | RW−EW gross | RW−EW net | Q spread | Pairwise | Cov | N |")
    lines.append("|--------|-----|------|---------|------------|----------|---------|---------|-----|---|")

    sorted_results = sorted(
        results,
        key=lambda x: x["top_ns"][str(top_n)]["horizons"].get("63", {}).get("rw_minus_ew_net_pp") or -999,
        reverse=True,
    )

    for r in sorted_results:
        h = r["top_ns"][str(top_n)]["horizons"].get("63", {})
        lines.append(
            f"| `{r['bundle_name']}` "
            f"| {_fmt(h.get('ic_mean'))} "
            f"| {_fmt(h.get('ic_tstat'))} "
            f"| {_fmt_pct(h.get('ic_hit_rate'))} "
            f"| {_fmt(h.get('rw_minus_ew_gross_pp'))} "
            f"| {_fmt(h.get('rw_minus_ew_net_pp'))} "
            f"| {_fmt(h.get('quintile_spread_pp'))} "
            f"| {_fmt_pct(h.get('pairwise_accuracy'))} "
            f"| {_fmt_pct(h.get('signal_coverage'))} "
            f"| {h.get('n_periods', 0)} |"
        )

    # 20d table
    lines.append(f"\n## 20d horizon (within top-{top_n})\n")
    lines.append("| Bundle | IC | IC t | RW−EW gross | RW−EW net | Q spread | N |")
    lines.append("|--------|-----|------|------------|----------|---------|---|")

    sorted_20 = sorted(
        results,
        key=lambda x: x["top_ns"][str(top_n)]["horizons"].get("20", {}).get("rw_minus_ew_net_pp") or -999,
        reverse=True,
    )
    for r in sorted_20:
        h = r["top_ns"][str(top_n)]["horizons"].get("20", {})
        lines.append(
            f"| `{r['bundle_name']}` "
            f"| {_fmt(h.get('ic_mean'))} "
            f"| {_fmt(h.get('ic_tstat'))} "
            f"| {_fmt(h.get('rw_minus_ew_gross_pp'))} "
            f"| {_fmt(h.get('rw_minus_ew_net_pp'))} "
            f"| {_fmt(h.get('quintile_spread_pp'))} "
            f"| {h.get('n_periods', 0)} |"
        )

    # Cumulative net spread
    lines.append(f"\n## Cumulative net RW−EW spread (top-{top_n})\n")
    lines.append("| Bundle | Cum 20d (pp) | Cum 63d (pp) |")
    lines.append("|--------|-------------|-------------|")
    for r in sorted_results:
        h20 = r["top_ns"][str(top_n)]["horizons"].get("20", {})
        h63 = r["top_ns"][str(top_n)]["horizons"].get("63", {})
        lines.append(
            f"| `{r['bundle_name']}` "
            f"| {_fmt(h20.get('rw_minus_ew_cum_net_pp'))} "
            f"| {_fmt(h63.get('rw_minus_ew_cum_net_pp'))} |"
        )

    # Compositions
    lines.append("\n## Bundle compositions\n")
    for r in sorted_results:
        sig_str = ", ".join(f"`{s}` ({info['weight']:.0%})" for s, info in r["signals"].items())
        lines.append(f"- **{r['bundle_name']}**: {sig_str}")

    # Regime stability
    lines.append(f"\n## Regime stability (63d, within top-{top_n})\n")
    lines.append("| Bundle | Bear IC | Bear RW−EW | Bear PW | Bull IC | Bull RW−EW | Bull PW |")
    lines.append("|--------|---------|-----------|---------|---------|-----------|---------|")
    for r in sorted_results:
        name = r["bundle_name"]
        reg = regime_results.get(name, {})
        bear = reg.get("bear", {})
        bull = reg.get("bull", {})
        lines.append(
            f"| `{name}` "
            f"| {_fmt(bear.get('ic_mean'))} "
            f"| {_fmt(bear.get('rw_minus_ew_pp'))} "
            f"| {_fmt_pct(bear.get('pairwise_accuracy'))} "
            f"| {_fmt(bull.get('ic_mean'))} "
            f"| {_fmt(bull.get('rw_minus_ew_pp'))} "
            f"| {_fmt_pct(bull.get('pairwise_accuracy'))} |"
        )

    # Promotion assessment
    lines.append("\n## Promotion assessment\n")
    lines.append("Promotion bar (from Spec 049):")
    lines.append("- Top-K IC positive and stable")
    lines.append("- RW top-K beats EW top-K net of costs (~65bps/yr)")
    lines.append("- Survives regime splits")
    lines.append("- Economically material (≥ +0.20pp/mo improvement)\n")

    for r in sorted_results:
        name = r["bundle_name"]
        h63 = r["top_ns"][str(top_n)]["horizons"].get("63", {})
        ic = h63.get("ic_mean")
        rw_net = h63.get("rw_minus_ew_net_pp")
        reg = regime_results.get(name, {})
        bear_ic = reg.get("bear", {}).get("ic_mean")
        bull_ic = reg.get("bull", {}).get("ic_mean")

        checks = []
        if ic is not None and ic > 0:
            checks.append("IC+")
        else:
            checks.append("IC−")
        if rw_net is not None and rw_net > 0:
            checks.append("RW+")
        else:
            checks.append("RW−")
        if bear_ic is not None and bull_ic is not None and bear_ic > -0.05 and bull_ic > -0.05:
            checks.append("Regime OK")
        else:
            checks.append("Regime FAIL")
        if rw_net is not None and rw_net >= 0.20:
            checks.append("Material")
        else:
            checks.append("Immaterial")

        all_pass = all(c in ("IC+", "RW+", "Regime OK", "Material") for c in checks)
        verdict = (
            "**PROMOTE**" if all_pass else "SHADOW" if checks.count("IC+") + checks.count("RW+") >= 2 else "REJECT"
        )
        lines.append(f"- `{name}`: {' | '.join(checks)} → {verdict}")

    lines.append("")
    path.write_text("\n".join(lines))


# ── Main ──────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Ranker bundle tests (Spec 049 Phase 4)")
    parser.add_argument("--top-n", type=int, default=30, help="Top-N for ranking (default: 30)")
    parser.add_argument("--horizons", default="20,63", help="Horizons (comma-separated)")
    args = parser.parse_args()

    horizons = [int(h) for h in args.horizons.split(",")]
    top_ns = [20, args.top_n] if args.top_n != 20 else [20]

    print("Loading research panel...")
    with open(PANEL_CSV) as f:
        panel = list(csv.DictReader(f))
    print(f"  {len(panel):,} rows")

    snapshots: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for row in panel:
        snapshots[row["snapshot_date"]].append(row)
    snapshots = dict(sorted(snapshots.items()))
    print(f"  {len(snapshots)} snapshots")

    print(f"\nTesting {len(BUNDLES)} ranker bundles (horizons={horizons}, top_ns={top_ns})...\n")

    all_results: List[Dict[str, Any]] = []
    regime_results: Dict[str, Dict[str, Any]] = {}

    for i, (name, bundle) in enumerate(BUNDLES.items()):
        sigs = ", ".join(f"{s}({w:.0%})" for s, (w, _) in bundle.items())
        print(f"  [{i+1}/{len(BUNDLES)}] {name}: {sigs}")

        result = evaluate_ranker_bundle(snapshots, name, bundle, horizons, top_ns)
        all_results.append(result)

        regime_results[name] = evaluate_ranker_regime(snapshots, bundle, args.top_n)

        # Quick preview
        h63 = result["top_ns"][str(args.top_n)]["horizons"].get("63", {})
        ic = h63.get("ic_mean", 0) or 0
        rw = h63.get("rw_minus_ew_net_pp", 0) or 0
        print(f"         → IC={ic:+.3f}  RW−EW net={rw:+.2f}pp")

    # Write outputs
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    json_path = OUTPUT_DIR / "ranker_bundle_results.json"
    with open(json_path, "w") as f:
        json.dump(
            {
                "schema": SCHEMA_VERSION,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "top_ns": top_ns,
                "horizons": horizons,
                "n_bundles": len(all_results),
                "bundles": all_results,
                "regime": regime_results,
            },
            f,
            indent=2,
            default=str,
        )
    print(f"\nJSON: {json_path}")

    md_path = OUTPUT_DIR / "ranker_bundle_report.md"
    write_ranker_report(all_results, regime_results, md_path, args.top_n)
    print(f"Report: {md_path}")

    # Print summary
    print(f"\n{'='*80}")
    print(f"RANKER BUNDLE RESULTS (within top-{args.top_n}, 63d)")
    print(f"{'='*80}")
    print(f"{'Bundle':<30s} {'IC':>6s} {'IC t':>6s} {'RW-EW net':>10s} {'Q spread':>9s} {'PW acc':>7s}")
    print(f"{'-'*30} {'-'*6} {'-'*6} {'-'*10} {'-'*9} {'-'*7}")

    ranked = sorted(
        all_results,
        key=lambda x: x["top_ns"][str(args.top_n)]["horizons"].get("63", {}).get("rw_minus_ew_net_pp") or -999,
        reverse=True,
    )
    for r in ranked:
        h = r["top_ns"][str(args.top_n)]["horizons"].get("63", {})
        print(
            f"  {r['bundle_name']:<28s} "
            f"{_fmt(h.get('ic_mean'), 3):>6s} "
            f"{_fmt(h.get('ic_tstat')):>6s} "
            f"{_fmt(h.get('rw_minus_ew_net_pp')):>10s} "
            f"{_fmt(h.get('quintile_spread_pp')):>9s} "
            f"{_fmt_pct(h.get('pairwise_accuracy')):>7s}"
        )

    print("\nDone.")


if __name__ == "__main__":
    main()
