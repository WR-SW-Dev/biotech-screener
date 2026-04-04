"""Portfolio risk layer — Spec 052.

Enforceable portfolio-level risk controls applied post-ranking, pre-trade.
Five controls:

    C1: Single-name concentration cap
    C2: Therapeutic-area concentration limit
    C3: Liquidity-aware position ceiling
    C4: Drawdown circuit breaker (tightens C1)
    C5: Correlated-pair limit (drops positions)

Deterministic and stateless. Missing data → skip with WARN (fail-open).
Missing policy → hard failure.
"""

from __future__ import annotations

import copy
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Position:
    ticker: str
    rank: int
    weight: float
    therapeutic_area: Optional[str] = None
    primary_indication: Optional[str] = None
    lead_program_phase: Optional[str] = None
    adv_usd_20d: Optional[float] = None


@dataclass
class PortfolioPolicy:
    risk_layer_enabled: bool = True
    global_name_cap_pct: float = 0.030
    global_name_cap_buffer_pct: float = 0.005
    therapeutic_area_cap_pct: float = 0.40
    liquidity_max_adv_pct: float = 0.05
    account_usd: float = 500_000
    drawdown_breaker_enabled: bool = True
    portfolio_dd_threshold: float = 0.15
    portfolio_dd_cap_multiplier: float = 0.75
    single_name_dd_threshold: float = 0.40
    correlated_pair_enabled: bool = True
    max_same_indication_phase: int = 2


@dataclass
class MarketSnapshot:
    portfolio_dd_from_high: float = 0.0
    single_name_dds: Dict[str, float] = field(default_factory=dict)


@dataclass
class RiskLayerResult:
    positions: List[Position]
    breaches: List[Dict[str, Any]] = field(default_factory=list)
    flags: List[Dict[str, Any]] = field(default_factory=list)
    effective_cap_pct: float = 0.030


def _apply_drawdown_breaker(
    positions,
    policy,
    snapshot,
    breaches,
    flags,
) -> float:
    effective_cap = policy.global_name_cap_pct
    if policy.drawdown_breaker_enabled and snapshot.portfolio_dd_from_high >= policy.portfolio_dd_threshold:
        effective_cap = policy.global_name_cap_pct * policy.portfolio_dd_cap_multiplier
        breaches.append(
            {
                "control": "C4_drawdown_breaker",
                "ticker": "_portfolio",
                "detail": f"portfolio DD {snapshot.portfolio_dd_from_high:.2%} >= threshold {policy.portfolio_dd_threshold:.2%}",
                "action": f"effective cap tightened to {effective_cap:.4f}",
            }
        )
    if policy.drawdown_breaker_enabled and snapshot.single_name_dds:
        for ticker, dd in snapshot.single_name_dds.items():
            if dd >= policy.single_name_dd_threshold:
                flags.append(
                    {
                        "flag_type": "SINGLE_NAME_DRAWDOWN",
                        "ticker": ticker,
                        "severity": "WARN",
                        "detail": f"trailing DD {dd:.2%} >= threshold {policy.single_name_dd_threshold:.2%}",
                    }
                )
    return effective_cap


def _apply_correlated_pair_limit(positions, policy, breaches):
    if not policy.correlated_pair_enabled:
        return list(positions)
    limit = policy.max_same_indication_phase
    groups: Dict[tuple, List[Position]] = defaultdict(list)
    for p in positions:
        if p.primary_indication and p.lead_program_phase:
            groups[(p.primary_indication, p.lead_program_phase)].append(p)
    dropped = set()
    for key, group in groups.items():
        if len(group) <= limit:
            continue
        group.sort(key=lambda p: p.rank)
        to_drop = group[limit:]
        breaches.append(
            {
                "control": "C5_correlated_pair_limit",
                "ticker": ",".join(p.ticker for p in to_drop),
                "detail": f"{key[0]}+{key[1]}: {len(group)} names > limit {limit}",
                "action": f"dropping {len(to_drop)} lowest-ranked: {[p.ticker for p in to_drop]}",
            }
        )
        for p in to_drop:
            dropped.add(p.ticker)
    return [p for p in positions if p.ticker not in dropped]


