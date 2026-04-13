#!/usr/bin/env python3
"""Expression overlay forward evaluation panel.

Reads the attribution log, joins with price data to compute realized
moves around catalyst dates, and produces a structured evaluation
of whether the overlay's recommendations were meaningful.

Separate from alpha evaluation — this measures the overlay's own
quality as a diagnostic tool.

Usage:
    python scripts/research/expression_forward_panel.py [--min-days N]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.eval_forward_returns import compute_forward_return, load_price_series

HORIZONS = [1, 5, 20]  # short horizons — overlay is event-adjacent


def _safe_float(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        f = float(v)
        return f if f == f else None
    except (ValueError, TypeError):
        return None


def load_attribution_log(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return records


def load_decision_log(path: Path) -> List[Dict[str, Any]]:
    return load_attribution_log(path)  # same format


def evaluate_panel(
    attr_path: Path,
    dec_path: Path,
    price_csv: Path,
    min_days: int = 5,
) -> Dict[str, Any]:
    """Build forward evaluation panel from attribution + decision logs.

    For each tradeable recommendation:
      - Compute 1d/5d/20d forward returns from as_of_date
      - Compare to universe mean return (baseline)
      - Score by mispricing_type, overlay_class, ev_source, confidence bucket
    """
    attr_records = load_attribution_log(attr_path)
    dec_records = load_decision_log(dec_path)

    if not attr_records:
        return {"status": "no_data", "n_tradeable": 0, "n_decisions": len(dec_records)}

    prices = load_price_series(price_csv)
    all_dates = sorted(set(d for tp in prices.values() for d in tp))

    # Evaluate each tradeable recommendation
    evaluated = []
    for rec in attr_records:
        tk = rec.get("ticker", "")
        as_of = rec.get("as_of_date", "")
        if not tk or not as_of or tk not in prices:
            continue

        # Forward returns
        fwd = {}
        for h in HORIZONS:
            ret = compute_forward_return(prices[tk], all_dates, as_of, h)
            if ret is not None:
                fwd[f"fwd_{h}d"] = round(ret * 100, 4)

        if not fwd:
            continue

        evaluated.append(
            {
                "ticker": tk,
                "as_of_date": as_of,
                "mispricing_type": rec.get("mispricing_type"),
                "overlay_class": rec.get("overlay_class"),
                "belief_strength": rec.get("belief_strength"),
                "permission_to_express": rec.get("permission_to_express"),
                "mispricing_confidence": rec.get("mispricing_confidence"),
                "surface_quality_score": rec.get("surface_quality_score"),
                "priced_move_pct": rec.get("priced_move_pct"),
                "scenario_ev": rec.get("scenario_ev"),
                "ev_source": rec.get("ev_source", "unknown"),
                **fwd,
            }
        )

    if len(evaluated) < min_days:
        return {
            "status": "insufficient_data",
            "n_tradeable": len(attr_records),
            "n_evaluated": len(evaluated),
            "min_required": min_days,
        }

    # Decision log summary
    dec_summary = Counter(r.get("decision") for r in dec_records)

    # Aggregate performance by horizon
    performance = {}
    for h in HORIZONS:
        key = f"fwd_{h}d"
        vals = [e[key] for e in evaluated if key in e]
        if vals:
            wins = sum(1 for v in vals if v > 0)
            performance[f"{h}d"] = {
                "n": len(vals),
                "mean_ret_pct": round(statistics.mean(vals), 3),
                "median_ret_pct": round(sorted(vals)[len(vals) // 2], 3),
                "win_rate": round(wins / len(vals), 3),
                "std_pct": round(statistics.stdev(vals), 3) if len(vals) >= 2 else None,
                "min_pct": round(min(vals), 3),
                "max_pct": round(max(vals), 3),
            }

    # By mispricing type
    by_type = defaultdict(lambda: defaultdict(list))
    for e in evaluated:
        mt = e.get("mispricing_type", "UNKNOWN")
        for h in HORIZONS:
            key = f"fwd_{h}d"
            if key in e:
                by_type[mt][f"{h}d"].append(e[key])

    type_perf = {}
    for mt, horizons in by_type.items():
        type_perf[mt] = {}
        for h_label, vals in horizons.items():
            if vals:
                wins = sum(1 for v in vals if v > 0)
                type_perf[mt][h_label] = {
                    "n": len(vals),
                    "mean_ret_pct": round(statistics.mean(vals), 3),
                    "win_rate": round(wins / len(vals), 3),
                }

    # By EV source (proxy calibration check)
    by_ev_source = defaultdict(lambda: defaultdict(list))
    for e in evaluated:
        src = e.get("ev_source", "unknown")
        for h in HORIZONS:
            key = f"fwd_{h}d"
            if key in e:
                by_ev_source[src][f"{h}d"].append(e[key])

    source_perf = {}
    for src, horizons in by_ev_source.items():
        source_perf[src] = {}
        for h_label, vals in horizons.items():
            if vals:
                wins = sum(1 for v in vals if v > 0)
                source_perf[src][h_label] = {
                    "n": len(vals),
                    "mean_ret_pct": round(statistics.mean(vals), 3),
                    "win_rate": round(wins / len(vals), 3),
                }

    # By confidence bucket
    buckets = {"low": (0, 0.50), "medium": (0.50, 0.70), "high": (0.70, 1.01)}
    by_conf = defaultdict(lambda: defaultdict(list))
    for e in evaluated:
        conf = e.get("mispricing_confidence", 0) or 0
        for label, (lo, hi) in buckets.items():
            if lo <= conf < hi:
                for h in HORIZONS:
                    key = f"fwd_{h}d"
                    if key in e:
                        by_conf[label][f"{h}d"].append(e[key])
                break

    conf_perf = {}
    for label, horizons in by_conf.items():
        conf_perf[label] = {}
        for h_label, vals in horizons.items():
            if vals:
                wins = sum(1 for v in vals if v > 0)
                conf_perf[label][h_label] = {
                    "n": len(vals),
                    "mean_ret_pct": round(statistics.mean(vals), 3),
                    "win_rate": round(wins / len(vals), 3),
                }

    return {
        "status": "evaluated",
        "n_tradeable": len(attr_records),
        "n_evaluated": len(evaluated),
        "n_decisions_total": len(dec_records),
        "decision_counts": dict(dec_summary),
        "aggregate_performance": performance,
        "by_mispricing_type": type_perf,
        "by_ev_source": source_perf,
        "by_confidence_bucket": conf_perf,
        "evaluated_tickers": sorted(set(e["ticker"] for e in evaluated)),
    }


def _format_report(result: Dict[str, Any]) -> str:
    lines = []
    lines.append("=" * 70)
    lines.append("EXPRESSION OVERLAY — FORWARD EVALUATION PANEL")
    lines.append(
        f"Tradeable: {result.get('n_tradeable', 0)}, "
        f"Evaluated: {result.get('n_evaluated', 0)}, "
        f"Decisions: {result.get('n_decisions_total', 0)}"
    )
    lines.append("=" * 70)

    if result.get("status") != "evaluated":
        lines.append(f"\nStatus: {result.get('status', 'unknown')}")
        return "\n".join(lines)

    lines.append(f"\nDecision counts: {result.get('decision_counts', {})}")

    lines.append("\n--- AGGREGATE PERFORMANCE ---")
    for h_label, perf in sorted(result.get("aggregate_performance", {}).items()):
        lines.append(
            f"  {h_label:>4s}: ret={perf['mean_ret_pct']:+.3f}%  " f"win={perf['win_rate']:.1%}  " f"n={perf['n']}"
        )

    lines.append("\n--- BY MISPRICING TYPE ---")
    for mt, horizons in sorted(result.get("by_mispricing_type", {}).items()):
        lines.append(f"  {mt}:")
        for h_label, perf in sorted(horizons.items()):
            lines.append(
                f"    {h_label:>4s}: ret={perf['mean_ret_pct']:+.3f}%  " f"win={perf['win_rate']:.1%}  n={perf['n']}"
            )

    lines.append("\n--- BY EV SOURCE (proxy calibration) ---")
    for src, horizons in sorted(result.get("by_ev_source", {}).items()):
        lines.append(f"  {src}:")
        for h_label, perf in sorted(horizons.items()):
            lines.append(
                f"    {h_label:>4s}: ret={perf['mean_ret_pct']:+.3f}%  " f"win={perf['win_rate']:.1%}  n={perf['n']}"
            )

    lines.append("\n--- BY CONFIDENCE BUCKET ---")
    for label, horizons in sorted(result.get("by_confidence_bucket", {}).items()):
        lines.append(f"  {label}:")
        for h_label, perf in sorted(horizons.items()):
            lines.append(
                f"    {h_label:>4s}: ret={perf['mean_ret_pct']:+.3f}%  " f"win={perf['win_rate']:.1%}  n={perf['n']}"
            )

    lines.append(
        f"\nTickers evaluated: {', '.join(result.get('evaluated_tickers', [])[:20])}"
        + ("..." if len(result.get("evaluated_tickers", [])) > 20 else "")
    )
    lines.append("\n" + "=" * 70)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Expression overlay forward evaluation panel")
    parser.add_argument("--attr-log", type=Path, default=PROJECT_ROOT / "data" / "expression_attribution_log.jsonl")
    parser.add_argument("--dec-log", type=Path, default=PROJECT_ROOT / "data" / "expression_decision_log.jsonl")
    parser.add_argument("--price-csv", type=Path, default=PROJECT_ROOT / "production_data" / "price_history.csv")
    parser.add_argument("--min-days", type=int, default=5)
    args = parser.parse_args()

    result = evaluate_panel(args.attr_log, args.dec_log, args.price_csv, args.min_days)

    out_dir = PROJECT_ROOT / "output" / "expression_forward_panel"
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "forward_panel.json", "w") as f:
        json.dump(result, f, indent=2)

    report = _format_report(result)
    print(report)
    with open(out_dir / "forward_panel_report.txt", "w") as f:
        f.write(report)

    print(f"\nResults: {out_dir}/")


if __name__ == "__main__":
    main()
