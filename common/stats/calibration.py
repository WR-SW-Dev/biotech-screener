"""Calibration diagnostics for pairwise ranker scores.

Provides reliability curves, Brier score, expected calibration error (ECE),
and Platt/isotonic calibration.

Usage:
    from common.stats.calibration import calibration_report, reliability_curve

    report = calibration_report(predicted_scores, actual_outcomes, n_bins=10)
"""

from __future__ import annotations

from typing import Any

import numpy as np


def reliability_curve(
    predicted: np.ndarray,
    actual: np.ndarray,
    n_bins: int = 10,
) -> dict[str, Any]:
    """Compute reliability (calibration) curve.

    Bins predictions and computes mean predicted vs mean actual per bin.

    Args:
        predicted: predicted probabilities or scores in [0, 1]
        actual: binary outcomes (0 or 1)
        n_bins: number of calibration bins

    Returns:
        dict with bin-level statistics
    """
    predicted = np.asarray(predicted, dtype=float)
    actual = np.asarray(actual, dtype=float)

    if len(predicted) != len(actual):
        return {"error": "length mismatch"}

    # Use quantile-based bins for balanced counts
    bin_edges = np.percentile(predicted, np.linspace(0, 100, n_bins + 1))
    bin_edges[0] = -np.inf
    bin_edges[-1] = np.inf

    bins = []
    for i in range(n_bins):
        mask = (predicted >= bin_edges[i]) & (predicted < bin_edges[i + 1])
        if i == n_bins - 1:
            mask = (predicted >= bin_edges[i]) & (predicted <= bin_edges[i + 1])
        if np.sum(mask) == 0:
            continue
        bin_pred = predicted[mask]
        bin_actual = actual[mask]
        bins.append(
            {
                "bin_idx": i,
                "mean_predicted": _round(float(np.mean(bin_pred))),
                "mean_actual": _round(float(np.mean(bin_actual))),
                "count": int(np.sum(mask)),
                "gap": _round(float(abs(np.mean(bin_pred) - np.mean(bin_actual)))),
            }
        )

    return {
        "n_bins": len(bins),
        "n_obs": len(predicted),
        "bins": bins,
    }


def brier_score(
    predicted: np.ndarray | list[float],
    actual: np.ndarray | list[float],
) -> float:
    """Compute Brier score (mean squared error of probability predictions).

    Lower is better. Range [0, 1]. Perfect = 0.
    """
    predicted = np.asarray(predicted, dtype=float)
    actual = np.asarray(actual, dtype=float)
    return float(np.mean((predicted - actual) ** 2))


def expected_calibration_error(
    predicted: np.ndarray | list[float],
    actual: np.ndarray | list[float],
    n_bins: int = 10,
) -> float:
    """Compute Expected Calibration Error (ECE).

    Weighted average of per-bin |mean_predicted - mean_actual|.
    Lower is better. 0 = perfectly calibrated.
    """
    rc = reliability_curve(np.asarray(predicted), np.asarray(actual), n_bins)
    if "error" in rc:
        return float("nan")

    total = sum(b["count"] for b in rc["bins"])
    ece = sum(b["count"] * b["gap"] for b in rc["bins"]) / total
    return float(ece)