def apply_risk_layer(
    positions: List[Position],
    policy: Optional[PortfolioPolicy],
    snapshot: MarketSnapshot,
) -> RiskLayerResult:
    if policy is None:
        raise ValueError("Risk layer requires a policy — cannot produce unconstrained weights")

    pos = [copy.copy(p) for p in positions]
    breaches: List[Dict[str, Any]] = []
    flags: List[Dict[str, Any]] = []

    if not policy.risk_layer_enabled:
        return RiskLayerResult(
            positions=pos,
            breaches=[],
            flags=[],
            effective_cap_pct=policy.global_name_cap_pct,
        )

    # C4: Drawdown breaker
    effective_cap = _apply_drawdown_breaker(pos, policy, snapshot, breaches, flags)

    # C5: Correlated-pair limit (drops positions)
    pos = _apply_correlated_pair_limit(pos, policy, breaches)

    # Flag missing data
    missing_area = [p for p in pos if not p.therapeutic_area]
    if missing_area:
        flags.append(
            {
                "flag_type": "MISSING_THERAPEUTIC_AREA",
                "ticker": ",".join(p.ticker for p in missing_area[:5]),
                "severity": "WARN",
                "detail": f"{len(missing_area)} names missing therapeutic_area",
            }
        )

    # Compute per-name hard cap from C1 + C3
    # Start with no cap (1.0), then tighten based on constraints
    n = len(pos) if pos else 1
    name_cap = max(effective_cap, 1.0 / n)
    per_name_cap: Dict[str, float] = {}
    for p in pos:
        cap = 1.0  # no initial constraint — C1 drift cap applied in allocation loop
        # C3: Liquidity ceiling — only tighten if liquidity is more restrictive than drift cap
        if p.adv_usd_20d is not None and p.adv_usd_20d > 0 and policy.account_usd > 0:
            liq_cap = (p.adv_usd_20d * policy.liquidity_max_adv_pct) / policy.account_usd
            if liq_cap < name_cap:
                cap = liq_cap
        elif p.adv_usd_20d is None:
            flags.append(
                {
                    "flag_type": "MISSING_ADV",
                    "ticker": p.ticker,
                    "severity": "WARN",
                    "detail": "no ADV data, skipping liquidity ceiling",
                }
            )
        per_name_cap[p.ticker] = cap

    # Build area groups
    area_tickers: Dict[str, List[str]] = defaultdict(list)
    for p in pos:
        area_tickers[p.therapeutic_area or "_unknown"].append(p.ticker)

    pos_map = {p.ticker: p for p in pos}

    # Iterative constrained allocation:
    # Start from input weights, iteratively enforce C1+C3 (per-name) and
    # C2 (area group), redistributing excess to unconstrained names.
    c1_logged = set()
    c2_logged = set()

    for _iteration in range(100):
        changed = False

        # Enforce per-name caps:
        # C1: drift cap (name_cap = max(effective_cap, 1/N))
        # C3: liquidity cap (may be tighter)
        for p in pos:
            # Effective cap for this position: tightest of name_cap and liquidity cap
            cap = min(name_cap, per_name_cap[p.ticker])
            trigger_val = cap + policy.global_name_cap_buffer_pct
            if p.weight > trigger_val:
                if p.ticker not in c1_logged:
                    control = "C1_single_name_cap"
                    if per_name_cap[p.ticker] < name_cap:
                        control = "C3_liquidity_ceiling"
                    breaches.append(
                        {
                            "control": control,
                            "ticker": p.ticker,
                            "detail": f"weight {p.weight:.4f} > cap {cap:.4f}",
                            "action": f"trimmed to {cap:.4f}",
                        }
                    )
                    c1_logged.add(p.ticker)
                p.weight = cap
                changed = True

        # Enforce area caps (C2)
        for area, tickers in area_tickers.items():
            if area == "_unknown":
                continue
            area_w = sum(pos_map[t].weight for t in tickers)
            if area_w <= policy.therapeutic_area_cap_pct + 1e-9:
                continue
            if area not in c2_logged:
                breaches.append(
                    {
                        "control": "C2_therapeutic_area_cap",
                        "ticker": area,
                        "detail": f"area '{area}' weight {area_w:.4f} > cap {policy.therapeutic_area_cap_pct:.4f}",
                        "action": "scaling down names in area",
                    }
                )
                c2_logged.add(area)
            scale = policy.therapeutic_area_cap_pct / area_w
            for t in tickers:
                pos_map[t].weight *= scale
            changed = True

        # Renormalize: distribute deficit to positions with room
        total = sum(p.weight for p in pos)
        if total < 1.0 - 1e-6:
            deficit = 1.0 - total
            # Compute area headroom
            area_headroom: Dict[str, float] = {}
            for area, tickers in area_tickers.items():
                if area == "_unknown":
                    area_headroom[area] = float("inf")
                    continue
                area_w = sum(pos_map[t].weight for t in tickers)
                area_headroom[area] = max(0, policy.therapeutic_area_cap_pct - area_w)

            # Count expandable names per area for fair sharing of area headroom
            # For deficit fill, use a relaxed cap that allows redistribution
            # The C1 drift cap only applies to names that have DRIFTED above fair share
            # During construction, names can go above 1/N to absorb excess from constrained areas
            fill_cap = max(name_cap * 3.0, 0.20)  # generous ceiling for fill
            expandable_per_area: Dict[str, int] = defaultdict(int)
            expandable = []
            for p in pos:
                cap = min(fill_cap, per_name_cap[p.ticker])
                name_room = cap - p.weight
                area = p.therapeutic_area or "_unknown"
                a_room = area_headroom.get(area, float("inf"))
                if name_room > 1e-9 and a_room > 1e-9:
                    expandable.append(p)
                    expandable_per_area[area] += 1

            if expandable:
                per = deficit / len(expandable)
                for p in expandable:
                    cap = min(fill_cap, per_name_cap[p.ticker])
                    name_room = cap - p.weight
                    area = p.therapeutic_area or "_unknown"
                    a_room_total = area_headroom.get(area, float("inf"))
                    n_in_area = expandable_per_area.get(area, 1)
                    a_room_per = a_room_total / n_in_area if a_room_total != float("inf") else float("inf")
                    add = min(per, name_room, max(a_room_per, 0))
                    if add > 1e-9:
                        p.weight += add
                        if area in area_headroom and area_headroom[area] != float("inf"):
                            area_headroom[area] -= add
                changed = True

        if not changed:
            break

    # Final: if total != 1.0, only use proportional normalization when
    # no area caps are binding (otherwise it would undo area constraints)
    total = sum(p.weight for p in pos)
    if total > 1e-9 and abs(total - 1.0) > 1e-6:
        # Check if any area cap is binding
        any_area_binding = False
        for area, tickers in area_tickers.items():
            if area == "_unknown":
                continue
            area_w = sum(pos_map[t].weight for t in tickers)
            if area_w >= policy.therapeutic_area_cap_pct - 1e-6:
                any_area_binding = True
                break
        if not any_area_binding:
            for p in pos:
                p.weight /= total
        # else: accept total < 1.0 (unallocated = cash)

    return RiskLayerResult(
        positions=pos,
        breaches=breaches,
        flags=flags,
        effective_cap_pct=effective_cap,
    )
