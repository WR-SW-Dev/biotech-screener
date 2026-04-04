"""Layer 2 — Timing / Execution Hazard Model.

Estimates the probability distribution of when a catalyst actually occurs.

Primary approach: discrete-time logistic event-in-window model.
Evaluates P(event arrives on time | features) using a feature-based
logistic model trained on historical ledger data where we know
actual vs expected dates.

Also supports survival/hazard analysis via common.stats.survival.

PIT safety:
- Feature computation uses only revisions known at as_of_date
- Actual arrival date is never used in feature computation
"""

from __future__ import annotations

import logging
import math
from datetime import date
from typing import Any, Dict, List, Optional

from .data_contracts import CatalystNode, DatePrecision, EventFamily, TimingEstimate

logger = logging.getLogger(__name__)

# Default model coefficients (logistic regression weights)
# These are initial priors — will be refined with data.
# Positive = increases P(on_time), negative = increases P(slip)
_DEFAULT_COEFFICIENTS = {
    "intercept": 0.5,
    "date_confidence": 1.2,  # higher confidence → more on-time
    "is_regulatory": 0.8,  # hard-dated regulatory events more reliable
    "is_clinical": -0.3,  # clinical milestones slip more
    "precision_day": 0.6,  # DAY precision → more reliable
    "precision_month_or_worse": -0.5,  # vague dates → likely to slip
    "n_revisions": -0.25,  # each revision reduces confidence
    "last_revision_pushout": -0.6,  # recent pushout → momentum
    "last_revision_pullin": 0.3,  # recent pullin → positive signal
    "phase_early": -0.2,  # early phase → more slippage
    "phase_3": 0.15,  # phase 3 → somewhat more disciplined
    "sponsor_quality": 0.4,  # better sponsors → more on-time
    "days_to_expected_near": 0.3,  # close events more certain
    "days_to_expected_far": -0.2,  # far events less certain
}


def _sigmoid(x: float) -> float:
    """Numerically stable sigmoid."""
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    ez = math.exp(x)
    return ez / (1.0 + ez)


