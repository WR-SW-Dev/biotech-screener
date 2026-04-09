#!/usr/bin/env python3
"""Herald precision dashboard -- rolling weekly metrics + drift detection.

Aggregates herald_precision metrics over a rolling window and flags
categories where classifier precision has drifted.

Usage:
    python tools/build_herald_precision_dashboard.py --as-of-date 2026-04-05
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

METRICS_DIR = PROJECT_ROOT / "artifacts" / "herald_precision"
OUTPUT_DIR = METRICS_DIR

SCHEMA = "herald_dashboard.v1"

logger = logging.getLogger(__name__)


def load_metrics_files(metrics_dir: Path, n_weeks: int = 4) -> list[dict]:
    """Load metrics_{date}.json files within the rolling window."""
    cutoff = (date.today() - timedelta(weeks=n_weeks)).isoformat()
    files = sorted(metrics_dir.glob("metrics_*.json"), reverse=True)
    results = []
    for f in files:
        dt = f.stem.replace("metrics_", "")
        if dt < cutoff:
            break
        try:
            results.append(json.loads(f.read_text()))
        except Exception as e:
            logger.warning("Error reading %s: %s", f.name, e)
    return results


def compute_rolling_metrics(metrics_list: list[dict]) -> dict[str, Any]:
    """Aggregate metrics across the rolling window."""
    if not metrics_list:
        return {"n_reports": 0}

    # Aggregate informational check
    total_info_checked = 0
    total_info_surprised = 0
    for m in metrics_list:
        ipc = m.get("informational_price_check", {})
        total_info_checked += ipc.get("n_checked", 0)
        total_info_surprised += ipc.get("n_surprised", 0)

    # Aggregate severity check
    total_sev_checked = 0
    total_sev_with_move = 0
    for m in metrics_list:
        spc = m.get("severity_price_check", {})
        total_sev_checked += spc.get("n_checked", 0)
        total_sev_with_move += spc.get("n_with_move", 0)

    # Aggregate CRT
    total_crt_matched = 0
    total_crt_cat_agree = 0
    for m in metrics_list:
        crt = m.get("crt_cross_reference", {})
        n = crt.get("n_matched", 0)
        total_crt_matched += n
        total_crt_cat_agree += round(crt.get("category_agreement_rate", 0) * n)

    # Aggregate category metrics (from most recent report with ground truth)
    latest_cat = None
    for m in metrics_list:
        if m.get("category_metrics"):
            latest_cat = m["category_metrics"]
            break

    return {
        "n_reports": len(metrics_list),
        "date_range": {
            "earliest": metrics_list[-1].get("as_of_date", ""),
            "latest": metrics_list[0].get("as_of_date", ""),
        },
        "rolling_informational": {
            "n_checked": total_info_checked,
            "n_surprised": total_info_surprised,
            "false_informational_rate": round(total_info_surprised / max(total_info_checked, 1), 3),
        },
        "rolling_severity": {
            "n_checked": total_sev_checked,
            "n_with_move": total_sev_with_move,
            "reaction_rate": round(total_sev_with_move / max(total_sev_checked, 1), 3),
        },
        "rolling_crt": {
            "n_matched": total_crt_matched,
            "category_agreement_rate": round(total_crt_cat_agree / max(total_crt_matched, 1), 3),
        },
        "latest_category_metrics": latest_cat,
    }


def detect_classifier_drift(
    current_metrics: dict | None,
    baseline_metrics: dict | None,
    threshold_pct: float = 10.0,
) -> list[dict]:
    """Flag categories where precision dropped > threshold from baseline."""
    if not current_metrics or not baseline_metrics:
        return []

    flags = []
    for cat in current_metrics:
        if cat not in baseline_metrics:
            continue
        curr_p = current_metrics[cat].get("precision", 0)
        base_p = baseline_metrics[cat].get("precision", 0)
        if base_p > 0:
            delta = (curr_p - base_p) / base_p * 100
            if delta < -threshold_pct:
                flags.append(
                    {
                        "category": cat,
                        "current_precision": curr_p,
                        "baseline_precision": base_p,
                        "delta_pct": round(delta, 1),
                        "flag": "DRIFT",
                    }
                )

    return flags


def build_dashboard(metrics_dir: Path, n_weeks: int = 4, as_of_date: str = "") -> dict:
    """Build the complete dashboard report."""
    metrics_list = load_metrics_files(metrics_dir, n_weeks)
    rolling = compute_rolling_metrics(metrics_list)

    # Drift detection: compare latest vs earliest in window
    latest_cat = None
    baseline_cat = None
    for m in metrics_list:
        if m.get("category_metrics"):
            if latest_cat is None:
                latest_cat = m["category_metrics"]
            baseline_cat = m["category_metrics"]

    drift_flags = detect_classifier_drift(latest_cat, baseline_cat)

    return {
        "schema": SCHEMA,
        "as_of_date": as_of_date or date.today().isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rolling_window_weeks": n_weeks,
        "rolling_metrics": rolling,
        "drift_flags": drift_flags,
        "n_drift_alerts": len(drift_flags),
    }


def write_markdown_summary(dashboard: dict, output_path: Path) -> None:
    """Write a human-readable markdown summary."""
    lines = [
        f"# Herald Precision Dashboard -- {dashboard['as_of_date']}",
        "",
        f"Rolling window: {dashboard['rolling_window_weeks']} weeks",
        f"Reports in window: {dashboard['rolling_metrics']['n_reports']}",
        "",
    ]

    rm = dashboard["rolling_metrics"]
    if rm["n_reports"] > 0:
        ri = rm["rolling_informational"]
        lines.append("## Informational check")
        lines.append(
            f"- False informational rate: {ri['false_informational_rate']:.1%} ({ri['n_surprised']}/{ri['n_checked']})"
        )
        lines.append("")

        rs = rm["rolling_severity"]
        lines.append("## Severity reaction")
        lines.append(f"- Reaction rate: {rs['reaction_rate']:.1%} ({rs['n_with_move']}/{rs['n_checked']})")
        lines.append("")

        rc = rm["rolling_crt"]
        lines.append("## CRT agreement")
        lines.append(f"- Category agreement: {rc['category_agreement_rate']:.1%} ({rc['n_matched']} matches)")
        lines.append("")

    if dashboard["drift_flags"]:
        lines.append("## Drift alerts")
        for f in dashboard["drift_flags"]:
            lines.append(
                f"- **{f['category']}**: precision {f['baseline_precision']:.2f} -> {f['current_precision']:.2f} ({f['delta_pct']:+.1f}%)"
            )
        lines.append("")
    else:
        lines.append("## Drift alerts")
        lines.append("- None")
        lines.append("")

    output_path.write_text("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description="Herald precision dashboard")
    parser.add_argument("--metrics-dir", type=Path, default=METRICS_DIR)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--n-weeks", type=int, default=4)
    parser.add_argument("--as-of-date", default=date.today().isoformat())
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    dashboard = build_dashboard(args.metrics_dir, args.n_weeks, args.as_of_date)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / f"dashboard_{args.as_of_date}.json"
    json_path.write_text(json.dumps(dashboard, indent=2, default=str))

    md_path = args.output_dir / f"dashboard_{args.as_of_date}.md"
    write_markdown_summary(dashboard, md_path)

    rm = dashboard["rolling_metrics"]
    print(f"\nHERALD PRECISION DASHBOARD -- {args.as_of_date}")
    print(f"  Reports in window: {rm['n_reports']}")
    if rm["n_reports"] > 0:
        print(f"  False informational: {rm['rolling_informational']['false_informational_rate']:.1%}")
        print(f"  Severity reaction: {rm['rolling_severity']['reaction_rate']:.1%}")
        print(f"  CRT agreement: {rm['rolling_crt']['category_agreement_rate']:.1%}")
    print(f"  Drift alerts: {dashboard['n_drift_alerts']}")
    print(f"\n  JSON: {json_path}")
    print(f"  Markdown: {md_path}")


if __name__ == "__main__":
    main()
