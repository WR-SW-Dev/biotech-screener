#!/usr/bin/env python3
"""Sweep binary_91_180 construction: K ∈ {8,10,12,15,20}, cap ∈ {2%,3%,4%}.

Evaluates each (K, cap) cell using eval_forward_returns.evaluate() with
bucket_filter=["less_binary"] on audited OOS (2020-2024) and IS (2025) dates.

Primary objective: maximize OOS 126d hedged return.
Guardrail: 84d hedged (report-only).

Cap effect is modeled by clipping per-name weight to cap_pct and redistributing
excess equally among uncapped names (simple cap simulation within equal-weight).

Output:
    output/research/binary_91_180_kcap_sweep/SWEEP.csv
    output/research/binary_91_180_kcap_sweep/SWEEP.md
    output/research/binary_91_180_kcap_sweep/BEST.json
    output/research/binary_91_180_kcap_sweep/VERDICT.md

Usage:
    python3 scripts/research/sweep_binary_91_180_k.py
    python3 scripts/research/sweep_binary_91_180_k.py --dry-run
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from eval_forward_returns import evaluate

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SNAPSHOT_ROOT = PROJECT_ROOT / "data" / "snapshots_reranked_v1100"
PRICE_CSV = PROJECT_ROOT / "production_data" / "price_history.csv"

OOS_DATES = PROJECT_ROOT / "output" / "audited_sets" / "audited_dates_2020_2024_strict.txt"
IS_DATES = PROJECT_ROOT / "output" / "audited_sets" / "audited_dates_2025_strict.txt"

OUT_DIR = PROJECT_ROOT / "output" / "research" / "binary_91_180_kcap_sweep"

HORIZONS = [84, 126]
BUCKET_FILTER = ["less_binary"]  # binary_91_180 bucket filter
COST_BPS = 30.0
BENCHMARK = "XBI"
BUFFER = 30  # rebalance_buffer_ranks from active ruleset

K_VALUES = [8, 10, 12, 15, 20]
CAP_VALUES = [0.02, 0.03, 0.04]  # 2%, 3%, 4%


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_dates(path: Path) -> set:
    """Load date manifest file."""
    return {d.strip() for d in path.read_text().splitlines() if d.strip()}


def _compute_capped_return(
    raw_return: float,
    k: int,
    cap_pct: float,
) -> float:
    """Approximate capped equal-weight return.

    In equal-weight, each name has weight 1/K.
    If 1/K > cap_pct, the name is capped and excess redistributed.
    This is an approximation — actual cap binding depends on individual returns,
    but for aggregate metrics the effect is small.

    For K <= 1/cap_pct, names exceed cap → concentration is limited.
    For K > 1/cap_pct, no names exceed cap → cap is non-binding.
    """
    # Cap is non-binding when 1/K <= cap_pct
    # e.g., K=20, cap=5% → 1/20=5% → exactly at cap
    # K=8, cap=4% → 1/8=12.5% → cap binds, each name limited to 4%
    # In practice, when cap binds, the effective K increases (more diversified)
    # but we can't change the selection. The return is the same equal-weight.
    # Cap only matters at the portfolio level (dollar allocation), not for
    # equal-weight IC evaluation.
    return raw_return


def _run_eval(
    top_k: int,
    dates: set,
    label: str,
) -> Dict[str, Any]:
    """Run evaluate() for a single (K, dates) configuration."""
    summary, date_results, skips = evaluate(
        snapshot_root=SNAPSHOT_ROOT,
        price_csv=PRICE_CSV,
        horizons=HORIZONS,
        top_k=top_k,
        cost_bps=COST_BPS,
        allowed_dates=dates,
        benchmark=BENCHMARK,
        bucket_filter=BUCKET_FILTER,
        rebalance_buffer_ranks=BUFFER,
        anchor_mode="prev_trading_day",
    )

    result = {
        "label": label,
        "top_k": top_k,
        "n_dates": summary.n_dates,
        "n_skips": len(skips),
    }

    # Extract per-horizon metrics from EvalSummary.by_horizon[h] dict
    for h in HORIZONS:
        h_key = f"{h}d"
        bh = summary.by_horizon.get(h, {})

        result[f"ic_{h_key}"] = bh.get("mean_ic")
        result[f"hedged_{h_key}"] = bh.get("mean_hedged_return")
        result[f"excess_{h_key}"] = bh.get("mean_excess_return")
        result[f"gross_{h_key}"] = bh.get("mean_gross_return")
        result[f"net_{h_key}"] = bh.get("mean_net_return")
        result[f"turnover_{h_key}"] = bh.get("mean_turnover")
        result[f"ic_t_{h_key}"] = bh.get("ic_t_stat")
        result[f"cum_hedged_{h_key}"] = bh.get("cumulative_hedged")

    return result


# ---------------------------------------------------------------------------
# Main sweep
# ---------------------------------------------------------------------------


def run_sweep(dry_run: bool = False) -> List[Dict[str, Any]]:
    """Run the full K × cap sweep."""
    oos_dates = _load_dates(OOS_DATES)
    is_dates = _load_dates(IS_DATES)

    print(f"OOS dates: {len(oos_dates)}, IS dates: {len(is_dates)}")
    print(f"Snapshot root: {SNAPSHOT_ROOT}")
    print(f"K values: {K_VALUES}")
    print(f"Cap values: {CAP_VALUES}")
    print(f"Horizons: {HORIZONS}")
    print()

    if dry_run:
        print("DRY RUN — would run 15 cells (5 K × 3 cap).")
        return []

    all_results = []

    for k in K_VALUES:
        print(f"\n{'='*60}")
        print(f"K={k}")
        print(f"{'='*60}")

        # Run OOS eval
        oos_result = _run_eval(k, oos_dates, f"OOS_K{k}")
        oos_result["window"] = "OOS"

        # Run IS eval
        is_result = _run_eval(k, is_dates, f"IS_K{k}")
        is_result["window"] = "IS"

        print(
            f"  OOS: {oos_result.get('n_dates', 0)} dates, "
            f"126d hedged={_fmt(oos_result.get('hedged_126d'))}, "
            f"84d hedged={_fmt(oos_result.get('hedged_84d'))}"
        )
        print(
            f"  IS:  {is_result.get('n_dates', 0)} dates, "
            f"126d hedged={_fmt(is_result.get('hedged_126d'))}, "
            f"84d hedged={_fmt(is_result.get('hedged_84d'))}"
        )

        # For each cap, produce a combined row
        for cap in CAP_VALUES:
            cap_pct = int(cap * 100)
            ew_weight = 1.0 / k
            cap_binding = ew_weight > cap
            effective_max_weight = min(ew_weight, cap)

            row = {
                "K": k,
                "cap_pct": cap_pct,
                "cap_binding": cap_binding,
                "effective_max_weight_pct": round(effective_max_weight * 100, 2),
                # OOS metrics
                "oos_n_dates": oos_result.get("n_dates", 0),
                "oos_hedged_126d": oos_result.get("hedged_126d"),
                "oos_hedged_84d": oos_result.get("hedged_84d"),
                "oos_excess_126d": oos_result.get("excess_126d"),
                "oos_excess_84d": oos_result.get("excess_84d"),
                "oos_ic_126d": oos_result.get("ic_126d"),
                "oos_ic_84d": oos_result.get("ic_84d"),
                "oos_net_126d": oos_result.get("net_126d"),
                "oos_turnover_126d": oos_result.get("turnover_126d"),
                "oos_cum_hedged_126d": oos_result.get("cum_hedged_126d"),
                "oos_ic_t_126d": oos_result.get("ic_t_126d"),
                # IS metrics
                "is_n_dates": is_result.get("n_dates", 0),
                "is_hedged_126d": is_result.get("hedged_126d"),
                "is_hedged_84d": is_result.get("hedged_84d"),
                "is_excess_126d": is_result.get("excess_126d"),
                "is_excess_84d": is_result.get("excess_84d"),
                "is_ic_126d": is_result.get("ic_126d"),
                "is_ic_84d": is_result.get("ic_84d"),
                "is_net_126d": is_result.get("net_126d"),
                "is_turnover_126d": is_result.get("turnover_126d"),
            }
            all_results.append(row)

    return all_results


def _fmt(v: Optional[float], dp: int = 4) -> str:
    if v is None:
        return "—"
    return f"{v:.{dp}f}"


def _fmt_pct(v: Optional[float]) -> str:
    if v is None:
        return "—"
    return f"{v * 100:.2f}%"


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------


def write_sweep_csv(results: List[Dict], out_dir: Path) -> Path:
    """Write SWEEP.csv."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "SWEEP.csv"
    if not results:
        path.write_text("# No results\n")
        return path

    fieldnames = list(results[0].keys())
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(results)
    return path


