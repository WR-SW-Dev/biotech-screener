"""Deterministic transaction-cost model for strategy backtests.

Uses PIT-safe ADV (avg_volume * price) from archive market_data.json to
estimate spread + market-impact costs.  All inputs are per-trade; the model
is stateless and has zero external dependencies.

Conventions
-----------
- Costs are in **basis points** (bps): 1 bp = 0.01%.
- ``estimate_trade_cost`` returns a *one-way* cost (spread + impact).
  Multiply by 2 for round-trip.
- ``participation_pct`` = trade_value / adv_dollars.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from dataclasses import fields as dc_fields
from typing import Dict, List, Tuple


@dataclass(frozen=True)
class CostSchedule:
    """Immutable, versioned cost-model parameters.

    ``spread_schedule`` maps (adv_floor_dollars, half_spread_bps) tuples.
    The schedule is scanned top-down; the first entry whose floor is <=
    the ticker's ADV determines the spread.

    ``aum_dollars`` is the strategy's live operating point. Per Spec 050
    (docs/MODEL_DOCUMENTATION.md:747), the documented account size is
    $50,000 notional. Capacity studies (scripts/research/capacity_audit.py,
    scripts/research/capacity_curve.py) pass their own AUM grids and do NOT
    read this default. Do not change this default without also updating
    MODEL_DOCUMENTATION.md; a mismatch manifests as sentinel WARN on
    ``median_cost_bps`` (~800 bps at the $50M default vs ~50 bps at the
    documented $50K operating point — see spec at
    fingpt_pilot/notes/SPEC_COST_MODEL_AUM_FIX.md, 2026-04-19).
    """

    spread_schedule: Tuple[Tuple[int, int], ...] = (
        (10_000_000, 3),  # ADV >= $10M
        (5_000_000, 5),  # ADV >= $5M
        (1_000_000, 10),  # ADV >= $1M
        (500_000, 18),  # ADV >= $500K
        (0, 25),  # ADV < $500K
    )
    impact_coeff: float = 0.10
    impact_cap_bps: float = 200.0
    aum_dollars: float = 50_000  # Spec 050 operating point — see class docstring

    @property
    def schedule_id(self) -> str:
        """Deterministic 8-char SHA-256 of all fields."""
        parts = []
        for f in dc_fields(self):
            parts.append(f"{f.name}={getattr(self, f.name)}")
        blob = "|".join(parts).encode()
        return hashlib.sha256(blob).hexdigest()[:8]


DEFAULT_SCHEDULE = CostSchedule()


@dataclass(frozen=True)
class CostEstimate:
    """Result of ``estimate_trade_cost``."""

    spread_bps: float
    impact_bps: float
    one_way_bps: float
    round_trip_bps: float
    participation_pct: float
    adv_dollars: float


def _lookup_spread(adv_dollars: float, schedule: Tuple[Tuple[int, int], ...]) -> float:
    """Walk the spread schedule and return half-spread bps for *adv_dollars*."""
    for floor, bps in schedule:
        if adv_dollars >= floor:
            return float(bps)
    # Fallback: last entry (floor=0) should always match, but be safe
    return float(schedule[-1][1])


def estimate_trade_cost(
    weight_pct: float,
    adv_dollars: float,
    schedule: CostSchedule = DEFAULT_SCHEDULE,
) -> CostEstimate:
    """Estimate one-way and round-trip trading cost for a single position.

    Parameters
    ----------
    weight_pct : float
        Portfolio weight in percent (e.g. 5.0 = 5%).
    adv_dollars : float
        Average daily volume in dollars (avg_volume * price).
    schedule : CostSchedule
        Cost-model parameters.

    Returns
    -------
    CostEstimate
        Spread, impact, one-way, round-trip costs in bps,
        plus participation rate and ADV.
    """
    if weight_pct <= 0 or adv_dollars <= 0:
        return CostEstimate(
            spread_bps=0.0,
            impact_bps=0.0,
            one_way_bps=0.0,
            round_trip_bps=0.0,
            participation_pct=0.0,
            adv_dollars=adv_dollars,
        )

    trade_value = schedule.aum_dollars * weight_pct / 100.0
    participation = trade_value / adv_dollars

    spread_bps = _lookup_spread(adv_dollars, schedule.spread_schedule)
    impact_bps = min(
        schedule.impact_coeff * math.sqrt(participation) * 10_000,
        schedule.impact_cap_bps,
    )
    one_way = spread_bps + impact_bps
    round_trip = 2.0 * one_way

    return CostEstimate(
        spread_bps=round(spread_bps, 2),
        impact_bps=round(impact_bps, 2),
        one_way_bps=round(one_way, 2),
        round_trip_bps=round(round_trip, 2),
        participation_pct=round(participation * 100, 4),
        adv_dollars=adv_dollars,
    )


def estimate_portfolio_cost_bps(
    adv_dollars_list: List[float],
    n_positions: int,
    schedule: CostSchedule = DEFAULT_SCHEDULE,
) -> float:
    """Estimate average one-way cost in bps for an equal-weight portfolio.

    Uses per-name ADV to compute spread + impact for each position,
    then returns the value-weighted average one-way cost.

    Parameters
    ----------
    adv_dollars_list : list of float
        ADV in dollars for each position (may be shorter than n_positions
        if some names lack volume data — missing names get the worst-tier cost).
    n_positions : int
        Total positions (used for weight_pct = 100/n).
    schedule : CostSchedule
        Cost parameters.

    Returns
    -------
    float
        Average one-way cost in bps.
    """
    if n_positions <= 0:
        return 0.0
    weight_pct = 100.0 / n_positions
    costs = []
    for adv in adv_dollars_list:
        est = estimate_trade_cost(weight_pct, adv, schedule)
        costs.append(est.one_way_bps)
    # Fill missing names with worst-tier cost
    if len(costs) < n_positions:
        worst = estimate_trade_cost(weight_pct, 1.0, schedule)
        costs.extend([worst.one_way_bps] * (n_positions - len(costs)))
    return sum(costs) / len(costs) if costs else 0.0


def compute_cost_telemetry(
    n_positions: int,
    estimates: List[CostEstimate],
    schedule: CostSchedule,
) -> Dict[str, float]:
    """Compute coverage and cap-binding diagnostics for cost estimates.

    Parameters
    ----------
    n_positions : int
        Total portfolio positions (including those without cost estimates).
    estimates : list of CostEstimate
        Cost estimates for positions that have ADV data.
    schedule : CostSchedule
        The schedule used, for cap-binding detection.

    Returns
    -------
    dict with keys: cost_coverage_pct, cap_binding_pct, n_costed, n_positions.
    """
    n_costed = len(estimates)
    coverage = n_costed / n_positions * 100 if n_positions > 0 else 0.0
    cap_binding = sum(1 for e in estimates if e.impact_bps >= schedule.impact_cap_bps - 0.01)
    cap_pct = cap_binding / n_costed * 100 if n_costed > 0 else 0.0
    return {
        "cost_coverage_pct": round(coverage, 1),
        "cap_binding_pct": round(cap_pct, 1),
        "n_costed": n_costed,
        "n_positions": n_positions,
    }
