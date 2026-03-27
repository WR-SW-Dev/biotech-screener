"""Wake Robin context enrichment — DEM-aware ticker context for alerts.

Reads the latest rankings.csv and shadow positions to produce enriched
context for any ticker. Turns a generic "$PVLA up 8%" into:

    PVLA | A-tier | Rank 18 | 4d to CLINICAL catalyst (hard) |
    IV regime ELEVATED | RR -0.21 (put skew) | move pctile 0.84 |
    shadow: YES (binary_0_30, 0.50%) | trade plan: NO

Usage:
    from common.wake_robin_context import enrich_ticker, enrich_alert

    ctx = enrich_ticker("PVLA", as_of_date="2026-03-27")
    enriched = enrich_alert({"ticker": "PVLA", "code": "STOCK_MOVE_UP"}, as_of_date="2026-03-27")
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any, Dict, Optional, Set

REPO_ROOT = Path(__file__).resolve().parent.parent

# Fields to extract from rankings.csv
CONTEXT_FIELDS = [
    "ticker",
    "actionable_rank",
    "tier_dev",
    "catalyst_days",
    "catalyst_family",
    "catalyst_bucket",
    "catalyst_event_type",
    "catalyst_source",
    "is_hard_catalyst",
    "archetype",
    "eligible",
    # Options surface
    "opt_atm_iv",
    "opt_term_slope",
    "opt_rr_25d",
    "opt_iv_regime",
    "opt_event_premium",
    "opt_use_for_judgment",
    "actual_implied_move_pctile",
    "atm_iv_change_5d",
    # Regulatory
    "regulatory_days",
    "regulatory_event_type",
    "regulatory_confidence",
    # Financials
    "runway_months",
    "market_cap_bucket",
    "mom_state",
]


def _sf(val: Any) -> float:
    if val is None or val == "":
        return math.nan
    try:
        return float(val)
    except (ValueError, TypeError):
        return math.nan


def _load_rankings(snap_dir: Path) -> Dict[str, Dict[str, str]]:
    """Load rankings.csv into {ticker: row} dict."""
    path = snap_dir / "rankings.csv"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return {r["ticker"]: r for r in csv.DictReader(f) if r.get("ticker")}


def _load_positions(artifacts_dir: Path, as_of_date: str) -> Dict[str, Dict]:
    """Load shadow positions into {ticker: position} dict."""
    path = artifacts_dir / "live_shadow" / "positions" / f"{as_of_date}.json"
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return {p["ticker"]: p for p in data.get("positions", []) if p.get("ticker")}
    except (json.JSONDecodeError, OSError):
        return {}


def _load_trade_plan(artifacts_dir: Path, as_of_date: str) -> Set[str]:
    """Load trade plan tickers."""
    path = artifacts_dir / "live_shadow" / "trade_plan" / as_of_date / "trade_plan.csv"
    if not path.exists():
        return set()
    try:
        with open(path, encoding="utf-8") as f:
            return {row["ticker"] for row in csv.DictReader(f) if row.get("ticker")}
    except (KeyError, OSError):
        return set()


# Cache for repeated calls within the same run
_cache: Dict[str, Any] = {}


def _get_data(
    as_of_date: str,
    snapshots_dir: Optional[Path] = None,
    artifacts_dir: Optional[Path] = None,
) -> tuple:
    """Load and cache rankings + positions for the given date."""
    cache_key = as_of_date
    if cache_key in _cache:
        return _cache[cache_key]

    snap_dir = (snapshots_dir or REPO_ROOT / "data" / "snapshots") / as_of_date
    art_dir = artifacts_dir or REPO_ROOT / "artifacts"

    rankings = _load_rankings(snap_dir)
    positions = _load_positions(art_dir, as_of_date)
    trade_plan = _load_trade_plan(art_dir, as_of_date)

    result = (rankings, positions, trade_plan)
    _cache[cache_key] = result
    return result


def enrich_ticker(
    ticker: str,
    as_of_date: str,
    *,
    snapshots_dir: Optional[Path] = None,
    artifacts_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Return full DEM context for a ticker.

    Returns dict with:
        screening: rank, tier, catalyst info, options surface
        portfolio: shadow membership, bucket, weight, trade plan status
    """
    rankings, positions, trade_plan = _get_data(as_of_date, snapshots_dir, artifacts_dir)

    row = rankings.get(ticker, {})
    pos = positions.get(ticker)

    # Screening context
    screening = {}
    for field in CONTEXT_FIELDS:
        val = row.get(field, "")
        screening[field] = val

    # Portfolio context (dual reporting per feedback)
    portfolio = {
        "in_shadow": pos is not None,
        "in_trade_plan": ticker in trade_plan,
    }
    if pos:
        portfolio["bucket"] = pos.get("bucket", "")
        portfolio["effective_family"] = pos.get("effective_family", "")
        portfolio["weight_pct"] = pos.get("weight_pct", 0)
        portfolio["regulatory_days"] = pos.get("regulatory_days", "")

    return {
        "ticker": ticker,
        "as_of_date": as_of_date,
        "screening": screening,
        "portfolio": portfolio,
    }


