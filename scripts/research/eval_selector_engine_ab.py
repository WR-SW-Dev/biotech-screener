#!/usr/bin/env python3
"""Spec 050 — A/B evaluation of SelectorEngine configs vs production baseline.

Tests whether the new SelectorEngine (with evidence-aligned weights from
Spec 049) improves top-30 selection vs the current DEM actionable_rank.

Three configs tested:
  1. DEFAULT  — Blueprint weights (clinical 35%, catalyst 25%, etc.)
  2. A4       — Coinvest-anchored (institutional 65%, market 10%, rest 25%)
  3. A5       — Coinvest-anchored + size-residualized coinvest

Also runs the existing bundle harness B6 and A4/A5 bundles as comparators
so we can see whether the multi-block selector adds or destroys value
relative to the proven raw-signal bundles.

Usage:
    python3 scripts/research/eval_selector_engine_ab.py
    python3 scripts/research/eval_selector_engine_ab.py --top-n 20
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
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from ranker_engine import compute_ranker_adjustments
from selector_engine import DEFAULT_SELECTOR_CONFIG, BlockWeight, SelectorConfig, SignalSpec, compute_selector_scores

PANEL_CSV = PROJECT_ROOT / "output" / "signals" / "research_panel.csv"
OUTPUT_DIR = PROJECT_ROOT / "output" / "signals"

# ── Selector configs to test ─────────────────────────────────────────

# A4-equivalent: coinvest + inst dominant, other blocks kept for
# survivability/catalyst gates but with minimal weight.
# Maps to Spec 049 B6: coinvest_score_z 65% + inst_delta_z 35%
# but implemented through the multi-block framework.
A4_CONFIG = SelectorConfig(
    block_weights=(
        BlockWeight("clinical", 0.05),
        BlockWeight("catalyst", 0.10),
        BlockWeight("survivability", 0.10),
        BlockWeight("institutional", 0.65),
        BlockWeight("market_structure", 0.10),
    ),
    # Override institutional signals to match A4: coinvest 65%, inst_delta 35%
    institutional_signals=(
        SignalSpec("coinvest_score_z", 0.65),
        SignalSpec("inst_delta_z", 0.35),
        SignalSpec(
            "coinvest_recency_state", 0.00, categorical=True, value_map=(("fresh", 1.0), ("stale", 0.3), ("", 0.0))
        ),
    ),
)

# A5-equivalent: size-residualized coinvest + inst dominant.
# Uses coinvest_z_size_resid (if available) instead of raw coinvest_score_z.
# NOTE: coinvest_z_size_resid may not be in all historical snapshots.
# The selector gracefully handles missing signals (penalizes, doesn't crash).
A5_CONFIG = SelectorConfig(
    block_weights=(
        BlockWeight("clinical", 0.05),
        BlockWeight("catalyst", 0.10),
        BlockWeight("survivability", 0.10),
        BlockWeight("institutional", 0.65),
        BlockWeight("market_structure", 0.10),
    ),
    institutional_signals=(
        SignalSpec("coinvest_z_size_resid", 0.65),
        SignalSpec("inst_delta_z", 0.35),
        SignalSpec(
            "coinvest_recency_state", 0.00, categorical=True, value_map=(("fresh", 1.0), ("stale", 0.3), ("", 0.0))
        ),
    ),
)

# Four-arm config: each entry is (selector_config, use_ranker)
CONFIGS = {
    "S050_A4_selector": (A4_CONFIG, False),
    "S050_A4_selector_ranker": (A4_CONFIG, True),
    "S050_A5_selector": (A5_CONFIG, False),
    "S050_DEFAULT": (DEFAULT_SELECTOR_CONFIG, False),
}


# ── Helpers (same as test_selector_bundles) ──────────────────────────


def _sf(v, default=float("nan")):
    if v is None or v == "":
        return default
    try:
        f = float(v)
        return f if not math.isnan(f) else default
    except (ValueError, TypeError):
        return default


def _safe_mean(vals: List[float]) -> Optional[float]:
    return statistics.mean(vals) if vals else None


def _safe_ir(vals: List[float]) -> Optional[float]:
    if len(vals) < 2:
        return None
    m = statistics.mean(vals)
    s = statistics.stdev(vals)
    return m / s if s > 1e-9 else None


def _safe_tstat(vals: List[float]) -> Optional[float]:
    if len(vals) < 2:
        return None
    m = statistics.mean(vals)
    s = statistics.stdev(vals)
    if s < 1e-9:
        return None
    return m / (s / len(vals) ** 0.5)


def _hit_rate(vals: List[float]) -> Optional[float]:
    if not vals:
        return None
    return sum(1 for v in vals if v > 0) / len(vals)


def _r(v, digits=4):
    if v is None:
        return None
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return round(v, digits)


def _pp(v):
    if v is None:
        return None
    return v * 100


def _fmt(v, digits=2) -> str:
    if v is None:
        return "—"
    return f"{v:.{digits}f}"


# ── Panel loading ────────────────────────────────────────────────────


def load_panel() -> Dict[str, List[Dict[str, str]]]:
    """Load research panel CSV, grouped by snapshot date."""
    if not PANEL_CSV.exists():
        print(f"ERROR: Research panel not found at {PANEL_CSV}")
        print("Run: python3 scripts/research/build_signal_research_panel.py")
        sys.exit(1)

    snapshots: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    with open(PANEL_CSV) as f:
        for row in csv.DictReader(f):
            snap_date = row.get("snapshot_date", "")
            if snap_date:
                snapshots[snap_date].append(row)

    print(f"Loaded {len(snapshots)} snapshots, {sum(len(v) for v in snapshots.values())} rows")
    return dict(snapshots)


# ── Evaluation ───────────────────────────────────────────────────────


def evaluate_config(
    snapshots: Dict[str, List[Dict[str, str]]],
    config_name: str,
    config: SelectorConfig,
    use_ranker: bool,
    top_n: int,
    horizons: List[int],
) -> Dict[str, Any]:
    """Evaluate a SelectorConfig (optionally with ranker) across all snapshots."""
    result: Dict[str, Any] = {
        "config_name": config_name,
        "block_weights": {bw.name: bw.weight for bw in config.block_weights},
        "use_ranker": use_ranker,
        "horizons": {},
    }

    for h in horizons:
        fwd_col = f"fwd_excess_xbi_{h}d"

        baseline_excess: List[float] = []
        selector_excess: List[float] = []
        improvement: List[float] = []
        turnover_vals: List[float] = []
        overlap_vals: List[float] = []
        rw_vs_ew_spread: List[float] = []  # rank-weighted vs EW net spread
        n_periods = 0
        prev_sel_tickers: set = set()

        for snap_date in sorted(snapshots.keys()):
            rows = snapshots[snap_date]

            # Build eligible rows with forward returns
            eligible: List[Dict[str, Any]] = []
            eligible_rows_for_selector: List[Dict[str, Any]] = []
            for r in rows:
                if _sf(r.get("eligible")) != 1.0:
                    continue
                fwd_xbi = _sf(r.get(fwd_col), default=None)
                rank_val = _sf(r.get("actionable_rank"), default=None)
                ticker = r.get("ticker", "")
                if fwd_xbi is not None and rank_val is not None:
                    eligible.append(
                        {
                            "ticker": ticker,
                            "rank": rank_val,
                            "fwd_xbi": fwd_xbi,
                            "row": r,
                        }
                    )
                    eligible_rows_for_selector.append(r)

            if len(eligible) < top_n:
                continue

            # Baseline: top-K by actionable_rank
            by_rank = sorted(eligible, key=lambda x: x["rank"])
            baseline_topk = by_rank[:top_n]
            baseline_ret = statistics.mean(e["fwd_xbi"] for e in baseline_topk)
            baseline_excess.append(baseline_ret)

            # Selector: compute scores, rank by selector_score or final_score
            sel_results = compute_selector_scores(eligible_rows_for_selector, config=config)

            if use_ranker:
                sel_scores = [sr.selector_score for sr in sel_results]
                sel_buckets = [sr.selector_rank_bucket for sr in sel_results]
                rnk_results = compute_ranker_adjustments(eligible_rows_for_selector, sel_scores, sel_buckets)
                for e, rr in zip(eligible, rnk_results):
                    e["final_score"] = rr.final_score
                sort_key = "final_score"
            else:
                for e, sr in zip(eligible, sel_results):
                    e["final_score"] = sr.selector_score
                sort_key = "final_score"

            by_selector = sorted(eligible, key=lambda x: -x[sort_key])
            sel_topk = by_selector[:top_n]

            # EW return (all top-K weighted equally)
            ew_ret = statistics.mean(e["fwd_xbi"] for e in sel_topk)
            selector_excess.append(ew_ret)

            # RW return (score-proportional weights within top-K)
            scores = [e[sort_key] for e in sel_topk]
            score_sum = sum(scores)
            if score_sum > 1e-9:
                rw_ret = sum(e["fwd_xbi"] * (e[sort_key] / score_sum) for e in sel_topk)
            else:
                rw_ret = ew_ret
            rw_vs_ew_spread.append(rw_ret - ew_ret)

            delta = ew_ret - baseline_ret
            improvement.append(delta)
            n_periods += 1

            # Top-30 overlap with baseline
            baseline_tickers = {e["ticker"] for e in baseline_topk}
            sel_tickers = {e["ticker"] for e in sel_topk}
            overlap = len(baseline_tickers & sel_tickers)
            overlap_vals.append(overlap / top_n)

            # Turnover
            if prev_sel_tickers:
                t_overlap = len(sel_tickers & prev_sel_tickers)
                turnover_vals.append(1.0 - t_overlap / top_n)
            prev_sel_tickers = sel_tickers

        result["horizons"][str(h)] = {
            "baseline_mean_excess_xbi_pp": _r(_pp(_safe_mean(baseline_excess))),
            "selector_mean_excess_xbi_pp": _r(_pp(_safe_mean(selector_excess))),
            "improvement_pp": _r(_pp(_safe_mean(improvement))),
            "improvement_cum_pp": _r(_pp(sum(improvement)) if improvement else None),
            "improvement_hit_rate": _r(_hit_rate(improvement)),
            "improvement_ir": _r(_safe_ir([v * 100 for v in improvement] if improvement else [])),
            "improvement_tstat": _r(_safe_tstat([v * 100 for v in improvement] if improvement else [])),
            "mean_baseline_overlap": _r(_safe_mean(overlap_vals)),
            "mean_turnover": _r(_safe_mean(turnover_vals)),
            "rw_vs_ew_spread_pp": _r(_pp(_safe_mean(rw_vs_ew_spread))),
            "n_periods": n_periods,
        }

    return result


def evaluate_regime_split(
    snapshots: Dict[str, List[Dict[str, str]]],
    config_name: str,
    config: SelectorConfig,
    use_ranker: bool,
    top_n: int,
) -> Dict[str, Any]:
    """Regime-split evaluation at 63d horizon."""
    result: Dict[str, Any] = {}

    for regime_label in ["bear", "neutral", "bull"]:
        improvement_vals: List[float] = []
        n_periods = 0

        for snap_date, rows in sorted(snapshots.items()):
            sample_regime = None
            for r in rows:
                sample_regime = r.get("regime_63d")
                if sample_regime:
                    break
            if sample_regime != regime_label:
                continue

            eligible: List[Dict[str, Any]] = []
            eligible_rows_for_sel: List[Dict[str, Any]] = []
            for r in rows:
                if _sf(r.get("eligible")) != 1.0:
                    continue
                fwd_xbi = _sf(r.get("fwd_excess_xbi_63d"), default=None)
                rank_val = _sf(r.get("actionable_rank"), default=None)
                ticker = r.get("ticker", "")
                if fwd_xbi is not None and rank_val is not None:
                    eligible.append(
                        {
                            "ticker": ticker,
                            "rank": rank_val,
                            "fwd_xbi": fwd_xbi,
                            "row": r,
                        }
                    )
                    eligible_rows_for_sel.append(r)

            if len(eligible) < top_n:
                continue
            n_periods += 1

            by_rank = sorted(eligible, key=lambda x: x["rank"])
            baseline_ret = statistics.mean(e["fwd_xbi"] for e in by_rank[:top_n])

            sel_results = compute_selector_scores(eligible_rows_for_sel, config=config)
            if use_ranker:
                sel_scores = [sr.selector_score for sr in sel_results]
                sel_buckets = [sr.selector_rank_bucket for sr in sel_results]
                rnk_results = compute_ranker_adjustments(eligible_rows_for_sel, sel_scores, sel_buckets)
                for e, rr in zip(eligible, rnk_results):
                    e["final_score"] = rr.final_score
            else:
                for e, sr in zip(eligible, sel_results):
                    e["final_score"] = sr.selector_score

            by_selector = sorted(eligible, key=lambda x: -x["final_score"])
            sel_ret = statistics.mean(e["fwd_xbi"] for e in by_selector[:top_n])

            improvement_vals.append(sel_ret - baseline_ret)

        result[regime_label] = {
            "n_periods": n_periods,
            "improvement_pp": _r(_pp(_safe_mean(improvement_vals))),
            "improvement_hit_rate": _r(_hit_rate(improvement_vals)),
        }

    return result


# ── Within-top-30 IC ─────────────────────────────────────────────────


def evaluate_within_top30_ic(
    snapshots: Dict[str, List[Dict[str, str]]],
    config_name: str,
    config: SelectorConfig,
    use_ranker: bool,
    top_n: int,
) -> Dict[str, Any]:
    """Compute within-top-30 Spearman IC: does ordering predict
    forward returns within the selected set?"""
    ic_vals: List[float] = []

    for snap_date in sorted(snapshots.keys()):
        rows = snapshots[snap_date]

        eligible: List[Dict[str, Any]] = []
        eligible_rows: List[Dict[str, Any]] = []
        for r in rows:
            if _sf(r.get("eligible")) != 1.0:
                continue
            fwd_xbi = _sf(r.get("fwd_excess_xbi_63d"), default=None)
            ticker = r.get("ticker", "")
            if fwd_xbi is not None:
                eligible.append({"ticker": ticker, "fwd_xbi": fwd_xbi, "row": r})
                eligible_rows.append(r)

        if len(eligible) < top_n:
            continue

        sel_results = compute_selector_scores(eligible_rows, config=config)
        if use_ranker:
            sel_scores = [sr.selector_score for sr in sel_results]
            sel_buckets = [sr.selector_rank_bucket for sr in sel_results]
            rnk_results = compute_ranker_adjustments(eligible_rows, sel_scores, sel_buckets)
            for e, rr in zip(eligible, rnk_results):
                e["final_score"] = rr.final_score
        else:
            for e, sr in zip(eligible, sel_results):
                e["final_score"] = sr.selector_score

        # Take top-N by final score
        by_sel = sorted(eligible, key=lambda x: -x["final_score"])
        topk = by_sel[:top_n]

        if len(topk) < 5:
            continue

        scores = [e["final_score"] for e in topk]
        fwd_returns = [e["fwd_xbi"] for e in topk]

        def _rank(values):
            indexed = sorted(range(len(values)), key=lambda i: values[i])
            ranks = [0.0] * len(values)
            for rank_pos, idx in enumerate(indexed):
                ranks[idx] = rank_pos + 1
            return ranks

        sel_ranks = _rank(scores)
        fwd_ranks = _rank(fwd_returns)

        n = len(topk)
        d_sq = sum((sr - fr) ** 2 for sr, fr in zip(sel_ranks, fwd_ranks))
        ic = 1 - 6 * d_sq / (n * (n * n - 1))
        ic_vals.append(ic)

    return {
        "mean_ic": _r(_safe_mean(ic_vals)),
        "ic_tstat": _r(_safe_tstat(ic_vals)),
        "ic_hit_rate": _r(_hit_rate(ic_vals)),
        "n_periods": len(ic_vals),
    }


# ── Report ───────────────────────────────────────────────────────────


def write_report(
    results: List[Dict[str, Any]],
    regime_results: Dict[str, Dict[str, Any]],
    ic_results: Dict[str, Dict[str, Any]],
    top_n: int,
    out_path: Path,
) -> None:
    """Write markdown A/B report."""
    lines = [
        "# Spec 050 — Selector Engine A/B Evaluation\n",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}  ",
        f"Configs tested: {len(results)}  ",
        f"Baseline: DEM actionable_rank top-{top_n} EW\n",
    ]

    # Main table
    lines.append(f"## Selector vs Baseline (top-{top_n}, excess vs XBI, 63d)\n")
    lines.append(
        "| Config | Ranker | Baseline (pp) | Arm (pp) | Δ (pp) | Δ cum (pp) | hit% | IR | t-stat | Overlap | Turnover | RW-EW (pp) | N |"
    )
    lines.append(
        "|--------|--------|--------------|---------|--------|-----------|------|-----|--------|---------|----------|-----------|---|"
    )

    sorted_results = sorted(
        results,
        key=lambda x: (x["horizons"].get("63", {}).get("improvement_pp") or -999),
        reverse=True,
    )

    for r in sorted_results:
        h63 = r["horizons"].get("63", {})
        ranker_tag = "Y" if r.get("use_ranker") else "N"
        lines.append(
            f"| `{r['config_name']}` "
            f"| {ranker_tag} "
            f"| {_fmt(h63.get('baseline_mean_excess_xbi_pp'))} "
            f"| {_fmt(h63.get('selector_mean_excess_xbi_pp'))} "
            f"| {_fmt(h63.get('improvement_pp'))} "
            f"| {_fmt(h63.get('improvement_cum_pp'))} "
            f"| {_fmt(h63.get('improvement_hit_rate') * 100 if h63.get('improvement_hit_rate') is not None else None, 0)} "
            f"| {_fmt(h63.get('improvement_ir'))} "
            f"| {_fmt(h63.get('improvement_tstat'))} "
            f"| {_fmt(h63.get('mean_baseline_overlap') * 100 if h63.get('mean_baseline_overlap') is not None else None, 0)}% "
            f"| {_fmt(h63.get('mean_turnover'))} "
            f"| {_fmt(h63.get('rw_vs_ew_spread_pp'))} "
            f"| {h63.get('n_periods', 0)} |"
        )

    # 20d horizon
    lines.append("\n## 20-day horizon\n")
    lines.append("| Config | Δ (pp) | hit% | IR | t-stat | N |")
    lines.append("|--------|--------|------|-----|--------|---|")
    for r in sorted_results:
        h20 = r["horizons"].get("20", {})
        lines.append(
            f"| `{r['config_name']}` "
            f"| {_fmt(h20.get('improvement_pp'))} "
            f"| {_fmt(h20.get('improvement_hit_rate'), 0)}% "
            f"| {_fmt(h20.get('improvement_ir'))} "
            f"| {_fmt(h20.get('improvement_tstat'))} "
            f"| {h20.get('n_periods', 0)} |"
        )

    # Within-top-30 IC
    lines.append(f"\n## Within-top-{top_n} IC (63d, Spearman)\n")
    lines.append("| Config | Mean IC | IC t-stat | IC hit% | N |")
    lines.append("|--------|---------|-----------|---------|---|")
    for r in sorted_results:
        ic = ic_results.get(r["config_name"], {})
        lines.append(
            f"| `{r['config_name']}` "
            f"| {_fmt(ic.get('mean_ic'), 3)} "
            f"| {_fmt(ic.get('ic_tstat'))} "
            f"| {_fmt(ic.get('ic_hit_rate'), 0)}% "
            f"| {ic.get('n_periods', 0)} |"
        )

    # Regime splits
    lines.append("\n## Regime splits (63d)\n")
    lines.append("| Config | Bear Δ (pp) | Bear hit% | Neutral Δ (pp) | Bull Δ (pp) |")
    lines.append("|--------|-----------|-----------|---------------|-----------|")
    for r in sorted_results:
        rg = regime_results.get(r["config_name"], {})
        bear = rg.get("bear", {})
        neutral = rg.get("neutral", {})
        bull = rg.get("bull", {})
        lines.append(
            f"| `{r['config_name']}` "
            f"| {_fmt(bear.get('improvement_pp'))} "
            f"| {_fmt(bear.get('improvement_hit_rate'), 0)}% "
            f"| {_fmt(neutral.get('improvement_pp'))} "
            f"| {_fmt(bull.get('improvement_pp'))} |"
        )

    # Block weights summary
    lines.append("\n## Block weight configs\n")
    lines.append("| Config | Clinical | Catalyst | Survivability | Institutional | Market |")
    lines.append("|--------|----------|----------|---------------|---------------|--------|")
    for r in sorted_results:
        bw = r.get("block_weights", {})
        lines.append(
            f"| `{r['config_name']}` "
            f"| {bw.get('clinical', 0):.0%} "
            f"| {bw.get('catalyst', 0):.0%} "
            f"| {bw.get('survivability', 0):.0%} "
            f"| {bw.get('institutional', 0):.0%} "
            f"| {bw.get('market_structure', 0):.0%} |"
        )

    lines.append("\n---\n")
    lines.append(
        "**Decision rule**: Promote config only if Δ > +0.20pp, t-stat >= 2.0, "
        "within-top-30 IC positive, and no regime with Δ < -0.50pp.\n"
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines))
    print(f"Report written to {out_path}")


# ── Main ─────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Spec 050 Selector Engine A/B")
    parser.add_argument("--top-n", type=int, default=30)
    parser.add_argument("--horizons", type=str, default="20,63")
    args = parser.parse_args()

    top_n = args.top_n
    horizons = [int(h) for h in args.horizons.split(",")]

    snapshots = load_panel()

    results: List[Dict[str, Any]] = []
    regime_results: Dict[str, Dict[str, Any]] = {}
    ic_results: Dict[str, Dict[str, Any]] = {}

    for config_name, (config, use_ranker) in CONFIGS.items():
        ranker_label = " +ranker" if use_ranker else ""
        print(f"\nEvaluating {config_name}{ranker_label}...")
        r = evaluate_config(snapshots, config_name, config, use_ranker, top_n, horizons)
        results.append(r)

        print("  Regime split...")
        regime_results[config_name] = evaluate_regime_split(snapshots, config_name, config, use_ranker, top_n)

        print(f"  Within-top-{top_n} IC...")
        ic_results[config_name] = evaluate_within_top30_ic(snapshots, config_name, config, use_ranker, top_n)

    # Save JSON
    out_json = OUTPUT_DIR / "selector_engine_ab_results.json"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    with open(out_json, "w") as f:
        json.dump(
            {
                "schema": "selector_engine_ab.v1",
                "generated": datetime.now(timezone.utc).isoformat(),
                "top_n": top_n,
                "horizons": horizons,
                "results": results,
                "regime": regime_results,
                "within_top_k_ic": ic_results,
            },
            f,
            indent=2,
        )
    print(f"\nJSON results: {out_json}")

    # Save report
    out_md = OUTPUT_DIR / "selector_engine_ab_report.md"
    write_report(results, regime_results, ic_results, top_n, out_md)


if __name__ == "__main__":
    main()
