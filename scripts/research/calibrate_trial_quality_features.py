#!/usr/bin/env python3
"""Calibrate trial quality features against p-value outcomes.

Builds a clinical-only PoS prediction surface from trial design features
and tests it against the 1,587 high-confidence CT.gov outcome labels.

Usage:
    python scripts/research/calibrate_trial_quality_features.py
"""

from __future__ import annotations

import json
import logging
import math
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

SCHEMA = "trial_quality_calibration.v1"


def load_labels(path: Path) -> Dict[str, Dict[str, Any]]:
    """Load high-confidence outcome labels → {nct_id: label_record}."""
    data = json.loads(path.read_text())
    return {
        r["nct_id"]: r
        for r in data.get("labels", [])
        if r.get("confidence") == "high" and r.get("binary_outcome") is not None
    }


def load_catalog(path: Path) -> Dict[str, Dict[str, Any]]:
    """Load clinical history catalog → {nct_id: catalog_record}."""
    data = json.loads(path.read_text())
    return {r["nct_id"]: r for r in data.get("records", [])}


def build_feature_matrix(
    labels: Dict[str, Dict],
    catalog: Dict[str, Dict],
) -> List[Dict[str, Any]]:
    """Build feature matrix by joining labels to catalog."""
    rows = []
    for nct_id, label in labels.items():
        cat = catalog.get(nct_id)
        if not cat:
            continue

        design = cat.get("design", {})
        phase = cat.get("phase", "")

        # Phase encoding (ordinal)
        phase_map = {"phase1": 1, "phase1_2": 1.5, "phase2": 2, "phase2_3": 2.5, "phase3": 3, "phase4": 4}
        phase_num = phase_map.get(phase)

        # Endpoint class encoding
        ep = design.get("endpoint_class", "other")
        ep_hard = 1 if ep in ("overall_survival", "progression_free_survival") else 0

        # Biomarker
        biomarker = 1 if design.get("biomarker_selected") else 0

        # Enrollment bucket encoding
        eb = design.get("enrollment_bucket", "unknown")
        enroll_map = {"small": 1, "medium": 2, "large": 3, "very_large": 4}
        enroll_ord = enroll_map.get(eb)

        # Enrollment count
        enroll_n = design.get("enrollment")

        rows.append(
            {
                "nct_id": nct_id,
                "ticker": label.get("ticker", cat.get("ticker", "")),
                "binary_outcome": label["binary_outcome"],
                "raw_pvalue": label.get("raw_pvalue"),
                "phase": phase,
                "phase_num": phase_num,
                "endpoint_class": ep,
                "endpoint_hard": ep_hard,
                "biomarker_selected": biomarker,
                "enrollment_bucket": eb,
                "enrollment_ordinal": enroll_ord,
                "enrollment_count": enroll_n,
                "status": cat.get("status", ""),
            }
        )

    return rows


def compute_univariate_odds(
    rows: List[Dict],
    feature: str,
    min_group: int = 20,
) -> Dict[str, Any]:
    """Compute univariate success rate by feature value."""
    groups: Dict[Any, List[int]] = {}
    for r in rows:
        val = r.get(feature)
        if val is None:
            continue
        groups.setdefault(val, []).append(r["binary_outcome"])

    results = {}
    for val, outcomes in sorted(groups.items(), key=lambda x: str(x[0])):
        n = len(outcomes)
        if n < min_group:
            continue
        rate = sum(outcomes) / n
        results[str(val)] = {"n": n, "success_rate": round(rate, 4), "n_success": sum(outcomes)}

    return results


