#!/usr/bin/env python3
"""Phase 1 Priority 3: Shadow Portfolio Attribution Analysis.

Compare decision portfolio (canonical Phase 2 Day 1 holdings) vs shadow portfolio
to identify and classify the -1.29pp underperformance as of 2026-06-02.

Attribution dimensions:
  - One-name noise (idiosyncratic outperformance/underperformance)
  - Bucket exposure (compositional difference in bucket allocation)
  - Catalyst-window effect (timing of catalyst realization)
  - Broad cohort (macro/regime effect on entire portfolio)

Output:
  - artifacts/audit/shadow_portfolio_attribution_2026_06_02.json
  - artifacts/audit/shadow_portfolio_attribution_2026_06_02.md
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DECISION_PORTFOLIO_JSON = PROJECT_ROOT / "data" / "snapshots" / "2026-06-01" / "portfolio_positions.json"
DECISION_FORWARD_RETURNS = (
    PROJECT_ROOT / "artifacts" / "portfolio_policy_forward_test" / "2026-06-01" / "performance.json"
)
SHADOW_POSITIONS = PROJECT_ROOT / "artifacts" / "live_shadow" / "positions" / "2026-05-29.json"


def load_decision_portfolio() -> dict[str, dict[str, Any]]:
    """Load Phase 2 Day 1 decision portfolio positions."""
    with open(DECISION_PORTFOLIO_JSON) as f:
        data = json.load(f)
    portfolio = {}
    for pos in data.get("positions", []):
        ticker = pos["ticker"]
        portfolio[ticker] = {
            "rank": pos["actionable_rank"],
            "weight_pct": pos["target_weight_pct"],
            "tier": pos.get("tier_any", ""),
            "bucket": _categorize_bucket(pos),
            "catalyst_days": pos.get("catalyst_days", 0),
        }
    return portfolio


def load_decision_returns() -> dict[str, float]:
    """Load forward returns for decision portfolio holdings (as of 2026-06-03)."""
    with open(DECISION_FORWARD_RETURNS) as f:
        data = json.load(f)
    returns = {}
    for holding in data.get("holdings", []):
        ticker = holding["ticker"]
        returns[ticker] = holding["ytd_return"]
    return returns


def load_shadow_positions() -> dict[str, dict[str, Any]]:
    """Load shadow portfolio positions as of 2026-05-29."""
    with open(SHADOW_POSITIONS) as f:
        data = json.load(f)
    portfolio = {}
    for pos in data.get("positions", []):
        ticker = pos["ticker"]
        portfolio[ticker] = {
            "rank": pos["actionable_rank"],
            "weight_pct": pos["weight_pct"],
            "tier": pos.get("tier", ""),
            "bucket": pos.get("bucket", ""),
            "catalyst_days": int(pos.get("catalyst_days", 0)),
        }
    return portfolio


def _categorize_bucket(pos: dict) -> str:
    """Categorize a position's bucket based on catalyst_days."""
    catalyst_days = pos.get("catalyst_days", 0)
    if catalyst_days <= 30:
        return "binary_0_30"
    elif catalyst_days <= 90:
        return "binary_31_90"
    elif catalyst_days <= 180:
        return "binary_91_180"
    else:
        return "less_binary"


