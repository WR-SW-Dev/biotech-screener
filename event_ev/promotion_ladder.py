"""Event EV Promotion Ladder — staged integration evaluator (Spec 061).

Provides:
  - EventEVPromotionStage enum for ladder positions
  - evaluate_ev_readiness() — checks forward evidence to determine
    which stages have enough data to justify activation
  - load_event_ev_for_cohort() — loads daily EV artifacts and returns
    a ticker-keyed lookup for injection into decision_fields
  - classify_ev_bucket() — maps downside_adjusted_ev to sizing bucket

This module is informational and injector-only — it does NOT auto-promote.
All promotion decisions require human governance review.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from enum import IntEnum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# Stage Enum
# =============================================================================


class EventEVPromotionStage(IntEnum):
    """Ordered promotion stages for Event EV."""

    OFF = 0
    TIEBREAKER = 1
    RANK_OVERLAY = 2
    SIZING_OVERLAY = 3
    COMPOSITE = 4

    @classmethod
    def from_str(cls, s: str) -> "EventEVPromotionStage":
        _map = {
            "off": cls.OFF,
            "tiebreaker": cls.TIEBREAKER,
            "rank_overlay": cls.RANK_OVERLAY,
            "sizing_overlay": cls.SIZING_OVERLAY,
            "composite": cls.COMPOSITE,
        }
        return _map.get(s.lower().strip(), cls.OFF)


# =============================================================================
# EV Bucket Classification (Stage 3)
# =============================================================================


def classify_ev_bucket(
    ds_adj_ev: Optional[float],
    high_threshold: float = 3.0,
    low_threshold: float = -1.0,
) -> str:
    """Classify a name's downside-adjusted EV into a sizing bucket.

    Args:
        ds_adj_ev: downside_adjusted_ev percentage (e.g. 5.2 = +5.2% EV)
        high_threshold: above this → "high_ev"
        low_threshold: below this → "low_ev"

    Returns:
        One of "high_ev", "mid_ev", "low_ev", "no_ev"
    """
    if ds_adj_ev is None:
        return "no_ev"
    if ds_adj_ev >= high_threshold:
        return "high_ev"
    if ds_adj_ev <= low_threshold:
        return "low_ev"
    return "mid_ev"


# =============================================================================
# Load EV Scores for Cohort Injection
# =============================================================================


def load_event_ev_for_cohort(
    as_of_date: date,
    tickers: List[str],
    artifacts_dir: Optional[Path] = None,
) -> Dict[str, Dict[str, Any]]:
    """Load daily Event EV artifacts and return a ticker-keyed lookup.

    Returns:
        {ticker: {"event_ev_score": float, "event_ev_analog_confidence": str,
                   "downside_adjusted_ev": float}} for tickers with EV data.
        Missing tickers are omitted (caller defaults to empty/zero).
    """
    if artifacts_dir is None:
        artifacts_dir = Path("artifacts/event_ev")

    date_str = as_of_date.isoformat()
    scores_path = artifacts_dir / f"{date_str}_event_ev_scores.json"

    if not scores_path.exists():
        logger.debug("No EV scores artifact for %s at %s", date_str, scores_path)
        return {}

    try:
        with open(scores_path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load EV scores from %s: %s", scores_path, e)
        return {}

    # data is a list of EventEV dicts (from build_event_ev_scores.py)
    events = data if isinstance(data, list) else data.get("events", [])

    result: Dict[str, Dict[str, Any]] = {}
    tickers_set = set(tickers)

    for ev in events:
        node = ev.get("node", {})
        ticker = node.get("ticker", "")
        if ticker not in tickers_set:
            continue

        payoff = ev.get("payoff", {})
        ds_adj_ev = payoff.get("downside_adjusted_ev")
        scenario_ev = payoff.get("scenario_ev")
        analog_conf = payoff.get("analog_confidence", "")

        # Use downside_adjusted_ev as the primary score
        score = ds_adj_ev if ds_adj_ev is not None else scenario_ev

        # If a ticker has multiple events, keep the one with highest EV
        existing = result.get(ticker)
        if existing and (existing.get("event_ev_score") or 0) >= (score or 0):
            continue

        result[ticker] = {
            "event_ev_score": score,
            "event_ev_analog_confidence": analog_conf,
            "downside_adjusted_ev": ds_adj_ev,
        }

    return result


def compute_cohort_ev_z_scores(
    ev_lookup: Dict[str, Dict[str, Any]],
) -> Dict[str, float]:
    """Compute cross-sectional z-scores from EV scores for rank overlay.

    Returns {ticker: z_score} for tickers with non-None EV data.
    """
    scores = []
    tickers = []
    for ticker, data in ev_lookup.items():
        s = data.get("event_ev_score")
        if s is not None:
            scores.append(float(s))
            tickers.append(ticker)

    if len(scores) < 2:
        # Not enough data for z-scoring; return raw scores as-is
        return {t: s for t, s in zip(tickers, scores)}

    mean = sum(scores) / len(scores)
    variance = sum((s - mean) ** 2 for s in scores) / len(scores)
    std = variance**0.5 if variance > 0 else 1.0

    return {t: (s - mean) / std for t, s in zip(tickers, scores)}


# =============================================================================
# Forward Evidence Readiness Evaluator
# =============================================================================


def evaluate_ev_readiness(
    artifacts_dir: Optional[Path] = None,
    min_days_tiebreaker: int = 5,
    min_days_rank_overlay: int = 15,
    min_days_sizing_overlay: int = 30,
    min_days_composite: int = 60,
    min_coverage_pct: float = 30.0,
) -> Dict[str, Any]:
    """Evaluate whether enough forward evidence exists for each stage.

    Checks:
      - Number of trading days with EV artifacts
      - Average cohort coverage (% of top-30 with EV data)
      - Any gaps longer than 5 days

    Returns:
        {
            "tiebreaker": {"ready": bool, "evidence": {...}},
            "rank_overlay": {"ready": bool, "evidence": {...}},
            "sizing_overlay": {"ready": bool, "evidence": {...}},
            "composite": {"ready": bool, "evidence": {...}},
            "summary": str,
        }
    """
    if artifacts_dir is None:
        artifacts_dir = Path("artifacts/event_ev")

    # Count daily artifacts
    scores_files = sorted(artifacts_dir.glob("*_event_ev_scores.json"))
    n_days = len(scores_files)

    # Compute coverage stats
    coverages: List[float] = []
    for fpath in scores_files:
        try:
            with open(fpath, encoding="utf-8") as f:
                data = json.load(f)
            events = data if isinstance(data, list) else data.get("leaderboard", data.get("events", []))
            tickers = {ev.get("ticker") or ev.get("node", {}).get("ticker", "") for ev in events} - {
                ""
            }  # Remove empty strings
            # Coverage as count (we don't know top-30 here, use absolute count)
            coverages.append(len(tickers))
        except (json.JSONDecodeError, OSError):
            coverages.append(0)

    avg_coverage = sum(coverages) / len(coverages) if coverages else 0
    max_gap = _compute_max_gap(scores_files)

    evidence_base = {
        "n_daily_artifacts": n_days,
        "avg_tickers_per_day": round(avg_coverage, 1),
        "max_gap_days": max_gap,
    }

    stages = {}
    for stage_name, min_days in [
        ("tiebreaker", min_days_tiebreaker),
        ("rank_overlay", min_days_rank_overlay),
        ("sizing_overlay", min_days_sizing_overlay),
        ("composite", min_days_composite),
    ]:
        ready = n_days >= min_days and avg_coverage >= 1.0
        stages[stage_name] = {
            "ready": ready,
            "evidence": {
                **evidence_base,
                "min_days_required": min_days,
                "days_met": n_days >= min_days,
                "coverage_met": avg_coverage >= 1.0,
            },
        }

    # Summary
    max_ready = "off"
    for name in ["composite", "sizing_overlay", "rank_overlay", "tiebreaker"]:
        if stages[name]["ready"]:
            max_ready = name
            break

    stages["summary"] = (
        f"{n_days} daily artifacts, avg {avg_coverage:.0f} tickers/day, "
        f"max gap {max_gap}d → highest ready stage: {max_ready}"
    )

    return stages


def _compute_max_gap(sorted_files: List[Path]) -> int:
    """Compute the maximum gap in days between consecutive EV artifacts."""
    if len(sorted_files) < 2:
        return 0

    dates = []
    for fpath in sorted_files:
        # Filename format: YYYY-MM-DD_event_ev_scores.json
        try:
            d = date.fromisoformat(fpath.name[:10])
            dates.append(d)
        except ValueError:
            continue

    if len(dates) < 2:
        return 0

    max_gap = 0
    for i in range(1, len(dates)):
        gap = (dates[i] - dates[i - 1]).days
        if gap > max_gap:
            max_gap = gap

    return max_gap
