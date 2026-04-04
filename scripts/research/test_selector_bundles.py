#!/usr/bin/env python3
"""Spec 049 Phase 3 — Selector bundle tests.

Tests interpretable multi-signal bundles as selectors: for each snapshot,
sort eligible names by the bundle score, take EW top-K, and compare to
baseline (actionable_rank) and to XBI.

Bundles are defined as weighted sums of z-scored signals.  Each signal
is z-scored across the eligible universe per snapshot before combining.

Usage:
    python3 scripts/research/test_selector_bundles.py
    python3 scripts/research/test_selector_bundles.py --top-n 30
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

SCHEMA_VERSION = "selector_bundle.v1"

# ── Bundle definitions ────────────────────────────────────────────────
# Each bundle: {signal_name: (weight, higher_is_better)}
# Weights within a bundle sum to 1.0.

BUNDLES = {
    # --- Spec 049 baseline progression ---
    "B1_clinical_only": {
        "clinical_score_v2_z": (1.0, True),
    },
    "B2_clinical_catalyst": {
        "clinical_score_v2_z": (0.65, True),
        "catalyst_score": (0.35, True),
    },
    "B3_clinical_catalyst_financial": {
        "clinical_score_v2_z": (0.45, True),
        "catalyst_score": (0.25, True),
        "financial_score": (0.20, True),
        "binary_quality_score": (0.10, True),
    },
    "B4_baseline_with_inst": {
        "clinical_score_v2_z": (0.45, True),
        "catalyst_score": (0.25, True),
        "financial_score": (0.20, True),
        "inst_delta_z": (0.10, True),
    },
    # --- Data-driven from Phase 2 signal cards ---
    "B5_coinvest_only": {
        "coinvest_score_z": (1.0, True),
    },
    "B6_coinvest_inst": {
        "coinvest_score_z": (0.65, True),
        "inst_delta_z": (0.35, True),
    },
    "B7_smart_money_full": {
        "coinvest_score_z": (0.40, True),
        "inst_delta_z": (0.20, True),
        "clinical_score_v2_z": (0.25, True),
        "catalyst_score": (0.15, True),
    },
    "B8_top_signals": {
        # Combine the Phase 2 winners
        "coinvest_score_z": (0.35, True),
        "inst_delta_z": (0.20, True),
        "ovf11_score": (0.15, True),
        "catalyst_score": (0.15, True),
        "clinical_score_v2_z": (0.15, True),
    },
    # --- Production comparators ---
    "B9_composite_score": {
        "composite_score": (1.0, True),
    },
    "B10_momentum_catalyst": {
        "momentum_score": (0.50, True),
        "catalyst_score": (0.50, True),
    },
    "B11_coinvest_clinical_catalyst": {
        "coinvest_score_z": (0.45, True),
        "clinical_score_v2_z": (0.30, True),
        "catalyst_score": (0.25, True),
    },
    "B12_equal_weight_all": {
        # Equal weight of all major families
        "clinical_score_v2_z": (0.20, True),
        "catalyst_score": (0.20, True),
        "coinvest_score_z": (0.20, True),
        "inst_delta_z": (0.20, True),
        "momentum_score": (0.20, True),
    },
    # --- Insider signal bundles ---
    "B13_insider_only": {
        "insider_net_buy_value_90d": (1.0, True),
    },
    "B14_coinvest_insider": {
        "coinvest_score_z": (0.55, True),
        "inst_delta_z": (0.25, True),
        "insider_net_buy_value_90d": (0.20, True),
    },
    "B15_coinvest_inst_insider": {
        "coinvest_score_z": (0.50, True),
        "inst_delta_z": (0.30, True),
        "insider_net_buy_value_90d": (0.20, True),
    },
    "B16_coinvest_insider_heavy": {
        "coinvest_score_z": (0.45, True),
        "insider_net_buy_value_90d": (0.35, True),
        "inst_delta_z": (0.20, True),
    },
    "B17_insider_exec_buy": {
        "insider_exec_buy_value_90d": (1.0, True),
    },
    "B18_coinvest_exec_insider": {
        "coinvest_score_z": (0.55, True),
        "inst_delta_z": (0.25, True),
        "insider_exec_buy_value_90d": (0.20, True),
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


def _safe_mean(vals: List[float]) -> Optional[float]:
    return statistics.mean(vals) if vals else None


def _safe_stdev(vals: List[float]) -> Optional[float]:
    return statistics.stdev(vals) if len(vals) >= 2 else None


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


def _fmt_pct(v) -> str:
    if v is None:
        return "—"
    return f"{v*100:.0f}%"


# ── Z-scoring ─────────────────────────────────────────────────────────


def zscore_eligible(
    rows: List[Dict[str, str]],
    signal: str,
) -> Dict[str, float]:
    """Z-score a signal across eligible names in a single snapshot.

    Returns {ticker: z_value} for names with valid signal data.
    Missing values get z=0 (neutral).
    """
    vals = []
    tickers = []
    for r in rows:
        if _sf(r.get("eligible")) != 1.0:
            continue
        v = _sf(r.get(signal), default=None)
        if v is not None:
            vals.append(v)
            tickers.append(r.get("ticker", ""))

    if len(vals) < 3:
        return {}

    m = statistics.mean(vals)
    s = statistics.stdev(vals) if len(vals) >= 2 else 1.0
    if s < 1e-9:
        s = 1.0

    result = {}
    for i, t in enumerate(tickers):
        result[t] = (vals[i] - m) / s

    return result


def compute_bundle_score(
    rows: List[Dict[str, str]],
    bundle: Dict[str, Tuple[float, bool]],
) -> Dict[str, float]:
    """Compute weighted bundle score for eligible names.

    Each signal is z-scored across eligible names first, then combined.
    Higher score = better candidate.
    """
    # Z-score each signal
    z_maps: Dict[str, Dict[str, float]] = {}
    for signal in bundle:
        z_maps[signal] = zscore_eligible(rows, signal)

    # Combine
    scores: Dict[str, float] = {}
    for r in rows:
        if _sf(r.get("eligible")) != 1.0:
            continue
        ticker = r.get("ticker", "")
        total = 0.0
        total_w = 0.0
        for signal, (weight, higher_better) in bundle.items():
            z = z_maps.get(signal, {}).get(ticker)
            if z is not None:
                if not higher_better:
                    z = -z
                total += weight * z
                total_w += weight
        if total_w > 0:
            scores[ticker] = total / total_w  # normalize by actual weight used
        else:
            scores[ticker] = 0.0

    return scores


# ── Core evaluation ───────────────────────────────────────────────────


def evaluate_bundle(
    snapshots: Dict[str, List[Dict[str, str]]],
    bundle_name: str,
    bundle: Dict[str, Tuple[float, bool]],
    horizons: List[int],
    top_ns: List[int],
) -> Dict[str, Any]:
    """Evaluate a selector bundle across all snapshots."""
    result: Dict[str, Any] = {
        "bundle_name": bundle_name,
        "signals": {s: {"weight": w, "higher_is_better": h} for s, (w, h) in bundle.items()},
        "top_ns": {},
    }

    for top_n in top_ns:
        result["top_ns"][str(top_n)] = {"horizons": {}}

        for h in horizons:
            fwd_col = f"fwd_excess_xbi_{h}d"
            fwd_ret_col = f"fwd_ret_{h}d"

            baseline_excess: List[float] = []
            bundle_excess: List[float] = []
            improvement: List[float] = []
            baseline_vs_elig: List[float] = []
            bundle_vs_elig: List[float] = []
            n_periods = 0
            turnover_vals: List[float] = []
            prev_bundle_tickers = set()

            for snap_date in sorted(snapshots.keys()):
                rows = snapshots[snap_date]

                # Build eligible set with forward returns
                eligible = []
                for r in rows:
                    if _sf(r.get("eligible")) != 1.0:
                        continue
                    fwd_xbi = _sf(r.get(fwd_col), default=None)
                    fwd_ret = _sf(r.get(fwd_ret_col), default=None)
                    rank_val = _sf(r.get("actionable_rank"), default=None)
                    ticker = r.get("ticker", "")
                    if fwd_xbi is not None and rank_val is not None:
                        eligible.append(
                            {
                                "ticker": ticker,
                                "rank": rank_val,
                                "fwd_xbi": fwd_xbi,
                                "fwd_ret": fwd_ret,
                            }
                        )

                if len(eligible) < top_n:
                    continue

                # Baseline: top-K by actionable_rank
                by_rank = sorted(eligible, key=lambda x: x["rank"])
                baseline_topk = by_rank[:top_n]
                baseline_ret = statistics.mean(e["fwd_xbi"] for e in baseline_topk)
                baseline_excess.append(baseline_ret)

                # Eligible EW
                elig_ew = statistics.mean(e["fwd_xbi"] for e in eligible)
                baseline_vs_elig.append(baseline_ret - elig_ew)

                # Bundle-sorted top-K
                scores = compute_bundle_score(rows, bundle)
                # Attach scores to eligible
                for e in eligible:
                    e["bundle_score"] = scores.get(e["ticker"], 0.0)

                by_bundle = sorted(eligible, key=lambda x: -x["bundle_score"])
                bundle_topk = by_bundle[:top_n]
                bundle_ret = statistics.mean(e["fwd_xbi"] for e in bundle_topk)
                bundle_excess.append(bundle_ret)
                bundle_vs_elig.append(bundle_ret - elig_ew)

                delta = bundle_ret - baseline_ret
                improvement.append(delta)
                n_periods += 1

                # Turnover
                curr_tickers = {e["ticker"] for e in bundle_topk}
                if prev_bundle_tickers:
                    overlap = len(curr_tickers & prev_bundle_tickers)
                    turnover = 1.0 - overlap / top_n
                    turnover_vals.append(turnover)
                prev_bundle_tickers = curr_tickers

            result["top_ns"][str(top_n)]["horizons"][str(h)] = {
                "baseline_mean_excess_xbi_pp": _r(_pp(_safe_mean(baseline_excess))),
                "bundle_mean_excess_xbi_pp": _r(_pp(_safe_mean(bundle_excess))),
                "improvement_pp": _r(_pp(_safe_mean(improvement))),
                "improvement_cum_pp": _r(_pp(sum(improvement)) if improvement else None),
                "improvement_hit_rate": _r(_hit_rate(improvement)),
                "improvement_ir": _r(_safe_ir([v * 100 for v in improvement] if improvement else [])),
                "improvement_tstat": _r(_safe_tstat([v * 100 for v in improvement] if improvement else [])),
                "baseline_vs_elig_pp": _r(_pp(_safe_mean(baseline_vs_elig))),
                "bundle_vs_elig_pp": _r(_pp(_safe_mean(bundle_vs_elig))),
                "mean_turnover": _r(_safe_mean(turnover_vals)),
                "n_periods": n_periods,
            }

    return result


def evaluate_bundle_regime(
    snapshots: Dict[str, List[Dict[str, str]]],
    bundle_name: str,
    bundle: Dict[str, Tuple[float, bool]],
    top_n: int,
) -> Dict[str, Any]:
    """Regime-split bundle evaluation at 63d horizon."""
    result: Dict[str, Any] = {}

    for regime_label in ["bear", "neutral", "bull"]:
        improvement_vals: List[float] = []
        bundle_excess_vals: List[float] = []
        n_periods = 0

        for snap_date, rows in sorted(snapshots.items()):
            # Check regime
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
                fwd_xbi = _sf(r.get("fwd_excess_xbi_63d"), default=None)
                rank_val = _sf(r.get("actionable_rank"), default=None)
                ticker = r.get("ticker", "")
                if fwd_xbi is not None and rank_val is not None:
                    eligible.append(
                        {
                            "ticker": ticker,
                            "rank": rank_val,
                            "fwd_xbi": fwd_xbi,
                        }
                    )

            if len(eligible) < top_n:
                continue

            n_periods += 1

            # Baseline
            by_rank = sorted(eligible, key=lambda x: x["rank"])
            baseline_ret = statistics.mean(e["fwd_xbi"] for e in by_rank[:top_n])

            # Bundle
            scores = compute_bundle_score(rows, bundle)
            for e in eligible:
                e["bundle_score"] = scores.get(e["ticker"], 0.0)
            by_bundle = sorted(eligible, key=lambda x: -x["bundle_score"])
            bundle_ret = statistics.mean(e["fwd_xbi"] for e in by_bundle[:top_n])

            improvement_vals.append(bundle_ret - baseline_ret)
            bundle_excess_vals.append(bundle_ret)

        result[regime_label] = {
            "n_periods": n_periods,
            "improvement_pp": _r(_pp(_safe_mean(improvement_vals))),
            "improvement_hit_rate": _r(_hit_rate(improvement_vals)),
            "bundle_excess_xbi_pp": _r(_pp(_safe_mean(bundle_excess_vals))),
        }

    return result


def evaluate_yearly(
    snapshots: Dict[str, List[Dict[str, str]]],
    bundle_name: str,
    bundle: Dict[str, Tuple[float, bool]],
    top_n: int,
) -> Dict[str, Any]:
    """Year-by-year bundle evaluation at 63d horizon."""
    yearly: Dict[str, List[float]] = defaultdict(list)

    for snap_date, rows in sorted(snapshots.items()):
        year = snap_date[:4]

        eligible = []
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
                    }
                )

        if len(eligible) < top_n:
            continue

        by_rank = sorted(eligible, key=lambda x: x["rank"])
        baseline_ret = statistics.mean(e["fwd_xbi"] for e in by_rank[:top_n])

        scores = compute_bundle_score(rows, bundle)
        for e in eligible:
            e["bundle_score"] = scores.get(e["ticker"], 0.0)
        by_bundle = sorted(eligible, key=lambda x: -x["bundle_score"])
        bundle_ret = statistics.mean(e["fwd_xbi"] for e in by_bundle[:top_n])

        yearly[year].append(bundle_ret - baseline_ret)

    result = {}
    for year in sorted(yearly.keys()):
        vals = yearly[year]
        result[year] = {
            "n_months": len(vals),
            "improvement_pp": _r(_pp(_safe_mean(vals))),
            "improvement_cum_pp": _r(_pp(sum(vals))),
            "hit_rate": _r(_hit_rate(vals)),
        }
    return result


# ── Output ────────────────────────────────────────────────────────────


def write_bundle_report(
    results: List[Dict[str, Any]],
    regime_results: Dict[str, Dict[str, Any]],
    yearly_results: Dict[str, Dict[str, Any]],
    path: Path,
    top_n: int,
) -> None:
    """Write the selector bundle comparison report."""
    lines = [
        "# Selector Bundle Report — Spec 049 Phase 3\n",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}  ",
        f"Bundles tested: {len(results)}  ",
        f"Baseline: DEM actionable_rank top-{top_n} EW\n",
    ]

    # Main comparison table
    lines.append(f"## Bundle comparison (top-{top_n}, excess vs XBI)\n")
    lines.append("| Bundle | Baseline (pp) | Bundle (pp) | Δ (pp) | Δ cum (pp) | hit% | IR | t-stat | Turnover | N |")
    lines.append("|--------|--------------|------------|--------|-----------|------|-----|--------|----------|---|")

    # Sort by improvement at 63d
    sorted_results = sorted(
        results,
        key=lambda x: x["top_ns"][str(top_n)]["horizons"].get("63", {}).get("improvement_pp") or -999,
        reverse=True,
    )

    for r in sorted_results:
        h63 = r["top_ns"][str(top_n)]["horizons"].get("63", {})
        h20 = r["top_ns"][str(top_n)]["horizons"].get("20", {})
        lines.append(
            f"| `{r['bundle_name']}` "
            f"| {_fmt(h63.get('baseline_mean_excess_xbi_pp'))} "
            f"| {_fmt(h63.get('bundle_mean_excess_xbi_pp'))} "
            f"| {_fmt(h63.get('improvement_pp'))} "
            f"| {_fmt(h63.get('improvement_cum_pp'))} "
            f"| {_fmt_pct(h63.get('improvement_hit_rate'))} "
            f"| {_fmt(h63.get('improvement_ir'))} "
            f"| {_fmt(h63.get('improvement_tstat'))} "
            f"| {_fmt(h63.get('mean_turnover'))} "
            f"| {h63.get('n_periods', 0)} |"
        )

    # 20d horizon
    lines.append(f"\n## 20d horizon (top-{top_n})\n")
    lines.append("| Bundle | Δ (pp) | hit% | t-stat | N |")
    lines.append("|--------|--------|------|--------|---|")
    for r in sorted_results:
        h20 = r["top_ns"][str(top_n)]["horizons"].get("20", {})
        lines.append(
            f"| `{r['bundle_name']}` "
            f"| {_fmt(h20.get('improvement_pp'))} "
            f"| {_fmt_pct(h20.get('improvement_hit_rate'))} "
            f"| {_fmt(h20.get('improvement_tstat'))} "
            f"| {h20.get('n_periods', 0)} |"
        )

    # Bundle signal compositions
    lines.append("\n## Bundle compositions\n")
    for r in sorted_results:
        sig_str = ", ".join(f"`{s}` ({info['weight']:.0%})" for s, info in r["signals"].items())
        lines.append(f"- **{r['bundle_name']}**: {sig_str}")

    # Regime splits
    lines.append(f"\n## Regime stability (63d, top-{top_n})\n")
    lines.append("| Bundle | Bear Δ (pp) | Bear hit% | Neutral Δ (pp) | Bull Δ (pp) | Bull hit% |")
    lines.append("|--------|-----------|----------|---------------|-----------|----------|")
    for r in sorted_results:
        name = r["bundle_name"]
        reg = regime_results.get(name, {})
        bear = reg.get("bear", {})
        neut = reg.get("neutral", {})
        bull = reg.get("bull", {})
        lines.append(
            f"| `{name}` "
            f"| {_fmt(bear.get('improvement_pp'))} "
            f"| {_fmt_pct(bear.get('improvement_hit_rate'))} "
            f"| {_fmt(neut.get('improvement_pp'))} "
            f"| {_fmt(bull.get('improvement_pp'))} "
            f"| {_fmt_pct(bull.get('improvement_hit_rate'))} |"
        )

    # Yearly breakdown for top bundles
    lines.append(f"\n## Yearly breakdown (63d, top-{top_n}, improvement pp vs baseline)\n")
    # Get all years
    all_years = set()
    for name, yd in yearly_results.items():
        all_years.update(yd.keys())
    all_years = sorted(all_years)

    header = "| Bundle | " + " | ".join(all_years) + " |"
    sep = "|--------| " + " | ".join(["---"] * len(all_years)) + " |"
    lines.append(header)
    lines.append(sep)
    for r in sorted_results:
        name = r["bundle_name"]
        yd = yearly_results.get(name, {})
        cells = []
        for y in all_years:
            v = yd.get(y, {}).get("improvement_cum_pp")
            cells.append(_fmt(v))
        lines.append(f"| `{name}` | " + " | ".join(cells) + " |")

    lines.append("")
    path.write_text("\n".join(lines))


# ── Main ──────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Selector bundle tests (Spec 049 Phase 3)")
    parser.add_argument("--top-n", type=int, default=30, help="Top-N for selection (default: 30)")
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

    print(f"\nTesting {len(BUNDLES)} bundles (horizons={horizons}, top_ns={top_ns})...\n")

    all_results: List[Dict[str, Any]] = []
    regime_results: Dict[str, Dict[str, Any]] = {}
    yearly_results: Dict[str, Dict[str, Any]] = {}

    for i, (name, bundle) in enumerate(BUNDLES.items()):
        sigs = ", ".join(f"{s}({w:.0%})" for s, (w, _) in bundle.items())
        print(f"  [{i+1}/{len(BUNDLES)}] {name}: {sigs}")

        result = evaluate_bundle(snapshots, name, bundle, horizons, top_ns)
        all_results.append(result)

        regime_results[name] = evaluate_bundle_regime(snapshots, name, bundle, args.top_n)
        yearly_results[name] = evaluate_yearly(snapshots, name, bundle, args.top_n)

        # Quick preview
        h63 = result["top_ns"][str(args.top_n)]["horizons"].get("63", {})
        imp = h63.get("improvement_pp", 0) or 0
        ts = h63.get("improvement_tstat", 0) or 0
        print(f"         → Δ={imp:+.2f}pp  t={ts:.2f}")

    # Write outputs
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # JSON
    output_json = {
        "schema": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "top_ns": top_ns,
        "horizons": horizons,
        "n_bundles": len(all_results),
        "bundles": all_results,
        "regime": regime_results,
        "yearly": yearly_results,
    }
    json_path = OUTPUT_DIR / "selector_bundle_results.json"
    with open(json_path, "w") as f:
        json.dump(output_json, f, indent=2, default=str)
    print(f"\nJSON: {json_path}")

    # Markdown report
    md_path = OUTPUT_DIR / "selector_bundle_report.md"
    write_bundle_report(all_results, regime_results, yearly_results, md_path, args.top_n)
    print(f"Report: {md_path}")

    # Print summary
    print(f"\n{'='*70}")
    print(f"SELECTOR BUNDLE RESULTS (top-{args.top_n}, 63d excess vs XBI)")
    print(f"{'='*70}")
    print(f"{'Bundle':<35s} {'Δ pp':>7s} {'t-stat':>7s} {'hit%':>6s} {'IR':>6s}")
    print(f"{'-'*35} {'-'*7} {'-'*7} {'-'*6} {'-'*6}")

    ranked = sorted(
        all_results,
        key=lambda x: x["top_ns"][str(args.top_n)]["horizons"].get("63", {}).get("improvement_pp") or -999,
        reverse=True,
    )
    for r in ranked:
        h63 = r["top_ns"][str(args.top_n)]["horizons"].get("63", {})
        imp = h63.get("improvement_pp")
        ts = h63.get("improvement_tstat")
        hr = h63.get("improvement_hit_rate")
        ir = h63.get("improvement_ir")
        print(
            f"  {r['bundle_name']:<33s} "
            f"{_fmt(imp):>7s} "
            f"{_fmt(ts):>7s} "
            f"{_fmt_pct(hr):>6s} "
            f"{_fmt(ir):>6s}"
        )

    print("\nDone.")


if __name__ == "__main__":
    main()
