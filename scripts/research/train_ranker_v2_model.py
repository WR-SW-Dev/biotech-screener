#!/usr/bin/env python3
"""Train and save a pairwise ranker v2 model for forward shadow use.

Trains on all available research panel data and serializes the model
to production_data/ranker_v2_model.json for use by run_screen.py.

Usage:
    python3 scripts/research/train_ranker_v2_model.py
"""

from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from ranker_v2_pairwise import (
    RankerV2Config,
    config_id,
    generate_pairs,
    get_feature_specs,
    model_to_dict,
    train_pairwise_logistic,
    zscore_cohort_features,
)

PANEL_CSV = PROJECT_ROOT / "output" / "signals" / "research_panel.csv"
MODEL_PATH = PROJECT_ROOT / "production_data" / "ranker_v2_model.json"


def _sf(v, default=float("nan")):
    if v is None or v == "":
        return default
    try:
        f = float(v)
        return f if f == f else default
    except (ValueError, TypeError):
        return default


def main():
    print("Training Ranker v2 pairwise model for forward shadow")
    print("=" * 50)

    # Config: the winning setup
    config = RankerV2Config(
        model_variant="pairwise_logistic",
        feature_set="minimal",
        cohort_top_n=60,
        require_catalyst_window=False,
        forward_horizon="fwd_ret_63d",
        n_epochs=200,
        learning_rate=0.01,
        l2_reg=0.01,
        max_pairs_per_date=400,
        train_window=36,
        recency_halflife_months=24,
    )

    feature_specs = get_feature_specs(config)
    feature_names = [s.name for s in feature_specs]
    n_features = len(feature_specs)
    print(f"  Features ({n_features}): {', '.join(feature_names)}")

    # Load panel
    print(f"  Loading: {PANEL_CSV}")
    snapshots: dict[str, list] = defaultdict(list)
    with open(PANEL_CSV, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            date = row.get("snapshot_date", "")
            if date:
                snapshots[date].append(row)
    print(f"  {len(snapshots)} dates loaded")

    # Filter to dates with forward returns
    sorted_dates = sorted(snapshots.keys())
    train_dates = sorted_dates  # use all available data

    # Apply rolling window
    if config.train_window > 0 and len(train_dates) > config.train_window:
        train_dates = train_dates[-config.train_window :]
    print(f"  Training on {len(train_dates)} dates (window={config.train_window})")

    latest_date = sorted_dates[-1]

    # Build training pairs
    from ranker_v2_pairwise import compute_recency_weight, filter_cohort

    all_pairs = []
    all_features = []
    offset = 0

    for date in train_dates:
        rows = filter_cohort(snapshots[date], config)
        if len(rows) < 5:
            continue

        features = zscore_cohort_features(rows, feature_specs)
        returns = [_sf(r.get(config.forward_horizon)) for r in rows]
        rw = compute_recency_weight(date, latest_date, config.recency_halflife_months)

        pairs = generate_pairs(
            returns,
            max_pairs=config.max_pairs_per_date,
            seed=config.pair_seed + hash(date) % 10000,
            sample_weight=rw,
        )

        from ranker_v2_pairwise import PairLabel

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

    print(f"  {len(all_pairs)} training pairs, {offset} total samples")

    # Train
    print("  Training...", end=" ", flush=True)
    model = train_pairwise_logistic(
        all_features,
        all_pairs,
        n_features,
        lr=config.learning_rate,
        n_epochs=config.n_epochs,
        l2_reg=config.l2_reg,
        feature_names=feature_names,
    )
    print(f"done. Loss={model.train_loss:.4f}, Acc={model.train_accuracy:.3f}")

    # Print weights
    print("\n  Feature weights:")
    for name, w in sorted(zip(feature_names, model.weights), key=lambda x: -abs(x[1])):
        print(f"    {name:30s}  {w:+.4f}")

    # Serialize
    artifact = {
        "type": "ranker_v2_pairwise",
        "version": "1.0.0",
        "trained": datetime.now(timezone.utc).isoformat(),
        "config_id": config_id(config),
        "config": {
            "feature_set": config.feature_set,
            "cohort_top_n": config.cohort_top_n,
            "require_catalyst_window": config.require_catalyst_window,
            "n_epochs": config.n_epochs,
            "max_pairs_per_date": config.max_pairs_per_date,
            "train_window": config.train_window,
            "forward_horizon": config.forward_horizon,
        },
        "train_dates": len(train_dates),
        "train_pairs": len(all_pairs),
        "model": model_to_dict(model),
    }

    MODEL_PATH.write_text(json.dumps(artifact, indent=2))
    print(f"\n  Saved: {MODEL_PATH}")
    print("Done.")


if __name__ == "__main__":
    main()
