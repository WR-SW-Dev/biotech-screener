"""Runway-to-Catalyst Severity — canonical financing-truth feature.

One feature computed once, consumed across four layers:
  A. Truth layer: survivability gate (financing_truth_gate)
  B. Expectation layer: crowd-belief distortion input
  C. EV layer: dilution-adjusted payoff (dilution_haircut)
  D. Portfolio layer: position sizing (size_multiplier)

Core insight: the model should care about BUFFER TO CATALYST, not
cash by itself. A company with 10 months of runway and a catalyst
in 4 months is fundamentally different from one with 10 months and
a catalyst in 14 months.

Policy: DIAGNOSTIC OVERLAY until forward-validated.
        Does not affect ranking or selection yet.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

EPS = 1e-6

# ═════════════════════════════════════════════════════════════════════════
# Catalyst decisiveness mapping
# ═════════════════════════════════════════════════════════════════════════

# catalyst_type_tier → decisiveness weight
# T1 = confirmed regulatory (PDUFA, AdCom) → most decisive
# T2 = pivotal data (Phase 3 readout) → very decisive
# T3 = calendar milestone (conference, data cutoff) → moderate
# T4 = soft signal (routine update, poster) → low
# T5 = unknown → minimal
TIER_DECISIVENESS: Dict[str, float] = {
    "T1": 1.0,
    "T2": 0.85,
    "T3": 0.50,
    "T4": 0.20,
    "T5": 0.10,
}

# Minimum tier to count as "truly decisive" for severity reduction
MIN_DECISIVE_TIER = "T2"

# ═════════════════════════════════════════════════════════════════════════
# Data contract
# ═════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class RunwaySeverityOverlay:
    """Runway-to-catalyst severity assessment for a single ticker.

    Two severity paths:
      - truth_severity: "can they survive to the catalyst?" (T1/T2 decisive only)
      - ev_severity: "what financing damage even if they do?" (any tier)

    Policy: DIAGNOSTIC OVERLAY. Not in ranking yet.
    """

    ticker: str
    as_of_date: str

    # Core inputs
    months_to_cash_out: Optional[float]
    months_to_next_decisive_catalyst: Optional[float]
    runway_buffer_months: Optional[float]  # truth-gate buffer (decisive only)

    # Severity scores [0, 1] — higher = more financing pressure
    runway_severity_score: float  # truth-gate severity (for gate + bucket)
    ev_severity_score: float  # EV/sizing severity (uses actual catalyst timing)

    # Layer outputs
    financing_truth_gate: bool  # False = hard fail (truth_severity > 0.92)
    dilution_haircut: float  # [0, ~0.35] — from ev_severity
    size_multiplier: float  # [0.40, 1.0] — from ev_severity

    # Context
    catalyst_type_tier: str
    catalyst_decisiveness: float
    severity_bucket: str  # safe / moderate / elevated / critical / extreme
    severity_notes: str

    model_version: str = "runway_severity_v1.1"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "as_of_date": self.as_of_date,
            "months_to_cash_out": (round(self.months_to_cash_out, 1) if self.months_to_cash_out is not None else None),
            "months_to_next_decisive_catalyst": (
                round(self.months_to_next_decisive_catalyst, 1)
                if self.months_to_next_decisive_catalyst is not None
                else None
            ),
            "runway_buffer_months": (
                round(self.runway_buffer_months, 1) if self.runway_buffer_months is not None else None
            ),
            "runway_severity_score": round(self.runway_severity_score, 4),
            "ev_severity_score": round(self.ev_severity_score, 4),
            "financing_truth_gate": self.financing_truth_gate,
            "dilution_haircut": round(self.dilution_haircut, 4),
            "size_multiplier": round(self.size_multiplier, 4),
            "catalyst_type_tier": self.catalyst_type_tier,
            "catalyst_decisiveness": round(self.catalyst_decisiveness, 2),
            "severity_bucket": self.severity_bucket,
            "severity_notes": self.severity_notes,
            "model_version": self.model_version,
        }


# ═════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════


def _sf(v: Any) -> Optional[float]:
    if v is None or v == "" or v == "None":
        return None
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except (ValueError, TypeError):
        return None


def _severity_bucket(score: float) -> str:
    if score < 0.15:
        return "safe"
    if score < 0.40:
        return "moderate"
    if score < 0.70:
        return "elevated"
    if score < 0.92:
        return "critical"
    return "extreme"


def _catalyst_months(catalyst_days: Optional[float]) -> Optional[float]:
    """Convert catalyst_days to months (30.44 days/month)."""
    if catalyst_days is None or catalyst_days <= 0:
        return None
    return catalyst_days / 30.44


def _is_decisive(tier: str) -> bool:
    """Is this catalyst tier truly value-inflecting?"""
    return tier in ("T1", "T2")


# ═════════════════════════════════════════════════════════════════════════
# Core severity computation
# ═════════════════════════════════════════════════════════════════════════


def _compute_base_severity(
    runway_months: float,
    buffer: float,
    catalyst_months: Optional[float],
    catalyst_tier: str,
    market_cap_mm: Optional[float],
    short_interest_pct: Optional[float],
    has_revenue_or_partner: bool,
    financing_pressure_score: Optional[float],
) -> float:
    """Base severity from buffer + adjustments. Shared by truth and EV paths."""
    # Base severity: sigmoid centered at 3-month buffer
    base = 1.0 / (1.0 + math.exp((buffer - 3.0) / 2.0))

    # Adjustments
    adj = 0.0

    # Financing window quality (from existing financing_pressure_score)
    if financing_pressure_score is not None and financing_pressure_score > 60:
        adj += 0.08  # poor financing window

    # Small-cap penalty (harder to raise capital)
    if market_cap_mm is not None and market_cap_mm < 300:
        adj += 0.07

    # High short interest = market skepticism → harder financing
    if short_interest_pct is not None and short_interest_pct > 15:
        adj += 0.05

    # Revenue or partnership → reduces financing pressure
    if has_revenue_or_partner:
        adj -= 0.08

    # Decisive catalyst nearby → value inflection reduces severity
    if catalyst_months is not None and catalyst_months <= 6 and _is_decisive(catalyst_tier):
        adj -= 0.06

    return max(0.0, min(1.0, base + adj))


def compute_severity(
    runway_months: Optional[float],
    catalyst_months: Optional[float],
    catalyst_tier: str,
    market_cap_mm: Optional[float],
    short_interest_pct: Optional[float],
    has_revenue_or_partner: bool,
    financing_pressure_score: Optional[float],
) -> float:
    """Compute runway severity score [0, 1] for truth gate.

    Uses decisive-catalyst buffer: non-decisive tiers get inflated horizon.
    This is the SURVIVABILITY question: "can they make it to the catalyst?"
    """
    if runway_months is None:
        return 0.35

    if catalyst_months is not None:
        buffer = runway_months - catalyst_months
    else:
        buffer = runway_months - 12.0

    return _compute_base_severity(
        runway_months,
        buffer,
        catalyst_months,
        catalyst_tier,
        market_cap_mm,
        short_interest_pct,
        has_revenue_or_partner,
        financing_pressure_score,
    )


def compute_ev_severity(
    runway_months: Optional[float],
    actual_catalyst_months: Optional[float],
    catalyst_tier: str,
    market_cap_mm: Optional[float],
    short_interest_pct: Optional[float],
    has_revenue_or_partner: bool,
    financing_pressure_score: Optional[float],
) -> float:
    """Compute severity for EV/sizing layers using ACTUAL catalyst timing.

    Unlike truth-gate severity, this uses the real catalyst date regardless
    of tier. A T3 conference in 2 months still matters for expectations,
    financing windows, and position sizing — even if it's not decisive
    enough to gate survivability.
    """
    if runway_months is None:
        return 0.35

    if actual_catalyst_months is not None:
        buffer = runway_months - actual_catalyst_months
    else:
        buffer = runway_months - 12.0

    return _compute_base_severity(
        runway_months,
        buffer,
        actual_catalyst_months,
        catalyst_tier,
        market_cap_mm,
        short_interest_pct,
        has_revenue_or_partner,
        financing_pressure_score,
    )


# ═════════════════════════════════════════════════════════════════════════
# Public API
# ═════════════════════════════════════════════════════════════════════════


class RunwaySeverityModel:
    """Compute runway-to-catalyst severity for a universe.

    Usage:
        model = RunwaySeverityModel()
        results = model.score_batch(csv_rows, as_of_date)
    """

    def score_row(
        self,
        row: Dict[str, Any],
        as_of_date: str,
    ) -> RunwaySeverityOverlay:
        """Score a single ticker row from rankings.csv."""
        ticker = row.get("ticker", "?")

        # Extract inputs — runway_months lives inside fundamental_red_flag_inputs (JSON string)
        runway_months = _sf(row.get("runway_months"))
        burn_ttm = _sf(row.get("burn_ttm"))
        has_revenue = False

        if runway_months is None:
            rflag_raw = row.get("fundamental_red_flag_inputs", "")
            if rflag_raw and rflag_raw not in ("", "None"):
                try:
                    if isinstance(rflag_raw, str):
                        import json

                        rflag = json.loads(rflag_raw)
                    else:
                        rflag = rflag_raw
                    runway_months = _sf(rflag.get("runway_months"))
                    if burn_ttm is None:
                        burn_ttm = _sf(rflag.get("burn_ttm"))
                    has_revenue = str(rflag.get("has_revenue", "")).lower() in (
                        "true",
                        "1",
                    )
                except (ValueError, TypeError):
                    pass

        catalyst_days = _sf(row.get("catalyst_days"))
        catalyst_tier = row.get("catalyst_type_tier", "T5") or "T5"
        catalyst_event_type = (row.get("catalyst_event_type") or "").strip()
        market_cap_mm = _sf(row.get("market_cap_mm"))
        short_interest_pct = _sf(row.get("short_interest_pct"))
        financing_pressure = _sf(row.get("financing_pressure_score"))

        # Revenue/partnership detection
        if not has_revenue:
            has_revenue = str(row.get("has_revenue", "")).lower() in ("true", "1")
        has_commercial = str(row.get("has_commercial_quality", "")).lower() in (
            "true",
            "1",
        )
        # Also check if burn is negative (cash-flow positive)
        cash_positive = burn_ttm is not None and burn_ttm <= 0
        has_revenue_or_partner = has_revenue or has_commercial or cash_positive

        # Convert catalyst_days to months
        cat_months = _catalyst_months(catalyst_days)

        # Effective decisiveness for buffer calculation.
        # The global tier map assigns CT_PRIMARY_COMPLETION to T3 (calendar
        # milestone), but a Phase 3 primary completion IS a decisive event
        # for survivability purposes. Promote to T2 when phase indicates
        # a pivotal readout.
        effective_tier = catalyst_tier
        if catalyst_tier == "T3" and catalyst_event_type in (
            "CT_PRIMARY_COMPLETION",
            "CT_STUDY_COMPLETION",
        ):
            tier_dev = (row.get("tier_dev") or "").strip().upper()
            phase_raw = (row.get("phase") or row.get("catalyst_phase") or "").strip().lower()
            is_pivotal = (
                "phase 3" in phase_raw
                or "phase3" in phase_raw
                or "pivotal" in phase_raw
                or tier_dev in ("A", "B")  # A/B dev tiers are typically late-stage
            )
            if is_pivotal:
                effective_tier = "T2"

        # Two buffer paths:
        #   truth_buffer: uses effective_cat_months (T1/T2 decisive only)
        #   ev_buffer: uses actual cat_months (any tier — T3 conferences
        #     still matter for expectations, financing windows, sizing)

        # Truth gate path: non-decisive tiers get inflated horizon
        effective_cat_months = cat_months
        if cat_months is not None and not _is_decisive(effective_tier):
            effective_cat_months = max(cat_months, 12.0)

        if runway_months is not None and effective_cat_months is not None:
            truth_buffer = runway_months - effective_cat_months
        elif runway_months is not None:
            truth_buffer = runway_months - 12.0
        else:
            truth_buffer = None

        # EV/sizing path: uses actual catalyst timing
        if runway_months is not None and cat_months is not None:
            ev_buffer = runway_months - cat_months
        elif runway_months is not None:
            ev_buffer = runway_months - 12.0
        else:
            ev_buffer = None

        # Truth-gate severity (survivability question)
        truth_severity = compute_severity(
            runway_months=runway_months,
            catalyst_months=effective_cat_months,
            catalyst_tier=effective_tier,
            market_cap_mm=market_cap_mm,
            short_interest_pct=short_interest_pct,
            has_revenue_or_partner=has_revenue_or_partner,
            financing_pressure_score=financing_pressure,
        )

        # EV/sizing severity (financing damage question — uses actual timing)
        ev_severity = compute_ev_severity(
            runway_months=runway_months,
            actual_catalyst_months=cat_months,
            catalyst_tier=effective_tier,
            market_cap_mm=market_cap_mm,
            short_interest_pct=short_interest_pct,
            has_revenue_or_partner=has_revenue_or_partner,
            financing_pressure_score=financing_pressure,
        )

        # Layer outputs — each layer uses the appropriate severity
        # Truth gate: "can they survive to the catalyst?"
        financing_gate = truth_severity <= 0.92
        if not financing_gate and catalyst_days is not None and catalyst_days <= 60 and _is_decisive(effective_tier):
            financing_gate = True

        # EV and sizing: "what financing damage even if they do?"
        dilution_haircut = 0.35 * ev_severity
        size_mult = max(0.40, 1.0 - 0.60 * ev_severity)

        # Reported severity = truth severity (for gate decisions and bucket)
        severity = truth_severity

        # Decisiveness
        decisiveness = TIER_DECISIVENESS.get(effective_tier, 0.10)

        # Notes
        notes_parts: List[str] = []
        if runway_months is not None:
            notes_parts.append(f"runway {runway_months:.0f}mo")
        else:
            notes_parts.append("no runway data")
        tier_label = effective_tier if effective_tier == catalyst_tier else f"{effective_tier}<-{catalyst_tier}"
        if cat_months is not None:
            notes_parts.append(f"catalyst {cat_months:.0f}mo ({tier_label})")
        if truth_buffer is not None:
            notes_parts.append(f"buffer {truth_buffer:+.0f}mo")
        if ev_buffer is not None and ev_buffer != truth_buffer:
            notes_parts.append(f"ev_buffer {ev_buffer:+.0f}mo")
        if has_revenue_or_partner:
            notes_parts.append("revenue/partner backed")
        if not financing_gate:
            notes_parts.append("GATE FAIL")
        if severity > 0.70:
            notes_parts.append("elevated financing risk")

        return RunwaySeverityOverlay(
            ticker=ticker,
            as_of_date=as_of_date,
            months_to_cash_out=runway_months,
            months_to_next_decisive_catalyst=effective_cat_months,
            runway_buffer_months=truth_buffer,
            runway_severity_score=truth_severity,
            ev_severity_score=ev_severity,
            financing_truth_gate=financing_gate,
            dilution_haircut=dilution_haircut,
            size_multiplier=size_mult,
            catalyst_type_tier=effective_tier,
            catalyst_decisiveness=decisiveness,
            severity_bucket=_severity_bucket(severity),
            severity_notes="; ".join(notes_parts),
        )

    def score_batch(
        self,
        csv_rows: List[Dict[str, Any]],
        as_of_date: str,
    ) -> List[RunwaySeverityOverlay]:
        """Score all rows. Returns one overlay per row (same order)."""
        results = [self.score_row(row, as_of_date) for row in csv_rows]

        n = len(results)
        buckets = {}
        for r in results:
            buckets[r.severity_bucket] = buckets.get(r.severity_bucket, 0) + 1
        n_gate_fail = sum(1 for r in results if not r.financing_truth_gate)

        logger.info(
            "[RunwaySeverity] Scored %d tickers: %s | %d gate failures",
            n,
            " ".join(f"{k}={v}" for k, v in sorted(buckets.items())),
            n_gate_fail,
        )
        return results


# ═════════════════════════════════════════════════════════════════════════
# CSV enrichment (called from run_screen.py)
# ═════════════════════════════════════════════════════════════════════════

RUNWAY_SEVERITY_CSV_COLUMNS = [
    "runway_severity_score",
    "runway_buffer_months",
    "financing_truth_gate",
    "dilution_haircut",
    "size_multiplier",
    "severity_bucket",
    "severity_notes",
]


def enrich_csv_rows(
    csv_rows: List[Dict[str, Any]],
    as_of_date: str,
) -> List[RunwaySeverityOverlay]:
    """Compute runway severity and inject columns in-place.

    Returns the list of RunwaySeverityOverlay objects (for sidecar writing).
    """
    model = RunwaySeverityModel()
    overlays = model.score_batch(csv_rows, as_of_date)

    for row, ov in zip(csv_rows, overlays):
        row["runway_severity_score"] = ov.runway_severity_score
        row["runway_buffer_months"] = ov.runway_buffer_months
        row["financing_truth_gate"] = ov.financing_truth_gate
        row["dilution_haircut"] = ov.dilution_haircut
        row["size_multiplier"] = ov.size_multiplier
        row["severity_bucket"] = ov.severity_bucket
        row["severity_notes"] = ov.severity_notes

    return overlays
