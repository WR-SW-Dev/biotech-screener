#!/usr/bin/env python3
"""Evaluate binary_91_180 within-bucket re-ranking candidates vs baseline.

Runs bucket_filter=["less_binary"] evaluation for:
  - Baseline (v1.10.0, snapshots_reranked_v1100)
  - quality_primary (snapshots_reranked_b91_quality_primary)
  - quality_plus_institutional (snapshots_reranked_b91_quality_plus_inst)

Output: output/research/b91_rerank/VERDICT.md + RESULTS.csv
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from eval_forward_returns import evaluate

PRICE_CSV = PROJECT_ROOT / "production_data" / "price_history.csv"
OOS_DATES = PROJECT_ROOT / "output" / "audited_sets" / "audited_dates_2020_2024_strict.txt"
IS_DATES = PROJECT_ROOT / "output" / "audited_sets" / "audited_dates_2025_strict.txt"
OUT_DIR = PROJECT_ROOT / "output" / "research" / "b91_rerank"

HORIZONS = [84, 126]
BUCKET_FILTER = ["less_binary"]
COST_BPS = 30.0
BENCHMARK = "XBI"
BUFFER = 30
TOP_K = 20

ARMS = {
    "baseline": PROJECT_ROOT / "data" / "snapshots_reranked_v1100",
    "quality_primary": PROJECT_ROOT / "data" / "snapshots_reranked_b91_quality_primary",
    "quality_plus_inst": PROJECT_ROOT / "data" / "snapshots_reranked_b91_quality_plus_inst",
}


def _load_dates(path: Path) -> set:
    return {d.strip() for d in path.read_text().splitlines() if d.strip()}


def _run_eval(name: str, snap_root: Path, dates: set, window: str) -> Dict[str, Any]:
    print(f"  Running {name} / {window} ({len(dates)} dates)...")
    summary, date_results, skips = evaluate(
        snapshot_root=snap_root,
        price_csv=PRICE_CSV,
        horizons=HORIZONS,
        top_k=TOP_K,
        cost_bps=COST_BPS,
        allowed_dates=dates,
        benchmark=BENCHMARK,
        bucket_filter=BUCKET_FILTER,
        rebalance_buffer_ranks=BUFFER,
        anchor_mode="prev_trading_day",
    )

    row = {"arm": name, "window": window, "n_dates": summary.n_dates}
    for h in HORIZONS:
        bh = summary.by_horizon.get(h, {})
        hk = f"{h}d"
        row[f"hedged_{hk}"] = bh.get("mean_hedged_return")
        row[f"excess_{hk}"] = bh.get("mean_excess_return")
        row[f"gross_{hk}"] = bh.get("mean_gross_return")
        row[f"net_{hk}"] = bh.get("mean_net_return")
        row[f"turnover_{hk}"] = bh.get("mean_turnover")
        row[f"ic_{hk}"] = bh.get("mean_ic")
        row[f"ic_t_{hk}"] = bh.get("ic_t_stat")
    return row


def _fmt_pct(v: Optional[float]) -> str:
    if v is None:
        return "—"
    return f"{v * 100:.2f}%"


def _fmt(v: Optional[float], dp: int = 4) -> str:
    if v is None:
        return "—"
    return f"{v:.{dp}f}"


def _delta_pp(cand: Optional[float], base: Optional[float]) -> str:
    if cand is None or base is None:
        return "—"
    d = (cand - base) * 100
    sign = "+" if d >= 0 else ""
    return f"{sign}{d:.2f}pp"


def main():
    oos_dates = _load_dates(OOS_DATES)
    is_dates = _load_dates(IS_DATES)

    results: List[Dict[str, Any]] = []

    for arm_name, snap_root in ARMS.items():
        print(f"\n{'='*60}")
        print(f"ARM: {arm_name}")
        print(f"{'='*60}")

        oos = _run_eval(arm_name, snap_root, oos_dates, "OOS")
        is_ = _run_eval(arm_name, snap_root, is_dates, "IS")

        print(f"  OOS 126d hedged: {_fmt_pct(oos.get('hedged_126d'))}")
        print(f"  IS  126d hedged: {_fmt_pct(is_.get('hedged_126d'))}")

        results.append(oos)
        results.append(is_)

    # Write CSV
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUT_DIR / "RESULTS.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        w.writeheader()
        w.writerows(results)
    print(f"\nCSV: {csv_path}")

    # Build verdict
    base_oos = next(r for r in results if r["arm"] == "baseline" and r["window"] == "OOS")
    base_is = next(r for r in results if r["arm"] == "baseline" and r["window"] == "IS")

    lines = [
        "# VERDICT: Binary 91-180 Within-Bucket Re-Ranking",
        "",
        "## Results Table",
        "",
        "| Arm | Window | 126d Hedged | 84d Hedged | 126d Excess | Turnover | IC 126d | Δ 126d Hedged |",
        "|-----|--------|-------------|------------|-------------|----------|---------|---------------|",
    ]

    for r in results:
        base_ref = base_oos if r["window"] == "OOS" else base_is
        delta = _delta_pp(r.get("hedged_126d"), base_ref.get("hedged_126d"))
        lines.append(
            f"| {r['arm']} | {r['window']} "
            f"| {_fmt_pct(r.get('hedged_126d'))} "
            f"| {_fmt_pct(r.get('hedged_84d'))} "
            f"| {_fmt_pct(r.get('excess_126d'))} "
            f"| {_fmt(r.get('turnover_126d'))} "
            f"| {_fmt(r.get('ic_126d'))} "
            f"| {delta} |"
        )

    # Determine winner
    cand_oos = [r for r in results if r["arm"] != "baseline" and r["window"] == "OOS"]
    best_cand = max(cand_oos, key=lambda r: r.get("hedged_126d") or -999)

    oos_delta = (best_cand.get("hedged_126d") or 0) - (base_oos.get("hedged_126d") or 0)
    oos_84_delta = (best_cand.get("hedged_84d") or 0) - (base_oos.get("hedged_84d") or 0)

    verdict = (
        "PROMOTE"
        if oos_delta >= 0.002 and oos_84_delta >= -0.0005
        else ("ARCHIVE" if oos_delta < -0.001 else "NEEDS_MORE")
    )

    lines.extend(
        [
            "",
            "## Acceptance Criteria",
            "",
            f"- Primary: Δ(OOS 126d hedged) ≥ +0.20pp → {'PASS' if oos_delta >= 0.002 else 'FAIL'} ({_delta_pp(best_cand.get('hedged_126d'), base_oos.get('hedged_126d'))})",
            f"- Guardrail: Δ(OOS 84d hedged) ≥ -0.05pp → {'PASS' if oos_84_delta >= -0.0005 else 'FAIL'} ({_delta_pp(best_cand.get('hedged_84d'), base_oos.get('hedged_84d'))})",
            "",
            f"## Verdict: **{verdict}**",
            "",
            f"Best candidate: **{best_cand['arm']}**",
            f"- OOS 126d hedged: {_fmt_pct(best_cand.get('hedged_126d'))} (Δ {_delta_pp(best_cand.get('hedged_126d'), base_oos.get('hedged_126d'))})",
            f"- OOS 84d hedged: {_fmt_pct(best_cand.get('hedged_84d'))} (Δ {_delta_pp(best_cand.get('hedged_84d'), base_oos.get('hedged_84d'))})",
            "",
            "---",
            "",
            f"*OOS: {base_oos['n_dates']} dates (2020-2024), IS: {base_is['n_dates']} dates (2025)*",
            f'*bucket_filter=["less_binary"], K={TOP_K}, buffer={BUFFER}, benchmark={BENCHMARK}*',
            "",
        ]
    )

    verdict_path = OUT_DIR / "VERDICT.md"
    verdict_path.write_text("\n".join(lines))
    print(f"Verdict: {verdict_path}")
    print(f"\nVERDICT: {verdict}")


if __name__ == "__main__":
    main()
