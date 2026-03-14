"""Historical event-move lookup table.

Provides empirical abs_gap distributions keyed by
(catalyst_family, phase_bucket, indication_bucket) for straddle
mispricing comparison.

The table is a research artifact — built deliberately from
build_event_move_table.py, not auto-rebuilt on every run.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List


def phase_bucket(phase_str: str) -> str:
    """Map lead_program_phase to a coarse bucket."""
    try:
        p = float(phase_str)
    except (ValueError, TypeError):
        return "unknown"
    if p >= 3:
        return "phase3"
    if p >= 2:
        return "phase2"
    return "early"


def indication_bucket(therapeutic_area: str) -> str:
    """Map therapeutic_area to a coarse indication bucket."""
    ta = (therapeutic_area or "").lower().strip()
    if ta == "oncology":
        return "oncology"
    if ta in ("rare_disease", "rare"):
        return "rare"
    return "other"


def compute_percentiles(values: List[float]) -> Dict[str, Any]:
    """Compute p25/p50/p75/p90 from a list of values."""
    clean = sorted(v for v in values if not math.isnan(v))
    n = len(clean)
    if n == 0:
        return {"n": 0, "p25": None, "p50": None, "p75": None, "p90": None}

    def _pct(p: float) -> float:
        idx = p * (n - 1)
        lo = int(idx)
        hi = min(lo + 1, n - 1)
        frac = idx - lo
        return round(clean[lo] * (1 - frac) + clean[hi] * frac, 6)

    confidence = "ok" if n >= 10 else "low_confidence" if n >= 5 else "insufficient"
    return {
        "n": n,
        "p25": _pct(0.25),
        "p50": _pct(0.50),
        "p75": _pct(0.75),
        "p90": _pct(0.90),
        "confidence": confidence,
    }


def build_table(
    rows: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """Build the event-move lookup table from enriched outcome rows.

    Args:
        rows: List of dicts with at least 'abs_gap', 'catalyst_family',
              'lead_program_phase', 'therapeutic_area'.

    Returns:
        Dict keyed by "family|phase|indication" with percentile stats.
    """
    from collections import defaultdict

    cells: Dict[str, List[float]] = defaultdict(list)

    for r in rows:
        gap = r.get("abs_gap")
        if gap is None or (isinstance(gap, float) and math.isnan(gap)):
            continue

        fam = r.get("catalyst_family", "") or "UNKNOWN"
        phase = phase_bucket(r.get("lead_program_phase", ""))
        ind = indication_bucket(r.get("therapeutic_area", ""))

        # Specific cell
        cells[f"{fam}|{phase}|{ind}"].append(gap)
        # Fallback: any indication
        cells[f"{fam}|{phase}|any"].append(gap)
        # Fallback: any phase
        cells[f"{fam}|any|any"].append(gap)
        # Global fallback
        cells["any|any|any"].append(gap)

    table = {}
    for key, vals in sorted(cells.items()):
        table[key] = compute_percentiles(vals)

    return table


def lookup_event_move(
    catalyst_family: str,
    catalyst_phase: str,
    indication: str,
    table: Dict[str, Dict[str, Any]],
    min_n: int = 10,
) -> Dict[str, Any]:
    """Look up historical event-move distribution with fallback hierarchy.

    Fallback order:
        1. (family, phase, indication)
        2. (family, phase, any)
        3. (family, any, any)
        4. (any, any, any)

    Returns the first cell with n >= min_n, or the global fallback.
    """
    keys = [
        f"{catalyst_family}|{catalyst_phase}|{indication}",
        f"{catalyst_family}|{catalyst_phase}|any",
        f"{catalyst_family}|any|any",
        "any|any|any",
    ]

    for key in keys:
        cell = table.get(key)
        if cell and cell.get("n", 0) >= min_n:
            return {**cell, "lookup_key": key, "fallback": key != keys[0]}

    # Last resort: global with low confidence
    global_cell = table.get("any|any|any", {})
    return {
        **global_cell,
        "lookup_key": "any|any|any",
        "fallback": True,
        "confidence": "low_confidence",
    }