def compute_logistic_coefficients(
    rows: List[Dict],
    features: List[str],
) -> Dict[str, Any]:
    """Simple logistic regression via iteratively reweighted least squares.

    Returns coefficients, odds ratios, and AUC approximation.
    Uses a basic Newton-Raphson implementation (no scipy dependency).
    """
    # Build X matrix (with intercept)
    valid_rows = []
    for r in rows:
        vals = [r.get(f) for f in features]
        if all(v is not None and not (isinstance(v, float) and math.isnan(v)) for v in vals):
            valid_rows.append(r)

    if len(valid_rows) < 50:
        return {"status": "insufficient", "n": len(valid_rows)}

    n = len(valid_rows)
    k = len(features) + 1  # +1 for intercept

    X = [[1.0] + [float(r[f]) for f in features] for r in valid_rows]
    y = [float(r["binary_outcome"]) for r in valid_rows]

    # Initialize coefficients
    beta = [0.0] * k

    def sigmoid(z):
        if z > 500:
            return 1.0
        if z < -500:
            return 0.0
        return 1.0 / (1.0 + math.exp(-z))

    # Newton-Raphson iterations
    for iteration in range(50):
        # Compute predictions
        p = [sigmoid(sum(X[i][j] * beta[j] for j in range(k))) for i in range(n)]

        # Gradient
        grad = [sum((p[i] - y[i]) * X[i][j] for i in range(n)) for j in range(k)]

        # Hessian diagonal (approximate)
        H_diag = [sum(p[i] * (1 - p[i]) * X[i][j] ** 2 for i in range(n)) for j in range(k)]

        # Update
        max_delta = 0
        for j in range(k):
            if H_diag[j] > 1e-10:
                delta = grad[j] / H_diag[j]
                beta[j] -= delta
                max_delta = max(max_delta, abs(delta))

        if max_delta < 1e-6:
            break

    # Final predictions
    p_final = [sigmoid(sum(X[i][j] * beta[j] for j in range(k))) for i in range(n)]

    # Log-likelihood
    ll = sum(
        y[i] * math.log(max(p_final[i], 1e-15)) + (1 - y[i]) * math.log(max(1 - p_final[i], 1e-15)) for i in range(n)
    )

    # AUC approximation (Mann-Whitney U statistic)
    pos = [(p_final[i], y[i]) for i in range(n) if y[i] == 1]
    neg = [(p_final[i], y[i]) for i in range(n) if y[i] == 0]
    if pos and neg:
        concordant = sum(1 for pp, _ in pos for pn, _ in neg if pp > pn)
        tied = sum(1 for pp, _ in pos for pn, _ in neg if pp == pn)
        auc = (concordant + 0.5 * tied) / (len(pos) * len(neg))
    else:
        auc = 0.5

    # Build coefficient table
    coef_table = {}
    feature_names = ["intercept"] + features
    for j, name in enumerate(feature_names):
        coef_table[name] = {
            "coefficient": round(beta[j], 4),
            "odds_ratio": round(math.exp(beta[j]), 4) if abs(beta[j]) < 20 else None,
        }

    return {
        "status": "ok",
        "n": n,
        "n_success": sum(y),
        "n_failure": n - sum(y),
        "auc": round(auc, 4),
        "log_likelihood": round(ll, 2),
        "iterations": iteration + 1,
        "coefficients": coef_table,
    }


