"""Execution Capacity Layer — slippage and sizing realism.

Models realizability of alpha, not alpha itself. This is a portfolio
construction layer that ensures positions are feasible given real
market liquidity.

Uses trailing-only rolling dollar-volume metrics from price_history.csv.
All inputs are PIT-safe (trailing windows, no forward-looking data).

Policy: CONSTRUCTION LAYER ONLY. Not for ranking or alpha.
        Never becomes a rank feature unless explicitly revalidated.
"""

from __future__ import annotations

import csv
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date as dt_date
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

EPS = 1e-6

# Default participation limit: max 5% of 20d ADV
DEFAULT_PARTICIPATION_LIMIT = 0.05
# Target position dollars (for capacity score normalization)
# This is strategy-dependent; defaults to $100K (a ~3.3% weight at $3M NAV)
DEFAULT_TARGET_POSITION_DOLLARS = 100_000.0
# Default portfolio NAV for weight calculation
DEFAULT_PORTFOLIO_NAV = 3_000_000.0

# ═════════════════════════════════════════════════════════════════════════
# Data contract
# ═════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class ExecutionCapacityOverlay:
    """Execution capacity and sizing assessment for a single ticker.

    Policy: CONSTRUCTION LAYER ONLY. Not for ranking or alpha.
    """

    ticker: str
    as_of_date: str

    # Raw metrics
    dollar_volume: float  # most recent day's dollar volume
    adv_20d: float  # mean dollar volume over trailing 20 trading days
    adv_60d: float  # mean dollar volume over trailing 60 trading days
    median_dollar_volume_20d: float  # median dollar volume over trailing 20 days

    # Derived
    execution_capacity_score: float  # clamp(max_pos / target_pos, 0, 1)
    max_position_dollars: float  # participation_limit * adv_20d
    max_position_weight: float  # max_position_dollars / portfolio_nav
    execution_bucket: str  # unrestricted / reduced / micro_size_only / untradeable
    execution_notes: str  # human-readable context

    # Diagnostics
    trading_days_available: int = 0
    features_used: Dict[str, Any] = field(default_factory=dict)
    model_version: str = "execution_v1.0"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "as_of_date": self.as_of_date,
            "dollar_volume": round(self.dollar_volume, 2),
            "adv_20d": round(self.adv_20d, 2),
            "adv_60d": round(self.adv_60d, 2),
            "median_dollar_volume_20d": round(self.median_dollar_volume_20d, 2),
            "execution_capacity_score": round(self.execution_capacity_score, 4),
            "max_position_dollars": round(self.max_position_dollars, 2),
            "max_position_weight": round(self.max_position_weight, 4),
            "execution_bucket": self.execution_bucket,
            "execution_notes": self.execution_notes,
            "trading_days_available": self.trading_days_available,
            "features_used": self.features_used,
            "model_version": self.model_version,
        }


# ═════════════════════════════════════════════════════════════════════════
# Price history loader
# ═════════════════════════════════════════════════════════════════════════


