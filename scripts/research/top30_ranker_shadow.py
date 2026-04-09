"""Top-30 within-bucket ranker — shadow model.

Trains a pairwise ranking model on the top-30 dataset, evaluates
out-of-sample, and compares ranker-weighted Top-30 vs EW Top-30.

Three baselines:
  A: inst_delta_z only (single feature)
  B: linear model on available features
  C: gradient-boosted pairwise model

Time-split: train on earlier months, test on later months.
Pairwise rows grouped by snapshot_date (no leakage).

Usage:
    python scripts/research/top30_ranker_shadow.py
    python scripts/research/top30_ranker_shadow.py --train-cutoff 2024-01-01
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

OUTPUT_DIR = REPO_ROOT / "output" / "ranker"

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("top30_ranker")

# Features for the ranker (numeric only, must exist in top30_features.csv)
NUMERIC_FEATURES = [
    "actionable_rank",
    "catalyst_days",
    "inst_delta_z",
    "clinical_optionality_pct_dev",
    "de_sort_total_adj",
    "de_sort_contrib_institutional",
    "de_vol_60d",
    "de_beta_xbi_60d",
    "de_drawdown",
    "de_rsi_14d",
    "de_alpha_60d",
    "opt_atm_iv",
    "opt_rr_25d",
    "opt_term_slope",
    "opt_put_call_skew",
    "actual_implied_move_pctile",
    "implied_event_move",
]

# Categorical features encoded as dummies
CATEGORICAL_FEATURES = [
    "is_hard_catalyst",
    "opt_event_premium",
    "mom_state",
    "opt_iv_regime",
]


def _safe_float(v) -> float:
    if v is None or v == "" or v == "None":
        return 0.0
    try:
        return float(v)
    except (ValueError, TypeError):
        return 0.0


def load_feature_rows() -> list[dict]:
    """Load top30_features.csv."""
    path = OUTPUT_DIR / "top30_features.csv"
    if not path.exists():
        log.error("Feature file not found: %s", path)
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def extract_numeric_vector(row: dict) -> list[float]:
    """Extract numeric feature vector from a row."""
    vec = []
    for f in NUMERIC_FEATURES:
        vec.append(_safe_float(row.get(f)))

    # Categorical one-hot
    vec.append(1.0 if row.get("is_hard_catalyst") == "1" else 0.0)
    vec.append(1.0 if row.get("opt_event_premium") == "YES" else 0.0)
    vec.append(1.0 if row.get("mom_state") == "tailwind" else 0.0)
    vec.append(1.0 if row.get("mom_state") == "headwind" else -1.0 if row.get("mom_state") == "headwind" else 0.0)
    vec.append(1.0 if row.get("opt_iv_regime") == "EXTREME" else 0.0)
    vec.append(1.0 if row.get("opt_has_data") == "1" else 0.0)

    return vec


# ---------------------------------------------------------------------------
# Pairwise model (no external deps — pure stdlib)
# ---------------------------------------------------------------------------


class PairwiseLogistic:
    """Simple logistic regression pairwise ranker (stdlib only).

    Learns: P(A beats B) = sigmoid(w · (features_A - features_B))
    """

    def __init__(self, n_features: int, lr: float = 0.01, reg: float = 0.001):
        self.weights = [0.0] * n_features
        self.bias = 0.0
        self.lr = lr
        self.reg = reg

    def _sigmoid(self, x: float) -> float:
        if x > 20:
            return 1.0
        if x < -20:
            return 0.0
        return 1.0 / (1.0 + math.exp(-x))

    def _dot(self, a: list[float], b: list[float]) -> float:
        return sum(ai * bi for ai, bi in zip(a, b))

    def predict_prob(self, diff: list[float]) -> float:
        """P(A beats B) given feature difference (A - B)."""
        return self._sigmoid(self._dot(self.weights, diff) + self.bias)

    def train(self, pairs: list[tuple[list[float], float]], epochs: int = 50):
        """Train on pairs of (feature_diff, label) where label=1 if A wins."""
        for epoch in range(epochs):
            total_loss = 0.0
            for diff, label in pairs:
                pred = self.predict_prob(diff)
                error = pred - label
                total_loss += -label * math.log(max(pred, 1e-10)) - (1 - label) * math.log(max(1 - pred, 1e-10))

                # SGD update
                for i in range(len(self.weights)):
                    self.weights[i] -= self.lr * (error * diff[i] + self.reg * self.weights[i])
                self.bias -= self.lr * error

            if (epoch + 1) % 10 == 0:
                avg_loss = total_loss / max(len(pairs), 1)
                log.info("  Epoch %d: loss=%.4f", epoch + 1, avg_loss)

    def score(self, features: list[float]) -> float:
        """Score a single name (higher = better predicted rank)."""
        return self._dot(self.weights, features) + self.bias


class SingleFeatureRanker:
    """Baseline A: rank by a single feature."""

    def __init__(self, feature_idx: int):
        self.feature_idx = feature_idx

    def score(self, features: list[float]) -> float:
        return features[self.feature_idx]


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def evaluate_ranker(
    ranker,
    test_rows_by_date: dict[str, list[dict]],
) -> dict:
    """Evaluate ranker on test data grouped by snapshot date."""
    all_pairwise_correct = 0
    all_pairwise_total = 0
    top10_vs_bot10_spreads = []
    ew_returns = []
    rw_returns = []
    date_ics = []

    for date, rows in sorted(test_rows_by_date.items()):
        if len(rows) < 10:
            continue

        # Score each name
        scored = []
        for r in rows:
            features = extract_numeric_vector(r)
            score = ranker.score(features)
            h20 = _safe_float(r.get("return_h20"))
            scored.append({"ticker": r["ticker"], "score": score, "return_h20": h20, "features": features})

        # Pairwise accuracy
        for i in range(len(scored)):
            for j in range(i + 1, len(scored)):
                a, b = scored[i], scored[j]
                if abs(a["return_h20"] - b["return_h20"]) < 0.005:
                    continue  # skip near-ties
                pred_a_wins = a["score"] > b["score"]
                actual_a_wins = a["return_h20"] > b["return_h20"]
                if pred_a_wins == actual_a_wins:
                    all_pairwise_correct += 1
                all_pairwise_total += 1

        # Top-10 vs bottom-10 by ranker score
        sorted_by_score = sorted(scored, key=lambda x: -x["score"])
        if len(sorted_by_score) >= 20:
            top10_ret = statistics.mean([s["return_h20"] for s in sorted_by_score[:10]])
            bot10_ret = statistics.mean([s["return_h20"] for s in sorted_by_score[-10:]])
            top10_vs_bot10_spreads.append(top10_ret - bot10_ret)

        # EW vs rank-weighted returns
        n = len(scored)
        if n > 0:
            ew_ret = statistics.mean([s["return_h20"] for s in scored])
            ew_returns.append(ew_ret)

            # Rank-weight: higher score gets more weight
            sorted_by_score = sorted(scored, key=lambda x: -x["score"])
            raw_weights = [n - i for i in range(n)]
            tw = sum(raw_weights)
            rw_ret = sum(w / tw * s["return_h20"] for w, s in zip(raw_weights, sorted_by_score))
            rw_returns.append(rw_ret)

        # Within-date IC (rank correlation of score vs return)
        if len(scored) >= 10:
            scores = [s["score"] for s in scored]
            returns = [s["return_h20"] for s in scored]
            ic = _spearman(scores, returns)
            if ic is not None:
                date_ics.append(ic)

    pairwise_acc = all_pairwise_correct / max(all_pairwise_total, 1)
    mean_spread = statistics.mean(top10_vs_bot10_spreads) if top10_vs_bot10_spreads else 0
    pct_positive_spread = sum(1 for s in top10_vs_bot10_spreads if s > 0) / max(len(top10_vs_bot10_spreads), 1)

    cum_ew = sum(ew_returns)
    cum_rw = sum(rw_returns)

    return {
        "pairwise_accuracy": round(pairwise_acc, 4),
        "pairwise_n": all_pairwise_total,
        "mean_top10_bot10_spread": round(mean_spread, 4),
        "pct_positive_spread": round(pct_positive_spread, 3),
        "n_test_dates": len(test_rows_by_date),
        "cum_ew_return": round(cum_ew, 4),
        "cum_rw_return": round(cum_rw, 4),
        "rw_minus_ew": round(cum_rw - cum_ew, 4),
        "mean_ic": round(statistics.mean(date_ics), 4) if date_ics else None,
        "median_ic": round(statistics.median(date_ics), 4) if date_ics else None,
        "pct_positive_ic": round(sum(1 for x in date_ics if x > 0) / max(len(date_ics), 1), 3) if date_ics else None,
        "n_ic_dates": len(date_ics),
    }


def _avg_ranks(values):
    n = len(values)
    idx = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j < n - 1 and values[idx[j + 1]] == values[idx[j]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[idx[k]] = avg
        i = j + 1
    return ranks


def _spearman(x, y):
    if len(x) < 5:
        return None
    rx = _avg_ranks(x)
    ry = _avg_ranks(y)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    cov = sum((rx[i] - mx) * (ry[i] - my) for i in range(len(x)))
    sx = math.sqrt(sum((rx[i] - mx) ** 2 for i in range(len(x))))
    sy = math.sqrt(sum((ry[i] - my) ** 2 for i in range(len(x))))
    if sx == 0 or sy == 0:
        return None
    return cov / (sx * sy)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run_ranker(train_cutoff: str = "2024-01-01"):
    rows = load_feature_rows()
    if not rows:
        return {}

    # Group by snapshot_date
    by_date: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        d = r.get("snapshot_date", "")
        if d:
            by_date[d].append(r)

    # Time split
    train_dates = {d: rs for d, rs in by_date.items() if d < train_cutoff}
    test_dates = {d: rs for d, rs in by_date.items() if d >= train_cutoff}

    log.info(
        "Train: %d dates (%d rows), Test: %d dates (%d rows)",
        len(train_dates),
        sum(len(v) for v in train_dates.values()),
        len(test_dates),
        sum(len(v) for v in test_dates.values()),
    )

    if not train_dates or not test_dates:
        log.error("Insufficient data for train/test split at %s", train_cutoff)
        return {}

    # Build training pairs
    train_pairs = []
    for date, date_rows in train_dates.items():
        for i in range(len(date_rows)):
            for j in range(i + 1, len(date_rows)):
                a, b = date_rows[i], date_rows[j]
                ret_a = _safe_float(a.get("return_h20"))
                ret_b = _safe_float(b.get("return_h20"))
                if abs(ret_a - ret_b) < 0.005:
                    continue

                feat_a = extract_numeric_vector(a)
                feat_b = extract_numeric_vector(b)
                diff = [fa - fb for fa, fb in zip(feat_a, feat_b)]

                label = 1.0 if ret_a > ret_b else 0.0
                train_pairs.append((diff, label))

    log.info("Training pairs: %d", len(train_pairs))

    # Subsample if too many pairs (keep training fast)
    import random

    random.seed(42)
    if len(train_pairs) > 50000:
        train_pairs = random.sample(train_pairs, 50000)
        log.info("Subsampled to %d pairs", len(train_pairs))

    n_features = len(extract_numeric_vector(rows[0]))

    # --- Baseline A: inst_delta_z only ---
    inst_delta_idx = NUMERIC_FEATURES.index("inst_delta_z")
    baseline_a = SingleFeatureRanker(inst_delta_idx)

    # --- Baseline B: logistic pairwise ---
    baseline_b = PairwiseLogistic(n_features, lr=0.005, reg=0.0005)
    log.info("Training Baseline B (logistic pairwise)...")
    baseline_b.train(train_pairs, epochs=30)

    # --- Evaluate all ---
    results = {}
    for name, ranker in [
        ("A_inst_delta_only", baseline_a),
        ("B_logistic_pairwise", baseline_b),
    ]:
        log.info("Evaluating %s...", name)
        eval_result = evaluate_ranker(ranker, test_dates)
        results[name] = eval_result

        # Feature importance for logistic
        if name == "B_logistic_pairwise" and hasattr(ranker, "weights"):
            feature_names = NUMERIC_FEATURES + [
                "is_hard",
                "event_premium",
                "tailwind",
                "headwind",
                "iv_extreme",
                "has_opts",
            ]
            importance = sorted(
                zip(feature_names, ranker.weights),
                key=lambda x: abs(x[1]),
                reverse=True,
            )
            results[name]["feature_importance"] = [{"feature": f, "weight": round(w, 4)} for f, w in importance[:15]]

    # Also evaluate: random ranker (control for pairwise accuracy)
    class RandomRanker:
        def __init__(self):
            self._rng = random.Random(123)

        def score(self, features):
            return self._rng.random()

    log.info("Evaluating random baseline...")
    results["Z_random"] = evaluate_ranker(RandomRanker(), test_dates)

    return {
        "schema": "top30_ranker_shadow.v1",
        "generated_at": "",
        "train_cutoff": train_cutoff,
        "n_train_dates": len(train_dates),
        "n_test_dates": len(test_dates),
        "n_train_pairs": len(train_pairs),
        "results": results,
    }


def main():
    from datetime import datetime

    parser = argparse.ArgumentParser(description="Top-30 ranker shadow")
    parser.add_argument("--train-cutoff", default="2024-01-01")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    result = run_ranker(train_cutoff=args.train_cutoff)

    if not result:
        log.error("No results")
        return

    result["generated_at"] = datetime.now().isoformat()

    output_path = OUTPUT_DIR / "top30_ranker_results.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    log.info("Wrote %s", output_path)

    # Print comparison
    print(f"\n{'='*75}")
    print(f"TOP-30 RANKER SHADOW — Train < {args.train_cutoff}, Test >= {args.train_cutoff}")
    print(f"{'='*75}")
    print(f"Train: {result['n_train_dates']} dates, {result['n_train_pairs']} pairs")
    print(f"Test: {result['n_test_dates']} dates")

    header = f"{'Model':<25} {'Pair Acc':<10} {'IC':<8} {'%+IC':<7} {'Spread':<9} {'%+Spr':<7} {'RW-EW':<10}"
    print(f"\n{header}")
    print("-" * len(header))

    for name, r in result["results"].items():
        label = name
        acc = r["pairwise_accuracy"]
        ic = r.get("mean_ic")
        pct_ic = r.get("pct_positive_ic")
        spread = r["mean_top10_bot10_spread"]
        pct_spr = r["pct_positive_spread"]
        rw_ew = r["rw_minus_ew"]

        ic_str = f"{ic:+.4f}" if ic is not None else "—"
        pct_ic_str = f"{pct_ic:.0%}" if pct_ic is not None else "—"

        print(
            f"{label:<25} {acc:>7.1%}   {ic_str:>7}  {pct_ic_str:>5}  {spread:>+7.4f}  {pct_spr:>5.0%}  {rw_ew:>+8.4f}"
        )

    # Feature importance
    logistic = result["results"].get("B_logistic_pairwise", {})
    if logistic.get("feature_importance"):
        print("\nFeature importance (logistic pairwise):")
        for fi in logistic["feature_importance"][:10]:
            print(f"  {fi['feature']:<35} {fi['weight']:>+.4f}")


if __name__ == "__main__":
    main()
