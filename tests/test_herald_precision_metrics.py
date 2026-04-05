"""Tests for Herald precision metrics and ground truth sampler."""

# Import path setup
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.research.herald_ground_truth_sampler import auto_label_from_crt, stratified_sample
from scripts.research.herald_precision_metrics import (
    compute_category_metrics,
    crt_cross_reference,
    informational_price_check,
    precision_by_source_type,
    severity_price_check,
)

# ---- Ground truth sampler tests ----


class TestStratifiedSample:
    def test_returns_n_total(self):
        records = [{"event_id": str(i), "event_category": f"cat_{i % 3}"} for i in range(200)]
        sample = stratified_sample(records, n_total=50)
        assert len(sample) == 50

    def test_category_representation(self):
        records = []
        for i in range(100):
            records.append({"event_id": str(i), "event_category": "clinical"})
        for i in range(20):
            records.append({"event_id": f"s{i}", "event_category": "safety"})
        for i in range(10):
            records.append({"event_id": f"m{i}", "event_category": "mna"})

        sample = stratified_sample(records, n_total=50, min_per_category=5)
        cats = {r["event_category"] for r in sample}
        # All three categories should be present
        assert "clinical" in cats
        assert "safety" in cats
        assert "mna" in cats
        # Each should have at least min_per_category
        for cat in cats:
            count = sum(1 for r in sample if r["event_category"] == cat)
            assert count >= 5

    def test_deterministic(self):
        records = [{"event_id": str(i), "event_category": f"cat_{i % 5}"} for i in range(100)]
        s1 = stratified_sample(records, seed=42)
        s2 = stratified_sample(records, seed=42)
        ids1 = [r["event_id"] for r in s1]
        ids2 = [r["event_id"] for r in s2]
        assert ids1 == ids2

    def test_empty_input(self):
        sample = stratified_sample([], n_total=10)
        assert len(sample) == 0


class TestAutoLabelFromCRT:
    def test_exact_date_match(self):
        sample = [
            {
                "event_id": "1",
                "ticker": "ACME",
                "event_category": "clinical",
                "published_at_utc": "2026-03-17T10:00:00Z",
            }
        ]
        resolutions = [
            {
                "ticker": "ACME",
                "catalyst_date": "2026-03-17",
                "catalyst_type": "PHASE_3_READOUT",
                "outcome": "HIT",
            }
        ]
        result = auto_label_from_crt(sample, resolutions)
        assert result[0]["gt_label_source"] == "crt_auto"
        assert result[0]["gt_event_category"] == "clinical"
        assert result[0]["gt_outcome"] == "hit"

    def test_window_match(self):
        sample = [
            {
                "event_id": "1",
                "ticker": "ACME",
                "event_category": "regulatory",
                "published_at_utc": "2026-03-18T10:00:00Z",
            }
        ]
        resolutions = [
            {
                "ticker": "ACME",
                "catalyst_date": "2026-03-15",
                "catalyst_type": "PDUFA_ACTION",
                "outcome": "MISS",
            }
        ]
        result = auto_label_from_crt(sample, resolutions, match_window_days=3)
        assert result[0]["gt_label_source"] == "crt_auto"
        assert result[0]["gt_event_category"] == "regulatory"

    def test_no_match(self):
        sample = [
            {
                "event_id": "1",
                "ticker": "ACME",
                "event_category": "clinical",
                "published_at_utc": "2026-03-17T10:00:00Z",
            }
        ]
        result = auto_label_from_crt(sample, [])
        assert result[0]["gt_label_source"] == "unlabeled"


# ---- Precision metrics tests ----


class TestCategoryMetrics:
    def test_perfect_classification(self):
        labeled = [
            {"event_category": "clinical", "gt_event_category": "clinical"},
            {"event_category": "regulatory", "gt_event_category": "regulatory"},
        ]
        metrics = compute_category_metrics(labeled)
        assert metrics["clinical"]["precision"] == 1.0
        assert metrics["clinical"]["recall"] == 1.0
        assert metrics["clinical"]["f1"] == 1.0

    def test_all_wrong(self):
        labeled = [
            {"event_category": "clinical", "gt_event_category": "regulatory"},
            {"event_category": "regulatory", "gt_event_category": "clinical"},
        ]
        metrics = compute_category_metrics(labeled)
        assert metrics["clinical"]["precision"] == 0.0
        assert metrics["regulatory"]["precision"] == 0.0

    def test_partial(self):
        labeled = [
            {"event_category": "clinical", "gt_event_category": "clinical"},
            {"event_category": "clinical", "gt_event_category": "regulatory"},
            {"event_category": "regulatory", "gt_event_category": "regulatory"},
        ]
        metrics = compute_category_metrics(labeled)
        # clinical: TP=1, FP=1, FN=0 -> P=0.5, R=1.0
        assert metrics["clinical"]["precision"] == 0.5
        assert metrics["clinical"]["recall"] == 1.0

    def test_missing_gt_skipped(self):
        labeled = [
            {"event_category": "clinical", "gt_event_category": None},
            {"event_category": "clinical", "gt_event_category": "clinical"},
        ]
        metrics = compute_category_metrics(labeled)
        # Only 1 valid record
        assert metrics["clinical"]["support"] == 1


