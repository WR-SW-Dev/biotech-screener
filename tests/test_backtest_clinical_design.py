"""Tests for backtest_clinical_design_features.py — all synthetic, no file I/O."""

from __future__ import annotations

import random
import sys
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.research.backtest_clinical_design_features import (
    bootstrap_auc_ci,
    build_survivorship_scenarios,
    compute_auc,
    compute_brier,
    compute_calibration_slope,
    compute_reliability_bins,
    fit_logistic,
    predict_logistic,
    run_part1,
    run_part3,
    sigmoid,
    stratified_kfold,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_rows(n: int = 200, seed: int = 42) -> List[Dict[str, Any]]:
    """Synthetic feature matrix rows with known structure."""
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        phase_num = rng.choice([2, 3, 4])
        ep_hard = rng.choice([0, 1])
        enroll = rng.choice([1, 2, 3, 4])
        # Higher phase → higher success prob (for testable discrimination)
        p = 0.3 + 0.15 * (phase_num - 2) + 0.05 * ep_hard
        outcome = 1 if rng.random() < p else 0
        rows.append(
            {
                "nct_id": f"NCT{i:08d}",
                "ticker": "TEST",
                "binary_outcome": outcome,
                "phase": f"phase{phase_num}",
                "phase_num": float(phase_num),
                "endpoint_class": "overall_survival" if ep_hard else "other",
                "endpoint_hard": ep_hard,
                "biomarker_selected": rng.choice([0, 1]) if rng.random() < 0.1 else 0,
                "enrollment_bucket": ["small", "medium", "large", "very_large"][enroll - 1],
                "enrollment_ordinal": enroll,
                "enrollment_count": enroll * 100,
                "status": "COMPLETED",
            }
        )
    return rows


def _make_labels_and_catalog(n_labeled: int = 100, n_unlabeled: int = 200, seed: int = 42):
    """Synthetic labels dict and catalog dict for Part 2."""
    rng = random.Random(seed)
    labels = {}
    catalog = {}

    for i in range(n_labeled):
        nct = f"NCT{i:08d}"
        phase = rng.choice(["phase2", "phase3", "phase4"])
        outcome = 1 if rng.random() < 0.6 else 0
        labels[nct] = {"nct_id": nct, "binary_outcome": outcome, "confidence": "high"}
        catalog[nct] = {
            "nct_id": nct,
            "phase": phase,
            "status": "COMPLETED",
            "design": {"endpoint_class": "other", "enrollment_bucket": "medium", "biomarker_selected": False},
            "lifecycle": {"is_completed": True, "is_terminated": False, "has_posted_results": True},
        }

    for i in range(n_labeled, n_labeled + n_unlabeled):
        nct = f"NCT{i:08d}"
        phase = rng.choice(["phase2", "phase3", "phase4"])
        status = rng.choice(["COMPLETED", "TERMINATED", "WITHDRAWN", "COMPLETED"])
        is_term = status in ("TERMINATED", "WITHDRAWN")
        has_results = not is_term and rng.random() < 0.3
        catalog[nct] = {
            "nct_id": nct,
            "phase": phase,
            "status": status,
            "design": {"endpoint_class": "other", "enrollment_bucket": "medium", "biomarker_selected": False},
            "lifecycle": {
                "is_completed": not is_term,
                "is_terminated": is_term,
                "has_posted_results": has_results,
            },
        }

    return labels, catalog


# ===========================================================================
# Part 1 tests
# ===========================================================================


class TestSigmoid:
    def test_zero(self):
        assert sigmoid(0) == 0.5

    def test_large_positive(self):
        assert sigmoid(600) == 1.0

    def test_large_negative(self):
        assert sigmoid(-600) == 0.0

    def test_monotonic(self):
        assert sigmoid(-2) < sigmoid(0) < sigmoid(2)


class TestFitLogistic:
    def test_basic_convergence(self):
        """Logistic fit on separable data converges."""
        X = [[1.0, float(i)] for i in range(20)]
        y = [0.0] * 10 + [1.0] * 10
        beta, var = fit_logistic(X, y)
        assert len(beta) == 2
        assert beta[1] > 0  # positive slope for ascending outcome

    def test_returns_variance(self):
        X = [[1.0, float(i)] for i in range(40)]
        y = [0.0] * 20 + [1.0] * 20
        beta, var = fit_logistic(X, y)
        assert len(var) == 2
        for v in var:
            assert v > 0

    def test_predictions_bounded(self):
        X = [[1.0, float(i)] for i in range(30)]
        y = [0.0] * 15 + [1.0] * 15
        beta, _ = fit_logistic(X, y)
        preds = predict_logistic(X, beta)
        assert all(0 <= p <= 1 for p in preds)


class TestAUC:
    def test_perfect(self):
        y = [0, 0, 0, 1, 1, 1]
        s = [0.1, 0.2, 0.3, 0.7, 0.8, 0.9]
        assert compute_auc(y, s) == 1.0

    def test_random(self):
        y = [0, 1, 0, 1]
        s = [0.5, 0.5, 0.5, 0.5]
        assert compute_auc(y, s) == 0.5

    def test_inverted(self):
        y = [1, 1, 0, 0]
        s = [0.1, 0.2, 0.8, 0.9]
        assert compute_auc(y, s) == 0.0

    def test_no_positives(self):
        assert compute_auc([0, 0], [0.1, 0.9]) == 0.5


class TestBootstrapAUC:
    def test_returns_three(self):
        y = [0] * 50 + [1] * 50
        s = [0.3] * 50 + [0.7] * 50
        auc, lo, hi = bootstrap_auc_ci(y, s, n_bootstrap=50, seed=42)
        assert lo <= auc <= hi

    def test_deterministic(self):
        y = [0] * 30 + [1] * 30
        s = [0.2 + i * 0.01 for i in range(60)]
        a1 = bootstrap_auc_ci(y, s, n_bootstrap=50, seed=99)
        a2 = bootstrap_auc_ci(y, s, n_bootstrap=50, seed=99)
        assert a1 == a2


class TestStratifiedKfold:
    def test_correct_n_folds(self):
        y = [0] * 40 + [1] * 60
        splits = stratified_kfold(y, 5, seed=42)
        assert len(splits) == 5

    def test_no_overlap(self):
        y = [0] * 30 + [1] * 30
        splits = stratified_kfold(y, 3, seed=42)
        for train, test in splits:
            assert len(set(train) & set(test)) == 0

    def test_all_indices_covered(self):
        y = [0] * 20 + [1] * 20
        splits = stratified_kfold(y, 4, seed=42)
        all_test = []
        for _, test in splits:
            all_test.extend(test)
        assert sorted(all_test) == list(range(40))

    def test_stratification(self):
        """Each fold should have roughly proportional class balance."""
        y = [0] * 40 + [1] * 60
        splits = stratified_kfold(y, 5, seed=42)
        for _, test in splits:
            test_labels = [y[i] for i in test]
            rate = sum(test_labels) / len(test_labels)
            assert 0.4 < rate < 0.8  # global rate is 0.6

    def test_deterministic(self):
        y = [0] * 20 + [1] * 20
        s1 = stratified_kfold(y, 4, seed=42)
        s2 = stratified_kfold(y, 4, seed=42)
        for (t1, v1), (t2, v2) in zip(s1, s2):
            assert t1 == t2
            assert v1 == v2


class TestRunPart1:
    def test_all_models_present(self):
        rows = _make_rows(300)
        result = run_part1(rows, n_folds=3, n_bootstrap=20, seed=42)
        assert "models" in result
        for name in ("phase_only", "phase_endpoint", "multi_feature"):
            assert name in result["models"]
            assert result["models"][name]["status"] == "ok"

    def test_incremental_lifts(self):
        rows = _make_rows(300)
        result = run_part1(rows, n_folds=3, n_bootstrap=20, seed=42)
        lifts = result["incremental_auc_lifts"]
        assert "multi_over_phase" in lifts

    def test_insufficient_data(self):
        rows = _make_rows(10)
        result = run_part1(rows, n_folds=3, n_bootstrap=20, seed=42)
        # With only 10 rows, should report insufficient
        for name in result["models"]:
            assert result["models"][name]["status"] == "insufficient"


# ===========================================================================
# Part 2 tests
# ===========================================================================


class TestBuildSurvivorshipScenarios:
    def test_three_scenarios(self):
        labels, catalog = _make_labels_and_catalog()
        result = build_survivorship_scenarios(labels, catalog)
        scenarios = result["scenarios"]
        assert set(scenarios.keys()) == {"best_case", "worst_case", "plausible_case"}

    def test_worst_more_than_best(self):
        labels, catalog = _make_labels_and_catalog()
        result = build_survivorship_scenarios(labels, catalog)
        sc = result["scenarios"]
        assert sc["worst_case"]["n"] > sc["best_case"]["n"]

    def test_worst_rate_lower(self):
        labels, catalog = _make_labels_and_catalog()
        result = build_survivorship_scenarios(labels, catalog)
        sc = result["scenarios"]
        # Adding failures should lower the rate
        assert sc["worst_case"]["global_rate"] <= sc["best_case"]["global_rate"]

    def test_terminated_are_failures(self):
        labels, catalog = _make_labels_and_catalog(n_labeled=50, n_unlabeled=100)
        result = build_survivorship_scenarios(labels, catalog)
        meta = result["metadata"]
        assert meta["n_terminated_added"] > 0

    def test_deterministic_coin_flip(self):
        labels, catalog = _make_labels_and_catalog()
        r1 = build_survivorship_scenarios(labels, catalog, seed=42)
        r2 = build_survivorship_scenarios(labels, catalog, seed=42)
        assert r1["scenarios"]["plausible_case"]["global_rate"] == r2["scenarios"]["plausible_case"]["global_rate"]

    def test_plausible_between_best_and_worst(self):
        labels, catalog = _make_labels_and_catalog()
        result = build_survivorship_scenarios(labels, catalog)
        sc = result["scenarios"]
        # Plausible should generally be between best and worst
        assert sc["worst_case"]["global_rate"] <= sc["plausible_case"]["global_rate"] <= sc["best_case"]["global_rate"]


# ===========================================================================
# Part 3 tests
# ===========================================================================


class TestBrier:
    def test_perfect(self):
        assert compute_brier([1, 0, 1], [1.0, 0.0, 1.0]) == 0.0

    def test_worst(self):
        assert compute_brier([1, 0], [0.0, 1.0]) == 1.0

    def test_partial(self):
        b = compute_brier([1, 0], [0.8, 0.2])
        assert 0 < b < 1


class TestCalibrationSlope:
    def test_constant_pred_returns_none(self):
        assert compute_calibration_slope([1, 0, 1], [0.5, 0.5, 0.5]) is None

    def test_varied_preds(self):
        y = [0] * 50 + [1] * 50
        p = [0.2] * 50 + [0.8] * 50
        slope = compute_calibration_slope(y, p)
        assert slope is not None
        assert slope > 0


class TestReliabilityBins:
    def test_correct_n_bins(self):
        y = [0] * 50 + [1] * 50
        p = [i / 100 for i in range(100)]
        bins = compute_reliability_bins(y, p, n_bins=5)
        assert len(bins) == 5

    def test_bin_structure(self):
        y = [0, 1, 0, 1, 0, 1, 0, 1, 0, 1]
        p = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
        bins = compute_reliability_bins(y, p, n_bins=2)
        for b in bins:
            assert "mean_pred" in b
            assert "mean_outcome" in b
            assert "n" in b


class TestRunPart3:
    def test_all_baselines(self):
        rows = _make_rows(200)
        # Add phase field
        result = run_part3(rows, v2_priors_path=None)
        baselines = result.get("baselines", {})
        assert "flat_prior" in baselines
        assert "wong_reference" in baselines
        assert "v2_empirical" in baselines

    def test_flat_prior_brier(self):
        rows = _make_rows(200)
        result = run_part3(rows, v2_priors_path=None)
        # Flat prior Brier should be > 0 (not perfect)
        assert result["baselines"]["flat_prior"]["brier_score"] > 0

    def test_improvements_present(self):
        rows = _make_rows(200)
        result = run_part3(rows, v2_priors_path=None)
        assert "improvements" in result

    def test_no_rows(self):
        result = run_part3([], v2_priors_path=None)
        assert result.get("status") == "no_valid_rows"