def format_context_line(ctx: Dict[str, Any]) -> str:
    """Format enriched context as a single compact line.

    Example:
        PVLA | A | Rank 18 | 4d CLINICAL (hard) | IV:ELEVATED RR:-0.21 move:0.84 | shadow:YES (binary_0_30 0.5%)
    """
    s = ctx.get("screening", {})
    p = ctx.get("portfolio", {})
    ticker = ctx.get("ticker", "?")

    parts = [ticker]

    # Tier + rank
    tier = s.get("tier_dev", "")
    rank = s.get("actionable_rank", "")
    if tier:
        parts.append(tier)
    if rank:
        parts.append(f"Rank {rank}")

    # Catalyst
    cat_days = s.get("catalyst_days", "")
    cat_family = s.get("catalyst_family", "")
    is_hard = s.get("is_hard_catalyst", "") == "1"
    if cat_days:
        hard_label = " (hard)" if is_hard else ""
        parts.append(f"{cat_days}d {cat_family}{hard_label}")

    # Options surface
    opt_parts = []
    regime = s.get("opt_iv_regime", "")
    if regime:
        opt_parts.append(f"IV:{regime}")
    rr = s.get("opt_rr_25d", "")
    if rr:
        try:
            opt_parts.append(f"RR:{float(rr):+.2f}")
        except ValueError:
            pass
    move = s.get("actual_implied_move_pctile", "")
    if move:
        try:
            opt_parts.append(f"move:{float(move):.2f}")
        except ValueError:
            pass
    if opt_parts:
        parts.append(" ".join(opt_parts))

    # Portfolio (dual reporting)
    shadow = p.get("in_shadow", False)
    if shadow:
        bucket = p.get("bucket", "")
        weight = p.get("weight_pct", 0)
        eff_family = p.get("effective_family", "")
        shadow_detail = f"shadow:YES ({bucket} {weight:.1f}%"
        if eff_family and eff_family != s.get("catalyst_family", ""):
            shadow_detail += f" eff:{eff_family}"
        shadow_detail += ")"
        parts.append(shadow_detail)
    else:
        parts.append("shadow:NO")

    if p.get("in_trade_plan"):
        parts.append("trade:YES")

    return " | ".join(parts)


def enrich_alert(
    alert: Dict[str, Any],
    as_of_date: str,
    *,
    snapshots_dir: Optional[Path] = None,
    artifacts_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Enrich an alert dict with full DEM context.

    Adds 'context' and 'context_line' fields to the alert.
    """
    ticker = alert.get("ticker", "")
    if not ticker:
        return alert

    ctx = enrich_ticker(ticker, as_of_date, snapshots_dir=snapshots_dir, artifacts_dir=artifacts_dir)
    enriched = dict(alert)
    enriched["context"] = ctx
    enriched["context_line"] = format_context_line(ctx)
    return enriched


def clear_cache():
    """Clear the data cache (for testing)."""
    _cache.clear()