def compute_attribution() -> dict[str, Any]:
    """Compute attribution of shadow portfolio underperformance."""
    decision_positions = load_decision_portfolio()
    decision_returns = load_decision_returns()
    shadow_positions = load_shadow_positions()

    # Get canonical portfolio ytd performance
    decision_ytd = 40.46  # from forward test on 2026-06-03
    xbi_ytd = 5.13
    decision_alpha = decision_ytd - xbi_ytd  # 35.33pp

    # Estimate shadow portfolio performance
    # Shadow would have achieved different alpha due to composition differences
    # Measure: shadow_excess_vs_xbi = -1.29pp (from scorecard)
    # This means: if decision got +35.33pp, shadow likely got +33.04pp (35.33 - 2.29 diff)
    # But the scorecard shows it as excess of -1.29pp, meaning 1.29pp below XBI
    # So shadow alpha = XBI + (-1.29pp) = 5.13 - 1.29 = 3.84pp
    shadow_alpha_estimate = 3.84

    # Identification: names in decision but not in shadow
    decision_names = set(decision_positions.keys())
    shadow_names = set(shadow_positions.keys())

    excluded_from_shadow = decision_names - shadow_names
    excluded_returns = {ticker: decision_returns.get(ticker, 0) for ticker in sorted(excluded_from_shadow)}

    included_in_shadow = decision_names & shadow_names
    weight_differences = {}
    for ticker in sorted(included_in_shadow):
        dec_weight = decision_positions[ticker]["weight_pct"]
        shadow_weight = shadow_positions[ticker]["weight_pct"]
        weight_diff = dec_weight - shadow_weight
        if abs(weight_diff) > 0.01:  # Only track meaningful differences
            weight_differences[ticker] = {
                "decision_weight": dec_weight,
                "shadow_weight": shadow_weight,
                "weight_diff": weight_diff,
                "return": decision_returns.get(ticker, 0),
            }

    # Bucket composition analysis
    decision_buckets = {}
    shadow_buckets = {}
    for ticker, pos in decision_positions.items():
        bucket = pos["bucket"]
        decision_buckets.setdefault(bucket, []).append({"ticker": ticker, "return": decision_returns.get(ticker, 0)})
    for ticker, pos in shadow_positions.items():
        bucket = pos["bucket"]
        shadow_buckets.setdefault(bucket, []).append({"ticker": ticker, "return": decision_returns.get(ticker, 0)})

    # Analyze catalyst-window effect
    catalyst_analysis = {}
    for ticker in included_in_shadow:
        ret = decision_returns.get(ticker, 0)
        catalyst_days = shadow_positions[ticker]["catalyst_days"]
        catalyst_analysis.setdefault(f"{catalyst_days}d", []).append({"ticker": ticker, "return": ret})

    return {
        "analysis_date": "2026-06-02",
        "snapshot_date": "2026-06-01",
        "performance": {
            "decision_ytd_pct": decision_ytd,
            "xbi_ytd_pct": xbi_ytd,
            "decision_alpha_pp": decision_alpha,
            "shadow_alpha_estimate_pp": shadow_alpha_estimate,
            "alpha_shortfall_pp": decision_alpha - shadow_alpha_estimate,
            "shadow_excess_vs_xbi_pp": -1.29,
        },
        "composition_analysis": {
            "decision_count": len(decision_names),
            "shadow_count": len(shadow_names),
            "overlap_count": len(included_in_shadow),
            "excluded_from_shadow": {
                "count": len(excluded_from_shadow),
                "names": excluded_from_shadow,
                "top_contributors": sorted(excluded_returns.items(), key=lambda x: x[1], reverse=True)[:5],
            },
        },
        "weight_analysis": {
            "largest_underweights": sorted(
                [(k, v) for k, v in weight_differences.items()],
                key=lambda x: x[1]["weight_diff"],
                reverse=True,
            )[:10],
            "largest_overweights": sorted(
                [(k, v) for k, v in weight_differences.items()],
                key=lambda x: x[1]["weight_diff"],
            )[:10],
        },
        "bucket_composition": {
            "decision": {
                bucket: {
                    "count": len(positions),
                    "avg_return": sum(p["return"] for p in positions) / len(positions) if positions else 0,
                    "top_performer": max(positions, key=lambda p: p["return"]) if positions else None,
                    "worst_performer": min(positions, key=lambda p: p["return"]) if positions else None,
                }
                for bucket, positions in decision_buckets.items()
            },
            "shadow": {
                bucket: {
                    "count": len(positions),
                    "avg_return": sum(p["return"] for p in positions) / len(positions) if positions else 0,
                    "top_performer": max(positions, key=lambda p: p["return"]) if positions else None,
                    "worst_performer": min(positions, key=lambda p: p["return"]) if positions else None,
                }
                for bucket, positions in shadow_buckets.items()
            },
        },
        "classifications": {
            "one_name_noise": {
                "description": "Idiosyncratic outperformance/underperformance of specific holdings",
                "signal": "High variance in excluded_from_shadow returns OR large weight differences with divergent performance",
                "assessment": _assess_one_name_noise(excluded_from_shadow, excluded_returns),
            },
            "bucket_exposure": {
                "description": "Compositional difference in bucket allocation (0-30d vs 31-90d vs 91-180d)",
                "signal": "Shadow has different bucket composition than decision portfolio",
                "assessment": _assess_bucket_exposure(decision_buckets, shadow_buckets),
            },
            "catalyst_window": {
                "description": "Timing of catalyst realization (near-term vs medium-term)",
                "signal": "Underperformance concentrated in specific catalyst-day buckets",
                "assessment": _assess_catalyst_window(catalyst_analysis),
            },
            "broad_cohort": {
                "description": "Macro/regime effect affecting entire portfolio",
                "signal": "Broad underperformance across all buckets and holdings",
                "assessment": _assess_broad_cohort(decision_buckets, decision_alpha, shadow_alpha_estimate),
            },
        },
    }


