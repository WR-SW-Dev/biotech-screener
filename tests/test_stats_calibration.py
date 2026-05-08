"""Tests for common.stats.calibration module."""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.stats.calibration import brier_score, calibration_report, expected_calibration_error, reliability_curve


class TestBrierScore:
    def test_perfect_predictions(self):
        """Brier score of perfect predictions is 0."""
        pred = np.array([1.0, 0.0, 1.0, 0.0])
        actual = np.array([1, 0, 1, 0])
        assert brier_score(pred, actual) < 1e-10

    def test_worst_predictions(self):
        """Brier score of perfectly wrong predictions is 1."""
        pred = np.array([0.0, 1.0, 0.0, 1.0])
        actual = np.array([1, 0, 1, 0])
        assert abs(brier_score(pred, actual) - 1.0) < 1e-10

    def test_random_predictions(self):
        """Brier score of 0.5 predictions on balanced data should be ~0.25."""
        pred = np.full(100, 0.5)
        actual = np.array([1] * 50 + [0] * 50)
        assert abs(brier_score(pred, actual) - 0.25) < 1e-10


class TestReliabilityCurve:
    def test_basic(self):
        """Reliability curve produces valid bin structure."""
        np.random.seed(42)
        pred = np.random.rand(200)
        actual = (pred + np.random.randn(200) * 0.2 > 0.5).astype(float)
        rc = reliability_curve(pred, actual, n_bins=5)
        assert rc["n_obs"] == 200
        assert len(rc["bins"]) > 0
        assert all("mean_predicted" in b for b in rc["bins"])
        assert all("mean_actual" in b for b in rc["bins"])


class TestECE:
    def test_well_calibrated(self):
        """ECE of well-calibrated predictions should be low."""
        np.random.seed(42)
        n = 1000
        pred = np.random.rand(n)
        actual = (np.random.rand(n) < pred).astype(float)
        ece = expected_calibration_error(pred, actual, n_bins=10)
        assert ece < 0.05  # well-calibrated

    def test_poorly_calibrated(self):
        """ECE of constant predictions on varied data should be higher."""
        pred = np.full(100, 0.8)
        actual = np.array([1] * 30 + [0] * 70)
        ece = expected_calibration_error(pred, actual, n_bins=5)
        assert ece > 0.3


class TestCalibrationReport:
    def test_report_structure(self):
        """Report should have all expected fields."""
        np.random.seed(42)
        pred = np.random.rand(200)
        actual = (np.random.rand(200) < pred).astype(float)
        report = calibration_report(pred, actual, n_bins=5)
        assert "brier_score" in report
        assert "ece" in report
        assert "reliability_curve" in report
        assert "calibration_verdict" in report

    def test_skips_calibration_on_request(self):
        np.random.seed(42)
        pred = np.random.rand(50)
        actual = (np.random.rand(50) > 0.5).astype(float)
        report = calibration_report(pred, actual, run_platt=False, run_isotonic=False)
        assert "platt" not in report
        assert "isotonic" not in report
