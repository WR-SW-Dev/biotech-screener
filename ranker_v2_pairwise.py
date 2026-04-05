"""
Ranker v2 — Pairwise ranking model for shadow research (Spec 051).

Three model variants:
  A. Current bounded-additive ranker (baseline, delegates to ranker_engine.py)
  B. Pointwise direct score model (logistic regression on absolute return)
  C. Pairwise logistic / Bradley-Terry model (primary candidate)

Operates ONLY within a selector-approved cohort (top-K by actionable_rank).
Produces a rank score per name; does NOT touch production output.

Stdlib-only. No external dependencies.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Feature blocks — each maps signal_name → (higher_is_better, categorical, value_map)
# value_map only used for categorical signals.

_CATEGORICAL = True
_NUMERIC = False


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    higher_is_better: bool = True
    categorical: bool = False
    value_map: Tuple[Tuple[str, float], ...] = ()


# Block definitions
BLOCK_INSTITUTIONAL = (
    FeatureSpec("coinvest_score_z"),
    FeatureSpec("inst_delta_z"),
    FeatureSpec("coinvest_conviction"),
    FeatureSpec("coinvest_filing_age_days", higher_is_better=False),
    FeatureSpec("sponsor_tier1_count"),
    FeatureSpec("inst_delta_net"),
)

BLOCK_CLINICAL = (
    FeatureSpec("clinical_score_v2_z"),
    FeatureSpec("clinical_quality_composite"),
    FeatureSpec("endpoint_strength_score"),
    FeatureSpec("design_quality_score"),
    FeatureSpec("binary_quality_score"),
    FeatureSpec("aact_execution_score"),
    FeatureSpec("execution_momentum"),
    FeatureSpec("catalyst_decay_w"),
    FeatureSpec("cat_priority", higher_is_better=False),
    FeatureSpec(
        "catalyst_type_tier",
        categorical=True,
        value_map=(("T1", 1.0), ("T2", 0.8), ("T3", 0.5), ("T4", 0.3), ("T5", 0.2), ("", 0.0)),
    ),
    FeatureSpec(
        "catalyst_family",
        categorical=True,
        value_map=(("REGULATORY", 1.0), ("CLINICAL", 0.6), ("SAFETY", 0.3), ("", 0.0)),
    ),
)

BLOCK_OPTIONS = (
    FeatureSpec("ovf_composite"),
    FeatureSpec("ovf11_score"),
    FeatureSpec("cheap_vol_score"),
    FeatureSpec("opt_rr_25d"),
    FeatureSpec("opt_event_premium"),
    FeatureSpec("opt_term_slope"),
    FeatureSpec(
        "opt_iv_regime",
        categorical=True,
        value_map=(("LOW", 0.8), ("NORMAL", 0.5), ("HIGH", 0.3), ("EXTREME", 0.1), ("", 0.5)),
    ),
)

BLOCK_RISK = (
    FeatureSpec("financial_score"),
    FeatureSpec(
        "severity",
        higher_is_better=False,
        categorical=True,
        value_map=(("NONE", 0.0), ("", 0.0), ("SEV1", 0.33), ("SEV2", 0.67), ("SEV3", 1.0)),
    ),
    FeatureSpec(
        "runway_bucket",
        categorical=True,
        value_map=(("adequate", 1.0), ("short", 0.4), ("critical", 0.0), ("", 0.5)),
    ),
    FeatureSpec("competitive_intensity_z", higher_is_better=False),
    FeatureSpec("de_vol_60d", higher_is_better=False),
    FeatureSpec("de_beta_xbi_60d", higher_is_better=False),
    FeatureSpec("de_drawdown"),
)

ALL_BLOCKS = {
    "institutional": BLOCK_INSTITUTIONAL,
    "clinical": BLOCK_CLINICAL,
    "options": BLOCK_OPTIONS,
    "risk": BLOCK_RISK,
}

# Minimal core feature set (5 signals)
# clinical_score_v2_z removed: confirmed destructive at -0.35pp ablation
# (Spec 055 / ranker ablation study). Institutional + risk carry the signal.
FEATURES_MINIMAL = (
    FeatureSpec("coinvest_score_z"),
    FeatureSpec("inst_delta_z"),
    FeatureSpec("catalyst_decay_w"),
    FeatureSpec("binary_quality_score"),
    FeatureSpec("financial_score"),
)

# 2-feature minimal set (promoted 2026-04-05, scoring audit)
FEATURES_MINIMAL_V2 = (
    FeatureSpec("coinvest_score_z"),
    FeatureSpec("financial_score"),
)


@dataclass(frozen=True)
class RankerV2Config:
    """Configuration for Ranker v2 pairwise research."""

    # Cohort
    cohort_top_n: int = 60  # top-K by actionable_rank
    require_catalyst_window: bool = False  # True for C2/C3 cohorts
    require_eligible: bool = True

    # Feature set: "minimal", "expanded", or "ablation_drop_<block>"
    feature_set: str = "expanded"

    # Label
    forward_horizon: str = "fwd_ret_63d"  # column name for forward return
    label_mode: str = "pairwise_relative"  # "pairwise_relative" | "absolute_positive"

    # Pair sampling
    max_pairs_per_date: int = 200
    pair_seed: int = 42

    # Training
    learning_rate: float = 0.01
    n_epochs: int = 100
    l2_reg: float = 0.01  # L2 regularization strength
    recency_halflife_months: int = 24  # exponential decay half-life
    min_train_dates: int = 12
    train_window: int = 24  # rolling window: use only last N dates for training (0=expanding)

    # Model variant: "pairwise_logistic" | "pointwise_logistic" | "baseline_bounded"
    model_variant: str = "pairwise_logistic"

    # Portfolio
    portfolio_top_n: int = 30


DEFAULT_V2_CONFIG = RankerV2Config()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sf(val: Any, default: float = float("nan")) -> float:
    """Safe float conversion."""
    if val is None:
        return default
    try:
        if isinstance(val, str) and val.strip() == "":
            return default
        v = float(val)
        return v if v == v else default
    except (ValueError, TypeError):
        return default


def _sigmoid(x: float) -> float:
    """Numerically stable sigmoid."""
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    else:
        z = math.exp(x)
        return z / (1.0 + z)


# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------


def get_feature_specs(config: RankerV2Config) -> List[FeatureSpec]:
    """Return the feature list for the given config."""
    if config.feature_set == "minimal_v2":
        return list(FEATURES_MINIMAL_V2)

    if config.feature_set == "minimal":
        return list(FEATURES_MINIMAL)

    if config.feature_set.startswith("ablation_drop_"):
        drop_block = config.feature_set.replace("ablation_drop_", "")
        specs: list[FeatureSpec] = []
        for block_name, block_specs in ALL_BLOCKS.items():
            if block_name != drop_block:
                for s in block_specs:
                    if not s.categorical:
                        specs.append(s)
        return specs

    # "expanded" — all numeric signals from all blocks (skip categoricals for linear model speed)
    specs: list[FeatureSpec] = []
    for block_specs in ALL_BLOCKS.values():
        for s in block_specs:
            if not s.categorical:
                specs.append(s)
    return specs


def _encode_feature(row: Dict[str, Any], spec: FeatureSpec) -> float:
    """Encode a single feature value to numeric. Returns NaN if missing."""
    raw = row.get(spec.name)

    if spec.categorical:
        vmap = dict(spec.value_map)
        if raw is None or (isinstance(raw, str) and raw.strip() == ""):
            val = vmap.get("", float("nan"))
            if val != val:
                return float("nan")
            if not spec.higher_is_better:
                val = 1.0 - val
            return val
        key = str(raw).strip()
        if key in vmap:
            val = vmap[key]
            if not spec.higher_is_better:
                val = 1.0 - val
            return val
        return float("nan")

    fval = _sf(raw)
    if fval != fval:
        return float("nan")
    if not spec.higher_is_better:
        fval = -fval
    return fval


def extract_features(
    row: Dict[str, Any],
    feature_specs: List[FeatureSpec],
) -> List[float]:
    """Extract feature vector from a row. Missing = NaN."""
    return [_encode_feature(row, spec) for spec in feature_specs]


# ---------------------------------------------------------------------------
# Cohort z-scoring (within-cohort normalization)
# ---------------------------------------------------------------------------


def zscore_cohort_features(
    rows: List[Dict[str, Any]],
    feature_specs: List[FeatureSpec],
) -> List[List[float]]:
    """Extract and z-score features within the cohort.

    Returns list of feature vectors (one per row), z-scored per feature.
    Missing values are imputed to 0.0 (cohort mean) after z-scoring.
    """
    n = len(rows)
    if n == 0:
        return []

    # Extract raw
    raw_matrix: list[list[float]] = []
    for row in rows:
        raw_matrix.append(extract_features(row, feature_specs))

    n_features = len(feature_specs)

    # Z-score each feature
    result: list[list[float]] = [[0.0] * n_features for _ in range(n)]

    for j in range(n_features):
        vals = [raw_matrix[i][j] for i in range(n) if raw_matrix[i][j] == raw_matrix[i][j]]
        if len(vals) < 2:
            # Not enough data — leave as 0
            continue
        mean = sum(vals) / len(vals)
        variance = sum((v - mean) ** 2 for v in vals) / len(vals)
        std = math.sqrt(variance) if variance > 0 else 1.0

        for i in range(n):
            v = raw_matrix[i][j]
            if v != v:  # NaN
                result[i][j] = 0.0  # impute to cohort mean
            else:
                z = (v - mean) / std
                result[i][j] = max(-3.0, min(3.0, z))

    return result


# ---------------------------------------------------------------------------
# Pair generation
# ---------------------------------------------------------------------------


@dataclass
class PairLabel:
    """A labeled pair for pairwise training."""

    idx_i: int  # index into cohort
    idx_j: int
    label: float  # 1.0 if i > j, 0.0 if j > i
    weight: float  # sample weight (recency decay)


def generate_pairs(
    cohort_returns: List[float],
    max_pairs: int = 600,
    seed: int = 42,
    sample_weight: float = 1.0,
) -> List[PairLabel]:
    """Generate labeled pairs from forward returns within a cohort.

    Each pair (i, j) is labeled 1 if return_i > return_j, else 0.
    Ties (exact equal returns) are excluded.
    """
    n = len(cohort_returns)
    if n < 2:
        return []

    # Generate all valid pairs
    all_pairs: list[tuple[int, int, float]] = []
    for i in range(n):
        ri = cohort_returns[i]
        if ri != ri:  # NaN
            continue
        for j in range(i + 1, n):
            rj = cohort_returns[j]
            if rj != rj:
                continue
            if abs(ri - rj) < 1e-10:
                continue  # skip ties
            label = 1.0 if ri > rj else 0.0
            all_pairs.append((i, j, label))

    if not all_pairs:
        return []

    # Sample if too many
    if len(all_pairs) > max_pairs:
        rng = random.Random(seed)
        all_pairs = rng.sample(all_pairs, max_pairs)

    return [PairLabel(idx_i=i, idx_j=j, label=lbl, weight=sample_weight) for i, j, lbl in all_pairs]


# ---------------------------------------------------------------------------
# Recency weighting
# ---------------------------------------------------------------------------


def compute_recency_weight(
    snap_date: str,
    latest_date: str,
    halflife_months: int = 24,
) -> float:
    """Exponential decay weight based on distance from latest date.

    Dates are YYYY-MM-DD strings. Returns weight in (0, 1].
    """
    try:
        y1, m1 = int(snap_date[:4]), int(snap_date[5:7])
        y2, m2 = int(latest_date[:4]), int(latest_date[5:7])
        months_diff = (y2 - y1) * 12 + (m2 - m1)
        if months_diff <= 0:
            return 1.0
        decay = math.exp(-math.log(2) * months_diff / halflife_months)
        return max(decay, 0.01)  # floor at 1%
    except (ValueError, IndexError):
        return 1.0


# ---------------------------------------------------------------------------
# Model: Pairwise Logistic (Bradley-Terry)
# ---------------------------------------------------------------------------


@dataclass
class PairwiseLogisticModel:
    """Bradley-Terry pairwise logistic regression.

    For pair (i, j) with feature vectors x_i, x_j:
        P(i > j) = sigmoid(w · (x_i - x_j))

    Trained via SGD with L2 regularization.
    """

    weights: List[float] = field(default_factory=list)
    bias: float = 0.0
    n_features: int = 0
    trained: bool = False
    train_loss: float = 0.0
    train_accuracy: float = 0.0
    feature_names: List[str] = field(default_factory=list)

    def predict_pair(self, x_i: List[float], x_j: List[float]) -> float:
        """Predict P(i outranks j)."""
        if not self.weights:
            return 0.5
        diff = [x_i[k] - x_j[k] for k in range(self.n_features)]
        logit = self.bias + sum(self.weights[k] * diff[k] for k in range(self.n_features))
        return _sigmoid(logit)

    def score_name(
        self,
        name_features: List[float],
        all_features: List[List[float]],
        name_idx: int,
    ) -> float:
        """Score a name by average pairwise win probability vs all others."""
        n = len(all_features)
        if n <= 1:
            return 0.5
        total = 0.0
        count = 0
        for j in range(n):
            if j == name_idx:
                continue
            total += self.predict_pair(name_features, all_features[j])
            count += 1
        return total / count if count > 0 else 0.5


def train_pairwise_logistic(
    feature_matrix: List[List[float]],
    pairs: List[PairLabel],
    n_features: int,
    lr: float = 0.01,
    n_epochs: int = 200,
    l2_reg: float = 0.01,
    feature_names: Optional[List[str]] = None,
) -> PairwiseLogisticModel:
    """Train a pairwise logistic model via batch gradient descent.

    feature_matrix: cohort_size × n_features (already z-scored)
    pairs: list of PairLabel with indices into feature_matrix
    """
    model = PairwiseLogisticModel(
        weights=[0.0] * n_features,
        bias=0.0,
        n_features=n_features,
        feature_names=feature_names or [],
    )

    if not pairs or n_features == 0:
        return model

    n_pairs = len(pairs)

    # Precompute difference vectors and labels/weights for speed
    diff_matrix: list[list[float]] = []
    labels: list[float] = []
    weights: list[float] = []
    for pair in pairs:
        x_i = feature_matrix[pair.idx_i]
        x_j = feature_matrix[pair.idx_j]
        diff_matrix.append([x_i[k] - x_j[k] for k in range(n_features)])
        labels.append(pair.label)
        weights.append(pair.weight)

    w = model.weights
    b = model.bias

    # Batch gradient descent
    for epoch in range(n_epochs):
        total_loss = 0.0
        correct = 0
        grad_w = [0.0] * n_features
        grad_b = 0.0

        for p in range(n_pairs):
            diff = diff_matrix[p]
            logit = b + sum(w[k] * diff[k] for k in range(n_features))
            pred = _sigmoid(logit)

            pred_c = max(1e-7, min(1 - 1e-7, pred))
            y = labels[p]
            sw = weights[p]

            total_loss += sw * -(y * math.log(pred_c) + (1 - y) * math.log(1 - pred_c))
            if (pred > 0.5 and y == 1.0) or (pred < 0.5 and y == 0.0):
                correct += 1

            g = (pred - y) * sw
            for k in range(n_features):
                grad_w[k] += g * diff[k]
            grad_b += g

        # Update with L2 regularization
        inv_n = 1.0 / n_pairs
        for k in range(n_features):
            w[k] -= lr * (grad_w[k] * inv_n + l2_reg * w[k])
        b -= lr * grad_b * inv_n

    model.weights = w
    model.bias = b
    model.trained = True
    model.train_loss = total_loss / n_pairs
    model.train_accuracy = correct / n_pairs
    return model


# ---------------------------------------------------------------------------
# Model: Pointwise Logistic (variant B)
# ---------------------------------------------------------------------------


@dataclass
class PointwiseLogisticModel:
    """Pointwise logistic regression predicting P(positive return).

    P(ret > 0) = sigmoid(w · x + b)
    """

    weights: List[float] = field(default_factory=list)
    bias: float = 0.0
    n_features: int = 0
    trained: bool = False
    train_loss: float = 0.0
    train_accuracy: float = 0.0
    feature_names: List[str] = field(default_factory=list)

    def predict(self, x: List[float]) -> float:
        """Predict P(positive return)."""
        if not self.weights:
            return 0.5
        logit = self.bias + sum(self.weights[k] * x[k] for k in range(self.n_features))
        return _sigmoid(logit)


def train_pointwise_logistic(
    feature_matrix: List[List[float]],
    labels: List[float],
    weights: List[float],
    n_features: int,
    lr: float = 0.01,
    n_epochs: int = 200,
    l2_reg: float = 0.01,
    feature_names: Optional[List[str]] = None,
) -> PointwiseLogisticModel:
    """Train pointwise logistic model via batch gradient descent.

    labels: 1.0 if forward return > 0, else 0.0
    weights: sample weights (recency)
    """
    model = PointwiseLogisticModel(
        weights=[0.0] * n_features,
        bias=0.0,
        n_features=n_features,
        feature_names=feature_names or [],
    )

    valid_idx = [i for i in range(len(labels)) if labels[i] == labels[i]]
    if not valid_idx or n_features == 0:
        return model

    # Precompute valid data
    valid_x = [feature_matrix[i] for i in valid_idx]
    valid_y = [labels[i] for i in valid_idx]
    valid_w = [weights[i] for i in valid_idx]
    n_valid = len(valid_idx)

    w = model.weights
    b = model.bias

    for epoch in range(n_epochs):
        total_loss = 0.0
        correct = 0
        grad_w = [0.0] * n_features
        grad_b = 0.0

        for p in range(n_valid):
            x = valid_x[p]
            y = valid_y[p]
            sw = valid_w[p]

            logit = b + sum(w[k] * x[k] for k in range(n_features))
            pred = _sigmoid(logit)
            pred_c = max(1e-7, min(1 - 1e-7, pred))

            total_loss += sw * -(y * math.log(pred_c) + (1 - y) * math.log(1 - pred_c))
            if (pred > 0.5 and y == 1.0) or (pred < 0.5 and y == 0.0):
                correct += 1

            g = (pred - y) * sw
            for k in range(n_features):
                grad_w[k] += g * x[k]
            grad_b += g

        inv_n = 1.0 / n_valid
        for k in range(n_features):
            w[k] -= lr * (grad_w[k] * inv_n + l2_reg * w[k])
        b -= lr * grad_b * inv_n

    model.weights = w
    model.bias = b
    model.trained = True
    model.train_loss = total_loss / n_valid
    model.train_accuracy = correct / n_valid
    return model


# ---------------------------------------------------------------------------
# Cohort filtering
# ---------------------------------------------------------------------------


def filter_cohort(
    rows: List[Dict[str, Any]],
    config: RankerV2Config,
) -> List[Dict[str, Any]]:
    """Filter rows to the ranker-eligible cohort."""
    cohort = []
    for row in rows:
        # Eligibility check
        if config.require_eligible:
            elig = _sf(row.get("eligible"), 0.0)
            if elig != 1.0:
                continue

        # Top-K by actionable_rank
        rank = _sf(row.get("actionable_rank"), float("nan"))
        if rank != rank or rank > config.cohort_top_n:
            continue

        # Catalyst window gate
        if config.require_catalyst_window:
            ciw = row.get("catalyst_in_window", "")
            if ciw not in ("1", "1.0", 1, 1.0, True):
                # Also check catalyst_days as fallback
                cat_days = _sf(row.get("catalyst_days"), 0.0)
                if cat_days < 1 or cat_days > 120:
                    continue

        cohort.append(row)
    return cohort


# ---------------------------------------------------------------------------
# Full training pipeline
# ---------------------------------------------------------------------------


@dataclass
class TrainResult:
    """Result of training across all snapshot dates."""

    model_variant: str
    config: RankerV2Config
    n_train_dates: int
    n_train_pairs: int  # pairwise only
    n_train_samples: int  # pointwise only
    feature_names: List[str]
    # Model objects (last fold / expanding window)
    pairwise_model: Optional[PairwiseLogisticModel] = None
    pointwise_model: Optional[PointwiseLogisticModel] = None
    # Per-date out-of-sample results
    oos_results: List[Dict[str, Any]] = field(default_factory=list)


def train_and_evaluate(
    snapshots: Dict[str, List[Dict[str, Any]]],
    config: RankerV2Config = DEFAULT_V2_CONFIG,
) -> TrainResult:
    """Train and evaluate Ranker v2 using expanding-window cross-validation.

    For each test date t:
      - Train on all dates < t
      - Score the cohort at date t
      - Evaluate ranking quality and portfolio impact

    Args:
        snapshots: {date_str: [row_dicts]} from research_panel.csv
        config: RankerV2Config

    Returns:
        TrainResult with per-date OOS results
    """
    sorted_dates = sorted(snapshots.keys())
    feature_specs = get_feature_specs(config)
    feature_names = [s.name for s in feature_specs]
    n_features = len(feature_specs)

    result = TrainResult(
        model_variant=config.model_variant,
        config=config,
        n_train_dates=0,
        n_train_pairs=0,
        n_train_samples=0,
        feature_names=feature_names,
    )

    if len(sorted_dates) < config.min_train_dates + 1:
        return result

    latest_date = sorted_dates[-1]

    for test_idx in range(config.min_train_dates, len(sorted_dates)):
        test_date = sorted_dates[test_idx]
        all_train = sorted_dates[:test_idx]
        # Rolling window: use only last N dates
        if config.train_window > 0 and len(all_train) > config.train_window:
            train_dates = all_train[-config.train_window :]
        else:
            train_dates = all_train

        # --- Filter test cohort ---
        test_rows = filter_cohort(snapshots[test_date], config)
        if len(test_rows) < 5:
            continue

        # --- Z-score test cohort features ---
        test_features = zscore_cohort_features(test_rows, feature_specs)

        # --- Get forward returns for test date ---
        test_returns = [_sf(r.get(config.forward_horizon)) for r in test_rows]

        if config.model_variant == "baseline_bounded":
            # Just evaluate the existing actionable_rank ordering
            oos = _evaluate_baseline(test_rows, test_returns, config)
            oos["date"] = test_date
            result.oos_results.append(oos)
            continue

        # --- Build training data ---
        if config.model_variant == "pairwise_logistic":
            all_pairs, all_features_flat, pair_feature_map = _build_pairwise_train_data(
                snapshots,
                train_dates,
                feature_specs,
                config,
                latest_date,
            )
            if len(all_pairs) < 10:
                continue

            model = train_pairwise_logistic(
                all_features_flat,
                all_pairs,
                n_features,
                lr=config.learning_rate,
                n_epochs=config.n_epochs,
                l2_reg=config.l2_reg,
                feature_names=feature_names,
            )
            result.pairwise_model = model
            result.n_train_pairs += len(all_pairs)
            result.n_train_dates = len(train_dates)

            # Score test cohort
            scores = []
            for i in range(len(test_rows)):
                s = model.score_name(test_features[i], test_features, i)
                scores.append(s)

            oos = _evaluate_scores(test_rows, scores, test_returns, test_features, model, config)
            oos["date"] = test_date
            oos["train_dates"] = len(train_dates)
            oos["train_pairs"] = len(all_pairs)
            oos["train_loss"] = model.train_loss
            oos["train_accuracy"] = model.train_accuracy
            result.oos_results.append(oos)

        elif config.model_variant == "pointwise_logistic":
            all_features_flat, all_labels, all_weights = _build_pointwise_train_data(
                snapshots,
                train_dates,
                feature_specs,
                config,
                latest_date,
            )
            if len(all_labels) < 10:
                continue

            model = train_pointwise_logistic(
                all_features_flat,
                all_labels,
                all_weights,
                n_features,
                lr=config.learning_rate,
                n_epochs=config.n_epochs,
                l2_reg=config.l2_reg,
                feature_names=feature_names,
            )
            result.pointwise_model = model
            result.n_train_samples += len(all_labels)
            result.n_train_dates = len(train_dates)

            # Score test cohort
            scores = [model.predict(test_features[i]) for i in range(len(test_rows))]

            oos = _evaluate_scores(test_rows, scores, test_returns, test_features, None, config)
            oos["date"] = test_date
            oos["train_dates"] = len(train_dates)
            oos["train_samples"] = len(all_labels)
            oos["train_loss"] = model.train_loss
            oos["train_accuracy"] = model.train_accuracy
            result.oos_results.append(oos)

    return result


# ---------------------------------------------------------------------------
# Training data builders
# ---------------------------------------------------------------------------


def _build_pairwise_train_data(
    snapshots: Dict[str, List[Dict[str, Any]]],
    train_dates: List[str],
    feature_specs: List[FeatureSpec],
    config: RankerV2Config,
    latest_date: str,
) -> Tuple[List[PairLabel], List[List[float]], Dict]:
    """Build pairwise training data across all train dates.

    Returns:
        all_pairs: PairLabel list with indices into all_features_flat
        all_features_flat: feature matrix (all cohort names across all dates)
        pair_feature_map: metadata
    """
    all_pairs: list[PairLabel] = []
    all_features: list[list[float]] = []
    offset = 0

    for date in train_dates:
        rows = filter_cohort(snapshots[date], config)
        if len(rows) < 5:
            continue

        features = zscore_cohort_features(rows, feature_specs)
        returns = [_sf(r.get(config.forward_horizon)) for r in rows]

        # Recency weight
        rw = compute_recency_weight(date, latest_date, config.recency_halflife_months)

        # Generate pairs
        pairs = generate_pairs(
            returns,
            max_pairs=config.max_pairs_per_date,
            seed=config.pair_seed + hash(date) % 10000,
            sample_weight=rw,
        )

        # Remap pair indices to global offset
        for p in pairs:
            all_pairs.append(
                PairLabel(
                    idx_i=p.idx_i + offset,
                    idx_j=p.idx_j + offset,
                    label=p.label,
                    weight=p.weight,
                )
            )

        all_features.extend(features)
        offset += len(rows)

    return all_pairs, all_features, {}


def _build_pointwise_train_data(
    snapshots: Dict[str, List[Dict[str, Any]]],
    train_dates: List[str],
    feature_specs: List[FeatureSpec],
    config: RankerV2Config,
    latest_date: str,
) -> Tuple[List[List[float]], List[float], List[float]]:
    """Build pointwise training data: predict sign of forward return."""
    all_features: list[list[float]] = []
    all_labels: list[float] = []
    all_weights: list[float] = []

    for date in train_dates:
        rows = filter_cohort(snapshots[date], config)
        if len(rows) < 5:
            continue

        features = zscore_cohort_features(rows, feature_specs)
        rw = compute_recency_weight(date, latest_date, config.recency_halflife_months)

        for i, row in enumerate(rows):
            ret = _sf(row.get(config.forward_horizon))
            if ret != ret:
                continue
            all_features.append(features[i])
            all_labels.append(1.0 if ret > 0 else 0.0)
            all_weights.append(rw)

    return all_features, all_labels, all_weights


# ---------------------------------------------------------------------------
# Evaluation helpers
# ---------------------------------------------------------------------------


def _evaluate_baseline(
    test_rows: List[Dict[str, Any]],
    test_returns: List[float],
    config: RankerV2Config,
) -> Dict[str, Any]:
    """Evaluate baseline (current actionable_rank ordering)."""
    # Sort by actionable_rank (already ordered in test_rows)
    indexed = list(range(len(test_rows)))
    indexed.sort(key=lambda i: _sf(test_rows[i].get("actionable_rank"), 999))

    top_n = min(config.portfolio_top_n, len(indexed))
    top_indices = indexed[:top_n]

    # EW portfolio return
    top_rets = [test_returns[i] for i in top_indices if test_returns[i] == test_returns[i]]
    ew_ret = sum(top_rets) / len(top_rets) if top_rets else float("nan")

    # XBI excess
    xbi_col = config.forward_horizon.replace("fwd_ret_", "fwd_excess_xbi_")
    top_xbi = [_sf(test_rows[i].get(xbi_col)) for i in top_indices]
    top_xbi = [x for x in top_xbi if x == x]
    ew_excess_xbi = sum(top_xbi) / len(top_xbi) if top_xbi else float("nan")

    # Pairwise accuracy (rank order vs returns)
    pw_correct = 0
    pw_total = 0
    for a_pos in range(len(top_indices)):
        for b_pos in range(a_pos + 1, len(top_indices)):
            i, j = top_indices[a_pos], top_indices[b_pos]
            ri, rj = test_returns[i], test_returns[j]
            if ri != ri or rj != rj or abs(ri - rj) < 1e-10:
                continue
            pw_total += 1
            if ri > rj:  # higher-ranked (lower pos) should have higher return
                pw_correct += 1
    pw_acc = pw_correct / pw_total if pw_total > 0 else float("nan")

    # Spearman IC
    valid = [(i, test_returns[i]) for i in range(len(test_rows)) if test_returns[i] == test_returns[i]]
    ranks = [_sf(test_rows[i].get("actionable_rank"), 999) for i, _ in valid]
    rets = [r for _, r in valid]
    ic = _spearman([-r for r in ranks], rets)  # negate rank so higher = better

    # Regime
    regime = None
    for row in test_rows:
        r = row.get("regime_63d")
        if r:
            regime = r
            break

    # Top-30 roster
    top_tickers = [test_rows[i].get("ticker", "") for i in top_indices]

    return {
        "model": "baseline_bounded",
        "cohort_size": len(test_rows),
        "portfolio_size": len(top_rets),
        "ew_ret": _round(ew_ret),
        "ew_excess_xbi": _round(ew_excess_xbi),
        "pairwise_accuracy": _round(pw_acc),
        "rank_ic": _round(ic),
        "regime": regime,
        "top_tickers": top_tickers,
    }


def _evaluate_scores(
    test_rows: List[Dict[str, Any]],
    scores: List[float],
    test_returns: List[float],
    test_features: List[List[float]],
    pairwise_model: Optional[PairwiseLogisticModel],
    config: RankerV2Config,
) -> Dict[str, Any]:
    """Evaluate model scores against forward returns."""
    n = len(test_rows)

    # Sort by score descending
    indexed = sorted(range(n), key=lambda i: -scores[i])
    top_n = min(config.portfolio_top_n, n)
    top_indices = indexed[:top_n]

    # EW portfolio return
    top_rets = [test_returns[i] for i in top_indices if test_returns[i] == test_returns[i]]
    ew_ret = sum(top_rets) / len(top_rets) if top_rets else float("nan")

    # XBI excess
    xbi_col = config.forward_horizon.replace("fwd_ret_", "fwd_excess_xbi_")
    top_xbi = [_sf(test_rows[i].get(xbi_col)) for i in top_indices]
    top_xbi = [x for x in top_xbi if x == x]
    ew_excess_xbi = sum(top_xbi) / len(top_xbi) if top_xbi else float("nan")

    # Pairwise accuracy within top-K
    pw_correct = 0
    pw_total = 0
    for a_pos in range(len(top_indices)):
        for b_pos in range(a_pos + 1, len(top_indices)):
            i, j = top_indices[a_pos], top_indices[b_pos]
            ri, rj = test_returns[i], test_returns[j]
            if ri != ri or rj != rj or abs(ri - rj) < 1e-10:
                continue
            pw_total += 1
            if ri > rj:
                pw_correct += 1
    pw_acc = pw_correct / pw_total if pw_total > 0 else float("nan")

    # Pairwise accuracy across full cohort
    pw_full_correct = 0
    pw_full_total = 0
    for i in range(n):
        for j in range(i + 1, n):
            ri, rj = test_returns[i], test_returns[j]
            si, sj = scores[i], scores[j]
            if ri != ri or rj != rj or abs(ri - rj) < 1e-10:
                continue
            pw_full_total += 1
            if (si > sj and ri > rj) or (si < sj and ri < rj):
                pw_full_correct += 1
    pw_full_acc = pw_full_correct / pw_full_total if pw_full_total > 0 else float("nan")

    # Spearman IC (score vs return)
    valid_scores = []
    valid_rets = []
    for i in range(n):
        if test_returns[i] == test_returns[i]:
            valid_scores.append(scores[i])
            valid_rets.append(test_returns[i])
    ic = _spearman(valid_scores, valid_rets)

    # Quintile spread
    q_spread = float("nan")
    if len(indexed) >= 10:
        q_size = max(1, len(indexed) // 5)
        top_q = [
            test_returns[indexed[i]] for i in range(q_size) if test_returns[indexed[i]] == test_returns[indexed[i]]
        ]
        bot_q = [
            test_returns[indexed[-i - 1]]
            for i in range(q_size)
            if test_returns[indexed[-i - 1]] == test_returns[indexed[-i - 1]]
        ]
        if top_q and bot_q:
            q_spread = sum(top_q) / len(top_q) - sum(bot_q) / len(bot_q)

    # Cutoff zone swaps (ranks 20-50 relative to baseline)
    baseline_order = sorted(range(n), key=lambda i: _sf(test_rows[i].get("actionable_rank"), 999))
    model_order = indexed
    cutoff_swaps = 0
    cutoff_improvements = 0
    for pos in range(min(20, n), min(50, n)):
        if pos < len(baseline_order) and pos < len(model_order):
            if baseline_order[pos] != model_order[pos]:
                cutoff_swaps += 1
                # Did the swap improve? (model pick has higher return)
                br = test_returns[baseline_order[pos]]
                mr = test_returns[model_order[pos]]
                if br == br and mr == mr and mr > br:
                    cutoff_improvements += 1

    # Regime
    regime = None
    for row in test_rows:
        r = row.get("regime_63d")
        if r:
            regime = r
            break

    # Top-30 roster
    top_tickers = [test_rows[i].get("ticker", "") for i in top_indices]

    # Turnover placeholder (computed across dates in harness)

    return {
        "model": config.model_variant,
        "cohort_size": n,
        "portfolio_size": len(top_rets),
        "ew_ret": _round(ew_ret),
        "ew_excess_xbi": _round(ew_excess_xbi),
        "pairwise_accuracy_top": _round(pw_acc),
        "pairwise_accuracy_full": _round(pw_full_acc),
        "rank_ic": _round(ic),
        "quintile_spread": _round(q_spread),
        "cutoff_swaps": cutoff_swaps,
        "cutoff_improvements": cutoff_improvements,
        "regime": regime,
        "top_tickers": top_tickers,
    }


def _spearman(x: List[float], y: List[float]) -> float:
    """Spearman rank correlation."""
    n = len(x)
    if n < 5:
        return float("nan")

    def _rank(vals):
        indexed = sorted(range(n), key=lambda i: vals[i])
        ranks = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j < n - 1 and vals[indexed[j + 1]] == vals[indexed[j]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                ranks[indexed[k]] = avg
            i = j + 1
        return ranks

    rx, ry = _rank(x), _rank(y)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    dx = sum((rx[i] - mx) ** 2 for i in range(n)) ** 0.5
    dy = sum((ry[i] - my) ** 2 for i in range(n)) ** 0.5
    if dx < 1e-9 or dy < 1e-9:
        return float("nan")
    return num / (dx * dy)


def _round(v: float, d: int = 6) -> float:
    if v != v:
        return v
    return round(v, d)


# ---------------------------------------------------------------------------
# Convenience: score a single snapshot (for shadow production use)
# ---------------------------------------------------------------------------


def score_snapshot(
    rows: List[Dict[str, Any]],
    model: PairwiseLogisticModel,
    config: RankerV2Config = DEFAULT_V2_CONFIG,
) -> List[Dict[str, Any]]:
    """Score a live snapshot with a trained pairwise model.

    Returns list of {ticker, ranker_v2_score, ranker_v2_rank} for cohort names.
    Non-cohort names get score=None.
    """
    feature_specs = get_feature_specs(config)
    cohort = filter_cohort(rows, config)

    if not cohort or not model.trained:
        return [{"ticker": r.get("ticker", ""), "ranker_v2_score": None, "ranker_v2_rank": None} for r in rows]

    # Z-score within cohort
    features = zscore_cohort_features(cohort, feature_specs)

    # Score each name
    cohort_scores = {}
    for i, row in enumerate(cohort):
        ticker = row.get("ticker", "")
        cohort_scores[ticker] = model.score_name(features[i], features, i)

    # Rank within cohort
    ranked = sorted(cohort_scores.items(), key=lambda x: -x[1])
    cohort_ranks = {ticker: rank + 1 for rank, (ticker, _) in enumerate(ranked)}

    results = []
    for row in rows:
        ticker = row.get("ticker", "")
        if ticker in cohort_scores:
            results.append(
                {
                    "ticker": ticker,
                    "ranker_v2_score": round(cohort_scores[ticker], 6),
                    "ranker_v2_rank": cohort_ranks[ticker],
                }
            )
        else:
            results.append({"ticker": ticker, "ranker_v2_score": None, "ranker_v2_rank": None})

    return results


# ---------------------------------------------------------------------------
# Model serialization
# ---------------------------------------------------------------------------


def model_to_dict(model: PairwiseLogisticModel) -> Dict[str, Any]:
    """Serialize a pairwise model to a dict."""
    return {
        "type": "pairwise_logistic",
        "weights": model.weights,
        "bias": model.bias,
        "n_features": model.n_features,
        "feature_names": model.feature_names,
        "trained": model.trained,
        "train_loss": model.train_loss,
        "train_accuracy": model.train_accuracy,
    }


def model_from_dict(d: Dict[str, Any]) -> PairwiseLogisticModel:
    """Deserialize a pairwise model from a dict."""
    return PairwiseLogisticModel(
        weights=d["weights"],
        bias=d["bias"],
        n_features=d["n_features"],
        feature_names=d.get("feature_names", []),
        trained=d.get("trained", True),
        train_loss=d.get("train_loss", 0.0),
        train_accuracy=d.get("train_accuracy", 0.0),
    )


def config_id(config: RankerV2Config) -> str:
    """Deterministic hash of config for provenance."""
    d = {
        "model_variant": config.model_variant,
        "feature_set": config.feature_set,
        "cohort_top_n": config.cohort_top_n,
        "require_catalyst_window": config.require_catalyst_window,
        "forward_horizon": config.forward_horizon,
        "portfolio_top_n": config.portfolio_top_n,
        "l2_reg": config.l2_reg,
        "n_epochs": config.n_epochs,
        "learning_rate": config.learning_rate,
        "recency_halflife_months": config.recency_halflife_months,
    }
    raw = json.dumps(d, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:8]