def platt_scaling(
    predicted: np.ndarray | list[float],
    actual: np.ndarray | list[float],
) -> dict[str, Any]:
    """Platt scaling: fit logistic regression on predicted scores.

    Maps raw scores to calibrated probabilities via sigmoid.

    Args:
        predicted: raw scores
        actual: binary outcomes

    Returns:
        dict with a, b parameters (calibrated = sigmoid(a * score + b)),
        plus calibrated scores
    """
    from scipy.special import expit

    predicted = np.asarray(predicted, dtype=float)
    actual = np.asarray(actual, dtype=float)

    # Fit logistic: P(y=1 | x) = sigmoid(a*x + b)
    # Use simple grid + refinement
    def neg_log_likelihood(params):
        a, b = params
        logits = a * predicted + b
        logits = np.clip(logits, -30, 30)
        probs = expit(logits)
        probs = np.clip(probs, 1e-10, 1 - 1e-10)
        ll = actual * np.log(probs) + (1 - actual) * np.log(1 - probs)
        return -np.sum(ll)

    from scipy.optimize import minimize

    result = minimize(
        neg_log_likelihood,
        x0=[1.0, 0.0],
        method="Nelder-Mead",
    )
    a_opt, b_opt = result.x

    calibrated = expit(a_opt * predicted + b_opt)

    return {
        "a": _round(float(a_opt)),
        "b": _round(float(b_opt)),
        "brier_raw": _round(brier_score(predicted, actual)),
        "brier_calibrated": _round(brier_score(calibrated, actual)),
        "ece_raw": _round(expected_calibration_error(predicted, actual)),
        "ece_calibrated": _round(expected_calibration_error(calibrated, actual)),
        "calibrated_scores": calibrated,
    }


def isotonic_calibration(
    predicted: np.ndarray | list[float],
    actual: np.ndarray | list[float],
) -> dict[str, Any]:
    """Isotonic regression calibration.

    Non-parametric monotone calibration mapping.
    """
    from sklearn.isotonic import IsotonicRegression

    predicted = np.asarray(predicted, dtype=float)
    actual = np.asarray(actual, dtype=float)

    iso = IsotonicRegression(out_of_bounds="clip")
    calibrated = iso.fit_transform(predicted, actual)

    return {
        "brier_raw": _round(brier_score(predicted, actual)),
        "brier_calibrated": _round(brier_score(calibrated, actual)),
        "ece_raw": _round(expected_calibration_error(predicted, actual)),
        "ece_calibrated": _round(expected_calibration_error(calibrated, actual)),
        "calibrated_scores": calibrated,
    }


def calibration_report(
    predicted: np.ndarray | list[float],
    actual: np.ndarray | list[float],
    n_bins: int = 10,
    run_platt: bool = True,
    run_isotonic: bool = True,
) -> dict[str, Any]:
    """Full calibration report with multiple metrics and calibration methods.

    Args:
        predicted: predicted scores/probabilities
        actual: binary outcomes (0/1)
        n_bins: number of calibration bins
        run_platt: whether to attempt Platt scaling
        run_isotonic: whether to attempt isotonic calibration

    Returns:
        dict with reliability curve, Brier, ECE, and optional calibration results
    """
    predicted = np.asarray(predicted, dtype=float)
    actual = np.asarray(actual, dtype=float)

    result = {
        "n_obs": len(predicted),
        "base_rate": _round(float(np.mean(actual))),
        "mean_predicted": _round(float(np.mean(predicted))),
        "brier_score": _round(brier_score(predicted, actual)),
        "ece": _round(expected_calibration_error(predicted, actual, n_bins)),
        "reliability_curve": reliability_curve(predicted, actual, n_bins),
    }

    # Verdict
    ece_val = result["ece"]
    if ece_val is not None and ece_val < 0.05:
        result["calibration_verdict"] = "GOOD — calibrated for sizing"
    elif ece_val is not None and ece_val < 0.10:
        result["calibration_verdict"] = "FAIR — calibrated for ranking"
    else:
        result["calibration_verdict"] = "POOR — ordinal ranking only"

    if run_platt:
        try:
            platt = platt_scaling(predicted, actual)
            result["platt"] = {k: v for k, v in platt.items() if k != "calibrated_scores"}
        except Exception as e:
            result["platt"] = {"error": str(e)}

    if run_isotonic:
        try:
            iso = isotonic_calibration(predicted, actual)
            result["isotonic"] = {k: v for k, v in iso.items() if k != "calibrated_scores"}
        except Exception as e:
            result["isotonic"] = {"error": str(e)}

    return result


def _round(v, d=4):
    if v is None:
        return None
    if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
        return None
    return round(v, d)
