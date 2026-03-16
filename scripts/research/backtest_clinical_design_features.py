#!/usr/bin/env python3
"""Backtest clinical trial design features against binary outcomes.

Three-part analysis:
  1. Design-feature discrimination (phase, endpoint, enrollment)
  2. Survivorship sensitivity (best/worst/plausible scenarios)
  3. Forward utility of v2 phase prior vs flat/reference baselines

Usage:
    python scripts/research/backtest_clinical_design_features.py \
        [--output-dir data/research] \
        [--n-folds 10] [--n-bootstrap 200] [--seed 42] \
        [--parts 1,2,3] \
        [--v2-priors production_data/clinical_pos_priors_v2.json]
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import random
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.research.build_clinical_pos_priors import REFERENCE_PRIORS
from scripts.research.calibrate_trial_quality_features import build_feature_matrix, load_catalog, load_labels

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

SCHEMA = "clinical_design_backtest.v1"


# ---------------------------------------------------------------------------
# Core math helpers
# ---------------------------------------------------------------------------


def sigmoid(z: float) -> float:
    if z > 500:
        return 1.0
    if z < -500:
        return 0.0
    return 1.0 / (1.0 + math.exp(-z))


def _solve_linear(A: List[List[float]], b: List[float]) -> Optional[List[float]]:
    """Solve Ax = b via Gaussian elimination with partial pivoting."""
    k = len(b)
    # Augmented matrix
    M = [row[:] + [b[i]] for i, row in enumerate(A)]

    for col in range(k):
        # Partial pivot
        max_row = col
        for row in range(col + 1, k):
            if abs(M[row][col]) > abs(M[max_row][col]):
                max_row = row
        M[col], M[max_row] = M[max_row], M[col]

        if abs(M[col][col]) < 1e-12:
            return None

        for row in range(col + 1, k):
            factor = M[row][col] / M[col][col]
            for j in range(col, k + 1):
                M[row][j] -= factor * M[col][j]

    # Back-substitution
    x = [0.0] * k
    for row in range(k - 1, -1, -1):
        x[row] = M[row][k]
        for j in range(row + 1, k):
            x[row] -= M[row][j] * x[j]
        x[row] /= M[row][row]

    return x


def fit_logistic(
    X: List[List[float]],
    y: List[float],
    max_iter: int = 50,
    tol: float = 1e-6,
) -> Tuple[List[float], List[float]]:
    """Newton-Raphson logistic regression with full Hessian.

    Returns (beta, var_diag) where var_diag are approximate variances
    for each coefficient (diagonal of inverse Hessian).
    """
    n = len(y)
    k = len(X[0])
    beta = [0.0] * k

    for _ in range(max_iter):
        p = [sigmoid(sum(X[i][j] * beta[j] for j in range(k))) for i in range(n)]
        grad = [sum((p[i] - y[i]) * X[i][j] for i in range(n)) for j in range(k)]

        # Full Hessian: H[a][b] = sum_i p_i(1-p_i) * X[i][a] * X[i][b]
        H = [[0.0] * k for _ in range(k)]
        for i in range(n):
            w = p[i] * (1 - p[i])
            for a in range(k):
                for b in range(a, k):
                    val = w * X[i][a] * X[i][b]
                    H[a][b] += val
                    if a != b:
                        H[b][a] += val

        delta = _solve_linear(H, grad)
        if delta is None:
            break

        max_delta = 0.0
        for j in range(k):
            beta[j] -= delta[j]
            max_delta = max(max_delta, abs(delta[j]))

        if max_delta < tol:
            break

    # Variance estimates from diagonal of inverse Hessian
    p_final = [sigmoid(sum(X[i][j] * beta[j] for j in range(k))) for i in range(n)]
    H_final = [[0.0] * k for _ in range(k)]
    for i in range(n):
        w = p_final[i] * (1 - p_final[i])
        for a in range(k):
            for b in range(a, k):
                val = w * X[i][a] * X[i][b]
                H_final[a][b] += val
                if a != b:
                    H_final[b][a] += val

    # Get diagonal of H_inv by solving H * e_j = e_j for each j
    var_diag = []
    for j in range(k):
        e = [0.0] * k
        e[j] = 1.0
        sol = _solve_linear(H_final, e)
        var_diag.append(sol[j] if sol is not None else float("inf"))

    return beta, var_diag


def predict_logistic(X: List[List[float]], beta: List[float]) -> List[float]:
    return [sigmoid(sum(X[i][j] * beta[j] for j in range(len(beta)))) for i in range(len(X))]


def compute_auc(y_true: List[float], y_score: List[float]) -> float:
    """Mann-Whitney U AUC."""
    pos = [s for s, yt in zip(y_score, y_true) if yt == 1]
    neg = [s for s, yt in zip(y_score, y_true) if yt == 0]
    if not pos or not neg:
        return 0.5
    concordant = sum(1 for pp in pos for pn in neg if pp > pn)
    tied = sum(1 for pp in pos for pn in neg if pp == pn)
    return (concordant + 0.5 * tied) / (len(pos) * len(neg))


def bootstrap_auc_ci(
    y_true: List[float],
    y_score: List[float],
    n_bootstrap: int = 200,
    seed: int = 42,
) -> Tuple[float, float, float]:
    """Bootstrap percentile CI for AUC. Returns (auc, ci_lo, ci_hi)."""
    rng = random.Random(seed)
    n = len(y_true)
    aucs = []
    for _ in range(n_bootstrap):
        idx = [rng.randint(0, n - 1) for _ in range(n)]
        yt = [y_true[i] for i in idx]
        ys = [y_score[i] for i in idx]
        if len(set(yt)) < 2:
            continue
        aucs.append(compute_auc(yt, ys))
    if not aucs:
        return 0.5, 0.5, 0.5
    aucs.sort()
    lo = aucs[max(0, int(len(aucs) * 0.025))]
    hi = aucs[min(len(aucs) - 1, int(len(aucs) * 0.975))]
    return compute_auc(y_true, y_score), lo, hi


def stratified_kfold(y: List[float], n_folds: int, seed: int = 42) -> List[Tuple[List[int], List[int]]]:
    """Deterministic stratified k-fold split."""
    rng = random.Random(seed)
    pos_idx = [i for i, v in enumerate(y) if v == 1]
    neg_idx = [i for i, v in enumerate(y) if v == 0]
    rng.shuffle(pos_idx)
    rng.shuffle(neg_idx)

    folds: List[List[int]] = [[] for _ in range(n_folds)]
    for i, idx in enumerate(pos_idx):
        folds[i % n_folds].append(idx)
    for i, idx in enumerate(neg_idx):
        folds[i % n_folds].append(idx)

    splits = []
    for f in range(n_folds):
        test = folds[f]
        train = [idx for g in range(n_folds) if g != f for idx in folds[g]]
        splits.append((train, test))
    return splits


def compute_brier(y_true: List[float], y_pred: List[float]) -> float:
    n = len(y_true)
    if n == 0:
        return 0.0
    return sum((y_pred[i] - y_true[i]) ** 2 for i in range(n)) / n


def compute_calibration_slope(y_true: List[float], y_pred: List[float]) -> Optional[float]:
    """OLS regression of logit(outcome) ~ logit(pred).

    Uses binary outcome directly: slope of logit(pred) predicting outcome
    via logistic regression (single-variable).
    """
    # Filter out constant predictions
    unique_preds = set(round(p, 8) for p in y_pred)
    if len(unique_preds) < 2:
        return None

    # Transform predictions to logit scale
    logit_preds = []
    valid_y = []
    for i in range(len(y_true)):
        p = max(min(y_pred[i], 1 - 1e-10), 1e-10)
        logit_preds.append(math.log(p / (1 - p)))
        valid_y.append(y_true[i])

    if not logit_preds:
        return None

    # Fit logistic: outcome ~ logit(pred) → slope should be ~1 for perfect calibration
    X = [[1.0, lp] for lp in logit_preds]
    beta, _ = fit_logistic(X, valid_y)
    return beta[1]  # slope on logit(pred)


def compute_reliability_bins(y_true: List[float], y_pred: List[float], n_bins: int = 10) -> List[Dict[str, Any]]:
    """Reliability diagram bins."""
    pairs = sorted(zip(y_pred, y_true), key=lambda x: x[0])
    bins = []
    chunk = max(1, len(pairs) // n_bins)
    for i in range(0, len(pairs), chunk):
        group = pairs[i : i + chunk]
        if not group:
            continue
        preds = [g[0] for g in group]
        outcomes = [g[1] for g in group]
        bins.append(
            {
                "bin_lo": round(min(preds), 4),
                "bin_hi": round(max(preds), 4),
                "mean_pred": round(sum(preds) / len(preds), 4),
                "mean_outcome": round(sum(outcomes) / len(outcomes), 4),
                "n": len(group),
            }
        )
    return bins


# ---------------------------------------------------------------------------
# Part 1: Design-Feature Discrimination
# ---------------------------------------------------------------------------

MODEL_SPECS = {
    "phase_only": ["phase_num"],
    "phase_endpoint": ["phase_num", "endpoint_hard"],
    "multi_feature": ["phase_num", "endpoint_hard", "enrollment_ordinal"],
}


def _prepare_Xy(rows: List[Dict], features: List[str]) -> Tuple[List[List[float]], List[float], List[Dict]]:
    """Filter rows with all features present and build X (with intercept), y."""
    valid = []
    for r in rows:
        vals = [r.get(f) for f in features]
        if all(v is not None and not (isinstance(v, float) and math.isnan(v)) for v in vals):
            valid.append(r)
    X = [[1.0] + [float(r[f]) for f in features] for r in valid]
    y = [float(r["binary_outcome"]) for r in valid]
    return X, y, valid


def run_part1(
    rows: List[Dict],
    n_folds: int = 10,
    n_bootstrap: int = 200,
    seed: int = 42,
) -> Dict[str, Any]:
    """Design-feature discrimination analysis."""
    results = {}

    for spec_name, features in MODEL_SPECS.items():
        X, y, valid = _prepare_Xy(rows, features)
        n = len(y)
        if n < 50:
            results[spec_name] = {"status": "insufficient", "n": n}
            continue

        # Full-sample fit for odds ratios
        beta, var_diag = fit_logistic(X, y)
        p_full = predict_logistic(X, beta)
        auc_full, ci_lo, ci_hi = bootstrap_auc_ci(y, p_full, n_bootstrap, seed)

        # Odds ratios with SE
        coefs = {}
        names = ["intercept"] + features
        for j, name in enumerate(names):
            se = math.sqrt(var_diag[j]) if var_diag[j] != float("inf") else None
            or_val = math.exp(beta[j]) if abs(beta[j]) < 20 else None
            coefs[name] = {
                "coefficient": round(beta[j], 4),
                "se": round(se, 4) if se is not None else None,
                "odds_ratio": round(or_val, 4) if or_val is not None else None,
            }

        # K-fold CV
        splits = stratified_kfold(y, n_folds, seed)
        cv_aucs = []
        for train_idx, test_idx in splits:
            X_train = [X[i] for i in train_idx]
            y_train = [y[i] for i in train_idx]
            X_test = [X[i] for i in test_idx]
            y_test = [y[i] for i in test_idx]

            if len(set(y_test)) < 2 or len(set(y_train)) < 2:
                continue

            beta_fold, _ = fit_logistic(X_train, y_train)
            p_test = predict_logistic(X_test, beta_fold)
            cv_aucs.append(compute_auc(y_test, p_test))

        mean_cv_auc = sum(cv_aucs) / len(cv_aucs) if cv_aucs else 0.5
        std_cv_auc = math.sqrt(sum((a - mean_cv_auc) ** 2 for a in cv_aucs) / len(cv_aucs)) if len(cv_aucs) > 1 else 0.0

        results[spec_name] = {
            "status": "ok",
            "n": n,
            "n_success": int(sum(y)),
            "features": features,
            "auc": round(auc_full, 4),
            "auc_ci_lo": round(ci_lo, 4),
            "auc_ci_hi": round(ci_hi, 4),
            "cv_auc_mean": round(mean_cv_auc, 4),
            "cv_auc_std": round(std_cv_auc, 4),
            "cv_n_folds": len(cv_aucs),
            "coefficients": coefs,
        }

    # Incremental AUC lifts
    lifts = {}
    if results.get("phase_only", {}).get("auc") and results.get("phase_endpoint", {}).get("auc"):
        lifts["endpoint_over_phase"] = round(results["phase_endpoint"]["auc"] - results["phase_only"]["auc"], 4)
    if results.get("phase_endpoint", {}).get("auc") and results.get("multi_feature", {}).get("auc"):
        lifts["enrollment_over_phase_endpoint"] = round(
            results["multi_feature"]["auc"] - results["phase_endpoint"]["auc"], 4
        )
    if results.get("phase_only", {}).get("auc") and results.get("multi_feature", {}).get("auc"):
        lifts["multi_over_phase"] = round(results["multi_feature"]["auc"] - results["phase_only"]["auc"], 4)

    # Biomarker informational
    bio_rows = [r for r in rows if r.get("biomarker_selected") is not None and r.get("phase_num") is not None]
    bio_info = {"n_biomarker_yes": 0, "n_biomarker_no": 0, "rate_yes": None, "rate_no": None}
    yes = [r["binary_outcome"] for r in bio_rows if r["biomarker_selected"] == 1]
    no = [r["binary_outcome"] for r in bio_rows if r["biomarker_selected"] == 0]
    bio_info["n_biomarker_yes"] = len(yes)
    bio_info["n_biomarker_no"] = len(no)
    if yes:
        bio_info["rate_yes"] = round(sum(yes) / len(yes), 4)
    if no:
        bio_info["rate_no"] = round(sum(no) / len(no), 4)

    return {
        "models": results,
        "incremental_auc_lifts": lifts,
        "biomarker_informational": bio_info,
    }


# ---------------------------------------------------------------------------
# Part 2: Survivorship Sensitivity
# ---------------------------------------------------------------------------

ALLOWED_PHASES = {"phase2", "phase3", "phase4"}


def build_survivorship_scenarios(
    labels: Dict[str, Dict],
    catalog: Dict[str, Dict],
    seed: int = 42,
) -> Dict[str, Any]:
    """Build best/worst/plausible survivorship scenarios."""
    rng = random.Random(seed)

    # Best-case: labeled set only (phases 2/3/4)
    best = []
    for nct_id, label in labels.items():
        cat = catalog.get(nct_id, {})
        phase = cat.get("phase", "")
        if phase not in ALLOWED_PHASES:
            continue
        best.append({"nct_id": nct_id, "phase": phase, "binary_outcome": label["binary_outcome"]})

    # Build unlabeled pool from catalog (phases 2/3/4, not in labels)
    unlabeled = []
    for nct_id, cat in catalog.items():
        phase = cat.get("phase", "")
        if phase not in ALLOWED_PHASES:
            continue
        if nct_id in labels:
            continue
        lc = cat.get("lifecycle", {})
        unlabeled.append(
            {
                "nct_id": nct_id,
                "phase": phase,
                "is_terminated": lc.get("is_terminated", False),
                "is_completed": lc.get("is_completed", False),
                "has_posted_results": lc.get("has_posted_results", False),
                "status": cat.get("status", ""),
            }
        )

    # Classify unlabeled
    terminated = [r for r in unlabeled if r["is_terminated"] or r["status"] in ("TERMINATED", "WITHDRAWN")]
    completed_no_results = [
        r
        for r in unlabeled
        if r["is_completed"]
        and not r["has_posted_results"]
        and not r["is_terminated"]
        and r["status"] not in ("TERMINATED", "WITHDRAWN")
    ]

    # Worst-case: terminated→failure, completed-no-results→failure
    worst = list(best)
    for r in terminated:
        worst.append({"nct_id": r["nct_id"], "phase": r["phase"], "binary_outcome": 0})
    for r in completed_no_results:
        worst.append({"nct_id": r["nct_id"], "phase": r["phase"], "binary_outcome": 0})

    # Plausible-case: terminated→failure, completed-no-results→50/50 coin flip
    plausible = list(best)
    for r in terminated:
        plausible.append({"nct_id": r["nct_id"], "phase": r["phase"], "binary_outcome": 0})
    for r in completed_no_results:
        outcome = 1 if rng.random() < 0.5 else 0
        plausible.append({"nct_id": r["nct_id"], "phase": r["phase"], "binary_outcome": outcome})

    scenarios = {}
    for name, rows in [("best_case", best), ("worst_case", worst), ("plausible_case", plausible)]:
        by_phase: Dict[str, List[int]] = {}
        for r in rows:
            by_phase.setdefault(r["phase"], []).append(r["binary_outcome"])

        phase_rates = {}
        total_n = 0
        total_success = 0
        for phase in sorted(by_phase):
            outcomes = by_phase[phase]
            n = len(outcomes)
            s = sum(outcomes)
            total_n += n
            total_success += s
            phase_rates[phase] = {
                "n": n,
                "success_rate": round(s / n, 4) if n else 0,
                "n_success": s,
            }

        scenarios[name] = {
            "n": total_n,
            "n_success": total_success,
            "global_rate": round(total_success / total_n, 4) if total_n else 0,
            "by_phase": phase_rates,
        }

    # Metadata
    meta = {
        "n_labeled": len(best),
        "n_terminated_added": len(terminated),
        "n_completed_no_results_added": len(completed_no_results),
    }

    return {"scenarios": scenarios, "metadata": meta}


def run_part2(
    labels: Dict[str, Dict],
    catalog: Dict[str, Dict],
    rows: List[Dict],
    seed: int = 42,
) -> Dict[str, Any]:
    """Survivorship sensitivity analysis."""
    surv = build_survivorship_scenarios(labels, catalog, seed)

    # Re-fit phase_only logistic for best-case scenario to get AUC
    scenario_aucs = {}

    for name, sc in surv["scenarios"].items():
        if name == "best_case":
            # Use actual rows filtered to allowed phases
            filtered = [r for r in rows if r.get("phase") in ALLOWED_PHASES and r.get("phase_num") is not None]
            if len(filtered) >= 50:
                Xf = [[1.0, float(r["phase_num"])] for r in filtered]
                yf = [float(r["binary_outcome"]) for r in filtered]
                beta, _ = fit_logistic(Xf, yf)
                preds = predict_logistic(Xf, beta)
                scenario_aucs[name] = round(compute_auc(yf, preds), 4)
        # For worst/plausible we report phase rates only (no individual-level AUC)

    # Deltas vs best-case
    best_rate = surv["scenarios"]["best_case"]["global_rate"]
    deltas = {}
    for name in ("worst_case", "plausible_case"):
        rate = surv["scenarios"][name]["global_rate"]
        deltas[name] = round(rate - best_rate, 4)

    surv["scenario_aucs"] = scenario_aucs
    surv["rate_deltas_vs_best"] = deltas
    return surv


# ---------------------------------------------------------------------------
# Part 3: Forward Utility of V2 Prior
# ---------------------------------------------------------------------------


def run_part3(
    rows: List[Dict],
    v2_priors_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Compare v2 prior calibration vs flat and reference baselines."""
    # Filter to rows with known phase
    valid = [r for r in rows if r.get("phase") and r.get("binary_outcome") is not None]
    if not valid:
        return {"status": "no_valid_rows"}

    y_true = [float(r["binary_outcome"]) for r in valid]
    global_rate = sum(y_true) / len(y_true)

    # Baseline 1: Flat prior (global rate)
    flat_preds = [global_rate] * len(valid)

    # Baseline 2: Wong et al. reference
    ref_preds = [REFERENCE_PRIORS.get(r["phase"], global_rate) for r in valid]

    # Baseline 3: V2 empirical priors
    v2_priors = None
    if v2_priors_path and v2_priors_path.exists():
        v2_priors = json.loads(v2_priors_path.read_text())

    if v2_priors:
        v2_preds = []
        for r in valid:
            phase = r["phase"]
            phase_data = v2_priors.get("by_phase", {}).get(phase)
            if phase_data:
                base = phase_data.get("shrunk_rate", global_rate)
                # Apply endpoint modifier if available
                ep = r.get("endpoint_class", "other")
                ep_mod = v2_priors.get("endpoint_modifiers", {}).get(ep, {})
                delta = ep_mod.get("shrunk_delta", 0)
                pred = max(0.01, min(0.99, base + delta))
            else:
                pred = global_rate
            v2_preds.append(pred)
    else:
        v2_preds = [global_rate] * len(valid)

    baselines = {}
    for name, preds in [("flat_prior", flat_preds), ("wong_reference", ref_preds), ("v2_empirical", v2_preds)]:
        brier = compute_brier(y_true, preds)
        auc = compute_auc(y_true, preds)
        slope = compute_calibration_slope(y_true, preds)
        bins = compute_reliability_bins(y_true, preds)

        baselines[name] = {
            "brier_score": round(brier, 6),
            "auc": round(auc, 4),
            "calibration_slope": round(slope, 4) if slope is not None else None,
            "reliability_bins": bins,
            "n": len(valid),
        }

    # Relative improvements
    flat_brier = baselines["flat_prior"]["brier_score"]
    improvements = {}
    for name in ("wong_reference", "v2_empirical"):
        b = baselines[name]["brier_score"]
        improvements[name + "_vs_flat"] = {
            "brier_reduction": round(flat_brier - b, 6),
            "pct_reduction": round(100 * (flat_brier - b) / flat_brier, 2) if flat_brier > 0 else 0,
        }

    return {
        "baselines": baselines,
        "improvements": improvements,
        "global_rate": round(global_rate, 4),
        "n": len(valid),
    }


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def generate_markdown(part1: Dict, part2: Dict, part3: Dict) -> str:
    lines = [
        "# Clinical Design-Feature Backtest",
        "",
        f"**Date**: {date.today().isoformat()}",
        f"**Schema**: {SCHEMA}",
        "",
    ]

    # Part 1
    lines += ["## Part 1: Design-Feature Discrimination", ""]
    if part1:
        models = part1.get("models", {})
        lines += [
            "| Model | N | AUC | AUC CI | CV AUC (mean +/- std) |",
            "|-------|---|-----|--------|----------------------|",
        ]
        for name in ("phase_only", "phase_endpoint", "multi_feature"):
            m = models.get(name, {})
            if m.get("status") != "ok":
                continue
            ci = f"[{m['auc_ci_lo']:.3f}, {m['auc_ci_hi']:.3f}]"
            cv = f"{m['cv_auc_mean']:.3f} +/- {m['cv_auc_std']:.3f}"
            lines.append(f"| {name} | {m['n']} | {m['auc']:.4f} | {ci} | {cv} |")
        lines.append("")

        lifts = part1.get("incremental_auc_lifts", {})
        if lifts:
            lines += ["### Incremental AUC Lifts", ""]
            for k, v in lifts.items():
                lines.append(f"- **{k}**: {v:+.4f}")
            lines.append("")

        # Coefficients for multi_feature
        mf = models.get("multi_feature", {})
        if mf.get("coefficients"):
            lines += [
                "### Multi-Feature Coefficients",
                "",
                "| Feature | Coef | SE | OR |",
                "|---------|------|-----|------|",
            ]
            for feat, c in mf["coefficients"].items():
                se_str = f"{c['se']:.4f}" if c.get("se") is not None else "—"
                or_str = f"{c['odds_ratio']:.4f}" if c.get("odds_ratio") is not None else "—"
                lines.append(f"| {feat} | {c['coefficient']:.4f} | {se_str} | {or_str} |")
            lines.append("")

        bio = part1.get("biomarker_informational", {})
        if bio.get("n_biomarker_yes"):
            lines += [
                "### Biomarker (Informational)",
                f"- Selected: n={bio['n_biomarker_yes']}, rate={bio['rate_yes']:.1%}" if bio.get("rate_yes") else "",
                f"- Not selected: n={bio['n_biomarker_no']}, rate={bio['rate_no']:.1%}" if bio.get("rate_no") else "",
                "",
            ]

    # Part 2
    lines += ["## Part 2: Survivorship Sensitivity", ""]
    if part2:
        meta = part2.get("metadata", {})
        lines += [
            f"- Labeled (phases 2/3/4): {meta.get('n_labeled', '?')}",
            f"- Terminated/withdrawn added: {meta.get('n_terminated_added', '?')}",
            f"- Completed-no-results added: {meta.get('n_completed_no_results_added', '?')}",
            "",
        ]
        scenarios = part2.get("scenarios", {})
        lines += [
            "| Scenario | N | Global Rate | Phase 2 | Phase 3 | Phase 4 |",
            "|----------|---|------------|---------|---------|---------|",
        ]
        for name in ("best_case", "worst_case", "plausible_case"):
            sc = scenarios.get(name, {})
            bp = sc.get("by_phase", {})
            p2 = bp.get("phase2", {}).get("success_rate", "—")
            p3 = bp.get("phase3", {}).get("success_rate", "—")
            p4 = bp.get("phase4", {}).get("success_rate", "—")
            p2s = f"{p2:.1%}" if isinstance(p2, float) else p2
            p3s = f"{p3:.1%}" if isinstance(p3, float) else p3
            p4s = f"{p4:.1%}" if isinstance(p4, float) else p4
            lines.append(f"| {name} | {sc.get('n', '?')} | {sc.get('global_rate', 0):.1%} | {p2s} | {p3s} | {p4s} |")
        lines.append("")

        deltas = part2.get("rate_deltas_vs_best", {})
        if deltas:
            lines += ["### Rate Deltas vs Best-Case", ""]
            for k, v in deltas.items():
                lines.append(f"- **{k}**: {v:+.1%}")
            lines.append("")

    # Part 3
    lines += ["## Part 3: V2 Prior Utility", ""]
    if part3:
        baselines = part3.get("baselines", {})
        lines += [
            "| Baseline | Brier | AUC | Cal. Slope |",
            "|----------|-------|-----|-----------|",
        ]
        for name in ("flat_prior", "wong_reference", "v2_empirical"):
            b = baselines.get(name, {})
            slope_str = f"{b['calibration_slope']:.4f}" if b.get("calibration_slope") is not None else "—"
            lines.append(f"| {name} | {b.get('brier_score', '?'):.6f} | {b.get('auc', '?'):.4f} | {slope_str} |")
        lines.append("")

        improvements = part3.get("improvements", {})
        if improvements:
            lines += ["### Brier Improvements vs Flat", ""]
            for k, v in improvements.items():
                lines.append(f"- **{k}**: {v['brier_reduction']:+.6f} ({v['pct_reduction']:+.2f}%)")
            lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Clinical design-feature backtest")
    p.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "data" / "research")
    p.add_argument("--n-folds", type=int, default=10)
    p.add_argument("--n-bootstrap", type=int, default=200)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--parts", default="1,2,3", help="Comma-separated parts to run")
    p.add_argument(
        "--v2-priors",
        type=Path,
        default=PROJECT_ROOT / "production_data" / "clinical_pos_priors_v2.json",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    parts = {int(p.strip()) for p in args.parts.split(",")}

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

    result: Dict[str, Any] = {
        "schema": SCHEMA,
        "built_as_of": date.today().isoformat(),
        "n_labels": len(labels),
        "n_matrix": len(matrix),
        "seed": args.seed,
    }

    part1_result = None
    part2_result = None
    part3_result = None

    if 1 in parts:
        logger.info("=== Part 1: Design-Feature Discrimination ===")
        part1_result = run_part1(matrix, args.n_folds, args.n_bootstrap, args.seed)
        result["part1_discrimination"] = part1_result
        for name, m in part1_result.get("models", {}).items():
            if m.get("status") == "ok":
                logger.info(
                    "  %s: AUC=%.4f, CV=%.4f +/- %.4f (n=%d)", name, m["auc"], m["cv_auc_mean"], m["cv_auc_std"], m["n"]
                )

    if 2 in parts:
        logger.info("=== Part 2: Survivorship Sensitivity ===")
        part2_result = run_part2(labels, catalog, matrix, args.seed)
        result["part2_survivorship"] = part2_result
        for name, sc in part2_result.get("scenarios", {}).items():
            logger.info("  %s: rate=%.1f%% (n=%d)", name, sc["global_rate"] * 100, sc["n"])

    if 3 in parts:
        logger.info("=== Part 3: V2 Prior Utility ===")
        part3_result = run_part3(matrix, args.v2_priors)
        result["part3_prior_utility"] = part3_result
        for name, b in part3_result.get("baselines", {}).items():
            logger.info("  %s: Brier=%.6f, AUC=%.4f", name, b["brier_score"], b["auc"])

    # Write outputs
    args.output_dir.mkdir(parents=True, exist_ok=True)

    json_path = args.output_dir / "clinical_design_backtest.json"
    json_path.write_text(json.dumps(result, indent=2, default=str) + "\n")
    logger.info("JSON → %s", json_path)

    md = generate_markdown(part1_result, part2_result, part3_result)
    md_path = args.output_dir / "clinical_design_backtest.md"
    md_path.write_text(md)
    logger.info("Report → %s", md_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
