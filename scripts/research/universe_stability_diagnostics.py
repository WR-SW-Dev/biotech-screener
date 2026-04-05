#!/usr/bin/env python3
"""Universe stability diagnostics (Item 10 — quant hardening).

Tracks cross-sectional distribution drift of key z-scored signals over time.
Monitors composition shift and moment drift. Does NOT attempt corrections.

Outputs a diagnostic artifact showing:
  - Universe size over time
  - Signal distribution moments (mean, std, skew, kurtosis) per snapshot
  - Composition turnover (Jaccard overlap between adjacent snapshots)
  - Drift flags for moments that shift materially

Usage:
    python3 scripts/research/universe_stability_diagnostics.py
    python3 scripts/research/universe_stability_diagnostics.py --panel output/signals/research_panel.csv
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

PANEL_CSV = PROJECT_ROOT / "output" / "signals" / "research_panel.csv"
OUTPUT_DIR = PROJECT_ROOT / "output" / "universe_stability"

# Signals to track
TRACKED_SIGNALS = [
    "coinvest_score_z",
    "inst_delta_z",
    "clinical_score_v2_z",
    "catalyst_decay_w",
    "financial_score",
    "composite_score",
]


def _safe_float(val, default=None):
    if val is None or val == "":
        return default
    try:
        v = float(val)
        return v if not math.isnan(v) else default
    except (ValueError, TypeError):
        return default


def _moments(vals: List[float]) -> Dict[str, Optional[float]]:
    """Compute mean, std, skew, kurtosis for a list of values."""
    n = len(vals)
    if n < 3:
        return {"mean": None, "std": None, "skew": None, "kurtosis": None, "n": n}
    mean = sum(vals) / n
    var = sum((v - mean) ** 2 for v in vals) / n
    std = var**0.5
    if std < 1e-12:
        return {"mean": round(mean, 4), "std": 0.0, "skew": 0.0, "kurtosis": 0.0, "n": n}
    skew = sum(((v - mean) / std) ** 3 for v in vals) / n
    kurt = sum(((v - mean) / std) ** 4 for v in vals) / n - 3.0
    return {
        "mean": round(mean, 4),
        "std": round(std, 4),
        "skew": round(skew, 4),
        "kurtosis": round(kurt, 4),
        "n": n,
    }


def _jaccard(set_a: set, set_b: set) -> float:
    if not set_a and not set_b:
        return 1.0
    inter = len(set_a & set_b)
    union = len(set_a | set_b)
    return inter / union if union > 0 else 0.0


def run_diagnostics(panel_path: Path) -> Dict[str, Any]:
    """Compute universe stability diagnostics from research panel."""
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

    # Per-snapshot diagnostics
    snapshots = []
    prev_tickers: set = set()

    for d in snap_dates:
        rows = by_date[d]
        eligible = [r for r in rows if r.get("eligible", "") not in ("0", "0.0", "")]
        tickers = {r.get("ticker", "") for r in eligible}

        # Composition overlap
        jaccard = _jaccard(tickers, prev_tickers) if prev_tickers else None

        # Signal moments
        signal_moments = {}
        for sig in TRACKED_SIGNALS:
            vals = [v for v in (_safe_float(r.get(sig)) for r in eligible) if v is not None]
            signal_moments[sig] = _moments(vals)

        snapshots.append(
            {
                "date": d,
                "n_eligible": len(eligible),
                "n_total": len(rows),
                "jaccard_vs_prior": round(jaccard, 4) if jaccard is not None else None,
                "signals": signal_moments,
            }
        )
        prev_tickers = tickers

    # Aggregate drift summary
    drift_summary = {}
    for sig in TRACKED_SIGNALS:
        means = [s["signals"][sig]["mean"] for s in snapshots if s["signals"][sig]["mean"] is not None]
        stds = [s["signals"][sig]["std"] for s in snapshots if s["signals"][sig]["std"] is not None]
        if len(means) >= 5:
            # First half vs second half comparison
            half = len(means) // 2
            first_mean = sum(means[:half]) / half
            second_mean = sum(means[half:]) / (len(means) - half)
            first_std = sum(stds[:half]) / half if stds[:half] else 0
            second_std = sum(stds[half:]) / (len(stds) - half) if stds[half:] else 0
            mean_shift = second_mean - first_mean
            std_shift = second_std - first_std

            drift_summary[sig] = {
                "mean_first_half": round(first_mean, 4),
                "mean_second_half": round(second_mean, 4),
                "mean_shift": round(mean_shift, 4),
                "std_first_half": round(first_std, 4),
                "std_second_half": round(second_std, 4),
                "std_shift": round(std_shift, 4),
                "material": abs(mean_shift) > 0.3 or abs(std_shift) > 0.3,
            }

    # Composition drift
    jaccards = [s["jaccard_vs_prior"] for s in snapshots if s["jaccard_vs_prior"] is not None]
    sizes = [s["n_eligible"] for s in snapshots]

    return {
        "schema": "universe_stability_diagnostics.v1",
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "panel_path": str(panel_path),
        "n_snapshots": len(snap_dates),
        "composition": {
            "mean_jaccard": round(sum(jaccards) / len(jaccards), 4) if jaccards else None,
            "min_jaccard": round(min(jaccards), 4) if jaccards else None,
            "mean_size": round(sum(sizes) / len(sizes), 1) if sizes else None,
            "size_range": [min(sizes), max(sizes)] if sizes else None,
        },
        "drift_summary": drift_summary,
        "snapshots": snapshots,
    }


def main():
    parser = argparse.ArgumentParser(description="Universe stability diagnostics")
    parser.add_argument("--panel", type=Path, default=PANEL_CSV)
    parser.add_argument("--out-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    result = run_diagnostics(args.panel)

    out_path = args.out_dir / "stability_diagnostics.json"
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\nSaved: {out_path}")

    # Markdown summary
    md = [
        "# Universe Stability Diagnostics",
        "",
        f"Snapshots: {result['n_snapshots']}",
        f"Mean Jaccard overlap: {result['composition']['mean_jaccard']}",
        f"Min Jaccard overlap: {result['composition']['min_jaccard']}",
        f"Universe size range: {result['composition']['size_range']}",
        "",
        "## Signal Distribution Drift (first half vs second half)",
        "",
        "| Signal | Mean₁ | Mean₂ | Shift | Std₁ | Std₂ | Material? |",
        "|--------|-------|-------|-------|------|------|-----------|",
    ]
    for sig, ds in result["drift_summary"].items():
        flag = "YES" if ds["material"] else "no"
        md.append(
            f"| {sig} | {ds['mean_first_half']} | {ds['mean_second_half']} "
            f"| {ds['mean_shift']:+.4f} | {ds['std_first_half']} "
            f"| {ds['std_second_half']} | {flag} |"
        )

    md_path = args.out_dir / "stability_diagnostics.md"
    md_path.write_text("\n".join(md))
    print(f"Saved: {md_path}")


if __name__ == "__main__":
    main()
