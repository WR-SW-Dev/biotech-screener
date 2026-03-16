"""Clinical PoS prior v2 loader and lookup (Spec 023/024).

Provides universe-specific empirical clinical priors from
clinical_pos_priors_v2.json with deterministic fallback to
Wong et al. reference rates when v2 is unavailable or thin.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Wong et al. reference priors (fallback)
WONG_PHASE_PRIORS = {
    "phase1": 0.066,
    "phase1_2": 0.15,
    "phase2": 0.305,
    "phase2_3": 0.40,
    "phase3": 0.580,
    "phase4": 0.650,
}

# Maximum staleness before falling back (days)
MAX_STALE_DAYS = 180

# Minimum support to use v2 rate
MIN_N_FOR_V2 = 10

_V2_CACHE: Optional[Dict[str, Any]] = None


def _load_v2(prior_path: Path) -> Optional[Dict[str, Any]]:
    """Load and validate v2 prior artifact. Returns None on failure."""
    global _V2_CACHE
    if _V2_CACHE is not None:
        return _V2_CACHE

    if not prior_path.exists():
        return None

    try:
        data = json.loads(prior_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None

    if data.get("schema") != "clinical_pos_priors.v2":
        return None

    _V2_CACHE = data
    return data


def _is_stale(v2: Dict[str, Any], as_of: Optional[str] = None) -> bool:
    """Check if v2 artifact is too old."""
    built = v2.get("built_as_of", "")
    if not built:
        return True
    try:
        built_date = date.fromisoformat(built)
        ref = date.fromisoformat(as_of) if as_of else date.today()
        return (ref - built_date).days > MAX_STALE_DAYS
    except (ValueError, TypeError):
        return True


def get_clinical_pos_prior(
    phase: str,
    endpoint_class: str = "other",
    prior_path: Path = Path("production_data") / "clinical_pos_priors_v2.json",
    as_of_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Look up empirical PoS prior for this phase and endpoint.

    Falls back to Wong et al. if v2 is missing, stale, or has thin support.

    Returns:
        pos_prior: float — base rate to use
        pos_prior_source: str — "v2_empirical" or "wong_fallback"
        pos_prior_phase: str
        pos_prior_n: int — sample size backing the v2 rate (0 if fallback)
        pos_prior_endpoint_modifier: float
        pos_prior_value_raw: float — phase prior before endpoint modifier
    """
    result = {
        "pos_prior": 0.0,
        "pos_prior_source": "wong_fallback",
        "pos_prior_phase": phase,
        "pos_prior_n": 0,
        "pos_prior_endpoint_modifier": 0.0,
        "pos_prior_value_raw": 0.0,
    }

    # Normalize phase
    phase_norm = phase.lower().replace(" ", "").replace("/", "_")
    phase_map = {
        "phase1": "phase1",
        "phase2": "phase2",
        "phase3": "phase3",
        "phase4": "phase4",
        "phase1_2": "phase1_2",
        "phase1_phase2": "phase1_2",
        "phase2_3": "phase2_3",
        "phase2_phase3": "phase2_3",
    }
    phase_key = phase_map.get(phase_norm, phase_norm)

    # Try v2
    v2 = _load_v2(prior_path)
    if v2 and not _is_stale(v2, as_of_date):
        phase_entry = v2.get("by_phase", {}).get(phase_key)
        if phase_entry and phase_entry.get("n", 0) >= MIN_N_FOR_V2:
            base = phase_entry.get("shrunk_rate", phase_entry.get("raw_rate", 0))

            # Endpoint modifier
            ep_mod = 0.0
            ep_key = "overall_survival" if endpoint_class == "overall_survival" else "other"
            ep_entry = v2.get("endpoint_modifiers", {}).get(ep_key)
            if ep_entry and ep_entry.get("n", 0) >= MIN_N_FOR_V2:
                ep_mod = ep_entry.get("shrunk_delta", 0.0)

            prior = max(0.01, min(0.99, base + ep_mod))
            result["pos_prior"] = round(prior, 4)
            result["pos_prior_source"] = "v2_empirical"
            result["pos_prior_n"] = phase_entry.get("n", 0)
            result["pos_prior_endpoint_modifier"] = round(ep_mod, 4)
            result["pos_prior_value_raw"] = round(base, 4)
            return result

    # Fallback to Wong
    wong_rate = WONG_PHASE_PRIORS.get(phase_key, 0.10)
    result["pos_prior"] = round(wong_rate, 4)
    result["pos_prior_value_raw"] = round(wong_rate, 4)
    return result


def enrich_row_with_pos_prior(
    row: dict,
    prior_path: Path = Path("production_data") / "clinical_pos_priors_v2.json",
    as_of_date: Optional[str] = None,
) -> None:
    """Add PoS prior diagnostic fields to a rankings row (in-place)."""
    # Determine phase from row
    phase = ""
    m4_scores = row.get("_m4_scores", {})
    if m4_scores and isinstance(m4_scores, dict):
        phase = m4_scores.get("lead_phase", "")
    if not phase:
        # Fallback: try to infer from clinical_score or archetype
        phase = row.get("_lead_phase", "")

    endpoint = row.get("_endpoint_class", "other")

    prior = get_clinical_pos_prior(phase, endpoint, prior_path, as_of_date)

    row["pos_prior_source"] = prior["pos_prior_source"]
    row["pos_prior_phase"] = prior["pos_prior_phase"]
    row["pos_prior_value_v2"] = str(prior["pos_prior"]) if prior["pos_prior_source"] == "v2_empirical" else ""
    row["pos_prior_endpoint_modifier"] = (
        str(prior["pos_prior_endpoint_modifier"]) if prior["pos_prior_endpoint_modifier"] else ""
    )
    row["pos_prior_n"] = str(prior["pos_prior_n"]) if prior["pos_prior_n"] else ""
