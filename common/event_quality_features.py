"""Event Quality Features — per-family quality decomposition for binary catalysts.

Produces family-specific quality columns that complement the composite
binary_quality_score.  These are **passive** (informational only, no ranking
change) and intended for downstream return-attribution analysis.

Columns added:
  regulatory_quality  — 0–1 score for REGULATORY events (ADCOM, source, timing)
  clinical_quality    — 0–1 score for CLINICAL events (phase, design, program depth)
  has_adcom           — 1 if any ADCOM event contributes to the catalyst, else 0
  single_asset_risk   — 1 if program_count == 1 (binary concentrated), else 0

Usage:
    from common.event_quality_features import compute_event_quality_features
    features = compute_event_quality_features(row)
    row.update(features)
"""

from __future__ import annotations

from typing import Any, Dict

# ---------------------------------------------------------------------------
# Regulatory quality components
# ---------------------------------------------------------------------------

_REG_EVENT_SCORE: Dict[str, float] = {
    "PDUFA": 1.0,
    "FDA_PDUFA_DATE": 1.0,
    "FDA_ADCOM": 0.95,
    "FDA_DECISION": 0.90,
    "FDA_APPROVAL": 0.85,
    "EMA_AGENDA": 0.80,
    "EMA_OUTCOME": 0.80,
    "EMA_COMMITTEE_AGENDA": 0.75,
    "EMA_COMMITTEE_OUTCOME": 0.75,
    "FDA_SUBMISSION": 0.50,
    "FDA_DESIGNATION": 0.40,
    "FDA_CRL": 0.30,
    "FDA_RTF": 0.25,
}

_REG_SOURCE_SCORE: Dict[str, float] = {
    "SEC_8K_FILING": 1.0,
    "PDUFA_MANUAL": 0.95,
    "FDA_FEDREG": 0.90,
    "FDA_ADCOM": 0.90,
    "CTGOV_CALENDAR": 0.50,
}

_ADCOM_EVENT_TYPES = frozenset({"FDA_ADCOM"})


def _regulatory_quality(event_type: str, source: str) -> float:
    """Score regulatory catalyst quality [0, 1].

    Components:
      0.60 * event_type score (PDUFA > ADCOM > EMA > submission)
      0.40 * source reliability (SEC 8-K > manual > Fed Register > CTgov)
    """
    evt = _REG_EVENT_SCORE.get(event_type, 0.3)
    src = _REG_SOURCE_SCORE.get(source, 0.4)
    return round(0.60 * evt + 0.40 * src, 4)


# ---------------------------------------------------------------------------
# Clinical quality components
# ---------------------------------------------------------------------------

_CLIN_EVENT_SCORE: Dict[str, float] = {
    "DATA_READOUT": 0.90,
    "CT_DATE_CONFIRMED_ACTUAL": 0.85,
    "DATA_PRESENTATION": 0.80,
    "CT_PRIMARY_COMPLETION": 0.65,
    "CT_STUDY_COMPLETION": 0.50,
    "CT_RESULTS_POSTED": 0.45,
    "DATA_PUBLICATION": 0.40,
    "CT_TIMELINE_PULLIN": 0.35,
    "CT_STATUS_UPGRADE": 0.30,
}

_PHASE_SCORE: Dict[float, float] = {
    3.0: 1.0,
    2.5: 0.80,
    2.0: 0.55,
    1.5: 0.35,
    1.0: 0.15,
}


def _safe_float(v: Any, default: float = 0.0) -> float:
    if v is None or v == "":
        return default
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


def _clinical_quality(
    event_type: str,
    phase_str: str,
    design_quality: str,
    program_count_str: str,
) -> float:
    """Score clinical catalyst quality [0, 1].

    Components:
      0.30 * event_type (DATA_READOUT > PCD > completion)
      0.30 * phase (phase 3 > 2 > 1)
      0.20 * design_quality (reused from calendar alpha v2)
      0.20 * program depth (multi-program > single)
    """
    evt = _CLIN_EVENT_SCORE.get(event_type, 0.3)

    phase_val = _safe_float(phase_str, 0.0)
    phase = _PHASE_SCORE.get(phase_val, 0.3)

    design = _safe_float(design_quality, 0.3)
    design = max(0.0, min(1.0, design))

    prog = _safe_float(program_count_str, 1.0)
    # multi-program: more diversified, lower single-name risk
    depth = min(1.0, prog / 5.0) if prog > 0 else 0.0

    return round(0.30 * evt + 0.30 * phase + 0.20 * design + 0.20 * depth, 4)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# Columns produced by compute_event_quality_features
EVENT_QUALITY_COLUMNS = [
    "regulatory_quality",
    "clinical_quality",
    "has_adcom",
    "single_asset_risk",
]


def compute_event_quality_features(row: Dict[str, Any]) -> Dict[str, Any]:
    """Compute per-family quality features from a rankings row.

    Returns a dict with EVENT_QUALITY_COLUMNS keys.
    """
    family = str(row.get("catalyst_family", "") or "")
    event_type = str(row.get("catalyst_event_type", "") or "")
    source = str(row.get("catalyst_source", "") or "")
    phase_str = str(row.get("lead_program_phase", "") or "")
    design_str = str(row.get("design_quality_score", "") or "")
    prog_str = str(row.get("program_count", "") or "")

    # Regulatory quality (only meaningful for REGULATORY family)
    reg_q = _regulatory_quality(event_type, source) if family == "REGULATORY" else 0.0

    # Clinical quality (only meaningful for CLINICAL family)
    clin_q = _clinical_quality(event_type, phase_str, design_str, prog_str) if family == "CLINICAL" else 0.0

    # ADCOM flag: is the nearest event an ADCOM?
    has_adcom = 1 if event_type in _ADCOM_EVENT_TYPES else 0

    # Single-asset risk: company has only 1 clinical program
    prog_count = _safe_float(prog_str, 0.0)
    single_asset = 1 if prog_count == 1 else 0

    return {
        "regulatory_quality": reg_q,
        "clinical_quality": clin_q,
        "has_adcom": has_adcom,
        "single_asset_risk": single_asset,
    }
