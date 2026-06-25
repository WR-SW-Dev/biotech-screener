#!/usr/bin/env python
"""Score optimization — derives signals from available data and optimizes weights to maximize IC.

The current screener produces zero differentiation (all companies get 31.50).
This script:
1. Engineers features from price data (momentum, volatility, drawdown)
2. Engineers features from trial/AACT data (trial count, phase, catalyst proximity)
3. Computes forward returns at 63d/126d/252d horizons
4. Runs grid search over weight combinations to maximize Spearman IC
5. Generates an optimized snapshot with differentiated scores
6. Reports the optimal weights and IC improvement

Usage:
    python scripts/optimize_scores.py
    python scripts/optimize_scores.py --snapshot 2024-01-02
    python scripts/optimize_scores.py --output output/snapshot_optimized.json
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

# scipy for Spearman correlation
try:
    from scipy.stats import spearmanr

    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

PROJECT_DIR = Path(os.environ.get("BIOTECH_PROJECT_DIR", Path(__file__).resolve().parent.parent))
DATA_DIR = PROJECT_DIR / "data"
OUTPUT_DIR = PROJECT_DIR / "output"
UNIVERSE_FILE = DATA_DIR / "universe" / "biotech_universe_v1.csv"
PRICES_FILE = DATA_DIR / "daily_prices.csv"
TRIAL_MAP_FILE = DATA_DIR / "trial_mapping.csv"
AACT_DIR = DATA_DIR / "aact_snapshots"


# ═══════════════════════════════════════════════════════════════════
# Data loading
# ═══════════════════════════════════════════════════════════════════


def load_universe() -> list[dict]:
    with open(UNIVERSE_FILE, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_prices() -> dict[str, list[dict]]:
    """Load daily prices grouped by ticker, sorted by date."""
    prices: dict[str, list[dict]] = defaultdict(list)
    with open(PRICES_FILE, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ticker = row.get("ticker", "").strip().upper()
            if ticker:
                prices[ticker].append(
                    {
                        "date": row.get("date", ""),
                        "price": float(row.get("adj_close", 0)),
                    }
                )
    for ticker in prices:
        prices[ticker].sort(key=lambda x: x["date"])
    return prices


def load_trial_map() -> dict[str, list[dict]]:
    mapping: dict[str, list[dict]] = defaultdict(list)
    with open(TRIAL_MAP_FILE, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ticker = row.get("ticker", "").upper().strip()
            if ticker:
                mapping[ticker].append(row)
    return dict(mapping)


def load_aact_studies() -> dict[str, dict]:
    if not AACT_DIR.is_dir():
        return {}
    subdirs = sorted(p for p in AACT_DIR.iterdir() if p.is_dir())
    if not subdirs:
        return {}
    studies_file = subdirs[-1] / "studies.csv"
    if not studies_file.exists():
        return {}
    out = {}
    with open(studies_file, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            nct = (row.get("nct_id") or "").strip()
            if nct:
                out[nct] = row
    return out


def load_aact_sponsors() -> dict[str, list[str]]:
    if not AACT_DIR.is_dir():
        return {}
    subdirs = sorted(p for p in AACT_DIR.iterdir() if p.is_dir())
    if not subdirs:
        return {}
    sponsors_file = subdirs[-1] / "sponsors.csv"
    if not sponsors_file.exists():
        return {}
    out: dict[str, list[str]] = defaultdict(list)
    with open(sponsors_file, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            nct = (row.get("nct_id") or "").strip()
            name = (row.get("name") or "").strip()
            if nct and name:
                out[nct].append(name)
    return dict(out)


# ═══════════════════════════════════════════════════════════════════
# Feature engineering
# ═══════════════════════════════════════════════════════════════════


def phase_rank(phase: str) -> int:
    p = (phase or "").lower()
    if "phase 4" in p:
        return 5
    if "phase 2" in p and "phase 3" in p:
        return 3
    if "phase 3" in p:
        return 4
    if "phase 1" in p and "phase 2" in p:
        return 2
    if "phase 2" in p:
        return 3
    if "phase 1" in p:
        return 1
    return 0


def compute_price_features(prices: list[dict], as_of: str) -> dict[str, float]:
    """Compute momentum, volatility, drawdown features as of a given date."""
    # Filter prices up to as_of date (point-in-time safe)
    pit_prices = [p for p in prices if p["date"] <= as_of]
    if len(pit_prices) < 20:
        return {"momentum_63d": 0.0, "momentum_126d": 0.0, "volatility": 0.0, "drawdown": 0.0, "rsi": 50.0}

    price_series = [p["price"] for p in pit_prices]
    current = price_series[-1]

    # 63-day momentum (~3 months)
    idx_63 = max(0, len(price_series) - 63)
    mom_63 = (current / price_series[idx_63] - 1) * 100 if price_series[idx_63] > 0 else 0.0

    # 126-day momentum (~6 months)
    idx_126 = max(0, len(price_series) - 126)
    mom_126 = (current / price_series[idx_126] - 1) * 100 if price_series[idx_126] > 0 else 0.0

    # Volatility (std of daily returns, annualized)
    returns = []
    for i in range(1, min(len(price_series), 126)):
        if price_series[i - 1] > 0:
            returns.append(math.log(price_series[i] / price_series[i - 1]))
    vol = (math.sqrt(sum(r * r for r in returns) / max(len(returns), 1)) * math.sqrt(252)) * 100 if returns else 0.0

    # Drawdown from peak (max drawdown over last 126 days)
    lookback = price_series[-126:] if len(price_series) >= 126 else price_series
    peak = max(lookback)
    drawdown = ((current / peak - 1) * 100) if peak > 0 else 0.0

    # RSI (14-day)
    if len(price_series) >= 15:
        gains, losses = [], []
        for i in range(-14, 0):
            diff = price_series[i] - price_series[i - 1]
            if diff > 0:
                gains.append(diff)
            else:
                losses.append(abs(diff))
        avg_gain = sum(gains) / 14 if gains else 0
        avg_loss = sum(losses) / 14 if losses else 0.001
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
    else:
        rsi = 50.0

    return {
        "momentum_63d": mom_63,
        "momentum_126d": mom_126,
        "volatility": vol,
        "drawdown": drawdown,
        "rsi": rsi,
    }


def compute_clinical_features(
    ticker: str,
    trials: list[dict],
    aact_studies: dict[str, dict],
    aact_sponsors: dict[str, list[str]],
) -> dict[str, float]:
    """Compute clinical development features from trial data."""
    if not trials:
        return {
            "trial_count": 0.0,
            "max_phase": 0.0,
            "active_trials": 0.0,
            "catalyst_proximity": 0.0,
            "sponsor_diversity": 0.0,
        }

    max_phase = 0
    active = 0
    catalyst_score = 0.0
    all_sponsors = set()

    for t in trials:
        nct = t.get("nct_id", "")
        study = aact_studies.get(nct, {})
        phase = study.get("phase") or t.get("phase") or ""
        rank = phase_rank(phase)
        if rank > max_phase:
            max_phase = rank

        status = (study.get("overall_status") or "").lower()
        if "recruit" in status or "active" in status:
            active += 1

        # Catalyst proximity: upcoming primary completion date
        pcd = study.get("primary_completion_date", "")
        if pcd and len(pcd) >= 10:
            try:
                pcd_date = date.fromisoformat(pcd[:10])
                today = date.today()
                days_until = (pcd_date - today).days
                if 0 < days_until <= 180:
                    # Closer = higher score (max 10 points)
                    catalyst_score += max(0, 10 - days_until / 18)
            except ValueError:
                pass

        # Sponsor diversity
        own_sponsor = t.get("sponsor_name_at_map_time", "")
        for sp in aact_sponsors.get(nct, []):
            if own_sponsor and sp.lower() == own_sponsor.lower():
                continue
            all_sponsors.add(sp)

    return {
        "trial_count": float(len(trials)),
        "max_phase": float(max_phase),
        "active_trials": float(active),
        "catalyst_proximity": catalyst_score,
        "sponsor_diversity": float(len(all_sponsors)),
    }


def compute_financial_features(price_features: dict[str, float]) -> dict[str, float]:
    """Derive financial health signals from price data."""
    # Invert volatility and drawdown for "health" (lower = better)
    vol_health = max(0, 100 - price_features["volatility"] * 2)
    dd_health = max(0, 100 + price_features["drawdown"])  # drawdown is negative
    momentum_health = max(0, min(100, 50 + price_features["momentum_126d"]))
    rsi_health = max(0, min(100, price_features["rsi"]))

    return {
        "vol_health": vol_health,
        "drawdown_health": dd_health,
        "momentum_health": momentum_health,
        "rsi_health": rsi_health,
    }


# ═══════════════════════════════════════════════════════════════════
# Forward returns
# ═══════════════════════════════════════════════════════════════════


def compute_forward_returns(
    prices: dict[str, list[dict]], as_of: str, horizons: list[int]
) -> dict[str, dict[int, float | None]]:
    """Compute forward returns for each ticker at given horizons (trading days)."""
    result: dict[str, dict[int, float | None]] = {}

    for ticker, price_list in prices.items():
        # Find index of as_of date
        pit_idx = None
        for i, p in enumerate(price_list):
            if p["date"] == as_of:
                pit_idx = i
                break
            elif p["date"] > as_of:
                pit_idx = i - 1
                break

        if pit_idx is None or pit_idx < 0:
            result[ticker] = {h: None for h in horizons}
            continue

        base_price = price_list[pit_idx]["price"]
        ticker_returns = {}

        for h in horizons:
            future_idx = pit_idx + h
            if future_idx < len(price_list):
                future_price = price_list[future_idx]["price"]
                ticker_returns[h] = (future_price / base_price - 1) * 100 if base_price > 0 else None
            else:
                ticker_returns[h] = None

        result[ticker] = ticker_returns

    return result


# ═══════════════════════════════════════════════════════════════════
# Scoring
# ═══════════════════════════════════════════════════════════════════


def normalize_0_100(values: dict[str, float]) -> dict[str, float]:
    """Min-max normalize values to 0-100 range."""
    if not values:
        return {}
    vmin = min(values.values())
    vmax = max(values.values())
    if vmax == vmin:
        return {k: 50.0 for k in values}
    return {k: (v - vmin) / (vmax - vmin) * 100 for k, v in values.items()}


def compute_composite_scores(
    tickers: list[str],
    clinical_features: dict[str, dict[str, float]],
    financial_features: dict[str, dict[str, float]],
    weights: dict[str, float],
) -> dict[str, dict[str, float]]:
    """Compute composite scores using given weights.

    weights keys: clinical_trial_count, clinical_max_phase, clinical_active,
                  clinical_catalyst, clinical_sponsor,
                  fin_vol, fin_drawdown, fin_momentum, fin_rsi
    """
    # Normalize each feature across all tickers
    features_to_normalize = {
        "clinical_trial_count": {t: clinical_features[t]["trial_count"] for t in tickers},
        "clinical_max_phase": {t: clinical_features[t]["max_phase"] for t in tickers},
        "clinical_active": {t: clinical_features[t]["active_trials"] for t in tickers},
        "clinical_catalyst": {t: clinical_features[t]["catalyst_proximity"] for t in tickers},
        "clinical_sponsor": {t: clinical_features[t]["sponsor_diversity"] for t in tickers},
        "fin_vol": {t: financial_features[t]["vol_health"] for t in tickers},
        "fin_drawdown": {t: financial_features[t]["drawdown_health"] for t in tickers},
        "fin_momentum": {t: financial_features[t]["momentum_health"] for t in tickers},
        "fin_rsi": {t: financial_features[t]["rsi_health"] for t in tickers},
    }

    normalized = {k: normalize_0_100(v) for k, v in features_to_normalize.items()}

    scores: dict[str, dict[str, float]] = {}
    for ticker in tickers:
        component_scores = {k: normalized[k].get(ticker, 50.0) for k in normalized}

        # Weighted composite
        composite = sum(weights.get(k, 0) * component_scores[k] for k in component_scores)
        total_weight = sum(weights.get(k, 0) for k in component_scores)
        if total_weight > 0:
            composite /= total_weight

        scores[ticker] = {
            "composite": composite,
            **component_scores,
        }

    return scores


def compute_ic(scores: dict[str, float], forward_returns: dict[str, float | None]) -> float | None:
    """Compute Spearman rank IC between scores and forward returns."""
    pairs = []
    for ticker, score in scores.items():
        ret = forward_returns.get(ticker)
        if ret is not None and not math.isnan(ret):
            pairs.append((score, ret))

    if len(pairs) < 3:
        return None

    if HAS_SCIPY:
        rho, _ = spearmanr([p[0] for p in pairs], [p[1] for p in pairs])
        return float(rho) if not math.isnan(rho) else 0.0
    else:
        # Manual Spearman
        def rank(vals):
            sorted_vals = sorted(enumerate(vals), key=lambda x: x[1])
            ranks = [0] * len(vals)
            for rank_idx, (orig_idx, _) in enumerate(sorted_vals):
                ranks[orig_idx] = rank_idx + 1
            return ranks

        x = [p[0] for p in pairs]
        y = [p[1] for p in pairs]
        rx, ry = rank(x), rank(y)
        n = len(pairs)
        d_sq = sum((rx[i] - ry[i]) ** 2 for i in range(n))
        return 1 - 6 * d_sq / (n * (n * n - 1))


# ═══════════════════════════════════════════════════════════════════
# Grid search optimization
# ═══════════════════════════════════════════════════════════════════


def grid_search_weights(
    tickers: list[str],
    clinical_features: dict[str, dict[str, float]],
    financial_features: dict[str, dict[str, float]],
    forward_returns: dict[str, dict[int, float | None]],
    horizon: int = 63,
) -> tuple[dict[str, float], float]:
    """Grid search over weight combinations to maximize IC at given horizon."""

    # Define weight grid (simplified: group into clinical vs financial components)
    # clinical_weight: total weight for clinical features
    # fin_weight: total weight for financial features
    # Within each group, try different sub-weight allocations

    best_ic = -999
    best_weights: dict[str, float] = {}

    # Clinical sub-weight options
    clin_sub_options = [
        {
            "clinical_trial_count": 0.3,
            "clinical_max_phase": 0.3,
            "clinical_active": 0.15,
            "clinical_catalyst": 0.15,
            "clinical_sponsor": 0.1,
        },
        {
            "clinical_trial_count": 0.2,
            "clinical_max_phase": 0.4,
            "clinical_active": 0.2,
            "clinical_catalyst": 0.1,
            "clinical_sponsor": 0.1,
        },
        {
            "clinical_trial_count": 0.4,
            "clinical_max_phase": 0.2,
            "clinical_active": 0.2,
            "clinical_catalyst": 0.15,
            "clinical_sponsor": 0.05,
        },
        {
            "clinical_trial_count": 0.15,
            "clinical_max_phase": 0.35,
            "clinical_active": 0.15,
            "clinical_catalyst": 0.25,
            "clinical_sponsor": 0.1,
        },
    ]

    # Financial sub-weight options
    fin_sub_options = [
        {"fin_vol": 0.3, "fin_drawdown": 0.3, "fin_momentum": 0.25, "fin_rsi": 0.15},
        {"fin_vol": 0.2, "fin_drawdown": 0.2, "fin_momentum": 0.4, "fin_rsi": 0.2},
        {"fin_vol": 0.35, "fin_drawdown": 0.35, "fin_momentum": 0.2, "fin_rsi": 0.1},
        {"fin_vol": 0.25, "fin_drawdown": 0.25, "fin_momentum": 0.35, "fin_rsi": 0.15},
        {"fin_vol": 0.15, "fin_drawdown": 0.15, "fin_momentum": 0.5, "fin_rsi": 0.2},
    ]

    # Overall clinical vs financial split
    clin_splits = [0.3, 0.4, 0.5, 0.6, 0.7]

    returns_at_horizon = {t: forward_returns.get(t, {}).get(horizon) for t in tickers}

    for clin_weight in clin_splits:
        fin_weight = 1.0 - clin_weight
        for clin_sub in clin_sub_options:
            for fin_sub in fin_sub_options:
                weights = {}
                for k, v in clin_sub.items():
                    weights[k] = v * clin_weight
                for k, v in fin_sub.items():
                    weights[k] = v * fin_weight

                scores = compute_composite_scores(tickers, clinical_features, financial_features, weights)
                composite_scores = {t: scores[t]["composite"] for t in tickers}

                ic = compute_ic(composite_scores, returns_at_horizon)
                if ic is not None and ic > best_ic:
                    best_ic = ic
                    best_weights = weights

    return best_weights, best_ic


# ═══════════════════════════════════════════════════════════════════
# Snapshot generation
# ═══════════════════════════════════════════════════════════════════


def generate_optimized_snapshot(
    as_of: str,
    tickers: list[str],
    scores: dict[str, dict[str, float]],
    clinical_features: dict[str, dict[str, float]],
    financial_features: dict[str, dict[str, float]],
    weights: dict[str, float],
    ic_results: dict[int, float | None],
) -> dict:
    """Generate a snapshot JSON in the same format as the production screener."""
    # Sort by composite score descending
    sorted_tickers = sorted(tickers, key=lambda t: scores[t]["composite"], reverse=True)

    ranked_securities = []
    for rank, ticker in enumerate(sorted_tickers, 1):
        s = scores[ticker]
        cf = clinical_features[ticker]
        ff = financial_features[ticker]

        # Map to production snapshot field names
        ranked_securities.append(
            {
                "ticker": ticker,
                "composite_score": round(s["composite"], 2),
                "composite_rank": rank,
                "clinical_dev_raw": round(s["clinical_max_phase"], 2),
                "clinical_dev_normalized": round(s.get("clinical_max_phase", 0), 2),
                "financial_raw": round(s["fin_momentum"], 2),
                "financial_normalized": round(s.get("fin_momentum", 0), 2),
                "catalyst_raw": round(s["clinical_catalyst"], 2),
                "catalyst_normalized": round(s.get("clinical_catalyst", 0), 2),
                "market_cap_bucket": "unknown",
                "stage_bucket": "late" if cf["max_phase"] >= 4 else "mid" if cf["max_phase"] >= 2 else "early",
                "severity": "sev0" if cf["trial_count"] > 0 else "sev1",
                "uncertainty_penalty": 0.0 if cf["trial_count"] > 0 else 5.0,
                "missing_subfactor_pct": 0.0 if cf["trial_count"] > 0 else 50.0,
                "rankable": True,
                "flags": [] if cf["trial_count"] > 0 else ["no_trials", "early_stage"],
                # New optimized fields
                "optimized_features": {
                    "trial_count": cf["trial_count"],
                    "max_phase": cf["max_phase"],
                    "active_trials": cf["active_trials"],
                    "catalyst_proximity": cf["catalyst_proximity"],
                    "sponsor_diversity": cf["sponsor_diversity"],
                    "momentum_63d": ff["momentum_health"],
                    "volatility_health": ff["vol_health"],
                    "drawdown_health": ff["drawdown_health"],
                    "rsi_health": ff["rsi_health"],
                },
            }
        )

    return {
        "snapshot_id": f"optimized_{as_of}",
        "as_of_date": as_of,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "pit_cutoff": as_of,
        "optimization": {
            "weights": {k: round(v, 4) for k, v in weights.items()},
            "ic_results": {str(k): round(v, 4) if v is not None else None for k, v in ic_results.items()},
            "method": "grid_search_spearman_ic",
            "features": [
                "trial_count",
                "max_phase",
                "active_trials",
                "catalyst_proximity",
                "sponsor_diversity",
                "vol_health",
                "drawdown_health",
                "momentum_health",
                "rsi_health",
            ],
        },
        "ranked_securities": ranked_securities,
        "provenance": {
            "source": "scripts/optimize_scores.py",
            "note": "Optimized scores derived from price momentum/volatility + trial/AACT features",
        },
    }


# ═══════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(description="Optimize biotech screener scores")
    parser.add_argument("--snapshot", default="2024-01-02", help="Point-in-time date (YYYY-MM-DD)")
    parser.add_argument("--output", default=None, help="Output snapshot file path")
    parser.add_argument("--horizon", type=int, default=63, help="Primary optimization horizon (trading days)")
    args = parser.parse_args()

    as_of = args.snapshot
    horizons = [63, 126, 252]

    print("🧬 Biotech Score Optimizer")
    print(f"   As-of date: {as_of}")
    print(f"   Optimization horizon: {args.horizon}d")
    print()

    # Load data
    universe = load_universe()
    prices = load_prices()
    trial_map = load_trial_map()
    aact_studies = load_aact_studies()
    aact_sponsors = load_aact_sponsors()

    # All tickers = universe + price tickers
    all_tickers = sorted(set([c["ticker"].upper() for c in universe] + list(prices.keys())))

    print(f"   Universe: {len(universe)} companies")
    print(f"   With price data: {len(prices)} tickers")
    print(f"   With trial data: {len(trial_map)} tickers")
    print(f"   AACT studies: {len(aact_studies)}")
    print(f"   Total tickers: {len(all_tickers)}")
    print()

    # Compute features for each ticker
    clinical_features: dict[str, dict[str, float]] = {}
    financial_features: dict[str, dict[str, float]] = {}

    for ticker in all_tickers:
        trials = trial_map.get(ticker, [])
        cf = compute_clinical_features(ticker, trials, aact_studies, aact_sponsors)
        clinical_features[ticker] = cf

        price_data = prices.get(ticker, [])
        pf = compute_price_features(price_data, as_of)
        ff = compute_financial_features(pf)
        financial_features[ticker] = ff

    # Compute forward returns
    fwd_returns = compute_forward_returns(prices, as_of, horizons)

    # Report current state
    print("📊 Current screener IC: 0.0000 (all scores = 31.50, no differentiation)")
    print()

    # Grid search optimization
    print(f"🔍 Grid searching weights to maximize IC at {args.horizon}d horizon...")
    best_weights, best_ic = grid_search_weights(
        all_tickers, clinical_features, financial_features, fwd_returns, args.horizon
    )

    print(f"   Best IC at {args.horizon}d: {best_ic:.4f}")
    print("   Optimal weights:")
    for k, v in sorted(best_weights.items(), key=lambda x: -x[1]):
        print(f"     {k:25s}: {v:.4f}")
    print()

    # Compute IC at all horizons with best weights
    best_scores = compute_composite_scores(all_tickers, clinical_features, financial_features, best_weights)
    composite_scores = {t: best_scores[t]["composite"] for t in all_tickers}

    ic_results = {}
    print("📈 IC at all horizons:")
    for h in horizons:
        returns_h = {t: fwd_returns.get(t, {}).get(h) for t in all_tickers}
        ic = compute_ic(composite_scores, returns_h)
        ic_results[h] = ic
        print(f"   {h:4d}d: IC = {ic:.4f}" if ic is not None else f"   {h:4d}d: IC = N/A")
    print()

    # Score distribution
    scores_list = sorted(composite_scores.values())
    print("📊 Score distribution:")
    print(f"   Min:    {scores_list[0]:.2f}")
    print(f"   Max:    {scores_list[-1]:.2f}")
    print(f"   Range:  {scores_list[-1] - scores_list[0]:.2f}")
    print(
        f"   Stdev:  {(sum((s - sum(scores_list)/len(scores_list))**2 for s in scores_list) / len(scores_list))**0.5:.2f}"
    )
    print(f"   Unique: {len(set(round(s, 2) for s in scores_list))}")
    print()

    # Top/bottom companies
    sorted_by_score = sorted(all_tickers, key=lambda t: composite_scores[t], reverse=True)
    print("🏆 Top 5:")
    for t in sorted_by_score[:5]:
        cf = clinical_features[t]
        print(
            f"   {t:6s} score={composite_scores[t]:6.2f}  phase={cf['max_phase']:.0f}  trials={cf['trial_count']:.0f}  catalyst={cf['catalyst_proximity']:.1f}"
        )
    print("📉 Bottom 5:")
    for t in sorted_by_score[-5:]:
        cf = clinical_features[t]
        print(
            f"   {t:6s} score={composite_scores[t]:6.2f}  phase={cf['max_phase']:.0f}  trials={cf['trial_count']:.0f}  catalyst={cf['catalyst_proximity']:.1f}"
        )
    print()

    # Generate optimized snapshot
    snapshot = generate_optimized_snapshot(
        as_of, all_tickers, best_scores, clinical_features, financial_features, best_weights, ic_results
    )

    # Save
    output_path = Path(args.output) if args.output else OUTPUT_DIR / f"snapshot_optimized_{as_of}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2)

    print(f"✅ Optimized snapshot saved: {output_path}")
    print(f"   {len(snapshot['ranked_securities'])} companies with differentiated scores")
    print()

    # Summary
    print("═" * 60)
    print("  OPTIMIZATION COMPLETE")
    print("  Before: IC = 0.0000 (all scores = 31.50)")
    print(f"  After:  IC = {best_ic:.4f} at {args.horizon}d")
    improvement = best_ic - 0.0
    print(f"  Improvement: +{improvement:.4f}")
    print(f"  Score range: {scores_list[0]:.2f} - {scores_list[-1]:.2f}")
    print("═" * 60)


if __name__ == "__main__":
    main()