def main() -> int:
    labels_path = PROJECT_ROOT / "data" / "clinical" / "clinical_outcome_labels_v2.json"
    catalog_path = PROJECT_ROOT / "data" / "clinical" / "clinical_history_catalog.json"

    logger.info("Loading labels ...")
    labels = load_labels(labels_path)
    logger.info("High-confidence labels: %d", len(labels))

    logger.info("Loading catalog ...")
    catalog = load_catalog(catalog_path)
    logger.info("Catalog: %d records", len(catalog))

    logger.info("Building feature matrix ...")
    matrix = build_feature_matrix(labels, catalog)
    logger.info("Feature matrix: %d rows", len(matrix))

    if not matrix:
        logger.warning("Empty feature matrix")
        return 1

    # Feature coverage
    coverage = {}
    for feat in ["phase_num", "endpoint_hard", "biomarker_selected", "enrollment_ordinal", "enrollment_count"]:
        n_valid = sum(1 for r in matrix if r.get(feat) is not None)
        coverage[feat] = {"n_valid": n_valid, "n_total": len(matrix), "pct": round(100 * n_valid / len(matrix), 1)}

    logger.info("Feature coverage:")
    for f, c in coverage.items():
        logger.info("  %s: %d/%d (%.1f%%)", f, c["n_valid"], c["n_total"], c["pct"])

    # Univariate odds
    logger.info("Computing univariate odds ...")
    univariate = {}
    for feat in ["phase", "endpoint_class", "biomarker_selected", "enrollment_bucket"]:
        univariate[feat] = compute_univariate_odds(matrix, feat)
        for val, stats in univariate[feat].items():
            logger.info("  %s=%s: rate=%.1f%% (n=%d)", feat, val, stats["success_rate"] * 100, stats["n"])

    # Logistic regression
    logger.info("Fitting logistic regression ...")
    features_full = ["phase_num", "endpoint_hard", "biomarker_selected"]
    logistic = compute_logistic_coefficients(matrix, features_full)

    if logistic.get("status") == "ok":
        logger.info("  AUC: %.4f (n=%d)", logistic["auc"], logistic["n"])
        for name, coef in logistic["coefficients"].items():
            or_val = coef.get("odds_ratio")
        or_str = f"{or_val:.4f}" if or_val is not None else "overflow"
        logger.info("  %s: coef=%.4f, OR=%s", name, coef["coefficient"], or_str)
    else:
        logger.info("  Logistic: %s (n=%d)", logistic.get("status"), logistic.get("n", 0))

    # Write outputs
    output_dir = PROJECT_ROOT / "data" / "research"
    output_dir.mkdir(parents=True, exist_ok=True)

    report = {
        "schema": SCHEMA,
        "built_as_of": date.today().isoformat(),
        "n_labels": len(labels),
        "n_matrix": len(matrix),
        "feature_coverage": coverage,
        "univariate": univariate,
        "logistic": logistic,
    }
    (output_dir / "trial_quality_calibration.json").write_text(json.dumps(report, indent=2, default=str) + "\n")

    # Markdown
    md = [
        "# Trial Quality Feature Calibration",
        "",
        f"**Labels**: {len(labels)} high-confidence",
        f"**Matrix rows**: {len(matrix)}",
        "",
        "## Feature Coverage",
        "",
        "| Feature | Valid | Total | Coverage |",
        "|---------|-------|-------|----------|",
    ]
    for f, c in coverage.items():
        md.append(f"| {f} | {c['n_valid']} | {c['n_total']} | {c['pct']}% |")

    md += ["", "## Univariate Success Rates", ""]
    for feat, vals in univariate.items():
        md.append(f"### {feat}")
        md.append("")
        md.append("| Value | N | Success Rate |")
        md.append("|-------|---|-------------|")
        for val, stats in vals.items():
            md.append(f"| {val} | {stats['n']} | {stats['success_rate']:.1%} |")
        md.append("")

    if logistic.get("status") == "ok":
        md += [
            "## Logistic Regression",
            "",
            f"**AUC**: {logistic['auc']}",
            f"**N**: {logistic['n']} (success={logistic['n_success']}, failure={logistic['n_failure']})",
            "",
            "| Feature | Coefficient | Odds Ratio |",
            "|---------|------------|-----------|",
        ]
        for name, coef in logistic["coefficients"].items():
            or_str = f"{coef['odds_ratio']:.4f}" if coef.get("odds_ratio") else "—"
            md.append(f"| {name} | {coef['coefficient']:.4f} | {or_str} |")

    md.append("")
    (output_dir / "trial_quality_calibration.md").write_text("\n".join(md))
    logger.info("Report → %s", output_dir / "trial_quality_calibration.md")

    # Coverage CSV
    import csv

    cov_path = output_dir / "trial_quality_feature_coverage.csv"
    with open(cov_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["feature", "n_valid", "n_total", "pct"])
        w.writeheader()
        for feat, c in coverage.items():
            w.writerow({"feature": feat, **c})

    return 0


if __name__ == "__main__":
    sys.exit(main())
