"""Shared watchlist construction for model-relevant alert agents.

Centralizes the watchlist composition used by:
- `tools/build_price_action_watch.py` (daily EOD)
- `tools/build_intraday_mover_watch.py` (real-time intraday)

The watchlist is the union of:
    review queue + trade plan + shadow positions + catalyst delta + A-tier <=30d

capped at WATCHLIST_MAX and prioritized by `actionable_rank`.

Changing this module changes every alert agent's universe. Treat as stable.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any, Dict, Optional, Set, Tuple

WATCHLIST_MAX = 40


def _sf(val: Any) -> float:
    if val is None or val == "":
        return math.nan
    try:
        return float(val)
    except (ValueError, TypeError):
        return math.nan


def _load_json(path: Path) -> Optional[Dict]:
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _load_csv_tickers(path: Path) -> Set[str]:
    if not path.exists():
        return set()
    try:
        with open(path, encoding="utf-8") as f:
            return {row["ticker"] for row in csv.DictReader(f) if row.get("ticker")}
    except (KeyError, OSError):
        return set()


def build_model_relevant_watchlist(
    as_of_date: str,
    *,
    snapshots_dir: Path,
    artifacts_dir: Path,
    rankings: Dict[str, Dict[str, str]],
    max_size: int = WATCHLIST_MAX,
) -> Tuple[Set[str], Dict[str, int]]:
    """Build the canonical model-relevant watchlist for alert agents.

    Parameters
    ----------
    as_of_date : str   YYYY-MM-DD
    snapshots_dir : Path   data/snapshots root
    artifacts_dir : Path   artifacts/ root
    rankings : dict of ticker -> ranking row (as parsed from rankings.csv)
    max_size : int   cap; names over cap are pruned by actionable_rank

    Returns
    -------
    (watchlist, sources)
        watchlist : set of tickers
        sources   : dict with per-source counts (for artifact provenance)
    """
    snap_dir = snapshots_dir / as_of_date

    review_queue = _load_csv_tickers(snap_dir / "review_queue.csv")
    trade_plan = _load_csv_tickers(artifacts_dir / "live_shadow" / "trade_plan" / as_of_date / "trade_plan.csv")

    positions: Set[str] = set()
    pos_data = _load_json(artifacts_dir / "live_shadow" / "positions" / f"{as_of_date}.json")
    if pos_data:
        positions = {p["ticker"] for p in pos_data.get("positions", []) if p.get("ticker")}

    catalyst_delta: Set[str] = set()
    cd_data = _load_json(artifacts_dir / "catalyst_delta" / f"{as_of_date}_delta.json")
    if cd_data:
        catalyst_delta = {d["ticker"] for d in cd_data.get("deltas", []) if d.get("ticker")}

    a_near = {
        t
        for t, r in rankings.items()
        if r.get("tier_dev") == "A"
        and not math.isnan(_sf(r.get("catalyst_days", "")))
        and _sf(r.get("catalyst_days", "")) <= 30
    }

    watchlist = review_queue | trade_plan | positions | catalyst_delta | a_near
    watchlist = {t for t in watchlist if t in rankings}

    if len(watchlist) > max_size:
        ranked = sorted(watchlist, key=lambda t: _sf(rankings[t].get("actionable_rank", "9999")))
        watchlist = set(ranked[:max_size])

    sources = {
        "review_queue": len(review_queue),
        "trade_plan": len(trade_plan),
        "positions": len(positions),
        "catalyst_delta": len(catalyst_delta),
        "a_near": len(a_near),
    }
    return watchlist, sources