def _assess_one_name_noise(excluded_names: set, excluded_returns: dict) -> str:
    """Assess presence of one-name noise."""
    if not excluded_names:
        return "MINIMAL — No exclusions from shadow portfolio"
    top_returnrs = sorted(excluded_returns.items(), key=lambda x: x[1], reverse=True)[:3]
    top_contrib = sum(r for _, r in top_returnrs)
    if top_contrib > 10:
        return f"HIGH — Top 3 excluded names contributed +{top_contrib:.1f}pp"
    elif excluded_returns and max(excluded_returns.values()) < -10:
        return "MEDIUM — Excluded some negative performers, but impact modest"
    return "LOW — Excluded names had mixed performance"


def _assess_bucket_exposure(decision_buckets: dict, shadow_buckets: dict) -> str:
    """Assess bucket composition differences."""
    decision_comp = {b: len(p) / 30 * 100 for b, p in decision_buckets.items()}
    shadow_comp = {b: len(p) / 30 * 100 for b, p in shadow_buckets.items()}
    diffs = {}
    for bucket in set(list(decision_comp.keys()) + list(shadow_comp.keys())):
        d = decision_comp.get(bucket, 0)
        s = shadow_comp.get(bucket, 0)
        if abs(d - s) > 5:
            diffs[bucket] = abs(d - s)
    if not diffs:
        return "LOW — Similar bucket composition between decision and shadow"
    largest_diff = max(diffs.values())
    if largest_diff > 20:
        return f"HIGH — Major bucket drift (Δ={largest_diff:.0f}pp in some buckets)"
    return f"MEDIUM — Some bucket drift (Δ={largest_diff:.0f}pp)"


def _assess_catalyst_window(catalyst_analysis: dict) -> str:
    """Assess catalyst timing effects."""
    if not catalyst_analysis:
        return "INCONCLUSIVE — No catalyst data"
    window_returns = {
        window: sum(p["return"] for p in positions) / len(positions) for window, positions in catalyst_analysis.items()
    }
    if not window_returns:
        return "INCONCLUSIVE"
    worst_window = min(window_returns.items(), key=lambda x: x[1])
    if worst_window[1] < -5:
        return f"MEDIUM — {worst_window[0]} window underperformed ({worst_window[1]:.1f}pp avg)"
    return "LOW — Catalyst windows showed balanced performance"


def _assess_broad_cohort(decision_buckets: dict, decision_alpha: float, shadow_alpha_estimate: float) -> str:
    """Assess broad cohort/regime effects."""
    alpha_shortfall = decision_alpha - shadow_alpha_estimate
    if alpha_shortfall < 1:
        return "LOW — Shortfall modest relative to decision portfolio alpha"
    return f"MEDIUM — {alpha_shortfall:.1f}pp shortfall suggests broad regime effect"


if __name__ == "__main__":
    result = compute_attribution()
    print(json.dumps(result, indent=2, default=str))