class TimingHazardModel:
    """Estimates timing probability distribution for catalyst events.

    Usage:
        model = TimingHazardModel()
        estimate = model.estimate(node, as_of_date)
    """

    def __init__(
        self,
        coefficients: Optional[Dict[str, float]] = None,
        slip_window_days: int = 30,
        early_window_days: int = 14,
    ) -> None:
        self.coefficients = coefficients or dict(_DEFAULT_COEFFICIENTS)
        self.slip_window_days = slip_window_days
        self.early_window_days = early_window_days

    def estimate(
        self,
        node: CatalystNode,
        as_of: date,
    ) -> TimingEstimate:
        """Produce a timing estimate for a catalyst node.

        Returns TimingEstimate with on-time/slip/early probabilities
        and expected delay.
        """
        features = self._extract_features(node, as_of)
        logit = self._compute_logit(features)
        p_on_time = _sigmoid(logit)

        # Allocate slip vs early from remainder
        p_remainder = 1.0 - p_on_time
        early_share = self._early_share(features)
        p_early = p_remainder * early_share
        p_slip = p_remainder * (1.0 - early_share)

        # Expected delay (days)
        expected_delay = self._expected_delay(p_slip, features)

        # Days from as_of to expected arrival
        days_to = node.days_to_event(as_of)
        if days_to is not None and days_to > 0:
            median_arrival = days_to + expected_delay
        else:
            median_arrival = expected_delay

        # Hazard rate: instantaneous probability of event per day
        if days_to and days_to > 0:
            hazard = p_on_time / max(days_to, 1)
        else:
            hazard = 0.0

        return TimingEstimate(
            node_id=node.node_id,
            as_of_date=str(as_of),
            prob_on_time=round(p_on_time, 4),
            prob_slip=round(p_slip, 4),
            prob_early=round(p_early, 4),
            expected_delay_days=round(expected_delay, 1),
            median_arrival_days=round(max(median_arrival, 0), 1),
            hazard_rate=round(hazard, 6),
            features_used=features,
            model_version="timing_logistic_v0.1",
        )

    def _extract_features(self, node: CatalystNode, as_of: date) -> Dict[str, Any]:
        """Extract PIT-safe features from a catalyst node."""
        revisions = node.pit_revisions(as_of)
        n_revisions = len(revisions)

        # Last revision direction
        last_pushout = False
        last_pullin = False
        if revisions:
            last = revisions[-1]
            if last.field_name == "expected_date":
                try:
                    old_d = date.fromisoformat(last.old_value)
                    new_d = date.fromisoformat(last.new_value)
                    if new_d > old_d:
                        last_pushout = True
                    elif new_d < old_d:
                        last_pullin = True
                except (ValueError, TypeError):
                    pass

        days_to = node.days_to_event(as_of)

        features = {
            "date_confidence": node.date_confidence,
            "is_regulatory": 1.0 if node.event_family == EventFamily.REGULATORY.value else 0.0,
            "is_clinical": 1.0 if node.event_family == EventFamily.CLINICAL.value else 0.0,
            "precision_day": 1.0 if node.date_precision == DatePrecision.DAY.value else 0.0,
            "precision_month_or_worse": (
                1.0
                if node.date_precision
                in (
                    DatePrecision.MONTH.value,
                    DatePrecision.QUARTER.value,
                    DatePrecision.HALF_YEAR.value,
                    DatePrecision.YEAR.value,
                    DatePrecision.UNKNOWN.value,
                )
                else 0.0
            ),
            "n_revisions": min(n_revisions, 5),  # cap at 5
            "last_revision_pushout": 1.0 if last_pushout else 0.0,
            "last_revision_pullin": 1.0 if last_pullin else 0.0,
            "phase_early": 1.0 if node.phase in ("1", "1_2") else 0.0,
            "phase_3": 1.0 if node.phase == "3" else 0.0,
            "sponsor_quality": node.sponsor_quality or 0.5,
            "days_to_expected_near": 1.0 if days_to is not None and 0 < days_to <= 60 else 0.0,
            "days_to_expected_far": 1.0 if days_to is not None and days_to > 120 else 0.0,
        }
        return features

    def _compute_logit(self, features: Dict[str, Any]) -> float:
        """Compute logit from features and coefficients."""
        logit = self.coefficients.get("intercept", 0.0)
        for key, value in features.items():
            coeff = self.coefficients.get(key, 0.0)
            logit += coeff * float(value)
        return logit

    def _early_share(self, features: Dict[str, Any]) -> float:
        """What fraction of non-on-time probability is 'early' vs 'slip'.

        Regulatory events rarely come early. Clinical events occasionally do.
        """
        if features.get("is_regulatory", 0):
            return 0.05  # regulatory almost never early
        if features.get("precision_day", 0):
            return 0.10  # precise dates mostly slip, rarely early
        return 0.15  # clinical with vague dates can go either way

    def _expected_delay(self, p_slip: float, features: Dict[str, Any]) -> float:
        """Estimate expected delay in days conditional on overall slip probability."""
        # Base delay proportional to slip probability
        base_delay = p_slip * 45  # at 100% slip, expect ~45 day delay

        # Adjustments
        if features.get("precision_month_or_worse", 0):
            base_delay *= 1.5  # vague dates → bigger delays
        if features.get("last_revision_pushout", 0):
            base_delay *= 1.3  # pushout momentum
        if features.get("is_regulatory", 0):
            base_delay *= 0.5  # regulatory delays smaller (hard dates)

        return base_delay

    # =========================================================================
    # Training / calibration (research mode)
    # =========================================================================

    def train_on_historical(
        self,
        training_data: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Train logistic model on historical timing data.

        Each record needs:
            - node features (from _extract_features)
            - actual_on_time: 1 if event landed in window, 0 if slipped

        Returns training diagnostics.
        """
        if len(training_data) < 10:
            logger.warning("Insufficient training data: %d records", len(training_data))
            return {"error": "insufficient_data", "n": len(training_data)}

        # Simple gradient descent on logistic loss
        lr = 0.01
        epochs = 200
        feature_keys = [k for k in self.coefficients if k != "intercept"]

        for epoch in range(epochs):
            total_loss = 0.0
            for rec in training_data:
                features = rec.get("features", {})
                y = float(rec.get("actual_on_time", 0))

                logit = self.coefficients["intercept"]
                for k in feature_keys:
                    logit += self.coefficients.get(k, 0.0) * float(features.get(k, 0.0))

                p = _sigmoid(logit)
                p = max(min(p, 0.999), 0.001)  # clamp for log stability

                # Binary cross-entropy
                loss = -(y * math.log(p) + (1 - y) * math.log(1 - p))
                total_loss += loss

                # Gradient update
                grad = p - y
                self.coefficients["intercept"] -= lr * grad
                for k in feature_keys:
                    self.coefficients[k] -= lr * grad * float(features.get(k, 0.0))

        # Evaluate
        correct = 0
        for rec in training_data:
            features = rec.get("features", {})
            y = rec.get("actual_on_time", 0)
            logit = self._compute_logit(features)
            pred = 1 if _sigmoid(logit) >= 0.5 else 0
            if pred == y:
                correct += 1

        accuracy = correct / len(training_data)
        avg_loss = total_loss / len(training_data)

        result = {
            "n_training": len(training_data),
            "epochs": epochs,
            "final_loss": round(avg_loss, 4),
            "accuracy": round(accuracy, 4),
            "coefficients": {k: round(v, 4) for k, v in self.coefficients.items()},
        }
        logger.info("Timing model trained: accuracy=%.3f, loss=%.4f", accuracy, avg_loss)
        return result

    def build_training_data(
        self,
        nodes: List[CatalystNode],
        actual_dates: Dict[str, str],
        as_of_dates: List[date],
    ) -> List[Dict[str, Any]]:
        """Build training dataset from resolved nodes.

        Args:
            nodes: CatalystNode objects (resolved ones)
            actual_dates: {node_id: actual_event_date_iso}
            as_of_dates: evaluation dates for PIT feature extraction

        Returns:
            List of training records with features and label
        """
        records = []
        for node in nodes:
            if node.node_id not in actual_dates:
                continue
            if not node.expected_date:
                continue

            actual_str = actual_dates[node.node_id]
            try:
                expected = date.fromisoformat(node.expected_date)
                actual = date.fromisoformat(actual_str)
            except (ValueError, TypeError):
                continue

            delay = (actual - expected).days
            on_time = 1 if abs(delay) <= self.slip_window_days else 0

            # Use as_of before the expected date for PIT-safe features
            for as_of in as_of_dates:
                if as_of >= expected:
                    continue  # can't use post-event features
                if not node.is_visible(as_of):
                    continue

                features = self._extract_features(node, as_of)
                records.append(
                    {
                        "node_id": node.node_id,
                        "ticker": node.ticker,
                        "as_of_date": str(as_of),
                        "expected_date": node.expected_date,
                        "actual_date": actual_str,
                        "delay_days": delay,
                        "actual_on_time": on_time,
                        "features": features,
                    }
                )

        logger.info("Built %d training records from %d resolved nodes", len(records), len(nodes))
        return records
