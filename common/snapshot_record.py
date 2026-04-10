"""Typed snapshot record — structured alternative to CSV dict rows.

Provides a SnapshotRecord dataclass that carries typed fields instead
of raw CSV strings. New consumers can use this for type-safe access;
existing code continues to use csv_rows dicts unchanged.

Usage:
    from common.snapshot_record import SnapshotRecord, from_csv_row

    record = from_csv_row(csv_row_dict)
    print(record.ticker, record.final_score)  # typed, no float() needed
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class SnapshotRecord:
    """Typed representation of one row in rankings.csv."""

    # Identity
    ticker: str = ""
    company_name: str = ""

    # Ranking
    actionable_rank: Optional[int] = None
    composite_rank: Optional[int] = None
    composite_score: Optional[float] = None
    selector_score: Optional[float] = None
    final_score: Optional[float] = None
    ranker_adjustment: Optional[float] = None

    # Eligibility
    eligible: bool = False
    tier_dev: str = ""
    tier_commercial: str = ""
    archetype: str = ""

    # Clinical discriminators
    endpoint_strength_score: Optional[float] = None
    design_quality_score: Optional[float] = None
    execution_momentum: Optional[float] = None
    binary_quality_score: Optional[float] = None
    program_diversification: Optional[float] = None
    clinical_optionality_pct_dev: Optional[float] = None

    # Catalyst
    catalyst_days: Optional[int] = None
    catalyst_mode: str = ""
    catalyst_family: str = ""

    # Financial
    financial_score: Optional[float] = None
    severity: str = ""

    # Institutional
    coinvest_score_z: Optional[float] = None
    inst_delta_z: Optional[float] = None

    # Market
    close_price: Optional[float] = None
    market_cap_mm: Optional[float] = None
    short_interest_pct: Optional[float] = None
    priced_move_pct: Optional[float] = None

    # Options
    opt_atm_iv: Optional[float] = None
    straddle_price: Optional[float] = None
    implied_event_move: Optional[float] = None

    # Raw dict for fields not in the dataclass
    _extra: Dict[str, Any] = field(default_factory=dict, repr=False)


def _safe_float(val: Any) -> Optional[float]:
    if val is None or val == "":
        return None
    try:
        f = float(val)
        return None if f != f else f  # NaN check
    except (ValueError, TypeError):
        return None


def _safe_int(val: Any) -> Optional[int]:
    if val is None or val == "":
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


def from_csv_row(row: Dict[str, Any]) -> SnapshotRecord:
    """Convert a CSV dict row to a typed SnapshotRecord."""
    return SnapshotRecord(
        ticker=row.get("ticker", ""),
        company_name=row.get("company_name", ""),
        actionable_rank=_safe_int(row.get("actionable_rank")),
        composite_rank=_safe_int(row.get("composite_rank")),
        composite_score=_safe_float(row.get("composite_score")),
        selector_score=_safe_float(row.get("selector_score")),
        final_score=_safe_float(row.get("final_score")),
        ranker_adjustment=_safe_float(row.get("ranker_adjustment")),
        eligible=row.get("eligible", "") in ("1", "True", "true"),
        tier_dev=row.get("tier_dev", ""),
        tier_commercial=row.get("tier_commercial", ""),
        archetype=row.get("archetype", ""),
        endpoint_strength_score=_safe_float(row.get("endpoint_strength_score")),
        design_quality_score=_safe_float(row.get("design_quality_score")),
        execution_momentum=_safe_float(row.get("execution_momentum")),
        binary_quality_score=_safe_float(row.get("binary_quality_score")),
        program_diversification=_safe_float(row.get("program_diversification")),
        clinical_optionality_pct_dev=_safe_float(row.get("clinical_optionality_pct_dev")),
        catalyst_days=_safe_int(row.get("catalyst_days")),
        catalyst_mode=row.get("catalyst_mode", ""),
        catalyst_family=row.get("catalyst_family", ""),
        financial_score=_safe_float(row.get("financial_score")),
        severity=row.get("severity", ""),
        coinvest_score_z=_safe_float(row.get("coinvest_score_z")),
        inst_delta_z=_safe_float(row.get("inst_delta_z")),
        close_price=_safe_float(row.get("close_price")),
        market_cap_mm=_safe_float(row.get("market_cap_mm")),
        short_interest_pct=_safe_float(row.get("short_interest_pct")),
        priced_move_pct=_safe_float(row.get("priced_move_pct")),
        opt_atm_iv=_safe_float(row.get("opt_atm_iv")),
        straddle_price=_safe_float(row.get("straddle_price")),
        implied_event_move=_safe_float(row.get("implied_event_move")),
        _extra={k: v for k, v in row.items() if k not in _KNOWN_FIELDS},
    )


_KNOWN_FIELDS = {f.name for f in SnapshotRecord.__dataclass_fields__.values() if f.name != "_extra"}
