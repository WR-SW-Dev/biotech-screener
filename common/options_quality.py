"""Options diagnostics robustness layer (Spec 045).

Phase 1: data-state classification, chain-quality scoring, tier-mode assignment.
Makes missingness explicit — blanks are never treated as neutral.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

# Quality gate thresholds
MIN_OI_THRESHOLD = 10  # minimum open interest per contract
MAX_SPREAD_PCT = 0.50  # max bid-ask spread as fraction of mid
MAX_QUOTE_STALE_HOURS = 48  # quotes older than this are stale
MIN_HISTORY_DAYS = 5  # minimum days of IV history for history-based alerts
MIN_TENOR_COUNT = 2  # minimum distinct expiry tenors

# Feature fields by tier
FULL_FEATURES = [
    "opt_atm_iv",
    "opt_front_iv",
    "opt_back_iv",
    "opt_term_slope",
    "opt_put_call_skew",
    "opt_rr_25d",
    "opt_event_premium",
    "actual_implied_move_pctile",
    "implied_event_move",
]
REDUCED_FEATURES = [
    "opt_atm_iv",
    "opt_front_iv",
    "opt_back_iv",
    "opt_event_premium",
    "implied_event_move",
]


@dataclass
class OptionsQuality:
    """Quality assessment for one ticker's options data."""

    ticker: str
    data_state: str  # full | partial | absent | stale
    missing_reason: str  # "" | no_chain | low_oi | stale_quote | bad_spread | parser_fail
    chain_quality_score: float  # 0-1
    tier_mode: str  # full | reduced | absent
    feature_count_present: int
    last_refresh_utc: str
    min_obs_met: bool
    spread_gate_pass: bool
    oi_gate_pass: bool
    staleness_gate_pass: bool
    history_depth: int  # days of usable IV history

    def to_dict(self) -> Dict[str, Any]:
        return {
            "options_data_state": self.data_state,
            "options_missing_reason": self.missing_reason,
            "options_chain_quality_score": round(self.chain_quality_score, 4),
            "options_tier_mode": self.tier_mode,
            "options_feature_count_present": self.feature_count_present,
            "options_last_refresh_utc": self.last_refresh_utc,
            "options_min_obs_met": int(self.min_obs_met),
            "options_spread_gate_pass": int(self.spread_gate_pass),
            "options_oi_gate_pass": int(self.oi_gate_pass),
            "options_staleness_gate_pass": int(self.staleness_gate_pass),
        }


def _parse_float(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def assess_options_quality(
    ranking_row: Dict[str, str],
    as_of_utc: Optional[datetime] = None,
) -> OptionsQuality:
    """Assess options data quality for one ticker from its rankings row.

    Args:
        ranking_row: Full row from rankings.csv with options fields.
        as_of_utc: Current time for staleness check.

    Returns:
        OptionsQuality assessment.
    """
    ticker = ranking_row.get("ticker", "")
    has_data = ranking_row.get("opt_has_data", "0") == "1"

    if not has_data:
        return OptionsQuality(
            ticker=ticker,
            data_state="absent",
            missing_reason="no_chain",
            chain_quality_score=0.0,
            tier_mode="absent",
            feature_count_present=0,
            last_refresh_utc="",
            min_obs_met=False,
            spread_gate_pass=False,
            oi_gate_pass=False,
            staleness_gate_pass=False,
            history_depth=0,
        )

    # Count present features
    present = 0
    for field in FULL_FEATURES:
        val = ranking_row.get(field, "")
        if val and val.strip():
            present += 1

    # Staleness check
    quote_ts = ranking_row.get("opt_quote_ts", "")
    staleness_pass = True
    if quote_ts and as_of_utc:
        try:
            qt = datetime.fromisoformat(quote_ts.replace("Z", "+00:00"))
            hours_old = (as_of_utc - qt).total_seconds() / 3600
            staleness_pass = hours_old <= MAX_QUOTE_STALE_HOURS
        except (ValueError, TypeError):
            staleness_pass = False

    # Liquidity check
    liquidity_ok = ranking_row.get("opt_liquidity_ok", "0") == "1"

    # Use-for-judgment flag
    use_for_judgment = ranking_row.get("opt_use_for_judgment", "") == "YES"

    # Compute quality score (0-1)
    freshness_score = 1.0 if staleness_pass else 0.3
    liquidity_score = 1.0 if liquidity_ok else 0.4
    coverage_score = min(1.0, present / max(len(FULL_FEATURES), 1))
    judgment_score = 1.0 if use_for_judgment else 0.5

    quality = 0.3 * freshness_score + 0.3 * liquidity_score + 0.2 * coverage_score + 0.2 * judgment_score

    # Determine data state and tier mode
    if not staleness_pass:
        data_state = "stale"
        missing_reason = "stale_quote"
        tier_mode = "reduced" if present >= 3 else "absent"
    elif present >= 7 and liquidity_ok:
        data_state = "full"
        missing_reason = ""
        tier_mode = "full"
    elif present >= 3:
        data_state = "partial"
        missing_reason = "low_oi" if not liquidity_ok else ""
        tier_mode = "reduced"
    else:
        data_state = "partial"
        missing_reason = "low_oi" if not liquidity_ok else "bad_spread"
        tier_mode = "absent"

    return OptionsQuality(
        ticker=ticker,
        data_state=data_state,
        missing_reason=missing_reason,
        chain_quality_score=quality,
        tier_mode=tier_mode,
        feature_count_present=present,
        last_refresh_utc=quote_ts,
        min_obs_met=present >= len(REDUCED_FEATURES),
        spread_gate_pass=liquidity_ok,
        oi_gate_pass=liquidity_ok,
        staleness_gate_pass=staleness_pass,
        history_depth=0,  # TODO: compute from IV history when available
    )


def build_options_quality_manifest(
    ranking_rows: list,
    as_of_utc: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Build options quality manifest for the full universe.

    Returns summary dict with per-ticker assessments.
    """
    if as_of_utc is None:
        as_of_utc = datetime.now(timezone.utc)

    assessments = {}
    state_counts = {"full": 0, "partial": 0, "stale": 0, "absent": 0}
    tier_counts = {"full": 0, "reduced": 0, "absent": 0}
    liq_state_counts = {"liquid": 0, "thin": 0, "absent": 0}

    for row in ranking_rows:
        ticker = row.get("ticker", "")
        if not ticker:
            continue
        q = assess_options_quality(row, as_of_utc)
        assessments[ticker] = q.to_dict()
        state_counts[q.data_state] = state_counts.get(q.data_state, 0) + 1
        tier_counts[q.tier_mode] = tier_counts.get(q.tier_mode, 0) + 1
        liq = row.get("opt_liquidity_state", "absent")
        if liq in liq_state_counts:
            liq_state_counts[liq] += 1
        else:
            liq_state_counts["absent"] += 1

    total = len(assessments)
    return {
        "schema": "options_quality_manifest.v1",
        "as_of_utc": as_of_utc.isoformat(),
        "total_tickers": total,
        "state_distribution": state_counts,
        "tier_distribution": tier_counts,
        "liquidity_state_distribution": liq_state_counts,
        "coverage_pct": round((state_counts.get("full", 0) + state_counts.get("partial", 0)) / max(total, 1) * 100, 1),
        "full_pct": round(state_counts.get("full", 0) / max(total, 1) * 100, 1),
        "assessments": assessments,
    }
