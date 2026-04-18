"""Shared PIT 13F cache resolver.

Single canonical resolver used by both the institutional_summary builder and
the coinvest features builder. Backward-only lookup preserves point-in-time
correctness — a target date never sees a cache dated after it.
"""

from __future__ import annotations

import json
import logging
from datetime import date as _date
from datetime import timedelta as _td
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

PIT_INDEX_SCHEMA_VERSION = "sec_13f_pit_index.v1"


def _load_index(path: Path) -> Optional[dict]:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def resolve_pit_cache_dir(
    base: Path,
    as_of_date: str,
    nearest_prior_days: int,
) -> Tuple[Optional[Path], str]:
    """Resolve the PIT 13F cache dir for a date with nearest-prior fallback.

    Policy:
      1. Exact-match at base/{as_of_date}/index.json wins if present and valid.
      2. Else, if nearest_prior_days > 0, scan back day-by-day up to that
         many days looking for a cache dir whose index.json exists and has
         the expected schema. First hit wins.
      3. Else, return (None, "no_cache").

    The lookup is backward-only: a target date never resolves to a cache
    dated after it, which preserves PIT correctness (a 13F filing dated after
    the target never enters the current state).

    Returns (cache_dir, source_tag) where source_tag is one of:
      - "exact"           : exact as_of_date match
      - "prior_{ISO}"     : nearest-prior match (ISO = actual cache date)
      - "no_cache"        : no usable cache within the lookback window
    """
    exact = base / as_of_date
    if (exact / "index.json").exists():
        idx = _load_index(exact / "index.json")
        if idx is not None and idx.get("schema_version") == PIT_INDEX_SCHEMA_VERSION:
            return exact, "exact"

    if nearest_prior_days <= 0:
        return None, "no_cache"

    try:
        target = _date.fromisoformat(as_of_date)
    except (ValueError, TypeError):
        return None, "no_cache"

    for delta in range(1, nearest_prior_days + 1):
        candidate_date = (target - _td(days=delta)).isoformat()
        candidate_dir = base / candidate_date
        candidate_idx = candidate_dir / "index.json"
        if not candidate_idx.exists():
            continue
        idx = _load_index(candidate_idx)
        if idx is None:
            continue
        if idx.get("schema_version") != PIT_INDEX_SCHEMA_VERSION:
            continue
        return candidate_dir, f"prior_{candidate_date}"

    return None, "no_cache"
