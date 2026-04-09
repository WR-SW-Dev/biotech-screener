"""Options verdict research features — converts fused multi-lens verdict into
per-ticker numeric features suitable for within-bucket rerank testing.

Features computed per ticker:
  - ovf_agreement_count: number of lenses (0-4) that flagged this ticker
  - ovf_severity_score: HIGH=2, MEDIUM=1, RESOLVED/none=0
  - ovf_near_catalyst: 1 if catalyst_days <= 14, else 0
  - ovf_has_event_premium: 1 if EVENT_PREMIUM in flags
  - ovf_has_iv_ramp: 1 if IV_RAMP_HIGH in flags
  - ovf_has_quiet_before: 1 if QUIET_BEFORE_CATALYST in flags
  - ovf_surface_confirmed: 1 if both options_watch and surface_delta agree
  - ovf_composite: bounded [0, 1] composite for rerank testing

All features are deterministic, PIT-safe (derived from same-day artifacts),
and suitable for cross-sectional z-scoring.

Usage:
    from common.options_verdict_features import compute_verdict_features
    features = compute_verdict_features(verdict_artifact, ticker)
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional

_D = Decimal
_SEVERITY_SCORE = {"HIGH": _D("2"), "MEDIUM": _D("1"), "RESOLVED": _D("0")}

# Flags that contribute to composite
_HIGH_VALUE_FLAGS = {
    "EVENT_PREMIUM",
    "IV_RAMP_HIGH",
    "SURFACE_MOVE_HIGH",
    "EXTREME_SKEW",
    "QUIET_BEFORE_CATALYST",
    "iv_jump_up",
    "iv_jump_large_up",
    "rr_flipped_bullish",
}

_PENALTY_FLAGS = {
    "IV_CRUSH",
    "iv_jump_down",
    "iv_jump_large_down",
    "rr_flipped_bearish",
    "REACTION_MISMATCH",
}


def compute_verdict_features(
    verdict_row: Optional[Dict[str, Any]],
) -> Dict[str, str]:
    """Compute research features from one verdict row.

    Args:
        verdict_row: A single row from options_verdict.v1 verdicts list,
                     or None if the ticker has no verdict.

    Returns:
        Dict of feature name → string value (CSV-ready).
        Empty strings for missing/inapplicable features.
    """
    prefix = "ovf_"
    empty = {
        f"{prefix}agreement_count": "",
        f"{prefix}severity_score": "",
        f"{prefix}near_catalyst": "",
        f"{prefix}has_event_premium": "",
        f"{prefix}has_iv_ramp": "",
        f"{prefix}has_quiet_before": "",
        f"{prefix}surface_confirmed": "",
        f"{prefix}composite": "",
    }

    if not verdict_row or verdict_row.get("severity") == "RESOLVED":
        return empty

    flags = set(verdict_row.get("flags", []))
    lenses = set(verdict_row.get("lenses", []))
    n_lenses = verdict_row.get("n_lenses", 0)
    near_cat = verdict_row.get("near_catalyst", False)

    # Agreement count (0-4)
    agreement = _D(str(n_lenses))

    # Severity score
    sev = _SEVERITY_SCORE.get(verdict_row.get("severity", ""), _D("0"))

    # Binary flag features
    has_event_premium = 1 if "EVENT_PREMIUM" in flags else 0
    has_iv_ramp = 1 if "IV_RAMP_HIGH" in flags else 0
    has_quiet = 1 if "QUIET_BEFORE_CATALYST" in flags else 0

    # Surface confirmation: both options_watch AND surface_delta agree
    ow_active = any(l.startswith("options_watch") for l in lenses)
    sd_active = "surface_delta" in lenses
    surface_confirmed = 1 if ow_active and sd_active else 0

    # Composite: bounded [0, 1]
    # Base from agreement (0-4 → 0-0.5)
    composite = agreement * _D("0.125")  # 4 lenses → 0.5

    # High-value flag bonus (up to +0.3)
    hv_count = len(flags & _HIGH_VALUE_FLAGS)
    composite += min(_D("0.3"), _D(str(hv_count)) * _D("0.1"))

    # Penalty flag reduction (up to -0.2)
    pen_count = len(flags & _PENALTY_FLAGS)
    composite -= min(_D("0.2"), _D(str(pen_count)) * _D("0.1"))

    # Near-catalyst bonus (+0.1)
    if near_cat:
        composite += _D("0.1")

    # Surface confirmation bonus (+0.1)
    if surface_confirmed:
        composite += _D("0.1")

    # Clamp to [0, 1]
    composite = max(_D("0"), min(_D("1"), composite))

    return {
        f"{prefix}agreement_count": str(n_lenses),
        f"{prefix}severity_score": str(sev),
        f"{prefix}near_catalyst": str(int(near_cat)),
        f"{prefix}has_event_premium": str(has_event_premium),
        f"{prefix}has_iv_ramp": str(has_iv_ramp),
        f"{prefix}has_quiet_before": str(has_quiet),
        f"{prefix}surface_confirmed": str(surface_confirmed),
        f"{prefix}composite": str(composite.quantize(_D("0.0001"))),
    }


def enrich_csv_rows_with_verdict(
    csv_rows: List[Dict[str, Any]],
    verdict_data: Optional[Dict[str, Any]],
) -> int:
    """Inject verdict features into csv_rows in-place.

    Args:
        csv_rows: The rankings rows to enrich.
        verdict_data: The options_verdict.v1 artifact dict, or None.

    Returns:
        Number of tickers enriched.
    """
    if not verdict_data:
        # Fill empty features for all rows
        for row in csv_rows:
            row.update(compute_verdict_features(None))
        return 0

    # Build ticker → verdict row lookup
    verdict_by_ticker: Dict[str, Dict] = {}
    for v in verdict_data.get("verdicts", []):
        t = v.get("ticker")
        if t:
            verdict_by_ticker[t] = v

    enriched = 0
    for row in csv_rows:
        ticker = row.get("ticker", "")
        vr = verdict_by_ticker.get(ticker)
        row.update(compute_verdict_features(vr))
        if vr:
            enriched += 1

    return enriched