class TestInformationalPriceCheck:
    def test_no_move_passes(self):
        records = [{"informational_only": True, "ticker": "A", "published_at_utc": "2026-01-03"}]
        prices = {"A": {"2026-01-02": 10.0, "2026-01-03": 10.1}}  # 1% move
        result = informational_price_check(records, prices, vol_adjusted=False, threshold_pct=5.0)
        assert result["n_checked"] == 1
        assert result["n_surprised"] == 0

    def test_big_move_flagged(self):
        records = [{"informational_only": True, "ticker": "A", "published_at_utc": "2026-01-03"}]
        prices = {"A": {"2026-01-02": 10.0, "2026-01-03": 11.0}}  # 10% move
        result = informational_price_check(records, prices, vol_adjusted=False, threshold_pct=5.0)
        assert result["n_surprised"] == 1
        assert result["false_informational_rate"] == 1.0

    def test_vol_adjusted_ignores_normal_volatility(self):
        """A 6% move on a ticker that routinely moves 5% should NOT flag."""
        # Build 60 days of prices with ~5% daily moves
        base = 10.0
        price_series = {}
        for i in range(61):
            d = f"2026-01-{i+1:02d}" if i < 28 else f"2026-02-{i-27:02d}"
            price_series[d] = base
            base *= 1.05 if i % 2 == 0 else 0.95  # alternating +5%/-5%
        prices = {"A": price_series}
        records = [{"informational_only": True, "ticker": "A", "published_at_utc": "2026-02-02"}]
        result = informational_price_check(records, prices, vol_adjusted=True, vol_floor_pct=10.0)
        # 6% move on a 5%-daily-vol ticker should NOT flag (threshold > 10%)
        assert result["n_surprised"] == 0

    def test_vol_adjusted_flags_true_outlier(self):
        """A 25% move should flag even on a volatile ticker."""
        price_series = {}
        base = 10.0
        for i in range(61):
            d = f"2026-01-{i+1:02d}" if i < 28 else f"2026-02-{i-27:02d}"
            price_series[d] = base
            base *= 1.03 if i % 2 == 0 else 0.97
        # Spike on the test date
        price_series["2026-02-03"] = price_series.get("2026-02-02", 10.0) * 1.25
        prices = {"A": price_series}
        records = [{"informational_only": True, "ticker": "A", "published_at_utc": "2026-02-03"}]
        result = informational_price_check(records, prices, vol_adjusted=True, vol_floor_pct=10.0)
        assert result["n_surprised"] == 1

    def test_missing_price_skipped(self):
        records = [{"informational_only": True, "ticker": "A", "published_at_utc": "2026-01-03"}]
        prices = {}  # no price data
        result = informational_price_check(records, prices)
        assert result["n_checked"] == 0


class TestSeverityPriceCheck:
    def test_critical_with_move(self):
        records = [
            {"severity": "critical", "event_category": "clinical", "ticker": "A", "published_at_utc": "2026-01-03"},
        ]
        prices = {"A": {"2026-01-02": 10.0, "2026-01-03": 10.5}}  # 5% move
        result = severity_price_check(records, prices, min_move_pct=3.0)
        assert result["n_with_move"] == 1

    def test_high_severity_no_move(self):
        records = [
            {"severity": "high", "event_category": "regulatory", "ticker": "A", "published_at_utc": "2026-01-03"},
        ]
        prices = {"A": {"2026-01-02": 10.0, "2026-01-03": 10.1}}  # 1%
        result = severity_price_check(records, prices, min_move_pct=3.0)
        assert result["n_with_move"] == 0


class TestSourceReliability:
    def test_by_source_type(self):
        records = [
            {"source_type": "company_ir", "informational_only": False, "severity": "high"},
            {"source_type": "company_ir", "informational_only": True, "severity": "low"},
            {"source_type": "globenewswire", "informational_only": True, "severity": "low"},
        ]
        result = precision_by_source_type(records)
        assert result["company_ir"]["n_records"] == 2
        assert result["company_ir"]["informational_rate"] == 0.5
        assert result["globenewswire"]["n_records"] == 1


class TestCRTCrossReference:
    def test_match_agreement(self):
        classified = [
            {
                "ticker": "ACME",
                "published_at_utc": "2026-03-17T10:00:00Z",
                "event_category": "clinical",
                "event_outcome_guess": "hit",
            }
        ]
        resolutions = [
            {
                "ticker": "ACME",
                "catalyst_date": "2026-03-17",
                "catalyst_type": "PHASE_3_READOUT",
                "outcome": "HIT",
            }
        ]
        result = crt_cross_reference(classified, resolutions)
        assert result["n_matched"] == 1
        assert result["category_agreement_rate"] == 1.0

    def test_no_match(self):
        classified = [
            {
                "ticker": "ACME",
                "published_at_utc": "2026-03-17T10:00:00Z",
                "event_category": "clinical",
                "event_outcome_guess": "hit",
            }
        ]
        result = crt_cross_reference(classified, [])
        assert result["n_matched"] == 0