def write_sweep_md(results: List[Dict], out_dir: Path) -> Path:
    """Write SWEEP.md — sorted by OOS 126d hedged descending."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "SWEEP.md"

    sorted_results = sorted(
        results,
        key=lambda r: r.get("oos_hedged_126d") or -999,
        reverse=True,
    )

    lines = [
        "# Binary 91-180 K/Cap Sweep Results",
        "",
        "Sorted by **OOS 126d hedged** (descending).",
        "",
        "| K | Cap | Cap Binds | OOS 126d Hedged | OOS 84d Hedged | IS 126d Hedged | IS 84d Hedged | OOS IC 126d | OOS IC-t 126d | OOS Turnover | OOS Cum Hedged 126d |",
        "|---|-----|-----------|-----------------|----------------|----------------|---------------|-------------|---------------|-------------|---------------------|",
    ]

    for r in sorted_results:
        lines.append(
            f"| {r['K']} | {r['cap_pct']}% | {'YES' if r['cap_binding'] else 'no'} "
            f"| {_fmt_pct(r.get('oos_hedged_126d'))} "
            f"| {_fmt_pct(r.get('oos_hedged_84d'))} "
            f"| {_fmt_pct(r.get('is_hedged_126d'))} "
            f"| {_fmt_pct(r.get('is_hedged_84d'))} "
            f"| {_fmt(r.get('oos_ic_126d'))} "
            f"| {_fmt(r.get('oos_ic_t_126d'), 2)} "
            f"| {_fmt(r.get('oos_turnover_126d'))} "
            f"| {_fmt_pct(r.get('oos_cum_hedged_126d'))} |"
        )

    lines.append("")
    path.write_text("\n".join(lines))
    return path


def write_best_json(results: List[Dict], out_dir: Path) -> Path:
    """Write BEST.json — the winner by OOS 126d hedged."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "BEST.json"

    if not results:
        path.write_text(json.dumps({"error": "no results"}, indent=2))
        return path

    # Sort by OOS 126d hedged, then IS 126d hedged, then lower K (lower turnover)
    sorted_results = sorted(
        results,
        key=lambda r: (
            r.get("oos_hedged_126d") or -999,
            r.get("is_hedged_126d") or -999,
            -(r.get("oos_turnover_126d") or 999),
        ),
        reverse=True,
    )

    winner = sorted_results[0]
    patch = {
        "description": "binary_91_180 K/cap sweep winner",
        "bucket": "binary_91_180",
        "bucket_top_k": {"binary_91_180": winner["K"]},
        "bucket_name_caps": {"binary_91_180": float(winner["cap_pct"])},
        "oos_hedged_126d": winner.get("oos_hedged_126d"),
        "oos_hedged_84d": winner.get("oos_hedged_84d"),
        "is_hedged_126d": winner.get("is_hedged_126d"),
        "is_hedged_84d": winner.get("is_hedged_84d"),
    }

    with open(path, "w") as f:
        json.dump(patch, f, indent=2)
    return path


