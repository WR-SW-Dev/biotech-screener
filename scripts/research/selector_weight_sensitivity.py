#!/usr/bin/env python3
"""Selector block-weight sensitivity grid (Item 9 — quant hardening).

Tests a controlled grid of institutional block weights around the current
A4 config. Uses the research panel for forward-return IC computation.

This is a diagnostic script — no production changes. Output is a
comparison table showing IC stability across weight configurations.

Usage:
    python3 scripts/research/selector_weight_sensitivity.py
    python3 scripts/research/selector_weight_sensitivity.py --panel output/signals/research_panel.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from selector_engine import BlockWeight, SelectorConfig, SignalSpec, compute_selector_scores

PANEL_CSV = PROJECT_ROOT / "output" / "signals" / "research_panel.csv"
OUTPUT_DIR = PROJECT_ROOT / "output" / "selector_weight_sensitivity"

# Current production config (A4 v1.1)
PRODUCTION_INST_WEIGHT = 0.65
PRODUCTION_INST_SIGNALS = (
    SignalSpec("coinvest_score_z", 0.65),
    SignalSpec("inst_delta_z", 0.35),
    SignalSpec(
        "coinvest_recency_state",
        0.00,
        categorical=True,
        value_map=(("fresh", 1.0), ("stale", 0.3), ("", 0.0)),
    ),
)

# Grid: vary institutional weight, redistribute remainder proportionally
INST_WEIGHTS = [0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80]

# Other blocks share the remainder proportionally
# Current non-inst ratios: catalyst=0.15, survivability=0.10, market=0.10
# (clinical=0.00 after item 2)
NON_INST_RATIOS = {"catalyst": 0.15, "survivability": 0.10, "market_structure": 0.10}


def _make_config(inst_weight: float) -> SelectorConfig:
    """Build a SelectorConfig with the given institutional weight."""
    remainder = 1.0 - inst_weight
    ratio_sum = sum(NON_INST_RATIOS.values())
    blocks = [BlockWeight("clinical", 0.00)]
    for name, ratio in NON_INST_RATIOS.items():
        blocks.append(BlockWeight(name, round(remainder * ratio / ratio_sum, 4)))
    blocks.append(BlockWeight("institutional", inst_weight))
    return SelectorConfig(
        block_weights=tuple(blocks),
        institutional_signals=PRODUCTION_INST_SIGNALS,
    )


def _spearman_ic(x: List[float], y: List[float]) -> Optional[float]:
    """Compute Spearman rank IC between two lists."""
    if len(x) != len(y) or len(x) < 5:
        return None
    n = len(x)

    def _rank(vals):
        indexed = sorted(range(n), key=lambda i: vals[i])
        ranks = [0.0] * n
        for rank, idx in enumerate(indexed):
            ranks[idx] = rank + 1
        return ranks

    rx = _rank(x)
    ry = _rank(y)
    d_sq = sum((rx[i] - ry[i]) ** 2 for i in range(n))
    return 1.0 - 6.0 * d_sq / (n * (n * n - 1))


def _safe_float(val, default=None):
    if val is None or val == "":
        return default
    try:
        v = float(val)
        return v if not math.isnan(v) else default
    except (ValueError, TypeError):
        return default


def run_sensitivity(panel_path: Path) -> Dict[str, Any]:
    """Run the full sensitivity grid."""
    # Load panel
    with open(panel_path, newline="", encoding="utf-8") as f:
        panel = list(csv.DictReader(f))

    # Group by snapshot date
    by_date: Dict[str, List[Dict]] = {}
    for row in panel:
        d = row.get("snapshot_date", "")
        if d:
            by_date.setdefault(d, []).append(row)

    snap_dates = sorted(by_date.keys())
    print(f"Panel: {len(panel)} rows, {len(snap_dates)} snapshots")

    # For each weight config, compute IC across all snapshots
    results = []
    for inst_w in INST_WEIGHTS:
        config = _make_config(inst_w)
        ics_20d = []
        ics_63d = []

        for d in snap_dates:
            rows = by_date[d]
            # Filter to eligible rows with forward returns
            eligible = [
                r
                for r in rows
                if r.get("eligible", "") not in ("0", "0.0", "") and _safe_float(r.get("fwd_ret_20d")) is not None
            ]
            if len(eligible) < 10:
                continue

            # Compute selector scores
            try:
                sel_results = compute_selector_scores(eligible, config)
            except Exception:
                continue

            scores = [sr.selector_score for sr in sel_results]
            rets_20d = [_safe_float(r.get("fwd_ret_20d"), 0) for r in eligible]
            rets_63d = [_safe_float(r.get("fwd_ret_63d"), 0) for r in eligible]

            ic_20 = _spearman_ic(scores, rets_20d)
            if ic_20 is not None:
                ics_20d.append(ic_20)

            if all(v is not None for v in rets_63d):
                ic_63 = _spearman_ic(scores, rets_63d)
                if ic_63 is not None:
                    ics_63d.append(ic_63)

        mean_ic_20 = sum(ics_20d) / len(ics_20d) if ics_20d else None
        mean_ic_63 = sum(ics_63d) / len(ics_63d) if ics_63d else None
        n_dates = len(ics_20d)

        # t-stat
        if ics_20d and len(ics_20d) > 1:
            std_20 = (sum((v - mean_ic_20) ** 2 for v in ics_20d) / (len(ics_20d) - 1)) ** 0.5
            t_20 = mean_ic_20 / (std_20 / len(ics_20d) ** 0.5) if std_20 > 0 else 0
        else:
            t_20 = None

        entry = {
            "inst_weight": inst_w,
            "catalyst_weight": round((1 - inst_w) * 0.15 / 0.35, 4),
            "mean_ic_20d": round(mean_ic_20, 4) if mean_ic_20 is not None else None,
            "mean_ic_63d": round(mean_ic_63, 4) if mean_ic_63 is not None else None,
            "ic_t_stat_20d": round(t_20, 2) if t_20 is not None else None,
            "n_dates": n_dates,
            "is_production": inst_w == PRODUCTION_INST_WEIGHT,
        }
        results.append(entry)
        marker = " ← PRODUCTION" if inst_w == PRODUCTION_INST_WEIGHT else ""
        print(
            f"  inst={inst_w:.0%}  IC_20d={entry['mean_ic_20d']}  "
            f"IC_63d={entry['mean_ic_63d']}  t={entry['ic_t_stat_20d']}  "
            f"n={n_dates}{marker}"
        )

    return {
        "schema": "selector_weight_sensitivity.v1",
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "panel_path": str(panel_path),
        "n_snapshots": len(snap_dates),
        "grid": results,
    }


def main():
    parser = argparse.ArgumentParser(description="Selector weight sensitivity grid")
    parser.add_argument("--panel", type=Path, default=PANEL_CSV)
    parser.add_argument("--out-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    result = run_sensitivity(args.panel)

    out_path = args.out_dir / "sensitivity_grid.json"
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\nSaved: {out_path}")

    # Markdown summary
    md_lines = [
        "# Selector Weight Sensitivity Grid",
        "",
        f"Panel: {result['n_snapshots']} snapshots",
        "",
        "| Inst Wt | Cat Wt | IC 20d | IC 63d | t-stat | n | |",
        "|---------|--------|--------|--------|--------|---|---|",
    ]
    for g in result["grid"]:
        marker = "**PROD**" if g["is_production"] else ""
        md_lines.append(
            f"| {g['inst_weight']:.0%} | {g['catalyst_weight']:.0%} "
            f"| {g['mean_ic_20d']} | {g['mean_ic_63d']} "
            f"| {g['ic_t_stat_20d']} | {g['n_dates']} | {marker} |"
        )
    md_path = args.out_dir / "sensitivity_grid.md"
    md_path.write_text("\n".join(md_lines))
    print(f"Saved: {md_path}")


if __name__ == "__main__":
    main()