def _load_price_volume_history(
    price_history_path: Path,
    as_of_date: str,
    lookback_days: int = 120,
) -> Dict[str, List[Tuple[str, float, float]]]:
    """Load (date, close, volume) tuples from price_history.csv.

    Returns dict: ticker -> [(date_str, close, volume), ...] sorted by date ascending.
    Only includes rows within [as_of - lookback_days, as_of].
    """
    cutoff_date = dt_date.fromisoformat(as_of_date)
    start_date = cutoff_date - timedelta(days=lookback_days)

    result: Dict[str, List[Tuple[str, float, float]]] = defaultdict(list)

    with open(price_history_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            date_str = row.get("date", "")
            ticker = row.get("ticker", "")
            close_str = row.get("close", "")
            volume_str = row.get("volume", "")

            if not date_str or not ticker or not close_str or not volume_str:
                continue

            try:
                row_date = dt_date.fromisoformat(date_str)
            except (ValueError, TypeError):
                continue

            if row_date < start_date or row_date > cutoff_date:
                continue

            try:
                close = float(close_str)
                volume = float(volume_str)
            except (ValueError, TypeError):
                continue

            if close <= 0 or volume < 0:
                continue

            result[ticker].append((date_str, close, volume))

    # Sort each ticker's data by date
    for ticker in result:
        result[ticker].sort(key=lambda x: x[0])

    logger.info(
        "[ExecutionCapacity] Loaded price/volume for %d tickers, lookback %d days from %s",
        len(result),
        lookback_days,
        as_of_date,
    )
    return result


def _compute_dollar_volume_metrics(
    series: List[Tuple[str, float, float]],
) -> Dict[str, float]:
    """Compute rolling dollar-volume metrics from (date, close, volume) series.

    All metrics are trailing-only (no forward-looking data).
    """
    if not series:
        return {
            "dollar_volume": 0.0,
            "adv_20d": 0.0,
            "adv_60d": 0.0,
            "median_dollar_volume_20d": 0.0,
            "trading_days": 0,
        }

    # Compute dollar volume per day
    dv_series = [(d, close * volume) for d, close, volume in series]

    # Most recent dollar volume
    dollar_volume = dv_series[-1][1] if dv_series else 0.0

    # Trailing 20d and 60d ADV
    dvs = [dv for _, dv in dv_series]
    last_20 = dvs[-20:] if len(dvs) >= 20 else dvs
    last_60 = dvs[-60:] if len(dvs) >= 60 else dvs

    adv_20d = sum(last_20) / len(last_20) if last_20 else 0.0
    adv_60d = sum(last_60) / len(last_60) if last_60 else 0.0

    # Median 20d
    sorted_20 = sorted(last_20)
    n = len(sorted_20)
    if n == 0:
        median_20d = 0.0
    elif n % 2 == 1:
        median_20d = sorted_20[n // 2]
    else:
        median_20d = (sorted_20[n // 2 - 1] + sorted_20[n // 2]) / 2.0

    return {
        "dollar_volume": dollar_volume,
        "adv_20d": adv_20d,
        "adv_60d": adv_60d,
        "median_dollar_volume_20d": median_20d,
        "trading_days": len(dvs),
    }


def _execution_bucket(capacity_score: float) -> str:
    """Classify execution feasibility."""
    if capacity_score >= 1.0:
        return "unrestricted"
    if capacity_score >= 0.5:
        return "reduced"
    if capacity_score > 0.0:
        return "micro_size_only"
    return "untradeable"


# ═════════════════════════════════════════════════════════════════════════
# Public API
# ═════════════════════════════════════════════════════════════════════════


class ExecutionCapacityModel:
    """Compute execution capacity overlays for a universe.

    Usage:
        model = ExecutionCapacityModel(price_history_path=path)
        results = model.score_batch(csv_rows, as_of_date)
    """

    def __init__(
        self,
        price_volume_data: Optional[Dict[str, List[Tuple[str, float, float]]]] = None,
        price_history_path: Optional[Path] = None,
        as_of_date: Optional[str] = None,
        participation_limit: float = DEFAULT_PARTICIPATION_LIMIT,
        target_position_dollars: float = DEFAULT_TARGET_POSITION_DOLLARS,
        portfolio_nav: float = DEFAULT_PORTFOLIO_NAV,
    ) -> None:
        self.participation_limit = participation_limit
        self.target_position_dollars = target_position_dollars
        self.portfolio_nav = portfolio_nav

        if price_volume_data is not None:
            self._data = price_volume_data
        elif price_history_path and price_history_path.exists() and as_of_date:
            self._data = _load_price_volume_history(price_history_path, as_of_date)
        else:
            self._data = {}
            logger.warning("[ExecutionCapacity] No price/volume data — all tickers get zero capacity")

    def score_row(
        self,
        row: Dict[str, Any],
        as_of_date: str,
    ) -> ExecutionCapacityOverlay:
        """Score a single ticker row."""
        ticker = row.get("ticker", "?")
        features: Dict[str, Any] = {}

        series = self._data.get(ticker, [])
        metrics = _compute_dollar_volume_metrics(series)

        adv_20d = metrics["adv_20d"]
        adv_60d = metrics["adv_60d"]
        median_20d = metrics["median_dollar_volume_20d"]
        dollar_volume = metrics["dollar_volume"]
        trading_days = metrics["trading_days"]

        # Max position: conservative rule (min of ADV and median)
        if adv_20d > 0 and median_20d > 0:
            max_pos = min(
                self.participation_limit * adv_20d,
                0.10 * median_20d,
            )
        elif adv_20d > 0:
            max_pos = self.participation_limit * adv_20d
        else:
            max_pos = 0.0

        # Capacity score
        if self.target_position_dollars > 0:
            cap_score = min(1.0, max(0.0, max_pos / self.target_position_dollars))
        else:
            cap_score = 1.0

        # Max weight
        max_weight = max_pos / self.portfolio_nav if self.portfolio_nav > 0 else 0.0

        # Bucket
        bucket = _execution_bucket(cap_score)

        # Notes
        notes_parts: List[str] = []
        if adv_20d > 0:
            if adv_20d >= 1_000_000:
                notes_parts.append(f"ADV20 ${adv_20d / 1_000_000:.1f}mm")
            else:
                notes_parts.append(f"ADV20 ${adv_20d / 1_000:.0f}K")
        else:
            notes_parts.append("no volume data")
        if max_pos > 0:
            notes_parts.append(f"max ${max_pos / 1_000:.0f}K")
        if max_weight > 0:
            notes_parts.append(f"max weight {max_weight * 100:.1f}%")
        if bucket == "micro_size_only":
            notes_parts.append("below desired participation threshold")
        elif bucket == "untradeable":
            notes_parts.append("insufficient liquidity")
        if trading_days < 20:
            notes_parts.append(f"only {trading_days} trading days available")

        # Check options liquidity if available
        opt_liq = row.get("opt_liquidity_state", "")
        if opt_liq:
            if opt_liq == "liquid":
                notes_parts.append("options liquidity OK")
            elif opt_liq in ("illiquid", "absent"):
                notes_parts.append(f"options {opt_liq}")

        features["inputs"] = {
            "participation_limit": self.participation_limit,
            "target_position_dollars": self.target_position_dollars,
            "portfolio_nav": self.portfolio_nav,
            "trading_days": trading_days,
            "opt_liquidity_state": opt_liq,
        }

        return ExecutionCapacityOverlay(
            ticker=ticker,
            as_of_date=as_of_date,
            dollar_volume=dollar_volume,
            adv_20d=adv_20d,
            adv_60d=adv_60d,
            median_dollar_volume_20d=median_20d,
            execution_capacity_score=cap_score,
            max_position_dollars=max_pos,
            max_position_weight=max_weight,
            execution_bucket=bucket,
            execution_notes="; ".join(notes_parts),
            trading_days_available=trading_days,
            features_used=features,
        )

    def score_batch(
        self,
        csv_rows: List[Dict[str, Any]],
        as_of_date: str,
    ) -> List[ExecutionCapacityOverlay]:
        """Score all rows. Returns one overlay per row (same order)."""
        results = []
        for row in csv_rows:
            results.append(self.score_row(row, as_of_date))

        n_scored = len(results)
        n_unrestricted = sum(1 for r in results if r.execution_bucket == "unrestricted")
        n_reduced = sum(1 for r in results if r.execution_bucket == "reduced")
        n_micro = sum(1 for r in results if r.execution_bucket == "micro_size_only")
        n_untradeable = sum(1 for r in results if r.execution_bucket == "untradeable")

        logger.info(
            "[ExecutionCapacity] Scored %d tickers: %d unrestricted, %d reduced, %d micro, %d untradeable",
            n_scored,
            n_unrestricted,
            n_reduced,
            n_micro,
            n_untradeable,
        )
        return results


# ═════════════════════════════════════════════════════════════════════════
# CSV enrichment (called from run_screen.py)
# ═════════════════════════════════════════════════════════════════════════

EXECUTION_CSV_COLUMNS = [
    "dollar_volume",
    "adv_20d",
    "adv_60d",
    "median_dollar_volume_20d",
    "execution_capacity_score",
    "max_position_dollars",
    "max_position_weight",
    "execution_bucket",
    "execution_notes",
]


def enrich_csv_rows(
    csv_rows: List[Dict[str, Any]],
    as_of_date: str,
    price_history_path: Optional[Path] = None,
    participation_limit: float = DEFAULT_PARTICIPATION_LIMIT,
    target_position_dollars: float = DEFAULT_TARGET_POSITION_DOLLARS,
    portfolio_nav: float = DEFAULT_PORTFOLIO_NAV,
) -> List[ExecutionCapacityOverlay]:
    """Compute execution capacity and inject columns in-place.

    Returns the list of ExecutionCapacityOverlay objects (for sidecar writing).
    """
    if price_history_path is None:
        price_history_path = Path("production_data") / "price_history.csv"

    model = ExecutionCapacityModel(
        price_history_path=price_history_path,
        as_of_date=as_of_date,
        participation_limit=participation_limit,
        target_position_dollars=target_position_dollars,
        portfolio_nav=portfolio_nav,
    )
    overlays = model.score_batch(csv_rows, as_of_date)

    for row, overlay in zip(csv_rows, overlays):
        row["dollar_volume"] = overlay.dollar_volume
        row["adv_20d"] = overlay.adv_20d
        row["adv_60d"] = overlay.adv_60d
        row["median_dollar_volume_20d"] = overlay.median_dollar_volume_20d
        row["execution_capacity_score"] = overlay.execution_capacity_score
        row["max_position_dollars"] = overlay.max_position_dollars
        row["max_position_weight"] = overlay.max_position_weight
        row["execution_bucket"] = overlay.execution_bucket
        row["execution_notes"] = overlay.execution_notes

    return overlays