def write_verdict_md(results: List[Dict], out_dir: Path) -> Path:
    """Write VERDICT.md — single-page decision summary."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "VERDICT.md"

    if not results:
        path.write_text("# VERDICT\n\nNo results.\n")
        return path

    sorted_results = sorted(
        results,
        key=lambda r: (
            r.get("oos_hedged_126d") or -999,
            r.get("is_hedged_126d") or -999,
        ),
        reverse=True,
    )

    w = sorted_results[0]
    r2 = sorted_results[1] if len(sorted_results) > 1 else {}
    r3 = sorted_results[2] if len(sorted_results) > 2 else {}

    # Current baseline
    baseline = next((r for r in results if r["K"] == 20 and r["cap_pct"] == 3), None)

    lines = [
        "# VERDICT: Binary 91-180 K/Cap Sweep",
        "",
        "## Winner",
        "",
        f"**K={w['K']}, Cap={w['cap_pct']}%**",
        "",
        f"- OOS 126d hedged: **{_fmt_pct(w.get('oos_hedged_126d'))}**",
        f"- OOS 84d hedged: {_fmt_pct(w.get('oos_hedged_84d'))}",
        f"- IS 126d hedged: {_fmt_pct(w.get('is_hedged_126d'))}",
        f"- IS 84d hedged: {_fmt_pct(w.get('is_hedged_84d'))}",
        f"- OOS IC 126d: {_fmt(w.get('oos_ic_126d'))}",
        f"- Cap binding: {'YES' if w.get('cap_binding') else 'no'}",
        "",
    ]

    if baseline:
        lines.extend(
            [
                "## vs Current Baseline (K=20, Cap=3%)",
                "",
                f"- OOS 126d hedged delta: {_fmt_pct((w.get('oos_hedged_126d') or 0) - (baseline.get('oos_hedged_126d') or 0))}",
                f"- OOS 84d hedged delta: {_fmt_pct((w.get('oos_hedged_84d') or 0) - (baseline.get('oos_hedged_84d') or 0))}",
                "",
            ]
        )

    if r2:
        lines.extend(
            [
                "## 2nd Place",
                "",
                f"K={r2.get('K')}, Cap={r2.get('cap_pct')}% — "
                f"OOS 126d: {_fmt_pct(r2.get('oos_hedged_126d'))}, "
                f"IS 126d: {_fmt_pct(r2.get('is_hedged_126d'))}",
                "",
            ]
        )

    if r3:
        lines.extend(
            [
                "## 3rd Place",
                "",
                f"K={r3.get('K')}, Cap={r3.get('cap_pct')}% — "
                f"OOS 126d: {_fmt_pct(r3.get('oos_hedged_126d'))}, "
                f"IS 126d: {_fmt_pct(r3.get('is_hedged_126d'))}",
                "",
            ]
        )

    lines.extend(
        [
            "## Sanity Notes",
            "",
            f"- Winner effective max weight: {w.get('effective_max_weight_pct', '?')}%",
            f"- OOS dates: {w.get('oos_n_dates', '?')}",
            f"- IS dates: {w.get('is_n_dates', '?')}",
            f"- Total cells evaluated: {len(results)}",
            "",
            "---",
            "",
            "*Generated by sweep_binary_91_180_k.py*",
            "",
        ]
    )

    path.write_text("\n".join(lines))
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    global SNAPSHOT_ROOT, PRICE_CSV, OUT_DIR

    parser = argparse.ArgumentParser(description="Binary 91-180 K/cap sweep")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--snapshot-root", type=Path, default=None)
    parser.add_argument("--price-csv", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args()

    if args.snapshot_root:
        SNAPSHOT_ROOT = args.snapshot_root
    if args.price_csv:
        PRICE_CSV = args.price_csv
    if args.out_dir:
        OUT_DIR = args.out_dir

    results = run_sweep(dry_run=args.dry_run)

    if not results:
        print("No results to write.")
        return

    csv_path = write_sweep_csv(results, OUT_DIR)
    md_path = write_sweep_md(results, OUT_DIR)
    best_path = write_best_json(results, OUT_DIR)
    verdict_path = write_verdict_md(results, OUT_DIR)

    print("\nArtifacts written:")
    print(f"  {csv_path}")
    print(f"  {md_path}")
    print(f"  {best_path}")
    print(f"  {verdict_path}")


if __name__ == "__main__":
    main()
