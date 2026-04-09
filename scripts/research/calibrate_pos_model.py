#!/usr/bin/env python3
"""PoS model calibration against clinical outcome events.

Joins snapshot-era model predictions to actual clinical outcomes using
PIT-safe availability timestamps. Produces calibration curves, Brier
scores, and reliability tables.

Usage:
    python scripts/research/calibrate_pos_model.py
"""

from __future__ import annotations

import csv
import json
import logging
import math
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

SCHEMA = "pos_calibration.v1"

# Outcome labels that count as success/failure for calibration
SUCCESS_LABELS = {"CT_RESULTS_POSTED"}  # from our catalog — all are results-posted
# For now, we use phase as a PoS proxy: Phase 3 completion → likely positive,
# but the real binary label needs outcome text. As a first pass, use whether
# the trial was completed (not terminated) as a weak proxy.


def _sf(v: Any, default: float = float("nan")) -> float:
    if v is None or v == "":
        return default
    try:
        f = float(v)
        return f if not math.isnan(f) else default
    except (ValueError, TypeError):
        return default


def load_outcome_events(path: Path) -> List[Dict[str, Any]]:
    """Load clinical outcome events."""
    data = json.loads(path.read_text())
    return data.get("events", [])


def load_snapshot_predictions(
    snapshots_dir: Path,
) -> Dict[str, Dict[str, Dict[str, float]]]:
    """Load predictions from snapshots → {date: {ticker: {field: val}}}."""
    date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    index: Dict[str, Dict[str, Dict[str, float]]] = {}

    for d in sorted(snapshots_dir.iterdir()):
        if not d.is_dir() or not date_re.match(d.name):
            continue
        csv_path = d / "rankings.csv"
        if not csv_path.exists():
            continue
        try:
            tickers = {}
            with open(csv_path, newline="", encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    tk = (row.get("ticker") or "").upper()
                    if not tk:
                        continue
                    tickers[tk] = {
                        "composite_score": _sf(row.get("composite_score")),
                        "clinical_score": _sf(row.get("clinical_score")),
                        "clinical_score_z": _sf(row.get("clinical_score_z")),
                        "clinical_quality": _sf(row.get("clinical_quality")),
                    }
            index[d.name] = tickers
        except (OSError, csv.Error):
            continue

    return index


def find_nearest_snapshot(
    snap_dates: List[str],
    target_date: str,
) -> Optional[str]:
    """Find the latest snapshot date <= target_date."""
    candidates = [d for d in snap_dates if d <= target_date]
    return candidates[-1] if candidates else None


def build_calibration_dataset(
    events: List[Dict[str, Any]],
    predictions: Dict[str, Dict[str, Dict[str, float]]],
    catalog: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Join outcome events to model predictions."""
    snap_dates = sorted(predictions.keys())
    dataset = []

    for ev in events:
        ticker = ev.get("ticker", "").upper()
        disclosure_date = ev.get("public_disclosure_date", "")
        if not ticker or not disclosure_date:
            continue

        # Find nearest snapshot before disclosure
        snap_date = find_nearest_snapshot(snap_dates, disclosure_date)
        if not snap_date:
            continue

        # Get model prediction at that snapshot
        ticker_preds = predictions.get(snap_date, {}).get(ticker, {})
        if not ticker_preds:
            continue

        composite = ticker_preds.get("composite_score", float("nan"))
        clinical = ticker_preds.get("clinical_score", float("nan"))
        clinical_z = ticker_preds.get("clinical_score_z", float("nan"))

        if math.isnan(composite) and math.isnan(clinical):
            continue

        # Get catalog info for outcome labeling
        nct_id = ev.get("nct_id", "")
        cat_entry = catalog.get(nct_id, {})
        is_completed = cat_entry.get("lifecycle", {}).get("is_completed", False)
        is_terminated = cat_entry.get("lifecycle", {}).get("is_terminated", False)

        # Binary outcome: completed (not terminated) = success proxy
        # This is imperfect but the best we have without outcome text parsing
        if is_terminated:
            outcome = 0
        elif is_completed:
            outcome = 1
        else:
            continue  # Skip ambiguous

        dataset.append(
            {
                "ticker": ticker,
                "nct_id": nct_id,
                "disclosure_date": disclosure_date,
                "snap_date": snap_date,
                "phase": ev.get("phase", ""),
                "endpoint_class": ev.get("design_endpoint_class", ""),
                "biomarker_selected": ev.get("design_biomarker_selected", False),
                "composite_score": composite,
                "clinical_score": clinical,
                "clinical_score_z": clinical_z,
                "binary_outcome": outcome,
            }
        )

    return dataset


def compute_calibration(
    dataset: List[Dict[str, Any]],
    score_field: str,
    n_bins: int = 5,
) -> Dict[str, Any]:
    """Compute calibration metrics for a score field."""
    pairs = [(r[score_field], r["binary_outcome"]) for r in dataset if not math.isnan(r[score_field])]
    if len(pairs) < 20:
        return {"status": "insufficient", "n": len(pairs)}

    # Sort by prediction
    pairs.sort(key=lambda x: x[0])
    n = len(pairs)

    # Bin into quantiles
    bins = []
    bin_size = n // n_bins
    for i in range(n_bins):
        start = i * bin_size
        end = start + bin_size if i < n_bins - 1 else n
        bin_pairs = pairs[start:end]
        preds = [p for p, _ in bin_pairs]
        outcomes = [o for _, o in bin_pairs]
        bins.append(
            {
                "bin": i,
                "n": len(bin_pairs),
                "pred_mean": round(sum(preds) / len(preds), 6),
                "pred_min": round(min(preds), 6),
                "pred_max": round(max(preds), 6),
                "actual_rate": round(sum(outcomes) / len(outcomes), 4),
            }
        )

    # Brier score
    brier = sum((p - o) ** 2 for p, o in pairs) / n

    # Overall accuracy
    overall_rate = sum(o for _, o in pairs) / n

    # Simple calibration slope (linear regression of actual_rate on pred_mean)
    pred_means = [b["pred_mean"] for b in bins]
    actual_rates = [b["actual_rate"] for b in bins]
    if len(pred_means) >= 3:
        x_mean = sum(pred_means) / len(pred_means)
        y_mean = sum(actual_rates) / len(actual_rates)
        num = sum((x - x_mean) * (y - y_mean) for x, y in zip(pred_means, actual_rates))
        den = sum((x - x_mean) ** 2 for x in pred_means)
        slope = num / den if den > 0 else float("nan")
        intercept = y_mean - slope * x_mean
    else:
        slope = float("nan")
        intercept = float("nan")

    return {
        "status": "ok",
        "n": n,
        "brier_score": round(brier, 6),
        "overall_success_rate": round(overall_rate, 4),
        "calibration_slope": round(slope, 4) if not math.isnan(slope) else None,
        "calibration_intercept": round(intercept, 4) if not math.isnan(intercept) else None,
        "bins": bins,
    }


def main() -> int:
    events_path = PROJECT_ROOT / "data" / "clinical" / "clinical_outcome_events.json"
    catalog_path = PROJECT_ROOT / "data" / "clinical" / "clinical_history_catalog.json"
    snapshots_dir = PROJECT_ROOT / "data" / "snapshots"
    output_dir = PROJECT_ROOT / "data" / "research"
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Loading outcome events ...")
    events = load_outcome_events(events_path)
    logger.info("Loaded %d events", len(events))

    logger.info("Loading catalog ...")
    cat_data = json.loads(catalog_path.read_text())
    catalog = {r["nct_id"]: r for r in cat_data.get("records", [])}
    logger.info("Catalog: %d records", len(catalog))

    logger.info("Loading snapshot predictions ...")
    predictions = load_snapshot_predictions(snapshots_dir)
    logger.info("Loaded %d snapshot dates", len(predictions))

    logger.info("Building calibration dataset ...")
    dataset = build_calibration_dataset(events, predictions, catalog)
    logger.info("Calibration dataset: %d rows", len(dataset))

    if not dataset:
        logger.warning("No calibration data")
        return 1

    # Overall calibration
    logger.info("Computing calibration ...")
    results = {}
    for field in ["composite_score", "clinical_score"]:
        cal = compute_calibration(dataset, field)
        results[field] = cal
        if cal.get("status") == "ok":
            logger.info(
                "  %s: Brier=%.4f, slope=%s, n=%d, success_rate=%.2f",
                field,
                cal["brier_score"],
                cal.get("calibration_slope"),
                cal["n"],
                cal["overall_success_rate"],
            )

    # By phase
    phase_results = {}
    for phase in ["phase2", "phase3"]:
        subset = [r for r in dataset if r["phase"] == phase]
        if len(subset) >= 20:
            phase_results[phase] = compute_calibration(subset, "composite_score")

    # By biomarker
    bio_results = {}
    for bio_val, label in [(True, "biomarker_yes"), (False, "biomarker_no")]:
        subset = [r for r in dataset if r["biomarker_selected"] == bio_val]
        if len(subset) >= 20:
            bio_results[label] = compute_calibration(subset, "composite_score")

    # By endpoint
    endpoint_results = {}
    for ep in ["overall_survival", "objective_response_rate", "other"]:
        subset = [r for r in dataset if r["endpoint_class"] == ep]
        if len(subset) >= 20:
            endpoint_results[ep] = compute_calibration(subset, "composite_score")

    # Write report
    report = {
        "schema": SCHEMA,
        "n_outcome_events": len(events),
        "n_calibration_rows": len(dataset),
        "n_success": sum(r["binary_outcome"] for r in dataset),
        "n_failure": sum(1 - r["binary_outcome"] for r in dataset),
        "overall": results,
        "by_phase": phase_results,
        "by_biomarker": bio_results,
        "by_endpoint": endpoint_results,
    }
    (output_dir / "pos_calibration_report.json").write_text(json.dumps(report, indent=2, default=str) + "\n")

    # Markdown
    md = [
        "# PoS Model Calibration Report",
        "",
        f"**Outcome events**: {len(events)}",
        f"**Calibration rows**: {len(dataset)}",
        f"**Success rate**: {sum(r['binary_outcome'] for r in dataset)}/{len(dataset)} "
        f"({100 * sum(r['binary_outcome'] for r in dataset) / len(dataset):.1f}%)",
        "",
    ]

    for field in ["composite_score", "clinical_score"]:
        cal = results.get(field, {})
        if cal.get("status") != "ok":
            md.append(f"## {field}: insufficient data")
            continue
        md += [
            f"## {field}",
            "",
            f"- **Brier score**: {cal['brier_score']:.4f}",
            f"- **Calibration slope**: {cal.get('calibration_slope', '—')}",
            f"- **Calibration intercept**: {cal.get('calibration_intercept', '—')}",
            f"- **N**: {cal['n']}",
            "",
            "| Bin | N | Pred Mean | Pred Range | Actual Rate |",
            "|-----|---|-----------|-----------|-------------|",
        ]
        for b in cal.get("bins", []):
            md.append(
                f"| {b['bin']} | {b['n']} | {b['pred_mean']:.4f} | [{b['pred_min']:.3f}, {b['pred_max']:.3f}] | {b['actual_rate']:.2f} |"
            )
        md.append("")

    if phase_results:
        md += ["## By Phase", ""]
        for phase, cal in sorted(phase_results.items()):
            if cal.get("status") == "ok":
                md.append(
                    f"- **{phase}**: Brier={cal['brier_score']:.4f}, slope={cal.get('calibration_slope')}, n={cal['n']}, success={cal['overall_success_rate']:.2f}"
                )
        md.append("")

    if bio_results:
        md += ["## By Biomarker Selection", ""]
        for label, cal in sorted(bio_results.items()):
            if cal.get("status") == "ok":
                md.append(
                    f"- **{label}**: Brier={cal['brier_score']:.4f}, success={cal['overall_success_rate']:.2f}, n={cal['n']}"
                )
        md.append("")

    md.append("")
    (output_dir / "pos_calibration_report.md").write_text("\n".join(md))
    logger.info("Report → %s", output_dir / "pos_calibration_report.md")

    return 0


if __name__ == "__main__":
    sys.exit(main())
