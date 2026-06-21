"""Backtesting dashboard API.

``GET /api/backtest``          full backtest results (IC, bucket returns, hit rates)
``GET /api/backtest/stability`` stability attribution (what drives rank changes)
``GET /api/backtest/cohort``    cohort census (stage distribution over time)
``GET /api/backtest/readiness`` data readiness gate status
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Query

from .. import data_loader as dl

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/backtest", tags=["backtest"])

OUTPUT_DIR = dl.REPO_ROOT / "output"


def _load_json(filename: str) -> Dict[str, Any]:
    path = OUTPUT_DIR / filename
    if not path.exists():
        return {"error": f"File not found: {filename}", "path": str(path)}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _sf(value, default=0.0):
    """Safely convert to float, handling None and strings."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@router.get("")
def get_backtest():
    """Full backtest results — IC, bucket returns, hit rates across all periods and horizons."""
    data = _load_json("backtest_results.json")
    if "error" in data:
        return data

    # Summarize for quick dashboard rendering
    periods = data.get("period_metrics", {})
    horizons = data.get("horizons_display", ["3m", "6m", "12m"])
    horizon_keys = data.get("horizons", ["63d", "126d", "252d"])

    # Build summary: IC and Q5-Q1 spread per period per horizon
    summary: Dict[str, Any] = {"periods": [], "horizons": horizons}

    for date_str in sorted(periods.keys()):
        period = periods[date_str]
        period_summary: Dict[str, Any] = {
            "date": date_str,
            "n_ranked": period.get("n_ranked", 0),
            "horizons": {},
        }
        for hk, hd in zip(horizon_keys, horizons):
            h_data = period.get("horizons", {}).get(hk, {})
            bucket = h_data.get("bucket_metrics", {})
            q_returns = bucket.get("bucket_returns", {})
            period_summary["horizons"][hd] = {
                "ic_spearman": _sf(h_data.get("ic_spearman")),
                "n_obs": h_data.get("n_obs", 0),
                "coverage_pct": _sf(h_data.get("coverage_pct")),
                "top_minus_bottom": _sf(bucket.get("top_minus_bottom")),
                "monotonic": bucket.get("monotonic", False),
                "bucket_returns": {k: _sf(v) for k, v in q_returns.items()},
                "bucket_counts": bucket.get("bucket_counts", {}),
                "q5_minus_q1": _sf(h_data.get("q5_minus_q1")),
                "q1_mean": _sf(h_data.get("q1_mean_return")),
                "q5_mean": _sf(h_data.get("q5_mean_return")),
                "hit_rate_q5": _sf(h_data.get("hit_rate_q5")),
                "cross_section_median": _sf(h_data.get("cross_section_median")),
                "window": h_data.get("window", {}),
            }
        summary["periods"].append(period_summary)

    # Aggregate stats across all periods
    agg_ic = {hd: [] for hd in horizons}
    agg_spread = {hd: [] for hd in horizons}
    for p in summary["periods"]:
        for hd in horizons:
            h = p["horizons"].get(hd, {})
            agg_ic[hd].append(h.get("ic_spearman", 0))
            agg_spread[hd].append(h.get("top_minus_bottom", 0))

    summary["aggregate"] = {
        hd: {
            "avg_ic": sum(agg_ic[hd]) / len(agg_ic[hd]) if agg_ic[hd] else 0,
            "avg_spread": sum(agg_spread[hd]) / len(agg_spread[hd]) if agg_spread[hd] else 0,
            "n_periods": len(agg_ic[hd]),
        }
        for hd in horizons
    }

    return {"run_id": data.get("run_id"), "summary": summary, "raw": data}


@router.get("/stability")
def get_stability():
    """Stability attribution — what drives composite rank changes over time."""
    return _load_json("stability_attribution.json")


@router.get("/cohort")
def get_cohort():
    """Cohort census — stage distribution (late/mid/early) across snapshot dates."""
    return _load_json("cohort_census.json")


@router.get("/readiness")
def get_readiness():
    """Data readiness gate — schema validation, coverage, price data quality."""
    return _load_json("data_readiness.json")


@router.get("/sanity")
def get_sanity():
    """Sanity metrics — basic data quality checks."""
    return _load_json("sanity_metrics.json")
